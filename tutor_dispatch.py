"""Host-installed native source/grant/budget adapter over the metered image gateway."""
import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass, field, KW_ONLY

import tutor_contracts as contracts
import tutor_gateway as gateway
import tutor_transport as wire


def _fingerprint(cfg, root, output_cap, provider, credential):
    material={'provider':cfg.get('providers',{}).get(provider),'roles':cfg.get('roles',{}),
              'root':os.path.realpath(root),'output_cap':output_cap,
              'resolved_credential_digest':hashlib.sha256(credential.encode('utf-8')).hexdigest()}
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).digest()


def _configuration(agent, provider):
    return _fingerprint(agent.cfg,agent.root,agent.max_output_tokens,provider,
                        agent._api_key(agent.provider_cfg(provider)))


def _snapshot_agent(agent, provider, expected):
    """Pin the account and output cap actually used, preserving original Fleet core."""
    import credentials
    root=agent.root
    cfg=copy.deepcopy(agent.cfg)
    original_cap=agent.max_output_tokens
    prov=cfg['providers'][provider]
    credential=credentials.resolve(prov,root)
    if _fingerprint(cfg,root,original_cap,provider,credential)!=expected:
        raise gateway.GatewayRefused('PROVIDER_UNAVAILABLE','dispatch policy changed before its snapshot')
    effective_cap=original_cap if original_cap>0 else prov.get('tutor_default_max_output_tokens')
    if type(effective_cap) is not int or not 1<=effective_cap<=1_000_000:
        raise gateway.GatewayRefused('ACCOUNTING_UNKNOWN','bounded output cap required')
    snapshot=copy.copy(agent)
    snapshot.root=root
    snapshot.cfg=cfg
    snapshot.max_output_tokens=effective_cap
    # The existing single credential resolver now reads the approved literal,
    # so later environment/file changes cannot choose another attempt's account.
    prov.pop('api_key_env',None)
    prov.pop('api_key_file',None)
    prov['api_key']=credential
    return snapshot


@dataclass(frozen=True, slots=True)
class ImageProviderRoute:
    agent: object
    _: KW_ONLY
    provider: str
    model: str
    current_grant_view: object
    current_budget_view: object
    _config: bytes = field(init=False,repr=False)

    def __post_init__(self):
        from loop import Agent
        if not isinstance(self.agent,Agent):
            raise gateway.GatewayRefused('PROVIDER_UNAVAILABLE','host-owned Fleet Agent required')
        gateway._ident(self.provider,'provider');gateway._model_name(self.model)
        if not callable(self.current_grant_view) or not callable(self.current_budget_view):
            raise gateway.GatewayRefused('AUTHORITY_UNAVAILABLE','current host grant and budget readers required')
        object.__setattr__(self,'_config',_configuration(self.agent,self.provider))

    def dispatch(self,request,observations,*,store,current_owner,current_binding,_release_checks=None):
        if not isinstance(store,gateway.EphemeralImageStore) or not callable(current_owner) or not callable(current_binding):
            raise gateway.GatewayRefused('AUTHORITY_UNAVAILABLE','current host observation dependencies required')
        if request.get('mode') not in ('EXPLAIN','GUIDE') or request.get('research_scope')!='SOURCE_ONLY':
            raise gateway.GatewayRefused('REFUSE_MODE_ACTION','image explanation route does not grant research or actions')
        if not isinstance(observations,list) or len(observations)!=1:
            raise gateway.GatewayRefused('STALE_SOURCE','exactly one admitted observation required')
        observation=copy.deepcopy(observations[0]);request=copy.deepcopy(request)
        if request['observation_ids']!=[observation['observation_id']] or request['source_ids']!=[observation['source_id']]:
            raise gateway.GatewayRefused('STALE_SOURCE','request and observation disagree')
        frozen_authority=None
        def authority():
            owner=copy.deepcopy(current_owner())
            grant=copy.deepcopy(self.current_grant_view(owner))
            budget=copy.deepcopy(self.current_budget_view(owner))
            if not contracts.authorize_tutor_request(request,owner)['allowed'] or not contracts.validate_observation(observation,owner)['allowed']:
                raise gateway.GatewayRefused('STALE_SOURCE','current request/observation authority refused')
            if not contracts.validate_session_grant_view(grant,owner)['allowed']:
                raise gateway.GatewayRefused('REFUSE_PERMISSION','current SessionGrantView refused')
            for name in ('session_id','user_id','tenant_id','project_id','consent_revision','cancellation_generation'):
                if grant[name]!=request[name] or name!='cancellation_generation' and observation[name]!=request[name]:
                    raise gateway.GatewayRefused('REFUSE_CONTEXT_ACCESS','grant/request/observation scope mismatch')
            if (self.provider not in grant['provider_destinations']
                or not set(contracts.MODE_CAPABILITIES[request['mode']]).issubset(grant['capabilities'])
                or observation['source_id'] not in grant['source_ids']
                or grant['retention_policy_id']!=request['retention_policy_id']
                or observation['retention_policy_id']!=request['retention_policy_id']):
                raise gateway.GatewayRefused('REFUSE_PERMISSION','destination/source/capability/retention not authorized')
            contracts._record(budget,('budget_policy_id','budget_reservation_id','ceiling_usd','agent_root'))
            if (budget['budget_policy_id']!=grant['budget_policy_id']
                or budget['budget_reservation_id']!=request['budget_reservation_id']
                or os.path.realpath(budget['agent_root'])!=os.path.realpath(self.agent.root)):
                raise gateway.GatewayRefused('REFUSE_PERMISSION','current budget policy does not belong to this dispatch')
            ceiling=gateway._finite(budget['ceiling_usd'],'ceiling_usd',0.000001)
            if _configuration(self.agent,self.provider)!=self._config:
                raise gateway.GatewayRefused('PROVIDER_UNAVAILABLE','installed provider/account configuration changed')
            binding=current_binding()
            for name in ('source_id','source_revision','capture_epoch'):
                if binding[name]!=observation[name]:
                    raise gateway.GatewayRefused('STALE_SOURCE','current capture identity changed')
            if frozen_authority is not None and (grant,budget)!=frozen_authority:
                raise gateway.GatewayRefused('REFUSE_PERMISSION','current grant or budget changed during dispatch')
            return owner,grant,budget,ceiling,{**binding,'content_sha256':observation['content_sha256']}
        owner,grant,budget,ceiling,binding=authority()
        frozen_authority=(copy.deepcopy(grant),copy.deepcopy(budget))
        # Never convert a Windows absolute timestamp into the gateway clock.
        # Take the local clock first, then measure the remaining original lease.
        gateway_now=time.monotonic_ns()//1_000_000
        original_deadline=min(request['deadline_monotonic_ms'],observation['expires_at_monotonic_ms'],grant['expires_at_monotonic_ms'])
        try:
            dispatch_deadline=wire.gateway_deadline(original_deadline,bridge_now_ms=wire.windows_monotonic_ms(),gateway_now_ms=gateway_now)
        except wire.TransportRefusal as error:
            raise gateway.GatewayRefused('DEADLINE_EXPIRED','original image grant/request expired') from error
        def current_image_binding():return authority()[-1]
        def cancelled():
            try:authority();return False
            except (ValueError,RuntimeError,contracts.ContractViolation):return True
        dispatch_agent=_snapshot_agent(self.agent,self.provider,self._config)
        result=gateway.ask_image(dispatch_agent,store,{'request_id':request['request_id'],'session_id':request['session_id'],
            'source_id':observation['source_id'],'source_revision':observation['source_revision'],
            'capture_epoch':observation['capture_epoch'],'question':request['question'],'image_ref':observation['artifact_ref'],
            'provider':self.provider,'model':self.model,'budget_ceiling_usd':ceiling,
            'deadline_monotonic_ms':dispatch_deadline},current_image_binding,cancelled)
        authority()
        answer=result['answer']
        if result['uncertainty']:answer+='\n\nUncertainty: '+result['uncertainty']
        instruction={'schema':'fleet.tutor.instruction.v1','request_id':request['request_id'],'move':'EXPLAIN',
            'answer':answer,'claims':[],'annotations':[],'requested_response':'No response required.','reveal_level':'DIRECT',
            'expected_progress':{'kind':'EXPLANATION_AVAILABLE','scope':'Current selected source; learning outcome unverified'},'execution_request':None}
        verdict=contracts.validate_instruction(instruction,observation,{'mode':request['mode'],'request_id':request['request_id'],
            'cancellation_generation':request['cancellation_generation'],'current_cancellation_generation':request['cancellation_generation']})
        if not verdict['allowed']:raise gateway.GatewayRefused('MALFORMED_PROVIDER_RESPONSE','image result exceeds instruction contract')
        if _release_checks is not None:
            def release_current():
                try:
                    authority()
                    return True
                except (ValueError, RuntimeError, contracts.ContractViolation):
                    return False
            _release_checks.append(release_current)
        return instruction
