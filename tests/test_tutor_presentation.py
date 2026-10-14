"""Draft of the next package's source-bound presentation witness; no live IO."""
import copy
import json
import sys
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch
from common import AGENT_DIR
sys.path.insert(0, AGENT_DIR)
from test_tutor_canvas import scene
from test_tutor_host import fixture
from tutor_presentation import TeachingScene, PresentationRefused


def refused(call):
    try:
        call()
    except PresentationRefused:
        return
    raise AssertionError('unavailable or foreign presentation was admitted')


def main():
    _, request, observation, _, owner = fixture()
    request['learning_intent'] = 'LEARN'
    request['output_preferences']['response_format'] = 'TEXT_AND_SCENE'
    teaching = TeachingScene.local_check(scene(), tenant_id='tenant-1', project_id='project-1')
    before = copy.deepcopy((request, observation, owner))
    value = teaching.render(request, observation, owner)
    assert value['schema'] == 'fleet.tutor.presentation.v1'
    assert value['qualification'] == 'LOCAL_ONLY'
    assert value['learning_success_claimed'] is False
    assert value['render_model']['schema'] == 'tutor.canvas-render/1'
    assert value['render_model']['executable_content'] is False
    assert value['render_model']['text_alternative'] == scene()['text_alternative']
    for field in ('observation_id', 'source_id', 'source_revision', 'capture_epoch', 'geometry_revision', 'content_sha256'):
        assert value['binding'][field] == observation[field]
    assert value['binding']['request_id'] == request['request_id']
    assert owner['now_monotonic_ms'] < value['expires_at_monotonic_ms'] <= min(request['deadline_monotonic_ms'], observation['expires_at_monotonic_ms'])
    assert (request, observation, owner) == before
    for key, changed in [('tenant_id', 'foreign'), ('project_id', 'foreign'), ('user_id', 'foreign'), ('consent_revision', 'foreign')]:
        bad = {**request, key: changed}
        refused(lambda: teaching.render(bad, observation, owner))
    for key, changed in [('source_revision', 'foreign'), ('capture_epoch', 999), ('geometry_revision', 'foreign')]:
        changed_observation = {**observation, key: changed}
        # Observation references must remain admitted by the current owner and
        # exact source binding; not a caller-chosen coordinate or revision.
        if key != 'geometry_revision':
            refused(lambda: teaching.render(request, changed_observation, owner))
    expired = {**owner, 'now_monotonic_ms': observation['expires_at_monotonic_ms']}
    refused(lambda: teaching.render(request, observation, expired))
    refused(lambda: teaching.render({**request, 'mode': 'DELEGATE'}, observation, owner))
    refused(lambda: teaching.render({**request, 'learning_intent': 'ASSESS'}, observation, owner))
    refused(lambda: TeachingScene(scene()))
    bad_scene = scene(); bad_scene['executable_content'] = True
    refused(lambda: TeachingScene.local_check(bad_scene, tenant_id='tenant-1', project_id='project-1'))
    for name, changed in [('_qualification','REVIEWED_PACK'),('_scope',{'tenant_id':'tenant-1','project_id':'foreign'})]:
        original = getattr(teaching,name); setattr(teaching,name,changed)
        refused(lambda: teaching.render(request,observation,owner))
        setattr(teaching,name,original)
    teaching._scene['title'] = 'mutated title'
    refused(lambda: teaching.render(request,observation,owner))
    check_reviewed_reference()
    check_presentation_wire()
    check_shared_signed_boundaries()
    check_host_presentation()
    print('PASS test_tutor_presentation: closed scene, exact source scope, expiry, immutable qualification and actual reviewed-reference mechanism')


def check_reviewed_reference():
    import tutor_packs
    import tutor_sources
    from test_tutor_sources import source_record
    from test_tutor_packs import seed,authorize_reviewer,CHECKLIST,REVIEWER
    with tempfile.TemporaryDirectory(prefix='teaching-presentation-',dir=os.environ.get('AGENT_TEST_TMP')) as directory:
        home=Path(directory)/'home'; home.mkdir(); seed(str(home))
        raw=json.dumps(scene(),sort_keys=True)
        record=source_record(source_id='canvas-teaching',excerpt_id='closed-scene',text=raw,source_type='fixture')
        tutor_sources.register_source(str(home),record)
        ref={'source_id':'canvas-teaching','revision':'rev-1','excerpt_id':'closed-scene','tenant_id':'tenant-alpha','project_id':'project-reporting'}
        stage=Path(directory)/'stage'; shutil.copytree(Path(AGENT_DIR)/'teaching_packs/reporting-v1',stage)
        manifest=json.loads((stage/'sources.json').read_text(encoding='utf-8'))
        manifest['references'].append(ref)
        (stage/'sources.json').write_text(json.dumps(manifest),encoding='utf-8')
        tutor_packs.install_candidate(str(home),str(stage))
        refused(lambda:TeachingScene.from_pack(str(home),'reporting-v1',reference=ref))
        authorize_reviewer(str(home))
        tutor_packs.review_pack(str(home),'reporting-v1',reviewer_id=REVIEWER,reviewer_kind='subject_matter_human',checklist=CHECKLIST)
        tutor_packs.qualify_pack(str(home),'reporting-v1',reviewer_id=REVIEWER,evidence_ref='SYNTHETIC-ROLE-FIXTURE-ONLY-NO-REAL-SUBJECT-REVIEW')
        installed=TeachingScene.from_pack(str(home),'reporting-v1',reference=ref)
        assert installed._qualification=='REVIEWED_PACK'
        installed.verify_current()
        hidden={'source_id':'reporting-final','revision':'rev-1','excerpt_id':'final-solution','tenant_id':'tenant-alpha','project_id':'project-reporting'}
        refused(lambda:TeachingScene.from_pack(str(home),'reporting-v1',reference=hidden))
        refused(lambda:TeachingScene.from_pack(str(home),'reporting-v1',reference={**ref,'project_id':'foreign'}))
        changed=scene(); changed['title']='changed excerpt bytes'
        with patch('tutor_sources.read_excerpt',return_value=json.dumps(changed)):
            refused(lambda:TeachingScene.from_pack(str(home),'reporting-v1',reference=ref))
        from test_tutor_host import review_host
        published_host,_,_=review_host()
        _,req,obs,_,authority=fixture()
        req['learning_intent']='LEARN'; req['output_preferences']['response_format']='TEXT_AND_SCENE'
        receipt=TeachingScene.local_check(scene(),tenant_id='tenant-1',project_id='project-1').render(req,obs,authority)
        def still_reviewed():
            installed.verify_current()
            return True
        published_host._publish_presentation(receipt,still_reviewed)
        assert published_host.supervise_presentation() is None
        with patch('tutor_packs.status',return_value={'assignable':False}):
            refused(installed.verify_current)
            assert published_host.supervise_presentation()['binding']==receipt['binding']
        published_host._publish_presentation(receipt,still_reviewed)
        source_path=Path(tutor_sources._path(str(home),'tenant-alpha','project-reporting','canvas-teaching','rev-1'))
        disk=json.loads(source_path.read_text(encoding='utf-8')); disk['excerpts'][0]['text']=json.dumps(changed)
        source_path.write_text(json.dumps(disk),encoding='utf-8')
        refused(installed.verify_current)
        assert published_host.supervise_presentation()['binding']==receipt['binding']
        published_host.stop()
    print('[reviewed scene mechanism] candidate/hidden/foreign/read-time mismatch/revocation/source drift refuse; synthetic reviewer role only, no qualified human content')


def check_presentation_wire():
    import tutor_transport as wire
    _,request,observation,instruction,owner=fixture()
    request['learning_intent']='LEARN'; request['output_preferences']['response_format']='TEXT_AND_SCENE'
    value=TeachingScene.local_check(scene(),tenant_id='tenant-1',project_id='project-1').render(request,observation,owner)
    message={'schema':'fleet.tutor.bridge.v1','protocol_version':'1.1','session_id':'bridge-session',
        'bridge_epoch':1,'sequence':1,'message_id':'answer-1','reply_to':'question-1','deadline_monotonic_ms':8000,
        'cancellation_generation':0,'message_type':'ANSWER','body':{'instruction':instruction,'presentation':value}}
    key=bytes(range(32)); original=copy.deepcopy(message)
    raw=wire.encode_message(key,message)
    expected={'session_id':'bridge-session','bridge_epoch':1,'sequence':1,'cancellation_generation':0}
    got=wire.decode_message(key,raw,expected,2000)
    assert got['body']==message['body'] and message==original
    for changed in [{'qualification':'invented'},{'learning_success_claimed':True},
                    {'expires_at_monotonic_ms':8001},{'input_privileges':['click']}]:
        bad=copy.deepcopy(message); bad['body']['presentation'].update(changed)
        try:wire.encode_message(key,bad)
        except wire.TransportRefusal:pass
        else:raise AssertionError('invalid presentation wire was admitted')
    bad=copy.deepcopy(message); bad['body']['presentation']['binding']['request_id']='foreign-question'
    try:wire.encode_message(key,bad)
    except wire.TransportRefusal:pass
    else:raise AssertionError('foreign presentation request was admitted')
    signed=json.loads(raw); signed['body']['presentation']['qualification']='REVIEWED_PACK'
    modified=json.dumps({k:v for k,v in signed.items() if k!='mac'},sort_keys=True,separators=(',',':')).encode()[:-1]+b',"mac":"'+signed['mac'].encode()+b'"}'
    try:wire.decode_message(key,modified,expected,2000)
    except wire.TransportRefusal:pass
    else:raise AssertionError('changed authenticated presentation was admitted')
    print('[presentation wire] optional closed authenticated answer, expiry/request/qualification/no-input negatives; existing plain answer shape retained')


def check_shared_signed_boundaries():
    import tutor_transport as wire
    cases=json.loads((Path(AGENT_DIR)/'tests/fixtures/tutor_presentation_review_boundaries_v1.json').read_text(encoding='utf-8'))
    expected={'session_id':'bridge-session','bridge_epoch':1,'sequence':1,'cancellation_generation':0}
    for case in cases:
        try:
            wire.decode_message(bytes(range(32)),case['wire'].encode(),expected,2000)
            accepted=True
        except ValueError:
            accepted=False
        assert accepted is case['allowed'],case['name']
    print('[shared signed boundaries] Unicode/depth positive limits, outside limits, slider contradiction and scoped retirement validated')


def check_host_presentation():
    from tutor_host import NativeTutorHost
    from tutor_service import TutorService
    from learning_contracts import LearningService
    session,request,observation,instruction,owner=fixture()
    instruction['annotations']=[]
    learning=LearningService()
    binding=learning.bind_host('user-1','tenant-1','policy-1','grant-1','course-1',
        ['learning:read','session:write'],['capture.selected'])
    teaching=TeachingScene.local_check(scene(),tenant_id='tenant-1',project_id='project-1')
    calls=[]
    def dispatch(req,obs):
        calls.append(copy.deepcopy(req)); return {**instruction,'request_id':req['request_id']}
    host=NativeTutorHost(TutorService(enabled=True,dispatch=dispatch),lambda:copy.deepcopy(owner),
        learning.adapter('native_companion',binding),presentation=teaching)
    host._session=session; host._observations[observation['observation_id']]=copy.deepcopy(observation)
    body={'request_id':'teaching-question','observation_id':observation['observation_id'],
        'question':'Teach this concept','learning_intent':'LEARN','locale':'en-CA'}
    checks=[]
    value=host.ask_observed(body,deadline_ms=8000,_release_checks=checks)
    assert value['allowed'] and value['presentation']['binding']['request_id']=='teaching-question'
    assert value['presentation']['qualification']=='LOCAL_ONLY' and all(check() for check in checks)
    assert calls[-1]['output_preferences']['response_format']=='TEXT_AND_SCENE'
    host._publish_presentation(value['presentation'], checks[-1])
    assert host.supervise_presentation() is None
    teaching._scene['title']='content replaced before reply'
    retired=host.supervise_presentation()
    assert retired['binding']==value['presentation']['binding']
    assert host.supervise_presentation() is None, 'retirement repeated'
    assert not all(check() for check in checks), 'changed teaching authority released its delayed scene'
    plain=host.ask_observed({**body,'request_id':'plain-question','learning_intent':'UNDERSTAND'},deadline_ms=8000)
    assert plain['allowed'] and 'presentation' not in plain
    host.stop()
    print('[host teaching] optional typed scene, actual release checks and plain-answer compatibility; no provider called')


if __name__ == '__main__':
    main()
