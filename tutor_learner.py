#!/usr/bin/env python3
"""Append-only, user-correctable learner evidence for Screen Tutor.

The durable record keeps what happened, who acted, what help or answer was
available, and what an outcome rubric observed. A projection can be rebuilt at
any time. Corrections invalidate dependent judgments without deleting history.
"""

import json
import os
import re
import time


SCHEMA = "tutor.learner-event/1"
ROOT = os.path.join("org", "tutor-learner-evidence")
KINDS = ("EXPOSURE", "ATTEMPT", "CORRECTION", "OBSERVATION")
ACTORS = ("USER", "AGENT", "SHARED")
ASSISTANCE = ("NONE", "ACCOMMODATION", "HINT", "ANSWER", "EXECUTION")
OUTCOMES = ("CORRECT", "INCORRECT", "UNSCORED")
CORRECTION_REASONS = ("VERSION", "TARGET", "PERMISSION", "TUTOR_ERROR")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class LearnerEvidenceRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", f"invalid {name}")
    return value


def _text(value, name, maximum=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", f"invalid {name}")
    return value.strip()


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", f"invalid {where} fields")
    return value


def _ids(value, name, maximum=32):
    if not isinstance(value, list) or len(value) > maximum:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", f"invalid {name}")
    result = [_ident(item, name) for item in value]
    if len(set(result)) != len(result):
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", f"duplicate {name}")
    return result


def _path(home, tenant_id, project_id, user_id):
    parts = [_ident(value, name) for value, name in (
        (tenant_id, "tenant_id"), (project_id, "project_id"),
        (user_id, "user_id"))]
    base = os.path.realpath(os.path.join(os.path.abspath(home), ROOT))
    path = os.path.join(base, *parts) + ".jsonl"
    if os.path.commonpath((base, os.path.realpath(path))) != base:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", "path escapes ledger root")
    return path


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", str(exc)) from exc


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise LearnerEvidenceRefused("EVIDENCE_CORRUPT", f"duplicate key {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise LearnerEvidenceRefused("EVIDENCE_CORRUPT", f"non-finite value {value}")


def _validate(event):
    _exact(event, ("schema", "event_id", "kind", "user_id", "tenant_id",
                   "project_id", "session_id", "skill_id", "attempt_id",
                   "recorded_at_utc", "payload"), "event")
    if event["schema"] != SCHEMA or event["kind"] not in KINDS:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", "schema or kind")
    for field in ("event_id", "user_id", "tenant_id", "project_id",
                  "session_id", "skill_id", "attempt_id"):
        _ident(event[field], field)
    if not isinstance(event["recorded_at_utc"], str) or not UTC.fullmatch(
            event["recorded_at_utc"]):
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid UTC timestamp")
    payload = event["payload"]
    if event["kind"] == "EXPOSURE":
        _exact(payload, ("assessment_key", "assistance", "answer_revealed",
                         "evidence_ref"), "exposure")
        _ident(payload["assessment_key"], "assessment_key")
        _ident(payload["evidence_ref"], "evidence_ref")
        if payload["assistance"] not in ASSISTANCE or not isinstance(
                payload["answer_revealed"], bool):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid exposure")
    elif event["kind"] == "ATTEMPT":
        _exact(payload, ("assessment_key", "actor", "assistance", "outcome",
                         "assessable", "answer_exposed", "assistive_technology",
                         "app_version", "artifact_sha256", "evaluator"), "attempt")
        _ident(payload["assessment_key"], "assessment_key")
        if payload["actor"] not in ACTORS or payload["assistance"] not in ASSISTANCE:
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid attribution")
        if payload["outcome"] not in OUTCOMES:
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid outcome")
        if any(not isinstance(payload[name], bool) for name in (
                "assessable", "answer_exposed", "assistive_technology")):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid attempt flags")
        if not isinstance(payload["app_version"], str) or not VERSION.fullmatch(
                payload["app_version"]):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid app version")
        if not isinstance(payload["artifact_sha256"], str) or not SHA256.fullmatch(
                payload["artifact_sha256"]):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid artifact digest")
        if payload["evaluator"] not in ("OUTCOME_RUBRIC", "NONE"):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid evaluator")
        if payload["outcome"] != "UNSCORED" and payload["evaluator"] != "OUTCOME_RUBRIC":
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "scored outcome lacks rubric")
        if payload["actor"] == "AGENT" and payload["assistance"] != "EXECUTION":
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "agent work must name execution")
        if payload["assistance"] == "ACCOMMODATION" and not payload["assistive_technology"]:
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "accommodation must be declared")
    elif event["kind"] == "CORRECTION":
        _exact(payload, ("reason", "invalidates", "corrected_advice",
                         "evidence_refs", "editor"), "correction")
        if payload["reason"] not in CORRECTION_REASONS:
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid correction reason")
        _ids(payload["invalidates"], "invalidates")
        _ids(payload["evidence_refs"], "evidence_refs")
        _text(payload["corrected_advice"], "corrected_advice", 4096)
        if payload["editor"] not in ("USER", "OWNER", "QUALIFIED_REVIEWER"):
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid editor")
    else:
        _exact(payload, ("signal", "meaning", "facts", "hypotheses"), "observation")
        if payload["signal"] not in ("PAUSE", "SILENCE") or payload["meaning"] != "UNDETERMINED":
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "observation overclaims meaning")
        if payload["facts"] != [] or payload["hypotheses"] != []:
            raise LearnerEvidenceRefused("INVALID_EVIDENCE", "pause/silence cannot infer a diagnosis")
    if len(_canonical(event).encode("utf-8")) > 32 * 1024:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", "event exceeds 32 KiB")
    return event


def _read_path(path):
    rows = []
    try:
        if os.path.islink(path):
            raise LearnerEvidenceRefused("EVIDENCE_CORRUPT", "ledger is a symlink")
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    try:
                        row = json.loads(line, object_pairs_hook=_pairs,
                                         parse_constant=_nonfinite)
                    except json.JSONDecodeError as exc:
                        raise LearnerEvidenceRefused("EVIDENCE_CORRUPT", str(exc)) from exc
                    rows.append(_validate(row))
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise LearnerEvidenceRefused("EVIDENCE_UNAVAILABLE", str(exc)) from exc
    return rows


def append_event(home, event):
    """Append one immutable event. Exact retries are idempotent."""
    import locks
    _validate(event)
    path = _path(home, event["tenant_id"], event["project_id"], event["user_id"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = _canonical(event)
    with locks.holding(path, timeout=10.0, stale=8.0):
        rows = _read_path(path)
        prior = next((row for row in rows if row["event_id"] == event["event_id"]), None)
        if prior is not None:
            if _canonical(prior) == text:
                return {"created": False, "event_id": event["event_id"]}
            raise LearnerEvidenceRefused("EVENT_CONFLICT", "event ID is immutable")
        known = {row["event_id"] for row in rows}
        if event["kind"] == "CORRECTION" and not set(
                event["payload"]["invalidates"]) <= known:
            raise LearnerEvidenceRefused("INVALID_CORRECTION", "correction names unknown event")
        with open(path, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(text + "\n")
            stream.flush(); os.fsync(stream.fileno())
    return {"created": True, "event_id": event["event_id"]}


def read_events(home, *, tenant_id, project_id, user_id):
    return _read_path(_path(home, tenant_id, project_id, user_id))


def event(*, event_id, kind, user_id, tenant_id, project_id, session_id,
          skill_id, attempt_id, payload, recorded_at_utc=None):
    row = {"schema": SCHEMA, "event_id": event_id, "kind": kind,
           "user_id": user_id, "tenant_id": tenant_id,
           "project_id": project_id, "session_id": session_id,
           "skill_id": skill_id, "attempt_id": attempt_id,
           "recorded_at_utc": recorded_at_utc or time.strftime(
               "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "payload": payload}
    return _validate(row)


def evaluate_group_sum(rows, submitted):
    """Grade the resulting totals, independent of the clicks or method used."""
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise LearnerEvidenceRefused("INVALID_RUBRIC_INPUT", "invalid source rows")
    expected = {}
    for row in rows:
        _exact(row, ("group", "amount"), "source row")
        group = _text(row["group"], "group", 80)
        amount = row["amount"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise LearnerEvidenceRefused("INVALID_RUBRIC_INPUT", "amount must be integer")
        expected[group] = expected.get(group, 0) + amount
    if not isinstance(submitted, list) or len(submitted) > 100:
        raise LearnerEvidenceRefused("INVALID_RUBRIC_INPUT", "invalid submitted totals")
    actual = {}
    for row in submitted:
        _exact(row, ("group", "total"), "submitted row")
        group = _text(row["group"], "group", 80)
        total = row["total"]
        if group in actual or isinstance(total, bool) or not isinstance(total, int):
            raise LearnerEvidenceRefused("INVALID_RUBRIC_INPUT", "invalid submitted total")
        actual[group] = total
    return {"schema": "tutor.outcome-rubric-result/1",
            "outcome": "CORRECT" if actual == expected else "INCORRECT",
            "method_scored": False, "route_scored": False,
            "expected_groups": sorted(expected), "submitted_groups": sorted(actual)}


def build_projection(events):
    """Rebuild the editable view without changing the append-only record."""
    if not isinstance(events, list) or len(events) > 10000:
        raise LearnerEvidenceRefused("INVALID_EVIDENCE", "invalid event list")
    checked = [_validate(row) for row in events]
    if checked:
        scope = tuple(checked[0][name] for name in (
            "user_id", "tenant_id", "project_id"))
        if any(tuple(row[name] for name in (
                "user_id", "tenant_id", "project_id")) != scope
               for row in checked):
            raise LearnerEvidenceRefused("ACL_MISMATCH", "projection mixes learner scopes")
    seen = set()
    for row in checked:
        if row["event_id"] in seen:
            raise LearnerEvidenceRefused("EVENT_CONFLICT", "duplicate event ID")
        if (row["kind"] == "CORRECTION"
                and not set(row["payload"]["invalidates"]) <= seen):
            raise LearnerEvidenceRefused(
                "INVALID_CORRECTION", "correction must follow its target events")
        seen.add(row["event_id"])
    invalidated = set()
    corrections = []
    for row in checked:
        if row["kind"] == "CORRECTION":
            invalidated.update(row["payload"]["invalidates"])
            corrections.append({"event_id": row["event_id"], **row["payload"]})
    exposures = set()
    attempts = []
    counts = {"NOT_ASSESSABLE": 0, "ASSISTED": 0,
              "INDEPENDENT_ELIGIBLE": 0, "INVALIDATED": 0}
    independent_correct = 0
    for row in checked:
        payload = row["payload"]
        if row["kind"] == "EXPOSURE":
            if payload["answer_revealed"] or payload["assistance"] in (
                    "ANSWER", "EXECUTION"):
                exposures.add(payload["assessment_key"])
            continue
        if row["kind"] != "ATTEMPT":
            continue
        exposed = (payload["answer_exposed"]
                   or payload["assessment_key"] in exposures)
        if row["event_id"] in invalidated:
            classification = "INVALIDATED"
        elif payload["actor"] == "AGENT" or not payload["assessable"]:
            classification = "NOT_ASSESSABLE"
        elif (exposed or payload["actor"] == "SHARED"
              or payload["assistance"] in ("HINT", "ANSWER", "EXECUTION")):
            classification = "ASSISTED"
        else:
            classification = "INDEPENDENT_ELIGIBLE"
        counts[classification] += 1
        if classification == "INDEPENDENT_ELIGIBLE" and payload["outcome"] == "CORRECT":
            independent_correct += 1
        attempts.append({
            "event_id": row["event_id"], "attempt_id": row["attempt_id"],
            "skill_id": row["skill_id"], "app_version": payload["app_version"],
            "classification": classification, "outcome": payload["outcome"],
            "answer_exposed": exposed, "actor": payload["actor"],
            "assistance": payload["assistance"],
            "assistive_technology": payload["assistive_technology"],
            "independent_success_increment": (
                1 if classification == "INDEPENDENT_ELIGIBLE"
                and payload["outcome"] == "CORRECT" else 0),
        })
    observations = [{"event_id": row["event_id"], **row["payload"]}
                    for row in checked if row["kind"] == "OBSERVATION"]
    return {
        "schema": "tutor.learner-projection/1", "counts": counts,
        "independent_correct": independent_correct, "attempts": attempts,
        "corrections": corrections, "observations": observations,
        "mastery": None, "retention": None, "intelligence": None,
        "diagnosis": None, "emotion": None,
    }
