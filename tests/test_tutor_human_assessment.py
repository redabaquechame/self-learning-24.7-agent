"""SC-2F actual submitted bytes, verification-only custody and shared service."""
import copy
import hashlib
import json
import os
import shutil
import inspect
from pathlib import Path
import sys
import tempfile
import pathlib
import concurrent.futures
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def require_refused(operation):
    from tutor_attempts import SubmissionRefused
    from learning_contracts import ContractError
    try:
        operation()
    except (SubmissionRefused,ContractError):
        return
    raise AssertionError('invalid/foreign/tampered submission was admitted')


def check_actual_wrong_and_correct_bytes():
    import tutor_attempts as A
    import tutor_assessment as E
    with tempfile.TemporaryDirectory(prefix='human-submission-', dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        custody = A.AttemptCustody(directory, project_id='project-1', key=b'k' * 32)
        scope = dict(tenant_id='tenant-1', project_id='project-1', learner_id='learner-1',
                     course_revision='course-1', variant_revision='variant-1')
        rubric = E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1', 'rubric_id':'rubric-1',
            'revision':'rubric-r1', 'operation':'JSON_EQUALS', 'expected':{'total':42}})
        authority = E.HumanAssessmentAuthority(custody)
        exposure = {'coverage':'UNKNOWN','actor':'USER','assistance':'NONE', 'answer_exposed':False,
                    'repeated_example':False,'accommodation_allowed':True}
        authority.authorize_assignment('assignment-1','learner-1','tenant-1','course-1','variant-1',rubric,
                                       exposure_reader=lambda: copy.deepcopy(exposure))
        binding = type('OwnedBinding', (), {'principal_id':'learner-1','tenant_id':'tenant-1','course_revision':'course-1',
                                           'entitlements':frozenset()})()
        fixtures=Path(__file__).resolve().parent.parent/'evaluation/tutor/submission_fixtures'
        manifest=json.loads((fixtures/'manifest.json').read_text(encoding='utf-8'))
        assert manifest['qualification']=='LOCAL_ONLY'
        for name,expected in manifest['files'].items():
            payload=(fixtures/name).read_bytes()
            assert hashlib.sha256(payload).hexdigest()==expected['sha256'] and len(payload)==expected['size_bytes']
        for suffix, raw, correct in [('wrong',(fixtures/'incorrect.json').read_bytes(),False),('correct',(fixtures/'correct.json').read_bytes(),True)]:
            attempt = {'id':'attempt-'+suffix,'assignment_id':'assignment-1','learner_id':'learner-1',
                       'tenant_id':'tenant-1','variant_revision':'variant-1'}
            authority.begin(attempt,binding)
            receipt = authority.ingest(attempt['id'],binding,raw)
            submission = {'id':'submission-'+suffix,'attempt_id':attempt['id'],'learner_id':'learner-1',
                          'tenant_id':'tenant-1','artifact_digests':[hashlib.sha256(raw).hexdigest()]}
            authority.submit(submission,binding)
            before = {p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*.blob')}
            with patch('goal.pursue',side_effect=AssertionError('human grading called pursuit')), \
                 patch('mastery._execute_task',side_effect=AssertionError('human grading invoked agent evaluator')), \
                 patch('pathlib.Path.write_bytes',side_effect=AssertionError('grading wrote an artifact')), \
                 patch('pathlib.Path.read_bytes',side_effect=AssertionError('grading used an unbounded file read')), \
                 patch('fileauth._atomic_write',side_effect=AssertionError('grading invoked artifact repair')):
                verdict = authority.evaluate(submission['id'],binding)
                replay = authority.evaluate(submission['id'],binding)
            assert verdict == replay and verdict['predicate_correct'] is correct, verdict
            assert verdict['passing'] is None and verdict['independent_success'] is False
            assert verdict['qualification']=='LOCAL_ONLY' and verdict['independence']=='UNKNOWN'
            assert before == {p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*.blob')}
            metadata, submitted = custody.read_submission(submission['id'],scope)
            assert submitted == (raw,) and metadata['artifact_digests']==submission['artifact_digests']
            assert 'expected' not in verdict and '{"total":42}' not in json.dumps(verdict)
        print('[human exact bytes] wrong/right owned JSON verified without pursuit or repair; original blobs unchanged; local/unknown evidence creates zero independent credit')


def check_custody_refusals_and_limits():
    import tutor_attempts as A
    with tempfile.TemporaryDirectory(prefix='human-custody-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        custody = A.AttemptCustody(directory,project_id='project-1',key=b'k'*32)
        scope = dict(tenant_id='tenant-1',project_id='project-1',learner_id='learner-1',course_revision='course-1',variant_revision='variant-1')
        custody.begin('attempt-1',scope,{'rubric_digest':'a'*64})
        for raw in [b'{',b'{"a":1,"a":2}',b'{"a":NaN}',b'PK\x03\x04archive',b'['*25+b'0'+b']'*25,b' '* (A.MAX_ARTIFACT_BYTES+1)]:
            require_refused(lambda raw=raw:custody.ingest('attempt-1',scope,raw))
        for field in ['tenant_id','project_id','learner_id','course_revision','variant_revision']:
            require_refused(lambda field=field:custody.ingest('attempt-1',{**scope,field:'foreign'},b'{}'))
        require_refused(lambda:custody.submit('submission-forged','attempt-1',scope,['f'*64]))
        receipt = custody.ingest('attempt-1',scope,b'{"a":1}')
        blob = next(Path(directory).rglob('*.blob')); original = blob.read_bytes()
        blob.write_bytes(b'{"a":2}')
        require_refused(lambda:custody.submit('submission-tampered','attempt-1',scope,[receipt['artifact_digest']]))
        blob.write_bytes(original)
        custody.submit('submission-1','attempt-1',scope,[receipt['artifact_digest']])
        assert custody.read_submission('submission-1',scope)[1]==(original,)
        require_refused(lambda:custody.submit('submission-late','attempt-1',scope,[receipt['artifact_digest']]))
        for field in ['tenant_id','project_id','learner_id','course_revision','variant_revision']:
            require_refused(lambda field=field:custody.read_submission('submission-1',{**scope,field:'foreign'}))
        with patch.dict(os.environ,{'AGENT_TASK_ID':'owned-negative','AGENT_ROLE':'worker'}):
            try: custody.begin('worker-attempt',scope,{})
            except SystemExit: pass
            else: raise AssertionError('worker created submission authority')
        custody.begin('upload-limit',scope,{})
        for number in range(A.MAX_ARTIFACTS): custody.ingest('upload-limit',scope,json.dumps({'n':number}).encode())
        require_refused(lambda:custody.ingest('upload-limit',scope,b'{"n":999}'))
    print('[human custody] malformed/archive/deep/duplicate/nonfinite/oversized, foreign scope, missing bytes, overwrite, late submit and worker authority refuse; upload count bounded')


def check_group_sum_and_exposure():
    import tutor_attempts as A
    import tutor_assessment as E
    with tempfile.TemporaryDirectory(prefix='human-group-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        custody = A.AttemptCustody(directory,project_id='project-1',key=b'k'*32)
        rubric = E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'groups','revision':'r1',
            'operation':'GROUP_SUM','expected':{'rows':[{'group':'A','amount':0.1},{'group':'A','amount':0.2},{'group':'B','amount':7}]}})
        assert rubric.verify_bytes(b'{"B":7.0,"A":0.3}')
        assert not rubric.verify_bytes(b'{"B":true,"A":0.3}') and not rubric.verify_bytes(b'{"A":0.3}')
        binding = SimpleNamespace(principal_id='learner-1',tenant_id='tenant-1',course_revision='course-1',entitlements=frozenset())
        base = {'coverage':'COMPLETE','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
        cases = [('plain',{},'ELIGIBLE_UNDER_RECORDED_CONDITIONS'),('unknown',{'coverage':'UNKNOWN'},'UNKNOWN'),
            ('agent',{'actor':'AGENT'},'ASSISTED'),('shared',{'actor':'SHARED'},'ASSISTED'),('hint',{'assistance':'HINT'},'ASSISTED'),
            ('answer',{'answer_exposed':True},'ASSISTED'),('repeat',{'repeated_example':True},'ASSISTED'),
            ('screen-reader',{'assistance':'ACCOMMODATION'},'ELIGIBLE_UNDER_RECORDED_CONDITIONS'),
            ('unknown-aid',{'assistance':'ACCOMMODATION','accommodation_allowed':False},'ASSISTED')]
        authority = E.HumanAssessmentAuthority(custody)
        for name,change,classification in cases:
            exposure = {**base,**change}
            aid = 'assignment-'+name
            authority.authorize_assignment(aid,'learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda exposure=exposure:copy.deepcopy(exposure))
            attempt={'id':'attempt-'+name,'assignment_id':aid,'learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'}
            authority.begin(attempt,binding)
            receipt=authority.ingest(attempt['id'],binding,b'{"A":0.3,"B":7}')
            submission={'id':'submission-'+name,'attempt_id':attempt['id'],'learner_id':'learner-1','tenant_id':'tenant-1','artifact_digests':[receipt['artifact_digest']]}
            authority.submit(submission,binding)
            verdict=authority.evaluate(submission['id'],binding)
            assert verdict['predicate_correct'] and verdict['independence']==classification and not verdict['independent_success'],verdict
            require_refused(lambda:authority.ingest(attempt['id'],binding,b'{"A":8}'))
            for field in ['tenant_id','principal_id','course_revision']:
                foreign=SimpleNamespace(**{**vars(binding),field:'foreign'})
                require_refused(lambda foreign=foreign:authority.evaluate(submission['id'],foreign))
        rubric._spec['expected']['rows'][0]['amount']=999
        require_refused(lambda:authority.evaluate('submission-plain',binding))
    print('[human attribution] numeric alternate outputs verify; unknown/exposed/shared/agent/repeat evidence cannot claim independence; accommodations retain recorded eligibility; rubric changes refuse')


def check_exact_raw_numeric_and_aggregate_boundaries():
    import tutor_attempts as A
    import tutor_assessment as E
    spec=A.decode_artifact(b'{"schema":"tutor.human-rubric/1","rubric_id":"exact","revision":"r1","operation":"GROUP_SUM","expected":{"rows":[{"group":"A","amount":999999999999.00000001}]}}')
    rubric=E.ReviewedRubric.local_check(spec)
    assert rubric.verify_bytes(b'{"A":999999999999.00000001}')
    assert not rubric.verify_bytes(b'{"A":999999999999.00000002}'), 'one eighth decimal place was lost before group grading'
    spec['operation']='JSON_EQUALS';spec['expected']=A.decode_artifact(b'{"A":999999999999.00000001}')
    rubric=E.ReviewedRubric.local_check(spec)
    assert rubric.verify_bytes(b'{"A":999999999999.00000001}')
    assert not rubric.verify_bytes(b'{"A":999999999999.00000002}'), 'JSON grading collapsed distinct raw numbers'
    assert not rubric.verify_bytes(b'{"A":true}')
    print('[human exact numeric bytes] eighth-place large-magnitude differences remain distinct in both predicates')


def check_aggregate_boundaries():
    import tutor_assessment as E
    rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'aggregate','revision':'r1',
        'operation':'GROUP_SUM','expected':{'rows':[{'group':'A','amount':10**12}]*1000}})
    assert rubric.verify_bytes(b'{"A":1000000000000000}'), 'valid1000-row aggregate exceeds per-input bound'
    assert not rubric.verify_bytes(b'{"A":1000000000000001}')
    assert not rubric.verify_bytes(b'{"A":999999999999999}')
    print('[human aggregate output] valid1000-row aggregate and adjacent incorrect output boundaries verify exactly')


def check_shared_service_actual_ingress():
    import learning_contracts as L
    import tutor_attempts as A
    import tutor_assessment as E
    entitlements = {'learning:read','course:write','assignment:write','session:write','attempt:write','assessment:evaluate'}
    records=[]
    for surface in sorted(L.SURFACES):
        with tempfile.TemporaryDirectory(prefix='human-surface-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
            backend=E.HumanAssessmentAuthority(A.AttemptCustody(directory,project_id='project-1',key=b'k'*32))
            service=L.LearningService(clock=lambda:'2026-10-14T04:00:00Z',host_key=b'h'*32,cursor_key=b'c'*32,human_assessment=backend)
            bound=service.bind_host('learner-1','tenant-1','policy-1','grant-1','course-1',entitlements)
            api=service.adapter(surface,bound)
            assert 'assessment.evaluate' in api.command('learning.capabilities')['operations']
            course=api.command('course.register',{'title':'Owned mechanical fixture','course_revision':'course-1'},'course','course')['record']
            assignment=api.command('assignment.create',{'course_id':course['id'],'assignee_id':'learner-1'},'assignment','assignment')['record']
            rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'rubric-1','revision':'r1','operation':'JSON_EQUALS','expected':{'total':42}})
            exposure={'coverage':'UNKNOWN','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
            backend.authorize_assignment(assignment['id'],'learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
            session=api.command('session.open',{'assignment_id':assignment['id']},'session','session')['record']
            attempt=api.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'attempt','attempt')['record']
            raw=b'{"total":41}'; raw_digest=hashlib.sha256(raw).hexdigest()
            payload={'attempt_id':attempt['id'],'artifact_digests':[raw_digest]}
            try: api.command('attempt.submit',payload,'missing-ingress','missing-ingress')
            except (A.SubmissionRefused,L.ContractError): pass
            else: raise AssertionError('frontend digest alone became a submitted human artifact')
            assert service._records[attempt['id']]['state']=='ACTIVE'
            receipt=service.ingest_human_artifact(bound,attempt['id'],raw)
            assert receipt['artifact_digest']==raw_digest
            submission=api.command('attempt.submit',payload,'submit','submit')['record']
            with patch('goal.pursue',side_effect=AssertionError('shared human path pursued goal')), \
                 patch('mastery._execute_task',side_effect=AssertionError('shared human path used agent evaluator')):
                evaluated=api.command('assessment.evaluate',{'submission_id':submission['id']},'evaluate','evaluate')
                replay=api.command('assessment.evaluate',{'submission_id':submission['id']},'replay','evaluate')
            verdict=evaluated['record']
            assert verdict==replay['record'] and replay['transport']['replay']
            assert verdict['predicate_correct'] is False and verdict['passing'] is None and not verdict['independent_success']
            assert len([e for e in service.events(bound) if e['operation']=='assessment.evaluate'])==1
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                repeated=list(pool.map(lambda index:api.command('assessment.evaluate',{'submission_id':submission['id']},
                    'parallel-'+str(index),'parallel-'+str(index))['record'],range(2)))
            assert all(row==verdict for row in repeated), 'new caller keys created multiple verdict records for one immutable submission'
            assert len([e for e in service.events(bound) if e['operation']=='assessment.evaluate'])==1
            assert verdict['schema']=='learning.assessment.v1'
            assessor_bound=service.bind_host('assessor-2','tenant-1','policy-1','grant-1','course-1',
                entitlements|{'assessment:evaluate:any','learning:read:any'})
            second=service.adapter(surface,assessor_bound).command('assessment.evaluate',
                {'submission_id':submission['id']},'second-assessor','second-assessor')['record']
            assert second==verdict and len([e for e in service.events(bound) if e['operation']=='assessment.evaluate'])==1
            cancelled=api.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'cancel-attempt','cancel-attempt')['record']
            api.command('request.cancel',{'target_id':cancelled['id'],'reason':'Owned cancellation witness'},'cancel','cancel')
            files_before={p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
            require_refused(lambda:service.ingest_human_artifact(bound,cancelled['id'],b'{"total":42}'))
            assert files_before=={p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}, 'cancelled ingress stored new artifact'
            for fake in [{'submission_id':submission['id'],'score':100},{'submission_id':submission['id'],'expected':{'total':41}},
                         {'submission_id':submission['id'],'qualification':'REVIEWED_PACK'},{'submission_id':submission['id'],'evaluator':'agent'}]:
                try: api.command('assessment.evaluate',fake,'forged','forged')
                except L.ContractError: pass
                else: raise AssertionError('frontend selected assessment authority')
            foreign=service.bind_host('intruder','tenant-1','policy-1','grant-1','course-1',entitlements)
            assert service.adapter(surface,foreign).command('records.list',{'kind':'assessment'})['records']==[]
            require_refused(lambda:service.ingest_human_artifact(foreign,attempt['id'],raw))
            try: service.adapter(surface,foreign).command('assessment.evaluate',{'submission_id':submission['id']},'foreign','foreign')
            except (L.ContractError,A.SubmissionRefused): pass
            else: raise AssertionError('foreign learner assessed/read private submission')
            records.append({k:v for k,v in verdict.items() if k not in ('sequence',)})
    assert all(row==records[0] for row in records), 'surfaces forked human assessment results'
    default=L.LearningService()
    plain=default.bind_host('learner-1','tenant-1','policy-1','grant-1','course-1',entitlements)
    assert 'assessment.evaluate' not in default.adapter('embed_sdk',plain).command('learning.capabilities')['operations']
    try: default.adapter('embed_sdk',plain).command('assessment.evaluate',{},'unavailable','unavailable')
    except L.ContractError as error: assert 'not implemented' in str(error)
    else: raise AssertionError('default surface silently enabled assessment')
    print('[human shared service] same exact submitted-byte verdict across four sealed adapters; authoritative ingress required; retry/foreign/forged authority/default unavailability preserved')


def check_reviewed_hidden_rubric_binding():
    import tutor_assessment as E
    import tutor_sources
    import tutor_packs
    from test_tutor_sources import source_record
    from test_tutor_packs import seed,authorize_reviewer,CHECKLIST,REVIEWER
    with tempfile.TemporaryDirectory(prefix='human-rubric-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        home=Path(directory)/'home'; home.mkdir(); seed(str(home))
        spec={'schema':'tutor.human-rubric/1','rubric_id':'hidden-rubric','revision':'r1','operation':'JSON_EQUALS','expected':{'total':42}}
        encoded=json.dumps(spec,sort_keys=True).replace('42','999999999999.00000001')
        encoded_wrong=encoded.replace('999999999999.00000001','999999999999.00000002')
        record=source_record(source_id='human-final',excerpt_id='closed-rubric',text=encoded,purpose='final_assessment',source_type='fixture')
        tutor_sources.register_source(str(home),record)
        ref={'source_id':'human-final','revision':'rev-1','excerpt_id':'closed-rubric','tenant_id':'tenant-alpha',
             'project_id':'project-reporting','content_sha256':hashlib.sha256(encoded.encode()).hexdigest()}
        stage=Path(directory)/'stage'; shutil.copytree(Path(__file__).resolve().parent.parent/'teaching_packs/reporting-v1',stage)
        (stage/'assessment_manifest.json').write_text(json.dumps({'schema':'tutor.assessment-manifest/1','items':[ref]}),encoding='utf-8')
        tutor_packs.install_candidate(str(home),str(stage))
        require_refused(lambda:E.ReviewedRubric.from_pack(str(home),'reporting-v1',assessment_ref=ref))
        authorize_reviewer(str(home))
        tutor_packs.review_pack(str(home),'reporting-v1',reviewer_id=REVIEWER,reviewer_kind='subject_matter_human',checklist=CHECKLIST)
        tutor_packs.qualify_pack(str(home),'reporting-v1',reviewer_id=REVIEWER,evidence_ref='SYNTHETIC-ROLE-FIXTURE-ONLY-NO-ACTUAL-SUBJECT-REVIEW')
        rubric=E.ReviewedRubric.from_pack(str(home),'reporting-v1',assessment_ref=ref)
        assert rubric.verify_bytes(b'{"total":999999999999.00000001}') and not rubric.verify_bytes(b'{"total":999999999999.00000002}')
        assert rubric.binding()['qualification']=='REVIEWED_PACK'
        import tutor_attempts as A
        authority=E.HumanAssessmentAuthority(A.AttemptCustody(str(home),project_id='project-reporting',key=b'k'*32))
        exposure={'coverage':'COMPLETE','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
        authority.authorize_assignment('synthetic-assignment','learner-1','tenant-alpha','course-1','variant-1',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
        binding=SimpleNamespace(principal_id='learner-1',tenant_id='tenant-alpha',course_revision='course-1',entitlements=frozenset())
        for name,raw,correct in [('wrong',b'{"total":999999999999.00000002}',False),('right',b'{"total":999999999999.00000001}',True)]:
            attempt={'id':'synthetic-'+name,'assignment_id':'synthetic-assignment','learner_id':'learner-1','tenant_id':'tenant-alpha','variant_revision':'variant-1'}
            authority.begin(attempt,binding);receipt=authority.ingest(attempt['id'],binding,raw)
            authority.submit({'id':'synthetic-submission-'+name,'attempt_id':attempt['id'],'learner_id':'learner-1','tenant_id':'tenant-alpha','artifact_digests':[receipt['artifact_digest']]},binding)
            observed=authority.evaluate('synthetic-submission-'+name,binding)
            assert observed['passing'] is correct and observed['independent_success'] is correct
        load=tutor_sources._load_path
        def changed_at_direct_read(path):
            value=load(path)
            caller=next(frame for frame in inspect.stack()[1:] if not frame.filename.endswith('unittest/mock.py') and not frame.filename.endswith('unittest\\mock.py'))
            if caller.function=='from_pack':
                value=copy.deepcopy(value); value['excerpts'][0]['text']=encoded_wrong
            return value
        with patch.object(tutor_sources,'_load_path',side_effect=changed_at_direct_read):
            require_refused(lambda:E.ReviewedRubric.from_pack(str(home),'reporting-v1',assessment_ref=ref))
        path=Path(tutor_sources._path(str(home),'tenant-alpha','project-reporting','human-final','rev-1'))
        original=path.read_bytes(); changed=json.loads(original)
        changed['excerpts'][0]['text']=encoded_wrong; path.write_text(json.dumps(changed),encoding='utf-8')
        try: require_refused(lambda:rubric.verify_bytes(b'{"total":999999999999.00000001}'))
        finally: path.write_bytes(original)
        assert rubric.verify_bytes(b'{"total":999999999999.00000001}')
    print('[human reviewed reference mechanism] unqualified candidate refuses; owned synthetic-role branch binds exact hidden rubric digest and refuses read-time/source drift; no real subject review or learner qualification occurred')


def check_failure_retry_and_rubric_promotion_refusal():
    import tutor_attempts as A
    import tutor_assessment as E
    with tempfile.TemporaryDirectory(prefix='human-retry-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        custody=A.AttemptCustody(directory,project_id='project-1',key=b'k'*32)
        rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'retry','revision':'r1','operation':'JSON_EQUALS','expected':{'ok':True}})
        original_qualification=rubric._qualification
        rubric._qualification='REVIEWED_PACK'
        require_refused(rubric.binding)
        rubric._qualification=original_qualification
        authority=E.HumanAssessmentAuthority(custody)
        exposure={'coverage':'UNKNOWN','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
        authority.authorize_assignment('assignment-1','learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
        binding=SimpleNamespace(principal_id='learner-1',tenant_id='tenant-1',course_revision='course-1',entitlements=frozenset())
        attempt={'id':'attempt-1','assignment_id':'assignment-1','learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'}
        authority.begin(attempt,binding)
        receipt=authority.ingest('attempt-1',binding,b'{"ok":false}')
        authority.submit({'id':'submission-1','attempt_id':'attempt-1','learner_id':'learner-1','tenant_id':'tenant-1','artifact_digests':[receipt['artifact_digest']]},binding)
        before={p.name:p.read_bytes() for p in Path(directory).rglob('*.blob')}
        with patch('goal.pursue',side_effect=AssertionError('failed grading pursued goal')), \
             patch('fileauth._atomic_write',side_effect=AssertionError('failed grading repaired artifact')), \
             patch.object(rubric,'verify_bytes',side_effect=RuntimeError('owned evaluator failure')):
            try: authority.evaluate('submission-1',binding)
            except RuntimeError as error: assert str(error)=='owned evaluator failure'
            else: raise AssertionError('failed evaluator created a verdict')
        verdict=authority.evaluate('submission-1',binding)
        assert verdict['predicate_correct'] is False and not verdict['independent_success']
        assert before=={p.name:p.read_bytes() for p in Path(directory).rglob('*.blob')}
        exposure['answer_exposed']=True
        require_refused(lambda:authority.evaluate('submission-1',binding))
        require_refused(lambda:E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'bad','revision':'r1','operation':'EXECUTE_STUDENT_CODE','expected':True}))
        require_refused(lambda:E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'big','revision':'r1','operation':'GROUP_SUM','expected':{'rows':[{'group':'A','amount':1e100}]}}))
    print('[human failed evaluator] failure/retry preserves wrong original bytes and no credit; local rubric promotion, changed exposure, unsupported execution and unbounded numerical precision refuse')


def check_known_exposure_cannot_disappear():
    import tutor_attempts as A
    import tutor_assessment as E
    with tempfile.TemporaryDirectory(prefix='human-history-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        authority=E.HumanAssessmentAuthority(A.AttemptCustody(directory,project_id='project-1',key=b'k'*32))
        rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'history','revision':'r1','operation':'JSON_EQUALS','expected':42})
        exposure={'coverage':'COMPLETE','actor':'USER','assistance':'ANSWER','answer_exposed':True,'repeated_example':False,'accommodation_allowed':True}
        authority.authorize_assignment('assignment-1','learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
        binding=SimpleNamespace(principal_id='learner-1',tenant_id='tenant-1',course_revision='course-1',entitlements=frozenset())
        authority.begin({'id':'attempt-1','assignment_id':'assignment-1','learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'},binding)
        exposure.update(assistance='NONE',answer_exposed=False)
        receipt=authority.ingest('attempt-1',binding,b'42')
        authority.submit({'id':'submission-1','attempt_id':'attempt-1','learner_id':'learner-1','tenant_id':'tenant-1','artifact_digests':[receipt['artifact_digest']]},binding)
        verdict=authority.evaluate('submission-1',binding)
        assert verdict['independence']=='ASSISTED' and verdict['exposure']['answer_exposed'], 'later host snapshot erased previously known answer exposure'
        exposure.update(coverage='UNKNOWN',assistance='NONE',answer_exposed=False)
        authority.begin({'id':'attempt-unknown','assignment_id':'assignment-1','learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'},binding)
        exposure['coverage']='COMPLETE'
        receipt=authority.ingest('attempt-unknown',binding,b'42')
        authority.submit({'id':'submission-unknown','attempt_id':'attempt-unknown','learner_id':'learner-1','tenant_id':'tenant-1','artifact_digests':[receipt['artifact_digest']]},binding)
        assert authority.evaluate('submission-unknown',binding)['independence']=='UNKNOWN'
        authority.begin({'id':'attempt-truncated','assignment_id':'assignment-1','learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'},binding)
        receipt=authority.ingest('attempt-truncated',binding,b'42')
        authority.record_exposure('attempt-truncated',binding,{**exposure,'assistance':'ANSWER','answer_exposed':True})
        authority.submit({'id':'submission-truncated','attempt_id':'attempt-truncated','learner_id':'learner-1','tenant_id':'tenant-1','artifact_digests':[receipt['artifact_digest']]},binding)
        scope=dict(tenant_id='tenant-1',project_id='project-1',learner_id='learner-1',course_revision='course-1',variant_revision='variant-1')
        log=authority.custody._path('exposure','attempt-truncated').with_suffix('.jsonl')
        original=log.read_bytes();log.write_bytes(original.splitlines(keepends=True)[0])
        try: require_refused(lambda:authority.evaluate('submission-truncated',binding))
        finally: log.write_bytes(original)
        assert authority.evaluate('submission-truncated',binding)['independence']=='ASSISTED'
    print('[human exposure history] later clean snapshot cannot erase known answer exposure')


def check_current_projection_after_exposure():
    import learning_contracts as L
    import tutor_attempts as A
    import tutor_assessment as E
    with tempfile.TemporaryDirectory(prefix='human-projection-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        custody=A.AttemptCustody(directory,project_id='project-1',key=b'k'*32)
        backend=E.HumanAssessmentAuthority(custody)
        exposure={'coverage':'COMPLETE','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
        rubric=E.ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'projection','revision':'r1','operation':'JSON_EQUALS','expected':42})
        # Exercise the qualified projection branch under an explicit owned role
        # mechanism fixture; never use this seam for production/content proof.
        rubric=E.ReviewedRubric._make(rubric._spec,'REVIEWED_PACK',lambda:None,{})
        entitlements={'learning:read','course:write','assignment:write','session:write','attempt:write','assessment:evaluate'}
        service=L.LearningService(human_assessment=backend)
        binding=service.bind_host('learner-1','tenant-1','policy-1','grant-1','course-1',entitlements)
        api=service.adapter('main_learn',binding)
        course=api.command('course.register',{'title':'Synthetic projection check','course_revision':'course-1'},'course','course')['record']
        assignment=api.command('assignment.create',{'course_id':course['id'],'assignee_id':'learner-1'},'assignment','assignment')['record']
        backend.authorize_assignment(assignment['id'],'learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda:copy.deepcopy(exposure))
        session=api.command('session.open',{'assignment_id':assignment['id']},'session','session')['record']
        attempt=api.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'attempt','attempt')['record']
        receipt=service.ingest_human_artifact(binding,attempt['id'],b'42')
        submission=api.command('attempt.submit',{'attempt_id':attempt['id'],'artifact_digests':[receipt['artifact_digest']]},'submit','submit')['record']
        original=api.command('assessment.evaluate',{'submission_id':submission['id']},'evaluate','evaluate')['record']
        assert original['independent_success'] and original['passing'] is True
        service.record_human_exposure(binding,attempt['id'],{**exposure,'assistance':'ANSWER','answer_exposed':True})
        for surface in sorted(L.SURFACES):
            view=service.adapter(surface,binding)
            rows=view.command('records.list',{'kind':'assessment'})['records']
            assert len(rows)==1 and rows[0]['independent_success'] is False and rows[0]['passing'] is None \
                and rows[0]['state']=='REVIEW_REQUIRED', 'current readback retained stale independent success'
            assert rows[0]['original_judgment']['independent_success'] is True
            attempts=view.command('records.list',{'kind':'attempt'})['records']
            assert attempts[0]['state']=='REVIEW_REQUIRED' and attempts[0]['passing'] is None
            require_refused(lambda:view.command('assessment.evaluate',{'submission_id':submission['id']},'retry','evaluate'))
        assert service._records[original['id']]==original,'original judgment was rewritten instead of projected stale'
        fresh=api.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'unknown-attempt','unknown-attempt')['record']
        receipt=service.ingest_human_artifact(binding,fresh['id'],b'42')
        submitted=api.command('attempt.submit',{'attempt_id':fresh['id'],'artifact_digests':[receipt['artifact_digest']]},'unknown-submit','unknown-submit')['record']
        scored=api.command('assessment.evaluate',{'submission_id':submitted['id']},'unknown-evaluate','unknown-evaluate')['record']
        assert scored['independent_success']
        service.record_human_exposure(binding,fresh['id'],{**exposure,'coverage':'UNKNOWN'})
        files_before={p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}
        for surface in sorted(L.SURFACES):
            view=service.adapter(surface,binding)
            current=next(row for row in view.command('records.list',{'kind':'assessment'})['records'] if row['id']==scored['id'])
            assert current['state']=='REVIEW_REQUIRED' and not current['independent_success'] and current['passing'] is None
            require_refused(lambda:view.command('assessment.evaluate',{'submission_id':submitted['id']},'unknown-retry','unknown-evaluate'))
        assert files_before=={p.relative_to(directory).as_posix():p.read_bytes() for p in Path(directory).rglob('*') if p.is_file()}, 'readback/rejected replay mutated exposure history'
    print('[human current projection] ANSWER and UNKNOWN publication withdraw current credit across four readbacks; original judgment retained, readonly projection and replay refusal; synthetic branch only')


def check_shared_project_directory():
    from tutor_assessment import HumanAssessmentDirectory,HumanAssessmentAuthority,ReviewedRubric
    from tutor_attempts import AttemptCustody,SubmissionRefused
    from learning_contracts import LearningService,ContractError
    with tempfile.TemporaryDirectory(prefix='owned-practice-directory-') as tmp:
        directory=HumanAssessmentDirectory()
        service=LearningService(human_assessment=directory)
        grants={'learning:read','course:write','assignment:write','session:write','attempt:write','assessment:evaluate'}
        binding=service.bind_host('learner-1','tenant-1','policy-1','grant-1','course-1',grants)
        native=service.adapter('native_companion',binding)
        portal=service.adapter('standalone_portal',binding)
        course=native.command('course.register',{'title':'Owned project practice','course_revision':'course-1'},'course','course')['record']
        outcomes=[];authorities=[]
        for project,total in [('project-A',42),('project-B',7)]:
            authority=HumanAssessmentAuthority(AttemptCustody(pathlib.Path(tmp)/project,project_id=project,key=b'k'*32))
            assignment=native.command('assignment.create',{'course_id':course['id'],'assignee_id':'learner-1'},project,project)['record']
            rubric=ReviewedRubric.local_check({'schema':'tutor.human-rubric/1','rubric_id':'rubric-'+project,'revision':'r1','operation':'JSON_EQUALS','expected':{'total':total}})
            exposure={'coverage':'UNKNOWN','actor':'USER','assistance':'NONE','answer_exposed':False,'repeated_example':False,'accommodation_allowed':True}
            authority.authorize_assignment(assignment['id'],'learner-1','tenant-1','course-1','variant-1',rubric,exposure_reader=lambda exposure=exposure:copy.deepcopy(exposure))
            authorities.append((authority,assignment))
            directory.register_assignment(authority,assignment['id'])
            try:directory.register_assignment(authority,assignment['id'])
            except SubmissionRefused:pass
            else:raise AssertionError('directory assignment routing can be replaced')
            session=native.command('session.open',{'assignment_id':assignment['id']},'session-'+project,'session-'+project)['record']
            attempt=native.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'attempt-'+project,'attempt-'+project)['record']
            raw=b'{"total":42}';digest=hashlib.sha256(raw).hexdigest()
            service.ingest_human_artifact(binding,attempt['id'],raw)
            submission=native.command('attempt.submit',{'attempt_id':attempt['id'],'artifact_digests':[digest]},'submit-'+project,'submit-'+project)['record']
            verdict=portal.command('assessment.evaluate',{'submission_id':submission['id']},'grade-'+project,'grade-'+project)['record']
            assert verdict['project_id']==project and verdict['predicate_correct']==(total==42)
            assert verdict['passing'] is None and not verdict['independent_success']
            outcomes.append((attempt,submission))
        other=service.bind_host('other-learner','tenant-1','policy-1','grant-1','course-1',grants)
        foreign=service.adapter('native_companion',other)
        for attempt,submission in outcomes:
            for op in (lambda:service.ingest_human_artifact(other,attempt['id'],b'{}'),lambda:foreign.command('assessment.evaluate',{'submission_id':submission['id']},'foreign','foreign')):
                try:op()
                except (SubmissionRefused,ContractError):pass
                else:raise AssertionError('foreign learner crossed project submission authority')
        require_refused(lambda:directory.register_assignment(object(),'assignment-unknown'))
        require_refused(lambda:directory.register_assignment(authorities[0][0],'assignment-unknown'))
        first,assigned=authorities[0]
        before={p.relative_to(tmp).as_posix():p.read_bytes() for p in Path(tmp).rglob('*.blob')}
        session=native.command('session.open',{'assignment_id':assigned['id']},'scope-session','scope-session')['record']
        for tenant,course_revision in [('tenant-foreign','course-1'),('tenant-1','course-foreign')]:
            foreign_bound=service.bind_host('learner-1',tenant,'policy-1','grant-1',course_revision,grants)
            foreign_api=service.adapter('native_companion',foreign_bound)
            require_refused(lambda:foreign_api.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-1'},'scope-refusal','scope-refusal'))
        require_refused(lambda:native.command('attempt.begin',{'session_id':session['id'],'variant_revision':'variant-foreign'},'variant-refusal','variant-refusal'))
        assert before=={p.relative_to(tmp).as_posix():p.read_bytes() for p in Path(tmp).rglob('*.blob')},'foreign scope wrote submitted bytes'
        assisted={'coverage':'UNKNOWN','actor':'SHARED','assistance':'ANSWER','answer_exposed':True,'repeated_example':False,'accommodation_allowed':True}
        service.record_human_exposure(binding,outcomes[0][0]['id'],assisted)
        assert directory.current_projection(outcomes[0][1]['id'],binding)=='STALE_EXPOSURE'
        assert directory.current_projection(outcomes[1][1]['id'],binding)=='CURRENT','projectA help contaminated projectB exposure'
        before={p.relative_to(tmp).as_posix():p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()}
        other_authority,other_assignment=authorities[1]
        require_refused(lambda:directory.begin({**outcomes[0][0],'assignment_id':other_assignment['id']},binding))
        require_refused(lambda:directory.submit({**outcomes[0][1],'attempt_id':outcomes[1][0]['id']},binding))
        assert before=={p.relative_to(tmp).as_posix():p.read_bytes() for p in Path(tmp).rglob('*') if p.is_file()},'route collision mutated another project custody'
        import threading
        entered=threading.Event();release=threading.Event();failures=[]
        original_begin=other_authority.begin
        retry_attempt={'id':'attempt-directory-retry','assignment_id':other_assignment['id'],'learner_id':'learner-1','tenant_id':'tenant-1','variant_revision':'variant-1'}
        def interrupted_begin(attempt,bound):
            if threading.current_thread().name=='owned-directory-failure':
                entered.set();assert release.wait(2)
                raise SubmissionRefused('owned interrupted start')
            return original_begin(attempt,bound)
        def interrupted():
            try:directory.begin(retry_attempt,binding)
            except SubmissionRefused:failures.append('refused')
        with patch.object(other_authority,'begin',interrupted_begin):
            worker=threading.Thread(target=interrupted,name='owned-directory-failure');worker.start();assert entered.wait(2)
            directory.begin(retry_attempt,binding)
            release.set();worker.join(2);assert not worker.is_alive() and failures==['refused']
        receipt=directory.ingest(retry_attempt['id'],binding,b'{"total":7}')
        assert receipt['artifact_digest']==hashlib.sha256(b'{"total":7}').hexdigest(),'failed concurrent start lost successful retry route'
        print('PASS one shared service, two immutable project custody routes, exact bytes, different outcomes, no false independent credit and foreign learner refusal')


def main():
    check_shared_project_directory()
    check_actual_wrong_and_correct_bytes()
    check_custody_refusals_and_limits()
    check_group_sum_and_exposure()
    check_exact_raw_numeric_and_aggregate_boundaries()
    check_aggregate_boundaries()
    check_shared_service_actual_ingress()
    check_reviewed_hidden_rubric_binding()
    check_failure_retry_and_rubric_promotion_refusal()
    check_known_exposure_cannot_disappear()
    check_current_projection_after_exposure()
    print('PASS test_tutor_human_assessment')


if __name__=='__main__':
    main()
