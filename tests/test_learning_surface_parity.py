#!/usr/bin/env python3
"""SC-0D: every surface shares one host-authorized learning contract."""

import copy
import hashlib
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import learning_contracts as L  # noqa: E402


ENTITLEMENTS = {
    "learning:read", "course:write", "assignment:write",
    "session:write", "attempt:write", "evidence:write",
}
NOW = "2026-09-15T04:30:00Z"


def expect(error, call, contains=""):
    try:
        call()
    except error as caught:
        assert contains in str(caught), (contains, str(caught))
        return caught
    raise AssertionError(f"expected {error.__name__}: {contains}")


def adapter(service, surface, principal="learner-1", tenant="tenant-a",
            entitlements=ENTITLEMENTS, local_capabilities=(), branding=None):
    bound = service.bind_host(
        principal, tenant, "policy-r7", "grants-r3", "course-r11",
        entitlements, local_capabilities)
    return service.adapter(surface, bound, branding or {
        "title": surface, "accent_color": "#123456"}), bound


def execute_fixture(surface, branding):
    service = L.LearningService(
        clock=lambda: NOW, host_key=b"h" * 32, cursor_key=b"c" * 32)
    api, bound = adapter(service, surface, branding=branding)
    responses = []
    course = api.command("course.register", {
        "title": "Spreadsheet foundations",
        "course_revision": "course-r11",
        "retention_class": "operational",
    }, "r-course", "k-course")
    responses.append(course["record"])
    assignment = api.command("assignment.create", {
        "course_id": course["record"]["id"],
        "assignee_id": "learner-1",
        "due_policy": "America/Toronto:2026-10-01T17:00:00",
    }, "r-assignment", "k-assignment")
    responses.append(assignment["record"])
    session = api.command("session.open", {
        "assignment_id": assignment["record"]["id"],
        "intention": "build the model without tutor completion",
    }, "r-session", "k-session")
    responses.append(session["record"])
    attempt = api.command("attempt.begin", {
        "session_id": session["record"]["id"],
        "assignment_id": assignment["record"]["id"],
        "variant_revision": "variant-4",
    }, "r-attempt", "k-attempt")
    responses.append(attempt["record"])
    evidence = api.command("evidence.append", {
        "attempt_id": attempt["record"]["id"],
        "evidence_kind": "workbook",
        "digest": hashlib.sha256(b"wrong answer fixture").hexdigest(),
        "assistance": "ASSISTED",
    }, "r-evidence", "k-evidence")
    responses.append(evidence["record"])
    submission = api.command("attempt.submit", {
        "attempt_id": attempt["record"]["id"],
        "artifact_digests": [evidence["record"]["digest"]],
    }, "r-submit", "k-submit")
    responses.append(submission["record"])
    return responses, service.events(bound), submission, service, api, bound


def check_surface_and_brand_parity():
    baselines = []
    event_sets = []
    for index, surface in enumerate(sorted(L.SURFACES)):
        records, events, submission, _service, _api, _bound = execute_fixture(
            surface, {"title": f"Brand {index}",
                      "logo_url": f"https://brand{index}.invalid/logo.svg",
                      "accent_color": f"#{index + 1:06d}"})
        baselines.append(records)
        event_sets.append(events)
        assert submission["record"]["passing"] is None
        assert submission["record"]["state"] == "SUBMITTED"
        assert submission["transport"]["surface"] == surface
    assert all(rows == baselines[0] for rows in baselines[1:])
    assert all(rows == event_sets[0] for rows in event_sets[1:])
    assert len(event_sets[0]) == 6
    print("[surface-parity] main Learn, native, standalone and embed adapters "
          "produced byte-equivalent authoritative course, assignment, "
          "session, attempt, evidence and submission records across four brands")


def check_host_authority_and_cross_tenant_refusal():
    service = L.LearningService(clock=lambda: NOW)
    api_a, bound_a = adapter(service, "main_learn")
    course = api_a.command("course.register", {
        "title": "Tenant A", "course_revision": "course-r11"},
        "a-course", "a-course-key")["record"]
    api_b, _bound_b = adapter(
        service, "standalone_portal", principal="learner-2",
        tenant="tenant-b")
    expect(L.NotFound, lambda: api_b.command("assignment.create", {
        "course_id": course["id"], "assignee_id": "learner-2"},
        "b-assignment", "b-assignment-key"), "tenant-scoped")

    forged = L.HostBinding(
        "learner-1", "tenant-a", "policy-r7", "grants-r3",
        "course-r11", frozenset(ENTITLEMENTS), frozenset(), "fake")
    expect(L.Unauthorized,
           lambda: service.adapter("main_learn", forged), "forged")
    assert len(service.events(bound_a)) == 1
    same_tenant_other, _ = adapter(
        service, "main_learn", principal="tenant-a-other")
    listed = same_tenant_other.command("records.list", {"kind": "course"})
    assert listed["records"] == []
    print("[host-authority] a forged binding and a cross-tenant course "
          "reference were refused before creating an assignment or event")


def check_frontend_cannot_escalate_or_create_a_pass():
    service = L.LearningService(clock=lambda: NOW)
    api, bound = adapter(service, "standalone_portal")
    session = api.command("session.open", {"objective": "practise safely"},
                          "session", "session-key")["record"]
    expect(L.Unauthorized, lambda: api.command("attempt.begin", {
        "session_id": session["id"], "variant_revision": "v1",
        "learner_id": "administrator"}, "forged-learner", "forged-key"),
        "learner_id")
    attempt = api.command("attempt.begin", {
        "session_id": session["id"], "variant_revision": "v1"},
        "attempt", "attempt-key")["record"]
    wrong = hashlib.sha256(b"deliberately incorrect").hexdigest()
    expect(L.Unauthorized, lambda: api.command("attempt.submit", {
        "attempt_id": attempt["id"], "artifact_digests": [wrong],
        "passed": True}, "forged-pass", "forged-pass-key"), "passed")
    expect(L.ContractError, lambda: service.adapter(
        "standalone_portal", bound, {"title": "<script>alert(1)</script>"}),
        "executable")
    expect(L.ContractError, lambda: service.adapter(
        "standalone_portal", bound, {"logo_url": "http://unsafe.invalid/a"}),
        "https")
    expect(L.ContractError, lambda: service.adapter(
        "standalone_portal", bound, {"accent_color": "red"}), "#RRGGBB")
    expect(L.ContractError, lambda: api.command(
        "learning.capabilities", []), "payload must be an object")
    submission = api.command("attempt.submit", {
        "attempt_id": attempt["id"], "artifact_digests": [wrong]},
        "submit", "submit-key")["record"]
    assert submission["passing"] is None
    assert all(event["operation"] != "assessment.evaluate"
               for event in service.events(bound))
    print("[no-frontend-success] forged learner and pass fields plus executable "
          "branding were refused; the incorrect submission remained unscored")


def check_idempotency_version_and_reserved_operations():
    service = L.LearningService(clock=lambda: NOW)
    api, bound = adapter(service, "embed_sdk")
    payload = {"title": "Idempotent", "course_revision": "course-r11"}
    first = api.command("course.register", payload, "first", "same-key")
    replay = api.command("course.register", copy.deepcopy(payload),
                         "retry", "same-key")
    assert first["record"] == replay["record"]
    assert replay["transport"]["replay"] is True
    assert len(service.events(bound)) == 1
    expect(L.Conflict, lambda: api.command("course.register", {
        "title": "Different", "course_revision": "course-r11"},
        "conflict", "same-key"), "different content")
    expect(L.ContractError, lambda: api.command(
        "assessment.evaluate", {}, "reserved", "reserved-key"),
        "not implemented")
    bad = {"api_version": "learning.v2", "request_id": "bad-version",
           "operation": "learning.capabilities", "idempotency_key": "",
           "payload": {}}
    expect(L.ContractError,
           lambda: service.dispatch("embed_sdk", bound, bad), "unsupported")
    print("[retry-version] identical retry returned one record and one event; "
          "conflicting reuse, version skew and reserved evaluation all refused")


def check_cursor_cancellation_and_local_permission_split():
    service = L.LearningService(
        clock=lambda: NOW, host_key=b"z" * 32, cursor_key=b"q" * 32)
    api, bound = adapter(service, "native_companion",
                         local_capabilities={"capture.selected"})
    capability = api.command("learning.capabilities")
    assert capability["transport"]["native_capture"] is True
    portal = service.adapter("standalone_portal", bound, {"title": "Portal"})
    assert portal.command("learning.capabilities")["transport"][
        "native_capture"] is False
    for i in range(3):
        api.command("course.register", {
            "title": f"Course {i}", "course_revision": "course-r11"},
            f"course-{i}", f"course-key-{i}")
    first = api.command("records.list", {"kind": "course", "limit": 2})
    assert len(first["records"]) == 2 and first["next_cursor"]
    second = api.command("records.list", {
        "kind": "course", "limit": 2, "cursor": first["next_cursor"]})
    assert len(second["records"]) == 1 and second["next_cursor"] is None
    tampered = first["next_cursor"][:-1] + (
        "A" if first["next_cursor"][-1] != "A" else "B")
    expect(L.Unauthorized, lambda: api.command("records.list", {
        "kind": "course", "cursor": tampered}), "cursor")

    other, _ = adapter(service, "main_learn", principal="other")
    expect(L.Unauthorized, lambda: other.command("records.list", {
        "kind": "course", "cursor": first["next_cursor"]}), "cursor")
    session = api.command("session.open", {"objective": "cancel me"},
                          "cancel-session", "cancel-session-key")
    cancelled = api.command("request.cancel", {
        "target_id": session["record"]["id"], "reason": "learner stopped"},
        "cancel", "cancel-key")
    repeated = api.command("request.cancel", {
        "target_id": session["record"]["id"], "reason": "learner stopped"},
        "cancel-retry", "cancel-key")
    assert cancelled["record"] == repeated["record"]
    assert repeated["transport"]["replay"] is True
    assert "local_capabilities" not in str(capability)
    print("[cursor-cancel-local] scoped cursors reject tampering and another "
          "principal; cancellation is idempotent; portal transport cannot "
          "inherit native capture from the same sealed host context")


def main():
    check_surface_and_brand_parity()
    check_host_authority_and_cross_tenant_refusal()
    check_frontend_cannot_escalate_or_create_a_pass()
    check_idempotency_version_and_reserved_operations()
    check_cursor_cancellation_and_local_permission_split()
    print("PASS test_learning_surface_parity")


if __name__ == "__main__":
    main()
