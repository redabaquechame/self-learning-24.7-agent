#!/usr/bin/env python3
"""Optional native adapter over existing host authority and learning.v1.

No process, native API, capture or model call occurs at import. The host supplies
the sealed learning adapter, current policy reader and qualified dispatch. Native
transport and presentation are separate; this adapter cannot mint a grant.
"""
import copy
import threading
from collections import deque, OrderedDict

import learning_contracts
import tutor_contracts as contracts
from tutor_service import TutorService, TutorUnavailable
from tutor_session import TutorSession, SelectedSource


class NativeTutorHost:
    MAX_AUTHORIZATION_MS = 15 * 60 * 1000
    MAX_FRAME_ADMISSION_AGE_MS = 2000
    MAX_TEXT_SNAPSHOT_MS = 15000
    RECEIPT_FIELDS = ("source_id", "display_name", "source_kind", "source_revision",
                      "native_handle_digest", "width", "height", "capture_epoch")

    def __init__(self, service, current_owner_state, learning_adapter, *, presentation=None, source_authority=None):
        if not isinstance(service, TutorService) or not service.enabled:
            raise TutorUnavailable("screen tutor host service is unavailable")
        if not callable(current_owner_state):
            raise TutorUnavailable("current host policy reader is required")
        if (not isinstance(learning_adapter, learning_contracts.LearningAdapter)
                or learning_adapter._surface != "native_companion"):
            raise TutorUnavailable("sealed native learning adapter is required")
        try:
            learning_adapter.command("learning.capabilities")
        except learning_contracts.ContractError as error:
            raise TutorUnavailable("native learning binding is unavailable") from error
        binding = learning_adapter._binding
        if "capture.selected" not in binding.local_capabilities:
            raise TutorUnavailable("selected native capture capability is unavailable")
        self._identity = {"user_id": binding.principal_id, "tenant_id": binding.tenant_id}
        self._binding = binding
        self._learning_service = learning_adapter._service
        self._service = service
        self._image_route = None
        self._image_release_checks = OrderedDict()
        self._reader = current_owner_state
        if source_authority is not None:
            from tutor_authority import SourceApprovalAuthority
            if (not isinstance(source_authority, SourceApprovalAuthority)
                    or getattr(current_owner_state, '__self__', None) is not source_authority
                    or getattr(current_owner_state, '__func__', None) is not SourceApprovalAuthority.owner_state):
                raise TutorUnavailable('typed source authority requires its exact current owner reader')
        self._source_authority = source_authority
        self._pending_source = None
        self._learning = learning_adapter
        if presentation is not None:
            from tutor_presentation import TeachingScene
            if not isinstance(presentation, TeachingScene):
                raise TutorUnavailable('teaching presentation requires a typed host installation')
            presentation.verify_current()
        self._presentation = presentation
        self._practice = None
        self._published_presentation = None
        self._project = None
        self._session = None
        from tutor_gateway import EphemeralImageStore
        self._images = EphemeralImageStore()
        self._frame_reader = None
        self._capture_authorization = None
        self._observations = OrderedDict()
        self._question_ids = deque(maxlen=128)
        self._connection = None
        self._launch_stop = None
        self._selection_generation = 0
        self._running = False
        self._workers = set()
        self._gate = threading.RLock()
        self._retired = deque(maxlen=128)
        initial = self._current()
        contracts._ident(initial.get("project_id"), "project_id")
        self._project = initial["project_id"]
        if source_authority is not None and source_authority.identity != {**self._identity, 'project_id': self._project}:
            raise TutorUnavailable('source authority belongs to another host scope')

    def install_practice(self, *, assignment_id, variant_revision):
        """Trusted host configuration; no wire-selected task or project."""
        from tutor_human_practice import HostPractice
        with self._gate:
            if (self._practice is not None or self._connection is not None
                    or self._launch_stop is not None or self._session is not None or self._workers):
                raise TutorUnavailable('practice must be installed before native work')
            self._practice = HostPractice(self._learning,assignment_id=assignment_id,
                variant_revision=variant_revision,project_id=self._project,current_check=self._current)

    def install_source_authority(self, authority):
        """Trusted Fleet binding, once before any native connection or work."""
        from tutor_authority import SourceApprovalAuthority
        if not isinstance(authority, SourceApprovalAuthority):
            raise TutorUnavailable('typed existing-approval source authority required')
        with self._gate:
            if (self._source_authority is not None or self._connection is not None
                    or self._launch_stop is not None or self._session is not None
                    or self._pending_source is not None or self._running or self._workers):
                raise TutorUnavailable('source authority must be installed before native work')
            self._current()
            if authority.identity != {**self._identity, 'project_id': self._project}:
                raise TutorUnavailable('source authority belongs to another host scope')
            self._source_authority = authority
            self._reader = authority.owner_state

    def install_image_provider(self, route):
        """Trusted host configuration only, before any connected source/session."""
        from tutor_dispatch import ImageProviderRoute
        if not isinstance(route, ImageProviderRoute):
            raise TutorUnavailable('typed host image-provider route required')
        with self._gate:
            if (self._image_route is not None or self._service.dispatch is not None
                    or self._connection is not None or self._launch_stop is not None
                    or self._session is not None or self._running or self._workers):
                raise TutorUnavailable('image provider must be installed before native work starts')
            self._current()
            self._image_route = route
            self._service.dispatch = self._dispatch_image

    def _dispatch_image(self, request, observations):
        if len(observations) != 1:
            raise TutorUnavailable('one current image observation is required')
        observation = copy.deepcopy(observations[0])
        with self._gate:
            session = self._session
            route = self._image_route
        if session is None or route is None:
            raise TutorUnavailable('native image dispatch unavailable')
        def current_owner():
            owner = self._current()
            with self._gate:
                if (session is not self._session or request['session_id'] != session.session_id
                        or self._observations.get(observation['observation_id']) != observation
                        or route is not self._image_route):
                    raise TutorUnavailable('image dispatch crossed a stopped or changed observation')
            return {**owner, 'session_id': session.session_id,
                    'observation_ids': [observation['observation_id']],
                    'artifact_refs': [observation['artifact_ref']]}
        checks = []
        instruction = route.dispatch(request, observations, store=self._images,
            current_owner=current_owner, current_binding=self._frame_binding, _release_checks=checks)
        with self._gate:
            if session is not self._session or route is not self._image_route:
                raise TutorUnavailable('image answer crossed Stop before publication')
            self._image_release_checks[request['request_id']] = tuple(checks)
            while len(self._image_release_checks) > 128:
                self._image_release_checks.popitem(last=False)
        return instruction

    def _current(self):
        if (self._learning._binding != self._binding or self._learning._service is not self._learning_service
                or self._learning._surface != "native_companion"):
            raise TutorUnavailable("native learning binding changed")
        owner = self._reader()
        if not isinstance(owner, dict):
            raise TutorUnavailable("current native host policy is unavailable")
        owner = copy.deepcopy(owner)
        if any(owner.get(key) != value for key, value in self._identity.items()):
            raise TutorUnavailable("host identity changed")
        if self._project is not None and owner.get("project_id") != self._project:
            raise TutorUnavailable("host project changed")
        try:
            self._learning.command("learning.capabilities")
        except learning_contracts.ContractError as error:
            raise TutorUnavailable("native learning binding is unavailable") from error
        if (self._learning._binding != self._binding or self._learning._service is not self._learning_service
                or self._learning._surface != "native_companion"):
            raise TutorUnavailable("native learning binding changed")
        return owner

    @staticmethod
    def _receipt(receipt):
        contracts._record(receipt, NativeTutorHost.RECEIPT_FIELDS)
        for key in ("source_id", "source_revision"):
            contracts._ident(receipt[key], key)
        contracts._enum(receipt["source_kind"], "source_kind", contracts.SOURCE_KINDS)
        contracts._string(receipt["display_name"], "display_name", 512)
        if not isinstance(receipt["native_handle_digest"], str) or not contracts.SHA256.fullmatch(receipt["native_handle_digest"]):
            raise TutorUnavailable("native selection digest is invalid")
        for key in ("width", "height", "capture_epoch"):
            contracts._integer(receipt[key], key, 1)
        if receipt["width"] > 8192 or receipt["height"] > 8192 or receipt["width"] * receipt["height"] * 4 > 32 * 1024 * 1024:
            raise TutorUnavailable("native selection dimensions exceed capture bounds")
        return copy.deepcopy(receipt)

    def select_source(self, native_receipt, *, _dispatch_connection=None, _dispatch_generation=None):
        receipt = self._receipt(native_receipt)
        with self._gate:
            if _dispatch_connection is not None and (
                    _dispatch_connection is not self._connection or not _dispatch_connection.ready
                    or _dispatch_generation != self._selection_generation):
                raise TutorUnavailable('native selection crossed a stopped connection')
            same_pending = (self._source_authority is not None and self._session is None
                            and self._pending_source == receipt)
            if same_pending:
                self._selection_generation += 1
            else:
                self.stop_sharing()
            attempt = self._selection_generation
        identity = (receipt["source_id"], receipt["source_revision"], receipt["capture_epoch"])
        with self._gate:
            if attempt != self._selection_generation:
                raise TutorUnavailable("native selection was cancelled")
            if identity in self._retired:
                raise TutorUnavailable("retired native selection cannot be reauthorized")
        if self._source_authority is not None:
            with self._gate:
                if attempt != self._selection_generation:
                    raise TutorUnavailable('native source approval cancelled')
                self._pending_source = copy.deepcopy(receipt)
            def current_attempt():
                with self._gate:
                    return (attempt == self._selection_generation and self._pending_source == receipt
                            and (_dispatch_connection is None or _dispatch_connection is self._connection and _dispatch_connection.ready))
            self._source_authority.request_source(receipt, current_attempt=current_attempt)
        owner = self._current()
        self._authorize_source(receipt, owner)
        with self._gate:
            if attempt != self._selection_generation:
                raise TutorUnavailable('native selection stopped before session creation')
        opened = self._learning.command("session.open", {
            "objective": "Explain the explicitly selected source",
            "retention_class": "ephemeral"},
            request_id="native-open-" + receipt["source_id"],
            idempotency_key="native-source-" + receipt["source_id"])
        owner = self._current()
        now, expiry = self._authorize_source(receipt, owner)
        session = TutorSession(opened["record"]["id"], self._identity["user_id"],
                               self._identity["tenant_id"], self._project, [receipt["source_id"]])
        session.invoke()
        session.select_source(SelectedSource(receipt["source_id"], receipt["source_kind"],
                                             receipt["source_revision"], receipt["native_handle_digest"]),
                              native_capture_epoch=receipt["capture_epoch"])
        try:
            current = self._current()
            now, expiry = self._authorize_source(receipt, current)
            if (current['consent_revision'] != owner['consent_revision']
                    or current.get('cancellation_generation') != owner.get('cancellation_generation')
                    or current.get('cancellation_generation') != session.cancellation_generation):
                raise TutorUnavailable('native selection permission changed')
        except BaseException:
            session.stop()
            raise
        with self._gate:
            if attempt != self._selection_generation:
                session.stop()
                raise TutorUnavailable("native selection was cancelled")
            self._session = session
            self._pending_source = None
            authorization = {"schema": "fleet.tutor.capture-authorization.v1", "session_id": session.session_id,
                    "source_id": receipt["source_id"], "source_revision": receipt["source_revision"],
                    "capture_epoch": session.capture_epoch, "consent_revision": owner["consent_revision"],
                    "cancellation_generation": session.cancellation_generation,
                    "now_monotonic_ms": now, "expires_at_monotonic_ms": min(expiry, now + self.MAX_AUTHORIZATION_MS),
                    "grant_created": False}
            self._capture_authorization = copy.deepcopy(authorization)
            factory = getattr(self._connection, 'create_frame_reader', None)
            if callable(factory):
                self._frame_reader = factory(self._frame_binding)
            return authorization

    @staticmethod
    def _authorize_source(receipt, owner):
        if (receipt["source_id"] not in owner.get("source_ids", [])
                or owner.get("source_revisions", {}).get(receipt["source_id"]) != receipt["source_revision"]
                or owner.get("capture_epoch") != receipt["capture_epoch"]
                or "observe" not in owner.get("grant_view", [])):
            raise TutorUnavailable("native selection is outside current host authority")
        contracts._ident(owner.get("consent_revision"), "consent_revision")
        now = contracts._integer(owner.get("now_monotonic_ms"), "now_monotonic_ms")
        expiry = contracts._integer(owner.get("grant_expires_at_monotonic_ms"), "grant_expires_at_monotonic_ms", 1)
        if expiry <= now:
            raise TutorUnavailable("native source grant expired")
        return now, expiry

    def launch(self, native_executable, *, timeout_ms):
        """Host-owned verified configuration only; never selected by request text."""
        from tutor_connection import launch
        with self._gate:
            generation = self._selection_generation
            if self._connection is not None or self._launch_stop is not None:
                raise TutorUnavailable('native companion already connected')
            cancel = self._launch_stop = threading.Event()
        connection = None
        try:
            self._current()
            options = {'protocol_version':'1.2'} if self._practice is not None else {}
            connection = launch(native_executable, enabled=self._service.enabled, timeout_ms=timeout_ms, stop_event=cancel, **options)
            if isinstance(connection, dict):
                return connection
            self._current()
            with self._gate:
                if generation != self._selection_generation or self._connection is not None:
                    raise TutorUnavailable('native launch stopped or superseded')
                self._connection = connection
            return connection
        except BaseException:
            if connection is not None and not isinstance(connection, dict):
                connection.stop()
            raise
        finally:
            with self._gate:
                if self._launch_stop is cancel:
                    self._launch_stop = None

    def ask(self, request, observations):
        with self._gate:
            session = self._session
        if session is None:
            raise TutorUnavailable("no current native source session")
        result = self._service.ask_current(request, self._current, observations, session)
        if result["allowed"]:
            return {**result, "grant_created": False, "learning_success_claimed": False}
        return result

    def _publish_presentation(self, receipt, current_check):
        with self._gate:
            self._published_presentation = (copy.deepcopy(receipt), current_check)

    def supervise_presentation(self):
        """Retire only the published scene whose teaching authority changed."""
        with self._gate:
            published = self._published_presentation
        if published is None:
            return None
        receipt, current_check = published
        try:
            valid = current_check()
        except (TutorUnavailable, contracts.ContractViolation, ValueError):
            valid = False
        if valid:
            return None
        with self._gate:
            if self._published_presentation is not published:
                return None
            self._published_presentation = None
        return {'binding': copy.deepcopy(receipt['binding']), 'reason_code': 'TEACHING_AUTHORIZATION_REVOKED'}

    def supervise_source(self):
        """Retire revoked capture on idle ticks, without waiting for a new Ask."""
        with self._gate:
            authorization = self._capture_authorization
            generation = self._selection_generation
        if authorization is None:
            return True
        try:
            self._frame_binding()
            return True
        except (TutorUnavailable, contracts.ContractViolation, ValueError):
            with self._gate:
                if generation == self._selection_generation and authorization is self._capture_authorization:
                    self._retire_source_locked()
                    return False
            return True

    def ask_observed(self, body, *, deadline_ms, _release_checks=None):
        """Native input selects no authority; only the host builds the request."""
        import tutor_transport as wire
        wire._question_shape(body)
        deadline_ms = contracts._integer(deadline_ms, 'deadline_ms', 1)
        with self._gate:
            session = self._session
            observation = copy.deepcopy(self._observations.get(body['observation_id']))
            if session is None or observation is None:
                raise TutorUnavailable('current source observation unavailable')
            if body['request_id'] in self._question_ids:
                raise TutorUnavailable('duplicate native question')
            self._question_ids.append(body['request_id'])
        if self._service.dispatch is None:
            raise TutorUnavailable('no qualified answer provider configured')
        def current():
            owner = self._current()
            with self._gate:
                if session is not self._session or self._observations.get(body['observation_id']) != observation:
                    raise TutorUnavailable('source observation changed during question')
            return {**owner, 'session_id': session.session_id,
                    'observation_ids': [observation['observation_id']], 'artifact_refs': [observation['artifact_ref']]}
        owner = current()
        budgets = owner.get('budget_reservation_ids', [])
        if not isinstance(budgets, list) or len(budgets) != 1:
            raise TutorUnavailable('one current host budget reservation is required')
        request = {'schema': 'fleet.tutor.request.v1', 'request_id': body['request_id'],
            'session_id': session.session_id, **self._identity, 'project_id': self._project,
            'mode': 'EXPLAIN', 'learning_intent': body['learning_intent'], 'question': body['question'],
            'observation_ids': [observation['observation_id']], 'source_ids': [observation['source_id']],
            'skill_ids': [], 'consent_revision': observation['consent_revision'],
            'cancellation_generation': session.cancellation_generation, 'budget_reservation_id': budgets[0],
            'retention_policy_id': observation['retention_policy_id'],
            'deadline_monotonic_ms': min(deadline_ms, owner['grant_expires_at_monotonic_ms'], observation['expires_at_monotonic_ms']),
            'research_scope': 'SOURCE_ONLY', 'output_preferences': {'response_format':
                'TEXT_AND_SCENE' if self._presentation is not None and body['learning_intent'] == 'LEARN' else 'TEXT',
                'speech': False, 'locale': body['locale']}}
        try:
            result = self._service.ask_current(request, current, [observation], session)
        finally:
            with self._gate:
                image_checks = self._image_release_checks.pop(request['request_id'], ())
        if result['allowed'] and self._image_route is not None:
            if not image_checks or not all(check() for check in image_checks):
                raise TutorUnavailable('image answer authority changed before release')
            if _release_checks is not None:
                _release_checks.extend(image_checks)
        if result['allowed'] and any(not set(claim['evidence_refs']).issubset({observation['observation_id']})
                                     for claim in result['instruction']['claims']):
            result = {'allowed': False, 'reason_code': 'UNKNOWN_EVIDENCE', 'record_id': body['request_id']}
            result['failure_stage'] = 'INSTRUCTION_VALIDATION'
        if result['allowed'] and _release_checks is not None:
            def release_current():
                return not isinstance(self._service._admit(request, current(), [observation], session), dict)
            _release_checks.append(release_current)
        if result['allowed'] and self._presentation is not None and body['learning_intent'] == 'LEARN':
            from tutor_presentation import PresentationRefused
            scene = self._presentation
            try:
                presentation = scene.render(request, observation, current())
            except PresentationRefused:
                # Keep the admitted explanation. The native Teach flow labels
                # the absent diagram explicitly; no replacement scene is used.
                result['presentation_unavailable'] = True
            else:
                result['presentation'] = presentation
                if _release_checks is not None:
                    def presentation_current():
                        try:
                            owner = current()
                            candidate = scene.render(request, observation, owner)
                            # Rechecking authority cannot extend the originally published lease.
                            if owner['now_monotonic_ms'] >= presentation['expires_at_monotonic_ms'] or candidate['expires_at_monotonic_ms'] < presentation['expires_at_monotonic_ms']:
                                return False
                            candidate['expires_at_monotonic_ms'] = presentation['expires_at_monotonic_ms']
                            return scene is self._presentation and candidate == presentation
                        except (ValueError, TutorUnavailable, contracts.ContractViolation):
                            return False
                    _release_checks.append(presentation_current)
        return {**result, 'grant_created': False, 'learning_success_claimed': False}

    def run(self, *, stop_event):
        """Caller-owned receive pump; bounded workers never block local controls."""
        if not isinstance(stop_event, threading.Event):
            raise TutorUnavailable('host loop requires caller-owned cancellation')
        import tutor_transport as wire
        with self._gate:
            if self._running or self._workers:
                raise TutorUnavailable('native host loop already running or draining')
            self._running = True
        operation = supervision = None
        failures = []
        def start_worker(action, name):
            def work():
                try:
                    action()
                except BaseException:
                    with self._gate:
                        live = self._connection is not None and not stop_event.is_set()
                    if live:
                        failures.append(True)
                        self.stop()
                finally:
                    with self._gate:
                        self._workers.discard(threading.current_thread())
            worker = threading.Thread(target=work, name=name, daemon=True)
            with self._gate:
                self._workers.add(worker)
            try: worker.start()
            except BaseException:
                with self._gate: self._workers.discard(worker)
                raise
            return worker
        def schedule(message, connection, generation):
            nonlocal operation
            if operation is not None and operation.is_alive():
                remaining = message['deadline_monotonic_ms'] - wire.windows_monotonic_ms()
                if remaining > 0:
                    connection.send('REFUSAL', {'reason_code': 'OPERATION_BUSY', 'detail': 'A native request is still pending'},
                        timeout_ms=min(remaining, 2000), reply_to=message['message_id'], deadline_ms=message['deadline_monotonic_ms'])
                return
            owned = copy.deepcopy(message)
            operation = start_worker(lambda: self._dispatch_event(owned, connection, generation), 'screen-tutor-native-operation')
        def supervise():
            retired = self.supervise_presentation()
            if retired is not None:
                with self._gate: connection = self._connection
                if connection is not None and connection.ready:
                    connection.send('PRESENTATION_RETIRED', retired, timeout_ms=2000,
                        reply_to=None, deadline_ms=wire.windows_monotonic_ms() + 2000)
            if not self.supervise_source():
                with self._gate: connection = self._connection
                if connection is not None and connection.ready:
                    connection.send('UNAVAILABLE', {'reason_code': 'SOURCE_AUTHORIZATION_REVOKED',
                        'detail': 'Sharing authorization changed; choose the source again'},
                        timeout_ms=2000, reply_to=None, deadline_ms=wire.windows_monotonic_ms() + 2000)
        try:
            while not stop_event.is_set():
                if failures: raise TutorUnavailable('native operation unavailable')
                if not self._service.enabled:
                    raise TutorUnavailable('screen tutor disabled during host loop')
                self.expire_observations()
                with self._gate: has_source = self._capture_authorization is not None
                if has_source and (supervision is None or not supervision.is_alive()):
                    supervision = start_worker(supervise, 'screen-tutor-native-supervision')
                try:
                    self.serve_once(timeout_ms=100, _schedule=schedule)
                except wire.StaleBridgeMessage:
                    continue  # Authenticated sequence consumed; no expired control or answer is applied.
        finally:
            self.stop()
            with self._gate: self._running = False

    def serve_once(self, *, timeout_ms, _schedule=None):
        """Dispatch one already-authenticated native event on the owned channel.

        The application owns scheduling. Idle is no work; native selection is
        admitted by the sealed current policy, never by its wire receipt alone.
        """
        import tutor_transport as wire
        with self._gate:
            connection = self._connection
            generation = self._selection_generation
        if connection is None or not connection.ready:
            raise TutorUnavailable('native host connection unavailable')
        message = connection.poll(timeout_ms=timeout_ms)
        if message is None: return False
        if _schedule is not None and message['message_type'] in wire.REPLIES:
            _schedule(message, connection, generation)
            return True
        return self._dispatch_event(message, connection, generation)

    def _dispatch_event(self, message, connection, generation):
        import tutor_transport as wire
        from tutor_connection import ReleaseRefused
        from tutor_authority import SourceApprovalRequired
        kind = message['message_type']
        control = kind in ('STOP', 'UNAVAILABLE', 'PAUSE', 'REFUSAL')
        with self._gate:
            if connection is not self._connection or not connection.ready or not control and generation != self._selection_generation:
                raise TutorUnavailable('native event crossed a stopped or replaced source')
        if message['deadline_monotonic_ms'] <= wire.windows_monotonic_ms():
            return False
        response = None
        release_checks = []
        practice = self._practice
        help_token = None
        try:
            if kind == 'REFUSAL':
                return True
            if kind == 'SELECT_SOURCE':
                self.select_source(message['body'], _dispatch_connection=connection, _dispatch_generation=generation)
                response = ('CAPTURE_AUTHORIZATION', self._frame_binding())
            elif kind == 'FRAME':
                response = ('FRAME_ACCEPTED', {'observation': self.observe_frame(message['body']['frame_reference'])})
            elif kind == 'PRACTICE_REQUEST':
                with self._gate:
                    if (practice is None or message.get('protocol_version') != '1.2'
                            or connection is not self._connection or generation != self._selection_generation):
                        raise TutorUnavailable('native practice is unavailable or stale')
                response = ('PRACTICE_RESULT', practice.wire_command(message['body']))
            elif kind == 'QUESTION':
                if practice is not None:
                    help_token = practice.help_token()
                if self._service.dispatch is None:
                    response = ('REFUSAL', {'reason_code': 'PROVIDER_UNAVAILABLE', 'detail': 'No qualified answer provider is configured'})
                else:
                    result = self.ask_observed(message['body'], deadline_ms=message['deadline_monotonic_ms'], _release_checks=release_checks)
                    response = (('ANSWER', {'instruction': result['instruction']}) if result['allowed'] else
                                ('REFUSAL', {'reason_code': result['reason_code'], 'detail':
                                 'The answer failed validation and was not displayed. Ask again using the current source.'
                                 if result.get('failure_stage') == 'INSTRUCTION_VALIDATION' else
                                 'The question or source is no longer admissible'}))
                    if response[0] == 'ANSWER' and 'presentation' in result:
                        response[1]['presentation'] = result['presentation']
            elif kind in ('STOP', 'UNAVAILABLE', 'PAUSE'):
                if kind != 'PAUSE' and practice is not None:
                    practice.retire()
                with self._gate:
                    if connection is not self._connection or not connection.ready:
                        raise TutorUnavailable('native event crossed a stopped or replaced source')
                    self._retire_source_locked()
                return True
            else:
                response = ('REFUSAL', {'reason_code': 'OPERATION_UNAVAILABLE', 'detail': 'Native operation is not connected'})
        except SourceApprovalRequired as error:
            detail = ('Waiting for Fleet approval. Your source is selected, but sharing has not started.'
                      if error.code == 'SOURCE_APPROVAL_PENDING' else
                      'Fleet denied sharing this source. Choose another source.'
                      if error.code == 'SOURCE_APPROVAL_DENIED' else
                      'Source approval is no longer current. Choose and authorize the source again.')
            response = ('REFUSAL', {'reason_code': error.code, 'detail': detail})
        except (TutorUnavailable, contracts.ContractViolation, ValueError):
            response = ('REFUSAL', {'reason_code': 'SOURCE_AUTHORIZATION_REFUSED', 'detail': 'Current host authorization does not admit this source'})
        remaining = message['deadline_monotonic_ms'] - wire.windows_monotonic_ms()
        if remaining <= 0:
            if kind == 'SELECT_SOURCE': self.stop_sharing()
            if response[0] == 'FRAME_ACCEPTED':
                observation = response[1]['observation']
                with self._gate:
                    self._observations.pop(observation['observation_id'], None)
                self._discard_image(observation)
            return False
        if response[0] == 'CAPTURE_AUTHORIZATION':
            try:
                response = ('CAPTURE_AUTHORIZATION', self._frame_binding())
            except (TutorUnavailable, contracts.ContractViolation, ValueError):
                self.stop_sharing()
                response = ('REFUSAL', {'reason_code': 'SOURCE_AUTHORIZATION_REFUSED', 'detail': 'Source authorization changed before reply'})
        if response[0] == 'FRAME_ACCEPTED':
            observation = response[1]['observation']
            try:
                self._frame_binding()
                owner = {**self._current(), 'session_id': observation['session_id'], 'artifact_refs': [observation['artifact_ref']]}
                if (observation['retention_policy_id'] not in owner.get('retention_policy_ids', [])
                        or not contracts.validate_observation(observation, owner)['allowed']):
                    raise TutorUnavailable('observation changed before frame reply')
            except (TutorUnavailable, contracts.ContractViolation, ValueError):
                with self._gate:
                    self._observations.pop(observation['observation_id'], None)
                self._discard_image(observation)
                response = ('REFUSAL', {'reason_code': 'FRAME_REFUSED', 'detail': 'Frame authorization changed before reply'})
        if response[0] == 'ANSWER':
            try:
                if not release_checks or not all(check() for check in release_checks):
                    raise TutorUnavailable('question changed before wire release')
            except (TutorUnavailable, contracts.ContractViolation, ValueError):
                response = ('REFUSAL', {'reason_code': 'QUESTION_REFUSED', 'detail': 'Question authorization changed before reply'})
            if response[0] == 'ANSWER' and practice is not None:
                try:
                    practice.record_help(help_token, answer_exposed=response[1]['instruction']['reveal_level'] == 'DIRECT')
                except ValueError:
                    response = ('REFUSAL', {'reason_code':'PRACTICE_EXPOSURE_UNAVAILABLE','detail':'Assistance could not be recorded before publication'})
        with self._gate:
            if connection is not self._connection or not connection.ready:
                raise TutorUnavailable('native host connection stopped before reply')
            if response[0] == 'CAPTURE_AUTHORIZATION' and (self._capture_authorization is None
                    or any(self._capture_authorization.get(name) != response[1].get(name)
                           for name in ('session_id', 'source_id', 'source_revision', 'capture_epoch', 'consent_revision', 'cancellation_generation'))):
                response = ('REFUSAL', {'reason_code': 'SOURCE_AUTHORIZATION_REFUSED', 'detail': 'Source selection changed before reply'})
            if response[0] == 'FRAME_ACCEPTED' and (generation != self._selection_generation
                    or self._observations.get(response[1]['observation']['observation_id']) != response[1]['observation']):
                response = ('REFUSAL', {'reason_code': 'FRAME_REFUSED', 'detail': 'Source stopped before frame reply'})
            if response[0] == 'ANSWER' and generation != self._selection_generation:
                response = ('REFUSAL', {'reason_code': 'QUESTION_REFUSED', 'detail': 'Source stopped before answer reply'})
            release_generation = self._selection_generation
        def release_at_writer():
            try:
                with self._gate:
                    if (connection is not self._connection or not connection.ready
                            or release_generation != self._selection_generation):
                        return False
                if response[0] == 'CAPTURE_AUTHORIZATION':
                    if self._frame_binding() != response[1]:
                        return False
                elif response[0] == 'FRAME_ACCEPTED':
                    observation = response[1]['observation']
                    self._frame_binding()
                    owner = {**self._current(), 'session_id': observation['session_id'],
                             'artifact_refs': [observation['artifact_ref']]}
                    if (observation['retention_policy_id'] not in owner.get('retention_policy_ids', [])
                            or not contracts.validate_observation(observation, owner)['allowed']):
                        return False
                elif response[0] == 'PRACTICE_RESULT':
                    return (practice is self._practice and practice.wire_status() == response[1])
                else:
                    return bool(release_checks) and all(check() for check in release_checks)
                with self._gate:
                    return (connection is self._connection and connection.ready
                        and release_generation == self._selection_generation
                        and (response[0] != 'FRAME_ACCEPTED' or
                             self._observations.get(observation['observation_id']) == observation))
            except (TutorUnavailable, contracts.ContractViolation, ValueError):
                return False
        send_options = {}
        if response[0] in ('ANSWER', 'CAPTURE_AUTHORIZATION', 'FRAME_ACCEPTED', 'PRACTICE_RESULT'):
            send_options['release_check'] = release_at_writer
        try:
            connection.send(*response, timeout_ms=min(remaining, 10000),
                            reply_to=message['message_id'] if kind in wire.REPLIES else None,
                            deadline_ms=message['deadline_monotonic_ms'], **send_options)
        except ReleaseRefused:
            refusal_code = {'CAPTURE_AUTHORIZATION': 'SOURCE_AUTHORIZATION_REFUSED',
                            'FRAME_ACCEPTED': 'FRAME_REFUSED', 'ANSWER': 'QUESTION_REFUSED', 'PRACTICE_RESULT':'PRACTICE_REFUSED'}[response[0]]
            if response[0] == 'CAPTURE_AUTHORIZATION':
                with self._gate:
                    if release_generation == self._selection_generation:
                        self._retire_source_locked()
            elif response[0] == 'FRAME_ACCEPTED':
                observation = response[1]['observation']
                with self._gate:
                    if self._observations.get(observation['observation_id']) == observation:
                        self._observations.pop(observation['observation_id'], None)
                self._discard_image(observation)
            remaining = message['deadline_monotonic_ms'] - wire.windows_monotonic_ms()
            if remaining > 0 and connection.ready:
                connection.send('REFUSAL', {'reason_code': refusal_code,
                    'detail':'Authorization changed before reply'},
                    timeout_ms=min(remaining,10000), reply_to=message['message_id'],
                    deadline_ms=message['deadline_monotonic_ms'])
            return False
        if response[0] == 'ANSWER' and 'presentation' in response[1]:
            with self._gate:
                if connection is self._connection and generation == self._selection_generation:
                    self._publish_presentation(response[1]['presentation'], release_checks[-1])
        return True

    def _frame_binding(self):
        with self._gate:
            session = self._session
            authorization = copy.deepcopy(self._capture_authorization)
        if session is None or authorization is None or not self._service.enabled:
            raise TutorUnavailable('no current frame source authorization')
        owner = self._current()
        self._authorize_source(authorization, owner)
        if (owner['consent_revision'] != authorization['consent_revision']
                or owner.get('cancellation_generation') != authorization['cancellation_generation']
                or session.cancellation_generation != authorization['cancellation_generation']):
            raise TutorUnavailable('frame source permission changed')
        authorization['expires_at_monotonic_ms'] = min(authorization['expires_at_monotonic_ms'], owner['grant_expires_at_monotonic_ms'])
        with self._gate:
            if session is not self._session or self._capture_authorization is None:
                raise TutorUnavailable('frame source stopped')
        return authorization

    def consume_frame(self, reference, *, expires_bridge_ms=None):
        with self._gate:
            reader = self._frame_reader; generation = self._selection_generation
        if reader is None: raise TutorUnavailable('native frame connection unavailable')
        admitted = None
        try:
            admitted = reader.put_png(reference, self._images, expires_bridge_ms=expires_bridge_ms)
            with self._gate:
                if reader is not self._frame_reader or generation != self._selection_generation:
                    raise TutorUnavailable('frame source stopped before publication')
                return admitted
        except Exception:
            if admitted is not None:
                try:
                    image = self._images.take(admitted['artifact_ref'], admitted)
                    image['bytes'][:] = b'\0' * len(image['bytes'])
                except ValueError: pass
            raise

    def _discard_image(self, observation):
        try:
            image = self._images.take(observation['artifact_ref'], observation)
            image['bytes'][:] = b'\0' * len(image['bytes'])
        except ValueError:
            pass

    def expire_observations(self):
        with self._gate:
            if not self._observations:
                return 0
        import tutor_transport as wire
        now = wire.windows_monotonic_ms()
        with self._gate:
            expired = [key for key, value in self._observations.items() if now >= value['expires_at_monotonic_ms']]
            for key in expired:
                self._discard_image(self._observations.pop(key))
            return len(expired)

    def observe_frame(self, reference):
        """Construct model evidence from admitted bytes and host-owned identity."""
        import uuid
        from datetime import datetime, timezone, timedelta
        import tutor_transport as wire
        binding = self._frame_binding()
        with self._gate:
            session = self._session; generation = self._selection_generation
            source = session.source if session is not None else None
        if source is None: raise TutorUnavailable('no selected frame source')
        wire._frame_shape(reference)
        owner = self._current()
        retention = owner.get('retention_policy_ids', [])
        if not isinstance(retention, list) or len(retention) != 1:
            raise TutorUnavailable('one explicit host retention policy is required')
        contracts._ident(retention[0], 'retention_policy_id')
        captured = reference['frame_receipt']['captured_at_monotonic_ms']
        now = wire.windows_monotonic_ms()
        if not 0 <= now - captured < self.MAX_FRAME_ADMISSION_AGE_MS:
            raise TutorUnavailable('frame is not current')
        try:
            image = self.consume_frame(reference, expires_bridge_ms=captured + self.MAX_TEXT_SNAPSHOT_MS)
        except ValueError as error:
            raise TutorUnavailable('frame image admission refused') from error
        observation = {'schema': 'fleet.tutor.observation.v1', 'observation_id': 'obs-' + uuid.uuid4().hex,
            'session_id': binding['session_id'], 'capture_epoch': binding['capture_epoch'],
            'source_id': binding['source_id'], 'source_kind': source.source_kind,
            'source_revision': binding['source_revision'], **self._identity, 'project_id': self._project,
            'consent_revision': binding['consent_revision'],
            'captured_at_utc': (datetime.now(timezone.utc) - timedelta(milliseconds=now-captured)).isoformat().replace('+00:00', 'Z'),
            'captured_at_monotonic_ms': captured, 'expires_at_monotonic_ms': min(binding['expires_at_monotonic_ms'], captured + self.MAX_TEXT_SNAPSHOT_MS),
            'geometry_revision': 'geometry-' + uuid.uuid4().hex,
            'geometry': {'coordinate_space': 'source_pixels', 'source_width': image['width'], 'source_height': image['height'],
                'crop': {'x': 0, 'y': 0, 'width': image['width'], 'height': image['height']},
                'model_width': image['width'], 'model_height': image['height'], 'desktop_origin_x': None,
                'desktop_origin_y': None, 'native_dpi_scale': None},
            'modalities': ['pixels'], 'media': None, 'artifact_ref': image['artifact_ref'],
            'content_sha256': image['content_sha256'], 'retention_policy_id': retention[0]}
        try:
            current = self._current()
            current_binding = self._frame_binding()
            if (any(current_binding[name] != binding[name] for name in ('session_id', 'source_id', 'source_revision', 'capture_epoch', 'consent_revision', 'cancellation_generation'))
                    or current.get('retention_policy_ids') != retention):
                raise TutorUnavailable('frame policy changed before observation publication')
            current = {**current, 'session_id': session.session_id, 'artifact_refs': [image['artifact_ref']]}
            if not contracts.validate_observation(observation, current)['allowed']:
                raise TutorUnavailable('frame observation refused by current policy')
            with self._gate:
                if session is not self._session or generation != self._selection_generation:
                    raise TutorUnavailable('source stopped before observation publication')
                self._observations[observation['observation_id']] = copy.deepcopy(observation)
                while len(self._observations) > 3:
                    _, old = self._observations.popitem(last=False)
                    self._discard_image(old)
            return copy.deepcopy(observation)
        except BaseException:
            self._discard_image(observation)
            raise

    def stop(self):
        if self._practice is not None:
            self._practice.retire()
        with self._gate:
            connection, self._connection = self._connection, None
            if self._launch_stop is not None:
                self._launch_stop.set()
                self._launch_stop = None
            self._retire_source_locked()
        if connection is not None:
            connection.stop()

    def _retire_source_locked(self):
        self._selection_generation += 1
        if self._pending_source is not None:
            pending = self._pending_source
            self._retired.append((pending['source_id'], pending['source_revision'], pending['capture_epoch']))
            self._pending_source = None
        if self._source_authority is not None:
            self._source_authority.retire()
        self._capture_authorization = None
        self._published_presentation = None
        self._image_release_checks.clear()
        self._observations.clear()
        reader, self._frame_reader = self._frame_reader, None
        if reader is not None: reader.close()
        self._images.close()
        if self._session is not None:
            source = self._session.source
            if source is not None:
                self._retired.append((source.source_id, source.source_revision, self._session.capture_epoch))
            self._session.stop()
            self._session = None

    def stop_sharing(self):
        """Retire selected-source work while preserving the authenticated bridge."""
        with self._gate:
            self._retire_source_locked()
