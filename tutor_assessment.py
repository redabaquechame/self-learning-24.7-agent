"""Closed verification-only human assessment. No pursuit, repair or model calls."""
import copy
from decimal import Decimal, InvalidOperation
import json
import threading

from tutor_attempts import AttemptCustody, SubmissionRefused, canonical, decode_artifact, digest, text, exposure_facts

_RUBRIC = object()
_EXPOSURE_FIELDS = frozenset(('coverage','actor','assistance','answer_exposed','repeated_example','accommodation_allowed'))


def _spec(value):
    if not isinstance(value,dict) or set(value) != {'schema','rubric_id','revision','operation','expected'}:
        raise SubmissionRefused('invalid closed human rubric')
    if value['schema']!='tutor.human-rubric/1' or value['operation'] not in ('JSON_EQUALS','GROUP_SUM'):
        raise SubmissionRefused('rubric evaluator is unavailable')
    text(value['rubric_id']); text(value['revision'])
    result = decode_artifact(canonical(value))
    if value['operation']=='GROUP_SUM': _group_sum(value['expected'])
    return result


def _number(value, *, aggregate=False):
    if isinstance(value,bool) or not isinstance(value,(int,float,Decimal)):
        raise SubmissionRefused('group sum requires finite numeric amounts')
    try: result = Decimal(str(value))
    except InvalidOperation as error: raise SubmissionRefused('invalid numeric amount') from error
    if not result.is_finite(): raise SubmissionRefused('non-finite numeric amount')
    maximum=Decimal('1000000000000000') if aggregate else Decimal('1000000000000')
    if result.copy_abs()>maximum or result.as_tuple().exponent < -8:
        raise SubmissionRefused('numeric amount exceeds mechanical precision bounds')
    return result


def _group_sum(value):
    if not isinstance(value,dict) or set(value) != {'rows'} or not isinstance(value['rows'],list) or not 1<=len(value['rows'])<=1000:
        raise SubmissionRefused('group-sum rubric rows are invalid')
    totals = {}
    for row in value['rows']:
        if not isinstance(row,dict) or set(row)!= {'group','amount'}: raise SubmissionRefused('invalid grouping row')
        group = text(row['group']); amount = _number(row['amount'])
        totals[group] = totals.get(group,Decimal(0)) + amount
    return totals


class ReviewedRubric:
    def __init__(self, *args, **kwargs):
        raise SubmissionRefused('rubrics come from the host review boundary')

    @classmethod
    def _make(cls, spec, qualification, current_check, binding):
        result = object.__new__(cls)
        result._spec = _spec(spec)
        result._digest = digest(canonical(result._spec))
        result._qualification = qualification
        result._check = current_check
        result._binding = copy.deepcopy(binding)
        result._proof = (_RUBRIC,qualification,result._digest,digest(canonical(result._binding)),current_check)
        return result

    @classmethod
    def local_check(cls, spec):
        return cls._make(spec,'LOCAL_ONLY',lambda:None,{})

    @classmethod
    def from_pack(cls, home, pack_id, *, assessment_ref):
        import tutor_packs
        import tutor_sources
        from pathlib import Path
        reference = copy.deepcopy(assessment_ref)
        current = tutor_packs.status(home,pack_id)
        if not current.get('assignable') or current.get('review_scope')!='subject_matter_human':
            raise SubmissionRefused('current independent pack qualification is required')
        pack_digest = current['validation']['digest']
        manifest = tutor_packs._read(str(Path(tutor_packs._pack_dir(home,pack_id))/'assessment_manifest.json'))
        if reference not in manifest['items']:
            raise SubmissionRefused('rubric reference is outside the reviewed final bank')
        def check():
            latest = tutor_packs.status(home,pack_id)
            checked = tutor_sources.verify_assessment_reference(home,reference)
            if not latest.get('assignable') or latest['validation']['digest']!=pack_digest or not checked['ok']:
                raise SubmissionRefused('reviewed pack or hidden rubric changed')
        check()
        source = tutor_sources._load_path(tutor_sources._path(home,reference['tenant_id'],reference['project_id'],
                                                            reference['source_id'],reference['revision']))
        excerpt = next(row for row in source['excerpts'] if row['excerpt_id']==reference['excerpt_id'])
        if digest(excerpt['text'].encode('utf-8'))!=reference['content_sha256']:
            raise SubmissionRefused('hidden rubric bytes changed during loading')
        spec = decode_artifact(excerpt['text'].encode('utf-8'))
        return cls._make(spec,'REVIEWED_PACK',check,{'pack_id':pack_id,'pack_digest':pack_digest,
            'tenant_id':reference['tenant_id'],'project_id':reference['project_id'],'source_digest':reference['content_sha256']})

    def verify_current(self):
        if (self._proof != (_RUBRIC,self._qualification,self._digest,digest(canonical(self._binding)),self._check)
                or digest(canonical(self._spec)) != self._digest):
            raise SubmissionRefused('human rubric identity changed')
        self._check()

    def binding(self):
        self.verify_current()
        return {'rubric_id':self._spec['rubric_id'],'rubric_revision':self._spec['revision'],
            'rubric_digest':self._digest,'qualification':self._qualification,**self._binding}

    def verify_bytes(self, raw):
        self.verify_current()
        value = decode_artifact(raw)
        if self._spec['operation']=='JSON_EQUALS':
            # JSON booleans must not compare equal to numeric student answers.
            return canonical(value)==canonical(self._spec['expected'])
        expected = _group_sum(self._spec['expected'])
        if not isinstance(value,dict) or set(value)!=set(expected): return False
        try: return all(_number(value[group],aggregate=True)==amount for group,amount in expected.items())
        except SubmissionRefused: return False


class HumanAssessmentAuthority:
    def __init__(self,custody):
        if not isinstance(custody,AttemptCustody): raise SubmissionRefused('typed host submission custody is required')
        self.custody = custody
        self._assignments = {}; self._attempts = {}; self._submissions = {}; self._verdicts = {}
        self._gate = threading.RLock()

    def authorize_assignment(self,assignment_id,learner_id,tenant_id,course_revision,variant_revision,rubric,*,exposure_reader):
        if not isinstance(rubric,ReviewedRubric) or not callable(exposure_reader):
            raise SubmissionRefused('host rubric and exposure reader are required')
        with self._gate:
            scope = {'tenant_id':text(tenant_id),'project_id':self.custody.project_id,'learner_id':text(learner_id),
                     'course_revision':text(course_revision),'variant_revision':text(variant_revision)}
            current = rubric.binding()
            if current.get('tenant_id',tenant_id)!=tenant_id or current.get('project_id',self.custody.project_id)!=self.custody.project_id:
                raise SubmissionRefused('reviewed rubric is outside assignment scope')
            key = text(assignment_id)
            if key in self._assignments: raise SubmissionRefused('assignment authority is immutable')
            self._assignments[key] = (scope,rubric,exposure_reader)

    def _owns(self,scope,binding,*,evaluate=False,read=False):
        if scope['tenant_id']!=binding.tenant_id or scope['course_revision']!=binding.course_revision:
            raise SubmissionRefused('foreign tenant or course revision')
        if scope['learner_id']!=binding.principal_id and not ((evaluate and 'assessment:evaluate:any' in binding.entitlements)
                or (read and 'learning:read:any' in binding.entitlements)):
            raise SubmissionRefused('foreign learner submission')

    def assignment_scope(self, assignment_id, binding):
        with self._gate:
            value = self._assignments.get(text(assignment_id))
            if value is None:
                raise SubmissionRefused('host assignment is unavailable')
            scope, rubric, _ = value
            self._owns(scope, binding)
            rubric.verify_current()
            return copy.deepcopy(scope)

    def begin(self,attempt,binding):
        with self._gate:
            assigned = self._assignments.get(attempt.get('assignment_id'))
            if assigned is None: raise SubmissionRefused('host-assigned human rubric is unavailable')
            scope,rubric,reader = assigned
            self._owns(scope,binding)
            if attempt.get('learner_id')!=scope['learner_id'] or attempt.get('tenant_id')!=scope['tenant_id'] or attempt.get('variant_revision')!=scope['variant_revision']:
                raise SubmissionRefused('attempt differs from authorized variant')
            initial = self._exposure(reader)
            body = self.custody.begin(attempt['id'],scope,rubric.binding(),initial_exposure=initial)
            self.custody.record_exposure(attempt['id'],scope,initial)
            prior = self._attempts.get(attempt['id'])
            if prior and prior[0]!=scope: raise SubmissionRefused('attempt scope conflict')
            self._attempts[attempt['id']] = (copy.deepcopy(scope),rubric,reader)
            return body

    def _attempt(self,attempt_id,binding):
        value = self._attempts.get(attempt_id)
        if value is None: raise SubmissionRefused('human attempt is unavailable')
        self._owns(value[0],binding)
        value[1].verify_current()
        return value

    def ingest(self,attempt_id,binding,raw):
        with self._gate:
            scope,_,reader = self._attempt(attempt_id,binding)
            if any(row[0]==attempt_id for row in self._submissions.values()):
                raise SubmissionRefused('submitted attempt cannot ingest later work')
            self.custody.record_exposure(attempt_id,scope,self._exposure(reader))
            return self.custody.ingest(attempt_id,scope,raw)

    def submit(self,submission,binding):
        with self._gate:
            scope,rubric,reader = self._attempt(submission['attempt_id'],binding)
            if submission.get('learner_id')!=scope['learner_id'] or submission.get('tenant_id')!=scope['tenant_id']:
                raise SubmissionRefused('submission identity differs from attempt')
            self.custody.record_exposure(submission['attempt_id'],scope,self._exposure(reader))
            body = self.custody.submit(submission['id'],submission['attempt_id'],scope,submission['artifact_digests'])
            self._submissions[submission['id']] = (submission['attempt_id'],copy.deepcopy(scope),rubric,reader)
            return body

    def validate_submission(self,submission_id,binding,*,read=False):
        value = self._submissions.get(submission_id)
        if value is None: raise SubmissionRefused('human submission is unavailable')
        attempt_id,scope,rubric,reader = value
        self._owns(scope,binding,evaluate=True,read=read)
        rubric.verify_current()
        metadata,blobs = self.custody.read_submission(submission_id,scope)
        if metadata['rubric_binding']!=rubric.binding(): raise SubmissionRefused('submission rubric changed')
        return metadata,blobs,reader,rubric

    @staticmethod
    def _exposure(reader):
        return exposure_facts(reader())

    def record_exposure(self,attempt_id,binding,facts):
        with self._gate:
            scope,_,_ = self._attempt(attempt_id,binding)
            return self.custody.record_exposure(attempt_id,scope,facts)

    @staticmethod
    def _merge_exposure(records):
        if not records: raise SubmissionRefused('host exposure history is unavailable')
        facts=[row['body']['facts'] for row in records]
        levels=('NONE','ACCOMMODATION','HINT','ANSWER','EXECUTION')
        return {'coverage':'UNKNOWN' if any(row['coverage']=='UNKNOWN' for row in facts) else 'COMPLETE',
            'actor':'AGENT' if any(row['actor']=='AGENT' for row in facts) else 'SHARED' if any(row['actor']=='SHARED' for row in facts) else 'USER',
            'assistance':max((row['assistance'] for row in facts),key=levels.index),
            'answer_exposed':any(row['answer_exposed'] for row in facts),
            'repeated_example':any(row['repeated_example'] for row in facts),
            'accommodation_allowed':not any(row['assistance']=='ACCOMMODATION' and not row['accommodation_allowed'] for row in facts)}

    def current_projection(self,submission_id,binding):
        """Read-only current status; original verdict remains immutable history."""
        with self._gate:
            try:
                metadata,_,reader,_=self.validate_submission(submission_id,binding,read=True)
                records=self.custody.read_exposure(metadata['attempt_id'],metadata['scope'])
                current=self._merge_exposure([*records,{'body':{'facts':self._exposure(reader)}}])
                original=self._verdicts.get(submission_id)
                if original is None: return 'UNAVAILABLE'
                return 'CURRENT' if original['exposure']==current else 'STALE_EXPOSURE'
            except (SubmissionRefused,OSError,RuntimeError):
                return 'UNAVAILABLE'

    def project_for_submission(self,submission_id,binding):
        with self._gate:
            value=self._submissions.get(submission_id)
            if value is None:raise SubmissionRefused('human submission is unavailable')
            self._owns(value[1],binding,evaluate=True)
            return value[1]['project_id']

    def evaluate(self,submission_id,binding):
        with self._gate:
            metadata,blobs,reader,rubric = self.validate_submission(submission_id,binding)
            records=self.custody.record_exposure(metadata['attempt_id'],metadata['scope'],self._exposure(reader))
            exposure = self._merge_exposure(records)
            if len(blobs)!=1: raise SubmissionRefused('this mechanical evaluator requires one JSON artifact')
            prior = self._verdicts.get(submission_id)
            if prior:
                if prior['exposure']!=exposure: raise SubmissionRefused('exposure changed; original verdict needs explicit correction')
                return copy.deepcopy(prior)
            observed = rubric.verify_bytes(blobs[0])
            unknown = exposure['coverage']=='UNKNOWN'
            assisted = (exposure['actor']!='USER' or exposure['answer_exposed'] or exposure['repeated_example']
                        or exposure['assistance'] in ('HINT','ANSWER','EXECUTION')
                        or exposure['assistance']=='ACCOMMODATION' and not exposure['accommodation_allowed'])
            independence = 'UNKNOWN' if unknown else 'ASSISTED' if assisted else 'ELIGIBLE_UNDER_RECORDED_CONDITIONS'
            qualified = rubric.binding()['qualification']=='REVIEWED_PACK'
            verdict = {'schema':'tutor.human-verdict/1','submission_id':submission_id,
                'attempt_id':metadata['attempt_id'],'artifact_digests':metadata['artifact_digests'],
                'rubric_digest':rubric.binding()['rubric_digest'],'predicate_correct':observed,
                'passing':observed if qualified else None,'qualification':rubric.binding()['qualification'],
                'independence':independence,'independent_success':bool(observed and qualified and not unknown and not assisted),
                'exposure':exposure,'state':'SCORED' if qualified else 'REVIEW_REQUIRED',
                'verdict_id':'ver-'+digest(canonical([submission_id,metadata['artifact_digests'],rubric.binding(),exposure]))[:24]}
            self._verdicts[submission_id]=copy.deepcopy(verdict)
            return verdict


class HumanAssessmentDirectory:
    """Host-only immutable routing to project custodians in one learning engine."""
    def __init__(self):
        self._gate = threading.RLock()
        self._assignments = {}; self._attempts = {}; self._submissions = {}

    def register_assignment(self, authority, assignment_id):
        if not isinstance(authority, HumanAssessmentAuthority):
            raise SubmissionRefused('typed project assessment authority is required')
        assignment_id = text(assignment_id)
        with authority._gate:
            assigned = authority._assignments.get(assignment_id)
            if assigned is None:
                raise SubmissionRefused('host assignment is unavailable')
            assigned[1].verify_current()
        with self._gate:
            if assignment_id in self._assignments:
                raise SubmissionRefused('assignment routing is immutable')
            self._assignments[assignment_id] = authority

    def _route(self, records, identifier):
        identifier = text(identifier)
        with self._gate:
            authority = records.get(identifier)
        if authority is None:
            raise SubmissionRefused('host human assessment route is unavailable')
        return authority

    def _bind(self, records, identifier, authority, operation):
        identifier = text(identifier)
        with self._gate:
            prior = records.get(identifier)
            if prior is not None and prior is not authority:
                raise SubmissionRefused('human record crossed project authority')
            if prior is None:
                records[identifier] = authority
        # A failed operation grants nothing: the backend still requires its
        # committed attempt/submission. Keep the namespace reservation so a
        # concurrent successful retry cannot lose its route, and another
        # project cannot take over the immutable identifier after failure.
        return operation()

    def assignment_scope(self, assignment_id, binding):
        return self._route(self._assignments, assignment_id).assignment_scope(assignment_id, binding)

    def begin(self, attempt, binding):
        authority = self._route(self._assignments, attempt.get('assignment_id'))
        return self._bind(self._attempts, attempt['id'], authority,
            lambda: authority.begin(attempt, binding))

    def ingest(self, attempt_id, binding, raw):
        return self._route(self._attempts, attempt_id).ingest(attempt_id, binding, raw)

    def submit(self, submission, binding):
        authority = self._route(self._attempts, submission['attempt_id'])
        return self._bind(self._submissions, submission['id'], authority,
            lambda: authority.submit(submission, binding))

    def evaluate(self, submission_id, binding):
        return self._route(self._submissions, submission_id).evaluate(submission_id, binding)

    def project_for_submission(self, submission_id, binding):
        return self._route(self._submissions, submission_id).project_for_submission(submission_id, binding)

    def record_exposure(self, attempt_id, binding, facts):
        return self._route(self._attempts, attempt_id).record_exposure(attempt_id, binding, facts)

    def current_projection(self, submission_id, binding):
        try:
            return self._route(self._submissions, submission_id).current_projection(submission_id, binding)
        except SubmissionRefused:
            return 'UNAVAILABLE'
