"""Host-installed, data-only teaching scenes bound to current source evidence.

No IO at import, provider call, assessment credit or application input. Local
scenes are explicitly unqualified demonstrations; reviewed content is loaded
only from the existing current pack and visible teaching-source authorities.
"""
import copy
import hashlib
import json

import tutor_canvas
import tutor_contracts as contracts

_INSTALLED = object()
MAX_SCENE_BYTES = 256 * 1024
MAX_LIFETIME_MS = 30_000
BINDING_FIELDS = ('request_id', 'session_id', 'user_id', 'tenant_id', 'project_id',
                  'observation_id', 'source_id', 'source_revision', 'capture_epoch',
                  'geometry_revision', 'content_sha256', 'consent_revision',
                  'cancellation_generation')


class PresentationRefused(ValueError):
    """A teaching presentation has no current host authority."""


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def validate_presentation(value, *, request_id, deadline_ms):
    """Structural/content check only; live source and grant checks are separate."""
    try:
        contracts._record(value, ('schema','binding','expires_at_monotonic_ms',
                                  'qualification','render_model','learning_success_claimed'))
        if (value['schema'] != 'fleet.tutor.presentation.v1'
                or value['qualification'] not in ('LOCAL_ONLY','REVIEWED_PACK')
                or value['learning_success_claimed'] is not False):
            raise PresentationRefused('invalid presentation schema or qualification')
        binding=contracts._record(value['binding'],BINDING_FIELDS)
        for name in BINDING_FIELDS:
            if name in ('capture_epoch','cancellation_generation'):
                contracts._integer(binding[name],name,1 if name=='capture_epoch' else 0)
            elif name=='content_sha256':
                if not isinstance(binding[name],str) or not contracts.SHA256.fullmatch(binding[name]):
                    raise PresentationRefused('invalid presentation source digest')
            else:contracts._ident(binding[name],name)
        expiry=contracts._integer(value['expires_at_monotonic_ms'],'expires_at_monotonic_ms',1)
        if binding['request_id'] != request_id or expiry > deadline_ms:
            raise PresentationRefused('presentation exceeds the answer request binding')
        render=contracts._record(value['render_model'],('schema','status','scene_id','primitives',
            'slider_values','text_alternative','executable_content'))
        if (render['schema']!='tutor.canvas-render/1' or render['status']!='RENDER'
                or render['executable_content'] is not False):
            raise PresentationRefused('invalid closed teaching render model')
        if not isinstance(render['primitives'],list) or not 1<=len(render['primitives'])<=64:
            raise PresentationRefused('teaching primitive count is outside bounds')
        rows=[]
        for row in render['primitives']:
            contracts._record(row,('kind','id','payload'))
            if not isinstance(row['payload'],dict) or set(row['payload']) & {'kind','id'}:
                raise PresentationRefused('invalid teaching primitive payload')
            rows.append({'kind':row['kind'],'id':row['id'],**row['payload']})
        scene=tutor_canvas.validate_scene({'schema':'tutor.scene/1','scene_id':render['scene_id'],
            'concept_id':'presentation','title':'Teaching presentation',
            'text_alternative':render['text_alternative'],'primitives':rows})
        if not isinstance(render['slider_values'],dict):
            raise PresentationRefused('invalid teaching slider state')
        for number in render['slider_values'].values():tutor_canvas._number(number,'slider value')
        expected=tutor_canvas.render_scene(scene,tutor_canvas.start_scene(scene))
        if expected != render or len(_encoded(value)) > MAX_SCENE_BYTES:
            raise PresentationRefused('rendered teaching content does not match its closed scene')
    except (ValueError,TypeError,KeyError,contracts.ContractViolation) as error:
        raise PresentationRefused('closed presentation is invalid') from error
    return value


class TeachingScene:
    def __init__(self, *args, **kwargs):
        raise PresentationRefused('teaching scenes require host installation')

    @classmethod
    def _make(cls, scene, qualification, scope, current_check):
        try:
            if len(_encoded(scene)) > MAX_SCENE_BYTES:
                raise PresentationRefused('teaching scene exceeds the byte bound')
            validated = tutor_canvas.validate_scene(copy.deepcopy(scene))
            for name in ('tenant_id', 'project_id'):
                contracts._ident(scope[name], name)
        except (ValueError, TypeError, KeyError, contracts.ContractViolation) as error:
            raise PresentationRefused('closed teaching scene or scope is invalid') from error
        result = object.__new__(cls)
        result._scene = validated
        result._qualification = qualification
        result._scope = copy.deepcopy(scope)
        result._check = current_check
        result._proof = (_INSTALLED, _digest(validated), qualification,
                         _digest(scope), current_check)
        return result

    @classmethod
    def local_check(cls, scene, *, tenant_id, project_id):
        return cls._make(scene, 'LOCAL_ONLY',
                         {'tenant_id': tenant_id, 'project_id': project_id}, lambda: None)

    @classmethod
    def from_pack(cls, home, pack_id, *, reference):
        import tutor_packs
        import tutor_sources
        from pathlib import Path
        ref = copy.deepcopy(reference)
        try:
            current = tutor_packs.status(home, pack_id)
            if not current.get('assignable') or current.get('review_scope') != 'subject_matter_human':
                raise PresentationRefused('current independent pack qualification is required')
            pack_digest = current['validation']['digest']
            manifest = tutor_packs._read(str(Path(tutor_packs._pack_dir(home, pack_id)) / 'sources.json'))
            if ref not in manifest['references']:
                raise PresentationRefused('scene reference is outside the reviewed teaching sources')
            checked = tutor_sources.source_reference_status(home, ref)
            if not checked.get('ok'):
                raise PresentationRefused('visible teaching source is unavailable')
            source_digest = checked['excerpt_sha256']

            def check():
                latest = tutor_packs.status(home, pack_id)
                source = tutor_sources.source_reference_status(home, ref)
                if (not latest.get('assignable') or latest.get('review_scope') != 'subject_matter_human'
                        or latest['validation']['digest'] != pack_digest or not source.get('ok')
                        or source['excerpt_sha256'] != source_digest):
                    raise PresentationRefused('reviewed teaching content changed or was revoked')

            check()
            raw = tutor_sources.read_excerpt(home, **ref).encode('utf-8')
            if len(raw) > MAX_SCENE_BYTES or hashlib.sha256(raw).hexdigest() != source_digest:
                raise PresentationRefused('loaded teaching scene bytes differ from the approved reference')
            scene = contracts.decode_wire(raw)
            result = cls._make(scene, 'REVIEWED_PACK',
                {'tenant_id': ref['tenant_id'], 'project_id': ref['project_id'],
                 'pack_id': pack_id, 'pack_digest': pack_digest, 'source_digest': source_digest}, check)
            result.verify_current()
            return result
        except (OSError, ValueError, TypeError, KeyError, contracts.ContractViolation) as error:
            raise PresentationRefused('reviewed teaching scene is unavailable') from error

    def verify_current(self):
        try:
            if self._proof != (_INSTALLED, _digest(self._scene), self._qualification,
                               _digest(self._scope), self._check):
                raise PresentationRefused('installed teaching scene identity changed')
            self._check()
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise PresentationRefused('installed teaching scene is unavailable') from error

    def render(self, request, observation, current_owner):
        self.verify_current()
        try:
            if request.get('mode') not in ('EXPLAIN', 'GUIDE') or request.get('learning_intent') != 'LEARN':
                raise PresentationRefused('teaching scenes require the learning explanation route')
            if request.get('output_preferences', {}).get('response_format') != 'TEXT_AND_SCENE':
                raise PresentationRefused('a teaching presentation was not requested')
            if not contracts.authorize_tutor_request(request, current_owner)['allowed']:
                raise PresentationRefused('current teaching request authority is unavailable')
            if not contracts.validate_observation(observation, current_owner)['allowed']:
                raise PresentationRefused('current teaching source is unavailable')
            for name in ('tenant_id', 'project_id'):
                if request[name] != self._scope[name] or observation[name] != self._scope[name]:
                    raise PresentationRefused('teaching scene is outside the current scope')
            for name in ('session_id', 'user_id', 'tenant_id', 'project_id', 'consent_revision'):
                if request[name] != observation[name]:
                    raise PresentationRefused('teaching request and source identities differ')
            if (request['observation_ids'] != [observation['observation_id']]
                    or request['source_ids'] != [observation['source_id']]):
                raise PresentationRefused('teaching scene requires one exact current observation')
            now = contracts._integer(current_owner.get('now_monotonic_ms'), 'now_monotonic_ms')
            expiry = min(request['deadline_monotonic_ms'], observation['expires_at_monotonic_ms'],
                         current_owner['grant_expires_at_monotonic_ms'], now + MAX_LIFETIME_MS)
            if expiry <= now:
                raise PresentationRefused('teaching presentation expired')
            binding = {name: copy.deepcopy(request[name] if name in request else observation[name])
                       for name in BINDING_FIELDS}
            render_model = tutor_canvas.render_scene(self._scene, tutor_canvas.start_scene(self._scene))
            self.verify_current()
            return {'schema': 'fleet.tutor.presentation.v1', 'binding': binding,
                    'expires_at_monotonic_ms': expiry, 'qualification': self._qualification,
                    'render_model': render_model, 'learning_success_claimed': False}
        except (ValueError, TypeError, KeyError, contracts.ContractViolation) as error:
            raise PresentationRefused('current source-bound teaching presentation is unavailable') from error
