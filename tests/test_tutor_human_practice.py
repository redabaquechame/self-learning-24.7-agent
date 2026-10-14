import sys,pathlib,tempfile,copy
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent))
import learning_contracts as L
import tutor_assessment as E
import tutor_attempts as A
from tutor_human_practice import HostPractice

def refused(fn):
    try: fn()
    except (L.ContractError,A.SubmissionRefused): return
    raise AssertionError('practice admitted invalid operation')

def check_host_assigned_practice():
    with tempfile.TemporaryDirectory() as root:
        directory=E.HumanAssessmentDirectory()
        service=L.LearningService(human_assessment=directory)
        rights={'learning:read','course:write','assignment:write','session:write','attempt:write','assessment:evaluate'}
        binding=service.bind_host('learner','tenant','policy','grant','course',rights,{'capture.selected'})
        api=service.adapter('native_companion',binding)
        course=api.command('course.register',{'title':'Owned JSON task','course_revision':'course'},'course','course')['record']
        assignment=api.command('assignment.create',{'course_id':course['id'],'assignee_id':'learner'},'assignment','assignment')['record']
        authority=E.HumanAssessmentAuthority(A.AttemptCustody(root,project_id='project',key=b'k'*32))
        exposure={'coverage':'UNKNOWN','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
        rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'owned','revision':'r1','operation':'JSON_EQUALS','expected':{'total':42}})
        authority.authorize_assignment(assignment['id'],'learner','tenant','course','variant',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
        directory.register_assignment(authority,assignment['id'])
        live=[True]
        def current():
            if not live[0]: raise L.Unauthorized('binding retired')
        practice=HostPractice(api,assignment_id=assignment['id'],variant_revision='variant',project_id='project',current_check=current)
        assert 'expected' not in str(practice.status()) and 'rubric' not in str(practice.status())
        refused(lambda:practice.upload(b'{"total":42}'))
        refused(lambda:HostPractice(api,assignment_id=assignment['id'],variant_revision='foreign',project_id='project',current_check=current))
        refused(lambda:HostPractice(api,assignment_id=assignment['id'],variant_revision='variant',project_id='foreign',current_check=current))
        first=practice.start(); token=practice.help_token()
        refused(practice.submit)
        wrong=practice.upload(b'{"total":7}')
        result=practice.submit()
        assert result['predicate_correct'] is False and result['passing'] is None and not result['independent_success']
        assert practice.submit()==result
        practice.start()
        practice.record_help(token,answer_exposed=True)
        practice.upload(b'{"total":42}')
        result=practice.submit()
        assert result['predicate_correct'] is True and result['passing'] is None
        assert result['independence']=='UNKNOWN', 'late old answer contaminated new attempt'
        practice.record_help(practice.help_token(),answer_exposed=True)
        assert practice.status()['assessment']['projection_status']=='STALE_EXPOSURE'
        assert practice.submit()['projection_status']=='STALE_EXPOSURE', 'retry returned obsolete cached judgment'
        other=service.adapter('standalone_portal',binding).command('records.list',{'kind':'assessment'})['records']
        assert len(other)==2 and all(not x['independent_success'] for x in other)
        practice.start(); practice.upload(b'{"total":42}'); practice.cancel()
        refused(practice.submit); refused(lambda:practice.upload(b'42'))
        # Exercise host admission separately from the pure practice workflow.
        from tutor_host import NativeTutorHost
        from tutor_service import TutorService
        from test_tutor_host import fixture
        owner=fixture()[-1];owner.update(user_id='learner',tenant_id='tenant',project_id='project')
        host=NativeTutorHost(TutorService(enabled=True),lambda:copy.deepcopy(owner),api)
        assert callable(getattr(host,'install_practice',None)), 'native host has no trusted practice installation'
        host.install_practice(assignment_id=assignment['id'],variant_revision='variant')
        class Connection:
            ready=True
            def __init__(self):self.responses=[]
            def send(self,kind,body,**options):
                if 'release_check' in options: assert options['release_check']()
                self.responses.append((kind,body))
            def stop(self):self.ready=False
        connection=Connection();host._connection=connection
        import tutor_transport as W
        import base64
        def dispatch(operation,payload):
            message={'message_type':'PRACTICE_REQUEST','message_id':'owned-request','protocol_version':'1.2',
                'deadline_monotonic_ms':W.windows_monotonic_ms()+15000,
                'body':{'schema':'fleet.tutor.practice-request.v1','operation':operation,'payload':payload}}
            host._dispatch_event(message,connection,host._selection_generation)
            return connection.responses[-1]
        assert dispatch('START',{})[0]=='PRACTICE_RESULT'
        assert dispatch('UPLOAD',{'artifact_base64':base64.b64encode(b'{"total":42}').decode()})[1]['artifact_count']==1
        kind,observed=dispatch('SUBMIT',{})
        assert kind=='PRACTICE_RESULT' and observed['predicate_correct'] is True and not observed['independent_success']
        host.stop()
        refused(host._practice.status)
        practice.start(); live[0]=False
        refused(lambda:practice.upload(b'{"total":42}')); refused(practice.submit)
    print('PASS exact host task, actual wrong/right bytes, no digest-only credit, late help isolation, shared result, cancel and retired binding')

if __name__ == "__main__":
    check_host_assigned_practice()
