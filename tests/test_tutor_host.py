#!/usr/bin/env python3
"""Actual host-policy answer release; controlled fixtures, no live provider."""
import copy
import sys
import importlib.util
import threading
from unittest.mock import patch, ANY
from dataclasses import replace

from common import AGENT_DIR
sys.path.insert(0, AGENT_DIR)
import tutor_contracts as contracts
from tutor_service import TutorService, TutorUnavailable
from tutor_session import TutorSession, SelectedSource, SessionRefusal
from learning_contracts import LearningService, LearningAdapter


def check_host_launch_lifecycle():
    from tutor_host import NativeTutorHost
    _, _, _, _, owner = fixture()
    learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), lambda: copy.deepcopy(owner), learning.adapter('native_companion', binding))
    assert callable(getattr(host, 'launch', None)), 'sealed tutor host has no native startup route'
    class Peer:
        ready = True
        def stop(self): self.ready = False
    peer = Peer()
    with patch('tutor_connection.launch', return_value=peer) as launched:
        assert host.launch(None, timeout_ms=5000) is peer
        launched.assert_called_once_with(None, enabled=True, timeout_ms=5000, stop_event=ANY)
        host.stop()
        assert not peer.ready, 'host Stop retained owned child connection'
    late = Peer()
    def stop_during_start(*args, **kwargs):
        host.stop(); return late
    with patch('tutor_connection.launch', side_effect=stop_during_start):
        refused(lambda: host.launch(None, timeout_ms=5000))
        assert not late.ready, 'late native startup escaped host Stop'
    entered = threading.Event(); release = threading.Event(); done = threading.Event()
    def pending_start(*args, **kwargs):
        entered.set()
        while not release.wait(0.01):
            token = kwargs.get('stop_event')
            if token is not None and token.is_set():
                from tutor_connection import ConnectionUnavailable
                raise ConnectionUnavailable('controlled pending startup cancelled')
        return Peer()
    def start_pending():
        try: host.launch(None, timeout_ms=5000)
        except (TutorUnavailable, __import__('tutor_connection').ConnectionUnavailable): pass
        finally: done.set()
    with patch('tutor_connection.launch', side_effect=pending_start):
        worker = threading.Thread(target=start_pending); worker.start()
        try:
            assert entered.wait(1)
            host.stop()
            assert done.wait(0.5), 'host Stop cannot cancel startup before a connection is published'
        finally:
            release.set(); worker.join(1)
    print('[host launch] current sealed owner launch, pending-start cancellation and Stop/late-start suppression checked without process/model calls')


def fixture():
    session = TutorSession("session-1", "user-1", "tenant-1", "project-1", ["source-1"])
    session.invoke()
    session.select_source(SelectedSource("source-1", "WINDOW", "source-r4", "a" * 64))
    data = copy.deepcopy(contracts.fixture_bundle()["records"])
    request, observation, instruction = data["request"], data["observation"], data["instruction"]
    request["cancellation_generation"] = session.cancellation_generation
    observation["capture_epoch"] = session.capture_epoch
    owner = {"user_id": "user-1", "tenant_id": "tenant-1", "project_id": "project-1",
             "consent_revision": "consent-r3", "capture_epoch": session.capture_epoch,
             "source_ids": ["source-1"], "source_revisions": {"source-1": "source-r4"},
             "observation_ids": ["obs-1"], "artifact_refs": ["artifact-1"],
             "now_monotonic_ms": 2000, "cancellation_generation": session.cancellation_generation,
             "current_cancellation_generation": session.cancellation_generation,
             "grant_expires_at_monotonic_ms": 9000, "mode": "GUIDE", "actor": "SYSTEM",
             "grant_view": ["observe", "explain", "annotate"],
             "budget_reservation_ids": ["budget-1"], "retention_policy_ids": ["retention-1"]}
    return session, request, observation, instruction, owner


def check_source_selection_keeps_bridge():
    from tutor_host import NativeTutorHost
    _, _, _, _, owner = fixture(); learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), lambda: copy.deepcopy(owner), learning.adapter('native_companion', binding))
    class Peer:
        ready = True
        def stop(self): self.ready = False
    peer = Peer()
    with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
    receipt = {'source_id': 'source-1', 'display_name': 'Owned source', 'source_kind': 'WINDOW',
               'source_revision': 'source-r4', 'native_handle_digest': 'a' * 64,
               'width': 322, 'height': 272, 'capture_epoch': owner['capture_epoch']}
    authorization = host.select_source(receipt)
    assert peer.ready and host._connection is peer, 'source selection terminated its authenticated native bridge'
    assert authorization['source_id'] == receipt['source_id']
    host.stop()
    assert not peer.ready
    print('[host selection lifecycle] source authorization preserves bridge; whole-host Stop closes it')


def check_host_frame_store():
    from tutor_host import NativeTutorHost
    from tutor_frames import FrameMemoryReader
    import tutor_frames
    _, _, _, _, owner = fixture(); learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), lambda: copy.deepcopy(owner), learning.adapter('native_companion', binding))
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def create_frame_reader(self, current):
            return FrameMemoryReader('bridge-1', bytes(range(32)), current, clock_ms=lambda: 3000)
    with patch('tutor_connection.launch', return_value=Peer()): host.launch(None, timeout_ms=5000)
    receipt = {'source_id': 'source-1', 'display_name': 'Owned source', 'source_kind': 'WINDOW',
               'source_revision': 'source-r4', 'native_handle_digest': 'a' * 64, 'width': 2, 'height': 1,
               'capture_epoch': owner['capture_epoch']}
    host.select_source(receipt)
    assert callable(getattr(host, 'consume_frame', None)), 'sealed host has no source-current frame image admission'
    pixels = bytearray([0, 0, 128, 128, 30, 20, 10, 255])
    reference = {'schema': 'fleet.tutor.frame-reference.v1', 'transfer_id': 'b' * 32,
        'frame_receipt': {'frame_id': 'frame-1', 'source_id': 'source-1', 'source_revision': 'source-r4',
            'capture_epoch': owner['capture_epoch'], 'captured_at_monotonic_ms': 2500, 'width': 2, 'height': 1,
            'pixel_format': 'BGRA8_PREMULTIPLIED', 'size_bytes': 8,
            'content_sha256': __import__('hashlib').sha256(pixels).hexdigest()}}
    with patch.object(tutor_frames, '_read_protected_mapping', return_value=pixels):
        image = host.consume_frame(reference)
    assert image['artifact_ref'].startswith('observation://') and host._images._items
    assert all(value == 0 for value in pixels)
    host.stop_sharing()
    assert not host._images._items and host._connection.ready
    host.stop()
    print('[host frame store] current sealed source admits PNG; source Stop wipes images without closing bridge')


def refused(call):
    try:
        result = call()
    except (TutorUnavailable, contracts.ContractViolation, SessionRefusal):
        return
    assert isinstance(result, dict) and result.get("allowed") is False and "instruction" not in result, result


def check_current_answer_release():
    session, request, observation, instruction, owner = fixture()
    calls = []
    service = TutorService(enabled=True, dispatch=lambda req, obs: calls.append(req) or instruction)
    method = getattr(service, "ask_current", None)
    assert callable(method), "actual answer release has no live host-policy reader route"
    result = method(request, lambda: copy.deepcopy(owner), [observation], session)
    assert result["allowed"] and result["instruction"] == instruction
    assert len(calls) == 1
    instruction["answer"] = "changed after service release"
    assert result["instruction"]["answer"] != instruction["answer"], "released answer aliases mutable adapter output"
    bad = copy.deepcopy(request); bad["user_id"] = "other-user"
    refused(lambda: method(bad, lambda: copy.deepcopy(owner), [observation], session))
    refused(lambda: method(request, lambda: copy.deepcopy(owner), [], session))
    foreign_observation = copy.deepcopy(observation)
    foreign_observation["session_id"] = "other-session"
    refused(lambda: method(request, lambda: copy.deepcopy(owner), [foreign_observation], session))
    assert len(calls) == 1, "refused request dispatched model work"
    refused(lambda: method(request, owner, [observation], session))
    refused(lambda: TutorService(enabled=True).ask_current(request, lambda: owner, [observation], session))
    def unavailable_owner():
        raise AssertionError("feature-off read host policy")
    refused(lambda: TutorService(enabled=False, dispatch=lambda *_: None).ask_current(
        request, unavailable_owner, [observation], session))
    malformed = copy.deepcopy(instruction); malformed['answer'] = None
    invalid_calls = []
    invalid_service = TutorService(enabled=True, dispatch=lambda *_: invalid_calls.append(True) or malformed)
    invalid = invalid_service.ask_current(request, lambda: copy.deepcopy(owner), [observation], session)
    assert not invalid['allowed'] and invalid['reason_code'] == 'INVALID_SCHEMA'
    assert invalid.get('failure_stage') == 'INSTRUCTION_VALIDATION' and 'instruction' not in invalid
    malformed_request = copy.deepcopy(request); malformed_request['output_preferences']['speech'] = 'invalid'
    invalid_input = invalid_service.ask_current(malformed_request, lambda: copy.deepcopy(owner), [observation], session)
    assert not invalid_input['allowed'] and invalid_input.get('failure_stage') is None
    assert len(invalid_calls) == 1, 'invalid request was dispatched or mislabeled as provider output'
    print("[host-answer] actual validated instruction returned defensively; wrong identity/missing observation/unready/feature-off dispatch nothing")


def check_late_host_changes():
    for event in ("grant", "consent", "identity", "revision", "epoch", "expiry", "stop"):
        session, request, observation, instruction, owner = fixture()
        current = [copy.deepcopy(owner)]
        calls = []
        def dispatch(req, obs):
            calls.append(req)
            changed = copy.deepcopy(owner)
            if event == "grant": changed["grant_view"] = []
            elif event == "consent": changed["consent_revision"] = "revoked-consent"
            elif event == "identity": changed["tenant_id"] = "other-tenant"
            elif event == "revision": changed["source_revisions"]["source-1"] = "changed-source"
            elif event == "epoch": changed["capture_epoch"] += 1
            elif event == "expiry": changed["now_monotonic_ms"] = 10000
            elif event == "stop": session.stop()
            current[0] = changed
            return copy.deepcopy(instruction)
        service = TutorService(enabled=True, dispatch=dispatch)
        refused(lambda: service.ask_current(request, lambda: copy.deepcopy(current[0]), [observation], session))
        assert len(calls) == 1
    session, request, observation, instruction, owner = fixture()
    forged = copy.deepcopy(instruction); forged["request_id"] = "foreign-request"
    refused(lambda: TutorService(enabled=True, dispatch=lambda *_: forged).ask_current(
        request, lambda: owner, [observation], session))
    print("[host-release] grant/consent/identity/revision/epoch/deadline/Stop changes and forged instructions release no answer")


def check_sealed_host_adapter():
    spec = importlib.util.find_spec("tutor_host")
    assert spec is not None, "actual sealed-learning native host adapter is missing"
    from tutor_host import NativeTutorHost
    _, request, observation, instruction, owner = fixture()
    owner["capture_epoch"] = 3
    learning = LearningService()
    binding = learning.bind_host("user-1", "tenant-1", "policy-1", "grant-1", "course-1",
                                 ["learning:read", "session:write"], ["capture.selected"])
    adapter = learning.adapter("native_companion", binding)
    calls = []
    service = TutorService(enabled=True, dispatch=lambda req, obs: calls.append(req) or {**instruction, "request_id": req["request_id"]})
    host = NativeTutorHost(service, lambda: copy.deepcopy(owner), adapter)
    receipt = {"source_id": "source-1", "display_name": "Test-owned source", "source_kind": "WINDOW",
               "source_revision": "source-r4", "native_handle_digest": "a" * 64,
               "width": 322, "height": 272, "capture_epoch": 3}
    authorization = host.select_source(receipt)
    assert authorization["source_id"] == "source-1" and authorization["capture_epoch"] == 3
    assert authorization["expires_at_monotonic_ms"] <= owner["grant_expires_at_monotonic_ms"]
    request["session_id"] = authorization["session_id"]
    request["cancellation_generation"] = authorization["cancellation_generation"]
    observation["session_id"] = authorization["session_id"]
    observation["capture_epoch"] = 3
    owner["cancellation_generation"] = authorization["cancellation_generation"]
    owner["current_cancellation_generation"] = authorization["cancellation_generation"]
    result = host.ask(request, [observation])
    assert result["allowed"] and "instruction" in result and len(calls) == 1
    assert result["grant_created"] is False and result["learning_success_claimed"] is False
    bad = copy.deepcopy(request); bad["user_id"] = "intruder"
    refused(lambda: host.ask(bad, [observation]))
    host.stop()
    refused(lambda: host.ask(request, [observation]))
    assert len(calls) == 1
    forged = LearningAdapter(learning, "native_companion", replace(binding, principal_id="intruder"), {})
    refused(lambda: NativeTutorHost(service, lambda: owner, forged))
    refused(lambda: NativeTutorHost(service, lambda: owner, learning.adapter("embed_sdk", binding)))
    wrong = copy.deepcopy(owner); wrong["tenant_id"] = "other-tenant"
    refused(lambda: NativeTutorHost(service, lambda: wrong, adapter))
    late_owner = copy.deepcopy(owner)
    late_host = NativeTutorHost(service, lambda: copy.deepcopy(late_owner), adapter)
    original_command = adapter.command
    def revoke_after_open(operation, *args, **kwargs):
        response = original_command(operation, *args, **kwargs)
        if operation == "session.open": late_owner["grant_view"] = []
        return response
    adapter.command = revoke_after_open
    try:
        refused(lambda: late_host.select_source(receipt))
    finally:
        adapter.command = original_command
    switched_host = NativeTutorHost(service, lambda: owner, adapter)
    adapter._binding = learning.bind_host("other-user", "tenant-1", "policy-1", "grant-1", "course-1",
                                          ["learning:read", "session:write"], ["capture.selected"])
    try:
        refused(lambda: switched_host.select_source(receipt))
    finally:
        adapter._binding = binding
    print("[sealed-host] real learning.v1 binding, exact native epoch/session and finite source authorization; forged/cross-surface/cross-tenant/stopped requests refuse")


def check_stop_pending_selection():
    from tutor_host import NativeTutorHost
    _, _, _, instruction, owner = fixture()
    learning = LearningService()
    binding = learning.bind_host("user-1", "tenant-1", "policy-1", "grant-1", "course-1",
                                 ["learning:read", "session:write"], ["capture.selected"])
    entered = threading.Event(); release = threading.Event(); stopped = threading.Event()
    blocking = [False]; outcomes = []
    def reader():
        if blocking[0]:
            entered.set(); release.wait(3)
        return copy.deepcopy(owner)
    host = NativeTutorHost(TutorService(enabled=True, dispatch=lambda *_: instruction),
                           reader, learning.adapter("native_companion", binding))
    receipt = {"source_id": "source-1", "display_name": "Test-owned source", "source_kind": "WINDOW",
               "source_revision": "source-r4", "native_handle_digest": "a" * 64,
               "width": 322, "height": 272, "capture_epoch": owner["capture_epoch"]}
    blocking[0] = True
    def select():
        try: outcomes.append(host.select_source(receipt))
        except TutorUnavailable: outcomes.append("REFUSED")
    selection = threading.Thread(target=select)
    selection.start()
    assert entered.wait(1), "controlled host policy read did not start"
    stopper = threading.Thread(target=lambda: (host.stop(), stopped.set()))
    stopper.start()
    try:
        assert stopped.wait(0.5), "host Stop waited for a stalled selection policy reader"
    finally:
        release.set(); selection.join(2); stopper.join(2)
    assert outcomes == ["REFUSED"], "late source authorization survived Stop"
    print("[host-stop] stalled selection does not delay Stop and its late authorization is refused")


def check_source_boundaries():
    from tutor_host import NativeTutorHost
    _, _, _, instruction, owner = fixture()
    learning = LearningService()
    binding = learning.bind_host("user-1", "tenant-1", "policy-1", "grant-1", "course-1",
                                 ["learning:read", "session:write"], ["capture.selected"])
    service = TutorService(enabled=True, dispatch=lambda *_: instruction)
    current = [copy.deepcopy(owner)]
    host = NativeTutorHost(service, lambda: copy.deepcopy(current[0]), learning.adapter("native_companion", binding))
    receipt = {"source_id": "source-1", "display_name": "Test-owned source", "source_kind": "WINDOW",
               "source_revision": "source-r4", "native_handle_digest": "a" * 64,
               "width": 322, "height": 272, "capture_epoch": owner["capture_epoch"]}
    for key, value in [("source_id", "foreign-source"), ("source_revision", "foreign-revision"),
                       ("capture_epoch", True), ("capture_epoch", 0), ("capture_epoch", 99),
                       ("width", 8193), ("height", -1), ("native_handle_digest", "not-a-digest")]:
        bad = {**receipt, key: value}
        refused(lambda: host.select_source(bad))
    refused(lambda: host.select_source({**receipt, "user_id": "intruder"}))
    current[0]["grant_expires_at_monotonic_ms"] = current[0]["now_monotonic_ms"]
    refused(lambda: host.select_source(receipt))
    current[0]["grant_expires_at_monotonic_ms"] = 10_000_000
    allowed = host.select_source(receipt)
    assert allowed["expires_at_monotonic_ms"] - allowed["now_monotonic_ms"] == 900_000
    host.stop()
    refused(lambda: host.select_source(receipt))
    missing_capture = learning.bind_host("user-1", "tenant-1", "policy-1", "grant-1", "course-1",
                                         ["learning:read", "session:write"])
    refused(lambda: NativeTutorHost(service, lambda: owner, learning.adapter("native_companion", missing_capture)))
    session = TutorSession("epoch-session", "user-1", "tenant-1", "project-1", ["source-1"])
    session.invoke()
    source = SelectedSource("source-1", "WINDOW", "source-r4", "a" * 64)
    session.select_source(source, native_capture_epoch=7)
    session.source_unavailable("test-owned source loss")
    refused(lambda: session.select_source(source, native_capture_epoch=7))
    assert session.capture_epoch == 8 and session.source is None
    session.select_source(source, native_capture_epoch=9)
    assert session.capture_epoch == 9
    print("[host-selection] forged/malformed/expired/retired sources refuse, lifetime caps15min and native epochs stay exact")


def check_binding_changed_inside_policy_read():
    from tutor_host import NativeTutorHost
    _, request, observation, instruction, owner = fixture()
    learning = LearningService()
    binding = learning.bind_host("user-1", "tenant-1", "policy-1", "grant-1", "course-1",
                                 ["learning:read", "session:write"], ["capture.selected"])
    other = learning.bind_host("other-user", "tenant-1", "policy-1", "grant-1", "course-1",
                               ["learning:read", "session:write"], ["capture.selected"])
    adapter = learning.adapter("native_companion", binding)
    switch = [False]; calls = []
    def reader():
        if switch[0]: adapter._binding = other
        return copy.deepcopy(owner)
    host = NativeTutorHost(TutorService(enabled=True, dispatch=lambda *_: calls.append("dispatch") or instruction), reader, adapter)
    auth = host.select_source({"source_id": "source-1", "display_name": "Test-owned source", "source_kind": "WINDOW",
                               "source_revision": "source-r4", "native_handle_digest": "a" * 64,
                               "width": 322, "height": 272, "capture_epoch": owner["capture_epoch"]})
    request["session_id"] = auth["session_id"]
    observation["session_id"] = auth["session_id"]
    switch[0] = True
    try:
        refused(lambda: host.ask(request, [observation]))
        assert calls == [], "binding change during policy read reached model dispatch"
    finally:
        adapter._binding = binding
        host.stop()
    print("[host-binding-read] identity change inside the policy reader refuses before model dispatch")


def check_source_wire_dispatch():
    from tutor_host import NativeTutorHost
    _, _, _, _, owner = fixture(); learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), lambda: copy.deepcopy(owner), learning.adapter('native_companion', binding))
    receipt = {'source_id': 'source-1', 'display_name': 'Owned source', 'source_kind': 'WINDOW',
               'source_revision': 'source-r4', 'native_handle_digest': 'a' * 64,
               'width': 2, 'height': 1, 'capture_epoch': owner['capture_epoch']}
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def poll(self, **kwargs): return self.message
        def send(self, kind, body, **kwargs):
            actual_deadline = kwargs.get('deadline_ms', 3001 + kwargs['timeout_ms'])
            assert actual_deadline <= self.message['deadline_monotonic_ms'], 'elapsed send scheduling extended original source request lifetime'
            self.sent.append((kind, body, kwargs))
    peer = Peer(); peer.sent = []
    peer.message = {'message_type': 'SELECT_SOURCE', 'body': receipt, 'message_id': 'select-1', 'deadline_monotonic_ms': 5000}
    with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
    assert callable(getattr(host, 'serve_once', None)), 'authenticated native selection has no host wire dispatcher'
    with patch('tutor_transport.windows_monotonic_ms', return_value=3000):
        assert host.serve_once(timeout_ms=500)
        assert peer.sent[0][0] == 'CAPTURE_AUTHORIZATION'
        assert peer.sent[0][1]['grant_created'] is False
        options = dict(peer.sent[0][2]); release = options.pop('release_check')
        assert options == {'timeout_ms': 2000, 'reply_to': 'select-1', 'deadline_ms': 5000}
        assert callable(release) and release()
        owner['grant_view'] = []
        assert not release(), 'queued capture authority survived permission revocation'
        peer.message = {**peer.message, 'message_id': 'select-denied'}
        assert host.serve_once(timeout_ms=500)
        assert peer.sent[-1][0] == 'REFUSAL' and peer.sent[-1][2]['reply_to'] == 'select-denied'
        assert host._session is None and peer.ready
        peer.message = None; assert host.serve_once(timeout_ms=500) is False
        # A fresh native selection can be revoked after initial admission but
        # before writing the authorization reply. No stale grant may escape.
        owner['source_ids'] = ['source-2']; owner['source_revisions'] = {'source-2': 'source-r5'}
        owner['grant_view'] = ['observe']
        peer.message = {'message_type': 'SELECT_SOURCE', 'body': {**receipt, 'source_id': 'source-2', 'source_revision': 'source-r5'},
                        'message_id': 'select-late-revoked', 'deadline_monotonic_ms': 5000}
        def revoke_at_release():
            owner['grant_view'] = []
            return 3000
        with patch('tutor_transport.windows_monotonic_ms', side_effect=revoke_at_release):
            assert host.serve_once(timeout_ms=500)
        assert peer.sent[-1][0] == 'REFUSAL', 'late host revocation released a capture authorization'
    host.stop()
    print('[source wire] current sealed host selection replies are correlated; denied capture creates no grant')


def review_host():
    from tutor_host import NativeTutorHost
    _, _, _, _, owner = fixture()
    learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), lambda: copy.deepcopy(owner), learning.adapter('native_companion', binding))
    receipt = {'source_id': 'source-1', 'display_name': 'Owned source', 'source_kind': 'WINDOW',
               'source_revision': 'source-r4', 'native_handle_digest': 'a' * 64,
               'width': 2, 'height': 1, 'capture_epoch': owner['capture_epoch']}
    return host, owner, receipt


def check_one_way_pause():
    import tutor_transport as wire
    host, owner, receipt = review_host()
    hp = wire.BridgeSession(bytes(range(32)), 'review-bridge', 1, 'HOST')
    np = wire.BridgeSession(bytes(range(32)), 'review-bridge', 1, 'NATIVE')
    np.receive(hp.start(5000), 1000)
    hp.receive(np.acknowledge(5000), 1000)
    np.receive(hp.acknowledge(5000), 1000)
    message = hp.receive(np.send('PAUSE', {'reason_code': 'USER_PAUSE'}, 5000), 1000)
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def poll(self, **kwargs): return message
        def send(self, kind, body, **kwargs):
            np.receive(hp.send(kind, body, kwargs['deadline_ms'], reply_to=kwargs.get('reply_to')), 3000)
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        host.select_source(receipt)
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000):
            assert host.serve_once(timeout_ms=500)
        assert peer.ready and host._capture_authorization is None and host._session is None
    finally:
        host.stop(); hp.close(); np.close()
    print('[regression] authenticated one-way Pause retires source without an impossible reply')


def check_receive_across_stop():
    import tutor_transport as wire
    host, _, receipt = review_host()
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def poll(self, **kwargs):
            host.stop()
            return {'message_type': 'SELECT_SOURCE', 'message_id': 'stopped-select', 'body': receipt, 'deadline_monotonic_ms': 5000}
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000):
            refused(lambda: host.serve_once(timeout_ms=500))
        assert host._connection is None and host._session is None and host._capture_authorization is None
    finally: host.stop()
    print('[regression] receive completing across Stop cannot recreate source state')


def check_late_selection_revocation():
    original = TutorSession.select_source
    for change in (lambda owner: owner.update(grant_view=[]),
                   lambda owner: owner.update(consent_revision='new-consent'),
                   lambda owner: owner.update(cancellation_generation=99),
                   lambda owner: owner.update(capture_epoch=99),
                   lambda owner: owner.update(grant_expires_at_monotonic_ms=owner['now_monotonic_ms'])):
        host, owner, receipt = review_host()
        def revoke(session, *args, **kwargs):
            result = original(session, *args, **kwargs)
            change(owner)
            return result
        try:
            with patch.object(TutorSession, 'select_source', revoke):
                refused(lambda: host.select_source(receipt))
            assert host._session is None and host._capture_authorization is None
        finally: host.stop()
    print('[regression] late permission/consent/cancellation/epoch/expiry changes refuse direct authorization')


def check_expired_event_and_refusal_echo():
    import tutor_transport as wire
    host, _, receipt = review_host()
    class Peer:
        ready = True
        sent = []
        def stop(self): self.ready = False
        def poll(self, **kwargs): return self.message
        def send(self, *args, **kwargs): self.sent.append((args, kwargs))
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        peer.message = {'message_type': 'SELECT_SOURCE', 'message_id': 'expired-select', 'body': receipt, 'deadline_monotonic_ms': 3000}
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000), patch.object(host._learning, 'command', wraps=host._learning.command) as commands:
            assert host.serve_once(timeout_ms=500) is False
            assert commands.call_count == 0, 'expired event created a learning session before refusal'
        peer.message = {'message_type': 'REFUSAL', 'message_id': 'refusal-event', 'body': {'reason_code': 'UNAVAILABLE', 'detail': 'Owned fixture'}, 'deadline_monotonic_ms': 5000}
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000):
            assert host.serve_once(timeout_ms=500)
        assert not peer.sent, 'one-way REFUSAL was echoed back to its sender'
    finally: host.stop()
    print('[regression] expired events create no session and one-way refusals cannot echo')


def check_current_capture_supervision():
    host, owner, receipt = review_host()
    class Peer:
        ready = True
        def stop(self): self.ready = False
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        host.select_source(receipt)
        assert host.supervise_source() is True
        owner['grant_view'] = []
        assert host.supervise_source() is False
        assert host._session is None and host._capture_authorization is None and peer.ready
        assert host.supervise_source() is True
    finally: host.stop()
    print('[supervision] current capture revocation retires selected work while preserving the bridge')


def check_owned_host_loop():
    import threading
    host, _, _ = review_host()
    stop = threading.Event()
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def poll(self, **kwargs):
            assert 0 < kwargs['timeout_ms'] <= 100
            stop.set()
            return None
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        host.run(stop_event=stop)
        assert host._connection is None and not peer.ready
    finally: host.stop()
    print('[host loop] caller-owned cancellation and bounded idle polling close only the owned connection')


def check_supervision_source_replacement():
    host, owner, receipt = review_host()
    try:
        host.select_source(receipt)
        def replace_during_read():
            owner['source_ids'] = ['source-2']; owner['source_revisions'] = {'source-2': 'source-r5'}
            host.select_source({**receipt, 'source_id': 'source-2', 'source_revision': 'source-r5'})
            raise TutorUnavailable('old source authorization changed')
        with patch.object(host, '_frame_binding', side_effect=replace_during_read):
            assert host.supervise_source() is True, 'old-source supervision falsely revoked the new selection'
        assert host._capture_authorization['source_id'] == 'source-2'
    finally: host.stop()
    print('[supervision replacement] a late old-source policy result cannot retire or report revocation of its replacement')


def check_host_current_observation():
    from tutor_frames import FrameMemoryReader
    import tutor_frames, tutor_transport as wire, hashlib
    host, owner, receipt = review_host()
    host._images._clock_ms = lambda: 1_000_000
    class Peer:
        ready = True
        sent = []
        def stop(self): self.ready = False
        def poll(self, **kwargs): return self.message
        def send(self, kind, body, **kwargs): self.sent.append((kind, body, kwargs))
        def create_frame_reader(self, current):
            return FrameMemoryReader('bridge-1', bytes(range(32)), current, clock_ms=lambda: 3000)
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        auth = host.select_source(receipt); owner['now_monotonic_ms'] = 3000
        pixels = bytearray([0, 0, 128, 128, 30, 20, 10, 255])
        reference = {'schema': 'fleet.tutor.frame-reference.v1', 'transfer_id': 'b' * 32,
            'frame_receipt': {'frame_id': 'frame-1', 'source_id': 'source-1', 'source_revision': 'source-r4',
                'capture_epoch': owner['capture_epoch'], 'captured_at_monotonic_ms': 2500, 'width': 2, 'height': 1,
                'pixel_format': 'BGRA8_PREMULTIPLIED', 'size_bytes': 8, 'content_sha256': hashlib.sha256(pixels).hexdigest()}}
        assert callable(getattr(host, 'observe_frame', None)), 'host has no current pixel-to-observation admission'
        peer.message = {'message_type': 'FRAME', 'message_id': 'frame-request', 'body': {'frame_reference': reference}, 'deadline_monotonic_ms': 5000}
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000), patch.object(tutor_frames, '_read_protected_mapping', return_value=pixels):
            assert host.serve_once(timeout_ms=500)
            assert peer.sent[-1][0] == 'FRAME_ACCEPTED', 'native frame dispatcher did not return an admitted observation'
            assert peer.sent[-1][2]['reply_to'] == 'frame-request'
            observation = peer.sent[-1][1]['observation']
            refused(lambda: host.observe_frame(reference))
        assert observation['session_id'] == auth['session_id'] and observation['user_id'] == 'user-1'
        assert observation['geometry']['desktop_origin_x'] is None and observation['geometry']['native_dpi_scale'] is None
        image = next(iter(host._images._items.values()))
        snapshot_end = min(auth['expires_at_monotonic_ms'], 2500 + host.MAX_TEXT_SNAPSHOT_MS)
        assert observation['captured_at_monotonic_ms'] == 2500 and observation['expires_at_monotonic_ms'] == snapshot_end
        assert image['expires_at_monotonic_ms'] == 1_000_000 + snapshot_end - 3000, 'host image outlives its bounded source observation'
        stale_reference = copy.deepcopy(reference)
        stale_reference['transfer_id'] = 'c' * 32
        stale_reference['frame_receipt']['captured_at_monotonic_ms'] = 999
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000), patch.object(tutor_frames, '_read_protected_mapping', side_effect=AssertionError('stale raw frame reached mapping')):
            refused(lambda: host.observe_frame(stale_reference))
        assert observation['content_sha256'] == hashlib.sha256(image['bytes']).hexdigest()
        assert observation['content_sha256'] != reference['frame_receipt']['content_sha256']
        observation['user_id'] = 'mutated-copy'
        assert next(iter(host._observations.values()))['user_id'] == 'user-1'
        with patch.object(wire, 'windows_monotonic_ms', return_value=snapshot_end):
            assert host.expire_observations() == 1
        assert not host._observations and not any(image['bytes'])
        assert host._session is not None and peer.ready
        host.stop_sharing()
        assert not host._observations and not any(image['bytes'])
    finally: host.stop()
    print('[host observation] exact admitted PNG becomes source-bound host-owned observation with unknown placement; replay and Stop refuse/wipe')


def check_host_loop_stop_pending_source():
    import threading, tutor_transport as wire
    host, owner, receipt = review_host()
    entered = threading.Event(); release = threading.Event(); consumed = threading.Event(); stop = threading.Event()
    blocking = [False]; outcomes = []
    original_reader = host._reader
    def reader():
        if blocking[0]:
            entered.set(); release.wait(2)
        return original_reader()
    host._reader = reader
    class Peer:
        ready = True
        first = True
        def stop(self): self.ready = False
        def poll(self, **kwargs):
            if self.first:
                self.first = False; blocking[0] = True
                return {'message_type': 'SELECT_SOURCE', 'message_id': 'slow-select', 'body': receipt, 'deadline_monotonic_ms': 5000}
            if entered.wait(.1):
                consumed.set(); stop.set()
                return {'message_type': 'STOP', 'message_id': 'prompt-stop', 'body': {'reason_code': 'USER_STOP'}, 'deadline_monotonic_ms': 5000}
            return None
        def send(self, *args, **kwargs): pass
    peer = Peer()
    with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
    def pump():
        try: host.run(stop_event=stop); outcomes.append('STOPPED')
        except BaseException as error: outcomes.append(error)
    with patch.object(wire, 'windows_monotonic_ms', return_value=3000):
        worker = threading.Thread(target=pump)
        try:
            worker.start(); assert entered.wait(1)
            assert consumed.wait(.5), 'slow source authorization blocked receiving native Stop'
            worker.join(.5)
            assert not worker.is_alive() and outcomes == ['STOPPED'], outcomes
            assert host._session is None and host._capture_authorization is None and not peer.ready
        finally:
            stop.set(); release.set(); host.stop(); worker.join(2)
    print('[host scheduling] native Stop is consumed while source policy is blocked; no late source authorization survives')


def check_stop_receive_during_source_generation_change():
    import tutor_transport as wire
    host, _, receipt = review_host()
    class Peer:
        ready = True
        def stop(self): self.ready = False
        def poll(self, **kwargs):
            host.stop_sharing()
            return {'message_type': 'STOP', 'message_id': 'current-stop', 'body': {'reason_code': 'USER_STOP'}, 'deadline_monotonic_ms': 5000}
    peer = Peer()
    try:
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        host.select_source(receipt)
        with patch.object(wire, 'windows_monotonic_ms', return_value=3000):
            assert host.serve_once(timeout_ms=100), 'current-connection Stop was discarded across a source generation change'
        assert host._session is None and host._capture_authorization is None and peer.ready
    finally: host.stop()
    print('[control admission] current-connection Stop survives source-generation changes without reopening a source')


def check_question_deadline_respects_snapshot():
    host, _, receipt = review_host()
    _, _, observation, instruction, _ = fixture()
    calls = []
    try:
        auth = host.select_source(receipt)
        observation['session_id'] = auth['session_id']
        host._observations[observation['observation_id']] = copy.deepcopy(observation)
        def answer(request, observations):
            calls.append(copy.deepcopy(request))
            result = copy.deepcopy(instruction); result['request_id'] = request['request_id']; result['annotations'] = []
            return result
        host._service.dispatch = answer
        result = host.ask_observed({'request_id':'snapshot-deadline','observation_id':observation['observation_id'],
            'question':'Explain this source','learning_intent':'UNDERSTAND','locale':'en-CA'}, deadline_ms=8000)
        assert result['allowed'] and len(calls)==1
        assert calls[0]['deadline_monotonic_ms'] <= observation['expires_at_monotonic_ms'], 'provider work deadline outlives its original source snapshot'
    finally: host.stop()
    print('[snapshot deadline] original source observation expiry bounds provider work as well as answer release')


def check_observed_question():
    host, owner, receipt = review_host()
    _, _, observation, instruction, _ = fixture()
    calls = []
    try:
        auth = host.select_source(receipt)
        observation['session_id'] = auth['session_id']
        host._observations[observation['observation_id']] = copy.deepcopy(observation)
        body = {'request_id': 'question-1', 'observation_id': observation['observation_id'],
                'question': 'Explain the selected source', 'learning_intent': 'UNDERSTAND', 'locale': 'en-CA'}
        def answer(request, observations):
            calls.append(copy.deepcopy(request))
            value = copy.deepcopy(instruction); value['request_id'] = request['request_id']; value['annotations'] = []
            return value
        host._service.dispatch = answer
        assert callable(getattr(host, 'ask_observed', None)), 'native user input has no host-built current request route'
        result = host.ask_observed(body, deadline_ms=4000)
        assert result['allowed'] and result['instruction']['answer'] == instruction['answer']
        assert result['learning_success_claimed'] is False and result['grant_created'] is False
        assert len(calls) == 1 and calls[0]['mode'] == 'EXPLAIN' and calls[0]['research_scope'] == 'SOURCE_ONLY'
        assert calls[0]['budget_reservation_id'] == owner['budget_reservation_ids'][0]
        class Peer:
            ready = True
            sent = []
            def stop(self): self.ready = False
            def poll(self, **kwargs): return self.message
            def send(self, kind, value, **kwargs): self.sent.append((kind, value, kwargs))
        peer = Peer()
        peer.message = {'message_type': 'QUESTION', 'body': {**body, 'request_id': 'question-wire-1'}, 'message_id': 'question-wire-msg', 'deadline_monotonic_ms': 4000}
        with patch('tutor_connection.launch', return_value=peer): host.launch(None, timeout_ms=5000)
        with patch('tutor_transport.windows_monotonic_ms', return_value=3000):
            assert host.serve_once(timeout_ms=100)
        assert peer.sent[-1][0] == 'ANSWER' and peer.sent[-1][1]['instruction']['request_id'] == 'question-wire-1', 'current native question was not routed to a validated answer'
        assert peer.sent[-1][2]['reply_to'] == 'question-wire-msg'
        peer.message['body']['request_id'] = 'question-wire-late'
        ticks = [0]
        def revoke_before_send():
            ticks[0] += 1
            if ticks[0] == 2: owner['grant_view'] = []
            return 3000
        with patch('tutor_transport.windows_monotonic_ms', side_effect=revoke_before_send):
            assert host.serve_once(timeout_ms=100)
        assert peer.sent[-1][0] == 'REFUSAL', 'revocation after service release escaped as an answer on the wire'
        owner['grant_view'] = ['observe', 'explain', 'annotate']
        refused(lambda: host.ask_observed(body, deadline_ms=4000))
        refused(lambda: host.ask_observed({**body, 'request_id': 'question-2', 'user_id': 'intruder'}, deadline_ms=4000))
        owner['budget_reservation_ids'] = []
        refused(lambda: host.ask_observed({**body, 'request_id': 'question-3'}, deadline_ms=4000))
        assert len(calls) == 3
        owner['budget_reservation_ids'] = ['budget-1']
        def forged_citation(request, observations):
            value = answer(request, observations)
            value['claims'][0]['evidence_refs'] = ['foreign-observation']
            return value
        host._service.dispatch = forged_citation
        refused(lambda: host.ask_observed({**body, 'request_id': 'question-4'}, deadline_ms=4000))
        def revoke(request, observations):
            value = answer(request, observations); owner['grant_view'] = []; return value
        host._service.dispatch = revoke
        refused(lambda: host.ask_observed({**body, 'request_id': 'question-5'}, deadline_ms=4000))
    finally: host.stop()
    print('[native question] host chooses current identity/budget/mode/source; duplicates, forged authority, missing budget and late revocation release no answer')


def check_image_route_installation():
    from tutor_host import NativeTutorHost
    assert callable(getattr(NativeTutorHost,'install_image_provider',None)), 'Native host cannot install the current source-bound qualified image gateway'


def main():
    check_image_route_installation()
    check_observed_question()
    check_question_deadline_respects_snapshot()
    check_stop_receive_during_source_generation_change()
    check_host_loop_stop_pending_source()
    check_host_current_observation()
    check_supervision_source_replacement()
    check_current_capture_supervision()
    check_owned_host_loop()
    check_expired_event_and_refusal_echo()
    check_one_way_pause()
    check_receive_across_stop()
    check_late_selection_revocation()
    check_source_wire_dispatch()
    check_host_frame_store()
    check_source_selection_keeps_bridge()
    check_host_launch_lifecycle()
    check_current_answer_release()
    check_late_host_changes()
    check_sealed_host_adapter()
    check_stop_pending_selection()
    check_source_boundaries()
    check_binding_changed_inside_policy_read()
    print("PASS test_tutor_host (service release only; native host/transport/provider journey remains unqualified)")


if __name__ == "__main__":
    main()
