#!/usr/bin/env python3
"""SC-0B: strict permissions, cancellation, and cross-language contracts."""

import copy
import json
import os
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import grants  # noqa: E402
import tutor_contracts as T  # noqa: E402


FIXTURE_PATH = os.path.join(AGENT_DIR, "companion", "windows",
                            "contract-probe", "tutor-contracts.v1.json")


def records():
    return copy.deepcopy(T.fixture_bundle()["records"])


def current():
    return {"user_id": "user-1", "tenant_id": "tenant-1", "project_id": "project-1",
            "consent_revision": "consent-r3", "capture_epoch": 7,
            "source_ids": ["source-1"], "source_revisions": {"source-1": "source-r4"},
            "observation_ids": ["obs-1"], "now_monotonic_ms": 2000,
            "artifact_refs": ["artifact-1"], "budget_reservation_ids": ["budget-1"],
            "retention_policy_ids": ["retention-1"],
            "grant_expires_at_monotonic_ms": 9000,
            "cancellation_generation": 4, "current_cancellation_generation": 4,
            "mode": "GUIDE", "actor": "SYSTEM",
            "grant_view": ["observe", "explain", "annotate"],
            "explicit_owner_request": False}


def assert_denied(result, code):
    assert result["allowed"] is False, result
    assert result["reason_code"] == code, result


def check_strict_wire_and_versioning():
    assert T.decode_wire('{"a":1}') == {"a": 1}
    for payload in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
        try:
            T.decode_wire(payload)
        except T.ContractViolation as exc:
            assert exc.code == "INVALID_JSON"
        else:
            raise AssertionError("strict JSON accepted " + payload)
    try:
        T.decode_wire(b"{" + b"x" * T.MAX_WIRE_BYTES)
    except T.ContractViolation as exc:
        assert exc.code == "MESSAGE_TOO_LARGE"
    else:
        raise AssertionError("oversized message accepted")
    assert T.negotiate_protocol("1.0")["compatible"]
    assert T.negotiate_protocol("1.1")["selected"] == "1.1"
    for version in ("2.0", "1.2", "garbage"):
        try:
            T.negotiate_protocol(version)
        except T.ContractViolation as exc:
            assert exc.code == "UNSUPPORTED_PROTOCOL"
        else:
            raise AssertionError("unsupported protocol accepted")
    bundle = T.fixture_bundle()
    assert T.downgrade_fixture(bundle)["protocol"] == "1.0"
    assert T.upgrade_fixture(T.downgrade_fixture(bundle))["protocol"] == "1.1"
    with open(FIXTURE_PATH, "rb") as handle:
        assert handle.read() == T.fixture_bytes()
    print("[T010 X002A] bounded strict JSON rejects duplicate, non-finite and oversized messages; versions and generated fixture agree")


def check_observation_bindings_and_modalities():
    observation = records()["observation"]
    context = current()
    assert T.validate_observation(observation, context) == {
        "allowed": True, "reason_code": "OK", "record_id": "obs-1",
        "unavailable_modalities": [], "answer_scope": "FULL"}
    no_a11y = copy.deepcopy(observation)
    no_a11y["modalities"] = ["pixels"]
    modality_context = copy.deepcopy(context)
    modality_context["required_modalities"] = ["pixels", "accessibility"]
    limited = T.validate_observation(no_a11y, modality_context)
    assert limited["allowed"] and limited["answer_scope"] == "LIMITED"
    assert limited["unavailable_modalities"] == ["accessibility"]
    expired = copy.deepcopy(context); expired["now_monotonic_ms"] = 5000
    assert_denied(T.validate_observation(observation, expired), "EXPIRED_OBSERVATION")
    foreign = copy.deepcopy(observation); foreign["project_id"] = "project-2"
    assert_denied(T.validate_observation(foreign, context), "REFUSE_CONTEXT_ACCESS")
    stale = copy.deepcopy(observation); stale["capture_epoch"] = 6
    assert_denied(T.validate_observation(stale, context), "STALE_SOURCE")
    print("[T008 T009] expired, foreign and stale observations refuse; missing optional modalities explicitly limit scope")


def check_permission_and_mode_boundaries():
    data = records(); request = data["request"]
    state = current()
    grant_result = T.validate_session_grant_view(data["grant_view"], state)
    assert grant_result["allowed"] and grant_result["grant_created"] is False
    stale_grant = copy.deepcopy(data["grant_view"]); stale_grant["cancellation_generation"] = 3
    assert_denied(T.validate_session_grant_view(stale_grant, state), "CANCELLED_GENERATION")
    result = T.authorize_tutor_request(request, state)
    assert result["allowed"] and result["grant_created"] is False
    replay_state = copy.deepcopy(state)
    replay_state["request_digests"] = {request["request_id"]: result["request_digest"]}
    assert T.authorize_tutor_request(request, replay_state)["idempotent_replay"] is True
    conflict = copy.deepcopy(request); conflict["question"] = "A different operation"
    assert_denied(T.authorize_tutor_request(conflict, replay_state), "INVALID_SCHEMA")
    wrong_project = copy.deepcopy(request); wrong_project["project_id"] = "project-2"
    assert_denied(T.authorize_tutor_request(wrong_project, state), "REFUSE_CONTEXT_ACCESS")
    stale_consent = copy.deepcopy(request); stale_consent["consent_revision"] = "consent-r2"
    assert_denied(T.authorize_tutor_request(stale_consent, state), "STALE_CONSENT")
    missing_cap = copy.deepcopy(state); missing_cap["grant_view"] = ["observe", "explain"]
    assert_denied(T.authorize_tutor_request(request, missing_cap), "REFUSE_PERMISSION")
    unknown_cap = copy.deepcopy(state); unknown_cap["grant_view"].append("admin")
    assert_denied(T.authorize_tutor_request(request, unknown_cap), "REFUSE_PERMISSION")
    upgrade = copy.deepcopy(request); upgrade["mode"] = "COLLABORATE"
    model = copy.deepcopy(state); model["actor"] = "MODEL"; model["grant_view"].append("input")
    assert_denied(T.authorize_tutor_request(upgrade, model), "REFUSE_MODE_ESCALATION")
    owner = copy.deepcopy(model); owner["actor"] = "OWNER"; owner["explicit_owner_request"] = True
    assert T.authorize_tutor_request(upgrade, owner)["allowed"]
    calls = []
    original = grants.grant
    grants.grant = lambda *a, **k: calls.append((a, k))
    try:
        assert T.authorize_tutor_request(request, state)["allowed"]
    finally:
        grants.grant = original
    assert calls == []
    print("[T006 X002A] tenant/project, consent and capabilities are load-bearing; only explicit owner upgrades and validation creates no grant")


def check_mode_action_and_cancellation():
    data = records(); policy = current()
    assert T.validate_instruction(data["instruction"], data["observation"], policy)["allowed"]
    action = copy.deepcopy(data["instruction"])
    action["execution_request"] = {"operation": "click", "target_id": "cell-a1",
                                   "justification": "Owner requested collaboration"}
    assert_denied(T.validate_instruction(action, data["observation"], policy), "REFUSE_MODE_ACTION")
    stale = copy.deepcopy(policy); stale["current_cancellation_generation"] = 5
    assert_denied(T.validate_instruction(data["instruction"], data["observation"], stale), "SUPPRESS_STALE_RESPONSE")
    counters = {stage: 0 for stage in T.STAGES}
    for stage in T.STAGES:
        gate = T.check_generation(3, 4, stage)
        assert gate["allowed"] is False
        if gate["allowed"]:
            counters[stage] += 1
    assert counters == {stage: 0 for stage in T.STAGES}
    queued = copy.deepcopy(data["request"]); queued["cancellation_generation"] = 3
    assert_denied(T.authorize_tutor_request(queued, policy), "CANCELLED_GENERATION")
    print("[T005 T007 X002B] Guide cannot execute; previous-generation work stops before capture, retrieval, charge/dispatch, render, handoff and action")


def check_session_machine_and_deadline():
    allowed = [("DORMANT", "INVOKE", "SELECTING"),
               ("SELECTING", "SELECT_SOURCE", "READY"),
               ("READY", "ASK", "OBSERVING"),
               ("OBSERVING", "OBSERVED", "THINKING"),
               ("THINKING", "RESULT", "PRESENTING"),
               ("PRESENTING", "PRESENTED", "READY")]
    for before, event, after in allowed:
        assert T.validate_session_transition(before, event, after)["allowed"]
    assert_denied(T.validate_session_transition("READY", "ASK", "DELEGATE"),
                  "INVALID_SCHEMA")
    request = records()["request"]
    elapsed = copy.deepcopy(request); elapsed["deadline_monotonic_ms"] = 2000
    assert_denied(T.authorize_tutor_request(elapsed, current()), "REFUSE_PERMISSION")
    too_late = copy.deepcopy(request); too_late["deadline_monotonic_ms"] = 9001
    assert_denied(T.authorize_tutor_request(too_late, current()), "REFUSE_PERMISSION")
    print("[state-deadline] session transitions are closed-table; requests cannot outlive now or their grant")


def check_instruction_evidence_and_learning_truth():
    data = records(); policy = current()
    moved = copy.deepcopy(data["instruction"])
    moved["annotations"][0]["geometry_revision"] = "geometry-r1"
    assert_denied(T.validate_instruction(moved, data["observation"], policy), "STALE_GEOMETRY")
    assert T.validate_evidence_event(data["evidence"], policy)["allowed"]
    foreign = copy.deepcopy(data["evidence"]); foreign["user_id"] = "user-2"
    assert_denied(T.validate_evidence_event(foreign, policy), "REFUSE_CONTEXT_ACCESS")
    cases = [
        ({"assessable": False}, [], "NOT_ASSESSABLE"),
        ({"assessable": True}, [{"actor": "USER", "assistance": "NONE"}], "INDEPENDENT_ELIGIBLE"),
        ({"assessable": True}, [{"actor": "USER", "assistance": "HINT"}], "ASSISTED"),
        ({"assessable": True}, [{"actor": "AGENT", "assistance": "EXECUTION"}], "ASSISTED"),
        ({"assessable": True, "invalidated": True}, [], "INVALIDATED"),
    ]
    for attempt, exposures, expected in cases:
        result = T.classify_learning_attempt(attempt, exposures)
        assert result == {"classification": expected, "success": None}
    projection = T.build_learner_projection([
        {"attempt": a, "exposures": e} for a, e, _ in cases])
    assert projection["mastery"] is None
    assert projection["counts"] == {"NOT_ASSESSABLE": 1, "ASSISTED": 2,
                                    "INDEPENDENT_ELIGIBLE": 1, "INVALIDATED": 1}
    print("[evidence] geometry and identity bind evidence; assistance classification never invents correctness or mastery")


def check_schema_negatives():
    data = records(); context = current()
    unknown = copy.deepcopy(data["observation"]); unknown["authority"] = "self-granted"
    assert_denied(T.validate_observation(unknown, context), "INVALID_SCHEMA")
    invalid_enum = copy.deepcopy(data["request"]); invalid_enum["mode"] = "AUTONOMOUS"
    assert_denied(T.authorize_tutor_request(invalid_enum, context), "INVALID_SCHEMA")
    null_required = copy.deepcopy(data["request"]); null_required["project_id"] = None
    assert_denied(T.authorize_tutor_request(null_required, context), "INVALID_SCHEMA")
    boolean_epoch = copy.deepcopy(data["observation"]); boolean_epoch["capture_epoch"] = True
    assert_denied(T.validate_observation(boolean_epoch, context), "INVALID_SCHEMA")
    bad_time = copy.deepcopy(data["observation"]); bad_time["captured_at_utc"] = 12
    assert_denied(T.validate_observation(bad_time, context), "INVALID_SCHEMA")
    bad_digest = copy.deepcopy(data["evidence"]); bad_digest["artifact_digest"] = 12
    assert_denied(T.validate_evidence_event(bad_digest, context), "INVALID_SCHEMA")
    pack = {"schema": "fleet.tutor.teaching_pack.v1", "pack_id": "pack-1",
            "source_refs": ["source-1"], "moves": [{"kind": "EXPLAIN"}],
            "content_sha256": "a" * 64}
    assert T.validate_teaching_pack(pack, {"source-1": {}})["allowed"]
    assert_denied(T.validate_teaching_pack(pack, {}), "STALE_SOURCE")
    print("[schema] unknown fields, invalid enums, null-required values and boolean epochs fail closed")


def check_unknown_desktop_geometry():
    data = records(); context = current()
    observation = data['observation']
    for field in ('desktop_origin_x', 'desktop_origin_y', 'native_dpi_scale'):
        observation['geometry'][field] = None
    assert T.validate_observation(observation, context)['allowed'], 'unknown desktop placement blocked source pixels'
    instruction = data['instruction']
    assert not T.validate_instruction(instruction, observation, context)['allowed'], 'unknown desktop placement admitted annotations'
    instruction['annotations'] = []
    assert T.validate_instruction(instruction, observation, context)['allowed'], 'unknown placement blocked a text explanation'
    for field in ('desktop_origin_x', 'desktop_origin_y', 'native_dpi_scale'):
        mixed = copy.deepcopy(observation)
        mixed['geometry'][field] = 1
        assert_denied(T.validate_observation(mixed, context), 'INVALID_SCHEMA')
    print('[geometry] unknown placement admits pixels/text only; partial placement and annotations refuse')


def main():
    check_unknown_desktop_geometry()
    check_strict_wire_and_versioning()
    check_observation_bindings_and_modalities()
    check_permission_and_mode_boundaries()
    check_mode_action_and_cancellation()
    check_session_machine_and_deadline()
    check_instruction_evidence_and_learning_truth()
    check_schema_negatives()
    print("PASS test_tutor_contracts")


if __name__ == "__main__":
    main()
