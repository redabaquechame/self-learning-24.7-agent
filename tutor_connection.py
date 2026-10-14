"""Optional Windows native child connection. No IO/process/native call at import.

Only host-verified executable records can launch. The random key travels through
the child's inherited stdin pipe, never command arguments, environment or disk.
"""
import hashlib
import json
import os
import pathlib
import secrets
import struct
import subprocess
import threading
import weakref
from dataclasses import dataclass

import tutor_transport as wire

_VERIFIED = object()


class ConnectionUnavailable(ValueError):
    """Secret-free native connection failure."""


class ConnectionIdle(Exception):
    """An empty poll consumed no frame bytes and leaves the pipe usable."""


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True, repr=False)
class _ExecutableAdmission:
    issuer: object
    path: pathlib.Path
    arguments: tuple
    files: tuple


@dataclass(frozen=True, repr=False)
class VerifiedNativeExecutable:
    path: pathlib.Path
    arguments: tuple
    files: tuple
    proof: object

    @classmethod
    def from_host(cls, path, *, arguments=('--native-host-stdin',)):
        path = pathlib.Path(path).resolve(strict=True)
        if path.suffix.lower() != '.exe' or path.read_bytes()[:2] != b'MZ':
            raise ConnectionUnavailable('native executable is unavailable')
        if arguments not in (('--native-host-stdin',), ('--native-host-fixture',)):
            raise ConnectionUnavailable('unsupported native launch mode')
        files = tuple((p, _digest(p)) for p in sorted(path.parent.rglob('*'))
                      if p.is_file() and p.suffix.lower() in ('.exe', '.dll', '.json'))
        return cls(path, arguments, files, _ExecutableAdmission(_VERIFIED, path, arguments, files))

    def verify(self):
        if (not isinstance(self.proof, _ExecutableAdmission) or self.proof.issuer is not _VERIFIED
                or (self.path, self.arguments, self.files) != (self.proof.path, self.proof.arguments, self.proof.files)
                or not self.files):
            raise ConnectionUnavailable('unverified native executable')
        current = {p for p in self.path.parent.rglob('*') if p.is_file()
                   and p.suffix.lower() in ('.exe', '.dll', '.json')}
        if current != {p for p, _ in self.files} or any(_digest(p) != digest for p, digest in self.files):
            raise ConnectionUnavailable('native executable candidate changed')


class WindowsPipe:
    """Own handle and overlapped operations only; Stop never takes an IO lock."""
    def __init__(self, name, process, deadline, *, stop_event=None):
        import _winapi
        self._api = _winapi
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._handle = None
        self._read_gate = threading.Lock(); self._write_gate = threading.Lock()
        self._handle_gate = threading.Lock()
        while wire.windows_monotonic_ms() < deadline:
            if self._stop.is_set():
                raise ConnectionUnavailable('native connection cancelled')
            if process.poll() is not None:
                raise ConnectionUnavailable('native peer exited before connection')
            try:
                self._handle = _winapi.CreateFile('\\\\.\\pipe\\' + name,
                    0xC0000000, 0, 0, 3, 0x40000000, 0)
                break
            except OSError as error:
                if error.winerror not in (2, 231):
                    raise ConnectionUnavailable('native pipe unavailable') from None
                self._stop.wait(0.02)
        if self._handle is None:
            raise ConnectionUnavailable('native connection timed out')
        try:
            import ctypes
            from ctypes import wintypes
            pid = wintypes.ULONG()
            method = ctypes.WinDLL('kernel32', use_last_error=True).GetNamedPipeServerProcessId
            method.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG)]
            method.restype = wintypes.BOOL
            if not method(self._handle, ctypes.byref(pid)) or pid.value != process.pid:
                raise ConnectionUnavailable('native pipe belongs to a foreign process')
        except BaseException:
            self.close()
            raise

    def stop(self):
        self._stop.set()

    def close(self):
        self.stop()
        with self._handle_gate:
            handle, self._handle = self._handle, None
        if handle is not None:
            self._api.CloseHandle(handle)

    def _io(self, data, deadline, *, reading, idle_allowed=False):
        if self._stop.is_set() or self._handle is None:
            raise ConnectionUnavailable('native connection stopped')
        operation = None
        try:
            with self._handle_gate:
                if self._stop.is_set() or self._handle is None:
                    raise ConnectionUnavailable('native connection stopped')
                operation, _ = (self._api.ReadFile(self._handle, data, overlapped=True) if reading
                                else self._api.WriteFile(self._handle, data, overlapped=True))
            while True:
                remaining = deadline - wire.windows_monotonic_ms()
                if self._stop.is_set() or remaining <= 0:
                    operation.cancel()
                    try:
                        count, error = operation.GetOverlappedResult(True)
                    except OSError as cancelled:
                        if cancelled.winerror != 995: raise
                        count, error = 0, 995
                    if reading and idle_allowed and not self._stop.is_set() and count == 0 and error == 995:
                        raise ConnectionIdle()
                    raise ConnectionUnavailable('native IO cancelled or timed out')
                if self._api.WaitForSingleObject(operation.event, min(remaining, 25)) == 0:
                    break
            count, error = operation.GetOverlappedResult(True)
            if error or count == 0:
                raise ConnectionUnavailable('native peer disconnected')
            return operation.getbuffer() if reading else count
        except (OSError, ConnectionUnavailable):
            self.stop()  # Partial framing/sequence cannot be retried.
            raise ConnectionUnavailable('native IO unavailable') from None

    def read(self, deadline, *, allow_idle=False):
        with self._read_gate:
            def exact(size, *, initial_idle=False):
                chunks = bytearray()
                while len(chunks) < size:
                    chunks.extend(self._io(size - len(chunks), deadline, reading=True,
                                           idle_allowed=initial_idle and not chunks))
                return bytes(chunks)
            length = struct.unpack('>I', exact(4, initial_idle=allow_idle))[0]
            if not 0 < length <= wire.MAX_BYTES:
                self.stop(); raise ConnectionUnavailable('native message length refused')
            return exact(length)

    def write(self, payload, deadline):
        with self._write_gate:
            data = struct.pack('>I', len(payload)) + payload
            offset = 0
            while offset < len(data):
                offset += self._io(data[offset:], deadline, reading=False)


class ReleaseRefused(wire.StaleBridgeMessage):
    """No application bytes emitted: current host authority failed at the writer."""


class NativeConnection:
    def __init__(self, process, pipe, peer):
        self._process, self._pipe, self._peer = process, pipe, peer
        self._stopped = threading.Event()
        self._send_gate = threading.Lock(); self._receive_gate = threading.Lock()
        self._frame_gate = threading.Lock(); self._frame_readers = weakref.WeakSet()

    def create_frame_reader(self, current_binding):
        from tutor_frames import FrameMemoryReader
        with self._frame_gate:
            if not self.ready: raise ConnectionUnavailable('native frame connection unavailable')
            reader = FrameMemoryReader(self._peer.session_id, self._peer._key, current_binding)
            self._frame_readers.add(reader)
            return reader

    @property
    def ready(self):
        return not self._stopped.is_set() and self._peer.ready and self._process.poll() is None

    def send(self, kind, body, *, timeout_ms, reply_to=None, deadline_ms=None, release_check=None):
        if not self.ready:
            raise ConnectionUnavailable('native connection unavailable')
        timeout = _timeout(timeout_ms)
        if not self._send_gate.acquire(timeout=timeout / 1000):
            raise ConnectionUnavailable('native writer is busy')
        try:
            now = wire.windows_monotonic_ms(); self._peer.expire_pending(now)
            deadline = now + timeout if deadline_ms is None else min(now + timeout, wire._int(deadline_ms, 1))
            if deadline <= now:
                raise wire.StaleBridgeMessage('outgoing request lifetime expired before send')
            if not self.ready:
                raise ConnectionUnavailable('native connection stopped while queued')
            if release_check is not None and not release_check():
                raise ReleaseRefused('current host authority changed while queued')
            self._pipe.write(self._peer.send(kind, body, deadline, reply_to=reply_to), deadline)
        except ConnectionUnavailable:
            self.stop(); raise
        finally:
            self._send_gate.release()

    def receive(self, *, timeout_ms):
        return self._receive(timeout_ms=timeout_ms, allow_idle=False)

    def poll(self, *, timeout_ms):
        """Bounded listener poll; idle is never an answer or success record."""
        return self._receive(timeout_ms=timeout_ms, allow_idle=True)

    def _receive(self, *, timeout_ms, allow_idle):
        if not self.ready:
            raise ConnectionUnavailable('native connection unavailable')
        timeout = _timeout(timeout_ms)
        if not self._receive_gate.acquire(timeout=timeout / 1000):
            raise ConnectionUnavailable('native reader is busy')
        try:
            raw = self._pipe.read(wire.windows_monotonic_ms() + timeout, allow_idle=allow_idle)
            return self._peer.receive(raw, wire.windows_monotonic_ms())
        except ConnectionIdle:
            return None
        except wire.StaleBridgeMessage:
            raise  # Already consumed; current traffic remains usable.
        except (ConnectionUnavailable, wire.TransportRefusal):
            self.stop(); raise
        finally:
            self._receive_gate.release()

    def stop(self):
        self._stopped.set(); self._pipe.stop()
        with self._frame_gate: readers = list(self._frame_readers); self._frame_readers.clear()
        for reader in readers: reader.close()
        # Signal IO first; only the child created by this connection is owned.
        if self._process.poll() is None:
            try: self._process.terminate()
            except ProcessLookupError: pass
        self._pipe.close()
        self._peer.close()

    def wait_closed(self, *, timeout_ms):
        """Bounded cleanup receipt, separate from urgent non-waiting Stop."""
        try:
            self._process.wait(timeout=_timeout(timeout_ms) / 1000)
            return True
        except subprocess.TimeoutExpired:
            return False


def _timeout(value):
    if type(value) is not int or not 1 <= value <= 10000:
        raise ConnectionUnavailable('native timeout outside bounds')
    return value


def launch(native_executable, *, enabled, timeout_ms=5000, stop_event=None, protocol_version='1.1'):
    if protocol_version not in ('1.1','1.2'):
        raise ConnectionUnavailable('unsupported native launch protocol')
    if enabled is not True:
        return {'available': False, 'reason_code': 'FEATURE_OFF'}
    if native_executable is None or os.name != 'nt':
        return {'available': False, 'reason_code': 'NATIVE_UNAVAILABLE'}
    if not isinstance(native_executable, VerifiedNativeExecutable):
        raise ConnectionUnavailable('host-verified native executable required')
    cancel = stop_event if stop_event is not None else threading.Event()
    if not isinstance(cancel, threading.Event) or cancel.is_set():
        raise ConnectionUnavailable('native launch cancelled')
    native_executable.verify()
    if cancel.is_set():
        raise ConnectionUnavailable('native launch cancelled')
    deadline = wire.windows_monotonic_ms() + _timeout(timeout_ms)
    key = bytearray(secrets.token_bytes(32)); process = pipe = peer = None
    session = secrets.token_hex(16); epoch = 1
    pipe_name = 'fleet-screen-tutor-' + secrets.token_hex(16)
    try:
        import base64
        bootstrap = {'schema': 'fleet.tutor.bootstrap.v1', 'protocol_version': protocol_version,
            'session_id': session, 'bridge_epoch': epoch, 'pipe_name': pipe_name,
            'host_process_id': os.getpid(), 'key_base64': base64.b64encode(key).decode('ascii'),
            'deadline_monotonic_ms': deadline}
        payload = json.dumps(bootstrap, separators=(',', ':')).encode('utf-8')
        if len(payload) > 4096:
            raise ConnectionUnavailable('native bootstrap exceeds bounds')
        if cancel.is_set(): raise ConnectionUnavailable('native launch cancelled')
        process = subprocess.Popen([str(native_executable.path), *native_executable.arguments],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(native_executable.path.parent), creationflags=subprocess.CREATE_NO_WINDOW)
        if cancel.is_set(): raise ConnectionUnavailable('native launch cancelled')
        process.stdin.write(struct.pack('>I', len(payload)) + payload)
        process.stdin.close()
        pipe = WindowsPipe(pipe_name, process, deadline, stop_event=cancel)
        peer = wire.BridgeSession(bytes(key), session, epoch, 'HOST', protocol_version=protocol_version)
        pipe.write(peer.start(deadline), deadline)
        peer.receive(pipe.read(deadline), wire.windows_monotonic_ms())
        pipe.write(peer.acknowledge(deadline), deadline)
        return NativeConnection(process, pipe, peer)
    except BaseException:
        if pipe is not None: pipe.close()
        if peer is not None: peer.close()
        if process is not None:
            if process.stdin is not None and not process.stdin.closed: process.stdin.close()
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=1)
            except subprocess.TimeoutExpired: pass
        raise ConnectionUnavailable('native startup or authentication failed') from None
    finally:
        key[:] = b'\0' * len(key)
