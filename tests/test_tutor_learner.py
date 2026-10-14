#!/usr/bin/env python3
"""SC-2B attribution, exposure, correction and projection witnesses."""

import copy
import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tutor_learner as L


STAMP = "2026-09-15T09:20:00Z"
DIGEST = hashlib.sha256(b"synthetic learner artifact").hexdigest()


def row(event_id, kind, payload, attempt_id=None):
    return L.event(
        event_id=event_id, kind=kind, user_id="learner-1",
        tenant_id="tenant-alpha", project_id="project-reporting",
        session_id="session-1", skill_id="reporting-procedure-group",
        attempt_id=attempt_id or event_id, payload=payload,
        recorded_at_utc=STAMP)


def attempt(event_id, *, actor="USER", assistance="NONE", outcome="CORRECT",
            key="fresh-family-1", assessable=True, exposed=False,
            assistive=False, version="1.5.0"):
    return row(event_id, "ATTEMPT", {
        "assessment_key": key, "actor": actor, "assistance": assistance,
        "outcome": outcome, "assessable": assessable,
        "answer_exposed": exposed, "assistive_technology": assistive,
        "app_version": version, "artifact_sha256": DIGEST,
        "evaluator": "OUTCOME_RUBRIC"})


def main():
    home = tempfile.mkdtemp(prefix="tutor-learner-")
    try:
        arrows = attempt("event-arrows", assistance="HINT", key="arrows-family")
        projection = L.build_projection([arrows])
        got = projection["attempts"][0]
        assert got["classification"] == "ASSISTED"
        assert got["independent_success_increment"] == 0
        print("[T034] a correct result after explicit arrows remained assisted and added no independent success")

        agent = attempt("event-agent", actor="AGENT", assistance="EXECUTION",
                        key="agent-family")
        got = L.build_projection([agent])["attempts"][0]
        assert got["classification"] == "NOT_ASSESSABLE"
        assert got["outcome"] == "CORRECT" and got["independent_success_increment"] == 0
        print("[T035 X007B] an agent-completed correct artifact remained operational success with no learner evidence")

        revealed = row("event-reveal", "EXPOSURE", {
            "assessment_key": "shared-answer-family", "assistance": "ANSWER",
            "answer_revealed": True, "evidence_ref": "example-answer-1"})
        retry = attempt("event-retry", key="shared-answer-family")
        got = L.build_projection([revealed, retry])["attempts"][0]
        assert got["classification"] == "ASSISTED" and got["answer_exposed"]
        assert got["independent_success_increment"] == 0
        print("[T036 X007B] a prior answer revealed in another example contaminated the equivalent retry")

        wrong = attempt("event-wrong-version", outcome="INCORRECT", version="2.0.0")
        correction = row("event-version-correction", "CORRECTION", {
            "reason": "VERSION", "invalidates": ["event-wrong-version"],
            "corrected_advice": "Use the qualified 1.x route or select new reviewed sources.",
            "evidence_refs": ["app-version-window"], "editor": "USER"})
        for event in (wrong, correction):
            assert L.append_event(home, event)["created"]
        assert not L.append_event(home, wrong)["created"]
        stored = L.read_events(home, tenant_id="tenant-alpha",
                               project_id="project-reporting", user_id="learner-1")
        fixed = L.build_projection(stored)
        assert fixed["attempts"][0]["classification"] == "INVALIDATED"
        assert fixed["counts"]["INVALIDATED"] == 1
        assert len(stored) == 2 and fixed["corrections"][0]["reason"] == "VERSION"
        conflict = copy.deepcopy(wrong); conflict["payload"]["outcome"] = "CORRECT"
        try:
            L.append_event(home, conflict)
            raise AssertionError("conflicting event ID accepted")
        except L.LearnerEvidenceRefused as exc:
            assert exc.code == "EVENT_CONFLICT"
        print("[T037] user correction preserved both append-only records and invalidated the dependent wrong-version judgment")

        pause = row("event-pause", "OBSERVATION", {
            "signal": "PAUSE", "meaning": "UNDETERMINED",
            "facts": [], "hypotheses": []})
        pause_projection = L.build_projection([pause])
        assert pause_projection["observations"][0]["meaning"] == "UNDETERMINED"
        for field in ("intelligence", "diagnosis", "emotion"):
            assert pause_projection[field] is None
        hostile_pause = copy.deepcopy(pause)
        hostile_pause["payload"]["facts"] = ["confused"]
        try:
            L.build_projection([hostile_pause])
            raise AssertionError("pause diagnosis accepted")
        except L.LearnerEvidenceRefused as exc:
            assert exc.code == "INVALID_EVIDENCE"
        foreign = copy.deepcopy(arrows)
        foreign["event_id"] = "foreign-event"
        foreign["tenant_id"] = "tenant-beta"
        try:
            L.build_projection([arrows, foreign])
            raise AssertionError("mixed-scope projection accepted")
        except L.LearnerEvidenceRefused as exc:
            assert exc.code == "ACL_MISMATCH"
        print("[T038] slow or silent interaction could be stored only as an undetermined observation")

        source_rows = [{"group": "North", "amount": 200},
                       {"group": "South", "amount": 125},
                       {"group": "North", "amount": 50}]
        formula_method = [{"group": "South", "total": 125},
                          {"group": "North", "total": 250}]
        result = L.evaluate_group_sum(source_rows, formula_method)
        assert result["outcome"] == "CORRECT"
        assert not result["method_scored"] and not result["route_scored"]
        print("[T039] an alternative formula route passed because its outcome matched, independent of clicks or method")

        accommodated = attempt(
            "event-accommodation", assistance="ACCOMMODATION",
            assistive=True, key="accessible-family")
        got = L.build_projection([accommodated])["attempts"][0]
        assert got["classification"] == "INDEPENDENT_ELIGIBLE"
        assert got["independent_success_increment"] == 1
        assert got["assistive_technology"]
        print("[T040-policy-only] non-answer-revealing accommodation remains independence-eligible in policy; human/native qualification was not performed")

        all_events = [arrows, agent, revealed, retry, wrong, correction, pause,
                      accommodated]
        complete = L.build_projection(all_events)
        assert complete["mastery"] is None and complete["retention"] is None
        assert complete["counts"] == {"NOT_ASSESSABLE": 1, "ASSISTED": 2,
                                       "INDEPENDENT_ELIGIBLE": 1,
                                       "INVALIDATED": 1}
        print("[projection] raw history rebuilt assisted, agent, exposed, corrected and accommodated outcomes without inventing mastery")
        print("PASS test_tutor_learner")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
