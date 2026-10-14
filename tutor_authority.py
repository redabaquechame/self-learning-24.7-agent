"""Current native source views derived from existing exact-call owner approvals.

No capture, provider, native call or new standing grant at import. The trusted
Fleet host supplies authenticated context; native receipts cannot grant access.
"""
import copy
import hashlib
import os
import threading
from collections import OrderedDict

import approvals
import org
import tutor_contracts as contracts


class SourceApprovalRequired(ValueError):
    def __init__(self, code, approval_id=None):
        self.code = code
        self.approval_id = approval_id
        super().__init__(code)


class SourceApprovalAuthority:
    def __init__(self, home, expert_root, expert_slug, current_context, *,
                 clock_ms, lifetime_ms=900000, instance_id):
        if (not callable(current_context) or not callable(clock_ms)
                or type(lifetime_ms) is not int or not 1 <= lifetime_ms <= 900000):
            raise ValueError('source authority dependencies unavailable')
        contracts._ident(expert_slug, 'expert_slug')
        contracts._ident(instance_id, 'instance_id')
        self.home = os.path.realpath(home)
        self.root = os.path.realpath(expert_root)
        self.slug = expert_slug
        self._reader, self._clock = current_context, clock_ms
        self._lifetime, self._instance = lifetime_ms, instance_id
        self._attempts, self._retired = OrderedDict(), OrderedDict()
        self._selected = None
        self._generation = 0
        self._gate = threading.RLock()
        self._context = self._live_context(initial=True)

    def _live_context(self, *, initial=False):
        value = copy.deepcopy(self._reader())
        contracts._record(value, ('user_id', 'tenant_id', 'project_id', 'actor_id',
            'profile_revision', 'purpose', 'retention_policy_id', 'budget_policy_id',
            'budget_reservation_id', 'budget_ceiling_usd', 'provider_models'))
        for name in ('user_id', 'tenant_id', 'project_id', 'profile_revision',
                     'purpose', 'retention_policy_id', 'budget_policy_id', 'budget_reservation_id'):
            contracts._ident(value[name], name)
        contracts._string(value['actor_id'], 'actor_id', 256)
        if not isinstance(value['provider_models'], dict) or len(value['provider_models']) > 64:
            raise ValueError('provider profile unavailable')
        import tutor_gateway
        for provider, model in value['provider_models'].items():
            contracts._ident(provider, 'provider')
            tutor_gateway._model_name(model)
        tutor_gateway._finite(value['budget_ceiling_usd'], 'budget_ceiling_usd', 0)
        try:
            org.check(self.home, value['actor_id'], 'run', self.slug)
        except org.Denied as error:
            raise SourceApprovalRequired('SOURCE_ACTOR_REFUSED') from error
        if not initial and value != self._context:
            raise SourceApprovalRequired('SOURCE_CONTEXT_CHANGED')
        return value

    @property
    def identity(self):
        context = self._live_context()
        return {name: context[name] for name in ('user_id', 'tenant_id', 'project_id')}

    def _retire_locked(self):
        self._generation += 1
        if self._selected is not None:
            self._retired[self._selected] = True
            while len(self._retired) > 128:
                self._retired.popitem(last=False)
        self._selected = None

    def retire(self):
        with self._gate:
            self._retire_locked()

    def retire_approval(self, approval_id):
        """Retire only this still-selected attempt, preserving owner history."""
        with self._gate:
            attempt = self._attempts.get(self._selected)
            if (attempt is None or attempt['approval_id'] != approval_id
                    or self._selected in self._retired):
                return False
            self._retire_locked()
            return True

    def request_source(self, receipt, *, current_attempt=None):
        from tutor_host import NativeTutorHost
        from tutor_service import TutorUnavailable
        try:
            receipt = NativeTutorHost._receipt(receipt)
        except (TutorUnavailable, contracts.ContractViolation, ValueError) as error:
            raise SourceApprovalRequired('SOURCE_RECEIPT_INVALID') from error
        context = self._live_context()
        if current_attempt is not None and not current_attempt():
            raise SourceApprovalRequired('SOURCE_RETIRED')
        exact = {'instance_id': self._instance, 'expert_root': self.root,
                 'context': context, 'source': receipt,
                 'requested_capabilities': ['observe', 'explain']}
        key = 'native-source-' + hashlib.sha256(
            contracts.canonical_json(exact).encode('ascii')).hexdigest()
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        with self._gate:
            if key in self._retired:
                raise SourceApprovalRequired('SOURCE_RETIRED')
            if self._selected is not None and self._selected != key:
                self._retire_locked()
            self._selected = key
            generation = self._generation
        record = approvals.request(self.root, key, 'screen_tutor', 'share_source_for_explanation',
            {'scope': exact, 'requested_at_monotonic_ms': now,
             'expires_at_monotonic_ms': now + self._lifetime},
            'Share this exact selected source for explanations under the current profile and budget',
            task_id=self._instance, lineage=self._instance)
        args = record.get('args', {})
        if (args.get('scope') != exact or record.get('key') != key
                or record.get('server') != 'screen_tutor'
                or record.get('tool') != 'share_source_for_explanation'):
            raise SourceApprovalRequired('SOURCE_APPROVAL_SCOPE_CHANGED', record['id'])
        start = contracts._integer(args.get('requested_at_monotonic_ms'), 'requested_at_monotonic_ms')
        expiry = contracts._integer(args.get('expires_at_monotonic_ms'), 'expires_at_monotonic_ms', 1)
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        self._live_context()
        # The host callback takes the host lock. Stop takes that lock before
        # retiring this authority, so never call back while holding ours.
        attempt_current = current_attempt is None or current_attempt()
        with self._gate:
            if (generation != self._generation or self._selected != key or key in self._retired
                    or not attempt_current):
                self._retired[key] = True
                while len(self._retired) > 128:
                    self._retired.popitem(last=False)
                raise SourceApprovalRequired('SOURCE_RETIRED', record['id'])
            if expiry - start != self._lifetime or not start <= now < expiry:
                raise SourceApprovalRequired('SOURCE_APPROVAL_EXPIRED', record['id'])
            self._attempts[key] = {'approval_id': record['id'], 'receipt': receipt,
                                  'start': start, 'expiry': expiry, 'scope': exact, 'key': key}
            while len(self._attempts) > 128:
                self._attempts.popitem(last=False)
        if record['status'] != 'granted':
            code = 'SOURCE_APPROVAL_PENDING' if record['status'] == 'pending' else 'SOURCE_APPROVAL_DENIED'
            raise SourceApprovalRequired(code, record['id'])
        admitted = self.current_source()
        if admitted is None:
            raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', record['id'])
        return admitted

    def current_source(self):
        current = self.current_approval()
        return current if current is not None and current['status'] == 'granted' else None

    def current_approval(self):
        """Read-only exact current attempt; pending is never sharing authority."""
        self._live_context()
        with self._gate:
            key, generation = self._selected, self._generation
            attempt = copy.deepcopy(self._attempts.get(key))
            if attempt is None or key in self._retired:
                return None
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        record = approvals.load(self.root, attempt['approval_id'])
        args = record.get('args', {}) if record else {}
        if (not attempt['start'] <= now < attempt['expiry'] or not record
                or record.get('status') not in ('pending', 'granted') or record.get('key') != key
                or record.get('server') != 'screen_tutor'
                or record.get('tool') != 'share_source_for_explanation'
                or args.get('scope') != attempt['scope']
                or args.get('requested_at_monotonic_ms') != attempt['start']
                or args.get('expires_at_monotonic_ms') != attempt['expiry']):
            return None
        self._live_context()
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        with self._gate:
            if (generation != self._generation or key != self._selected or key in self._retired
                    or not attempt['start'] <= now < attempt['expiry']):
                return None
        return {**attempt, 'status': record['status'], 'generation': generation}

    def matches_current(self, view):
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        with self._gate:
            return self._matches_locked(view, now)

    def _matches_locked(self, view, now):
        attempt = self._attempts.get(self._selected)
        return (attempt is not None and self._selected not in self._retired
                and view['generation'] == self._generation
                and attempt['approval_id'] == view['approval_id']
                and attempt['start'] <= now < attempt['expiry'])

    def decision_guard(self, approval_id, record, *, before_commit):
        """No context callback or approval-lock wait under the authority gate."""
        import contextlib
        @contextlib.contextmanager
        def guard():
            view = self.current_approval()
            if (view is None or view['approval_id'] != approval_id
                    or record.get('id') != approval_id
                    or record.get('server') != 'screen_tutor'
                    or record.get('tool') != 'share_source_for_explanation'
                    or record.get('key') != self._selected
                    or record.get('status') != view['status']
                    or record.get('args') != {'scope':view['scope'],
                        'requested_at_monotonic_ms':view['start'],
                        'expires_at_monotonic_ms':view['expiry']}):
                raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id)
            before_commit()
            now = contracts._integer(self._clock(), 'now_monotonic_ms')
            if not self._gate.acquire(blocking=False):
                raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id)
            try:
                if not self._matches_locked(view, now):
                    raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id)
                yield
            finally:
                self._gate.release()
        return guard()

    def owner_state(self):
        current = self.current_source()
        # current_source validates the live reader against this immutable
        # context before reading an attempt and again before granting a view.
        # Reading the same context once more adds no distinct policy check.
        context = copy.deepcopy(self._context)
        now = contracts._integer(self._clock(), 'now_monotonic_ms')
        receipt = current['receipt'] if current else None
        return {**{name: context[name] for name in ('user_id', 'tenant_id', 'project_id')},
            'consent_revision': 'consent-' + (current['approval_id'] if current else self._instance),
            'capture_epoch': receipt['capture_epoch'] if receipt else 0,
            'source_ids': [receipt['source_id']] if receipt else [],
            'source_revisions': {receipt['source_id']: receipt['source_revision']} if receipt else {},
            'observation_ids': [], 'artifact_refs': [], 'now_monotonic_ms': now,
            'cancellation_generation': 1 if current else 0, 'current_cancellation_generation': 1 if current else 0,
            'grant_expires_at_monotonic_ms': current['expiry'] if current else now,
            'mode': 'EXPLAIN', 'actor': 'SYSTEM', 'grant_view': ['observe', 'explain'] if current else [],
            'budget_reservation_ids': [context['budget_reservation_id']],
            'retention_policy_ids': [context['retention_policy_id']]}

    def grant_view(self, current_owner):
        context = self._live_context()
        approved = self.current_source()
        if approved is None:
            raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE')
        if any(current_owner.get(name) != context[name] for name in ('user_id', 'tenant_id', 'project_id')):
            raise SourceApprovalRequired('SOURCE_CONTEXT_CHANGED')
        view = {'schema': 'fleet.tutor.session_grant_view.v1', 'revision': 'source-' + approved['approval_id'],
            'session_id': current_owner['session_id'], 'user_id': context['user_id'],
            'tenant_id': context['tenant_id'], 'project_id': context['project_id'],
            'source_ids': [approved['receipt']['source_id']], 'capabilities': ['observe', 'explain'],
            'purpose': context['purpose'], 'granted_by_ref': approved['approval_id'],
            'consent_revision': 'consent-' + approved['approval_id'],
            'valid_from_monotonic_ms': approved['start'], 'expires_at_monotonic_ms': approved['expiry'],
            'provider_destinations': list(context['provider_models']),
            'retention_policy_id': context['retention_policy_id'], 'budget_policy_id': context['budget_policy_id'],
            'cancellation_generation': 1}
        if not contracts.validate_session_grant_view(view, current_owner)['allowed']:
            raise SourceApprovalRequired('SOURCE_CONTEXT_CHANGED')
        return view

    def budget_view(self, current_owner):
        context = self._live_context()
        if self.current_source() is None or any(current_owner.get(name) != context[name]
                for name in ('user_id', 'tenant_id', 'project_id')):
            raise SourceApprovalRequired('SOURCE_CONTEXT_CHANGED')
        return {'budget_policy_id': context['budget_policy_id'],
                'budget_reservation_id': context['budget_reservation_id'],
                'ceiling_usd': context['budget_ceiling_usd'], 'agent_root': self.root}
