"""Host-assigned human artifact workflow over the shared learning service.

No generated artifact, task selection, grading rule or independent-credit claim
is accepted from the learner interface. Transport is a separate boundary.
"""
import copy
import secrets
import threading

from learning_contracts import LearningAdapter, ContractError, Conflict
from tutor_assessment import HumanAssessmentAuthority, HumanAssessmentDirectory


class HostPractice:
    def __init__(self, adapter, *, assignment_id, variant_revision, project_id, current_check):
        if (not isinstance(adapter, LearningAdapter) or adapter._surface != 'native_companion'
                or not callable(current_check)):
            raise ContractError('sealed native practice binding required')
        backend = adapter._service._human_assessment
        if not isinstance(backend, (HumanAssessmentAuthority, HumanAssessmentDirectory)):
            raise ContractError('human practice is unavailable')
        current_check()
        adapter.command('learning.capabilities')
        scope = backend.assignment_scope(assignment_id, adapter._binding)
        if scope['project_id'] != project_id or scope['variant_revision'] != variant_revision:
            raise ContractError('practice differs from exact host assignment')
        self._adapter = adapter
        self._binding = adapter._binding
        self._backend = backend
        self._scope = scope
        self._assignment = assignment_id
        self._variant = variant_revision
        self._current_check = current_check
        self._gate = threading.RLock()
        self._attempt = None
        self._digests = []
        self._submission = None
        self._assessment = None
        self._cancelled = False
        self._retired = threading.Event()

    def _current(self):
        if self._retired.is_set():
            raise ContractError('native practice lifetime retired')
        self._current_check()
        if self._adapter._binding != self._binding or self._adapter._service._human_assessment is not self._backend:
            raise ContractError('practice binding changed')
        self._adapter.command('learning.capabilities')
        if self._backend.assignment_scope(self._assignment, self._binding) != self._scope:
            raise ContractError('practice assignment changed')

    def retire(self):
        """Urgent local lifetime retirement, without waiting for custody IO."""
        self._retired.set()

    def wire_command(self, body):
        import base64
        # This host boundary also checks shape for in-process callers. Native
        # authentication and ordered protocol validation precede dispatch.
        from tutor_transport import _shape
        _shape({'schema':'fleet.tutor.bridge.v1','protocol_version':'1.2',
            'session_id':'practice-shape','bridge_epoch':1,'sequence':1,
            'message_id':'practice-shape','reply_to':None,'deadline_monotonic_ms':1,
            'cancellation_generation':0,'message_type':'PRACTICE_REQUEST','body':body})
        with self._gate:
            operation=body['operation']
            if operation=='START': self.start()
            elif operation=='UPLOAD': self.upload(base64.b64decode(body['payload']['artifact_base64'],validate=True))
            elif operation=='SUBMIT': self.submit()
            elif operation=='CANCEL': self.cancel()
            return self.wire_status()

    def wire_status(self):
        status=self.status();assessment=status['assessment']
        return {'schema':'fleet.tutor.practice-result.v1','state':status['state'],
            'attempt_id':status['attempt_id'],'artifact_count':status['artifact_count'],
            'predicate_correct':assessment['predicate_correct'] if assessment else None,
            'passing':assessment['passing'] if assessment else None,
            'independent_success':assessment['independent_success'] if assessment else False,
            'projection_status':assessment['projection_status'] if assessment else 'UNASSESSED',
            'qualification':assessment['qualification'] if assessment else 'UNASSESSED'}

    def _command(self, operation, payload, key):
        return self._adapter.command(operation, payload, key, key)['record']

    def start(self):
        with self._gate:
            self._current()
            if self._attempt is not None and self._submission is None and not self._cancelled:
                raise Conflict('finish or cancel the current practice attempt first')
            key = 'practice-' + secrets.token_hex(16)
            session = self._command('session.open', {'assignment_id': self._assignment}, key + '-session')
            attempt = self._command('attempt.begin', {'session_id': session['id'], 'variant_revision': self._variant}, key + '-attempt')
            self._attempt = attempt['id']
            self._digests = []
            self._submission = None
            self._assessment = None
            self._cancelled = False
            return self.status()

    def _active(self):
        self._current()
        if self._attempt is None or self._cancelled or self._submission is not None:
            raise Conflict('an active human practice attempt is required')

    def upload(self, raw):
        with self._gate:
            self._active()
            receipt = self._adapter._service.ingest_human_artifact(self._binding, self._attempt, raw)
            digest = receipt['artifact_digest']
            if digest not in self._digests:
                self._digests.append(digest)
            return copy.deepcopy(receipt)

    def submit(self):
        with self._gate:
            self._current()
            if self._cancelled or self._attempt is None:
                raise Conflict('practice attempt is unavailable')
            if self._submission is None:
                # The currently installed evaluator accepts exactly one JSON
                # artifact. Refuse before sealing a non-evaluable submission.
                if len(self._digests) != 1:
                    raise Conflict('select exactly one JSON artifact before submitting')
                self._submission = self._command('attempt.submit', {'attempt_id': self._attempt,
                    'artifact_digests': list(self._digests)}, self._attempt + '-submit')
            if self._assessment is None:
                self._assessment = self._command('assessment.evaluate', {'submission_id': self._submission['id']}, self._attempt + '-evaluate')
            return self.status()['assessment']

    def help_token(self):
        with self._gate:
            self._current()
            return self._attempt

    def record_help(self, token, *, answer_exposed):
        with self._gate:
            self._current()
            if token is None:
                return
            if type(answer_exposed) is not bool:
                raise ContractError('help exposure must be explicit')
            # Use the dispatch-time attempt, even if a new attempt started.
            # The shared service validates ownership and retains old history.
            self._adapter._service.record_human_exposure(self._binding, token, {
                'coverage': 'UNKNOWN', 'actor': 'USER', 'assistance': 'ANSWER' if answer_exposed else 'HINT',
                'answer_exposed': answer_exposed, 'repeated_example': False, 'accommodation_allowed': True})

    def cancel(self):
        with self._gate:
            self._active()
            self._command('request.cancel', {'target_id': self._attempt, 'reason': 'Learner cancelled native practice'}, self._attempt + '-cancel')
            self._cancelled = True

    def status(self):
        with self._gate:
            self._current()
            assessment = None
            if self._assessment is not None:
                # Read the shared current projection, rather than re-publishing
                # a cached judgment after later assistance or changed exposure.
                cursor = None
                while True:
                    payload = {'kind': 'assessment', 'limit': 100}
                    if cursor: payload['cursor'] = cursor
                    page = self._adapter.command('records.list', payload)
                    assessment = next((x for x in page['records'] if x['id'] == self._assessment['id']), None)
                    if assessment is not None or page['next_cursor'] is None: break
                    cursor = page['next_cursor']
            return {'assignment_id': self._assignment, 'variant_revision': self._variant,
                'attempt_id': self._attempt, 'artifact_count': len(self._digests),
                'state': 'CANCELLED' if self._cancelled else 'SUBMITTED' if self._submission else 'ACTIVE' if self._attempt else 'ASSIGNED',
                'assessment': assessment}
