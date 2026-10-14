#!/usr/bin/env python3
"""Signed native-host codec boundaries; no provider, pipe or private capture."""
import copy
import importlib.util
import json
import hashlib
import hmac
import sys

from common import AGENT_DIR
sys.path.insert(0, AGENT_DIR)


def check_codec():
    spec = importlib.util.find_spec('tutor_transport')
    assert spec is not None, 'typed authenticated native-host codec is absent'
    import tutor_transport as wire
    key = bytes(range(32))
    message = {'schema': 'fleet.tutor.bridge.v1', 'protocol_version': '1.1',
               'session_id': 'session-1', 'bridge_epoch': 2, 'sequence': 1,
               'message_id': 'message-1', 'reply_to': None,
               'deadline_monotonic_ms': 5000, 'cancellation_generation': 0,
               'message_type': 'HELLO',
               'body': {'peer': 'HOST', 'challenge': 'a' * 64}}
    expected = {'session_id': 'session-1', 'bridge_epoch': 2, 'sequence': 1,
                'cancellation_generation': 0}
    raw = wire.encode_message(key, message)
    result = wire.decode_message(key, raw, expected, 1000)
    assert {k: v for k, v in result.items() if k != 'mac'} == message
    assert 'mac' not in message, 'encoder mutates caller input'

    def refuses(call):
        try:
            call()
        except wire.TransportRefusal:
            return
        raise AssertionError('invalid native-host message admitted')

    for field, value in [('deadline_monotonic_ms', 6000), ('message_type', 'STOP'),
                         ('reply_to', 'foreign'), ('message_id', 'altered'),
                         ('cancellation_generation', 1), ('body', {'peer': 'HOST', 'challenge': 'b' * 64})]:
        altered = json.loads(raw)
        altered[field] = value
        # Retain the original MAC; every field, including policy metadata, must bind.
        unsigned = {k: v for k, v in altered.items() if k != 'mac'}
        bad = json.dumps(unsigned, sort_keys=True, separators=(',', ':')).encode()[:-1]
        bad += b',"mac":"' + altered['mac'].encode() + b'"}'
        refuses(lambda: wire.decode_message(key, bad, expected, 1000))
    for field, value in [('protocol_version', '1.3'), ('protocol_version', '2.0'),
                         ('sequence', True), ('bridge_epoch', -1), ('sequence', 2**63),
                         ('body', {'peer': 'HOST', 'challenge': 'a' * 64, 'grant': True})]:
        bad = copy.deepcopy(message); bad[field] = value
        refuses(lambda: wire.encode_message(key, bad))
    refuses(lambda: wire.decode_message(key, raw, expected, 5000))
    refuses(lambda: wire.decode_message(b'x' * 32, raw, expected, 1000))
    refuses(lambda: wire.decode_message(key, raw, {**expected, 'sequence': 2}, 1000))
    refuses(lambda: wire.decode_message(key, raw, {**expected, 'cancellation_generation': 1}, 1000))
    refuses(lambda: wire.decode_message(key, b'{' + raw[1:].replace(b'"sequence":1', b'"sequence":1,"sequence":1'), expected, 1000))
    refuses(lambda: wire.decode_message(key, b' ' * (1024 * 1024 + 1), expected, 1000))
    refuses(lambda: wire.decode_message(key, b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}', expected, 1000))
    unicode_message = {**message, 'message_type': 'UNAVAILABLE',
                       'body': {'reason_code': 'HOST_OFFLINE', 'detail': 'Écran 日本語 😀 <>&'}}
    unicode_raw = wire.encode_message(key, unicode_message)
    assert wire.decode_message(key, unicode_raw, expected, 1000)['body'] == unicode_message['body']
    assert wire.gateway_deadline(5000, bridge_now_ms=2000, gateway_now_ms=900000) == 903000
    refuses(lambda: wire.gateway_deadline(2000, bridge_now_ms=2000, gateway_now_ms=900000))
    print('[transport] every signed field, strict JSON, Unicode, identity, generation, bounds and explicit clock conversion checked')


def check_handshake():
    import tutor_transport as wire
    assert hasattr(wire, 'BridgeSession'), 'mutual authenticated bridge handshake is absent'
    key = bytes(range(32))
    host = wire.BridgeSession(key, 'session-1', 2, 'HOST')
    native = wire.BridgeSession(key, 'session-1', 2, 'NATIVE')

    def refuses(call):
        try:
            call()
        except wire.TransportRefusal:
            return
        raise AssertionError('invalid handshake/state admitted')

    refuses(lambda: host.send('STOP', {'reason_code': 'USER_STOP'}, 5000))
    hello = host.start(5000)
    refuses(lambda: host.receive(hello, 1000))  # reflected own role
    incoming = native.receive(hello, 1000)
    assert incoming['message_type'] == 'HELLO' and not native.ready
    ack = native.acknowledge(5000)
    host.receive(ack, 1000)
    assert not host.ready
    final = host.acknowledge(5000)
    native.receive(final, 1000)
    assert host.ready and native.ready
    refuses(lambda: native.receive(final, 1000))
    for n in range(140):
        raw = host.send('PAUSE', {'reason_code': 'USER_PAUSE'}, 5000)
        native.receive(raw, 1000)
    assert len(native.accepted_history) <= 128
    raw = host.send('STOP', {'reason_code': 'USER_STOP'}, 5000)
    altered = json.loads(raw)
    unsigned = {k: v for k, v in altered.items() if k != 'mac'}
    unsigned['sequence'] += 1
    refuses(lambda: native.receive(wire.encode_message(key, unsigned), 1000))
    assert native.receive(raw, 1000)['message_type'] == 'STOP'
    refuses(lambda: native.receive(raw, 1000))
    unready = wire.BridgeSession(key, 'session-1', 2, 'NATIVE')
    unready.receive(hello, 1000)
    bad_ack = json.loads(ack); bad_ack.pop('mac')
    bad_ack['body']['echo_challenge'] = '0' * 64
    fresh_host = wire.BridgeSession(key, 'session-1', 2, 'HOST')
    fresh_host.start(5000)
    refuses(lambda: fresh_host.receive(wire.encode_message(key, bad_ack), 1000))
    print('[transport handshake] mutual challenge, reflected peer, replay, sequence gaps and bounded history checked')


def check_nested_shapes():
    import tutor_transport as wire
    import tutor_contracts as contracts
    key = bytes(range(32))
    message = json.loads((__import__('pathlib').Path(AGENT_DIR) / 'tests/fixtures/tutor_bridge_python_v1.json').read_bytes())
    message.pop('mac')
    records = contracts.fixture_bundle()['records']
    for kind, field, record in [('ASK', 'request', records['request']), ('ANSWER', 'instruction', records['instruction'])]:
        valid = {**message, 'message_type': kind, 'body': {field: record}}
        wire.encode_message(key, valid)
        for nested in ({}, {**record, 'extra_authority': True}):
            try:
                wire.encode_message(key, {**valid, 'body': {field: nested}})
            except wire.TransportRefusal:
                continue
            raise AssertionError('nested typed lesson shape is open')
    print('[transport] closed nested request/instruction schemas checked without treating wire identity as authority')


def check_operation_binding():
    import tutor_transport as wire
    import tutor_contracts as contracts
    key = bytes(range(32))
    host = wire.BridgeSession(key, 'session-1', 2, 'HOST')
    native = wire.BridgeSession(key, 'session-1', 2, 'NATIVE')
    native.receive(host.start(5000), 1000)
    host.receive(native.acknowledge(5000), 1000)
    native.receive(host.acknowledge(5000), 1000)
    records = contracts.fixture_bundle()['records']
    ask, answer = {'request': records['request']}, {'instruction': records['instruction']}
    def refuses(call):
        try: call()
        except wire.TransportRefusal: return
        raise AssertionError('foreign direction/correlation/generation admitted')
    refuses(lambda: host.send('ASK', ask, 5000))
    refuses(lambda: host.send('ANSWER', answer, 5000, reply_to='unknown'))
    request = native.send('ASK', ask, 5000)
    received = host.receive(request, 1000)
    reply = host.send('ANSWER', answer, 5000, reply_to=received['message_id'])
    bad = json.loads(reply); bad.pop('mac'); bad['reply_to'] = 'foreign'
    refuses(lambda: native.receive(wire.encode_message(key, bad), 1000))
    assert native.receive(reply, 1000)['message_type'] == 'ANSWER'
    refuses(lambda: host.send('ANSWER', answer, 5000, reply_to=received['message_id']))
    request = native.send('ASK', ask, 5000)
    received = host.receive(request, 1000)
    reply = host.send('ANSWER', answer, 5000, reply_to=received['message_id'])
    assert hasattr(native, 'advance_generation'), 'transport has no current cancellation generation boundary'
    native.advance_generation(1)
    refuses(lambda: native.receive(reply, 1000))
    refuses(lambda: native.advance_generation(0))
    host.advance_generation(1)
    assert native.receive(host.send('PAUSE', {'reason_code': 'USER_PAUSE'}, 5000), 1000)['message_type'] == 'PAUSE', 'stale answer stranded current connection sequence'
    print('[transport operations] sender role, exact pending reply, one reply and stale cancellation generation checked')


def check_signed_numeric_and_depth():
    import tutor_transport as wire
    import tutor_contracts as contracts
    key = bytes(range(32))
    base = json.loads((__import__('pathlib').Path(AGENT_DIR) / 'tests/fixtures/tutor_bridge_python_v1.json').read_bytes())
    base.pop('mac')
    base['message_type'] = 'ANSWER'
    base['body'] = {'instruction': copy.deepcopy(contracts.fixture_bundle()['records']['instruction'])}
    def sign(text):
        unsigned = text.encode('utf-8')
        return unsigned[:-1] + b',"mac":"' + hmac.new(key, unsigned, hashlib.sha256).hexdigest().encode('ascii') + b'"}'
    def refuse(raw):
        try: wire.decode_message(key, raw, {'session_id': 'session-1', 'bridge_epoch': 2, 'sequence': 1, 'cancellation_generation': 0}, 1000)
        except wire.TransportRefusal: return
        raise AssertionError('signed numeric overflow/deep payload admitted')
    base['body']['instruction']['claims'][0]['uncertainty'] = 'OVERFLOW'
    refuse(sign(contracts.canonical_json(base).replace('"OVERFLOW"', '1e999')))
    base['body']['instruction']['claims'][0]['uncertainty'] = 2**63
    refuse(sign(contracts.canonical_json(base)))
    nested = {}
    for _ in range(40): nested = {'x': nested}
    base = nested_value_cases()[0][2]
    base['body']['observation']['media'] = nested
    refuse(sign(contracts.canonical_json(base)))
    print('[transport] genuinely signed numeric overflow and deep lesson records refused')


def check_pending_expiry():
    import tutor_transport as wire
    import tutor_contracts as contracts
    key = bytes(range(32))
    host = wire.BridgeSession(key, 'session-1', 2, 'HOST')
    native = wire.BridgeSession(key, 'session-1', 2, 'NATIVE')
    native.receive(host.start(5000), 1000)
    host.receive(native.acknowledge(5000), 1000)
    native.receive(host.acknowledge(5000), 1000)
    body = {'request': contracts.fixture_bundle()['records']['request']}
    for _ in range(128): host.receive(native.send('ASK', body, 2000), 1000)
    try:
        native.send('ASK', body, 5000)
        raise AssertionError('unbounded pending request admission')
    except wire.TransportRefusal: pass
    assert hasattr(native, 'expire_pending'), 'expired requests have no capacity cleanup'
    native.expire_pending(2000); host.expire_pending(2000)
    current = host.receive(native.send('ASK', body, 5000), 2000)
    answer = {'instruction': contracts.fixture_bundle()['records']['instruction']}
    reply = host.send('ANSWER', answer, 5000, reply_to=current['message_id'])
    assert native.receive(reply, 2000)['message_type'] == 'ANSWER'
    current = host.receive(native.send('ASK', body, 3000), 2000)
    try:
        host.send('ANSWER', answer, 5000, reply_to=current['message_id'])
        raise AssertionError('reply extended original request deadline')
    except wire.TransportRefusal: pass
    print('[transport expiry] bounded128 pending requests recover at expiry; replies cannot extend request lifetime')


def check_capture_authorization_shape():
    import tutor_transport as wire
    key = bytes(range(32))
    base = json.loads((__import__('pathlib').Path(AGENT_DIR) / 'tests/fixtures/tutor_bridge_python_v1.json').read_bytes()); base.pop('mac')
    authorization = {'schema': 'fleet.tutor.capture-authorization.v1', 'session_id': 'lesson-1',
        'source_id': 'source-1', 'source_revision': 'revision-1', 'capture_epoch': 3,
        'consent_revision': 'consent-1', 'cancellation_generation': 0,
        'now_monotonic_ms': 1000, 'expires_at_monotonic_ms': 2000, 'grant_created': False}
    base.update(message_type='CAPTURE_AUTHORIZATION', body=authorization)
    wire.encode_message(key, base)
    for field, value in [('grant_created', True), ('grant_created', 0), ('capture_epoch', True),
                         ('capture_epoch', 0), ('expires_at_monotonic_ms', 1000),
                         ('expires_at_monotonic_ms', 901001), ('source_id', '../foreign'),
                         ('schema', 'untrusted.v1')]:
        try:
            wire.encode_message(key, {**base, 'body': {**authorization, field: value}})
        except wire.TransportRefusal: continue
        raise AssertionError('malformed capture authorization admitted: ' + field)
    print('[transport authorization] exact schema, finite15-minute lifetime and no minted grant checked')


def nested_value_cases():
    import tutor_contracts as c
    base = json.loads((__import__('pathlib').Path(AGENT_DIR) / 'tests/fixtures/tutor_bridge_python_v1.json').read_bytes()); base.pop('mac')
    records = copy.deepcopy(c.fixture_bundle()['records'])
    observation = records['observation']
    frame = {'schema': 'fleet.tutor.frame-reference.v1', 'transfer_id': 'transfer-1',
             'frame_receipt': {'frame_id': 'frame-1', 'source_id': observation['source_id'],
                'source_revision': observation['source_revision'], 'capture_epoch': observation['capture_epoch'],
                'captured_at_monotonic_ms': observation['captured_at_monotonic_ms'],
                'width': observation['geometry']['source_width'], 'height': observation['geometry']['source_height'],
                'pixel_format': 'BGRA8', 'size_bytes': observation['geometry']['source_width'] * observation['geometry']['source_height'] * 4,
                'content_sha256': observation['content_sha256']}}
    valid = [{**base, 'message_type': 'ASK', 'body': {'request': records['request']}},
             {**base, 'message_type': 'ANSWER', 'body': {'instruction': records['instruction']}},
             {**base, 'message_type': 'OBSERVATION', 'body': {'observation': observation, 'frame_reference': frame}}]
    valid.append({**base, 'message_type': 'UNAVAILABLE', 'body': {'reason_code': 'HOST_OFFLINE', 'detail': '😀' * 3000}})
    native_format = copy.deepcopy(valid[2])
    native_format['body']['frame_reference']['frame_receipt']['pixel_format'] = 'BGRA8_PREMULTIPLIED'
    valid.append(native_format)
    unknown_placement = copy.deepcopy(valid[2])
    for field in ('desktop_origin_x', 'desktop_origin_y', 'native_dpi_scale'):
        unknown_placement['body']['observation']['geometry'][field] = None
    valid.append(unknown_placement)
    valid.append({**base, 'message_type': 'FRAME', 'body': {'frame_reference': frame}})
    valid.append({**base, 'message_type': 'FRAME_ACCEPTED', 'body': {'observation': unknown_placement['body']['observation']}})
    valid.append({**base, 'message_type': 'QUESTION', 'body': {'request_id': 'request-1', 'observation_id': observation['observation_id'],
        'question': 'Explain this selected source', 'learning_intent': 'UNDERSTAND', 'locale': 'en-CA'}})
    invalid = []
    def bad(index, path, value):
        changed = copy.deepcopy(valid[index]); current = changed['body']
        for part in path[:-1]: current = current[part]
        current[path[-1]] = value
        invalid.append(changed)
    bad(0, ['request', 'mode'], 'UNKNOWN')
    bad(0, ['request', 'output_preferences', 'speech'], 'yes')
    bad(0, ['request', 'output_preferences', 'grant'], True)
    bad(0, ['request', 'observation_ids'], ['obs-1', 'obs-1'])
    bad(1, ['instruction', 'claims', 0, 'uncertainty'], True)
    bad(1, ['instruction', 'claims', 0, 'grant'], True)
    bad(1, ['instruction', 'expected_progress', 'scope'], [])
    bad(2, ['observation', 'geometry', 'crop', 'width'], 999999)
    bad(2, ['observation', 'modalities'], ['foreign'])
    bad(2, ['observation', 'grant'], True)
    bad(2, ['frame_reference', 'transfer_id'], '../mapping')
    bad(2, ['frame_reference', 'frame_receipt', 'pixel_format'], 'JPEG')
    bad(2, ['frame_reference', 'frame_receipt', 'size_bytes'], 1)
    bad(2, ['frame_reference', 'frame_receipt', 'source_id'], 'foreign')
    for field in ('desktop_origin_x', 'desktop_origin_y', 'native_dpi_scale'):
        bad(5, ['observation', 'geometry', field], 1)
    bad(6, ['frame_reference', 'frame_receipt', 'size_bytes'], 1)
    bad(6, ['frame_reference', 'transfer_id'], '../unowned')
    bad(8, ['question'], '')
    bad(8, ['learning_intent'], 'AUTO_EXECUTE')
    bad(8, ['provider'], 'native-selected-provider')
    return valid, invalid


def check_nested_values():
    import tutor_transport as wire
    key = bytes(range(32))
    valid, invalid = nested_value_cases()
    for message in valid: wire.encode_message(key, message)
    for index, message in enumerate(invalid):
        try: wire.encode_message(key, message)
        except wire.TransportRefusal: pass
        else: raise AssertionError('nested request/instruction/observation/frame value admitted: ' + str(index))
        unsigned = __import__('tutor_contracts').canonical_json(message).encode('utf-8')
        raw = unsigned[:-1] + b',"mac":"' + hmac.new(key, unsigned, hashlib.sha256).hexdigest().encode('ascii') + b'"}'
        try: wire.decode_message(key, raw, {'session_id': 'session-1', 'bridge_epoch': 2, 'sequence': 1, 'cancellation_generation': 0}, 1000)
        except wire.TransportRefusal: continue
        raise AssertionError('signed nested input admitted: ' + str(index))
    corpus = json.loads((__import__('pathlib').Path(AGENT_DIR) / 'tests/fixtures/tutor_bridge_nested_v1.json').read_text(encoding='utf-8'))
    assert corpus['valid'] == valid and corpus['invalid'] == invalid
    assert corpus['signed_invalid'] == shared_signed_rejections()
    for raw in corpus['signed_invalid']:
        try: wire.decode_message(key, raw.encode('utf-8'), {'session_id': 'session-1', 'bridge_epoch': 2, 'sequence': 1, 'cancellation_generation': 0}, 1000)
        except wire.TransportRefusal: continue
        raise AssertionError('shared signed rejection case admitted')
    print('[transport nested values] closed typed lessons, observation geometry and opaque exact-frame references checked')


def shared_signed_rejections():
    import tutor_contracts as c
    valid, invalid = nested_value_cases()
    extra = []
    for field, value in [('schema', 'foreign.v1'), ('protocol_version', '1.3'), ('protocol_version', '2.0'),
                         ('session_id', 'foreign'), ('bridge_epoch', 3), ('sequence', 2),
                         ('cancellation_generation', 1), ('deadline_monotonic_ms', 1000)]:
        extra.append({**valid[0], field: value})
    deep = copy.deepcopy(valid[2]); nested = {}
    for _ in range(40): nested = {'x': nested}
    deep['body']['observation']['media'] = nested; extra.append(deep)
    extra.append({**valid[3], 'body': {'reason_code': 'HOST_OFFLINE', 'detail': '\ud800'}})
    signed = []
    for message in invalid + extra:
        raw = c.canonical_json(message).encode('utf-8')
        signed.append((raw[:-1] + b',"mac":"' + hmac.new(bytes(range(32)), raw, hashlib.sha256).hexdigest().encode('ascii') + b'"}').decode('utf-8'))
    return signed


def check_peer_teardown():
    import tutor_transport as wire
    key = bytes(range(32)); peer = wire.BridgeSession(key, 'session-1', 2, 'HOST')
    assert callable(getattr(peer, 'close', None)), 'Python peer has no owned secret teardown'
    peer.start(5000); peer.close()
    assert not peer.ready and all(value == 0 for value in peer._key)
    assert key == bytes(range(32)), 'peer teardown changed caller key storage'
    try: peer.start(5000)
    except wire.TransportRefusal: pass
    else: raise AssertionError('closed peer reopened')
    print('[transport teardown] owned mutable key is wiped; closed peer cannot restart')


def check_practice_wire():
    import base64,copy
    import tutor_transport as W
    def refuses(fn):
        try:fn()
        except W.TransportRefusal:return
        raise AssertionError('invalid practice wire admitted')
    key=bytes(range(32))
    host=W.BridgeSession(key,'owned',1,'HOST',protocol_version='1.2')
    native=W.BridgeSession(key,'owned',1,'NATIVE',protocol_version='1.2')
    native.receive(host.start(5000),1000);host.receive(native.acknowledge(5000),1000);native.receive(host.acknowledge(5000),1000)
    request={'schema':'fleet.tutor.practice-request.v1','operation':'UPLOAD','payload':{'artifact_base64':base64.b64encode(b'{"total":42}').decode()}}
    raw=native.send('PRACTICE_REQUEST',request,5000)
    msg=host.receive(raw,1000)
    assert msg['protocol_version']=='1.2' and msg['body']==request
    for bad in [ {**request,'project_id':'foreign'}, {**request,'payload':{'artifact_digest':'a'*64}},
        {**request,'payload':{'artifact_base64':'!'}}, {**request,'payload':{'artifact_base64':base64.b64encode(b'x'*(256*1024+1)).decode()}},
        {**request,'operation':'GRADE'}, {**request,'payload':{'artifact_base64':request['payload']['artifact_base64'],'expected':42}} ]:
        refuses(lambda bad=bad:native.send('PRACTICE_REQUEST',bad,5000))
    result={'schema':'fleet.tutor.practice-result.v1','state':'ACTIVE','attempt_id':'attempt','artifact_count':1,
            'predicate_correct':None,'passing':None,'independent_success':False,'projection_status':'UNASSESSED','qualification':'UNASSESSED'}
    assert native.receive(host.send('PRACTICE_RESULT',result,5000,reply_to=msg['message_id']),1000)['body']==result
    old=W.BridgeSession(key,'old',1,'HOST')
    refuses(lambda:old.receive(W.BridgeSession(key,'old',1,'HOST',protocol_version='1.2').start(5000),1000))
    envelope={k:v for k,v in msg.items() if k!='mac'};envelope['protocol_version']='1.1'
    refuses(lambda:W.encode_message(key,envelope))
    print('PASS version1.2 mutual agreement, closed actual-byte upload, role/correlation/size/identity/digest-only refusals, unchanged1.1 excludes practice')

if __name__ == '__main__':
    check_practice_wire()
    check_codec()
    check_handshake()
    check_nested_shapes()
    check_operation_binding()
    check_signed_numeric_and_depth()
    check_pending_expiry()
    check_capture_authorization_shape()
    check_nested_values()
    check_peer_teardown()
    print('PASS test_tutor_transport')
