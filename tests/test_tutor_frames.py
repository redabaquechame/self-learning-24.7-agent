#!/usr/bin/env python3
"""Exact native frame conversion; controlled bytes, no private source/provider."""
import importlib.util
import struct
import sys
import zlib
import json
import os
import copy
import hashlib
from unittest.mock import patch

from common import AGENT_DIR
sys.path.insert(0, AGENT_DIR)


def check_exact_png():
    assert importlib.util.find_spec('tutor_frames') is not None, 'actual native BGRA-to-host-image adapter is absent'
    import tutor_frames as frames
    pixels = bytes([0, 0, 128, 128, 30, 20, 10, 255])
    png = frames.encode_bgra_png(pixels, 2, 1, pixel_format='BGRA8_PREMULTIPLIED')
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert struct.unpack('>II', png[16:24]) == (2, 1)
    position = 8; compressed = bytearray()
    while position < len(png):
        size = struct.unpack('>I', png[position:position + 4])[0]
        kind = png[position + 4:position + 8]; data = png[position + 8:position + 8 + size]
        crc = struct.unpack('>I', png[position + 8 + size:position + 12 + size])[0]
        assert zlib.crc32(kind + data) & 0xffffffff == crc
        if kind == b'IDAT': compressed.extend(data)
        position += size + 12
    assert zlib.decompress(compressed) == bytes([0, 255, 0, 0, 128, 10, 20, 30, 255]), 'native premultiplied colors were darkened/swapped'
    assert pixels == bytes([0, 0, 128, 128, 30, 20, 10, 255])
    for call in (lambda: frames.encode_bgra_png(b'x', 2, 1),
                 lambda: frames.encode_bgra_png(pixels, True, 1),
                 lambda: frames.encode_bgra_png(pixels, 9000, 1),
                 lambda: frames.encode_bgra_png(pixels, 2, 1, pixel_format='UNKNOWN'),
                 lambda: frames.encode_bgra_png(pixels, 2, 1, cancelled=lambda: True)):
        try: call()
        except frames.FrameRefused: continue
        raise AssertionError('invalid/cancelled native conversion admitted')
    print('[native image] exact PNG dimensions/CRC/channel order/premultiplied alpha and cancellation checked')


def check_memory_reader():
    import tutor_frames as frames
    assert hasattr(frames, 'FrameMemoryReader'), 'host one-shot native memory reader is absent'
    path = os.environ.get('AGENT_TUTOR_FRAME_REFERENCE')
    if path is None:
        print('[frame memory] no owned native mapping fixture selected; actual cross-process witness not run')
        return
    packet = json.loads(__import__('pathlib').Path(path).read_text(encoding='utf-8'))
    reader = frames.FrameMemoryReader('frame-test-bridge', bytes(range(32)), lambda: packet['authorization'])
    from tutor_gateway import EphemeralImageStore
    store = EphemeralImageStore()
    admitted = reader.put_png(packet['reference'], store)
    assert admitted['raw_content_sha256'] == packet['reference']['frame_receipt']['content_sha256']
    image = store.take(admitted['artifact_ref'], admitted)
    assert hashlib.sha256(image['bytes']).hexdigest() == admitted['content_sha256']
    assert image['width'] == packet['reference']['frame_receipt']['width'] and image['height'] == packet['reference']['frame_receipt']['height']
    try: reader.take(packet['reference'])
    except frames.FrameRefused: pass
    else: raise AssertionError('native frame mapping was consumed twice')
    assert image['bytes'][:8] == b'\x89PNG\r\n\x1a\n'
    image['bytes'][:] = b'\0' * len(image['bytes']); reader.close()
    print('[frame memory] actual native capture/memory/exact digest to PNG host one-shot store checked')


def memory_fixture():
    pixels = bytearray([0, 0, 128, 128, 30, 20, 10, 255])
    reference = {'schema': 'fleet.tutor.frame-reference.v1', 'transfer_id': 'a' * 32,
        'frame_receipt': {'frame_id': 'frame-1', 'source_id': 'source-1', 'source_revision': 'revision-1',
            'capture_epoch': 3, 'captured_at_monotonic_ms': 1500, 'width': 2, 'height': 1,
            'pixel_format': 'BGRA8_PREMULTIPLIED', 'size_bytes': 8, 'content_sha256': hashlib.sha256(pixels).hexdigest()}}
    binding = {'schema': 'fleet.tutor.capture-authorization.v1', 'session_id': 'lesson-1',
        'source_id': 'source-1', 'source_revision': 'revision-1', 'capture_epoch': 3, 'consent_revision': 'consent-1',
        'cancellation_generation': 0, 'now_monotonic_ms': 1000, 'expires_at_monotonic_ms': 5000, 'grant_created': False}
    return pixels, reference, binding


def check_store_admission():
    import tutor_frames as frames
    from tutor_gateway import EphemeralImageStore
    pixels, reference, binding = memory_fixture()
    reader = frames.FrameMemoryReader('bridge-1', bytes(range(32)), lambda: copy.deepcopy(binding), clock_ms=lambda: 2000)
    assert callable(getattr(reader, 'put_png', None)), 'verified native frame does not enter one-shot host image store'
    store = EphemeralImageStore(clock_ms=lambda: 900000)
    with patch.object(frames, '_read_protected_mapping', return_value=pixels):
        admitted = reader.put_png(reference, store)
    assert all(value == 0 for value in pixels), 'raw frame bytes retained after host image publication'
    assert admitted['raw_content_sha256'] == reference['frame_receipt']['content_sha256']
    image = store.take(admitted['artifact_ref'], {'source_id': 'source-1', 'source_revision': 'revision-1', 'capture_epoch': 3})
    assert image['expires_at_monotonic_ms'] == 903000, 'bridge expiry compared using wrong clock epoch'
    assert hashlib.sha256(image['bytes']).hexdigest() == admitted['content_sha256']
    assert image['width'] == 2 and image['height'] == 1
    image['bytes'][:] = b'\0' * len(image['bytes']); reader.close()
    pixels, reference, binding = memory_fixture()
    reader = frames.FrameMemoryReader('bridge-1', bytes(range(32)), lambda: copy.deepcopy(binding), clock_ms=lambda: 2000)
    store = EphemeralImageStore(clock_ms=lambda: 900000)
    original = store.put
    def revoke_after_put(*args):
        result = original(*args); binding['consent_revision'] = 'revoked'; return result
    with patch.object(frames, '_read_protected_mapping', return_value=pixels), patch.object(store, 'put', side_effect=revoke_after_put):
        try: reader.put_png(reference, store)
        except frames.FrameRefused: pass
        else: raise AssertionError('revoked frame published after store insertion')
    assert not store._items and all(value == 0 for value in pixels)
    reader.close()
    print('[host image store] raw bytes wiped, PNG/source identity and explicit expiry-clock conversion; late revocation rolls back own image')


def check_epoch_type_before_memory():
    import tutor_frames as frames
    pixels, reference, binding = memory_fixture()
    reference['frame_receipt']['capture_epoch'] = True; binding['capture_epoch'] = 1
    reader = frames.FrameMemoryReader('bridge-1', bytes(range(32)), lambda: binding, clock_ms=lambda: 2000)
    with patch.object(frames, '_read_protected_mapping', return_value=pixels) as mapping:
        try: reader.take(reference)
        except frames.FrameRefused: pass
        else: raise AssertionError('boolean native epoch aliases a host integer epoch')
        assert not mapping.called, 'malformed native epoch reached shared memory'
    reader.close()
    print('[frame admission] malformed epoch rejected before any shared-memory access')


def check_policy_failure_wipes():
    import tutor_frames as frames
    from tutor_service import TutorUnavailable
    from tutor_gateway import EphemeralImageStore
    pixels, reference, binding = memory_fixture()
    revoked = False
    def current():
        if revoked: raise TutorUnavailable('current owner revoked source')
        return copy.deepcopy(binding)
    reader = frames.FrameMemoryReader('bridge-1', bytes(range(32)), current, clock_ms=lambda: 2000)
    def read_and_revoke(*args):
        nonlocal revoked
        revoked = True
        return pixels
    with patch.object(frames, '_read_protected_mapping', side_effect=read_and_revoke):
        try: reader.take(reference)
        except (frames.FrameRefused, TutorUnavailable): pass
        else: raise AssertionError('owner failure released raw frame')
    assert not any(pixels), 'owner policy failure left decrypted native pixels intact'
    reader.close()
    pixels, reference, binding = memory_fixture(); revoked = False
    reader = frames.FrameMemoryReader('bridge-1', bytes(range(32)), current, clock_ms=lambda: 2000)
    store = EphemeralImageStore(clock_ms=lambda: 900000); put = store.put
    def put_and_revoke(*args):
        nonlocal revoked
        artifact = put(*args); revoked = True
        return artifact
    with patch.object(frames, '_read_protected_mapping', return_value=pixels), patch.object(store, 'put', side_effect=put_and_revoke):
        try: reader.put_png(reference, store)
        except (frames.FrameRefused, TutorUnavailable): pass
        else: raise AssertionError('owner failure released stored image')
    assert not store._items, 'owner policy exception left published image in host store'
    assert not any(pixels)
    reader.close()
    print('[policy failure] decrypted pixels and inserted image wiped on live owner exception')


if __name__ == '__main__':
    check_exact_png()
    check_store_admission()
    check_epoch_type_before_memory()
    check_policy_failure_wipes()
    check_memory_reader()
    print('PASS test_tutor_frames')
