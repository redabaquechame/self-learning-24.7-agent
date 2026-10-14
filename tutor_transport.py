"""Optional signed bridge codec. Authentication grants no capture or model authority.

The MAC authenticates the exact UTF-8 unsigned JSON object, including its final
brace. The wire appends a fixed, final MAC member. Readers authenticate those
bytes without reserializing numeric or Unicode values across runtimes.
"""
import hashlib
import base64
import hmac
import json
import math
import re
import secrets
import threading
from collections import deque

import tutor_contracts as contracts

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 32
MAX_INT = 2**63 - 1
FIELDS = ('schema', 'protocol_version', 'session_id', 'bridge_epoch', 'sequence',
          'message_id', 'reply_to', 'deadline_monotonic_ms',
          'cancellation_generation', 'message_type', 'body')
MAC_TRAILER = re.compile(rb',"mac":"([0-9a-f]{64})"}$')
BODY_FIELDS = {
    'HELLO': ('peer', 'challenge'),
    'HELLO_ACK': ('peer', 'challenge', 'echo_challenge'),
    'SELECT_SOURCE': ('source_id', 'display_name', 'source_kind', 'source_revision',
                      'native_handle_digest', 'width', 'height', 'capture_epoch'),
    'CAPTURE_AUTHORIZATION': ('schema', 'session_id', 'source_id', 'source_revision',
                              'capture_epoch', 'consent_revision', 'cancellation_generation',
                              'now_monotonic_ms', 'expires_at_monotonic_ms', 'grant_created'),
    'PRESENTATION_RETIRED': ('binding', 'reason_code'),
    'ASK': ('request',), 'ANSWER': ('instruction',),
    'OBSERVATION': ('observation', 'frame_reference'),
    'FRAME': ('frame_reference',), 'FRAME_ACCEPTED': ('observation',),
    'QUESTION': ('request_id', 'observation_id', 'question', 'learning_intent', 'locale'),
    'PAUSE': ('reason_code',), 'STOP': ('reason_code',),
    'UNAVAILABLE': ('reason_code', 'detail'), 'REFUSAL': ('reason_code', 'detail'),
    'PRACTICE_REQUEST': ('schema', 'operation', 'payload'),
    'PRACTICE_RESULT': ('schema', 'state', 'attempt_id', 'artifact_count',
        'predicate_correct', 'passing', 'independent_success', 'projection_status', 'qualification'),
}
LESSON_FIELDS = {
    'request': ('schema', 'request_id', 'session_id', 'user_id', 'tenant_id', 'project_id',
                'mode', 'learning_intent', 'question', 'observation_ids', 'source_ids',
                'skill_ids', 'consent_revision', 'cancellation_generation',
                'budget_reservation_id', 'retention_policy_id', 'deadline_monotonic_ms',
                'research_scope', 'output_preferences'),
    'instruction': ('schema', 'request_id', 'move', 'answer', 'claims', 'annotations',
                    'requested_response', 'reveal_level', 'expected_progress', 'execution_request'),
    'observation': ('schema', 'observation_id', 'session_id', 'capture_epoch', 'source_id',
        'source_kind', 'source_revision', 'user_id', 'tenant_id', 'project_id', 'consent_revision',
        'captured_at_utc', 'captured_at_monotonic_ms', 'expires_at_monotonic_ms', 'geometry_revision',
        'geometry', 'modalities', 'media', 'artifact_ref', 'content_sha256', 'retention_policy_id'),
}
OPERATIONS = {'HOST': frozenset(('CAPTURE_AUTHORIZATION', 'FRAME_ACCEPTED', 'ANSWER', 'PRESENTATION_RETIRED', 'PAUSE', 'STOP', 'UNAVAILABLE', 'REFUSAL', 'PRACTICE_RESULT')),
              'NATIVE': frozenset(('SELECT_SOURCE', 'FRAME', 'OBSERVATION', 'ASK', 'QUESTION', 'PAUSE', 'STOP', 'UNAVAILABLE', 'REFUSAL', 'PRACTICE_REQUEST'))}
REPLIES = {'ASK': 'ANSWER', 'QUESTION': 'ANSWER', 'SELECT_SOURCE': 'CAPTURE_AUTHORIZATION', 'FRAME': 'FRAME_ACCEPTED', 'PRACTICE_REQUEST': 'PRACTICE_RESULT'}


def _operation(kind, sender, reply_to, pending, deadline):
    if kind not in OPERATIONS[sender]:
        raise TransportRefusal('message is outside sender role')
    if kind in ('ANSWER', 'CAPTURE_AUTHORIZATION', 'FRAME_ACCEPTED', 'PRACTICE_RESULT') or reply_to is not None:
        prior = pending.get(reply_to)
        if prior is None or kind not in (REPLIES[prior[0]], 'REFUSAL', 'UNAVAILABLE'):
            raise TransportRefusal('reply does not match a pending request')
        if deadline > prior[1]:
            raise TransportRefusal('reply exceeds original request lifetime')
    elif kind in REPLIES and len(pending) >= 128:
        raise TransportRefusal('pending request limit reached')


class TransportRefusal(ValueError):
    """Untrusted, stale, malformed or unauthenticated bridge message."""


class StaleBridgeMessage(TransportRefusal):
    """Authenticated ordered application frame consumed, with no content release."""


def _int(value, minimum=0):
    if type(value) is not int or not minimum <= value <= MAX_INT:
        raise TransportRefusal('integer outside bridge range')
    return value


def _depth(value, level=1):
    if level > MAX_DEPTH:
        raise TransportRefusal('bridge nesting exceeds limit')
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise TransportRefusal('bridge object keys must be strings')
            key.encode('utf-8')
        for item in value.values():
            _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value:
            _depth(item, level + 1)
    elif type(value) is float and not math.isfinite(value):
        raise TransportRefusal('nonfinite bridge number')
    elif type(value) is int and not -MAX_INT - 1 <= value <= MAX_INT:
        raise TransportRefusal('bridge integer outside signed64 range')
    elif isinstance(value, str):
        value.encode('utf-8')  # Unpaired surrogates are not interoperable Unicode.


def _lesson_shape(kind, value):
    contracts._record(value, LESSON_FIELDS[kind])
    if value['schema'] != 'fleet.tutor.' + kind + '.v1':
        raise TransportRefusal('invalid nested lesson schema')
    if kind == 'request':
        for field in ('request_id', 'session_id', 'user_id', 'tenant_id', 'project_id',
                      'budget_reservation_id', 'retention_policy_id', 'consent_revision'):
            contracts._ident(value[field], field)
        contracts._enum(value['mode'], 'mode', contracts.MODES)
        contracts._enum(value['learning_intent'], 'learning_intent', contracts.LEARNING_INTENTS)
        contracts._string(value['question'], 'question', 8192)
        _int(value['deadline_monotonic_ms'], 1); _int(value['cancellation_generation'])
        contracts._enum(value['research_scope'], 'research_scope', ('SOURCE_ONLY', 'PERMITTED_RESEARCH'))
        for field in ('observation_ids', 'source_ids', 'skill_ids'):
            contracts._ident_list(value[field], field)
        preferences = contracts._record(value['output_preferences'], ('response_format', 'speech', 'locale'))
        contracts._enum(preferences['response_format'], 'response_format', ('TEXT', 'TEXT_AND_SCENE'))
        if type(preferences['speech']) is not bool:
            raise TransportRefusal('speech preference must be boolean')
        contracts._string(preferences['locale'], 'locale', 32)
    elif kind == 'instruction':
        contracts._ident(value['request_id'], 'request_id')
        for field, limit in (('move', 128), ('answer', 32768), ('requested_response', 2048)):
            contracts._string(value[field], field, limit)
        contracts._enum(value['reveal_level'], 'reveal_level', ('NONE', 'HINT', 'PARTIAL', 'DIRECT'))
        progress = contracts._record(value['expected_progress'], ('kind', 'scope'))
        contracts._ident(progress['kind'], 'kind'); contracts._string(progress['scope'], 'scope', 2048)
        for field in ('claims', 'annotations'):
            if not isinstance(value[field], list) or len(value[field]) > 128:
                raise TransportRefusal('lesson list outside bounds')
        for claim in value['claims']:
            contracts._record(claim, ('kind', 'text', 'evidence_refs', 'uncertainty'))
            contracts._ident(claim['kind'], 'kind'); contracts._string(claim['text'], 'text', 4096)
            contracts._ident_list(claim['evidence_refs'], 'evidence_refs')
            if type(claim['uncertainty']) not in (int, float) or not 0 <= claim['uncertainty'] <= 1:
                raise TransportRefusal('invalid claim uncertainty')
        for annotation in value['annotations']:
            contracts._record(annotation, ('primitive', 'observation_id', 'target_id', 'label', 'geometry_revision'))
            contracts._enum(annotation['primitive'], 'primitive', ('RECT', 'ARROW', 'POINT', 'LABEL'))
            for field in ('observation_id', 'target_id', 'geometry_revision'):
                contracts._ident(annotation[field], field)
            contracts._string(annotation['label'], 'label', 512)
        if value['execution_request'] is not None:
            action = contracts._record(value['execution_request'], ('operation', 'target_id', 'justification'))
            contracts._ident(action['operation'], 'operation'); contracts._ident(action['target_id'], 'target_id')
            contracts._string(action['justification'], 'justification', 2048)
    else:
        for field in ('observation_id', 'session_id', 'source_id', 'source_revision', 'user_id',
                      'tenant_id', 'project_id', 'consent_revision', 'geometry_revision', 'retention_policy_id'):
            contracts._ident(value[field], field)
        contracts._enum(value['source_kind'], 'source_kind', contracts.SOURCE_KINDS)
        _int(value['capture_epoch'])
        start = _int(value['captured_at_monotonic_ms']); end = _int(value['expires_at_monotonic_ms'])
        if end <= start or not isinstance(value['captured_at_utc'], str) or not contracts.UTC.fullmatch(value['captured_at_utc']):
            raise TransportRefusal('invalid observation lifetime')
        contracts._geometry(value['geometry'])
        modalities = contracts._ident_list(value['modalities'], 'modalities', 16)
        if not set(modalities).issubset(contracts.MODALITIES):
            raise TransportRefusal('unknown observation modality')
        if value['media'] is not None and not isinstance(value['media'], dict):
            raise TransportRefusal('invalid inert media metadata')
        contracts._string(value['artifact_ref'], 'artifact_ref', 512)
        if not isinstance(value['content_sha256'], str) or not contracts.SHA256.fullmatch(value['content_sha256']):
            raise TransportRefusal('invalid observation digest')


def _frame_shape(value, observation=None):
    contracts._record(value, ('schema', 'transfer_id', 'frame_receipt'))
    if value['schema'] != 'fleet.tutor.frame-reference.v1':
        raise TransportRefusal('unsupported frame reference')
    contracts._ident(value['transfer_id'], 'transfer_id')
    receipt = contracts._record(value['frame_receipt'], ('frame_id', 'source_id', 'source_revision',
        'capture_epoch', 'captured_at_monotonic_ms', 'width', 'height', 'pixel_format', 'size_bytes', 'content_sha256'))
    for field in ('frame_id', 'source_id', 'source_revision'):
        contracts._ident(receipt[field], field)
    width = _int(receipt['width'], 1); height = _int(receipt['height'], 1)
    if width > 8192 or height > 8192 or not 0 < width * height * 4 <= 32 * 1024 * 1024:
        raise TransportRefusal('frame dimensions outside bounds')
    if receipt['pixel_format'] not in ('BGRA8', 'BGRA8_PREMULTIPLIED') or _int(receipt['size_bytes'], 1) != width * height * 4:
        raise TransportRefusal('invalid exact BGRA frame length')
    _int(receipt['capture_epoch'], 1); _int(receipt['captured_at_monotonic_ms'])
    if not isinstance(receipt['content_sha256'], str) or not contracts.SHA256.fullmatch(receipt['content_sha256']):
        raise TransportRefusal('invalid frame digest')
    if observation is None:
        return
    for field in ('source_id', 'source_revision', 'capture_epoch', 'captured_at_monotonic_ms', 'content_sha256'):
        if receipt[field] != observation[field]:
            raise TransportRefusal('frame and observation binding mismatch')
    if width != observation['geometry']['source_width'] or height != observation['geometry']['source_height']:
        raise TransportRefusal('frame geometry mismatch')


def _question_shape(body):
    contracts._record(body, BODY_FIELDS['QUESTION'])
    for field in ('request_id', 'observation_id'):
        contracts._ident(body[field], field)
    contracts._string(body['question'], 'question', 8192)
    if not body['question'].strip():
        raise TransportRefusal('question is empty')
    contracts._enum(body['learning_intent'], 'learning_intent', contracts.LEARNING_INTENTS)
    contracts._string(body['locale'], 'locale', 32)


def _shape(message):
    contracts._record(message, FIELDS)
    if message['schema'] != 'fleet.tutor.bridge.v1' or message['protocol_version'] not in ('1.1', '1.2'):
        raise TransportRefusal('unsupported bridge protocol')
    for field in ('session_id', 'message_id'):
        contracts._ident(message[field], field)
    if message['reply_to'] is not None:
        contracts._ident(message['reply_to'], 'reply_to')
    for field in ('bridge_epoch', 'sequence', 'deadline_monotonic_ms'):
        _int(message[field], 1)
    _int(message['cancellation_generation'])
    kind = message['message_type']
    if not isinstance(kind, str) or kind not in BODY_FIELDS:
        raise TransportRefusal('unknown bridge message type')
    body = contracts._record(message['body'], BODY_FIELDS[kind], ('presentation',) if kind == 'ANSWER' else ())
    if kind in ('PRACTICE_REQUEST', 'PRACTICE_RESULT'):
        if message['protocol_version'] != '1.2':
            raise TransportRefusal('practice requires mutually selected bridge1.2')
        if kind == 'PRACTICE_REQUEST':
            if body['schema'] != 'fleet.tutor.practice-request.v1':
                raise TransportRefusal('unsupported practice request')
            contracts._enum(body['operation'], 'operation', ('STATUS', 'START', 'UPLOAD', 'SUBMIT', 'CANCEL'))
            fields = ('artifact_base64',) if body['operation'] == 'UPLOAD' else ()
            payload = contracts._record(body['payload'], fields)
            if fields:
                value = payload['artifact_base64']
                if not isinstance(value, str) or not 0 < len(value) <= 349528:
                    raise TransportRefusal('practice artifact exceeds bounds')
                try:
                    raw = base64.b64decode(value, validate=True)
                except (ValueError, TypeError) as error:
                    raise TransportRefusal('invalid practice artifact encoding') from error
                if not 0 < len(raw) <= 256 * 1024 or base64.b64encode(raw).decode('ascii') != value:
                    raise TransportRefusal('invalid or oversized practice artifact')
        else:
            if body['schema'] != 'fleet.tutor.practice-result.v1':
                raise TransportRefusal('unsupported practice result')
            contracts._enum(body['state'], 'state', ('ASSIGNED', 'ACTIVE', 'SUBMITTED', 'CANCELLED'))
            if body['attempt_id'] is not None: contracts._ident(body['attempt_id'], 'attempt_id')
            if _int(body['artifact_count']) > 8: raise TransportRefusal('artifact count outside bounds')
            for field in ('predicate_correct', 'passing'):
                if body[field] is not None and type(body[field]) is not bool:
                    raise TransportRefusal('invalid practice predicate')
            if type(body['independent_success']) is not bool: raise TransportRefusal('invalid independence')
            contracts._enum(body['projection_status'], 'projection_status', ('UNASSESSED', 'CURRENT', 'STALE_EXPOSURE', 'UNAVAILABLE'))
            contracts._enum(body['qualification'], 'qualification', ('UNASSESSED', 'LOCAL_ONLY', 'REVIEWED_PACK'))
    if kind == 'PRESENTATION_RETIRED':
        from tutor_presentation import BINDING_FIELDS
        binding = contracts._record(body['binding'], BINDING_FIELDS)
        for name in BINDING_FIELDS:
            if name in ('capture_epoch', 'cancellation_generation'):
                _int(binding[name], 1 if name == 'capture_epoch' else 0)
            elif name == 'content_sha256':
                if not isinstance(binding[name], str) or not contracts.SHA256.fullmatch(binding[name]):
                    raise TransportRefusal('invalid retirement digest')
            else:
                contracts._ident(binding[name], name)
        contracts._ident(body['reason_code'], 'reason_code')
        if message['reply_to'] is not None:
            raise TransportRefusal('retirement is unsolicited')
    if kind == 'QUESTION':
        _question_shape(body)
    if kind in ('HELLO', 'HELLO_ACK'):
        contracts._enum(body['peer'], 'peer', ('HOST', 'NATIVE'))
        for field in ('challenge', 'echo_challenge'):
            if field in body and (not isinstance(body[field], str) or not contracts.SHA256.fullmatch(body[field])):
                raise TransportRefusal('invalid handshake challenge')
    if kind in ('PAUSE', 'STOP', 'UNAVAILABLE', 'REFUSAL'):
        contracts._ident(body['reason_code'], 'reason_code')
        if 'detail' in body:
            contracts._string(body['detail'], 'detail', 4096)
    if kind == 'SELECT_SOURCE':
        for field in ('source_id', 'source_revision'):
            contracts._ident(body[field], field)
        contracts._string(body['display_name'], 'display_name', 512)
        contracts._enum(body['source_kind'], 'source_kind', contracts.SOURCE_KINDS)
        if not isinstance(body['native_handle_digest'], str) or not contracts.SHA256.fullmatch(body['native_handle_digest']):
            raise TransportRefusal('invalid native handle digest')
        if not 1 <= _int(body['width']) <= 8192 or not 1 <= _int(body['height']) <= 8192:
            raise TransportRefusal('source dimensions outside bounds')
        if body['width'] * body['height'] * 4 > 32 * 1024 * 1024:
            raise TransportRefusal('source exceeds frame limit')
        _int(body['capture_epoch'], 1)
    if kind == 'CAPTURE_AUTHORIZATION':
        if body['schema'] != 'fleet.tutor.capture-authorization.v1' or body['grant_created'] is not False:
            raise TransportRefusal('capture authorization cannot mint a grant')
        for field in ('session_id', 'source_id', 'source_revision', 'consent_revision'):
            contracts._ident(body[field], field)
        _int(body['capture_epoch'], 1)
        _int(body['cancellation_generation'])
        now = _int(body['now_monotonic_ms'])
        expiry = _int(body['expires_at_monotonic_ms'], 1)
        if not 0 < expiry - now <= 900000:
            raise TransportRefusal('capture authorization lifetime outside limit')
    # Structural checks are independent of live authority; receivers must still
    # verify current identity, source, target, memory bytes and permission.
    for field in ('request', 'instruction', 'observation', 'frame_reference'):
        if field in body and not isinstance(body[field], dict):
            raise TransportRefusal('nested bridge record must be an object')
        if field in body and field in LESSON_FIELDS:
            _lesson_shape(field, body[field])
    if 'presentation' in body:
        from tutor_presentation import validate_presentation
        validate_presentation(body['presentation'], request_id=body['instruction']['request_id'],
                              deadline_ms=message['deadline_monotonic_ms'])
    if kind == 'OBSERVATION':
        _frame_shape(body['frame_reference'], body['observation'])
    if kind == 'FRAME':
        _frame_shape(body['frame_reference'])
    _depth(message)


def _key(key):
    if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
        raise TransportRefusal('bridge key requires at least 32 bytes')


def encode_message(key, envelope):
    try:
        _key(key)
        _shape(envelope)
        unsigned = contracts.canonical_json(envelope).encode('utf-8')
        mac = hmac.new(key, unsigned, hashlib.sha256).hexdigest().encode('ascii')
        raw = unsigned[:-1] + b',"mac":"' + mac + b'"}'
        if len(raw) > MAX_BYTES:
            raise TransportRefusal('bridge message exceeds limit')
        return raw
    except (contracts.ContractViolation, TypeError, ValueError, RecursionError, UnicodeError) as error:
        raise TransportRefusal('invalid bridge message') from error


def decode_message(key, raw, expected, now_ms):
    try:
        _key(key)
        _int(now_ms)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
            raise TransportRefusal('invalid bridge length')
        trailer = MAC_TRAILER.search(raw)
        if trailer is None:
            raise TransportRefusal('missing final authentication member')
        unsigned = raw[:trailer.start()] + b'}'
        computed = hmac.new(key, unsigned, hashlib.sha256).hexdigest().encode('ascii')
        if not hmac.compare_digest(computed, trailer[1]):
            raise TransportRefusal('bridge authentication failed')
        message = contracts.decode_wire(raw)
        mac = message.pop('mac')
        _shape(message)
        contracts._record(expected, ('session_id', 'bridge_epoch', 'sequence', 'cancellation_generation'))
        for field in expected:
            if type(message[field]) is not type(expected[field]) or message[field] != expected[field]:
                raise TransportRefusal('stale or foreign bridge message')
        if message['deadline_monotonic_ms'] <= now_ms:
            raise TransportRefusal('expired bridge message')
        return {**message, 'mac': mac}
    except (contracts.ContractViolation, KeyError, TypeError, ValueError, RecursionError) as error:
        raise TransportRefusal('bridge message refused') from error


def gateway_deadline(deadline_ms, *, bridge_now_ms, gateway_now_ms):
    """Convert remaining wire lifetime; never assume equal clock epochs."""
    remaining = _int(deadline_ms, 1) - _int(bridge_now_ms)
    if remaining <= 0:
        raise TransportRefusal('expired bridge deadline')
    return _int(_int(gateway_now_ms) + remaining)


def windows_monotonic_ms():
    """Shared Windows GetTickCount64 domain; native uses Environment.TickCount64.

    Lazy call keeps optional feature-off imports free of native calls.
    """
    import os
    if os.name != 'nt':
        raise TransportRefusal('native bridge requires Windows clock')
    import ctypes
    clock = ctypes.WinDLL('kernel32', use_last_error=True).GetTickCount64
    clock.argtypes = []
    clock.restype = ctypes.c_ulonglong
    return clock()


class BridgeSession:
    """Per-launch mutual proof and ordered receive state, owned by the host/client.

    Pure codec state only: pipe IO and its deadlines/cancellation are separate.
    The key is never serialized. No operational dispatch happens here.
    """
    def __init__(self, key, session_id, bridge_epoch, peer, *, protocol_version='1.1'):
        _key(key)
        contracts._ident(session_id, 'session_id')
        _int(bridge_epoch, 1)
        if peer not in ('HOST', 'NATIVE'):
            raise TransportRefusal('unknown peer role')
        if protocol_version not in ('1.1', '1.2'):
            raise TransportRefusal('unsupported bridge version')
        self.protocol_version = protocol_version
        self._key = bytearray(key)
        self.session_id, self.epoch, self.peer = session_id, bridge_epoch, peer
        self._challenge = secrets.token_hex(32)
        self._remote_challenge = None
        self._handshake_reply = None
        self._phase = 'NEW'
        self._sent = self._received = 0
        self.cancellation_generation = 0
        self.accepted_history = deque(maxlen=128)
        self._pending_sent = {}
        self._pending_received = {}
        self._gate = threading.RLock()

    @property
    def ready(self):
        return self._phase == 'READY'

    def close(self):
        with self._gate:
            self._phase = 'CLOSED'
            self._key[:] = b'\0' * len(self._key)
            self._pending_sent.clear(); self._pending_received.clear()
            self.accepted_history.clear()

    def _encode(self, kind, body, deadline, reply_to=None):
        message = {'schema': 'fleet.tutor.bridge.v1', 'protocol_version': self.protocol_version,
                   'session_id': self.session_id, 'bridge_epoch': self.epoch,
                   'sequence': self._sent + 1, 'message_id': secrets.token_hex(16),
                   'reply_to': reply_to, 'deadline_monotonic_ms': deadline,
                   'cancellation_generation': self.cancellation_generation,
                   'message_type': kind, 'body': body}
        raw = encode_message(self._key, message)
        self._sent += 1
        return raw, message['message_id']

    def start(self, deadline_ms):
        with self._gate:
            if self.peer != 'HOST' or self._phase != 'NEW':
                raise TransportRefusal('unexpected HELLO start')
            raw, message_id = self._encode('HELLO', {'peer': self.peer, 'challenge': self._challenge}, deadline_ms)
            self._handshake_reply = message_id
            self._phase = 'WAIT_NATIVE_ACK'
            return raw

    def acknowledge(self, deadline_ms):
        with self._gate:
            if self._phase not in ('SEND_NATIVE_ACK', 'SEND_HOST_ACK'):
                raise TransportRefusal('no handshake challenge to answer')
            raw, message_id = self._encode('HELLO_ACK',
                {'peer': self.peer, 'challenge': self._challenge,
                 'echo_challenge': self._remote_challenge}, deadline_ms, self._handshake_reply)
            if self.peer == 'NATIVE':
                self._phase = 'WAIT_HOST_ACK'
                self._handshake_reply = message_id
            else:
                self._phase = 'READY'
            return raw

    def send(self, kind, body, deadline_ms, *, reply_to=None):
        with self._gate:
            if not self.ready or kind in ('HELLO', 'HELLO_ACK'):
                raise TransportRefusal('mutual handshake required before operations')
            _operation(kind, self.peer, reply_to, self._pending_received, deadline_ms)
            if kind in REPLIES and len(self._pending_sent) >= 128:
                raise TransportRefusal('pending request limit reached')
            raw, message_id = self._encode(kind, body, deadline_ms, reply_to)
            if kind in REPLIES:
                self._pending_sent[message_id] = (kind, deadline_ms)
            if reply_to is not None:
                del self._pending_received[reply_to]
            return raw

    def advance_generation(self, generation):
        """Host/client supervisor supplies current generation; never native text."""
        with self._gate:
            _int(generation)
            if generation < self.cancellation_generation:
                raise TransportRefusal('cancellation generation cannot regress')
            if generation != self.cancellation_generation:
                self.cancellation_generation = generation
                self._pending_sent.clear()
                self._pending_received.clear()

    def expire_pending(self, now_ms):
        """Current supervisor clock reclaims expired correlation slots only."""
        with self._gate:
            _int(now_ms)
            for pending in (self._pending_sent, self._pending_received):
                for message_id, (_, deadline) in list(pending.items()):
                    if deadline <= now_ms:
                        del pending[message_id]

    def receive(self, raw, now_ms):
        with self._gate:
            _int(now_ms)
            self.expire_pending(now_ms)
            try:
                wire_generation = contracts.decode_wire(raw)['cancellation_generation']
            except (contracts.ContractViolation, KeyError, RecursionError, ValueError) as error:
                raise TransportRefusal('invalid bridge generation') from error
            message = decode_message(self._key, raw,
                {'session_id': self.session_id, 'bridge_epoch': self.epoch,
                 'sequence': self._received + 1,
                 'cancellation_generation': wire_generation}, 0)
            kind, body = message['message_type'], message['body']
            if message['protocol_version'] != self.protocol_version:
                raise TransportRefusal('bridge version differs from launch selection')
            phase = self._phase
            if wire_generation > self.cancellation_generation:
                raise TransportRefusal('future cancellation generation')
            if wire_generation < self.cancellation_generation or message['deadline_monotonic_ms'] <= now_ms:
                sender = 'NATIVE' if self.peer == 'HOST' else 'HOST'
                if self.ready and kind in OPERATIONS[sender]:
                    self._received += 1
                    self.accepted_history.append((message['sequence'], hashlib.sha256(raw).hexdigest()))
                    raise StaleBridgeMessage('stale generation or expired authenticated message discarded')
                raise TransportRefusal('stale generation or expired authenticated message discarded')
            if kind == 'HELLO':
                if self.peer != 'NATIVE' or phase != 'NEW' or body['peer'] != 'HOST' or message['reply_to'] is not None:
                    raise TransportRefusal('unexpected or reflected HELLO')
                phase = 'SEND_NATIVE_ACK'
            elif kind == 'HELLO_ACK':
                expected_phase = 'WAIT_NATIVE_ACK' if self.peer == 'HOST' else 'WAIT_HOST_ACK'
                remote_peer = 'NATIVE' if self.peer == 'HOST' else 'HOST'
                if (phase != expected_phase or body['peer'] != remote_peer
                        or body['echo_challenge'] != self._challenge
                        or message['reply_to'] != self._handshake_reply):
                    raise TransportRefusal('handshake peer/challenge/correlation mismatch')
                if self.peer == 'NATIVE' and body['challenge'] != self._remote_challenge:
                    raise TransportRefusal('host challenge changed')
                phase = 'SEND_HOST_ACK' if self.peer == 'HOST' else 'READY'
            elif not self.ready:
                raise TransportRefusal('operational message before mutual proof')
            else:
                sender = 'NATIVE' if self.peer == 'HOST' else 'HOST'
                _operation(kind, sender, message['reply_to'], self._pending_sent, message['deadline_monotonic_ms'])
                if kind in REPLIES and len(self._pending_received) >= 128:
                    raise TransportRefusal('pending request limit reached')
            # Failed validation never advances accepted sequence or handshake.
            if kind in ('HELLO', 'HELLO_ACK'):
                self._remote_challenge = body['challenge']
                self._handshake_reply = message['message_id']
            self._phase = phase
            if kind in REPLIES:
                self._pending_received[message['message_id']] = (kind, message['deadline_monotonic_ms'])
            if kind not in ('HELLO', 'HELLO_ACK') and message['reply_to'] is not None:
                del self._pending_sent[message['reply_to']]
            self._received += 1
            self.accepted_history.append((message['sequence'], hashlib.sha256(raw).hexdigest()))
            return message
