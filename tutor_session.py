#!/usr/bin/env python3
"""Host-owned lifecycle and authenticated local bridge for Screen Tutor.

This module has no capture or provider dependency.  Native code supplies a
user-selected source and frames; the host enforces source identity, epochs,
bounds, Stop, and bridge replay rules before those bytes can be forwarded.
"""

import hashlib
import hmac
import json
import secrets
import threading
from collections import deque
from dataclasses import dataclass

import tutor_contracts as contracts


MAX_FRAMES = 3
MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_BUFFER_BYTES = 64 * 1024 * 1024


class SessionRefusal(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectedSource:
    source_id: str
    source_kind: str
    source_revision: str
    native_handle_digest: str


@dataclass
class _Frame:
    frame_id: str
    source_id: str
    source_revision: str
    capture_epoch: int
    captured_at_monotonic_ms: int
    content: bytearray

    @property
    def digest(self):
        return hashlib.sha256(self.content).hexdigest()

    def dispose(self):
        self.content[:] = b"\x00" * len(self.content)


class TutorSession:
    """One selected-source session; foreground changes never change selection."""

    def __init__(self, session_id, user_id, tenant_id, project_id,
                 allowed_source_ids=()):
        for value, name in ((session_id, "session_id"), (user_id, "user_id"),
                            (tenant_id, "tenant_id"), (project_id, "project_id")):
            contracts._ident(value, name)
        self.session_id = session_id
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.allowed_source_ids = frozenset(allowed_source_ids)
        self.state = "DORMANT"
        self.capture_epoch = 0
        self.bridge_epoch = 0
        self.cancellation_generation = 0
        self.source = None
        self._frames = deque()
        self._bytes = 0
        self._lock = threading.RLock()
        self._diagnostics = []

    def _transition(self, event, proposed):
        verdict = contracts.validate_session_transition(self.state, event, proposed)
        if not verdict["allowed"]:
            raise SessionRefusal(verdict["reason_code"])
        self.state = proposed

    def invoke(self):
        with self._lock:
            self._transition("INVOKE", "SELECTING")

    def select_source(self, source, *, native_capture_epoch=None):
        if not isinstance(source, SelectedSource):
            raise SessionRefusal("source must be host-selected")
        contracts._ident(source.source_id, "source_id")
        contracts._enum(source.source_kind, "source_kind", contracts.SOURCE_KINDS)
        contracts._ident(source.source_revision, "source_revision")
        if not contracts.SHA256.fullmatch(source.native_handle_digest):
            raise SessionRefusal("invalid native handle digest")
        with self._lock:
            if self.allowed_source_ids and source.source_id not in self.allowed_source_ids:
                raise SessionRefusal("source is outside the grant")
            if self.state not in ("SELECTING", "SOURCE_UNAVAILABLE"):
                raise SessionRefusal("source selection is unavailable in this state")
            next_epoch = self.capture_epoch + 1
            if native_capture_epoch is not None:
                contracts._integer(native_capture_epoch, "native_capture_epoch", 1)
                if native_capture_epoch <= self.capture_epoch:
                    raise SessionRefusal("native source epoch is stale")
                next_epoch = native_capture_epoch
            self._dispose_frames()
            self.capture_epoch = next_epoch
            self.cancellation_generation += 1
            self.source = source
            self._transition("SELECT_SOURCE", "READY")
            self._diagnostics.append({"event": "source_selected",
                                      "source_id": source.source_id,
                                      "capture_epoch": self.capture_epoch})

    def add_frame(self, frame_id, source_id, source_revision, capture_epoch,
                  captured_at_monotonic_ms, content):
        contracts._ident(frame_id, "frame_id")
        if not isinstance(content, bytes) or not content or len(content) > MAX_FRAME_BYTES:
            raise SessionRefusal("frame bytes are invalid or oversized")
        with self._lock:
            if self.state not in ("READY", "OBSERVING") or self.source is None:
                raise SessionRefusal("capture is not active")
            if (source_id != self.source.source_id
                    or source_revision != self.source.source_revision
                    or capture_epoch != self.capture_epoch):
                raise SessionRefusal("stale or foreign source frame")
            while self._frames and (len(self._frames) >= MAX_FRAMES
                                    or self._bytes + len(content) > MAX_BUFFER_BYTES):
                old = self._frames.popleft(); self._bytes -= len(old.content); old.dispose()
            if self._bytes + len(content) > MAX_BUFFER_BYTES:
                raise SessionRefusal("frame buffer capacity exceeded")
            frame = _Frame(frame_id, source_id, source_revision, capture_epoch,
                           contracts._integer(captured_at_monotonic_ms,
                                              "captured_at_monotonic_ms"),
                           bytearray(content))
            self._frames.append(frame); self._bytes += len(content)
            return {"frame_id": frame_id, "source_id": source_id,
                    "source_revision": source_revision, "capture_epoch": capture_epoch,
                    "content_sha256": frame.digest, "size_bytes": len(content)}

    def frame_bytes(self, frame_id, source_id, capture_epoch):
        """Return a private copy only after current source/epoch checks."""
        with self._lock:
            if self.source is None or source_id != self.source.source_id or capture_epoch != self.capture_epoch:
                raise SessionRefusal("stale or foreign frame read")
            for frame in self._frames:
                if frame.frame_id == frame_id:
                    return bytes(frame.content)
        raise SessionRefusal("frame unavailable")

    def pause(self):
        with self._lock:
            if self.state == "READY":
                self._transition("PAUSE", "PAUSED")
            elif self.state not in ("PAUSED", "CLOSED"):
                raise SessionRefusal("pause unavailable")
            self.cancellation_generation += 1
            self._dispose_frames()

    def resume(self):
        with self._lock:
            self._transition("RESUME", "READY")

    def source_unavailable(self, reason):
        with self._lock:
            if self.state == "CLOSED":
                return False
            if self.state not in ("READY", "OBSERVING", "PAUSED"):
                raise SessionRefusal("source loss is unavailable in this state")
            self._transition("SOURCE_LOST", "SOURCE_UNAVAILABLE")
            self.cancellation_generation += 1
            self.capture_epoch += 1
            self.source = None
            self._dispose_frames()
            self._diagnostics.append({"event": "source_unavailable",
                                      "reason": str(reason)[:256]})
            return True

    def reconnect(self):
        with self._lock:
            self.bridge_epoch += 1
            self.cancellation_generation += 1
            self._dispose_frames()
            return self.bridge_epoch

    def stop(self):
        """Immediate local Stop: invalidate work and wipe transient frames."""
        with self._lock:
            if self.state == "CLOSED":
                return False
            if self.state != "STOPPING":
                if self.state in ("READY", "OBSERVING", "THINKING", "PRESENTING"):
                    self._transition("STOP", "STOPPING")
                else:
                    self.state = "STOPPING"
            self.cancellation_generation += 1
            self.capture_epoch += 1
            self.source = None
            self._dispose_frames()
            self._transition("STOPPED", "CLOSED")
            self._diagnostics.append({"event": "stopped"})
            return True

    def _dispose_frames(self):
        while self._frames:
            self._frames.popleft().dispose()
        self._bytes = 0

    def diagnostics(self):
        """Content-free diagnostics suitable for bounded persistence."""
        with self._lock:
            return json.loads(json.dumps(self._diagnostics[-64:]))

    @property
    def buffer_status(self):
        with self._lock:
            return {"frames": len(self._frames), "bytes": self._bytes}


class AuthenticatedLocalBridge:
    """Session/peer/epoch/sequence authentication above an owner-only pipe."""

    def __init__(self, session, host_secret=None):
        if not isinstance(session, TutorSession):
            raise TypeError("session required")
        self.session = session
        self._secret = host_secret or secrets.token_bytes(32)
        if not isinstance(self._secret, bytes) or len(self._secret) < 32:
            raise ValueError("host secret must contain at least 32 bytes")
        self._channels = {}
        self._lock = threading.RLock()

    def open_channel(self, client_id, peer_identity, expires_at_monotonic_ms):
        contracts._ident(client_id, "client_id"); contracts._ident(peer_identity, "peer_identity")
        expiry = contracts._integer(expires_at_monotonic_ms, "expires_at_monotonic_ms", 1)
        nonce = secrets.token_hex(16)
        body = {"client_id": client_id, "peer_identity": peer_identity,
                "session_id": self.session.session_id, "bridge_epoch": self.session.bridge_epoch,
                "expires_at_monotonic_ms": expiry, "nonce": nonce}
        encoded = contracts.canonical_json(body).encode("ascii")
        token = hmac.new(self._secret, encoded, hashlib.sha256).hexdigest()
        with self._lock:
            self._channels[token] = {**body, "last_sequence": 0, "replays": {}}
        return token

    def receive(self, token, peer_identity, sequence, bridge_epoch,
                now_monotonic_ms, wire_payload):
        """Authenticate envelope before decoding any model-visible payload."""
        with self._lock:
            channel = self._channels.get(token)
            if channel is None or not hmac.compare_digest(channel["peer_identity"], peer_identity):
                raise SessionRefusal("unauthenticated peer")
            if bridge_epoch != self.session.bridge_epoch or bridge_epoch != channel["bridge_epoch"]:
                raise SessionRefusal("stale bridge epoch")
            now = contracts._integer(now_monotonic_ms, "now_monotonic_ms")
            if now >= channel["expires_at_monotonic_ms"]:
                raise SessionRefusal("expired bridge channel")
            seq = contracts._integer(sequence, "sequence", 1)
            digest = hashlib.sha256(wire_payload if isinstance(wire_payload, bytes)
                                    else str(wire_payload).encode("utf-8")).hexdigest()
            prior = channel["replays"].get(seq)
            if prior is not None:
                if prior != digest:
                    raise SessionRefusal("conflicting sequence replay")
                return {"payload": None, "idempotent_replay": True}
            if seq != channel["last_sequence"] + 1:
                raise SessionRefusal("out-of-order sequence")
            payload = contracts.decode_wire(wire_payload)
            channel["last_sequence"] = seq
            channel["replays"][seq] = digest
            return {"payload": payload, "idempotent_replay": False}
