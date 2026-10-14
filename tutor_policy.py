#!/usr/bin/env python3
"""Deterministic, source-grounded instructional policy for Screen Tutor.

The policy chooses one teaching move. It never executes a screen action and it
never converts fluent output, assisted completion, or a policy check into a
human-learning claim. Exact application advice comes only from a qualified
teaching pack and its ACL/version-bound source retrieval.
"""

import hashlib
import json
import re

import tutor_contracts
import tutor_learner
import tutor_packs


INTENTS = tutor_contracts.LEARNING_INTENTS
MOVES = (
    "DIRECT_EXPLANATION", "NEXT_STEP", "WORKED_EXAMPLE",
    "GUIDED_PRACTICE", "INDEPENDENT_PROMPT", "CHECK_UNDERSTANDING",
    "SCOPE_LIMIT",
)
DIAGNOSTIC_CATEGORIES = (
    "CONCEPT", "TARGET", "VERSION", "PERMISSION", "LATENCY",
    "ACCESSIBILITY", "TUTOR_ERROR",
)
RUBRIC_CRITERIA = (
    "factual_correctness", "target_accuracy", "diagnostic_accuracy",
    "helpfulness", "appropriate_interruption", "correction_quality",
    "source_scope", "accessibility",
)
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class PolicyRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise PolicyRefused("INVALID_POLICY_INPUT", f"invalid {name}")
    return value


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PolicyRefused("INVALID_POLICY_INPUT", f"invalid {name}")
    return value.strip()


def _principal(value):
    if (not isinstance(value, str) or not value or len(value) > 320
            or value != value.strip() or any(ch.isspace() for ch in value)):
        raise PolicyRefused("INVALID_REVIEW", "invalid reviewer principal")
    return value.lower()


def _source_ref(result):
    source = result["source"]
    encoded = json.dumps(source, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode("ascii")
    return "source_" + hashlib.sha256(encoded).hexdigest()


def diagnostic_hypotheses(*, pause_observed=False, evidence=()):
    """Return bounded hypotheses; a pause alone creates no diagnosis or fact.

    Evidence rows are explicit observations with `category`, `evidence_ref` and
    `summary`. Categories describe what to check, not a learner trait.
    """
    if not isinstance(pause_observed, bool) or not isinstance(evidence, (list, tuple)):
        raise PolicyRefused("INVALID_DIAGNOSTIC", "invalid observation input")
    hypotheses = []
    for row in evidence:
        if not isinstance(row, dict) or set(row) != {
                "category", "evidence_ref", "summary"}:
            raise PolicyRefused("INVALID_DIAGNOSTIC", "invalid evidence fields")
        category = row["category"]
        if category not in DIAGNOSTIC_CATEGORIES:
            raise PolicyRefused("INVALID_DIAGNOSTIC", "unknown category")
        hypotheses.append({
            "category": category,
            "status": "HYPOTHESIS",
            "evidence_ref": _ident(row["evidence_ref"], "evidence_ref"),
            "summary": _text(row["summary"], "summary", 500),
        })
    return {
        "schema": "tutor.diagnostic-hypotheses/1",
        "observations": ([{"kind": "PAUSE", "meaning": "UNDETERMINED"}]
                         if pause_observed else []),
        "facts": [],
        "hypotheses": hypotheses,
        "learner_traits": {},
    }


def _comparable_independent_successes(history, *, skill_id, app_version):
    if not isinstance(history, (list, tuple)) or len(history) > 100:
        raise PolicyRefused("INVALID_HISTORY", "history must be a bounded list")
    count = 0
    for row in history:
        if not isinstance(row, dict):
            raise PolicyRefused("INVALID_HISTORY", "history row must be an object")
        if (row.get("skill_id") == skill_id
                and row.get("app_version") == app_version
                and row.get("classification") == "INDEPENDENT_ELIGIBLE"
                and row.get("outcome") == "CORRECT"
                and row.get("answer_exposed") is False):
            count += 1
    return count


def plan_instruction(home, *, request_id, intent, question, pack_id,
                     user_id, tenant_id, project_id, app_version, skill_id):
    """Select exactly one move from qualified source evidence.

    The exact user's scoped append-only ledger can fade help only after two
    comparable independent, correct, unexposed outcomes. Caller-supplied history
    cannot influence the decision.
    """
    for value, name in ((request_id, "request_id"), (pack_id, "pack_id"),
                        (user_id, "user_id"),
                        (tenant_id, "tenant_id"), (project_id, "project_id"),
                        (skill_id, "skill_id")):
        _ident(value, name)
    if intent not in INTENTS:
        raise PolicyRefused("INVALID_INTENT", repr(intent))
    question = _text(question, "question", 8192)
    try:
        retrieval = tutor_packs.retrieve(
            home, pack_id, tenant_id=tenant_id, project_id=project_id,
            query=question, app_version=app_version, limit=3, max_chars=6000)
    except tutor_packs.PackRefused as exc:
        raise PolicyRefused(exc.code, exc.detail) from exc

    route = retrieval["route"]
    if not route["exact_route"] or retrieval["status"] != "OK":
        detail = route.get("scope_limit") or (
            "No qualified source excerpt answers this request in the selected scope.")
        instruction = {
            "schema": "fleet.tutor.instruction.v1", "request_id": request_id,
            "move": "SCOPE_LIMIT", "answer": detail, "claims": [],
            "annotations": [], "requested_response": "Select a supported version or source.",
            "reveal_level": "NONE",
            "expected_progress": {"kind": "SCOPE_REPAIR", "scope": detail},
            "execution_request": None,
        }
        return {"schema": "tutor.instruction-plan/1", "instruction": instruction,
                "evidence": [],
                "policy_trace": {"intent": intent, "move_count": 1,
                                 "independent_comparable_successes": 0,
                                 "pack_digest": retrieval["pack"]["digest"],
                                 "instruction_quality": None,
                                 "human_learning_efficacy": None}}

    history = tutor_learner.build_projection(tutor_learner.read_events(
        home, tenant_id=tenant_id, project_id=project_id,
        user_id=user_id))["attempts"]
    successes = _comparable_independent_successes(
        history, skill_id=skill_id, app_version=app_version)
    source = retrieval["results"][0]
    evidence_ref = _source_ref(source)
    content = source["content"]
    claim_text = content
    if intent == "UNDERSTAND":
        move, reveal = "DIRECT_EXPLANATION", "DIRECT"
        requested = "No response required; an example or check is optional."
        progress = ("EXPLANATION_RECEIVED", "The requested definition or principle is available.")
    elif intent == "FINISH":
        move, reveal = "NEXT_STEP", "HINT"
        requested = "Try this one step and report the observed result."
        progress = ("TASK_PROGRESS", "One bounded user-performed step.")
    elif intent == "ASSESS":
        move, reveal = "CHECK_UNDERSTANDING", "NONE"
        content = "Apply the qualified principle to a fresh equivalent task; no answer is revealed."
        requested = "Submit the resulting artifact for the separate assessment authority."
        progress = ("ASSESSMENT_ATTEMPT", "One answer-unrevealed attempt.")
    elif successes >= 2:
        move, reveal = "INDEPENDENT_PROMPT", "NONE"
        content = "Apply the same principle to a comparable fresh example and explain the result."
        requested = "Complete the example without answer-revealing help."
        progress = ("TRANSFER_ATTEMPT", "One comparable independent attempt.")
    elif successes == 1:
        move, reveal = "GUIDED_PRACTICE", "HINT"
        requested = "Try the next part; ask for another hint if needed."
        progress = ("GUIDED_ATTEMPT", "One learner-performed practice step.")
    else:
        move, reveal = "WORKED_EXAMPLE", "PARTIAL"
        requested = "Try an equivalent example after reviewing this principle."
        progress = ("EXAMPLE_THEN_ATTEMPT", "One proportionate application opportunity.")

    instruction = {
        "schema": "fleet.tutor.instruction.v1", "request_id": request_id,
        "move": move, "answer": content,
        "claims": [{"kind": "SOURCE_STATEMENT", "text": claim_text,
                    "evidence_refs": [evidence_ref], "uncertainty": 0.0}],
        "annotations": [], "requested_response": requested,
        "reveal_level": reveal,
        "expected_progress": {"kind": progress[0], "scope": progress[1]},
        "execution_request": None,
    }
    evidence = dict(source["source"])
    evidence["evidence_id"] = evidence_ref
    return {"schema": "tutor.instruction-plan/1", "instruction": instruction,
            "evidence": [evidence],
            "policy_trace": {"intent": intent, "move_count": 1,
                             "independent_comparable_successes": successes,
                             "pack_digest": retrieval["pack"]["digest"],
                             "instruction_quality": None,
                             "human_learning_efficacy": None}}


def review_instruction_quality(home, instruction, *, reviewer_id, reviewer_kind,
                               rubric, evidence_ref):
    """Score instruction quality without producing any learner-efficacy field."""
    _ident(evidence_ref, "evidence_ref")
    if reviewer_kind not in ("local_fixture", "qualified_content_reviewer"):
        raise PolicyRefused("INVALID_REVIEW", "unknown reviewer kind")
    if reviewer_kind == "qualified_content_reviewer":
        import org
        reviewer_id = _principal(reviewer_id)
        if org.load(home) is None:
            raise PolicyRefused("REVIEW_AUTHORITY_DENIED",
                                "qualified content review requires an organization")
        try:
            org.check(home, reviewer_id, "comment", instruction.get("request_id", ""))
        except (org.Denied, KeyError, ValueError) as exc:
            raise PolicyRefused("REVIEW_AUTHORITY_DENIED", str(exc)) from exc
    else:
        _ident(reviewer_id, "reviewer_id")
    if (isinstance(instruction, dict)
            and instruction.get("schema") == "tutor.instruction-plan/1"):
        instruction = instruction.get("instruction")
    if (not isinstance(instruction, dict)
            or instruction.get("schema") != "fleet.tutor.instruction.v1"
            or instruction.get("move") not in MOVES):
        raise PolicyRefused("INVALID_REVIEW", "invalid instruction")
    if (not isinstance(rubric, dict) or set(rubric) != set(RUBRIC_CRITERIA)
            or any(not isinstance(value, bool) for value in rubric.values())):
        raise PolicyRefused("INVALID_REVIEW", "rubric is incomplete")
    return {
        "schema": "tutor.instruction-quality-review/1",
        "request_id": instruction["request_id"],
        "reviewer_id": reviewer_id, "reviewer_kind": reviewer_kind,
        "evidence_ref": evidence_ref, "criteria": dict(rubric),
        "instruction_quality_passed": all(rubric.values()),
        "content_review_qualified": reviewer_kind == "qualified_content_reviewer",
        "human_learning_efficacy": None,
        "retention_claim": None,
    }
