#!/usr/bin/env python3
"""Source-bound unfamiliar-app explanations, using existing host authorities.

The host supplies current identity, app/version, generation and permissions.
Quoted documentation is source-relative evidence, not independently established
truth or an instruction to execute. This boundary neither creates grants nor
calls a model, controls an app or certifies learner competence. Its separate
host-policy adapters acquire bounded documents and create disposable examples;
provider paraphrases and real-app sample execution still need qualification.
No adapter invents a target or treats a mechanical example as human learning.
"""
import copy
import hashlib
import json
import re
from collections import OrderedDict

import tutor_contracts
import tutor_sources

MAX_SOURCES = 8
MAX_TEXT = 6000
MAX_CLAIMS = 17
MAX_ISSUED = 32
IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
SCOPE_FIELDS = ('tenant_id', 'project_id', 'app_id', 'app_version', 'cancellation_generation')
REFERENCE_FIELDS = ('source_id', 'revision', 'excerpt_id', 'tenant_id', 'project_id', 'content_sha256')
ANSWER_FIELDS = frozenset(('schema', 'status', 'question', 'question_kind', 'scope',
    'app', 'claims', 'source_map', 'limits', 'next_evidence', 'targets', 'actions',
    'pack_required', 'sample_status', 'learning_success_claimed'))

class InvestigationRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f'{code}: {detail}')

def _refuse(code, detail):
    raise InvestigationRefused(code, detail)

def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()

def _texts(values):
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 4:
        _refuse('INVALID_INPUT', 'reports/hypotheses must be bounded lists')
    if any(not isinstance(x, str) or not x.strip() or len(x) > 512 for x in values):
        _refuse('INVALID_INPUT', 'report or hypothesis is invalid')
    return values

class Investigation:
    """A host-owned, read-only source explanation and revalidation boundary."""
    def __init__(self, home, current_state):
        if not callable(current_state):
            _refuse('INVALID_INPUT', 'a current host-state reader is required')
        self.home = home
        self.current_state = current_state
        self._issued = OrderedDict()

    def _scope(self):
        state = copy.deepcopy(self.current_state())
        if not isinstance(state, dict) or any(k not in state for k in SCOPE_FIELDS):
            _refuse('INVALID_CONTEXT', 'host app and identity scope are required')
        for key in ('tenant_id', 'project_id', 'app_id'):
            if not isinstance(state[key], str) or not IDENT.fullmatch(state[key]):
                _refuse('INVALID_CONTEXT', 'invalid '+key)
        try:
            tutor_sources.parse_version(state['app_version'])
        except tutor_sources.SourceRefused as exc:
            _refuse(exc.code, str(exc))
        generation = state['cancellation_generation']
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            _refuse('INVALID_CONTEXT', 'invalid generation')
        grants = state.get('grant_view')
        if not isinstance(grants, list) or 'explain' not in grants:
            _refuse('PERMISSION_DENIED', 'current host scope does not permit explanation')
        return {key: state[key] for key in SCOPE_FIELDS}

    def _source(self, reference, scope):
        if not isinstance(reference, dict) or set(reference) != set(REFERENCE_FIELDS):
            _refuse('INVALID_CITATION', 'citation requires exact source identity and byte digest')
        if any(reference[k] != scope[k] for k in ('tenant_id', 'project_id')):
            _refuse('SCOPE_DENIED', 'citation is outside current caller scope')
        if not isinstance(reference['content_sha256'], str) or not SHA.fullmatch(reference['content_sha256']):
            _refuse('INVALID_CITATION', 'invalid excerpt digest')
        try:
            status = tutor_sources.source_reference_status(
                self.home, {k: reference[k] for k in REFERENCE_FIELDS if k != 'content_sha256'})
        except tutor_sources.SourceRefused as exc:
            _refuse(exc.code, str(exc))
        if not status['ok']:
            _refuse('MISSING_SOURCE' if status['code'] == 'SOURCE_UNAVAILABLE' else status['code'],
                    'the exact teaching source is unavailable')
        if status['excerpt_sha256'] != reference['content_sha256']:
            _refuse('CITATION_MISMATCH', 'citation bytes do not match the registered excerpt')
        record = status['record']
        if record['app_id'] != scope['app_id']:
            _refuse('APP_MISMATCH', 'documentation names another application')
        version = tutor_sources.parse_version(scope['app_version'])
        low = tutor_sources.parse_version(record['app_versions']['min'])
        high = tutor_sources.parse_version(record['app_versions']['max'])
        if not low <= version <= high:
            return None, {'source_id': reference['source_id'],
                          'reason': 'APP_VERSION_OUTSIDE_SOURCE_RANGE',
                          'supported_versions': copy.deepcopy(record['app_versions'])}
        text = next(e['text'] for e in record['excerpts'] if e['excerpt_id'] == reference['excerpt_id'])
        return {'citation': copy.deepcopy(reference), 'text': text,
                'title': record['title'], 'locator': record['locator'],
                'app_versions': copy.deepcopy(record['app_versions']),
                'source_type': record['source_type'], 'license_id': record['rights']['license_id'],
                'content_is_instruction': False}, None

    def explain(self, question, *, references=None, reports=None, hypotheses=None,
                observation=None, observation_state=None):
        scope = self._scope()
        if not isinstance(question, str) or not question.strip() or len(question) > 512:
            _refuse('INVALID_INPUT', 'question must contain 1..512 characters')
        reports, hypotheses = _texts(reports), _texts(hypotheses)
        limits, source_map, claims = [], [], []
        if references is None:
            try:
                found = tutor_sources.retrieve(self.home, tenant_id=scope['tenant_id'],
                    project_id=scope['project_id'], query=question,
                    app_id=scope['app_id'], app_version=scope['app_version'],
                    limit=MAX_SOURCES, max_chars=MAX_TEXT)
            except tutor_sources.SourceRefused as exc:
                _refuse('MISSING_SOURCE' if exc.code == 'SOURCE_UNAVAILABLE' else exc.code,
                        'current scoped teaching sources are unavailable')
            references = [dict(source_id=r['source']['source_id'], revision=r['source']['revision'],
                excerpt_id=r['source']['excerpt_id'], tenant_id=scope['tenant_id'],
                project_id=scope['project_id'], content_sha256=hashlib.sha256(r['content'].encode()).hexdigest())
                for r in found['results']]
            limits.extend(found['scope_limits'])
            if found['status'] != 'OK':
                limits.append({'reason': found['status']})
        if not isinstance(references, list) or len(references) > MAX_SOURCES:
            _refuse('INVALID_INPUT', 'too many source references')
        used, seen = 0, set()
        for ref in references:
            source, limit = self._source(ref, scope)
            if limit:
                limits.append(limit)
                continue
            identity = _digest(ref)
            if identity in seen:
                continue
            seen.add(identity)
            if used + len(source['text']) > MAX_TEXT:
                limits.append({'reason': 'SOURCE_TEXT_BUDGET', 'source_id': ref['source_id']})
                continue
            used += len(source['text'])
            source_map.append({**{k: v for k, v in source.items() if k not in ('text', 'citation')}, **ref})
            claims.append({'kind': 'documentation_claim', 'text': source['text'],
                           'citation': copy.deepcopy(ref), 'support': 'EXACT_QUOTE_ONLY'})
        observed = None
        if observation is not None:
            if not isinstance(observation_state, dict) or any(
                    observation_state.get(k) != scope[k] for k in ('tenant_id', 'project_id')):
                _refuse('SCOPE_DENIED', 'selected observation belongs to another caller scope')
            verdict = tutor_contracts.validate_observation(observation, observation_state)
            if not verdict['allowed']:
                _refuse(verdict['reason_code'], verdict.get('detail', 'observation refused'))
            if observation_state.get('current_cancellation_generation') != scope['cancellation_generation']:
                _refuse('STALE_CONTEXT', 'observation and host cancellation generation differ')
            observed = {'kind': 'observed_fact', 'observation_id': observation['observation_id'],
                        'text': 'Selected observation source: '+observation['source_id']+'.',
                        'source_id': observation['source_id'],
                        'source_revision': observation['source_revision'],
                        'capture_epoch': observation['capture_epoch']}
            claims.insert(0, observed)
        claims += [{'kind': 'user_report', 'text': x, 'verified': False} for x in reports]
        claims += [{'kind': 'hypothesis', 'text': x, 'verified': False} for x in hypotheses]
        if not source_map:
            limits.append({'reason': 'NO_VERSION_MATCHED_DOCUMENTATION',
                           'detail': 'No exact permitted teaching source supports an application instruction.'})
        prefix = question.strip().lower()
        kind = ('target' if prefix.startswith('where') else
                'procedure' if prefix.startswith('how') else
                'explanation' if prefix.startswith('why') else 'concept')
        answer = {'schema': 'tutor.investigation/1', 'status': 'SOURCE_SUPPORTED' if source_map else 'LIMITED',
                  'question': question, 'question_kind': kind, 'scope': scope,
                  'app': {'id': scope['app_id'], 'version': scope['app_version']},
                  'claims': claims, 'source_map': source_map, 'limits': limits,
                  'next_evidence': [] if source_map else ['Provide permitted official documentation for the exact installed app version or a current selected-source observation.'],
                  'targets': [], 'actions': [], 'pack_required': False,
                  'sample_status': 'NO_QUALIFIED_REVERSIBLE_SAMPLE', 'learning_success_claimed': False}
        if self._scope() != scope:
            _refuse('STALE_CONTEXT', 'scope changed before the answer was released')
        self._issued[_digest(answer)] = copy.deepcopy(observed)
        while len(self._issued) > MAX_ISSUED:
            self._issued.popitem(last=False)
        return answer

    def verify(self, answer):
        scope = self._scope()
        if (not isinstance(answer, dict) or set(answer) != ANSWER_FIELDS
                or answer.get('schema') != 'tutor.investigation/1'
                or answer.get('learning_success_claimed') is not False
                or answer.get('pack_required') is not False
                or answer.get('sample_status') != 'NO_QUALIFIED_REVERSIBLE_SAMPLE'):
            _refuse('INVALID_ANSWER', 'unsupported answer record')
        try:
            size = len(json.dumps(answer, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError):
            _refuse('INVALID_ANSWER', 'answer is not finite bounded JSON')
        if size > 64 * 1024:
            _refuse('INVALID_ANSWER', 'answer exceeds the byte ceiling')
        if answer.get('scope') != scope or answer.get('app') != {'id': scope['app_id'], 'version': scope['app_version']}:
            _refuse('STALE_CONTEXT', 'answer no longer matches the host app, identity or generation')
        if answer.get('targets') != [] or answer.get('actions') != []:
            _refuse('UNSUPPORTED_TARGET', 'documentation cannot authorize or locate application actions')
        claims = answer.get('claims')
        if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
            _refuse('INVALID_ANSWER', 'invalid claim list')
        expected_map = []
        for claim in claims:
            if not isinstance(claim, dict):
                _refuse('INVALID_ANSWER', 'invalid claim')
            kind = claim.get('kind')
            if kind == 'documentation_claim':
                if (set(claim) != {'kind', 'text', 'citation', 'support'}
                        or claim.get('support') != 'EXACT_QUOTE_ONLY'):
                    _refuse('UNSUPPORTED_CLAIM', 'documentation support may not be promoted beyond its exact quote')
                source, limit = self._source(claim.get('citation'), scope)
                if limit:
                    _refuse('STALE_CONTEXT', 'cited source is outside the current app version')
                if claim.get('text') != source['text']:
                    _refuse('UNSUPPORTED_CLAIM', 'claim differs from its exact source quote')
                expected_map.append({**{k: v for k, v in source.items() if k not in ('text', 'citation')},
                                     **claim['citation']})
            elif kind == 'observed_fact':
                if self._issued.get(_digest(answer)) != claim:
                    _refuse('UNSUPPORTED_CLAIM', 'observation claim was not issued by this current host boundary')
            else:
                if (kind not in ('user_report', 'hypothesis') or set(claim) != {'kind', 'text', 'verified'}
                        or claim.get('verified') is not False):
                    _refuse('UNSUPPORTED_CLAIM', 'reports and hypotheses cannot become verified facts')
                _texts([claim['text']])
        if answer.get('source_map') != expected_map:
            _refuse('CITATION_MISMATCH', 'displayed source map does not match current exact citation evidence')
        if answer['status'] != ('SOURCE_SUPPORTED' if expected_map else 'LIMITED'):
            _refuse('INVALID_ANSWER', 'answer status contradicts its source support')
        if self._scope() != scope:
            _refuse('STALE_CONTEXT', 'scope changed during citation verification')
        return {'allowed': True, 'support': 'EXACT_SOURCE_AND_HOST_BINDING_ONLY',
                'task_success_claimed': False, 'learning_success_claimed': False}


class SourceAcquisition:
    """Acquire only host-selected documents; retrieved instructions are inert.

    Policy is a current host-owned recipe map, never a request-body field.
    Each recipe binds scope, exact locator/redirects, source type, version and
    rights. An optional pin refuses changed raw bytes; unpinned documents get a
    new digest-derived immutable revision. Only the approved line range enters
    teaching retrieval. Neither downloaded bytes nor arbitrary URLs grant access.
    """
    MAX_BYTES = 128 * 1024
    MAX_POLICY_BYTES = 64 * 1024
    RECIPE_FIELDS = frozenset(('kind', 'locator', 'allowed_redirects',
        'expected_sha256', 'format', 'record', 'range', 'excerpt_id'))
    RECORD_FIELDS = frozenset(('schema', 'source_id', 'tenant_id', 'project_id',
        'title', 'source_type', 'locator', 'app_id', 'app_versions', 'rights', 'purpose'))

    def __init__(self, home, current_state, current_policy):
        if not callable(current_policy):
            _refuse('INVALID_INPUT', 'a current host-policy reader is required')
        self.home = home
        self.context = Investigation(home, current_state)
        self.current_policy = current_policy

    def _authorization(self, key):
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            _refuse('ACQUISITION_DENIED', 'a host-selected document key is required')
        scope = self.context._scope()
        state = self.context.current_state()
        if not isinstance(state, dict) or state.get('document_acquisition_permitted') is not True:
            _refuse('PERMISSION_DENIED', 'document acquisition is not currently permitted')
        try:
            encoded = json.dumps(self.current_policy(), sort_keys=True,
                                 separators=(',', ':'), allow_nan=False)
            if len(encoded.encode()) > self.MAX_POLICY_BYTES:
                _refuse('ACQUISITION_DENIED', 'host document policy exceeds bounds')
            policy = json.loads(encoded)
        except (TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, InvestigationRefused):
                raise
            _refuse('ACQUISITION_DENIED', 'invalid host document policy')
        if (not isinstance(policy, dict) or set(policy) != {'scope', 'recipes'}
                or policy['scope'] != scope or not isinstance(policy['recipes'], dict)
                or not 1 <= len(policy['recipes']) <= 32 or key not in policy['recipes']):
            _refuse('ACQUISITION_DENIED', 'no current host authorization for this document')
        recipe = policy['recipes'][key]
        if not isinstance(recipe, dict) or set(recipe) != self.RECIPE_FIELDS:
            _refuse('ACQUISITION_DENIED', 'invalid document recipe')
        if recipe['kind'] not in ('local', 'url') or recipe['format'] not in ('text', 'html'):
            _refuse('UNSUPPORTED_SOURCE', 'this document needs a qualified format adapter')
        if (not isinstance(recipe['locator'], str) or not recipe['locator']
                or len(recipe['locator']) > 2048):
            _refuse('ACQUISITION_DENIED', 'invalid document locator')
        redirects = recipe['allowed_redirects']
        if (not isinstance(redirects, list) or len(redirects) > 5
                or any(not isinstance(x, str) or len(x) > 2048 for x in redirects)
                or recipe['kind'] == 'local' and redirects):
            _refuse('ACQUISITION_DENIED', 'invalid exact redirect allowlist')
        pin = recipe['expected_sha256']
        if pin is not None and (not isinstance(pin, str) or not SHA.fullmatch(pin)):
            _refuse('ACQUISITION_DENIED', 'invalid source pin')
        rec = recipe['record']
        if (not isinstance(rec, dict) or set(rec) != self.RECORD_FIELDS
                or rec['locator'] != recipe['locator']
                or any(rec[k] != scope[k] for k in ('tenant_id', 'project_id', 'app_id'))):
            _refuse('SCOPE_DENIED', 'document metadata does not match the current scope')
        if rec['purpose'] != 'teaching':
            _refuse('ASSESSMENT_HIDDEN', 'assessment material cannot enter investigation')
        try:
            versions = rec['app_versions']
            version = tutor_sources.parse_version(scope['app_version'])
            if not tutor_sources.parse_version(versions['min']) <= version <= tutor_sources.parse_version(versions['max']):
                _refuse('VERSION_MISMATCH', 'document is not approved for the current app version')
            # Validate rights, ranges and metadata before any file/network read.
            self._record(recipe, '0' * 64, 'preflight validation')
        except (KeyError, TypeError, tutor_sources.SourceRefused):
            _refuse('ACQUISITION_DENIED', 'invalid source rights/version/line-range metadata')
        return scope, recipe, _digest(policy)

    def _record(self, recipe, digest, text):
        rec = copy.deepcopy(recipe['record'])
        line_range = recipe['range']
        if (not isinstance(line_range, dict) or set(line_range) != {'start', 'end'}
                or any(isinstance(line_range[k], bool) or not isinstance(line_range[k], int)
                       for k in ('start', 'end'))
                or not 1 <= line_range['start'] <= line_range['end'] <= self.MAX_BYTES):
            _refuse('ACQUISITION_DENIED', 'invalid document line range')
        rec['revision'] = digest
        rec['excerpts'] = [{'excerpt_id': recipe['excerpt_id'], **line_range,
            'text': text, 'source_revision': digest, 'tenant_id': rec['tenant_id'],
            'project_id': rec['project_id'], 'license_id': rec['rights']['license_id'],
            'purpose': 'teaching'}]
        return tutor_sources._validate(rec)

    def _read_local(self, locator):
        import fileauth
        try:
            path = fileauth.resolve(self.home, locator, actor='agent')
            with open(path, 'rb') as stream:
                raw = stream.read(self.MAX_BYTES + 1)
            if fileauth.resolve(self.home, locator, actor='agent') != path:
                _refuse('SOURCE_CHANGED', 'document path changed while reading')
            return raw
        except (OSError, fileauth.Denied):
            _refuse('SOURCE_ACCESS_DENIED', 'selected local document is unavailable or prohibited')

    def _read_url(self, recipe, check_current):
        import ingest
        import urllib.parse
        import urllib.request
        allowed = [recipe['locator']] + recipe['allowed_redirects']
        def check_url(url):
            check_current()
            if url not in allowed:
                _refuse('ACQUISITION_DENIED', 'effective document URL is not host-approved')
            try:
                parsed = urllib.parse.urlsplit(url)
                if parsed.username is not None or parsed.password is not None or parsed.fragment:
                    _refuse('SOURCE_ACCESS_DENIED', 'credential-bearing or fragment URLs are unsupported')
                ingest._check_scheme(url)
                ingest._check_host(url, self.home)
            except ValueError as exc:
                if isinstance(exc, InvestigationRefused):
                    raise
                _refuse('SOURCE_ACCESS_DENIED', 'document network destination is prohibited')
        class Redirects(urllib.request.HTTPRedirectHandler):
            hops = 0
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                self.hops += 1
                if self.hops > 5:
                    _refuse('ACQUISITION_DENIED', 'document redirect limit exceeded')
                check_url(newurl)
                return super().redirect_request(req, fp, code, msg, headers, newurl)
        check_url(recipe['locator'])
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
        request = urllib.request.Request(recipe['locator'], headers={'Accept': 'text/plain,text/html',
            'User-Agent': 'ScreenTutor-documents/1'}, method='GET')
        try:
            with opener.open(request, timeout=10) as response:
                effective = response.geturl()
                check_url(effective)
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    _refuse('UNSUPPORTED_SOURCE', 'encoded document needs a qualified adapter')
                content_type = response.headers.get_content_type()
                expected = ('text/html',) if recipe['format'] == 'html' else ('text/plain', 'text/markdown')
                if content_type not in expected:
                    _refuse('UNSUPPORTED_SOURCE', 'document content type disagrees with its approved format')
                return response.read(self.MAX_BYTES + 1), effective
        except InvestigationRefused:
            raise
        except (OSError, ValueError):
            _refuse('SOURCE_UNAVAILABLE', 'approved document could not be fetched')

    def acquire(self, key):
        scope, recipe, policy_digest = self._authorization(key)
        def check_current():
            current_scope, current_recipe, current_digest = self._authorization(key)
            if current_scope != scope or current_digest != policy_digest or current_recipe != recipe:
                _refuse('STALE_CONTEXT', 'document authority changed during acquisition')
        if recipe['kind'] == 'local':
            raw, effective = self._read_local(recipe['locator']), recipe['locator']
        else:
            raw, effective = self._read_url(recipe, check_current)
        check_current()
        if not raw or len(raw) > self.MAX_BYTES:
            _refuse('SOURCE_TOO_LARGE', 'document is empty or exceeds acquisition bounds')
        digest = hashlib.sha256(raw).hexdigest()
        if recipe['expected_sha256'] is not None and recipe['expected_sha256'] != digest:
            _refuse('SOURCE_CHANGED', 'document bytes disagree with the owner pin')
        try:
            text = raw.decode('utf-8', errors='strict')
        except UnicodeError:
            _refuse('UNSUPPORTED_SOURCE', 'document requires an explicit non-UTF-8 adapter')
        if recipe['format'] == 'html':
            import ingest
            text = ingest.html_to_text(text)
        lines = text.splitlines()
        line_range = recipe['range']
        if line_range['end'] > len(lines):
            _refuse('SOURCE_CHANGED', 'approved line range is not present in document')
        excerpt = '\n'.join(lines[line_range['start'] - 1:line_range['end']])
        try:
            record = self._record(recipe, digest, excerpt)
            check_current()
            registered = tutor_sources.register_source(self.home, record)
        except tutor_sources.SourceRefused as exc:
            _refuse(exc.code, 'acquired source cannot be adopted')
        check_current()
        reference = {'source_id': record['source_id'], 'revision': digest,
            'excerpt_id': recipe['excerpt_id'], 'tenant_id': scope['tenant_id'],
            'project_id': scope['project_id'], 'content_sha256': hashlib.sha256(excerpt.encode()).hexdigest()}
        return {'reference': reference, 'raw_sha256': digest, 'effective_locator': effective,
                'registry_digest': registered['digest'], 'policy_digest': policy_digest,
                'scope': scope, 'content_is_instruction': False, 'provider_or_content_qualified': False}


class ReversibleSamples:
    """Source-bound examples in disposable copies, never production app inputs.

    Answer keys, source bytes, rights and paths come only from current host
    policy. Callers receive opaque handles, not editable verifier sessions.
    Existing practice mechanisms check/reset artifacts; a passing example is
    neither a qualified pack nor independent learner success.
    """
    MAX_HANDLES = 32

    def __init__(self, investigator, current_policy):
        if not isinstance(investigator, Investigation) or not callable(current_policy):
            _refuse('INVALID_INPUT', 'host-owned investigation and sample policy are required')
        self.investigator = investigator
        self.current_policy = current_policy
        self._handles = {}
        self._stopped = OrderedDict()

    def _authorization(self, key):
        if not isinstance(key, str) or not IDENT.fullmatch(key):
            _refuse('SAMPLE_DENIED', 'a host-selected sample key is required')
        scope = self.investigator._scope()
        state = self.investigator.current_state()
        if not isinstance(state, dict) or state.get('sample_practice_permitted') is not True:
            _refuse('PERMISSION_DENIED', 'practice is not currently permitted')
        user_id = state.get('user_id')
        if not isinstance(user_id, str) or not IDENT.fullmatch(user_id):
            _refuse('SAMPLE_DENIED', 'sample requires current user identity')
        scope = {**scope, 'user_id': user_id}
        try:
            encoded = json.dumps(self.current_policy(), sort_keys=True,
                                 separators=(',', ':'), allow_nan=False)
            if len(encoded.encode()) > SourceAcquisition.MAX_POLICY_BYTES:
                _refuse('SAMPLE_DENIED', 'sample policy exceeds bounds')
            policy = json.loads(encoded)
        except (ValueError, TypeError, RecursionError) as exc:
            if isinstance(exc, InvestigationRefused):
                raise
            _refuse('SAMPLE_DENIED', 'invalid host sample policy')
        if (not isinstance(policy, dict) or set(policy) != {'scope', 'samples'}
                or policy['scope'] != scope or not isinstance(policy['samples'], dict)
                or not 1 <= len(policy['samples']) <= 32 or key not in policy['samples']):
            _refuse('SAMPLE_DENIED', 'no current host authorization for this sample')
        recipe = policy['samples'][key]
        if not isinstance(recipe, dict) or set(recipe) != {'citation', 'source', 'specification'}:
            _refuse('SAMPLE_DENIED', 'invalid sample recipe')
        import tutor_practice
        try:
            source = tutor_practice._source(recipe['source'])
            spec = tutor_practice._spec(recipe['specification'])
        except tutor_practice.PracticeRefused as exc:
            _refuse(exc.code, 'host sample recipe is not safe')
        except (TypeError, KeyError, ValueError):
            _refuse('SAMPLE_DENIED', 'malformed host sample recipe')
        if any(spec[k] != scope[k] for k in ('user_id', 'project_id')):
            _refuse('SAMPLE_DENIED', 'sample does not belong to this user/project')
        # Open-world examples are assisted, mechanically checked samples. Hidden
        # assessment and independent pack qualification remain separate gates.
        if spec['mode'] not in ('WORKED', 'PARTIAL') or spec['verifier'] != 'CANONICAL_JSON_EQUALS':
            _refuse('SAMPLE_DENIED', 'this route only supports assisted deterministic examples')
        documentation, limit = self.investigator._source(recipe['citation'], scope)
        if documentation is None or limit:
            _refuse('VERSION_MISMATCH', 'sample documentation does not support this app version')
        return scope, recipe, _digest(policy)

    def _check(self, entry):
        scope, recipe, policy_digest = self._authorization(entry['key'])
        if (scope != entry['scope'] or recipe != entry['recipe']
                or policy_digest != entry['policy_digest']):
            _refuse('STALE_CONTEXT', 'sample authority or answer key changed')
        self.investigator.verify(entry['answer'])

    def _entry(self, handle):
        if isinstance(handle, str) and handle in self._stopped:
            _refuse('PRACTICE_STOPPED', 'sample was stopped locally')
        if not isinstance(handle, str) or handle not in self._handles:
            _refuse('SAMPLE_DENIED', 'unknown host sample handle')
        entry = self._handles[handle]
        self._check(entry)
        return entry

    def validate(self, handle):
        """Revalidate current sample authority without reading/changing artifacts."""
        self._entry(handle)
        return {'allowed': True}

    def create(self, answer, key):
        import tutor_practice
        import uuid
        self.investigator.verify(answer)
        scope, recipe, policy_digest = self._authorization(key)
        if (answer['status'] != 'SOURCE_SUPPORTED'
                or not any({k: item[k] for k in REFERENCE_FIELDS} == recipe['citation']
                           for item in answer['source_map'])):
            _refuse('SAMPLE_DENIED', 'sample is not supported by this explanation source')
        if len(self._handles) >= self.MAX_HANDLES:
            _refuse('SAMPLE_DENIED', 'sample handle capacity reached')
        entry = {'scope': scope, 'key': key, 'recipe': recipe,
                 'policy_digest': policy_digest, 'answer': copy.deepcopy(answer)}
        self._check(entry)
        # The original policy ID is never an overwrite destination. Every copy
        # gets a private unique workspace ID, including across tenant namespaces.
        spec = copy.deepcopy(recipe['specification'])
        spec['practice_id'] = 'investigation-' + uuid.uuid4().hex
        try:
            session = tutor_practice.create_practice_copy(self.investigator.home,
                                                         recipe['source'], spec)
        except tutor_practice.PracticeRefused as exc:
            _refuse(exc.code, 'safe sample copy could not be created')
        self._check(entry)
        handle = uuid.uuid4().hex
        entry['session'] = session
        self._handles[handle] = entry
        return {'handle': handle, 'artifact_ref': session['artifact_ref'],
                'reversible': True, 'qualified_pack': False,
                'sample_status': 'READY_ASSISTED_EXAMPLE',
                'learning_success_claimed': False, 'independent_success_claimed': False}

    def verify(self, handle):
        import tutor_practice
        entry = self._entry(handle)
        try:
            result = tutor_practice.verify_practice(self.investigator.home, entry['session'])
        except tutor_practice.PracticeRefused as exc:
            _refuse(exc.code, 'sample verification refused')
        self._check(entry)
        return {**result, 'qualified_pack': False,
                'learning_success_claimed': False, 'independent_success_claimed': False}

    def reset(self, handle):
        import tutor_practice
        entry = self._entry(handle)
        try:
            entry['session'] = tutor_practice.reset_practice(self.investigator.home, entry['session'])
        except tutor_practice.PracticeRefused as exc:
            _refuse(exc.code, 'sample reset refused')
        self._check(entry)
        return {'reset': True, 'artifact_ref': entry['session']['artifact_ref'],
                'learning_success_claimed': False}

    def stop(self, handle):
        import tutor_practice
        # Local stop remains available even when explanation/practice authority
        # is revoked. It does not touch an artifact or source.
        if isinstance(handle, str) and handle in self._stopped:
            return {'stopped': True}
        if not isinstance(handle, str) or handle not in self._handles:
            _refuse('SAMPLE_DENIED', 'unknown host sample handle')
        entry = self._handles[handle]
        entry['session'] = tutor_practice.stop_practice(entry['session'])
        del self._handles[handle]
        self._stopped[handle] = None
        if len(self._stopped) > self.MAX_HANDLES:
            self._stopped.popitem(last=False)
        return {'stopped': True}
