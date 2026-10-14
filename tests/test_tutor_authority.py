"""Existing-approval source authority: no native pixels/provider or new issuer."""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from common import AGENT_DIR
sys.path.insert(0,AGENT_DIR)
import approvals
import org
from tutor_authority import SourceApprovalAuthority,SourceApprovalRequired
from test_tutor_host import review_host


def context():
    return {'user_id':'user-1','tenant_id':'tenant-1','project_id':'project-1','actor_id':'owner',
        'profile_revision':'profile-1','purpose':'source-explanation','retention_policy_id':'retention-1',
        'budget_policy_id':'policy-1','budget_reservation_id':'budget-1','budget_ceiling_usd':1.0,
        'provider_models':{'vision':'owned.model/v2:variant'}}


def expect(code,operation):
    try:operation()
    except SourceApprovalRequired as error:
        assert error.code==code,(code,error.code)
        return error
    raise AssertionError('source authority did not refuse '+code)


def check_host_pending_retry():
    from learning_contracts import LearningService
    from tutor_service import TutorService
    from tutor_host import NativeTutorHost
    with tempfile.TemporaryDirectory(prefix='owned-host-approval-',dir=os.environ.get('AGENT_TEST_TMP')) as home:
        root=Path(home)/'experts'/'owned';root.mkdir(parents=True)
        value=context();clock=[1000]
        authority=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:clock[0],lifetime_ms=5000,instance_id='host-launch-1')
        learning=LearningService();binding=learning.bind_host('user-1','tenant-1','policy-1','grant-1','course-1',
            ['learning:read','session:write'],['capture.selected'])
        host=NativeTutorHost(TutorService(enabled=True),authority.owner_state,learning.adapter('native_companion',binding),source_authority=authority)
        sample,_,receipt=review_host();sample.stop()
        try:
            pending=expect('SOURCE_APPROVAL_PENDING',lambda:host.select_source(receipt))
            assert host._session is None and host._capture_authorization is None and not host._observations
            approvals.decide(str(root),pending.approval_id,True,'owned test approval before explicit retry')
            clock[0]=2000
            authorization=host.select_source(receipt)
            assert host._session is not None and host._capture_authorization==authorization and authorization['expires_at_monotonic_ms']==6000 and not authorization['grant_created']
            owner={**authority.owner_state(),'session_id':host._session.session_id}
            assert authority.grant_view(owner)['granted_by_ref']==pending.approval_id
            assert authority.budget_view(owner)['agent_root']==str(root.resolve())
            host.stop_sharing();assert authority.current_source() is None
            try:host.select_source(receipt)
            except (RuntimeError,ValueError):pass
            else:raise AssertionError('stopped source reauthorized')
        finally:host.stop()
    print('[host source approval] pending opens no capture/session; explicit same-source retry uses existing owner grant and original lease; Stop retires authority')


def check_completion_stop_lock_order():
    import threading
    from learning_contracts import LearningService
    from tutor_service import TutorService
    from tutor_host import NativeTutorHost
    with tempfile.TemporaryDirectory(prefix='owned-source-lock-order-') as home:
        root=Path(home)/'experts'/'owned';root.mkdir(parents=True)
        authority=SourceApprovalAuthority(home,str(root),'owned',context,clock_ms=lambda:1000,instance_id='lock-order-launch')
        learning=LearningService();binding=learning.bind_host('user-1','tenant-1','policy-1','grant-1','course-1',
            ['learning:read','session:write'],['capture.selected'])
        host=NativeTutorHost(TutorService(enabled=True),authority.owner_state,learning.adapter('native_companion',binding),source_authority=authority)
        sample,_,receipt=review_host();sample.stop()
        completion=threading.Event();stop_has_host_lock=threading.Event();outcomes=[]
        original_request=authority.request_source;original_retire=authority.retire
        def request(receipt, *, current_attempt=None):
            calls=[0]
            def attempt():
                calls[0]+=1
                if calls[0]==2:
                    completion.set()
                    assert stop_has_host_lock.wait(1), 'Stop did not reach authority retirement'
                return current_attempt()
            return original_request(receipt,current_attempt=attempt)
        def retire():
            if threading.current_thread().name=='owned-source-stop':stop_has_host_lock.set()
            return original_retire()
        authority.request_source=request;authority.retire=retire
        def select():
            try:host.select_source(receipt)
            except SourceApprovalRequired as error:outcomes.append(error.code)
        def stop():
            assert completion.wait(1)
            host.stop()
        selection=threading.Thread(target=select,daemon=True,name='owned-source-completion')
        stopper=threading.Thread(target=stop,daemon=True,name='owned-source-stop')
        selection.start();stopper.start();selection.join(1.5);stopper.join(1.5)
        assert not selection.is_alive() and not stopper.is_alive(), 'source completion and Stop deadlocked across host/authority locks'
        assert outcomes==['SOURCE_RETIRED'] and host._session is None and host._pending_source is None
        pending=approvals.pending(str(root));assert len(pending)==1
        approvals.decide(str(root),pending[0]['id'],True,'late owned decision after completed Stop')
        assert authority.current_source() is None and host._capture_authorization is None
    print('[source lock order] concurrent approval completion/Stop both finish; late approval creates no source authority')


def check_current_approval_projection():
    with tempfile.TemporaryDirectory(prefix='owned-current-source-view-') as home:
        root=Path(home)/'experts'/'owned';root.mkdir(parents=True)
        clock=[1000];value=context()
        authority=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:clock[0],lifetime_ms=5000,instance_id='current-view-launch')
        sample,_,receipt=review_host();sample.stop()
        pending=expect('SOURCE_APPROVAL_PENDING',lambda:authority.request_source(receipt))
        view=authority.current_approval()
        assert view['approval_id']==pending.approval_id and view['status']=='pending' and view['expiry']==6000
        assert authority.current_source() is None, 'pending projection grants capture authority'
        approvals.decide(str(root),pending.approval_id,True,'owned current approval')
        assert authority.current_approval()['status']=='granted'
        with patch.object(authority,'_reader',wraps=authority._reader) as reader:
            owner=authority.owner_state()
            assert reader.call_count==2, 'owner state duplicated already verified source context'
            assert owner['source_ids']==[receipt['source_id']]
        original_reader=authority._reader;reads=[0]
        def changes_during_record_read():
            reads[0]+=1;result=original_reader()
            if reads[0]==2:result['profile_revision']='changed-profile'
            return result
        with patch.object(authority,'_reader',changes_during_record_read):
            expect('SOURCE_CONTEXT_CHANGED',authority.owner_state)
        import threading,time
        entered=threading.Event();release=threading.Event();seen=[];original_load=approvals.load
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(2)
            return original_load(*args,**kwargs)
        with patch.object(approvals,'load',side_effect=delayed):
            worker=threading.Thread(target=lambda:seen.append(authority.current_approval()),daemon=True);worker.start()
            assert entered.wait(1)
            started=time.monotonic();authority.retire()
            assert time.monotonic()-started<.5, 'read-only projection blocks source retirement'
            release.set();worker.join(1);assert not worker.is_alive() and seen==[None],seen
        assert authority.current_approval() is None
        assert approvals.load(str(root),pending.approval_id)['status']=='granted', 'retirement forges an owner decision'
        fresh=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:clock[0],lifetime_ms=5000,instance_id='current-view-restart')
        pending=expect('SOURCE_APPROVAL_PENDING',lambda:fresh.request_source(receipt))
        def expires_during_read(*args,**kwargs):
            record=original_load(*args,**kwargs);clock[0]=6000;return record
        with patch.object(approvals,'load',side_effect=expires_during_read):
            assert fresh.current_approval() is None, 'lease expired during protected read but projection stayed actionable'
        clock[0]=6000;assert fresh.current_approval() is None, 'expired current approval remains actionable'
    print('[current source approval] pending/granted views retain exact lease; Stop/restart/expiry cannot revive prior scope or forge a decision')


def check_current_role_and_pending_stop():
    import threading
    import time
    from learning_contracts import LearningService
    from tutor_service import TutorService
    from tutor_host import NativeTutorHost
    with tempfile.TemporaryDirectory(prefix='owned-source-role-',dir=os.environ.get('AGENT_TEST_TMP')) as home:
        root=Path(home)/'experts'/'owned';root.mkdir(parents=True)
        owner_email='owner@example.invalid';operator='operator@example.invalid';viewer='viewer@example.invalid'
        org.create(home,'Owned fixture org',owner_email)
        org.add_user(home,owner_email,operator,'operator');org.add_user(home,owner_email,viewer,'viewer')
        value=context();value['actor_id']=viewer
        expect('SOURCE_ACTOR_REFUSED',lambda:SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:1000,instance_id='role-launch-1'))
        assert not (root/'approvals').exists(), 'viewer created a pending source approval'
        value['actor_id']=operator
        authority=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:1000,instance_id='role-launch-2')
        org.set_role(home,owner_email,operator,'viewer')
        expect('SOURCE_ACTOR_REFUSED',authority.owner_state)
        value['actor_id']=owner_email
        authority=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:1000,instance_id='late-stop-launch')
        learning=LearningService();binding=learning.bind_host('user-1','tenant-1','policy-1','grant-1','course-1',
            ['learning:read','session:write'],['capture.selected'])
        host=NativeTutorHost(TutorService(enabled=True),authority.owner_state,learning.adapter('native_companion',binding),source_authority=authority)
        sample,_,receipt=review_host();sample.stop()
        entered=threading.Event();release=threading.Event();outcomes=[];original=approvals.request
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(2);return original(*args,**kwargs)
        def select():
            try:outcomes.append(host.select_source(receipt))
            except BaseException as error:outcomes.append(error)
        with patch.object(approvals,'request',side_effect=delayed):
            worker=threading.Thread(target=select);worker.start()
            try:
                assert entered.wait(1)
                started=time.monotonic();host.stop_sharing();assert time.monotonic()-started<.5
                release.set();worker.join(2)
                assert not worker.is_alive() and len(outcomes)==1 and isinstance(outcomes[0],SourceApprovalRequired),outcomes
                assert outcomes[0].code=='SOURCE_RETIRED' and host._session is None and host._capture_authorization is None
                record=approvals.history(str(root))[0]
                approvals.decide(str(root),record['id'],True,'owned late owner approval after local Stop')
                assert authority.current_source() is None
                try:host.select_source(receipt)
                except (RuntimeError,ValueError):pass
                else:raise AssertionError('late approved stopped source reactivated')
            finally:release.set();worker.join(2);host.stop()
    print('[source current role/Stop] real viewer/revoked role cannot authorize; delayed existing approval after prompt Stop never opens source/session')


def main():
    check_current_approval_projection()
    check_completion_stop_lock_order()
    check_host_pending_retry()
    check_current_role_and_pending_stop()
    with tempfile.TemporaryDirectory(prefix='owned-source-authority-',dir=os.environ.get('AGENT_TEST_TMP')) as home:
        root=Path(home)/'experts'/'owned';root.mkdir(parents=True)
        value=context();clock=[1000]
        authority=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),
            clock_ms=lambda:clock[0],lifetime_ms=5000,instance_id='owned-launch-1')
        host,_,receipt=review_host();host.stop()
        pending=expect('SOURCE_APPROVAL_PENDING',lambda:authority.request_source(receipt))
        assert authority.current_source() is None
        assert approvals.load(str(root),pending.approval_id)['status']=='pending'
        again=expect('SOURCE_APPROVAL_PENDING',lambda:authority.request_source(receipt))
        assert again.approval_id==pending.approval_id
        org.check(home,'owner','approve','owned')
        approvals.decide(str(root),pending.approval_id,True,'owned test existing owner decision')
        clock[0]=2000;approved=authority.request_source(receipt)
        assert approved['start']==1000 and approved['expiry']==6000
        clock[0]=3000;assert authority.request_source(receipt)['expiry']==6000
        for field,replacement in [('user_id','foreign-user'),('tenant_id','foreign-tenant'),('project_id','foreign-project'),
            ('profile_revision','changed-profile'),('retention_policy_id','changed-retention'),('budget_policy_id','changed-policy'),
            ('budget_reservation_id','changed-budget'),('budget_ceiling_usd',2.0),('provider_models',{'vision':'other-model'})]:
            saved=copy.deepcopy(value[field]);value[field]=replacement
            expect('SOURCE_CONTEXT_CHANGED',authority.current_source);value[field]=saved
        clock[0]=6000;assert authority.current_source() is None
        expect('SOURCE_APPROVAL_EXPIRED',lambda:authority.request_source(receipt))
        clock[0]=3000;authority.retire();expect('SOURCE_RETIRED',lambda:authority.request_source(receipt))
        # New launcher instance cannot reuse an old exact-call approval.
        fresh=SourceApprovalAuthority(home,str(root),'owned',lambda:copy.deepcopy(value),clock_ms=lambda:clock[0],lifetime_ms=5000,instance_id='owned-launch-2')
        denied=expect('SOURCE_APPROVAL_PENDING',lambda:fresh.request_source(receipt))
        assert denied.approval_id!=pending.approval_id
        approvals.decide(str(root),denied.approval_id,False,'owned test existing owner denial')
        expect('SOURCE_APPROVAL_DENIED',lambda:fresh.request_source(receipt));assert fresh.current_source() is None
        # Malformed selected source cannot create another approval.
        before=list((root/'approvals').glob('*.json'))
        expect('SOURCE_RECEIPT_INVALID',lambda:fresh.request_source({**receipt,'native_handle_digest':'bad'}))
        assert list((root/'approvals').glob('*.json'))==before
    print('PASS test_tutor_authority: existing owner exact-call pending/grant/denial, original lease, scope/profile/retirement and malformed source admission; no pixels/provider')


if __name__=='__main__':main()
