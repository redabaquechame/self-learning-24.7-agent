"""Bounded native frame conversion. No capture, file, network or model access."""
import struct
import zlib
import hashlib
import hmac
import re
import threading

import tutor_transport as wire

MAX_FRAME_BYTES = 32 * 1024 * 1024
MAX_PNG_BYTES = 10 * 1024 * 1024


class FrameRefused(ValueError):
    """Malformed, stale, cancelled or unauthorized frame operation."""


class FrameMemoryReader:
    """Per-launch one-shot memory reader. The host supplies live source authority."""
    def __init__(self, bridge_session, launch_key, current_binding, *, clock_ms=None):
        if not isinstance(bridge_session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', bridge_session):
            raise FrameRefused('invalid bridge namespace')
        if not isinstance(launch_key, (bytes, bytearray)) or len(launch_key) != 32 or not callable(current_binding):
            raise FrameRefused('owned key and current binding are required')
        self._session = bridge_session; self._key = bytearray(launch_key)
        self._binding = current_binding; self._clock = clock_ms or wire.windows_monotonic_ms
        self._used = set(); self._gate = threading.Lock(); self._closed = threading.Event()

    def _admit(self, reference):
        if self._closed.is_set(): raise FrameRefused('frame reader is closed')
        wire.contracts._record(reference, ('schema', 'transfer_id', 'frame_receipt'))
        if reference['schema'] != 'fleet.tutor.frame-reference.v1' or not re.fullmatch(r'[0-9a-f]{32}', reference['transfer_id']):
            raise FrameRefused('invalid frame transfer reference')
        receipt = reference['frame_receipt']
        wire.contracts._record(receipt, ('frame_id', 'source_id', 'source_revision', 'capture_epoch',
            'captured_at_monotonic_ms', 'width', 'height', 'pixel_format', 'size_bytes', 'content_sha256'))
        for name in ('frame_id', 'source_id', 'source_revision'): wire.contracts._ident(receipt[name], name)
        width = wire._int(receipt['width'], 1); height = wire._int(receipt['height'], 1)
        wire._int(receipt['capture_epoch'], 1); wire._int(receipt['size_bytes'], 1)
        if width > 8192 or height > 8192 or width * height * 4 > MAX_FRAME_BYTES or receipt['size_bytes'] != width * height * 4:
            raise FrameRefused('frame length outside bounds')
        if receipt['pixel_format'] not in ('BGRA8', 'BGRA8_PREMULTIPLIED') or not wire.contracts.SHA256.fullmatch(receipt['content_sha256']):
            raise FrameRefused('invalid frame format or digest')
        binding = self._binding()
        if not isinstance(binding, dict): raise FrameRefused('current host authorization absent')
        if binding.get('grant_created') is not False or binding.get('schema') != 'fleet.tutor.capture-authorization.v1':
            raise FrameRefused('current host authorization absent')
        for name in ('source_id', 'source_revision', 'capture_epoch'):
            if receipt[name] != binding.get(name): raise FrameRefused('frame source is stale or foreign')
        now = self._clock()
        start = wire._int(binding['now_monotonic_ms']); expires = wire._int(binding['expires_at_monotonic_ms'], 1)
        captured = wire._int(receipt['captured_at_monotonic_ms'])
        if not start <= captured <= now < expires or expires - start > 900000:
            raise FrameRefused('frame or source authorization expired')
        return tuple(binding.get(name) for name in ('session_id', 'source_id', 'source_revision', 'capture_epoch',
                                                   'consent_revision', 'cancellation_generation', 'expires_at_monotonic_ms'))

    def take(self, reference):
        raw = None
        try:
            binding = self._admit(reference); token = reference['transfer_id']
            with self._gate:
                if token in self._used or len(self._used) >= 4096 or self._closed.is_set():
                    raise FrameRefused('frame transfer reused, closed or at limit')
                self._used.add(token); key = bytearray(self._key)
            try:
                entropy = hmac.new(key, ('fleet.tutor.frame.v1\n' + self._session + '\n' + token).encode('utf-8'), hashlib.sha256).digest()
                raw = _read_protected_mapping('Local\\fleet-tutor-frame-' + self._session + '-' + token,
                                              reference['frame_receipt']['size_bytes'], entropy)
            finally: key[:] = b'\0' * len(key)
            if len(raw) != reference['frame_receipt']['size_bytes'] or hashlib.sha256(raw).hexdigest() != reference['frame_receipt']['content_sha256']:
                raise FrameRefused('frame bytes do not match exact receipt')
            if self._admit(reference) != binding: raise FrameRefused('source changed during memory read')
            return raw
        except Exception as error:
            if raw is not None: raw[:] = b'\0' * len(raw)
            raise FrameRefused('frame memory admission refused') from error

    def close(self):
        self._closed.set()
        with self._gate:
            self._key[:] = b'\0' * len(self._key); self._used.clear()

    def put_png(self, reference, store, *, expires_bridge_ms=None):
        """Publish only a current image; roll back this image on late revocation."""
        from tutor_gateway import EphemeralImageStore
        if not isinstance(store, EphemeralImageStore):
            raise FrameRefused('host one-shot image store is required')
        pixels = None; artifact = None; receipt = reference.get('frame_receipt', {})
        image_binding = {name: receipt.get(name) for name in ('source_id', 'source_revision', 'capture_epoch')}
        try:
            initial = self._admit(reference)
            pixels = self.take(reference)
            png = encode_bgra_png(pixels, receipt['width'], receipt['height'], pixel_format=receipt['pixel_format'],
                                  cancelled=self._closed.is_set)
            if self._admit(reference) != initial:
                raise FrameRefused('source changed during frame conversion')
            expiry_bridge = initial[-1]
            if expires_bridge_ms is not None:
                expiry_bridge = min(expiry_bridge, wire._int(expires_bridge_ms, 1))
            expiry = wire.gateway_deadline(expiry_bridge, bridge_now_ms=self._clock(), gateway_now_ms=store._clock_ms())
            artifact = store.put(png, 'image/png', receipt['source_id'], receipt['source_revision'], receipt['capture_epoch'], expiry)
            if self._admit(reference) != initial:
                raise FrameRefused('source changed during image publication')
            return {'artifact_ref': artifact, 'content_sha256': hashlib.sha256(png).hexdigest(),
                    'raw_content_sha256': receipt['content_sha256'], **image_binding,
                    'width': receipt['width'], 'height': receipt['height'], 'expires_at_monotonic_ms': expiry}
        except Exception as error:
            if artifact is not None:
                try:
                    item = store.take(artifact, image_binding)
                    item['bytes'][:] = b'\0' * len(item['bytes'])
                except ValueError: pass  # Expired/revoked store reads already wipe.
            raise FrameRefused('frame image publication refused') from error
        finally:
            if pixels is not None: pixels[:] = b'\0' * len(pixels)


def _read_protected_mapping(name, expected_size, entropy):
    """Open-existing only; no caller-selected names, paths, URL or new mappings."""
    import os
    if os.name != 'nt': raise FrameRefused('native memory transfer requires Windows')
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('data', ctypes.c_void_p)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True); crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]; kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]; kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]; kernel.UnmapViewOfFile.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]; kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]; kernel.LocalFree.restype = ctypes.c_void_p
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    handle = kernel.OpenFileMappingW(6, False, name)
    if not handle: raise FrameRefused('owned frame mapping absent')
    view = None; output = Blob()
    try:
        view = kernel.MapViewOfFile(handle, 6, 0, 0, 4)
        if not view: raise FrameRefused('frame header unavailable')
        length = struct.unpack('<I', ctypes.string_at(view, 4))[0]
        kernel.UnmapViewOfFile(view); view = None
        if not 0 < length <= expected_size + 65536: raise FrameRefused('protected frame exceeds bounds')
        view = kernel.MapViewOfFile(handle, 6, 0, 0, length + 4)
        if not view: raise FrameRefused('frame mapping length mismatch')
        encrypted = ctypes.create_string_buffer(ctypes.string_at(view + 4, length), length)
        extra = ctypes.create_string_buffer(entropy, len(entropy))
        source = Blob(length, ctypes.addressof(encrypted)); binding = Blob(len(entropy), ctypes.addressof(extra))
        if not crypt.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(binding), None, None, 1, ctypes.byref(output)):
            raise FrameRefused('frame protection binding failed')
        if output.length != expected_size: raise FrameRefused('unprotected frame length mismatch')
        return bytearray(ctypes.string_at(output.data, output.length))
    finally:
        if output.data:
            ctypes.memset(output.data, 0, output.length); kernel.LocalFree(output.data)
        if view:
            ctypes.memset(view, 0, length + 4); kernel.UnmapViewOfFile(view)
        kernel.CloseHandle(handle)


def encode_bgra_png(pixels, width, height, *, pixel_format='BGRA8', cancelled=None):
    if (type(width) is not int or type(height) is not int
            or not 1 <= width <= 8192 or not 1 <= height <= 8192
            or width * height * 4 > MAX_FRAME_BYTES):
        raise FrameRefused('frame dimensions outside bounds')
    if pixel_format not in ('BGRA8', 'BGRA8_PREMULTIPLIED'):
        raise FrameRefused('unsupported native pixel format')
    if not isinstance(pixels, (bytes, bytearray, memoryview)) or len(pixels) != width * height * 4:
        raise FrameRefused('frame length does not match dimensions')
    if cancelled is not None and not callable(cancelled):
        raise FrameRefused('host cancellation reader is required')
    def check():
        if cancelled is not None and cancelled():
            raise FrameRefused('frame conversion cancelled')
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value) & 0xffffffff)
    check()
    raw = memoryview(pixels).cast('B')
    compressor = zlib.compressobj(6)
    compressed = bytearray()
    row = bytearray(1 + width * 4)
    try:
        for y in range(height):
            check()
            source = raw[y * width * 4:(y + 1) * width * 4]
            row[1::4] = source[2::4]; row[2::4] = source[1::4]
            row[3::4] = source[0::4]; row[4::4] = source[3::4]
            if pixel_format == 'BGRA8_PREMULTIPLIED':
                for x in range(width):
                    if x % 256 == 0: check()
                    offset = 1 + x * 4; alpha = row[offset + 3]
                    if alpha != 255:
                        for channel in range(3):
                            row[offset + channel] = min(255, (row[offset + channel] * 255 + alpha // 2) // alpha) if alpha else 0
            compressed.extend(compressor.compress(row))
            if len(compressed) > MAX_PNG_BYTES:
                raise FrameRefused('encoded image exceeds qualified gateway bound')
        compressed.extend(compressor.flush())
        check()
        header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', compressed) + chunk(b'IEND', b'')
        if len(png) > MAX_PNG_BYTES:
            raise FrameRefused('encoded image exceeds qualified gateway bound')
        return png
    finally:
        row[:] = b'\0' * len(row)
        compressed[:] = b'\0' * len(compressed)
        raw.release()
