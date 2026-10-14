#!/usr/bin/env python3
"""Authorized, bounded and modality-honest temporal media index.

The index accepts only bytes/captions already obtained by an authorized adapter.
It contains no downloader, URL opener, browser or model client.  Evidence is
recorded under immutable content and timeline epochs; plans are requests for
evidence and never become processed coverage until bytes/text are ingested.
"""

import copy
import hashlib
import json
import math
import re


SOURCE_SCHEMA = "tutor.media-source/1"
INDEX_SCHEMA = "tutor.media-index/1"
ACCESS_METHODS = ("UPLOAD", "AUTHORIZED_URL", "CURRENT_SCREEN")
RIGHTS = ("PERMITTED", "DENIED", "REVOKED")
TRANSITIONS = ("SCENE", "AD_START", "AD_END", "SOURCE_CHANGE")
CAPTION_STATES = ("RAW", "CONTESTED", "CORRECTED")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$")
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_DURATION_MS = 8 * 60 * 60 * 1000
MAX_CAPTION_CHARS = 12_000
MAX_RECORDS = 4096
MAX_REQUEST_BUDGET = 256


class MediaRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {name}")
    return value


def _integer(value, name, low=0, high=2**63 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {name}")
    return value


def _digest(value, name):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {name}")
    return value


def _locale(value, name):
    if not isinstance(value, str) or not LOCALE.fullmatch(value):
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {name}")
    return value


def _interval(value, duration_ms, where="interval"):
    _exact(value, ("start_ms", "end_ms"), where)
    start = _integer(value["start_ms"], "start_ms", 0, duration_ms)
    end = _integer(value["end_ms"], "end_ms", 1, duration_ms)
    if end <= start:
        raise MediaRefused("INVALID_MEDIA_RECORD", f"invalid {where} bounds")
    return start, end


def validate_source(value):
    value = copy.deepcopy(value)
    _exact(value, ("schema", "media_id", "source_revision", "tenant_id",
                   "project_id", "access_method", "locator_ref", "content_sha256",
                   "byte_limit", "duration_ms", "rights", "allowed_intervals",
                   "expires_at_monotonic_ms"), "media source")
    if value["schema"] != SOURCE_SCHEMA or value["access_method"] not in ACCESS_METHODS:
        raise MediaRefused("INVALID_MEDIA_RECORD", "source schema or access method")
    for field in ("media_id", "source_revision", "tenant_id", "project_id", "locator_ref"):
        _ident(value[field], field)
    _digest(value["content_sha256"], "content_sha256")
    _integer(value["byte_limit"], "byte_limit", 1, MAX_SOURCE_BYTES)
    duration = _integer(value["duration_ms"], "duration_ms", 1, MAX_DURATION_MS)
    if value["rights"] not in RIGHTS:
        raise MediaRefused("INVALID_MEDIA_RECORD", "invalid rights")
    intervals = value["allowed_intervals"]
    if not isinstance(intervals, list) or not intervals or len(intervals) > 128:
        raise MediaRefused("INVALID_MEDIA_RECORD", "allowed intervals required")
    checked = [_interval(item, duration, "allowed interval") for item in intervals]
    if checked != sorted(checked) or any(checked[i][0] < checked[i - 1][1]
                                         for i in range(1, len(checked))):
        raise MediaRefused("INVALID_MEDIA_RECORD", "allowed intervals overlap or are unordered")
    expiry = value["expires_at_monotonic_ms"]
    if expiry is not None:
        _integer(expiry, "expires_at_monotonic_ms", 1)
    return value


def source_access(value, now_monotonic_ms):
    source = validate_source(value)
    _integer(now_monotonic_ms, "now_monotonic_ms")
    if source["rights"] != "PERMITTED":
        return {"available": False, "reason": "RIGHTS_" + source["rights"]}
    expiry = source["expires_at_monotonic_ms"]
    if expiry is not None and now_monotonic_ms >= expiry:
        return {"available": False, "reason": "SOURCE_EXPIRED"}
    return {"available": True, "reason": "AUTHORIZED"}


class MediaIndex:
    """In-memory evidence ledger for one exact authorized media revision."""

    def __init__(self, source, now_monotonic_ms, request_budget, clock_ms=None):
        self.source = validate_source(source)
        self._clock_ms = clock_ms or (lambda: now_monotonic_ms)
        access = source_access(self.source, now_monotonic_ms)
        if not access["available"]:
            raise MediaRefused("MEDIA_UNAVAILABLE", access["reason"])
        self.request_budget = _integer(request_budget, "request_budget", 1,
                                       MAX_REQUEST_BUDGET)
        self.timeline_epoch = 0
        self.content_epoch = 0
        self.playback_ms = 0
        self.playback_rate = 1.0
        self.captions = []
        self.frames = []
        self.gaps = []
        self.transitions = []
        self.retrieval_decisions = []
        self._requested = set()

    def _ensure_available(self):
        access = source_access(self.source, self._clock_ms())
        if not access["available"]:
            raise MediaRefused("MEDIA_UNAVAILABLE", access["reason"])

    def _current(self, source_revision, content_sha256, timeline_epoch):
        self._ensure_available()
        if (source_revision != self.source["source_revision"]
                or content_sha256 != self.source["content_sha256"]
                or timeline_epoch != self.timeline_epoch):
            raise MediaRefused("STALE_MEDIA", "content or timeline identity changed")

    def _allowed(self, start_ms, end_ms):
        duration = self.source["duration_ms"]
        if (isinstance(start_ms, bool) or isinstance(end_ms, bool)
                or not isinstance(start_ms, int) or not isinstance(end_ms, int)
                or start_ms < 0 or end_ms <= start_ms or end_ms > duration):
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid evidence interval")
        if not any(row["start_ms"] <= start_ms and end_ms <= row["end_ms"]
                   for row in self.source["allowed_intervals"]):
            raise MediaRefused("RIGHTS_DENIED", "evidence interval is outside allowed range")

    def _bounded(self):
        if sum(map(len, (self.captions, self.frames, self.gaps,
                         self.transitions, self.retrieval_decisions))) >= MAX_RECORDS:
            raise MediaRefused("MEDIA_INDEX_LIMIT", "media evidence ledger is full")

    def ingest_caption(self, caption_id, start_ms, end_ms, text, language,
                       provenance_ref, state, source_revision, content_sha256,
                       timeline_epoch):
        self._bounded()
        self._current(source_revision, content_sha256, timeline_epoch)
        self._allowed(start_ms, end_ms)
        _ident(caption_id, "caption_id"); _ident(provenance_ref, "provenance_ref")
        _locale(language, "language")
        if state not in CAPTION_STATES or not isinstance(text, str) \
                or not text.strip() or len(text) > MAX_CAPTION_CHARS:
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid caption")
        if any(row["caption_id"] == caption_id for row in self.captions):
            raise MediaRefused("INVALID_MEDIA_RECORD", "duplicate caption identity")
        self.captions.append({
            "caption_id": caption_id, "start_ms": start_ms, "end_ms": end_ms,
            "text": text, "language": language, "provenance_ref": provenance_ref,
            "state": state, "content_epoch": self.content_epoch,
            "timeline_epoch": self.timeline_epoch,
            "source_revision": source_revision, "content_sha256": content_sha256,
        })

    def ingest_frame(self, frame_id, timestamp_ms, encoded_bytes, mime,
                     provenance_ref, source_revision, content_sha256,
                     timeline_epoch):
        self._bounded()
        self._current(source_revision, content_sha256, timeline_epoch)
        _integer(timestamp_ms, "timestamp_ms", 0, self.source["duration_ms"] - 1)
        if not any(row["start_ms"] <= timestamp_ms < row["end_ms"]
                   for row in self.source["allowed_intervals"]):
            raise MediaRefused("RIGHTS_DENIED", "frame timestamp is outside allowed range")
        _ident(frame_id, "frame_id"); _ident(provenance_ref, "provenance_ref")
        if mime not in ("image/png", "image/jpeg", "application/x-test-frame"):
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid frame media type")
        if not isinstance(encoded_bytes, (bytes, bytearray, memoryview)):
            raise MediaRefused("INVALID_MEDIA_RECORD", "frame requires retrieved bytes")
        raw = bytes(encoded_bytes)
        if not raw or len(raw) > self.source["byte_limit"]:
            raise MediaRefused("INVALID_MEDIA_RECORD", "frame bytes exceed source limit")
        if any(row["frame_id"] == frame_id for row in self.frames):
            raise MediaRefused("INVALID_MEDIA_RECORD", "duplicate frame identity")
        self.frames.append({
            "frame_id": frame_id, "timestamp_ms": timestamp_ms, "mime": mime,
            "byte_count": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "provenance_ref": provenance_ref, "content_epoch": self.content_epoch,
            "timeline_epoch": self.timeline_epoch,
            "source_revision": source_revision, "content_sha256": content_sha256,
        })

    def record_gap(self, gap_id, start_ms, end_ms, modality, reason,
                   timeline_epoch):
        self._ensure_available()
        self._bounded()
        if timeline_epoch != self.timeline_epoch:
            raise MediaRefused("STALE_MEDIA", "gap belongs to another timeline")
        self._allowed(start_ms, end_ms)
        _ident(gap_id, "gap_id"); _ident(reason, "reason")
        if modality not in ("CAPTION", "AUDIO", "FRAME", "ALL"):
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid gap modality")
        if any(row["gap_id"] == gap_id for row in self.gaps):
            raise MediaRefused("INVALID_MEDIA_RECORD", "duplicate gap identity")
        self.gaps.append({"gap_id": gap_id, "start_ms": start_ms,
                          "end_ms": end_ms, "modality": modality,
                          "reason": reason, "timeline_epoch": self.timeline_epoch,
                          "content_epoch": self.content_epoch})

    def record_transition(self, transition_id, at_ms, kind, timeline_epoch):
        self._ensure_available()
        self._bounded()
        if timeline_epoch != self.timeline_epoch:
            raise MediaRefused("STALE_MEDIA", "transition belongs to another timeline")
        _ident(transition_id, "transition_id")
        _integer(at_ms, "at_ms", 0, self.source["duration_ms"])
        if kind not in TRANSITIONS:
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid transition kind")
        if any(row["transition_id"] == transition_id for row in self.transitions):
            raise MediaRefused("INVALID_MEDIA_RECORD", "duplicate transition identity")
        self.transitions.append({"transition_id": transition_id, "at_ms": at_ms,
                                 "kind": kind, "timeline_epoch": self.timeline_epoch,
                                 "content_epoch": self.content_epoch})

    def seek(self, playback_ms, playback_rate=1.0):
        self._ensure_available()
        _integer(playback_ms, "playback_ms", 0, self.source["duration_ms"])
        if (isinstance(playback_rate, bool) or not isinstance(playback_rate, (int, float))
                or not math.isfinite(playback_rate) or not 0.25 <= playback_rate <= 4.0):
            raise MediaRefused("INVALID_MEDIA_RECORD", "invalid playback rate")
        self.timeline_epoch += 1
        self.playback_ms = playback_ms
        self.playback_rate = float(playback_rate)
        self._requested.clear()
        return self.timeline_epoch

    def revoke(self):
        self.source["rights"] = "REVOKED"
        self.timeline_epoch += 1
        self._requested.clear()

    def replace_content(self, source, now_monotonic_ms):
        """Start new content/timeline identity without rewriting prior evidence."""
        replacement = validate_source(source)
        if not source_access(replacement, now_monotonic_ms)["available"]:
            raise MediaRefused("MEDIA_UNAVAILABLE", "replacement source is unavailable")
        for field in ("media_id", "tenant_id", "project_id"):
            if replacement[field] != self.source[field]:
                raise MediaRefused("FOREIGN_MEDIA", f"replacement {field} differs")
        if (replacement["source_revision"] == self.source["source_revision"]
                or replacement["content_sha256"] == self.source["content_sha256"]):
            raise MediaRefused("INVALID_MEDIA_RECORD",
                               "replacement needs new revision and content digest")
        self.source = replacement
        self.content_epoch += 1
        self.timeline_epoch += 1
        self.playback_ms = 0
        self.playback_rate = 1.0
        self._requested.clear()
        return {"content_epoch": self.content_epoch,
                "timeline_epoch": self.timeline_epoch}

    def plan_retrieval(self, start_ms, end_ms, transition_points, count):
        self._ensure_available()
        self._allowed(start_ms, end_ms)
        count = _integer(count, "count", 1, MAX_REQUEST_BUDGET)
        if count > self.request_budget:
            raise MediaRefused("RETRIEVAL_BUDGET", "requested samples exceed remaining budget")
        points = []
        if count == 1:
            points = [start_ms + (end_ms - start_ms) // 2]
        else:
            span = end_ms - start_ms - 1
            points = [start_ms + (span * index // (count - 1))
                      for index in range(count)]
        for point in transition_points:
            _integer(point, "transition point", start_ms, end_ms - 1)
        candidates = []
        for point in sorted(set(transition_points)):
            for offset in (-100, 0, 100):
                value = max(start_ms, min(end_ms - 1, point + offset))
                candidates.append((value, "TRANSITION"))
        for point in points:
            candidates.append((point, "BASELINE"))
        selected = []
        for timestamp, reason in candidates:
            key = (self.timeline_epoch, timestamp)
            if key in self._requested or any(row["timestamp_ms"] == timestamp for row in selected):
                continue
            selected.append({"timestamp_ms": timestamp, "reason": reason,
                             "timeline_epoch": self.timeline_epoch})
            if len(selected) == count:
                break
        if len(selected) < count:
            for timestamp in range(start_ms, end_ms):
                key = (self.timeline_epoch, timestamp)
                if key not in self._requested and not any(
                        row["timestamp_ms"] == timestamp for row in selected):
                    selected.append({"timestamp_ms": timestamp, "reason": "FILL",
                                     "timeline_epoch": self.timeline_epoch})
                    if len(selected) == count:
                        break
        if len(selected) != count:
            raise MediaRefused("RETRIEVAL_BUDGET", "interval has too few unique samples")
        self._bounded()
        self.request_budget -= count
        self._requested.update((self.timeline_epoch, row["timestamp_ms"]) for row in selected)
        self.retrieval_decisions.extend(copy.deepcopy(selected))
        return selected

    def support(self, modality, start_ms, end_ms, timeline_epoch):
        self._ensure_available()
        if timeline_epoch != self.timeline_epoch:
            return {"supported": False, "reason": "STALE_TIMELINE"}
        self._allowed(start_ms, end_ms)
        if modality == "CAPTION":
            found = any(row["timeline_epoch"] == timeline_epoch
                        and row["start_ms"] < end_ms and row["end_ms"] > start_ms
                        for row in self.captions)
            reason = "CAPTION_EVIDENCE" if found else "CAPTION_EVIDENCE_MISSING"
        elif modality == "VISUAL":
            found = any(row["timeline_epoch"] == timeline_epoch
                        and start_ms <= row["timestamp_ms"] < end_ms
                        for row in self.frames)
            reason = "FRAME_EVIDENCE" if found else "VISUAL_EVIDENCE_MISSING"
        else:
            raise MediaRefused("INVALID_MEDIA_RECORD", "unsupported claim modality")
        return {"supported": found, "reason": reason}

    def snapshot(self):
        return {
            "schema": INDEX_SCHEMA,
            "media_id": self.source["media_id"],
            "tenant_id": self.source["tenant_id"],
            "project_id": self.source["project_id"],
            "source_revision": self.source["source_revision"],
            "content_sha256": self.source["content_sha256"],
            "source_access_method": self.source["access_method"],
            "duration_ms": self.source["duration_ms"],
            "authorized_intervals": copy.deepcopy(self.source["allowed_intervals"]),
            "content_epoch": self.content_epoch,
            "timeline_epoch": self.timeline_epoch,
            "playback_ms": self.playback_ms,
            "playback_rate": self.playback_rate,
            "request_budget_remaining": self.request_budget,
            "captions": copy.deepcopy(self.captions),
            "frames": copy.deepcopy(self.frames),
            "gaps": copy.deepcopy(self.gaps),
            "transitions": copy.deepcopy(self.transitions),
            "retrieval_decisions": copy.deepcopy(self.retrieval_decisions),
        }


def canonical_source_json(value):
    return json.dumps(validate_source(value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
