#!/usr/bin/env python3
"""Owned native process and Python host connection, no provider/private capture."""
import importlib.util
import base64
import json
import contextlib
import os
import pathlib
import sys
import time
import threading
import tempfile
from dataclasses import replace
from unittest.mock import patch

from common import AGENT_DIR
sys.path.insert(0, AGENT_DIR)


def _read_owned_receipt(path, *, timeout_ms=500):
    """Bound only sharing-denied reads of this test's already-published metadata."""
    if type(timeout_ms) is not int or not 1<=timeout_ms<=1000:
        raise ValueError('owned receipt read timeout outside bounds')
    deadline=time.monotonic()+timeout_ms/1000
    while True:
        try:return path.read_text(encoding='utf-8')
        except PermissionError:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise
            time.sleep(min(.005,remaining))


def check_owned_receipt_sharing():
    import ctypes
    from ctypes import wintypes
    if os.name!='nt':return
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    read_receipt=globals().get('_read_owned_receipt',lambda path,timeout_ms=500:path.read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='owned-receipt-sharing-',dir=os.environ.get('AGENT_TEST_TMP')) as temporary:
        path=pathlib.Path(temporary)/'receipt.json';path.write_text('{"owned":true}',encoding='utf-8')
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        assert handle not in (None,ctypes.c_void_p(-1).value), 'owned sharing fixture could not hold its file'
        def release():
            time.sleep(.075);kernel.CloseHandle(handle)
        worker=threading.Thread(target=release);worker.start()
        try:
            assert json.loads(read_receipt(path))=={'owned':True}
        finally:worker.join(1)
        handle=kernel.CreateFileW(str(path),0x80000000,0,None,3,0x80,None)
        try:
            started=time.monotonic()
            try:read_receipt(path,timeout_ms=50)
            except PermissionError:pass
            else:raise AssertionError('permanent file-sharing denial was hidden')
            assert time.monotonic()-started<.4,'sharing denial exceeded bounded receipt wait'
        finally:kernel.CloseHandle(handle)
        try:read_receipt(path.with_name('missing.json'))
        except FileNotFoundError:pass
        else:raise AssertionError('missing owned receipt hidden')
        path.write_text('malformed',encoding='utf-8')
        try:json.loads(read_receipt(path))
        except ValueError:pass
        else:raise AssertionError('malformed owned receipt hidden')
    print('[owned metadata sharing] real exclusive Windows file releases within bounded read; permanent/missing/malformed failures remain visible')


def check_verified_candidate_boundaries():
    import tutor_connection as connection
    with patch.object(connection.subprocess, 'Popen') as spawned, patch.object(connection.wire, 'windows_monotonic_ms', side_effect=AssertionError('feature-off called native clock')):
        assert connection.launch(object(), enabled=False)['reason_code'] == 'FEATURE_OFF'
        assert connection.launch(None, enabled=True)['reason_code'] == 'NATIVE_UNAVAILABLE'
        assert not spawned.called
    if os.name != 'nt': return
    def refuses(call):
        try: call()
        except connection.ConnectionUnavailable: return
        raise AssertionError('unverified/changed native candidate admitted')
    with tempfile.TemporaryDirectory(prefix='tutor-native-candidate-', dir=os.environ.get('AGENT_TEST_TMP')) as temporary:
        root = pathlib.Path(temporary); exe = root / 'owned.exe'; dependency = root / 'owned.dll'
        exe.write_bytes(b'MZtest-owned-validation-only'); dependency.write_bytes(b'original')
        verified = connection.VerifiedNativeExecutable.from_host(exe)
        with patch.object(connection.subprocess, 'Popen') as spawned:
            refuses(lambda: connection.launch(replace(verified, arguments=('--unapproved',)), enabled=True))
            assert not spawned.called, 'copied verification proof allows a different launch command'
            dependency.write_bytes(b'changed'); refuses(lambda: connection.launch(verified, enabled=True))
            dependency.write_bytes(b'original'); (root / 'extra.dll').write_bytes(b'new'); refuses(lambda: connection.launch(verified, enabled=True))
            (root / 'extra.dll').unlink(); dependency.unlink(); refuses(lambda: connection.launch(verified, enabled=True))
            assert not spawned.called
        dependency.write_bytes(b'original')
        with patch.object(connection.subprocess, 'Popen', side_effect=OSError('test-owned runtime unavailable')):
            refuses(lambda: connection.launch(verified, enabled=True))
    print('[native candidate] feature-off starts nothing; changed/added/missing dependency and runtime-unavailable cases refuse')


def check_native_connection():
    spec = importlib.util.find_spec('tutor_connection')
    assert spec is not None, 'actual native startup/bootstrap connection is absent'
    import tutor_connection as connection
    assert callable(getattr(connection, 'launch', None)), 'actual optional native launch route is absent'
    check_verified_candidate_boundaries()
    check_absolute_send_deadline()
    check_queued_answer_authority('budget')
    check_queued_answer_authority('source')
    check_queued_capture_authority()
    check_queued_capture_authority(frame=True)
    assert connection.launch(None, enabled=False)['reason_code'] == 'FEATURE_OFF'
    assert connection.launch(None, enabled=True)['reason_code'] == 'NATIVE_UNAVAILABLE'
    if os.name != 'nt':
        print('SKIP test_tutor_connection: Windows native process requires Windows')
        return
    # Explicit opt-in to a test-owned compiled child; never choose a user app.
    value = os.environ.get('AGENT_TUTOR_NATIVE_FIXTURE')
    if value is None:
        print('SKIP test_tutor_connection: no owned compiled native child selected; feature-off and availability checks passed')
        return
    executable = pathlib.Path(value)
    owned = connection.VerifiedNativeExecutable.from_host(executable, arguments=('--native-host-fixture',))
    check_owned_receipt_sharing()
    check_actual_idle_control_receiver(owned)
    check_actual_stale_receive_pumps(owned)
    check_actual_host_loop(owned)
    check_actual_source_exchange(owned)
    check_actual_authorized_capture(owned)
    check_actual_authorized_capture(owned, window=True)
    check_actual_authorized_capture(owned, window=True, stop_pending=True)
    check_actual_authorized_capture(owned, window=True, source_loss=True)
    check_actual_authorized_capture(owned, window=True, frame_wire=True)
    check_actual_authorized_capture(owned, window=True, stop_pending=True, scheduled=True)
    check_actual_authorized_capture(owned, window=True, stop_pending=True, scheduled=True, startup_delay_ms=2600)
    check_actual_authorized_capture(owned, window=True, question_wire=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, no_provider=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_stop=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, pause_resume=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, pause_resume=True, resume_stop=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, pause_resume=True, resume_denied=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_slow=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_slow=True, repeat_static=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_slow=True, question_change=True)
    check_actual_authorized_capture(owned, window=True, queued_frame=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_pause=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_close=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_malformed=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_timeout=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_replace=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_revocation='GRANT')
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_revocation='IDENTITY')
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_many=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, question_retry=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, teaching_canvas=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, teaching_canvas=True, teaching_expiry=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_stop=True, teaching_canvas=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, qualified_gateway=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, question_stop=True, qualified_gateway=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, qualified_gateway=True, source_approval=True)
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, qualified_gateway=True, source_approval=True, source_approval_decision='deny')
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, qualified_gateway=True, source_approval=True, source_approval_decision='stop')
    check_actual_authorized_capture(owned, window=True, question_wire=True, receiver=True, qualified_gateway=True, source_approval=True, pause_resume=True, source_approval_decision='resume')
    # Mutate only the in-memory inherited bootstrap, never executable bytes or
    # persisted secret data. Every failed launch must close its owned child.
    original_dumps = connection.json.dumps
    original_popen = connection.subprocess.Popen
    for field, changed in [('protocol_version', '1.2'), ('host_process_id', os.getpid() + 1),
                           ('key_base64', base64.b64encode(b'x' * 32).decode('ascii')), ('session_id', 'foreign-session')]:
        children = []
        def corrupt(data, *args, **kwargs):
            if data.get('schema') == 'fleet.tutor.bootstrap.v1':
                data = dict(data); data[field] = changed
            return original_dumps(data, *args, **kwargs)
        def spawned(*args, **kwargs):
            child = original_popen(*args, **kwargs); children.append(child); return child
        with patch.object(connection.json, 'dumps', side_effect=corrupt), patch.object(connection.subprocess, 'Popen', side_effect=spawned):
            try:
                connection.launch(owned, enabled=True, timeout_ms=500)
                raise AssertionError('corrupted actual bootstrap admitted: ' + field)
            except connection.ConnectionUnavailable: pass
        assert len(children) == 1
        children[0].wait(timeout=1)
    print('[native bootstrap] actual corrupt version, foreign host PID, wrong key and foreign session fail with owned child teardown')
    peer = connection.launch(owned, enabled=True, timeout_ms=5000)
    try:
        assert peer.ready, 'actual Python/native mutual proof failed'
        peer.send('PAUSE', {'reason_code': 'USER_PAUSE'}, timeout_ms=2000)
        response = peer.receive(timeout_ms=2000)
        assert response['message_type'] == 'UNAVAILABLE'
        assert response['body']['reason_code'] == 'FIXTURE_ACK'
        peer.send('STOP', {'reason_code': 'USER_STOP'}, timeout_ms=2000)
    finally:
        peer.stop()
    assert not peer.ready
    assert callable(getattr(peer, 'wait_closed', None)), 'owned native child has no verified teardown wait'
    assert peer.wait_closed(timeout_ms=1000), 'owned native child remained running after Stop'
    receipt = {'fixture_pid': peer._process.pid, 'fixture_exit_code': peer._process.returncode,
               'fixture_process_closed': True, 'provider_called': False, 'private_source_selected': False}
    print('[native connection] real owned native child and Python authenticated pipe traffic/Stop checked')
    stalled = connection.launch(owned, enabled=True, timeout_ms=5000)
    try:
        try:
            stalled.receive(timeout_ms=100)
            raise AssertionError('silent owned peer completed a read')
        except connection.ConnectionUnavailable: pass
        assert not stalled.ready, 'timed-out pipe is still reported ready'
    finally:
        stalled.stop()
    assert stalled.wait_closed(timeout_ms=1000)
    hung = connection.launch(owned, enabled=True, timeout_ms=5000)
    outcomes = []
    def blocked_read():
        try: hung.receive(timeout_ms=5000)
        except connection.ConnectionUnavailable: outcomes.append('CANCELLED')
    reader = threading.Thread(target=blocked_read); reader.start()
    time.sleep(0.05)
    start = time.monotonic(); hung.stop(); reader.join(0.5)
    assert not reader.is_alive() and outcomes == ['CANCELLED']
    assert time.monotonic() - start < 0.5, 'Stop waited behind actual hung Python pipe IO'
    assert hung.wait_closed(timeout_ms=1000)
    print('[native IO] timed-out pipe becomes unavailable; actual hung Python read is cancelled promptly by Stop')
    for reason in ('TEST_PARTIAL', 'TEST_PEER_EXIT', 'TEST_REPLAY_HELLO'):
        faulty = connection.launch(owned, enabled=True, timeout_ms=5000)
        try:
            faulty.send('PAUSE', {'reason_code': reason}, timeout_ms=2000)
            try:
                faulty.receive(timeout_ms=500)
                raise AssertionError('faulty native fixture traffic admitted: ' + reason)
            except (connection.ConnectionUnavailable, __import__('tutor_transport').TransportRefusal): pass
            assert not faulty.ready
        finally: faulty.stop()
        assert faulty.wait_closed(timeout_ms=1000)
    print('[native failures] actual partial header, peer exit and replayed HELLO refuse and close owned connection')
    cancelled = threading.Event(); connecting = threading.Event(); completed = threading.Event(); outcomes = []; children = []
    real_pipe = connection.WindowsPipe
    def different_owned_pipe(data, *args, **kwargs):
        if data.get('schema') == 'fleet.tutor.bootstrap.v1':
            data = dict(data); data['pipe_name'] = 'fleet-screen-tutor-' + ('f' * 32 if data['pipe_name'][-32:] != 'f' * 32 else 'e' * 32)
        return original_dumps(data, *args, **kwargs)
    def waiting_connection(*args, **kwargs):
        connecting.set(); return real_pipe(*args, **kwargs)
    def start_cancelled():
        try: connection.launch(owned, enabled=True, timeout_ms=5000, stop_event=cancelled)
        except connection.ConnectionUnavailable: outcomes.append('CANCELLED')
        finally: completed.set()
    def capture_child(*args, **kwargs):
        child = original_popen(*args, **kwargs); children.append(child); return child
    with patch.object(connection.json, 'dumps', side_effect=different_owned_pipe), patch.object(connection, 'WindowsPipe', side_effect=waiting_connection), patch.object(connection.subprocess, 'Popen', side_effect=capture_child):
        starter = threading.Thread(target=start_cancelled); starter.start()
        try:
            assert connecting.wait(2), 'controlled missing-pipe startup did not begin'
            start = time.monotonic(); cancelled.set()
            assert completed.wait(0.5) and time.monotonic() - start < 0.5
        finally: cancelled.set(); starter.join(1)
    assert outcomes == ['CANCELLED'] and len(children) == 1 and children[0].poll() is not None
    print('[native pending startup] cancellation interrupts actual missing-pipe wait and closes its owned child within0.5s')
    idle = connection.launch(owned, enabled=True, timeout_ms=5000)
    try:
        assert callable(getattr(idle, 'poll', None)), 'healthy idle connection has no non-destructive polling route'
        for _ in range(3):
            assert idle.poll(timeout_ms=50) is None and idle.ready
        idle.send('PAUSE', {'reason_code': 'USER_PAUSE'}, timeout_ms=2000)
        assert idle.receive(timeout_ms=2000)['body']['reason_code'] == 'FIXTURE_ACK'
    finally: idle.stop()
    assert idle.wait_closed(timeout_ms=1000)
    print('[native idle] repeated empty polls preserve readiness and subsequent authenticated traffic')
    app = os.environ.get('AGENT_TUTOR_NATIVE_APP')
    if app is not None:
        actual = connection.launch(connection.VerifiedNativeExecutable.from_host(pathlib.Path(app)), enabled=True, timeout_ms=5000)
        try:
            assert actual.ready, 'actual companion startup ignores inherited host bootstrap'
        finally:
            actual.stop()
        assert actual.wait_closed(timeout_ms=1000), 'actual owned companion remained running after Stop'
        receipt.update(app_pid=actual._process.pid, app_exit_code=actual._process.returncode, app_process_closed=True)
        print('[native app startup] actual companion inherited-bootstrap handshake/owned teardown checked; no source selected')
    output = os.environ.get('AGENT_TUTOR_CONNECTION_RECEIPT')
    if output is not None:
        pathlib.Path(output).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


def check_actual_idle_control_receiver(owned):
    import tutor_connection as connection
    peer = connection.launch(owned, enabled=True, timeout_ms=5000)
    try:
        peer.send('PAUSE', {'reason_code': 'TEST_IDLE_CONTROL_RECEIVER'}, timeout_ms=2000)
        assert peer.receive(timeout_ms=2000)['body']['reason_code'] == 'RECEIVER_READY'
        peer.send('UNAVAILABLE', {'reason_code': 'SOURCE_AUTHORIZATION_REVOKED', 'detail': 'Owned test control'}, timeout_ms=2000)
        assert peer.receive(timeout_ms=2000)['body']['reason_code'] == 'CONTROL_RECEIVED'
        peer._process.wait(timeout=3)
        assert peer._process.returncode == 0
    finally:
        peer.stop(); assert peer.wait_closed(timeout_ms=1000)
    print('[actual idle control] native consumes source revocation without a pending request and preserves the bridge')


def check_actual_stale_receive_pumps(owned):
    import tutor_connection as connection
    import tutor_transport as wire
    from test_tutor_host import review_host
    peer = connection.launch(owned, enabled=True, timeout_ms=5000)
    try:
        peer.send('PAUSE', {'reason_code': 'TEST_STALE_NATIVE_RECEIVER'}, timeout_ms=2000)
        assert peer.receive(timeout_ms=2000)['body']['reason_code'] == 'RECEIVER_READY'
        peer.send('UNAVAILABLE', {'reason_code': 'EXPIRED_CONTROL', 'detail': 'Owned delayed control'},
                  timeout_ms=2000, deadline_ms=wire.windows_monotonic_ms() + 150)
        peer.send('UNAVAILABLE', {'reason_code': 'CURRENT_CONTROL', 'detail': 'Owned current control'}, timeout_ms=2000)
        assert peer.receive(timeout_ms=2500)['body']['reason_code'] == 'CURRENT_CONTROL_RECEIVED'
        peer._process.wait(timeout=3)
        assert peer._process.returncode == 0
    finally:
        peer.stop(); assert peer.wait_closed(timeout_ms=1000)
    host, _, _ = review_host()
    stop = threading.Event(); outcomes = []
    current = threading.Event()
    acknowledged = threading.Event()
    dispatch = host._dispatch_event
    def observe(message, connection, generation):
        result = dispatch(message, connection, generation)
        if message['body'].get('reason_code') == 'CURRENT_CONTROL': current.set()
        if message['body'].get('reason_code') == 'HOST_PUMP_ALIVE_ACK': acknowledged.set()
        return result
    host._dispatch_event = observe
    peer = host.launch(owned, timeout_ms=5000)
    try:
        peer.send('PAUSE', {'reason_code': 'TEST_STALE_HOST_RECEIVER'}, timeout_ms=2000)
        time.sleep(.4)  # Both validly sent envelopes wait before the real host pump starts.
        def pump():
            try: host.run(stop_event=stop); outcomes.append('STOPPED')
            except BaseException as error: outcomes.append(error)
        thread = threading.Thread(target=pump)
        thread.start()
        assert current.wait(1) and thread.is_alive() and peer.ready, outcomes
        peer.send('PAUSE', {'reason_code': 'HOST_PUMP_ALIVE'}, timeout_ms=2000)
        assert acknowledged.wait(1) and thread.is_alive() and peer.ready, outcomes
    finally:
        stop.set(); host.stop()
        if 'thread' in locals(): thread.join(1)
        assert peer.wait_closed(timeout_ms=1000)
    print('[actual stale traffic] expired authenticated envelopes discarded by both established pumps; subsequent current traffic preserved')


def check_actual_host_loop(owned):
    from test_tutor_host import review_host
    host, _, _ = review_host()
    stop = threading.Event(); outcomes = []
    peer = host.launch(owned, timeout_ms=5000)
    def pump():
        try:
            host.run(stop_event=stop)
            outcomes.append('STOPPED')
        except BaseException as error: outcomes.append(error)
    thread = threading.Thread(target=pump)
    try:
        thread.start()
        time.sleep(.25)
        assert peer.ready and thread.is_alive(), 'caller-owned loop lost a quiet real native bridge'
        started = time.monotonic(); stop.set(); thread.join(.5)
        assert not thread.is_alive() and outcomes == ['STOPPED'], outcomes
        assert time.monotonic() - started < .5 and host._connection is None
        assert peer.wait_closed(timeout_ms=1000)
    finally:
        stop.set(); host.stop(); thread.join(1)
    print('[actual host loop] bounded quiet pipe scheduling/caller cancellation/owned child teardown checked; no source or provider')


def check_queued_answer_authority(change='budget'):
    import copy
    import tutor_transport as wire
    import tutor_connection as connection
    from test_tutor_host import review_host,fixture
    host,owner,_=review_host()
    hp=wire.BridgeSession(bytes(range(32)),'queued-answer-bridge',1,'HOST')
    np=wire.BridgeSession(bytes(range(32)),'queued-answer-bridge',1,'NATIVE')
    np.receive(hp.start(8000),1000);hp.receive(np.acknowledge(8000),1000);np.receive(hp.acknowledge(8000),1000)
    body={'request_id':'request-1','observation_id':'obs-1','question':'Owned queued answer','learning_intent':'UNDERSTAND','locale':'en-CA'}
    message=hp.receive(np.send('QUESTION',body,8000),2000)
    class Process:
        stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
    class Pipe:
        def __init__(self):self.writes=[]
        def write(self,raw,deadline):self.writes.append(raw)
        def stop(self):pass
        def close(self):pass
    pipe=Pipe();connected=connection.NativeConnection(Process(),pipe,hp);host._connection=connected
    host._service.dispatch=lambda *args:None
    allowed=[True];checked=threading.Event();outcomes=[]
    def guard():
        admitted=allowed[0];checked.set();return admitted
    def ask(body,**kwargs):
        kwargs['_release_checks'].append(guard)
        instruction=copy.deepcopy(fixture()[3]);instruction['annotations']=[]
        return {'allowed':True,'instruction':instruction}
    host.ask_observed=ask
    def work():
        try:outcomes.append(host._dispatch_event(message,connected,0))
        except BaseException as error:outcomes.append(error)
    connected._send_gate.acquire()
    try:
        with patch.object(wire,'windows_monotonic_ms',return_value=2000):
            worker=threading.Thread(target=work);worker.start()
            assert checked.wait(1), 'answer did not reach its last authority check'
            time.sleep(.025)
            assert worker.is_alive(), 'owned writer was not actually occupied'
            if change=='budget':allowed[0]=False
            else:host._selection_generation+=1
            connected._send_gate.release();worker.join(2)
            assert not worker.is_alive(),outcomes
            messages=[np.receive(raw,2000) for raw in pipe.writes]
            assert outcomes==[False], outcomes
            assert len(messages)==1 and messages[0]['message_type']=='REFUSAL' and messages[0]['body']['reason_code']=='QUESTION_REFUSED', messages
            assert all(item['message_type']!='ANSWER' for item in messages), 'queued ANSWER crossed changed '+change+' authority'
            assert connected.ready, 'safe queued refusal destroyed reusable connection'
    finally:
        if connected._send_gate.locked():connected._send_gate.release()
        host.stop();np.close()
    print('[queued answer release] occupied native writer then '+change+' change emits zero ANSWER and retains healthy channel')


def check_queued_capture_authority(frame=False):
    import tutor_transport as wire
    import tutor_connection as connection
    from test_tutor_host import review_host
    host, owner, receipt = review_host()
    hp=wire.BridgeSession(bytes(range(32)),'queued-capture-bridge',1,'HOST')
    np=wire.BridgeSession(bytes(range(32)),'queued-capture-bridge',1,'NATIVE')
    np.receive(hp.start(8000),1000);hp.receive(np.acknowledge(8000),1000);np.receive(hp.acknowledge(8000),1000)
    class Process:
        stopped=False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped=True
    class Pipe:
        def __init__(self):self.writes=[]
        def write(self,raw,deadline):self.writes.append(raw)
        def stop(self):pass
        def close(self):pass
    pipe=Pipe();connected=connection.NativeConnection(Process(),pipe,hp);host._connection=connected
    import hashlib
    pixels=bytearray([0,0,128,128,30,20,10,255])
    with patch.object(wire,'windows_monotonic_ms',return_value=2000):
        if frame:host.select_source(receipt)
    reference={'schema':'fleet.tutor.frame-reference.v1','transfer_id':'b'*32,
        'frame_receipt':{'frame_id':'frame-1','source_id':'source-1','source_revision':'source-r4',
            'capture_epoch':1,'captured_at_monotonic_ms':2000,'width':2,'height':1,
            'pixel_format':'BGRA8_PREMULTIPLIED','size_bytes':8,'content_sha256':hashlib.sha256(pixels).hexdigest()}}
    message=hp.receive(np.send('FRAME' if frame else 'SELECT_SOURCE',{'frame_reference':reference} if frame else receipt,8000),2000)
    checked=threading.Event();original=host._frame_binding;outcomes=[]
    def binding():
        value=original();checked.set();return value
    host._frame_binding=binding
    def work():
        try:outcomes.append(host._dispatch_event(message,connected,1 if frame else 0))
        except BaseException as error:outcomes.append(error)
    connected._send_gate.acquire()
    try:
        with patch.object(wire,'windows_monotonic_ms',return_value=2000), \
             patch('tutor_frames._read_protected_mapping',return_value=pixels):
            worker=threading.Thread(target=work);worker.start()
            assert checked.wait(1), outcomes
            time.sleep(.025);assert worker.is_alive(), 'writer was not occupied'
            owner['grant_view']=[]
            connected._send_gate.release();worker.join(2)
            assert not worker.is_alive(),outcomes
            messages=[np.receive(raw,2000) for raw in pipe.writes]
            assert outcomes==[False] and len(messages)==1 and messages[0]['message_type']=='REFUSAL', (outcomes,messages)
            assert messages[0]['body']['reason_code']==('FRAME_REFUSED' if frame else 'SOURCE_AUTHORIZATION_REFUSED')
            if frame:
                assert not host._observations and not host._images._items
            else:
                assert host._session is None and host._capture_authorization is None
            assert connected.ready
    finally:
        if connected._send_gate.locked():connected._send_gate.release()
        host.stop();np.close()
    print('[queued capture release] changed permission at occupied writer exports zero '+('frame acknowledgement; discards observation/image' if frame else 'capture authorization; retires source')+' and preserves bridge')


def check_absolute_send_deadline():
    import tutor_connection as connection
    import tutor_transport as wire
    from test_tutor_frames import memory_fixture
    key = bytes(range(32))
    host = wire.BridgeSession(key, 'bridge-1', 1, 'HOST'); native = wire.BridgeSession(key, 'bridge-1', 1, 'NATIVE')
    native.receive(host.start(5000), 1000)
    host.receive(native.acknowledge(5000), 1000)
    native.receive(host.acknowledge(5000), 1000)
    _, _, binding = memory_fixture()
    source = {'source_id': 'source-1', 'display_name': 'Owned source', 'source_kind': 'WINDOW', 'source_revision': 'revision-1',
              'native_handle_digest': 'a' * 64, 'width': 2, 'height': 1, 'capture_epoch': 3}
    request = host.receive(native.send('SELECT_SOURCE', source, 5000), 1000)
    class Process:
        def poll(self): return None
    class Pipe:
        writes = []
        def write(self, raw, deadline): self.writes.append((raw, deadline))
    pipe = Pipe(); connected = connection.NativeConnection(Process(), pipe, host)
    with patch.object(wire, 'windows_monotonic_ms', return_value=4001):
        connected.send('CAPTURE_AUTHORIZATION', binding, timeout_ms=2000, reply_to=request['message_id'], deadline_ms=5000)
        raw, deadline = pipe.writes[-1]
        assert deadline == 5000 and native.receive(raw, 4001)['deadline_monotonic_ms'] == 5000
        try: connected.send('PAUSE', {'reason_code': 'USER_PAUSE'}, timeout_ms=2000, deadline_ms=4001)
        except wire.StaleBridgeMessage: pass
        else: raise AssertionError('expired absolute send deadline reached pipe')
        assert len(pipe.writes) == 1 and connected.ready, 'pre-IO expiry damaged healthy channel'
    host.close(); native.close()
    print('[absolute reply deadline] elapsed scheduling preserves original authenticated lifetime; expired pre-IO send writes nothing')


def check_actual_source_exchange(owned):
    import copy
    from learning_contracts import LearningService
    from tutor_service import TutorService
    from tutor_host import NativeTutorHost
    import tutor_transport as wire
    from test_tutor_host import fixture
    _, _, _, _, owner = fixture()
    owner['capture_epoch'] = 1
    def current():
        result = copy.deepcopy(owner); now = wire.windows_monotonic_ms()
        result['now_monotonic_ms'] = now; result['grant_expires_at_monotonic_ms'] = now + 5000
        return result
    learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    host = NativeTutorHost(TutorService(enabled=True), current, learning.adapter('native_companion', binding))
    peer = host.launch(owned, timeout_ms=5000)
    reader_key = None
    try:
        peer.send('PAUSE', {'reason_code': 'TEST_SOURCE_EXCHANGE'}, timeout_ms=2000)
        assert host.serve_once(timeout_ms=2000), 'native selected source did not reach host authorization'
        ack = peer.receive(timeout_ms=2000)
        assert ack['body']['reason_code'] == 'SOURCE_EXCHANGE_ACK'
        assert host._capture_authorization['capture_epoch'] == 1 and host._frame_reader is not None
        reader_key = host._frame_reader._key
        peer.send('STOP', {'reason_code': 'USER_STOP'}, timeout_ms=2000)
        peer._process.wait(timeout=2)
        assert peer._process.returncode == 0, 'native publisher ownership/Stop assertions failed'
    finally:
        host.stop()
        assert peer.wait_closed(timeout_ms=1000)
        if reader_key is not None: assert not any(reader_key), 'owned Python frame key survived host Stop'
    print('[source exchange] actual Python/native selected source, correlated current host grant and per-launch publisher Stop checked; no capture')


def check_actual_authorized_capture(owned, *, window=False, stop_pending=False, source_loss=False, frame_wire=False, scheduled=False, question_wire=False, no_provider=False, question_stop=False, receiver=False, pause_resume=False, resume_stop=False, resume_denied=False, question_slow=False, repeat_static=False, question_change=False, queued_frame=False, question_pause=False, question_close=False, question_malformed=False, question_timeout=False, question_replace=False, question_revocation=None, startup_delay_ms=0, question_many=False, question_retry=False, teaching_canvas=False, teaching_expiry=False, qualified_gateway=False, source_approval=False, source_approval_decision='approve'):
    import copy
    import hashlib
    from learning_contracts import LearningService
    from tutor_service import TutorService
    from tutor_host import NativeTutorHost
    import tutor_transport as wire
    from test_tutor_host import fixture
    _, _, _, _, owner = fixture()
    owner['source_ids'] = []; owner['source_revisions'] = {}
    delay_grant = False
    policy_marker = None
    policy_entered = threading.Event(); policy_finished = threading.Event(); stop_received = threading.Event()
    def current():
        nonlocal delay_grant
        if delay_grant:
            delay_grant = False
            policy_entered.set()
            if scheduled and policy_marker is not None: policy_marker.write_text('owned policy entered', encoding='utf-8')
            time.sleep(.75)  # Controlled foreign process policy delay, not UI work.
            policy_finished.set()
        result = copy.deepcopy(owner); now = wire.windows_monotonic_ms()
        result['now_monotonic_ms'] = now; result['grant_expires_at_monotonic_ms'] = now + (15000 if question_slow or question_many or question_retry else 5000)
        return result
    learning = LearningService()
    binding = learning.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                                ['learning:read', 'session:write'], ['capture.selected'])
    teaching = None
    if teaching_canvas:
        from tutor_presentation import TeachingScene
        from test_tutor_canvas import scene
        teaching = TeachingScene.local_check(scene(), tenant_id='tenant-1', project_id='project-1')
        render_teaching = teaching.render
        teaching_deadlines = {}
        def diagnose_teaching(request, observation, current_owner):
            try:
                result=render_teaching(request, observation, current_owner)
                if teaching_expiry:
                    deadline=teaching_deadlines.setdefault(request['request_id'],wire.windows_monotonic_ms()+800)
                    result['expires_at_monotonic_ms']=min(result['expires_at_monotonic_ms'],deadline)
                return result
            except ValueError as error:
                chain=[]; cause=error
                while cause is not None:
                    chain.append({'type':type(cause).__name__,'reason':str(cause)}); cause=cause.__cause__
                print('[owned teaching admission diagnostic] '+json.dumps(chain))
                raise
        teaching.render = diagnose_teaching
    host = NativeTutorHost(TutorService(enabled=True), current, learning.adapter('native_companion', binding), presentation=teaching)
    questions = []
    observed_frame = host.observe_frame
    def diagnose_frame(reference):
        try: return observed_frame(reference)
        except Exception as error:
            chain = []; cause = error
            while cause is not None:
                chain.append({'type':type(cause).__name__,'reason':str(cause)})
                cause = cause.__cause__
            print('[owned frame admission diagnostic] ' + json.dumps(chain))
            authorization = host._capture_authorization or {}
            print('[owned frame timing diagnostic] ' + json.dumps({'start':authorization.get('now_monotonic_ms'),'expires':authorization.get('expires_at_monotonic_ms'),'captured':reference.get('frame_receipt',{}).get('captured_at_monotonic_ms'),'now':wire.windows_monotonic_ms()}))
            raise
    host.observe_frame = diagnose_frame
    answering = threading.Event()
    if question_wire and not no_provider and not qualified_gateway:
        def controlled_answer(request, observations):
            questions.append(request)
            answering.set()
            if question_pause or question_close or question_replace: policy_marker.write_text("owned answer entered", encoding="utf-8")
            if question_stop or question_pause or question_close or question_replace or question_revocation: time.sleep(.75)
            elif question_slow: time.sleep(2.5)
            return {'schema': 'fleet.tutor.instruction.v1', 'request_id': request['request_id'], 'move': 'EXPLAIN',
                    'answer': None if question_malformed else 'Controlled owned-window answer.', 'claims': [{'kind': 'OBSERVED', 'text': 'Owned test window',
                    'evidence_refs': [observations[0]['observation_id']], 'uncertainty': .1}], 'annotations': [],
                    'requested_response': 'Fixture transport only', 'reveal_level': 'DIRECT',
                    'expected_progress': {'kind': 'OBSERVE', 'scope': 'owned fixture'}, 'execution_request': None}
        host._service.dispatch = controlled_answer
    with tempfile.TemporaryDirectory(prefix='tutor-owned-source-', dir=os.environ.get('AGENT_TEST_TMP')) as temporary, contextlib.ExitStack() as cleanup:
        gateway_server=None
        expected_answer='Controlled owned-window answer.'
        if qualified_gateway:
            import math
            import loop
            import tutor_contracts as contracts
            import modelgateway
            from tutor_dispatch import ImageProviderRoute
            from test_tutor_gateway import settings
            from fake_provider import FakeProvider
            gateway_server=FakeProvider();cleanup.callback(gateway_server.stop)
            gateway_root=pathlib.Path(temporary)/'gateway-agent';gateway_root.mkdir()
            settings(str(gateway_root),gateway_server)
            config_path=gateway_root/'settings.toml'
            config_path.write_text(config_path.read_text(encoding='utf-8').replace('tutor_image_input_units_per_megapixel = 1000000','tutor_image_input_units_per_megapixel = 1000'),encoding='utf-8')
            gateway_agent=loop.Agent(str(gateway_root))
            def close_gateway_log():
                logger=__import__('logging').getLogger(f'agent:{gateway_root}')
                for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
            cleanup.callback(close_gateway_log)
            source_authority=None
            if source_approval:
                from tutor_authority import SourceApprovalAuthority
                profile={'user_id':'user-1','tenant_id':'tenant-1','project_id':'project-1','actor_id':'owner',
                    'profile_revision':'owned-profile-1','purpose':'source-explanation','retention_policy_id':'retention-1',
                    'budget_policy_id':'budget-policy-1','budget_reservation_id':'budget-1','budget_ceiling_usd':1.0,
                    'provider_models':{'vision':'vision-model'}}
                source_authority=SourceApprovalAuthority(temporary,str(gateway_root),'owned',lambda:copy.deepcopy(profile),
                    clock_ms=wire.windows_monotonic_ms,lifetime_ms=15000,instance_id='owned-native-approval-1')
                host.install_source_authority(source_authority)
            def current_grant_view(current_owner):
                if source_authority is not None:return source_authority.grant_view(current_owner)
                authorization=host._capture_authorization
                if authorization is None:raise ValueError('owned current capture grant unavailable')
                value=copy.deepcopy(contracts.fixture_bundle()['records']['grant_view'])
                for name in ['session_id','user_id','tenant_id','project_id','consent_revision','cancellation_generation']:
                    value[name]=current_owner[name]
                value.update(source_ids=current_owner['source_ids'],provider_destinations=['vision'],
                    valid_from_monotonic_ms=authorization['now_monotonic_ms'],expires_at_monotonic_ms=authorization['expires_at_monotonic_ms'])
                return value
            def current_budget_view(current_owner):
                if source_authority is not None:return source_authority.budget_view(current_owner)
                return {'budget_policy_id':'budget-policy-1','budget_reservation_id':current_owner['budget_reservation_ids'][0],
                    'ceiling_usd':1.0,'agent_root':str(gateway_root)}
            host.install_image_provider(ImageProviderRoute(gateway_agent,provider='vision',model='vision-model',
                current_grant_view=current_grant_view,current_budget_view=current_budget_view))
            installed_dispatch=host._service.dispatch
            uncertainty='Owned loopback fixture; no real provider or learning outcome qualification.'
            expected_answer+='\n\nUncertainty: '+uncertainty
            def gateway_answer(request,observations):
                questions.append(copy.deepcopy(request));answering.set()
                observation=observations[0]
                geometry=observation['geometry'];image_units=math.ceil(geometry['source_width']*geometry['source_height']*1000/1_000_000)
                gateway_server.reply(text=json.dumps({'answer':'Controlled owned-window answer.','uncertainty':uncertainty,
                    'source_id':observation['source_id'],'source_revision':observation['source_revision'],
                    'capture_epoch':observation['capture_epoch']}),usage={'prompt_tokens':100+image_units,'completion_tokens':20,'total_tokens':120+image_units})
                return installed_dispatch(request,observations)
            host._service.dispatch=gateway_answer
            if question_stop:gateway_server.delay=.75
        output = pathlib.Path(temporary) / 'opaque-frame-reference.json'
        stop_notice = pathlib.Path(temporary) / 'stop-notification-receipt.json'
        policy_marker = pathlib.Path(temporary) / 'owned-policy-entered.marker'
        with patch.dict(os.environ, {'AGENT_TUTOR_SOURCE_FRAME_REFERENCE_OUTPUT': str(output), 'AGENT_TUTOR_STOP_NOTIFICATION_RECEIPT': str(stop_notice), 'AGENT_TUTOR_TEST_POLICY_MARKER': str(policy_marker), 'AGENT_TUTOR_TEST_STARTUP_DELAY_MS': str(startup_delay_ms)}):
            peer = host.launch(owned, timeout_ms=5000)
        try:
            peer.send('PAUSE', {'reason_code': ('TEST_SOURCE_WINDOW_SOURCE_APPROVAL_RESUME' if source_approval_decision=='resume' else 'TEST_SOURCE_WINDOW_SOURCE_APPROVAL_DENY' if source_approval_decision=='deny' else 'TEST_SOURCE_WINDOW_SOURCE_APPROVAL_STOP' if source_approval_decision=='stop' else 'TEST_SOURCE_WINDOW_SOURCE_APPROVAL') if source_approval else ('TEST_SOURCE_WINDOW_ASK_GATEWAY_STOP' if question_stop else 'TEST_SOURCE_WINDOW_ASK_GATEWAY') if qualified_gateway else ('TEST_SOURCE_WINDOW_ASK_CANVAS_STOP' if question_stop else 'TEST_SOURCE_WINDOW_ASK_CANVAS_EXPIRE' if teaching_expiry else 'TEST_SOURCE_WINDOW_ASK_CANVAS') if teaching_canvas else 'TEST_SOURCE_WINDOW_ASK_RETRY' if question_retry else 'TEST_SOURCE_WINDOW_ASK_MANY' if question_many else 'TEST_SOURCE_WINDOW_ASK_REVOKE' if question_revocation else 'TEST_SOURCE_WINDOW_ASK_REPLACE' if question_replace else 'TEST_SOURCE_WINDOW_ASK_TIMEOUT' if question_timeout else 'TEST_SOURCE_WINDOW_QUEUED_FRAME' if queued_frame else 'TEST_SOURCE_WINDOW_ASK_CHANGE' if question_change else 'TEST_SOURCE_WINDOW_STATIC_REPEAT' if repeat_static else 'TEST_SOURCE_WINDOW_ASK_SLOW' if question_slow else 'TEST_SOURCE_WINDOW_RESUME_STOP' if resume_stop else 'TEST_SOURCE_WINDOW_RESUME_DENIED' if resume_denied else 'TEST_SOURCE_WINDOW_PAUSE_RESUME' if pause_resume else 'TEST_SOURCE_WINDOW_RECEIVER_ASK' if receiver else 'TEST_SOURCE_WINDOW_ASK_MALFORMED' if question_malformed else 'TEST_SOURCE_WINDOW_ASK_PAUSE' if question_pause else 'TEST_SOURCE_WINDOW_ASK_CLOSE' if question_close else 'TEST_SOURCE_WINDOW_ASK_STOP' if question_stop else 'TEST_SOURCE_WINDOW_NO_PROVIDER' if no_provider else 'TEST_SOURCE_WINDOW_ASK' if question_wire else 'TEST_SOURCE_WINDOW_STOP_SCHEDULED' if scheduled else 'TEST_SOURCE_WINDOW_FRAME' if frame_wire else 'TEST_SOURCE_WINDOW_LOSS' if source_loss else 'TEST_SOURCE_WINDOW_STOP_PENDING' if stop_pending else 'TEST_SOURCE_WINDOW' if window else 'TEST_SOURCE_CAPTURE'}, timeout_ms=2000)
            poll = peer.poll
            send_reply = peer.send
            def diagnose_reply(kind, body, **kwargs):
                if kind == 'REFUSAL': print('[owned wire refusal diagnostic] ' + json.dumps(body))
                if kind == 'ANSWER' and teaching_canvas:
                    print('[owned teaching reply diagnostic] '+json.dumps({'has_presentation':'presentation' in body,'intents':[q['learning_intent'] for q in questions]}))
                return send_reply(kind, body, **kwargs)
            peer.send = diagnose_reply
            def explicit_test_grant(**kwargs):
                nonlocal delay_grant
                message = poll(**kwargs)
                if message is None: return None
                if message['message_type'] == 'STOP':
                    if scheduled:
                        assert policy_entered.is_set() and not policy_finished.is_set(), 'real native Stop was delayed until policy completed'
                        stop_received.set()
                    return message
                if message['message_type'] != 'SELECT_SOURCE': return message
                assert message['message_type'] == 'SELECT_SOURCE'
                selected = message['body']
                assert (selected['width'], selected['height']) == ((320, 240) if question_slow or question_many or question_retry or teaching_canvas or qualified_gateway else (322, 272)), {
                    'owned_selected_dimensions': [selected['width'], selected['height']], 'scheduled': scheduled}
                # Fixture-only policy action for this owned native test window.
                # The production dispatcher itself never grants a selection.
                owner['source_ids'] = [selected['source_id']]
                owner['source_revisions'] = {selected['source_id']: selected['source_revision']}
                owner['capture_epoch'] = selected['capture_epoch']
                delay_grant = stop_pending or (pause_resume and bool(owner['source_ids']) and selected['capture_epoch'] > 1)
                if resume_denied and selected['capture_epoch'] > 1: owner['grant_view'] = []
                return message
            if scheduled:
                from tutor_connection import ConnectionUnavailable
                gui_ready = peer.receive(timeout_ms=10000)
                assert gui_ready['body']['reason_code'] == 'SOURCE_WINDOW_GUI_READY', gui_ready['message_type']
                assert host._session is None and host._capture_authorization is None and not output.exists(), 'GUI readiness created source authority or pixels'
                peer.send('PAUSE', {'reason_code': 'BEGIN_OWNED_SELECTION'}, timeout_ms=2000)
                cancel = threading.Event(); outcomes = []
                def run_host():
                    try: host.run(stop_event=cancel); outcomes.append('STOPPED')
                    except ConnectionUnavailable: outcomes.append('PEER_EXIT')
                    except BaseException as error: outcomes.append(error)
                thread = threading.Thread(target=run_host)
                with patch.object(peer, 'poll', side_effect=explicit_test_grant):
                    try:
                        thread.start()
                        assert policy_entered.wait(5), {'failure': 'owned GUI startup never reached the controlled policy stage',
                            'outcomes': [repr(value) for value in outcomes], 'peer_ready': peer.ready,
                            'child_exit': peer._process.poll(), 'fixture_startup_delay_ms': startup_delay_ms}
                        assert stop_received.wait(.5), 'actual pipe receiver did not admit Stop while policy was blocked'
                        thread.join(4)
                        assert not thread.is_alive() and outcomes in (['STOPPED'], ['PEER_EXIT']), outcomes
                        assert host._session is None and host._capture_authorization is None and not host._images._items
                        assert not output.exists(), 'scheduled pending Stop released captured pixels'
                        notice = json.loads(_read_owned_receipt(stop_notice))
                        assert notice['notification_completed'] and notice['selection_still_pending'] and notice['elapsed_ms'] < 500, notice
                        assert peer.wait_closed(timeout_ms=1000)
                    finally:
                        cancel.set(); host.stop(); thread.join(1)
                print('[actual scheduled WPF Stop] real control pipe admits Stop during blocked policy; prompt notification, zero pixels/late authorization and owned teardown')
                return
            with patch.object(peer, 'poll', side_effect=explicit_test_grant):
                try:
                    assert host.serve_once(timeout_ms=4000)
                except Exception:
                    if stop_notice.exists(): print('[owned native Stop receipt] ' + _read_owned_receipt(stop_notice))
                    raise
            if source_approval:
                limit=time.monotonic()+3
                while not output.exists() and peer._process.poll() is None and time.monotonic()<limit:time.sleep(.01)
                assert output.exists(), 'actual pending source UI did not publish its owned witness'
                pending=json.loads(_read_owned_receipt(output))
                assert pending['source_approval_pending'] and pending['zero_frames'] and pending['retry_visible'] and not pending['ask_enabled'],pending
                assert host._session is None and host._capture_authorization is None and not host._images._items and not questions and not gateway_server.requests
                import approvals
                record=approvals.history(str(gateway_root))[0]
                assert record['status']=='pending' and record['tool']=='share_source_for_explanation'
                if source_approval_decision=='stop':
                    limit=time.monotonic()+2
                    while not stop_notice.exists() and time.monotonic()<limit:time.sleep(.01)
                    stopped=json.loads(_read_owned_receipt(stop_notice))
                    assert stopped['pending_source_stopped'] and stopped['zero_frames'] and stopped['retry_hidden'],stopped
                    assert host.serve_once(timeout_ms=2000), 'pending source local Stop did not reach host'
                    assert host._session is None and host._capture_authorization is None
                    approvals.decide(str(gateway_root),record['id'],True,'owned late approval after explicit Stop')
                    policy_marker.write_text('owner-approved-after-stop',encoding='utf-8')
                    assert peer.receive(timeout_ms=3000)['body']['reason_code']=='SOURCE_APPROVAL_STOPPED_ACK'
                    peer._process.wait(timeout=16);assert peer._process.returncode==0
                    assert source_authority.current_source() is None and not gateway_server.requests and not questions
                    print('[actual pending source Stop] selected source and retry cleared; later owner grant starts zero frames/provider work')
                    return
                approvals.decide(str(gateway_root),record['id'],source_approval_decision!='deny','owned explicit Fleet owner source decision')
                original_expiry=record['args']['expires_at_monotonic_ms']
                output.unlink()
                policy_marker.write_text('owner-approved',encoding='utf-8')
                with patch.object(peer,'poll',side_effect=explicit_test_grant):
                    assert host.serve_once(timeout_ms=4000), 'explicit native retry did not reach existing approval'
                if source_approval_decision=='deny':
                    limit=time.monotonic()+3
                    while not output.exists() and time.monotonic()<limit:time.sleep(.01)
                    denied=json.loads(_read_owned_receipt(output))
                    assert denied['source_approval_denied'] and denied['zero_frames'] and denied['retry_hidden'] and not denied['ask_enabled'],denied
                    assert host.serve_once(timeout_ms=2000), 'denied selection cleanup Stop did not reach host'
                    assert peer.receive(timeout_ms=3000)['body']['reason_code']=='SOURCE_APPROVAL_DENIED_ACK'
                    peer._process.wait(timeout=16);assert peer._process.returncode==0
                    assert host._session is None and host._capture_authorization is None and not gateway_server.requests and not questions
                    print('[actual denied source approval] explicit retry shows owner denial, clears selected source/retry and exports zero pixels')
                    return
                assert host._capture_authorization is not None and host._capture_authorization['expires_at_monotonic_ms']==original_expiry
                print('[actual existing owner approval] selected source retained without frames/session/provider; owner decision then explicit same-source retry preserves original expiry')
            if stop_pending:
                notice = json.loads(_read_owned_receipt(stop_notice))
                assert notice['notification_completed'] and notice['selection_still_pending'] and notice['elapsed_ms'] < 500, notice
                assert host.serve_once(timeout_ms=2000), 'pending companion Stop did not reach host'
                assert host._session is None and not host._images._items and peer.ready
                assert peer.receive(timeout_ms=2000)['body']['reason_code'] == 'PENDING_STOP_ACK'
                assert not output.exists(), 'stopped authorization published a native frame reference'
                peer.send('PAUSE', {'reason_code': 'STOP_RECEIPT_ACK'}, timeout_ms=2000)
                peer._process.wait(timeout=16)
                assert peer._process.returncode == 0
                print('[actual WPF pending Stop] local Stop under500ms, zero late frames and current host session retired; channel preserved')
                return
            if queued_frame:
                assert host.serve_once(timeout_ms=4000), 'queued native source Stop never reached host'
                assert host._session is None and not host._images._items
                try:
                    assert peer.receive(timeout_ms=4000)['body']['reason_code'] == 'QUEUED_FRAME_STOP_ACK'
                except Exception:
                    if output.exists(): print('[queued owned pixels diagnostic] ' + _read_owned_receipt(output))
                    raise
                receipt = json.loads(_read_owned_receipt(output))
                assert receipt['raw_pixels_wiped'] and receipt['transfer_pending'] and receipt['capture_closed'] and receipt['stop_elapsed_ms'] < 500
                peer._process.wait(timeout=16); assert peer._process.returncode == 0
                print('[queued native frame Stop] held real raw pixel bytes zero immediately while request gate stays occupied; no frame transmitted')
                return
            if frame_wire:
                assert host.serve_once(timeout_ms=4000), 'authenticated native frame never reached host admission'
                assert len(host._observations) == 1
            if pause_resume:
                assert host.serve_once(timeout_ms=4000), 'pre-Pause frame never reached host'
                old_source = owner['source_ids'][0]; old_epoch = owner['capture_epoch']
                held = [item['bytes'] for item in host._images._items.values()]
                assert held and any(any(pixels) for pixels in held)
                def pause_only(**kwargs):
                    message = poll(**kwargs)
                    assert message is not None and message['message_type'] == 'PAUSE', 'local Pause emitted no production PAUSE before its fixture barrier'
                    return message
                with patch.object(peer, 'poll', side_effect=pause_only):
                    assert host.serve_once(timeout_ms=4000), 'real Pause never retired host source state'
                assert peer.receive(timeout_ms=2000)['body']['reason_code'] == 'PAUSE_LOCAL_BARRIER'
                assert host._session is None and not host._observations and not host._images._items
                assert all(not any(pixels) for pixels in held), 'Pause retained host PNG bytes'
                with patch.object(peer, 'poll', side_effect=explicit_test_grant):
                    if resume_stop:
                        outcomes = []
                        def pending_resume():
                            try: outcomes.append(host.serve_once(timeout_ms=4000))
                            except BaseException as error: outcomes.append(error)
                        pending = threading.Thread(target=pending_resume); pending.start()
                        try:
                            assert policy_entered.wait(2)
                            assert host.serve_once(timeout_ms=2000), 'pending Resume blocked source Stop'
                        finally: pending.join(3)
                        assert outcomes == [True] and not pending.is_alive(), outcomes
                    else:
                        assert host.serve_once(timeout_ms=4000), 'Resume never requested fresh host authorization'
                assert owner['capture_epoch'] > old_epoch and owner['source_ids'][0] != old_source
                if source_approval:
                    limit=time.monotonic()+3
                    while not stop_notice.exists() and time.monotonic()<limit:time.sleep(.01)
                    resumed=json.loads(_read_owned_receipt(stop_notice))
                    assert resumed['resume_approval_pending'] and resumed['zero_frames'] and resumed['retry_visible'] and not resumed['ask_enabled'],resumed
                    assert host._session is None and host._capture_authorization is None and not host._observations and not host._images._items and not questions and not gateway_server.requests
                    from approvals import pending as pending_approvals
                    fresh_pending=pending_approvals(str(gateway_root));assert len(fresh_pending)==1
                    fresh_record=fresh_pending[0];assert fresh_record['id']!=record['id']
                    approvals.decide(str(gateway_root),fresh_record['id'],True,'owned explicit fresh-epoch Resume approval')
                    pathlib.Path(str(policy_marker)+'.resume').write_text('fresh-epoch-approved',encoding='utf-8')
                    with patch.object(peer,'poll',side_effect=explicit_test_grant):
                        assert host.serve_once(timeout_ms=4000), 'Resume explicit same-source retry never reached host'
                    assert host._capture_authorization['expires_at_monotonic_ms']==fresh_record['args']['expires_at_monotonic_ms']
                    print('[actual Resume existing approval] fresh epoch remains selected/unshared, new exact owner decision and explicit retry restore Pause before metered Ask')
                if resume_stop or resume_denied:
                    if resume_denied: assert host.serve_once(timeout_ms=2000), 'denied Resume never retired native source'
                    acknowledgement = peer.receive(timeout_ms=4000)['body']
                    assert acknowledgement['reason_code'] == ('RESUME_STOP_ACK' if resume_stop else 'RESUME_DENIED_ACK')
                    assert acknowledgement['detail'].endswith('next_pause_label=Pause'), acknowledgement
                    if resume_denied: assert 'Sharing could not resume.' in acknowledgement['detail'], acknowledgement
                    assert host._session is None and host._capture_authorization is None and not host._images._items and not host._observations
                    assert not questions and not output.exists()
                    peer._process.wait(timeout=16)
                    assert peer._process.returncode == 0
                    print('[actual fresh Resume ' + ('pending Stop' if resume_stop else 'owner revocation') + '] zero late pixels/guidance/provider calls, host source retired and owned child exits normally')
                    return
            if question_wire:
                raw_digests = []
                def record_frame(**kwargs):
                    message = poll(**kwargs)
                    if message is not None and message['message_type'] != 'FRAME':
                        print('[owned expected frame got control] ' + json.dumps({'type':message['message_type'],'body':message['body']}))
                    if message is not None and message['message_type'] == 'FRAME':
                        raw_digests.append(message['body']['frame_reference']['frame_receipt']['content_sha256'])
                    return message
                if question_retry:
                    first_ready = threading.Event(); release_old = threading.Event(); old_sent = threading.Event()
                    reply_ids = []; outcomes = []
                    def delayed_frame_reply(kind, body, **kwargs):
                        if kind == 'FRAME_ACCEPTED':
                            reply_ids.append(body['observation']['observation_id'])
                            if len(reply_ids) == 1:
                                first_ready.set()
                                assert release_old.wait(4), 'retry sent no second frame before old reply deadline'
                                send_reply(kind, body, **kwargs); old_sent.set(); return
                        return send_reply(kind, body, **kwargs)
                    def first_frame():
                        try: outcomes.append(host.serve_once(timeout_ms=4000))
                        except BaseException as error: outcomes.append(error)
                    with patch.object(peer, 'send', side_effect=delayed_frame_reply), patch.object(peer, 'poll', side_effect=record_frame):
                        pending = threading.Thread(target=first_frame); pending.start()
                        try:
                            assert first_ready.wait(4), 'first real frame never reached host before timeout'
                            current_frame = poll(timeout_ms=4000)
                            assert current_frame is not None and current_frame['message_type'] == 'FRAME'
                            assert current_frame['body']['frame_reference']['frame_receipt']['content_sha256'] != raw_digests[0], 'retry did not use distinct real source pixels'
                            release_old.set(); assert old_sent.wait(1)
                            with patch.object(peer, 'poll', return_value=current_frame):
                                assert host.serve_once(timeout_ms=4000)
                            assert len(reply_ids) == 2
                            question = poll(timeout_ms=4000)
                            assert question is not None and question['message_type'] == 'QUESTION'
                            assert question['body']['observation_id'] == reply_ids[1], {'requested_observation':question['body']['observation_id'],'old_observation':reply_ids[0],'current_observation':reply_ids[1]}
                            with patch.object(peer, 'poll', return_value=question):
                                assert host.serve_once(timeout_ms=4000)
                        finally:
                            release_old.set(); pending.join(3)
                    assert outcomes == [True] and not pending.is_alive(), outcomes
                    deadline = time.monotonic() + 3
                    while not output.exists() and peer._process.poll() is None and time.monotonic() < deadline: time.sleep(.02)
                    visible = json.loads(_read_owned_receipt(output))
                    assert visible['visible_answer'] == 'Controlled owned-window answer.' and len(questions) == 1, visible
                    host.stop_sharing()
                    peer.send('UNAVAILABLE', {'reason_code': 'SOURCE_REVOKED', 'detail': 'Owned retry source retired'}, timeout_ms=2000)
                    assert peer.receive(timeout_ms=4000)['body']['reason_code'] == 'SOURCE_REVOKED_ACK'
                    peer._process.wait(timeout=16); assert peer._process.returncode == 0
                    print('[actual timeout then retry] old still-valid authenticated reply discarded; distinct new real pixels select their exact observation and visible answer; bridge retained')
                    return
                if question_timeout:
                    message = poll(timeout_ms=4000)
                    assert message is not None and message['message_type'] == 'FRAME', 'timeout test saw no actual frame request'
                    deadline = time.monotonic() + 4
                    while not output.exists() and peer._process.poll() is None and time.monotonic() < deadline: time.sleep(.02)
                    assert output.exists(), 'actual request did not return a bounded visible timeout'
                    visible = json.loads(_read_owned_receipt(output))
                    assert visible['visible_answer'] == '' and visible['availability_status'] == 'The request timed out. Ask again using the current source.', visible
                    assert visible['ask_enabled'] and visible['question_draft'] == 'Explain the owned test window' and visible['ask_elapsed_ms'] < 3500, visible
                    assert not questions and not host._images._items and not host._observations and peer.ready
                    host.stop_sharing()
                    peer.send('UNAVAILABLE', {'reason_code': 'SOURCE_REVOKED', 'detail': 'Owned timeout fixture source retired'}, timeout_ms=2000)
                    try:
                        assert peer.receive(timeout_ms=4000)['body']['reason_code'] == 'SOURCE_REVOKED_ACK'
                    except Exception:
                        if stop_notice.exists(): print('[owned timeout native diagnostic] ' + _read_owned_receipt(stop_notice))
                        print('[owned timeout UI diagnostic] ' + json.dumps(visible))
                        raise
                    peer._process.wait(timeout=16); assert peer._process.returncode == 0
                    print('[actual WPF Ask timeout] unanswered real frame request returns clear bounded timeout; zero provider work, healthy bridge and subsequent revocation wipe')
                    return
                with patch.object(peer, 'poll', side_effect=record_frame):
                    assert host.serve_once(timeout_ms=4000), 'real Ask did not transfer its selected frame'
                if not host._observations:
                    if stop_notice.exists(): print('[owned frame failure detail] ' + _read_owned_receipt(stop_notice))
                    raise AssertionError('expected current frame admission instead consumed another control or refusal')
                original_png_digest = next(iter(host._observations.values()))['content_sha256']
                if question_revocation:
                    held = [item['bytes'] for item in host._images._items.values()]
                    assert held and any(any(pixels) for pixels in held)
                    outcomes = []
                    def pending_revoked_answer():
                        try: outcomes.append(host.serve_once(timeout_ms=4000))
                        except BaseException as error: outcomes.append(error)
                    pending = threading.Thread(target=pending_revoked_answer); pending.start()
                    try:
                        assert answering.wait(2), 'actual answer dispatch never began before revocation'
                        if question_revocation == 'GRANT': owner['grant_view'] = []
                        elif question_revocation == 'IDENTITY': owner['user_id'] = 'owned-other-user'
                        else: raise AssertionError('unknown owned revocation mode')
                        assert not host.supervise_source(), 'current policy revocation retained the old source'
                        peer.send('UNAVAILABLE', {'reason_code': 'SOURCE_REVOKED', 'detail': 'Owned current policy no longer admits this source'}, timeout_ms=2000)
                    finally: pending.join(3)
                    assert not pending.is_alive() and outcomes == [True], outcomes
                    assert host._session is None and not host._images._items and not host._observations
                    assert all(not any(pixels) for pixels in held), 'revocation retained host PNG bytes'
                    assert peer.receive(timeout_ms=4000)['body']['reason_code'] == 'SOURCE_REVOKED_ACK'
                    visible = json.loads(_read_owned_receipt(output))
                    assert visible['visible_answer'] == '' and visible['capture_state'] == 'Closed' and not visible['ask_enabled'], visible
                    assert len(questions) == 1 and peer.ready
                    peer._process.wait(timeout=16); assert peer._process.returncode == 0
                    print('[actual pending ' + question_revocation + ' revocation] current sealed owner policy retires source, wipes held PNG and suppresses late visible answer; authenticated bridge retained')
                    return
                if question_stop or question_pause or question_replace:
                    held_question_pixels = [item["bytes"] for item in host._images._items.values()]
                    assert held_question_pixels and any(any(pixels) for pixels in held_question_pixels)
                    outcomes = []
                    def pending_answer():
                        try: outcomes.append(host.serve_once(timeout_ms=4000))
                        except BaseException as error: outcomes.append(error)
                    pending = threading.Thread(target=pending_answer); pending.start()
                    try:
                        assert answering.wait(2)
                        assert host.serve_once(timeout_ms=2000), 'pending answer blocked real sharing Stop'
                        assert host._session is None and not host._images._items
                    finally: pending.join(3)
                    assert not pending.is_alive() and outcomes == [True], outcomes
                    assert all(not any(pixels) for pixels in held_question_pixels), "interruption retained host PNG bytes"
                    if question_replace:
                        old_source = owner['source_ids'][0]
                        with patch.object(peer, 'poll', side_effect=explicit_test_grant):
                            assert host.serve_once(timeout_ms=4000), 'replacement requested no fresh source authorization'
                        if owner['source_ids'][0] == old_source and stop_notice.exists(): print('[owned replacement native diagnostic] ' + _read_owned_receipt(stop_notice))
                        assert owner['source_ids'][0] != old_source and host._session is not None
                        with patch.object(peer, 'poll', side_effect=record_frame):
                            assert host.serve_once(timeout_ms=4000), 'replacement source sent no fresh frame'
                        assert len(host._observations) == 1 and next(iter(host._observations.values()))['source_id'] == owner['source_ids'][0]
                        assert host.serve_once(timeout_ms=4000), 'replacement source sent no fresh question'
                        assert len(questions) == 2 and questions[0]['source_ids'] == [old_source] and questions[1]['source_ids'] == owner['source_ids']

                else:
                    assert host.serve_once(timeout_ms=4000), 'real Ask did not send a current question'
                if question_many:
                    for index in range(4):
                        try:
                            with patch.object(peer, 'poll', side_effect=record_frame):
                                assert host.serve_once(timeout_ms=4000), 'repeated Ask sent no current frame'
                            assert host.serve_once(timeout_ms=4000), 'repeated Ask sent no question'
                        except Exception:
                            if output.exists(): print('[owned repeated Ask diagnostic] ' + _read_owned_receipt(output))
                            if stop_notice.exists(): print('[owned repeated Ask native diagnostic] ' + _read_owned_receipt(stop_notice))
                            print('[owned repeated Ask dispatch count] ' + str(len(questions)))
                            raise
                    assert len(questions) == 5 and all(question['source_ids'] == owner['source_ids'] for question in questions)
                if repeat_static:
                    try:
                        assert host.serve_once(timeout_ms=4000), 'repeat Ask sent no newly captured frame'
                    except Exception:
                        if output.exists(): print('[owned repeat snapshot diagnostic] ' + _read_owned_receipt(output))
                        raise
                    snapshots = list(host._observations.values())
                    assert len(snapshots) == 2 and snapshots[1]['captured_at_monotonic_ms'] > snapshots[0]['captured_at_monotonic_ms'] + 2000
                    assert snapshots[0]['content_sha256'] == snapshots[1]['content_sha256'], 'unchanged owned source did not retain identical visible pixels'
                    assert host.serve_once(timeout_ms=4000), 'repeat Ask sent no current question'
                deadline = time.monotonic() + 3
                while not output.exists() and peer._process.poll() is None and time.monotonic() < deadline: time.sleep(.02)
                assert output.exists(), 'actual Ask never displayed its host answer'
                visible = json.loads(_read_owned_receipt(output))
                if teaching_canvas and not question_stop:
                    assert visible['visible_scene'] and 'graph plots' in visible['scene_alternative'] and visible['scene_qualification'] == 'Local demonstration - unqualified content', visible
                    if teaching_expiry:
                        assert visible['expired_scene_cleared'] and visible['capture_ready_at_scene_expiry'], visible
                    elif receiver:
                        assert host._published_presentation is not None
                        teaching._scene['title']='owned content authority revoked after visible display'
                        retirement=host.supervise_presentation()
                        assert retirement and host._capture_authorization is not None and host._session is not None
                        old=copy.deepcopy(retirement); old['binding']['request_id']='older-question'
                        peer.send('PRESENTATION_RETIRED',old,timeout_ms=2000)
                        assert peer.receive(timeout_ms=4000)['body']['reason_code']=='OLD_TEACHING_RETIRED_ACK'
                        peer.send('PRESENTATION_RETIRED',retirement,timeout_ms=2000)
                        assert peer.receive(timeout_ms=4000)['body']['reason_code']=='TEACHING_RETIRED_ACK'
                        assert host.supervise_source(), 'teaching-only revocation retired valid capture'

                if question_slow: print('[owned static source diagnostic] ' + json.dumps(visible))
                if question_pause:
                    assert visible['visible_answer'] == '' and visible['capture_state'] == 'Paused' and visible['availability_status'] == 'Sharing paused. Resume requires fresh authorization.', visible
                    assert len(questions) == 1
                elif question_stop:
                    assert visible['visible_answer'] == '' and visible['availability_status'] == 'Sharing stopped locally.', visible
                    assert len(questions) == 1
                    if qualified_gateway:
                        assert len(gateway_server.requests)==1, 'pending Stop witness did not reach its real HTTP request'
                        state=modelgateway._read_spend(modelgateway.spend_file(str(gateway_root)))
                        assert len(state['reservations'])==1 and next(iter(state['reservations'].values()))['status']=='SETTLED'
                        print('[actual metered gateway Stop] Stop during one real loopback image HTTP request suppresses answer and settles exactly one reservation')
                elif question_malformed:
                    assert visible['visible_answer'] == '' and visible['availability_status'] == 'The answer failed validation and was not displayed. Ask again using the current source.', visible
                    assert len(questions) == 1
                elif no_provider:
                    assert visible['visible_answer'] == '' and 'No qualified answer provider is configured' in visible['availability_status'], visible
                    assert questions == []
                elif question_change:
                    assert visible['visible_answer'] == '' and 'source changed' in visible['availability_status'].lower(), visible
                    assert visible['captured_frames'] >= 2 and visible['capture_state'] == 'Ready' and len(questions) == 1
                else:
                    assert visible['visible_answer'] == expected_answer, visible
                    assert len(questions) == (5 if question_many else 2 if repeat_static or question_replace else 1) and questions[0]['mode'] == 'EXPLAIN'
                if question_replace:
                    assert visible['old_answer_suppressed'] and visible['original_source_id'] != visible['current_source_id'] == owner['source_ids'][0], visible
                if receiver:
                    held = [item['bytes'] for item in host._images._items.values()]
                    if qualified_gateway:
                        assert not held and len(gateway_server.requests)==1, 'gateway did not consume its exact PNG once'
                        payload=gateway_server.requests[0]['payload']
                        assert 'tools' not in payload and payload['model']=='vision-model'
                        state=modelgateway._read_spend(modelgateway.spend_file(str(gateway_root)))
                        assert len(state['reservations'])==1 and next(iter(state['reservations'].values()))['outcome']=='USAGE_RECONCILED'
                        print('[actual qualified gateway Ask] real owned PNG/native QUESTION/current grant and budget/HTTP image/no tools/metered result/visible source uncertainty; loopback mechanism only')
                    else:
                        assert held and any(any(pixels) for pixels in held)
                    host.stop_sharing()
                    peer.send('UNAVAILABLE', {'reason_code': 'SOURCE_REVOKED', 'detail': 'Owned fixture grant revoked'}, timeout_ms=2000)
                    assert peer.receive(timeout_ms=4000)['body']['reason_code'] == 'SOURCE_REVOKED_ACK'
                    assert not host._observations and not host._images._items and all(not any(pixels) for pixels in held)
                    peer._process.wait(timeout=16)
                    assert peer._process.returncode == 0
                    print('[actual production receiver ' + ('Pause/Resume/Ask' if pause_resume else 'Ask/revocation') + '] CAPTURE/FRAME/QUESTION replies route through continuous receiver; ' + ('Pause wipes cached bytes and Resume waits for fresh epoch/source authorization; ' if pause_resume else '') + 'host revocation closes pixels, clears visible guidance, wipes host cache and preserves bridge')
                    return
                peer.send('STOP', {'reason_code': 'USER_STOP'}, timeout_ms=2000)
                if not (question_stop or question_pause): assert host.serve_once(timeout_ms=2000)
                assert host._session is None and not host._observations and not host._images._items
                peer.send('PAUSE', {'reason_code': 'STOP_RECEIPT_ACK'}, timeout_ms=2000)
                peer._process.wait(timeout=16)
                assert peer._process.returncode == 0
                print('[actual WPF Ask ' + ('pending Stop' if question_stop else 'pending Pause' if question_pause else 'pending close/summon' if question_close else 'invalid provider response' if question_malformed else 'unavailable' if no_provider else 'answer') + '] real source/frame/question pipe; ' + ('prompt local Stop, live host retirement and late answer suppressed' if question_stop else 'prompt local Pause, host PNG wipe and late answer suppressed' if question_pause else 'invalid response withheld and validation failure explained' if question_malformed else 'provider refusal survives subsequent native frame changes; zero dispatch' if no_provider else 'exact validated visible fixture answer') + '; Stop wipes source data')
                return
            deadline = time.monotonic() + 4
            while not output.exists() and peer._process.poll() is None and time.monotonic() < deadline: time.sleep(.02)
            assert output.exists(), 'host-authorized native capture produced no opaque frame reference'
            packet = json.loads(_read_owned_receipt(output))
            assert packet['authorization'] == host._capture_authorization
            reference = packet['reference']; receipt = reference['frame_receipt']
            assert receipt['size_bytes'] == 350336 and receipt['source_id'] == owner['source_ids'][0]
            admitted = (next(iter(host._observations.values())) if frame_wire else host.consume_frame(reference))
            if frame_wire:
                assert packet['admittedObservation'] == admitted, 'native received a different observation from the real host'
                assert admitted['geometry']['desktop_origin_x'] is None
            else:
                assert admitted['raw_content_sha256'] == receipt['content_sha256']
            image = (host._images._items[admitted['artifact_ref'].split('://', 1)[1]] if window
                     else host._images.take(admitted['artifact_ref'], admitted))
            assert hashlib.sha256(image['bytes']).hexdigest() == admitted['content_sha256']
            assert image['bytes'][:8] == b'\x89PNG\r\n\x1a\n'
            if not window: image['bytes'][:] = b'\0' * len(image['bytes'])
            peer.send('PAUSE' if source_loss else 'STOP', {'reason_code': 'CLOSE_OWNED_SOURCE' if source_loss else 'USER_STOP'}, timeout_ms=2000)
            if window:
                assert host.serve_once(timeout_ms=6000 if source_loss else 2000), 'actual companion sharing Stop did not reach host'
                assert host._session is None and not host._images._items and peer.ready
                assert not any(image['bytes']), 'actual native Stop/loss left host cached PNG bytes intact'
                peer.send('PAUSE', {'reason_code': 'STOP_RECEIPT_ACK'}, timeout_ms=2000)
            peer._process.wait(timeout=16)
            if source_loss and stop_notice.exists(): print('[owned source closure stages] ' + _read_owned_receipt(stop_notice))
            if peer._process.returncode != 0 and stop_notice.exists(): print('[owned native failure diagnostic] ' + _read_owned_receipt(stop_notice))
            assert peer._process.returncode == 0, 'owned selected-source capture/closure assertions failed'
        finally:
            try:
                if stop_notice.exists():
                    diagnostic = json.loads(_read_owned_receipt(stop_notice))
                    if isinstance(diagnostic, dict) and diagnostic.get('test_failure'):
                        print('[owned native terminal failure] ' + json.dumps(diagnostic))
            except (OSError, ValueError):
                print('[owned native terminal diagnostic unavailable]')
            finally:
                host.stop(); assert peer.wait_closed(timeout_ms=1000)
    print('[joined source capture' + (' authenticated frame wire' if frame_wire else ' actual WPF source loss' if source_loss else ' actual WPF' if window else '') + '] selected owned window/host grant/capture/launch-bound memory/exact digest/PNG store checked; ' + ('real FRAME/FRAME_ACCEPTED pipe carries no pixels; test file compares returned metadata only' if frame_wire else 'metadata fixture is not production frame wire'))


if __name__ == '__main__':
    check_native_connection()
    print('PASS test_tutor_connection')
