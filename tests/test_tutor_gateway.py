#!/usr/bin/env python3
"""SC-1B: qualified image transport, source binding and exact-once spend."""

import io
import json
import os
import struct
import sys
import tempfile
import time
import zlib

from common import AGENT_DIR
from fake_provider import FakeProvider

sys.path.insert(0, AGENT_DIR)
import context  # noqa: E402
import loop  # noqa: E402
import modelgateway  # noqa: E402
import tutor_gateway as G  # noqa: E402


def png(width=2, height=2):
    def chunk(kind, value):
        body = kind + value
        return struct.pack(">I", len(value)) + body + struct.pack(">I", zlib.crc32(body))
    rows = b"".join(b"\x00" + b"\xff\xff\xff\xff" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def settings(root, server, *, capable=True, accounting=True, priced=True):
    lines = [
        "[agent]", 'sandbox = "host"', "allow_unsafe_host = true",
        "model_timeout_seconds = 3", "max_output_tokens = 32",
        "context_safety_margin = 16", "context_tool_schema_budget = 0",
        "", "[providers.vision]", f'base_url = "{server.base_url}"',
        'api_key = "test-only"', "context_limit = 8192",
    ]
    if capable:
        lines += ["tutor_image_enabled = true",
                  'tutor_image_models = ["vision-model"]',
                  'tutor_image_formats = ["image/png"]',
                  "tutor_image_input_units_per_megapixel = 1000000",
                  "tutor_default_max_output_tokens = 32"]
    if accounting:
        lines.append('tutor_usage_accounting = "prompt_tokens_includes_images"')
    if priced:
        lines += ["input_per_mtok = 2.0", "output_per_mtok = 10.0"]
    lines += ["", "[roles.tutor]", 'provider = "vision"',
              'model = "vision-model"', "tools = []"]
    with io.open(os.path.join(root, "settings.toml"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def binding(revision="revision-1", epoch=1):
    return {"source_id": "source-1", "source_revision": revision,
            "capture_epoch": epoch}


def request(image_ref, *, request_id="request-1", ceiling=1.0):
    return {"request_id": request_id, "session_id": "session-1",
            **binding(), "question": "Which control should I use?",
            "image_ref": image_ref, "provider": "vision", "model": "vision-model",
            "budget_ceiling_usd": ceiling,
            "deadline_monotonic_ms": time.monotonic_ns() // 1_000_000 + 20_000}


def answer(revision="revision-1", epoch=1):
    return json.dumps({"answer": "Use the visible Save control.",
                       "uncertainty": "The control is visible, but no click was executed.",
                       "source_id": "source-1", "source_revision": revision,
                       "capture_epoch": epoch})


def stored(store, revision="revision-1", epoch=1, raw=None):
    return store.put(raw or png(), "image/png", "source-1", revision, epoch,
                     time.monotonic_ns() // 1_000_000 + 20_000)


def spend(root):
    return modelgateway._read_spend(modelgateway.spend_file(root))


def refused(code, operation):
    try:
        operation()
    except G.GatewayRefused as exc:
        assert exc.code == code, (exc.code, str(exc))
    else:
        raise AssertionError(f"expected {code}")


def check_ordinary_routes_and_references_refuse(root, server):
    settings(root, server)
    agent = loop.Agent(root)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "hello"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
    ]}]
    try:
        context.assert_request_budget(agent.cfg, "vision", "vision-model", messages, 32)
    except context.ContextBudgetError as exc:
        assert "provider-specific" in str(exc)
    else:
        raise AssertionError("ordinary model route accepted multimodal content")
    store = G.EphemeralImageStore()
    refused("INVALID_IMAGE_REFERENCE", lambda: G.ask_image(
        agent, store, request("https://attacker.invalid/image.png"), binding))
    refused("INVALID_IMAGE_REFERENCE", lambda: G.ask_image(
        agent, store, request("C:\\private\\screen.png", request_id="request-2"), binding))
    assert server.requests == [], "a rejected reference reached a provider or URL resolver"
    print("[T017 T018] ordinary models reject image parts; remote URLs and paths cannot enter the qualified image route")


def check_capability_bounds_and_reservation_precede_dispatch(root, server):
    settings(root, server, capable=False)
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    refused("IMAGE_CAPABILITY_MISSING", lambda: G.ask_image(
        agent, store, request(stored(store)), binding))
    assert server.requests == []

    settings(root, server, accounting=False)
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    refused("ACCOUNTING_UNKNOWN", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-3"), binding))
    assert server.requests == []

    settings(root, server, priced=False)
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    refused("ACCOUNTING_UNKNOWN", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-4"), binding))
    assert server.requests == []

    settings(root, server)
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    refused("IMAGE_TOO_LARGE", lambda: stored(
        store, raw=(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
                    + struct.pack(">II", 9000, 2) + b"\x08\x06\x00\x00\x00")))
    ref = stored(store)
    try:
        G.ask_image(agent, store, request(ref, request_id="request-5", ceiling=0.000001), binding)
    except PermissionError:
        pass
    else:
        raise AssertionError("an over-ceiling reservation reached dispatch")
    assert server.requests == []
    print("[T019 X004B] missing capability, accounting, price, oversized media and over-budget reservations all stop before dispatch")


def check_successful_real_adapter_and_exact_once_spend(root, server):
    settings(root, server)
    server.reply(text=answer(), usage={"prompt_tokens": 100,
                                      "completion_tokens": 20,
                                      "total_tokens": 120})
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    result = G.ask_image(agent, store, request(stored(store), request_id="request-6"), binding)
    assert result["answer"] == "Use the visible Save control."
    assert result["image_count"] == 1 and result["image_pixels"] == 4
    assert result["image_input_units"] == 4 and result["text_prompt_tokens"] == 96
    assert result["cost_usd"] == 0.0004, result
    payload = server.last["payload"]
    assert payload["model"] == "vision-model" and "tools" not in payload
    assert payload["messages"][0]["role"] == "system"
    assert "untrusted material" in payload["messages"][0]["content"]
    parts = payload["messages"][1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    state = spend(root)
    assert state["usd"] == 0.0004, state
    settled = state["reservations"][result["reservation_id"]]
    assert settled["status"] == "SETTLED" and settled["outcome"] == "USAGE_RECONCILED"
    prior = dict(settled)
    modelgateway.reconcile_reserved_charge(root, result["reservation_id"], 99.0,
                                           "DUPLICATE_MUST_NOT_APPLY")
    assert spend(root)["usd"] == 0.0004
    assert spend(root)["reservations"][result["reservation_id"]] == prior
    store2 = G.EphemeralImageStore()
    refused("DUPLICATE_DISPATCH", lambda: G.ask_image(
        agent, store2, request(stored(store2), request_id="request-6"), binding))
    assert len(server.requests) == 1, "settled request identity dispatched twice"
    rows = modelgateway.calls(root, task="session-1")
    assert rows and rows[-1]["purpose"] == "tutor" and rows[-1]["provider"] == "vision"
    print("[X004A X004B] the actual HTTP adapter carried one bounded data image; provider usage replaced one reservation exactly once")


def check_late_cancelled_and_malformed_results_do_not_render(root, server):
    settings(root, server)
    agent = loop.Agent(root)

    server.reply(text=answer())
    store = G.EphemeralImageStore()
    moving = lambda: binding("revision-2") if server.requests else binding()
    refused("STALE_SOURCE", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-7"), moving))

    server.requests.clear(); server.reply(text=answer())
    store = G.EphemeralImageStore()
    cancelled = lambda: bool(server.requests)
    refused("CANCELLED_OR_LATE", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-8"), binding,
        cancelled=cancelled))

    server.requests.clear(); server.reply(text="not strict JSON")
    store = G.EphemeralImageStore()
    refused("MALFORMED_PROVIDER_RESPONSE", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-9"), binding))

    server.requests.clear()
    body = server._body(text=answer())
    body["usage"] = {}
    server.script.append(body)
    store = G.EphemeralImageStore()
    before = spend(root)["usd"]
    refused("ACCOUNTING_MISSING", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-10"), binding))
    state = spend(root)
    rec = state["reservations"]["tutor_request-10"]
    assert rec["outcome"] == "USAGE_UNKNOWN_CONSERVATIVE"
    assert state["usd"] > before, "unknown provider usage released a potentially paid call"
    print("[T020] stale, cancelled, malformed and unmetered provider results produce no qualified answer; unknown usage settles conservatively")


def check_rate_limit_uses_actual_dispatch_adapter(root, server):
    settings(root, server)
    server.fail(429, retry_after=1).reply(text=answer())
    agent = loop.Agent(root); store = G.EphemeralImageStore()
    slept, original = [], time.sleep
    time.sleep = lambda seconds: slept.append(seconds)
    try:
        result = G.ask_image(agent, store,
                             request(stored(store), request_id="request-11"), binding)
    finally:
        time.sleep = original
    assert result["answer"] and len(server.requests) == 2
    assert slept and 1 <= slept[0] <= 1.25, slept
    server.requests.clear(); server.fail_next.clear(); server.script.clear()
    server.fail(429, retry_after=1)
    store = G.EphemeralImageStore()
    refused("CANCELLED", lambda: G.ask_image(
        agent, store, request(stored(store), request_id="request-12"), binding,
        cancelled=lambda: bool(server.requests)))
    assert len(server.requests) == 1, "cancelled request continued its retry ladder"
    print("[provider-weather] a loopback 429 retries through the production HTTP adapter under one reservation, and cancellation stops before a second paid attempt")


def check_configured_model_names():
    from tutor_dispatch import ImageProviderRoute
    with tempfile.TemporaryDirectory(prefix='owned-model-name-') as folder:
        server=FakeProvider()
        try:
            settings(folder,server);agent=loop.Agent(folder)
            model='owned.model/v2:variant'
            agent.cfg['providers']['vision']['tutor_image_models']=[model]
            agent.cfg['roles']['tutor']['model']=model
            ImageProviderRoute(agent,provider='vision',model=model,current_grant_view=lambda _:None,current_budget_view=lambda _:None)
            server.reply(text=answer(),usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
            store=G.EphemeralImageStore();call=request(stored(store),request_id='configured-model-name-1');call['model']=model
            result=G.ask_image(agent,store,call,binding)
            assert result['model']==model and server.requests[0]['payload']['model']==model
            for invalid in ('','bad model','model\nheader','../path',None,123,'m'*257):
                try:G._model_name(invalid)
                except G.GatewayRefused:pass
                else:raise AssertionError('invalid configured model name admitted')
            refused('INVALID_REQUEST',lambda:G._ident('provider/name','provider'))
        finally:
            server.stop()
            logger=__import__('logging').getLogger(f'agent:{folder}')
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
    print('[configured model name] declared dotted/namespaced/colon name accepted as data; resource identifiers unchanged')


def check_digest_bound_store():
    store=G.EphemeralImageStore()
    reference=stored(store)
    held=next(iter(store._items.values()))['bytes']
    refused('STALE_SOURCE',lambda:store.take(reference,{**binding(),'content_sha256':'0'*64}))
    assert not any(held), 'digest-mismatched PNG bytes survived refusal'
    print('[exact observation image] source identity alone cannot substitute a different PNG digest; refusal consumes and wipes bytes')


def check_external_credential_pin(kind, phase='before'):
    import copy
    from pathlib import Path
    from unittest.mock import patch
    from test_tutor_host import fixture
    from tutor_dispatch import ImageProviderRoute
    import tutor_contracts as contracts
    import threading
    key_env='OWNED_TUTOR_REVIEW_KEY'
    with tempfile.TemporaryDirectory(prefix='owned-route-credential-') as folder:
        server=FakeProvider()
        try:
            settings(folder,server);agent=loop.Agent(folder)
            _,request,observation,_,owner=fixture()
            grant=copy.deepcopy(contracts.fixture_bundle()['records']['grant_view'])
            grant['cancellation_generation']=request['cancellation_generation'];grant['provider_destinations']=['vision']
            policy={'budget_policy_id':'budget-policy-1','budget_reservation_id':'budget-1','ceiling_usd':1.0,'agent_root':folder}
            provider=agent.cfg['providers']['vision'];provider.pop('api_key')
            if kind in ('env','agent-env'):provider['api_key_env']=key_env
            else:provider['api_key_file']='owned-key.txt'
            path=Path(folder)/('agent.env' if kind=='agent-env' else 'owned-key.txt')
            with patch.dict(os.environ,{key_env:'owned-first'} if kind=='env' else {},clear=False):
                if kind!='env':
                    os.environ.pop(key_env,None)
                    path.write_text(key_env+'=owned-first' if kind=='agent-env' else 'owned-first',encoding='utf-8')
                route=ImageProviderRoute(agent,provider='vision',model='vision-model',current_grant_view=lambda _:copy.deepcopy(grant),current_budget_view=lambda _:copy.deepcopy(policy))
                store=G.EphemeralImageStore();raw=png();observation['artifact_ref']=store.put(raw,'image/png',observation['source_id'],observation['source_revision'],observation['capture_epoch'],time.monotonic_ns()//1_000_000+5000)
                observation['content_sha256']=__import__('hashlib').sha256(raw).hexdigest();owner['artifact_refs']=[observation['artifact_ref']]
                def replace_credential():
                    if kind=='env':os.environ[key_env]='owned-replaced'
                    else:path.write_text(key_env+'=owned-replaced' if kind=='agent-env' else 'owned-replaced',encoding='utf-8')
                worker=None
                if phase=='before':replace_credential()
                else:
                    server.fail(429,retry_after=1)
                    def replace_after_first_attempt():
                        limit=time.monotonic()+2
                        while not server.requests and time.monotonic()<limit:time.sleep(.005)
                        replace_credential()
                    worker=threading.Thread(target=replace_after_first_attempt);worker.start()
                binding={name:observation[name] for name in ['source_id','source_revision','capture_epoch']}
                server.reply(text=json.dumps({'answer':'must not export through changed account','uncertainty':'synthetic fixture','source_id':observation['source_id'],'source_revision':observation['source_revision'],'capture_epoch':observation['capture_epoch']}),usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
                with patch('tutor_transport.windows_monotonic_ms',return_value=2000):
                    try:route.dispatch(request,[observation],store=store,current_owner=lambda:copy.deepcopy(owner),current_binding=lambda:copy.deepcopy(binding))
                    except G.GatewayRefused:pass
                    else:raise AssertionError('changed '+kind+' resolved credential exported pixels')
                if worker is not None:worker.join(2)
                assert len(server.requests)==(1 if phase=='retry' else 0)
                assert all(record['headers']['authorization']=='Bearer owned-first' for record in server.requests), 'HTTP used an account other than the approved snapshot'
        finally:
            server.stop()
            logger=__import__('logging').getLogger(f'agent:{folder}')
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
    print('[resolved account pin] '+kind+' '+phase+' replacement refused; only approved snapshot account can leave')


def check_output_cap_review(kind):
    import copy
    import threading
    from unittest.mock import patch
    from test_tutor_host import fixture
    from tutor_dispatch import ImageProviderRoute
    import tutor_contracts as contracts
    with tempfile.TemporaryDirectory(prefix='owned-output-cap-') as folder:
        server=FakeProvider()
        try:
            settings(folder,server);agent=loop.Agent(folder)
            _,request,observation,_,owner=fixture()
            grant=copy.deepcopy(contracts.fixture_bundle()['records']['grant_view']);grant['cancellation_generation']=request['cancellation_generation'];grant['provider_destinations']=['vision']
            policy={'budget_policy_id':'budget-policy-1','budget_reservation_id':'budget-1','ceiling_usd':1.0,'agent_root':folder}
            route=ImageProviderRoute(agent,provider='vision',model='vision-model',current_grant_view=lambda _:copy.deepcopy(grant),current_budget_view=lambda _:copy.deepcopy(policy))
            store=G.EphemeralImageStore();raw=png();observation['artifact_ref']=store.put(raw,'image/png',observation['source_id'],observation['source_revision'],observation['capture_epoch'],time.monotonic_ns()//1_000_000+5000)
            observation['content_sha256']=__import__('hashlib').sha256(raw).hexdigest();owner['artifact_refs']=[observation['artifact_ref']]
            binding={name:observation[name] for name in ['source_id','source_revision','capture_epoch']}
            server.reply(text=json.dumps({'answer':'output must stay hidden after cap change','uncertainty':'owned fixture','source_id':observation['source_id'],'source_revision':observation['source_revision'],'capture_epoch':observation['capture_epoch']}),usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
            reserve=modelgateway.reserve_charge
            def mutate_after_reservation(*args,**kwargs):
                result=reserve(*args,**kwargs);agent.max_output_tokens=128;return result
            worker=None
            if kind=='retry':
                server.fail(429,retry_after=1)
                def change_cap():
                    limit=time.monotonic()+2
                    while not server.requests and time.monotonic()<limit:time.sleep(.005)
                    agent.max_output_tokens=128
                worker=threading.Thread(target=change_cap);worker.start()
            with patch('tutor_transport.windows_monotonic_ms',return_value=2000), patch.object(modelgateway,'reserve_charge',side_effect=mutate_after_reservation if kind=='reserved' else reserve):
                try:route.dispatch(request,[observation],store=store,current_owner=lambda:copy.deepcopy(owner),current_binding=lambda:copy.deepcopy(binding))
                except G.GatewayRefused:pass
                else:raise AssertionError('changed output cap was not refused')
            if worker is not None:worker.join(2)
            assert len(server.requests)==(1 if kind=='retry' else 0), 'larger unreserved request reached provider'
            assert all(record['payload']['max_tokens']==32 for record in server.requests)
        finally:
            server.stop()
            logger=__import__('logging').getLogger(f'agent:{folder}')
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)
    print('[output cap binding] '+kind+' mutation refuses; no larger or extra request')


def check_host_installed_image_route():
    import copy
    import hashlib
    import threading
    from pathlib import Path
    from unittest.mock import patch
    from test_tutor_host import fixture
    from tutor_dispatch import ImageProviderRoute
    import tutor_contracts as contracts
    import tutor_gateway as gateway
    with tempfile.TemporaryDirectory(prefix='owned-tutor-route-') as folder:
        server=FakeProvider()
        try:
            settings(folder,server);agent=loop.Agent(folder)
            session,request,observation,instruction,owner=fixture()
            grant=copy.deepcopy(contracts.fixture_bundle()['records']['grant_view'])
            grant['cancellation_generation']=request['cancellation_generation'];grant['provider_destinations']=['vision']
            budget={'budget_policy_id':grant['budget_policy_id'],'budget_reservation_id':request['budget_reservation_id'],'ceiling_usd':1.0,'agent_root':folder}
            store=gateway.EphemeralImageStore();raw=png();ref=store.put(raw,'image/png',observation['source_id'],observation['source_revision'],observation['capture_epoch'],time.monotonic_ns()//1_000_000+5000)
            observation['artifact_ref']=ref;observation['content_sha256']=hashlib.sha256(raw).hexdigest();owner['artifact_refs']=[ref]
            server.reply(text=json.dumps({'answer':'Owned visible explanation','uncertainty':'Unverified instructional quality; no action taken','source_id':observation['source_id'],'source_revision':observation['source_revision'],'capture_epoch':observation['capture_epoch']}),usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
            route=ImageProviderRoute(agent,provider='vision',model='vision-model',current_grant_view=lambda _:copy.deepcopy(grant),current_budget_view=lambda _:copy.deepcopy(budget))
            binding={name:observation[name] for name in ['source_id','source_revision','capture_epoch']}
            from tutor_host import NativeTutorHost
            from tutor_service import TutorService,TutorUnavailable
            from learning_contracts import LearningService
            learning=LearningService()
            learning_binding=learning.bind_host('user-1','tenant-1','policy-1','grant-1','course-1',
                ['learning:read','session:write'],['capture.selected'])
            host=NativeTutorHost(TutorService(enabled=True),lambda:copy.deepcopy(owner),learning.adapter('native_companion',learning_binding))
            try:
                host.install_image_provider(object())
            except TutorUnavailable:pass
            else:raise AssertionError('untyped provider install admitted')
            host.install_image_provider(route)
            try:
                host.install_image_provider(route)
            except TutorUnavailable:pass
            else:raise AssertionError('provider replaced after installation')
            host._images.close();host._images=store
            host._session=session;host._observations[observation['observation_id']]=copy.deepcopy(observation)
            host._capture_authorization={**binding,'session_id':session.session_id,
                'consent_revision':owner['consent_revision'],'cancellation_generation':session.cancellation_generation,
                'now_monotonic_ms':2000,'expires_at_monotonic_ms':9000}
            wire_checks=[]
            with patch('tutor_transport.windows_monotonic_ms',return_value=2000):
                hosted=host.ask_observed({'request_id':'host-provider-question','observation_id':observation['observation_id'],
                    'question':'Explain this owned image','learning_intent':'UNDERSTAND','locale':'en-CA'},deadline_ms=8000,_release_checks=wire_checks)
            assert hosted['allowed'] and not hosted['grant_created'] and not hosted['learning_success_claimed']
            output=hosted['instruction']
            assert output['answer']=='Owned visible explanation\n\nUncertainty: Unverified instructional quality; no action taken'
            assert output['claims']==[] and output['execution_request'] is None and output['requested_response']=='No response required.'
            assert spend(folder)['usd']==.0004 and len(server.requests)==1
            assert wire_checks and all(check() for check in wire_checks)
            budget['ceiling_usd']=.5
            assert not all(check() for check in wire_checks), 'changed provider budget released an already returned answer'
            budget['ceiling_usd']=1.0
            original_grant=copy.deepcopy(grant);original_budget=copy.deepcopy(budget)
            checks=[('destination',lambda:grant.update(provider_destinations=[])),
                    ('tenant',lambda:grant.update(tenant_id='foreign-tenant')),
                    ('session',lambda:grant.update(session_id='foreign-session')),
                    ('retention',lambda:grant.update(retention_policy_id='foreign-retention')),
                    ('expiry',lambda:grant.update(expires_at_monotonic_ms=1000)),
                    ('capability',lambda:grant.update(capabilities=['observe'])),
                    ('source',lambda:grant.update(source_ids=[])),
                    ('budget-policy',lambda:budget.update(budget_policy_id='foreign-budget')),
                    ('budget-reservation',lambda:budget.update(budget_reservation_id='foreign-reservation')),
                    ('budget-ceiling',lambda:budget.update(ceiling_usd=0)),
                    ('agent-root',lambda:budget.update(agent_root=str(Path(folder)/'foreign-agent')))]
            for name,mutate in checks:
                grant.clear();grant.update(copy.deepcopy(original_grant));budget.clear();budget.update(copy.deepcopy(original_budget))
                mutate()
                with patch('tutor_transport.windows_monotonic_ms',return_value=2000):
                    try:route.dispatch(request,[observation],store=store,current_owner=lambda:copy.deepcopy(owner),current_binding=lambda:copy.deepcopy(binding))
                    except gateway.GatewayRefused:pass
                    else:raise AssertionError('admitted '+name)
                assert len(server.requests)==1,'negative exported unauthorized pixels: '+name
            grant.clear();grant.update(original_grant);budget.clear();budget.update(original_budget)
            configured=agent.cfg['providers']['vision']['base_url'];agent.cfg['providers']['vision']['base_url']='http://127.0.0.1:1/changed'
            with patch('tutor_transport.windows_monotonic_ms',return_value=2000):
                try:route.dispatch(request,[observation],store=store,current_owner=lambda:copy.deepcopy(owner),current_binding=lambda:copy.deepcopy(binding))
                except gateway.GatewayRefused:pass
                else:raise AssertionError('admitted changed destination configuration')
            agent.cfg['providers']['vision']['base_url']=configured
            assert len(server.requests)==1
            delayed_request=copy.deepcopy(request);delayed_request['request_id']='draft-delayed-budget-change'
            delayed_observation=copy.deepcopy(observation)
            delayed_observation['artifact_ref']=store.put(raw,'image/png',observation['source_id'],observation['source_revision'],observation['capture_epoch'],time.monotonic_ns()//1_000_000+5000)
            owner['artifact_refs']=[delayed_observation['artifact_ref']]
            server.delay=.3
            server.reply(text=json.dumps({'answer':'This answer must stay hidden','uncertainty':'Owned fixture only','source_id':observation['source_id'],'source_revision':observation['source_revision'],'capture_epoch':observation['capture_epoch']}),usage={'prompt_tokens':100,'completion_tokens':20,'total_tokens':120})
            outcomes=[]
            def pending():
                try:outcomes.append(route.dispatch(delayed_request,[delayed_observation],store=store,current_owner=lambda:copy.deepcopy(owner),current_binding=lambda:copy.deepcopy(binding)))
                except BaseException as error:outcomes.append(error)
            with patch('tutor_transport.windows_monotonic_ms',return_value=2000):
                worker=threading.Thread(target=pending);worker.start()
                limit=time.monotonic()+2
                while len(server.requests)<2 and time.monotonic()<limit:time.sleep(.005)
                assert len(server.requests)==2,'delayed real provider dispatch never started'
                budget['ceiling_usd']=.5
                worker.join(3)
            assert not worker.is_alive() and len(outcomes)==1 and isinstance(outcomes[0],gateway.GatewayRefused),outcomes
            state=spend(folder);reservation=state['reservations']['tutor_draft-delayed-budget-change']
            assert reservation['status']=='SETTLED' and reservation['outcome']=='USAGE_RECONCILED' and reservation['actual_usd']==.0004,reservation
            assert len(server.requests)==2,'changed authority caused another provider attempt'
            print('[host-qualified image route] authority changed during real HTTP: late answer suppressed and original known usage settled exactly once')
            print('[host-qualified image route] twelve scope/grant/retention/budget/destination negatives: zero unauthorized provider requests')
            print('[host-qualified image route] real loopback gateway source/uncertainty/instruction/accounting connection; local loopback only; no real provider qualification')
        finally:
            if 'host' in locals():host.stop()
            server.stop()
            logger=__import__('logging').getLogger(f'agent:{folder}')
            for handler in list(logger.handlers):handler.close();logger.removeHandler(handler)


def main():
    check_configured_model_names()
    for kind in ('env','agent-env','file'):
        for phase in ('before','retry'):check_external_credential_pin(kind,phase)
    for kind in ('reserved','retry'):check_output_cap_review(kind)
    check_digest_bound_store()
    check_host_installed_image_route()
    with tempfile.TemporaryDirectory(prefix="tutor-gateway-") as root:
        server = FakeProvider()
        try:
            check_ordinary_routes_and_references_refuse(root, server)
            check_capability_bounds_and_reservation_precede_dispatch(root, server)
            check_successful_real_adapter_and_exact_once_spend(root, server)
            server.requests.clear()
            check_late_cancelled_and_malformed_results_do_not_render(root, server)
            server.requests.clear()
            check_rate_limit_uses_actual_dispatch_adapter(root, server)
        finally:
            if 'host' in locals():host.stop()
            server.stop()
            logger = __import__("logging").getLogger(f"agent:{root}")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
    print("PASS test_tutor_gateway")


if __name__ == "__main__":
    main()
