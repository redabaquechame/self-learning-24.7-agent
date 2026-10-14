"""Fleet-owned native runtime: current authentication, device and teardown."""
import pathlib
import sys
import tempfile
import threading
import time
import json
import urllib.request
import urllib.error
import contextlib
import logging
import os
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tutor_runtime as R
import org
from learning_contracts import LearningService
from tutor_host import NativeTutorHost


def main():
    check_runtime_approval_projection()
    check_panel()
    check_profile_factory()
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        (home / 'experts' / 'owned').mkdir(parents=True)
        runtime = R.FleetTutorRuntime(home)
        assert isinstance(runtime.learning, LearningService)
        proof = lambda: 'owner'
        assert runtime.status('owned', 'owner', proof)['state'] == 'UNAVAILABLE'
        try:
            runtime.launch('owned', 'owner', proof)
        except R.RuntimeUnavailable:
            pass
        else:
            raise AssertionError('unconfigured runtime launched')
        from tutor_connection import VerifiedNativeExecutable
        exe = home / 'native' / 'owned.exe'; exe.parent.mkdir(); exe.write_bytes(b'MZowned')
        native = VerifiedNativeExecutable.from_host(exe)
        runtime.install('owned', device_actor='owner', native=native,
                        host_factory=lambda shared, current: make_host(shared, current))
        assert runtime.status('owned', 'foreign', lambda: 'foreign')['reason_code'] == 'DEVICE_ACTOR_UNAVAILABLE'
        assert runtime.status('owned', 'owner', lambda: None)['reason_code'] == 'AUTHENTICATION_CHANGED'
        stopped = threading.Event()
        def run(host, *, stop_event):
            stop_event.wait(3)
        with patch.object(NativeTutorHost, 'launch', return_value=object()), \
             patch.object(NativeTutorHost, 'run', run), \
             patch.object(NativeTutorHost, 'stop', lambda host: stopped.set()):
            current = ['owner']
            live = lambda: current[0]
            assert runtime.launch('owned', 'owner', live)['state'] == 'RUNNING'
            assert runtime.status('owned', 'owner', live)['return_path'] == '/#agent/owned/ov'
            current[0] = None
            assert stopped.wait(2), 'revoked caller survives without a new API request'
            assert not runtime.status('owned', 'owner', proof)['running']
            current[0] = 'owner'; stopped.clear()
            runtime.launch('owned', 'owner', live)
            runtime.close()
            assert stopped.is_set() and not runtime.status('owned', 'owner', live)['running']
        runtime.close()
    print('PASS Fleet runtime unavailable/device/authentication/current revocation/shared service/teardown')


def check_panel():
    import ui
    with tempfile.TemporaryDirectory() as tmp:
        home = pathlib.Path(tmp)
        (home / 'experts' / 'owned').mkdir(parents=True)
        org.create(tmp, 'Owned runtime test', 'owner@example.com')
        org.add_user(tmp, 'owner@example.com', 'viewer@example.com', 'viewer')
        viewer = org.issue_token(tmp, 'owner@example.com', 'viewer@example.com')
        runtime = R.FleetTutorRuntime(tmp)
        class Handler(ui.Handler):
            pass
        Handler.home = tmp; Handler.token = 'owned-master'; Handler.tutor_runtime = runtime
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def call(method, tail, body=None, token='owned-master', origin=None):
            headers = {'Authorization': 'Bearer ' + token, 'Origin': origin or base,
                       'Content-Type': 'application/json'}
            route = tail if tail.startswith('/api/') else '/api/experts/owned/tutor' + tail
            request = urllib.request.Request(base + route,
                       data=json.dumps(body).encode() if body is not None else None,
                       headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.status, json.load(response)
            except urllib.error.HTTPError as error:
                return error.code, json.load(error)
        try:
            status, data = call('GET', '')
            assert status == 200 and data['state'] == 'UNAVAILABLE', (status, data)
            assert call('GET', '', token=viewer)[0] == 403
            assert call('POST', '/launch', {}, token=viewer)[0] == 403
            assert call('POST', '/launch', {}, origin='https://foreign.invalid')[0] == 403
            assert call('POST', '/launch', {'actor_id':'owner@example.com', 'executable':'bad'})[0] == 400
            assert call('POST', '/launch', {})[0] == 409
            assert call('POST', '/stop', {})[0] == 200
            assert call('GET', '', token='foreign')[0] == 401
            import approvals
            pending = approvals.request(str(home/'experts'/'owned'), 'owned-source-key', 'screen_tutor',
                'share_source_for_explanation', {'scope':{'owned_test':True}}, 'Owned source approval')
            with patch.object(ui, 'start_expert') as start, patch.object(ui.loop, 'Agent') as pursuit:
                status, answer = call('POST', '/api/experts/owned/approval',
                    {'id':pending['id'], 'op':'grant', 'task':'owned-native-session'})
                assert status == 409 and approvals.load(str(home/'experts'/'owned'),pending['id'])['status']=='pending', (status,answer)
                assert not start.called and not pursuit.called, 'source approval started an unrelated Fleet pursuit'
            ordinary=approvals.request(str(home/'experts'/'owned'),'owned-ordinary-key','owned-mcp','inspect',{},'Owned ordinary request')
            status, visible=call('GET','/api/experts/owned/approvals',token=viewer)
            assert status==200 and [row['id'] for row in visible['pending']]==[ordinary['id']], visible
            from tutor_connection import VerifiedNativeExecutable
            exe = home / 'native' / 'owned.exe'; exe.parent.mkdir(); exe.write_bytes(b'MZowned')
            runtime.install('owned', device_actor='owner@example.com',
                native=VerifiedNativeExecutable.from_host(exe), host_factory=make_host)
            stopped = threading.Event()
            with patch.object(NativeTutorHost, 'launch', return_value=object()), \
                 patch.object(NativeTutorHost, 'run', lambda host, *, stop_event: stop_event.wait(3)), \
                 patch.object(NativeTutorHost, 'stop', lambda host: stopped.set()):
                owner_token = org.issue_token(tmp, 'owner@example.com')
                assert call('POST', '/launch', {}, token=owner_token)[1]['state'] == 'RUNNING'
                org.revoke_token(tmp, 'owner@example.com', 'owner@example.com')
                assert stopped.wait(2), 'revoked original HTTP bearer retains native work'
                assert not runtime.status('owned', 'owner@example.com', lambda:'owner@example.com')['running']
        finally:
            runtime.close(); server.shutdown(); server.server_close(); thread.join(2)
    print('PASS actual Fleet HTTP discovery/authentication/viewer/CSRF/body injection/unavailable/Stop')


def make_host(shared, current):
    from tutor_service import TutorService
    def owner():
        current()
        return {'user_id': 'user-1', 'tenant_id': 'tenant-1', 'project_id': 'owned'}
    binding = shared.bind_host('user-1', 'tenant-1', 'policy-1', 'grant-1', 'course-1',
                              ['learning:read', 'session:write'], ['capture.selected'])
    return NativeTutorHost(TutorService(enabled=True, dispatch=lambda *_: None), owner,
                           shared.adapter('native_companion', binding))


def check_profile_factory():
    from fake_provider import FakeProvider
    from test_tutor_gateway import settings
    from loop import Agent
    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as cleanup:
        server = FakeProvider()
        cleanup.callback(server.stop)
        root = pathlib.Path(tmp) / 'experts' / 'owned'; root.mkdir(parents=True)
        settings(root, server); agent = Agent(root)
        def close_log():
            logger = logging.getLogger('agent:' + str(root))
            for handler in list(logger.handlers):
                handler.close(); logger.removeHandler(handler)
        cleanup.callback(close_log)
        profile = {'profile_revision':'profile-1', 'purpose':'source-explanation',
                   'retention_policy_id':'retention-1', 'budget_policy_id':'budget-policy-1',
                   'budget_reservation_id':'budget-1', 'budget_ceiling_usd':1.0,
                   'provider_models':{'vision':'vision-model'}}
        factory = R.source_host_factory(tmp, 'owned', 'owner', agent,
                     provider='vision', model='vision-model', current_profile=lambda: profile.copy())
        shared = LearningService(); host = factory(shared, lambda: None)
        assert host._learning_service is shared and host._source_authority is not None
        assert host._project == 'owned' and host._image_route.agent is agent
        assert host._source_authority.identity['user_id'] != 'owner'
        settings_path=root/'settings.toml'; original_settings=settings_path.read_bytes()
        settings_path.write_bytes(original_settings.replace(b'tutor_image_enabled = true',b'tutor_image_enabled = false'))
        try:
            factory.verify_current()
        except ValueError:
            pass
        else:
            raise AssertionError('on-disk provider withdrawal leaves the original Agent snapshot authorized')
        finally:
            settings_path.write_bytes(original_settings)
        for before, after in ((b'api_key = "test-only"',b'api_key = "withdrawn-account"'),
                              (b'model = "vision-model"',b'model = "withdrawn-model"'),
                              (b'input_per_mtok = 2.0',b'input_per_mtok = 99.0')):
            settings_path.write_bytes(original_settings.replace(before,after))
            try:
                factory.verify_current()
            except ValueError:
                pass
            else:
                raise AssertionError('changed settings remain authorized')
            finally:
                settings_path.write_bytes(original_settings)
        settings_path.unlink()
        try:
            factory.verify_current()
        except ValueError:
            pass
        else:
            raise AssertionError('missing settings remain authorized')
        finally:
            settings_path.write_bytes(original_settings)
        agent.cfg['providers']['vision']['tutor_image_enabled'] = False
        try:
            R.source_host_factory(tmp, 'owned', 'owner', agent, provider='vision',
                model='vision-model', current_profile=lambda:profile.copy())
        except ValueError:
            pass
        else:
            raise AssertionError('unqualified provider profile is advertised as launchable')
        agent.cfg['providers']['vision']['tutor_image_enabled'] = True
        profile['profile_revision'] = 'profile-2'
        try:
            host._current()
        except ValueError:
            pass
        else:
            raise AssertionError('changed host profile preserves authorization')
        host.stop()
    print('PASS authenticated shared-service source/image factory and profile retirement; no HTTP or capture')


def check_runtime_approval_projection():
    from fake_provider import FakeProvider
    from test_tutor_gateway import settings
    from test_tutor_host import review_host
    from loop import Agent
    from tutor_connection import VerifiedNativeExecutable
    from tutor_authority import SourceApprovalRequired
    import approvals
    with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as cleanup:
        root=pathlib.Path(tmp)/'experts'/'owned';root.mkdir(parents=True)
        provider=FakeProvider();cleanup.callback(provider.stop);settings(root,provider);agent=Agent(root)
        def close_log():
            logger=logging.getLogger('agent:'+str(root))
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
        cleanup.callback(close_log)
        profile={'profile_revision':'profile-1','purpose':'source-explanation','retention_policy_id':'retention-1',
            'budget_policy_id':'policy-1','budget_reservation_id':'budget-1','budget_ceiling_usd':1.0,
            'provider_models':{'vision':'vision-model'}}
        exe=pathlib.Path(tmp)/'native'/'owned.exe';exe.parent.mkdir();exe.write_bytes(b'MZowned')
        runtime=R.FleetTutorRuntime(tmp);cleanup.callback(runtime.close)
        runtime.install('owned',device_actor='owner',native=VerifiedNativeExecutable.from_host(exe),
            host_factory=R.source_host_factory(tmp,'owned','owner',agent,provider='vision',model='vision-model',current_profile=lambda:profile.copy()))
        proof=['owner']
        class Peer:
            ready=True
            def stop(self):self.ready=False
        def launch(host,*args,**kwargs):host._connection=Peer();return host._connection
        with patch.object(NativeTutorHost,'launch',launch), \
             patch.object(NativeTutorHost,'run',lambda host,*,stop_event:stop_event.wait(3)):
            runtime.launch('owned','owner',lambda:proof[0]);host=runtime._active['owned']['host']
            sample,_,receipt=review_host();sample.stop()
            try:host.select_source(receipt)
            except SourceApprovalRequired as error:pending=error.approval_id
            else:raise AssertionError('source did not wait for approval')
            assert runtime.approval_state('owned',pending)=='CURRENT_PENDING'
            assert runtime.approval_state('owned','foreign-id')=='RETIRED_OR_UNAVAILABLE'
            assert runtime.approval_state('foreign',pending)=='RETIRED_OR_UNAVAILABLE'
            assert host._session is None and not provider.requests
            import ui
            class Handler(ui.Handler):pass
            Handler.home=tmp;Handler.token=None;Handler.tutor_runtime=runtime
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def decide(id,op):
                request=urllib.request.Request(base+'/api/experts/owned/approval',data=json.dumps({'id':id,'op':op}).encode(),
                    headers={'Content-Type':'application/json','Origin':base},method='POST')
                try:
                    with urllib.request.urlopen(request,timeout=3) as response:return response.status,json.load(response)
                except urllib.error.HTTPError as error:return error.code,json.load(error)
            try:
                assert decide(pending,'execute')[0]==400 and approvals.load(str(root),pending)['status']=='pending'
                original_decide=approvals.decide
                def stopped_before_commit(*args,**kwargs):
                    host._source_authority.retire()
                    return original_decide(*args,**kwargs)
                with patch.object(approvals,'decide',stopped_before_commit):
                    assert decide(pending,'grant')[0]==409, 'retirement immediately before decision wrote stale owner grant'
                assert approvals.load(str(root),pending)['status']=='pending'
                try:host.select_source({**receipt,'source_id':'source-after-race','source_revision':'revision-after-race','capture_epoch':2})
                except SourceApprovalRequired as error:pending=error.approval_id
                else:raise AssertionError('replacement did not require exact approval')
                entered=threading.Event(); release=threading.Event(); failures=[]
                original_load=approvals.load
                def delayed_load(*args,**kwargs):
                    if threading.current_thread().name=='owned-source-decision' and not entered.is_set():
                        entered.set(); assert release.wait(2)
                    return original_load(*args,**kwargs)
                def delayed_decision():
                    try:runtime.decide_approval('owned',pending,True,'',lambda:None)
                    except SourceApprovalRequired as error:failures.append(error.code)
                with patch.object(approvals,'load',delayed_load):
                    decision=threading.Thread(target=delayed_decision,name='owned-source-decision');decision.start()
                    assert entered.wait(2)
                    began=time.monotonic();host.stop_sharing();assert time.monotonic()-began<.5
                    release.set();decision.join(2);assert not decision.is_alive() and failures
                assert original_load(str(root),pending)['status']=='pending','delayed decision changed stopped owner history'
                try:host.select_source({**receipt,'source_id':'source-current-list','source_revision':'revision-current-list','capture_epoch':3})
                except SourceApprovalRequired as error:pending=error.approval_id
                else:raise AssertionError('new current source did not require approval')
                with patch.object(approvals,'pending',return_value=[]),patch.object(approvals,'history',return_value=[]):
                    with urllib.request.urlopen(base+'/api/experts/owned/approvals',timeout=3) as response:visible=json.load(response)
                    assert any(r['id']==pending for r in visible['pending']), 'current pending source lost outside bounded lists'
                status,answer=decide(pending,'grant')
                assert status==200 and answer['next']=='retry_source_authorization',answer
                assert runtime.approval_state('owned',pending)=='CURRENT_APPROVED'
                assert host._session is None and not provider.requests, 'owner decision starts capture/provider'
                with patch.object(approvals,'pending',return_value=[]),patch.object(approvals,'history',return_value=[]):
                    with urllib.request.urlopen(base+'/api/experts/owned/approvals',timeout=3) as response:visible=json.load(response)
                    assert any(r['id']==pending and r['source_approval_state']=='CURRENT_APPROVED' for r in visible['history']), 'current grant lost its withdrawal control outside history'
                status,answer=decide(pending,'deny')
                assert status==200 and answer['next']=='source_sharing_withdrawn',answer
                assert approvals.load(str(root),pending)['status']=='granted' and runtime.approval_state('owned',pending)=='RETIRED_OR_UNAVAILABLE'
                second={**receipt,'source_id':'source-2','source_revision':'revision-2','capture_epoch':2}
                try:host.select_source(second)
                except SourceApprovalRequired as error:stopped_id=error.approval_id
                else:raise AssertionError('fresh source did not wait')
                host.stop_sharing()
                assert decide(stopped_id,'grant')[0]==409
                assert approvals.load(str(root),stopped_id)['status']=='pending', 'stale decision mutates owner history'
                with urllib.request.urlopen(base+'/api/experts/owned/approvals',timeout=3) as response:visible=json.load(response)
                assert any(r['id']==stopped_id and r['source_approval_state']=='RETIRED_OR_UNAVAILABLE' for r in visible['pending'])
                assert all(r['source_approval_state']=='RETIRED_OR_UNAVAILABLE' for r in visible['pending'])
            finally:
                server.shutdown();server.server_close();worker.join(2)
            runtime.stop('owned','owner',lambda:proof[0])
            assert runtime.approval_state('owned',pending)=='RETIRED_OR_UNAVAILABLE'
    print('PASS current runtime source approval projection: exact pending/granted/id/project/Stop; no capture or forged decision')


def check_actual_panel_native(policy_change=False):
    """Explicit owned native opt-in; no picker, pixels or provider calls."""
    import ui
    from fake_provider import FakeProvider
    from test_tutor_gateway import settings
    from loop import Agent
    from tutor_connection import VerifiedNativeExecutable
    native = os.environ.get('AGENT_TUTOR_NATIVE_FIXTURE')
    assert native, 'owned native fixture opt-in is required'
    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as cleanup:
        root = pathlib.Path(tmp) / 'experts' / 'owned'; root.mkdir(parents=True)
        provider = FakeProvider(); cleanup.callback(provider.stop)
        settings(root, provider); agent = Agent(root)
        def close_log():
            logger = logging.getLogger('agent:' + str(root))
            for handler in list(logger.handlers): handler.close(); logger.removeHandler(handler)
        cleanup.callback(close_log)
        profile = {'profile_revision':'profile-1', 'purpose':'source-explanation',
                   'retention_policy_id':'retention-1', 'budget_policy_id':'budget-policy-1',
                   'budget_reservation_id':'budget-1', 'budget_ceiling_usd':1.0,
                   'provider_models':{'vision':'vision-model'}}
        runtime = R.FleetTutorRuntime(tmp)
        runtime.install('owned', device_actor='owner',
            native=VerifiedNativeExecutable.from_host(native, arguments=('--native-host-fixture',)),
            host_factory=R.source_host_factory(tmp, 'owned', 'owner', agent, provider='vision',
                model='vision-model', current_profile=lambda:profile.copy()))
        cleanup.callback(runtime.close)
        class Handler(ui.Handler): pass
        Handler.home=tmp; Handler.token=None; Handler.tutor_runtime=runtime
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            def post(action):
                request=urllib.request.Request(base+'/api/experts/owned/tutor/'+action,
                    data=b'{}',headers={'Content-Type':'application/json','Origin':base},method='POST')
                with urllib.request.urlopen(request,timeout=10) as response:return json.load(response)
            assert post('launch')['state']=='RUNNING'
            entry=runtime._active['owned']; host=entry['host']; process=host._connection._process
            assert host._source_authority is not None and host._session is None
            assert host._learning_service is runtime.learning and not provider.requests
            if policy_change:
                settings_path=root/'settings.toml'
                settings_path.write_bytes(settings_path.read_bytes().replace(b'tutor_image_enabled = true',b'tutor_image_enabled = false'))
            else:
                assert post('stop')['state']=='STOPPED'
            process.wait(timeout=5)
            assert process.poll() is not None and not runtime._active and not provider.requests
        finally:
            runtime.close(); server.shutdown(); server.server_close(); thread.join(2)
    print('PASS actual Fleet HTTP launch/shared service/existing source authority/native handshake/'+('on-disk policy withdrawal' if policy_change else 'Stop')+' child exit; zero capture or HTTP provider calls')


if __name__ == '__main__':
    main()
