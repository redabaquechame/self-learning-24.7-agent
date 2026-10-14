"""Fleet-owned native sessions. Installation is a trusted host operation only.

No executable, identity, profile, grant or provider is selected by web content.
Each runtime owns one shared learning.v1 service and retires work when the
original authentication proof changes, even without another browser request.
"""
import os
import copy
import hashlib
import secrets
import json
import pathlib
import tomllib
import re
import threading
from dataclasses import dataclass

import org
from learning_contracts import LearningService
from tutor_connection import VerifiedNativeExecutable
from tutor_host import NativeTutorHost


class RuntimeUnavailable(ValueError):
    pass


def source_host_factory(home, slug, actor, agent, *, provider, model, current_profile):
    """Trusted configuration over authenticated Fleet identity and exact approvals.

    The host opts into a declared image profile/budget; this function never
    selects stored credentials or supplies a default provider/model/ceiling.
    """
    from loop import Agent
    from tutor_authority import SourceApprovalAuthority
    from tutor_dispatch import ImageProviderRoute
    from tutor_dispatch import _configuration
    from tutor_gateway import _capability, _qualified_role
    from tutor_service import TutorService
    from tutor_transport import windows_monotonic_ms
    root = os.path.realpath(os.path.join(home, 'experts', slug))
    if not isinstance(agent, Agent) or os.path.realpath(agent.root) != root or not callable(current_profile):
        raise RuntimeUnavailable('HOST_PROFILE_UNAVAILABLE')
    settings_path = pathlib.Path(root) / 'settings.toml'
    def settings_bytes():
        try:
            value = settings_path.read_bytes()
            if len(value) > 8 * 1024 * 1024:
                raise ValueError('bounded policy required')
            return value
        except (OSError, ValueError):
            raise RuntimeUnavailable('HOST_POLICY_UNAVAILABLE') from None
    initial_settings = settings_bytes()
    try:
        if tomllib.loads(initial_settings.decode('utf-8-sig')) != agent.cfg:
            raise ValueError('agent policy snapshot differs from settings')
    except (ValueError, UnicodeError):
        raise RuntimeUnavailable('HOST_POLICY_CHANGED') from None
    settings_digest = hashlib.sha256(initial_settings).digest()
    del initial_settings
    _capability(agent, provider, model, 'image/png', 1)
    _qualified_role(agent, provider, model)
    expected_profile = copy.deepcopy(current_profile())
    expected_account = _configuration(agent, provider)
    def verify_current():
        if (hashlib.sha256(settings_bytes()).digest() != settings_digest or
                current_profile() != expected_profile or
                _configuration(agent, provider) != expected_account):
            raise RuntimeUnavailable('HOST_PROFILE_CHANGED')
        _capability(agent, provider, model, 'image/png', 1)
        _qualified_role(agent, provider, model)
    principal = 'user-' + hashlib.sha256(actor.encode()).hexdigest()[:32]
    tenant = 'fleet-' + hashlib.sha256(os.path.realpath(home).encode()).hexdigest()[:32]
    def factory(shared, current):
        def context():
            current()
            verify_current()
            profile = copy.deepcopy(current_profile())
            if not isinstance(profile, dict) or set(profile) != {
                    'profile_revision', 'purpose', 'retention_policy_id', 'budget_policy_id',
                    'budget_reservation_id', 'budget_ceiling_usd', 'provider_models'}:
                raise RuntimeUnavailable('HOST_PROFILE_UNAVAILABLE')
            if profile['provider_models'] != {provider: model}:
                raise RuntimeUnavailable('HOST_PROFILE_UNAVAILABLE')
            return {**profile, 'user_id': principal, 'tenant_id': tenant,
                    'project_id': slug, 'actor_id': actor}
        authority = SourceApprovalAuthority(home, root, slug, context,
            clock_ms=windows_monotonic_ms, instance_id='runtime-' + secrets.token_hex(16))
        profile = context()
        binding = shared.bind_host(principal, tenant, profile['profile_revision'],
            'source-approval-required', 'unqualified', ['learning:read', 'session:write'], ['capture.selected'])
        host = NativeTutorHost(TutorService(enabled=True), authority.owner_state,
            shared.adapter('native_companion', binding), source_authority=authority)
        host.install_image_provider(ImageProviderRoute(agent, provider=provider, model=model,
            current_grant_view=authority.grant_view, current_budget_view=authority.budget_view))
        return host
    factory.verify_current = verify_current
    return factory


def configure_from_host_file(home, config_path):
    """Explicit local CLI configuration, with no default provider or launch."""
    from loop import Agent
    path = os.path.realpath(config_path)
    def read():
        with open(path, encoding='utf-8') as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or set(value) != {
                'expert', 'device_actor', 'native_executable', 'provider', 'model', 'source_profile'}:
            raise RuntimeUnavailable('HOST_CONFIGURATION_UNAVAILABLE')
        return value
    config = read()
    runtime = FleetTutorRuntime(home)
    root = runtime._root(config['expert'])
    native = VerifiedNativeExecutable.from_host(config['native_executable'])
    agent = Agent(root)
    fixed = {k: v for k, v in config.items() if k != 'source_profile'}
    def profile():
        current = read()
        if {k: v for k, v in current.items() if k != 'source_profile'} != fixed:
            raise RuntimeUnavailable('HOST_CONFIGURATION_CHANGED')
        return current['source_profile']
    factory = source_host_factory(home, config['expert'], config['device_actor'], agent,
        provider=config['provider'], model=config['model'], current_profile=profile)
    # Validate the complete profile before exposing Available. No source,
    # approval, native child, image export or HTTP call is created here.
    host = factory(runtime.learning, lambda: None)
    host.stop()
    runtime.install(config['expert'], device_actor=config['device_actor'], native=native, host_factory=factory)
    return runtime


@dataclass(frozen=True)
class _Installation:
    root: str
    device_actor: str
    native: VerifiedNativeExecutable
    factory: object


class FleetTutorRuntime:
    def __init__(self, home):
        self.home = os.path.realpath(home)
        self.learning = LearningService()
        self._installed, self._active = {}, {}
        self._gate = threading.RLock()
        self._closed = False

    def _root(self, slug):
        if not isinstance(slug, str) or not re.fullmatch('[a-z0-9-]+', slug):
            raise RuntimeUnavailable('PROJECT_UNAVAILABLE')
        root = os.path.realpath(os.path.join(self.home, 'experts', slug))
        if (not os.path.isdir(root) or os.path.dirname(root) !=
                os.path.realpath(os.path.join(self.home, 'experts'))):
            raise RuntimeUnavailable('PROJECT_UNAVAILABLE')
        return root

    def install(self, slug, *, device_actor, native, host_factory):
        """Explicit device ownership and current host profile; never a route body."""
        if (not isinstance(native, VerifiedNativeExecutable) or not callable(host_factory)
                or not isinstance(device_actor, str) or not device_actor):
            raise RuntimeUnavailable('HOST_CONFIGURATION_UNAVAILABLE')
        native.verify()
        root = self._root(slug)
        org.check(self.home, device_actor, 'run', slug)
        with self._gate:
            if self._closed or slug in self._active:
                raise RuntimeUnavailable('RUNTIME_BUSY')
            self._installed[slug] = _Installation(root, device_actor, native, host_factory)

    def _admit(self, slug, actor, proof):
        if not callable(proof) or proof() != actor:
            raise RuntimeUnavailable('AUTHENTICATION_CHANGED')
        try:
            org.check(self.home, actor, 'run', slug)
        except org.Denied as error:
            raise RuntimeUnavailable('ACTOR_REFUSED') from error
        root = self._root(slug)
        with self._gate:
            if self._closed:
                raise RuntimeUnavailable('RUNTIME_CLOSED')
            installation = self._installed.get(slug)
        if installation is None:
            raise RuntimeUnavailable('HOST_CONFIGURATION_UNAVAILABLE')
        if installation.device_actor != actor:
            raise RuntimeUnavailable('DEVICE_ACTOR_UNAVAILABLE')
        if installation.root != root:
            raise RuntimeUnavailable('PROJECT_CHANGED')
        installation.native.verify()
        verify_profile = getattr(installation.factory, 'verify_current', None)
        if callable(verify_profile):
            verify_profile()
        return installation

    def status(self, slug, actor, proof):
        try:
            self._admit(slug, actor, proof)
        except Exception as error:
            code = str(error) if isinstance(error, RuntimeUnavailable) else 'HOST_CONFIGURATION_UNAVAILABLE'
            return {'state': 'UNAVAILABLE', 'reason_code': code, 'running': False}
        with self._gate:
            entry = self._active.get(slug)
            running = entry is not None and entry['actor'] == actor and not entry['stop'].is_set()
            state = 'RUNNING' if running else 'AVAILABLE'
            if running and entry['host'] is None:
                state = 'LAUNCHING'
        return {'state': state, 'reason_code': 'CURRENT' if running else 'HOST_CONFIGURED',
                'running': running, 'return_path': '/#agent/' + slug + '/ov',
                'learning_service': 'learning.v1', 'learning_outcome': 'unqualified'}

    def approval_state(self, slug, approval_id):
        """Read-only projection of the original live runtime's exact attempt.

        An approver can differ from the device member; callers still enforce
        their own approval permission. No callback runs under the registry lock.
        """
        retired = 'RETIRED_OR_UNAVAILABLE'
        with self._gate:
            entry = self._active.get(slug)
            if self._closed or entry is None or entry['stop'].is_set():
                return retired
            host, current = entry['host'], entry.get('current')
        if host is None or current is None:
            return retired
        try:
            current()
            authority = host._source_authority
            from tutor_authority import SourceApprovalAuthority
            if not isinstance(authority, SourceApprovalAuthority):
                return retired
            view = authority.current_approval()
            if view is None or view['approval_id'] != approval_id:
                return retired
            connection = host._connection
            if connection is None or not connection.ready:
                return retired
            current()
            if not authority.matches_current(view):
                return retired
            with self._gate:
                if self._active.get(slug) is not entry or entry['stop'].is_set():
                    return retired
            return 'CURRENT_PENDING' if view['status'] == 'pending' else 'CURRENT_APPROVED'
        except Exception:
            return retired

    def withdraw_approval(self, slug, approval_id):
        """Trusted existing approver route; revoke current view, never rewrite grant."""
        if self.approval_state(slug, approval_id) != 'CURRENT_APPROVED':
            return False
        with self._gate:
            entry = self._active.get(slug)
            if entry is None or entry['stop'].is_set():
                return False
            host = entry['host']
        if host is None:
            return False
        # Retire only a matching source. The existing host supervision sends
        # revocation and clears capture/held answers; no registry/host lock is
        # held while taking the authority lock.
        return host._source_authority.retire_approval(approval_id)

    def decide_approval(self, slug, approval_id, grant, note, approver_current):
        import approvals
        from tutor_authority import SourceApprovalRequired
        with self._gate:
            entry = self._active.get(slug)
        if entry is None or entry['stop'].is_set() or entry['host'] is None:
            raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id)
        authority = entry['host']._source_authority
        def before_commit():
            approver_current()
            try:entry['current']()
            except RuntimeUnavailable:
                raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id) from None
            with self._gate:
                if self._active.get(slug) is not entry or entry['stop'].is_set():
                    raise SourceApprovalRequired('SOURCE_APPROVAL_UNAVAILABLE', approval_id)
        def guard(record):
            return authority.decision_guard(approval_id, record, before_commit=before_commit)
        return approvals.decide(self._root(slug), approval_id, grant, note, commit_guard=guard)

    def current_approval_record(self, slug):
        import approvals
        with self._gate:
            entry = self._active.get(slug)
        if entry is None or entry['stop'].is_set() or entry['host'] is None:
            return None
        try:
            view = entry['host']._source_authority.current_approval()
            if view is None or self.approval_state(slug, view['approval_id']) == 'RETIRED_OR_UNAVAILABLE':
                return None
            return approvals.load(self._root(slug), view['approval_id'])
        except Exception:
            return None

    def launch(self, slug, actor, proof):
        installation = self._admit(slug, actor, proof)
        entry = {'actor': actor, 'stop': threading.Event(), 'host': None, 'threads': []}
        with self._gate:
            if self._closed or slug in self._active:
                raise RuntimeUnavailable('RUNTIME_BUSY')
            self._active[slug] = entry
        def current():
            if entry['stop'].is_set() or self._admit(slug, actor, proof) is not installation:
                raise RuntimeUnavailable('RUNTIME_RETIRED')
        entry['current'] = current
        try:
            host = installation.factory(self.learning, current)
            if (not isinstance(host, NativeTutorHost) or host._learning_service is not self.learning
                    or host._project != slug or host._service.dispatch is None):
                raise RuntimeUnavailable('HOST_PROFILE_UNAVAILABLE')
            with self._gate:
                entry['host'] = host
            current()
            result = host.launch(installation.native, timeout_ms=5000)
            if isinstance(result, dict):
                raise RuntimeUnavailable('NATIVE_UNAVAILABLE')
            current()
            def serve():
                try:
                    host.run(stop_event=entry['stop'])
                except Exception:
                    # The bridge can close during Stop or native exit. Retire
                    # all authority either way; never expose credential errors.
                    entry['reason_code'] = 'NATIVE_CONNECTION_CLOSED'
                finally:
                    self._retire(slug, entry)
            def watch():
                while not entry['stop'].wait(.1):
                    try:
                        current()
                        host._current()
                    except Exception:
                        self._retire(slug, entry)
                        return
            for function in (serve, watch):
                worker = threading.Thread(target=function, daemon=True, name='fleet-tutor-' + slug)
                entry['threads'].append(worker)
                worker.start()
            return self.status(slug, actor, proof)
        except Exception:
            self._retire(slug, entry)
            raise

    def _retire(self, slug, entry):
        entry['stop'].set()
        if entry['host'] is not None:
            entry['host'].stop()
        with self._gate:
            if self._active.get(slug) is entry:
                self._active.pop(slug)

    def stop(self, slug, actor, proof):
        # Stopping one's existing session is allowed after profile drift; it
        # still requires current authentication and run permission.
        if not callable(proof) or proof() != actor:
            raise RuntimeUnavailable('AUTHENTICATION_CHANGED')
        org.check(self.home, actor, 'run', slug)
        with self._gate:
            entry = self._active.get(slug)
            if entry is not None and entry['actor'] != actor:
                raise RuntimeUnavailable('DEVICE_ACTOR_UNAVAILABLE')
        if entry is not None:
            self._retire(slug, entry)
        return {'state': 'STOPPED', 'running': False, 'return_path': '/#agent/' + slug + '/ov'}

    def close(self):
        with self._gate:
            self._closed = True
            entries = list(self._active.items())
        for slug, entry in entries:
            self._retire(slug, entry)
        for _, entry in entries:
            for worker in entry['threads']:
                if worker is not threading.current_thread():
                    worker.join(timeout=1)
