#!/usr/bin/env python3
"""SC-2B instructional intent, move, diagnosis and review witnesses."""

import os
import shutil
import sys
import tempfile
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tutor_contracts
import tutor_learner
import tutor_packs
import tutor_policy
from test_tutor_packs import CHECKLIST, PACK_SOURCE, REVIEWER, authorize_reviewer, seed


def qualified_home():
    home = tempfile.mkdtemp(prefix="tutor-policy-")
    seed(home)
    tutor_packs.install_candidate(home, PACK_SOURCE)
    authorize_reviewer(home)
    tutor_packs.review_pack(
        home, "reporting-v1", reviewer_id=REVIEWER,
        reviewer_kind="subject_matter_human", checklist=CHECKLIST)
    tutor_packs.qualify_pack(
        home, "reporting-v1", reviewer_id=REVIEWER,
        evidence_ref="synthetic-policy-contract-witness")
    return home


def plan(home, intent="UNDERSTAND", version="1.5.0"):
    return tutor_policy.plan_instruction(
        home, request_id="request-1", intent=intent,
        question="Define how to group rows and sum integer amount values.",
        pack_id="reporting-v1", user_id="learner-1", tenant_id="tenant-alpha",
        project_id="project-reporting", app_version=version,
        skill_id="reporting-procedure-group")


def independent_event(number):
    return tutor_learner.event(
        event_id=f"independent-{number}", kind="ATTEMPT",
        user_id="learner-1", tenant_id="tenant-alpha",
        project_id="project-reporting", session_id="session-1",
        skill_id="reporting-procedure-group", attempt_id=f"attempt-{number}",
        recorded_at_utc="2026-09-15T09:20:00Z", payload={
            "assessment_key": f"fresh-family-{number}", "actor": "USER",
            "assistance": "NONE", "outcome": "CORRECT", "assessable": True,
            "answer_exposed": False, "assistive_technology": False,
            "app_version": "1.5.0",
            "artifact_sha256": hashlib.sha256(
                f"artifact-{number}".encode()).hexdigest(),
            "evaluator": "OUTCOME_RUBRIC"})


def wire_ok(result):
    instruction = result["instruction"]
    observation = {"observation_id": "observation-1",
                   "geometry_revision": "geometry-1"}
    policy = {"mode": "GUIDE", "cancellation_generation": 1,
              "current_cancellation_generation": 1, "request_id": "request-1"}
    assert tutor_contracts.validate_instruction(instruction, observation, policy)["allowed"]


def main():
    home = qualified_home()
    try:
        direct = plan(home)
        assert direct["schema"] == "tutor.instruction-plan/1"
        assert direct["instruction"]["move"] == "DIRECT_EXPLANATION"
        assert direct["instruction"]["reveal_level"] == "DIRECT"
        assert direct["instruction"]["requested_response"].startswith("No response required")
        assert direct["policy_trace"]["move_count"] == 1
        assert direct["policy_trace"]["human_learning_efficacy"] is None
        assert direct["instruction"]["claims"][0]["evidence_refs"]
        assert direct["evidence"][0]["evidence_id"] == direct["instruction"]["claims"][0]["evidence_refs"][0]
        wire_ok(direct)
        print("[T033] UNDERSTAND returned one direct, source-grounded explanation with no mandatory quiz and a wire-valid instruction")

        finish = plan(home, intent="FINISH")
        learn = plan(home, intent="LEARN")
        assess = plan(home, intent="ASSESS")
        assert finish["instruction"]["move"] == "NEXT_STEP"
        assert finish["instruction"]["execution_request"] is None
        assert learn["instruction"]["move"] == "WORKED_EXAMPLE"
        assert assess["instruction"]["move"] == "CHECK_UNDERSTANDING"
        assert assess["instruction"]["reveal_level"] == "NONE"
        assert "no answer is revealed" in assess["instruction"]["answer"]
        for result in (finish, learn, assess):
            wire_ok(result)
        print("[intent] FINISH, LEARN and ASSESS selected one proportional move; none requested execution")

        for number in (1, 2):
            tutor_learner.append_event(home, independent_event(number))
        faded = plan(home, intent="LEARN")
        assert faded["instruction"]["move"] == "INDEPENDENT_PROMPT"
        other_home = qualified_home()
        try:
            tutor_learner.append_event(other_home, independent_event(1))
            assert plan(other_home, intent="LEARN")["instruction"]["move"] == "GUIDED_PRACTICE"
        finally:
            shutil.rmtree(other_home, ignore_errors=True)
        print("[help-fading] help faded only from the exact user's durable ledger after two comparable independent, correct, unexposed outcomes")

        wrong_version = plan(home, version="2.0.0")
        assert wrong_version["instruction"]["move"] == "SCOPE_LIMIT"
        assert wrong_version["instruction"]["claims"] == []
        assert "1.0.0 through 1.9.9" in wrong_version["instruction"]["answer"]
        wire_ok(wrong_version)
        print("[T037-policy] an unsupported app version produced a source-free scope correction instead of exact advice")

        paused = tutor_policy.diagnostic_hypotheses(pause_observed=True)
        assert paused["observations"] == [{"kind": "PAUSE", "meaning": "UNDETERMINED"}]
        assert paused["facts"] == [] and paused["hypotheses"] == []
        assert paused["learner_traits"] == {}
        explicit = tutor_policy.diagnostic_hypotheses(evidence=[{
            "category": "VERSION", "evidence_ref": "window-version-1",
            "summary": "Observed app reports version 2.0.0."}])
        assert explicit["hypotheses"][0]["status"] == "HYPOTHESIS"
        assert explicit["facts"] == []
        print("[T038] a pause yielded no diagnosis, intelligence, emotion or learner-trait inference; explicit environment evidence remained a hypothesis")

        rubric = {name: True for name in tutor_policy.RUBRIC_CRITERIA}
        fixture_review = tutor_policy.review_instruction_quality(
            home, direct, reviewer_id="fixture-reviewer", reviewer_kind="local_fixture",
            rubric=rubric, evidence_ref="fixture-rubric-1")
        assert fixture_review["instruction_quality_passed"]
        assert not fixture_review["content_review_qualified"]
        assert fixture_review["human_learning_efficacy"] is None
        assert fixture_review["retention_claim"] is None
        qualified_review = tutor_policy.review_instruction_quality(
            home, direct, reviewer_id=REVIEWER,
            reviewer_kind="qualified_content_reviewer", rubric=rubric,
            evidence_ref="content-rubric-1")
        assert qualified_review["content_review_qualified"]
        unbound_home = tempfile.mkdtemp(prefix="unbound-review-")
        try:
            try:
                tutor_policy.review_instruction_quality(
                    unbound_home, direct, reviewer_id=REVIEWER,
                    reviewer_kind="qualified_content_reviewer", rubric=rubric,
                    evidence_ref="forged-rubric-1")
                raise AssertionError("unbound qualified reviewer accepted")
            except tutor_policy.PolicyRefused as exc:
                assert exc.code == "REVIEW_AUTHORITY_DENIED"
        finally:
            shutil.rmtree(unbound_home, ignore_errors=True)
        print("[rubric-boundary] fixture and organization-authorized content rubrics stayed separate from efficacy and retention; an unbound qualified-review label refused")
        print("PASS test_tutor_policy")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
