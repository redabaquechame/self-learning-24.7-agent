#!/usr/bin/env python3
"""Authority-bound disposable practice environments for Screen Tutor.

Only synthetic or explicitly licensed practice assets are accepted. The source
is read through File Authority, the destination is generated inside the
practice workspace, and reset writes only that generated artifact. No command,
application input, network call or real-project write is available here.
"""

import copy
import hashlib
import json
import os
import re

import fileauth


SAFE_SOURCE_KINDS = {
    "SYNTHETIC_SAMPLE": "SYNTHETIC",
    "LICENSED_SAMPLE": "LICENSED_FOR_PRACTICE",
}
MODES = ("WORKED", "PARTIAL", "INDEPENDENT")
ASSISTANCE = ("NONE", "HINT", "ANSWER")
NOVELTY = ("INPUT_VALUES", "STRUCTURE", "CONTEXT", "REPRESENTATION")
VERIFIERS = ("CANONICAL_JSON_EQUALS", "HUMAN_SUBJECTIVE")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_WATCH_REFS = 64
MAX_EXPECTED_BYTES = 256 * 1024


class PracticeRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PracticeRefused("INVALID_PRACTICE", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise PracticeRefused("INVALID_PRACTICE", f"invalid {name}")
    return value


def _sha(value, name):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise PracticeRefused("INVALID_PRACTICE", f"invalid {name}")
    return value


def _safe_json(value, name, maximum=MAX_EXPECTED_BYTES):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise PracticeRefused("INVALID_PRACTICE", f"invalid {name}") from error
    if len(encoded) > maximum:
        raise PracticeRefused("INVALID_PRACTICE", f"{name} exceeds bound")
    return json.loads(encoded.decode("utf-8"))


def _json_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise PracticeRefused("ARTIFACT_VERIFICATION_FAILED",
                                  f"duplicate JSON key {key}")
        result[key] = value
    return result


def _source(value):
    _exact(value, ("source_ref", "content_sha256", "source_revision",
                   "source_kind", "rights", "license_id", "practice_eligible",
                   "pack_id", "pack_version"), "practice source")
    for field in ("source_revision", "license_id", "pack_id"):
        _ident(value[field], field)
    if (value["source_kind"] not in SAFE_SOURCE_KINDS
            or value["rights"] != SAFE_SOURCE_KINDS.get(value["source_kind"])
            or value["practice_eligible"] is not True):
        raise PracticeRefused("SAFE_COPY_REQUIRED",
                              "source is not a synthetic or licensed practice asset")
    if not isinstance(value["source_ref"], str) or not value["source_ref"].strip():
        raise PracticeRefused("INVALID_PRACTICE", "invalid source_ref")
    if (not isinstance(value["pack_version"], str)
            or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
                                value["pack_version"])):
        raise PracticeRefused("INVALID_PRACTICE", "invalid pack version")
    result = dict(value)
    result["content_sha256"] = _sha(value["content_sha256"], "source digest")
    return result


def _spec(value):
    _exact(value, ("practice_id", "user_id", "project_id", "sample_id", "mode",
                   "artifact_name", "verifier", "expected_result", "watch_refs",
                   "revealed_elements"), "practice specification")
    for field in ("practice_id", "user_id", "project_id", "sample_id"):
        _ident(value[field], field)
    if value["mode"] not in MODES or value["verifier"] not in VERIFIERS:
        raise PracticeRefused("INVALID_PRACTICE", "mode or verifier")
    if (not isinstance(value["artifact_name"], str)
            or not FILENAME.fullmatch(value["artifact_name"])
            or value["artifact_name"] in (".", "..")):
        raise PracticeRefused("INVALID_PRACTICE", "artifact name")
    reveals = value["revealed_elements"]
    if (isinstance(reveals, bool) or not isinstance(reveals, int)
            or not 0 <= reveals <= 1000):
        raise PracticeRefused("INVALID_PRACTICE", "revealed element count")
    if value["mode"] == "INDEPENDENT" and reveals != 0:
        raise PracticeRefused("INDEPENDENT_VARIANT_EXPOSED",
                              "independent practice reveals an answer element")
    if value["mode"] in ("WORKED", "PARTIAL") and reveals == 0:
        raise PracticeRefused("INVALID_PRACTICE",
                              "assisted mode must account for its reveals")
    refs = value["watch_refs"]
    if (not isinstance(refs, list) or not 1 <= len(refs) <= MAX_WATCH_REFS
            or not all(isinstance(ref, str) and ref.strip() for ref in refs)
            or len(set(refs)) != len(refs)):
        raise PracticeRefused("INVALID_PRACTICE", "watch refs")
    result = dict(value)
    result["expected_result"] = _safe_json(value["expected_result"], "expected result")
    result["watch_refs"] = list(refs)
    return result


def _digest_refs(home, refs):
    result = {}
    for ref in refs:
        try:
            result[ref] = fileauth.sha256_bytes(home, ref)
        except (OSError, fileauth.Denied) as error:
            raise PracticeRefused("PRACTICE_SOURCE_UNAVAILABLE", str(error)) from error
    return result


def create_practice_copy(home, source, specification):
    source = _source(source)
    spec = _spec(specification)
    if source["source_ref"] not in spec["watch_refs"]:
        raise PracticeRefused("INVALID_PRACTICE", "source must be watched")
    try:
        source_path = fileauth.resolve(home, source["source_ref"], "read", "agent")
        if os.path.getsize(source_path) > MAX_SOURCE_BYTES:
            raise PracticeRefused("PRACTICE_SOURCE_TOO_LARGE", source["source_ref"])
        payload = fileauth.read_bytes(home, source["source_ref"])
    except PracticeRefused:
        raise
    except (OSError, fileauth.Denied) as error:
        raise PracticeRefused("PRACTICE_SOURCE_UNAVAILABLE", str(error)) from error
    digest = hashlib.sha256(payload).hexdigest()
    if digest != source["content_sha256"]:
        raise PracticeRefused("PRACTICE_SOURCE_CHANGED", source["source_ref"])
    watched = _digest_refs(home, spec["watch_refs"])
    artifact_ref = (f"artifacts/tutor-practice/{spec['project_id']}/"
                    f"{spec['user_id']}/{spec['practice_id']}/{spec['artifact_name']}")
    artifact_path = fileauth.resolve(home, artifact_ref, "write", "agent")
    if os.path.exists(artifact_path):
        raise PracticeRefused("PRACTICE_EXISTS", artifact_ref)
    try:
        fileauth.write_bytes(home, artifact_ref, payload)
    except (OSError, fileauth.Denied) as error:
        raise PracticeRefused("PRACTICE_COPY_FAILED", str(error)) from error
    assistance = {"WORKED": "ANSWER", "PARTIAL": "HINT",
                  "INDEPENDENT": "NONE"}[spec["mode"]]
    return {
        "schema": "tutor.practice-session/1",
        "practice_id": spec["practice_id"], "user_id": spec["user_id"],
        "project_id": spec["project_id"], "sample_id": spec["sample_id"],
        "source_ref": source["source_ref"],
        "source_sha256": source["content_sha256"],
        "source_revision": source["source_revision"],
        "source_rights": source["rights"], "license_id": source["license_id"],
        "pack_id": source["pack_id"], "pack_version": source["pack_version"],
        "artifact_ref": artifact_ref, "artifact_name": spec["artifact_name"],
        "baseline_artifact_sha256": digest, "mode": spec["mode"],
        "verifier": spec["verifier"], "expected_result": spec["expected_result"],
        "expected_result_sha256": _json_digest(spec["expected_result"]),
        "watch_digests": watched, "status": "ACTIVE", "reset_count": 0,
        "executor": "NONE_DETERMINISTIC_IN_PROCESS",
        "reveal_accounting": {"assistance": assistance,
                              "revealed_elements": spec["revealed_elements"],
                              "independence_eligible": assistance == "NONE"},
    }


_SESSION_KEYS = ("schema", "practice_id", "user_id", "project_id", "sample_id",
                 "source_ref", "source_sha256", "source_revision", "source_rights",
                 "license_id", "pack_id", "pack_version", "artifact_ref",
                 "artifact_name", "baseline_artifact_sha256", "mode", "verifier",
                 "expected_result", "expected_result_sha256", "watch_digests",
                 "status", "reset_count",
                 "executor", "reveal_accounting")


def _session(value):
    _exact(value, _SESSION_KEYS, "practice session")
    if value["schema"] != "tutor.practice-session/1" or value["status"] not in ("ACTIVE", "STOPPED"):
        raise PracticeRefused("INVALID_PRACTICE", "session schema or status")
    for field in ("practice_id", "user_id", "project_id", "sample_id",
                  "source_revision", "license_id", "pack_id"):
        _ident(value[field], field)
    for field in ("source_sha256", "baseline_artifact_sha256",
                  "expected_result_sha256"):
        _sha(value[field], field)
    if (not isinstance(value["artifact_name"], str)
            or not FILENAME.fullmatch(value["artifact_name"])):
        raise PracticeRefused("INVALID_PRACTICE", "session artifact name")
    expected_artifact_ref = (
        f"artifacts/tutor-practice/{value['project_id']}/"
        f"{value['user_id']}/{value['practice_id']}/{value['artifact_name']}")
    if value["artifact_ref"] != expected_artifact_ref:
        raise PracticeRefused("INVALID_PRACTICE",
                              "artifact is outside the generated practice folder")
    if (not isinstance(value["watch_digests"], dict)
            or not 1 <= len(value["watch_digests"]) <= MAX_WATCH_REFS
            or any(not isinstance(ref, str) or not ref.strip()
                   or not isinstance(digest, str) or not SHA256.fullmatch(digest)
                   for ref, digest in value["watch_digests"].items())):
        raise PracticeRefused("INVALID_PRACTICE", "watch digests")
    if (value["mode"] not in MODES or value["verifier"] not in VERIFIERS
            or value["executor"] != "NONE_DETERMINISTIC_IN_PROCESS"):
        raise PracticeRefused("INVALID_PRACTICE", "session mode, verifier or executor")
    if (value["source_rights"] not in SAFE_SOURCE_KINDS.values()
            or not isinstance(value["pack_version"], str)
            or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)",
                                value["pack_version"])):
        raise PracticeRefused("INVALID_PRACTICE", "source lineage")
    if isinstance(value["reset_count"], bool) or not isinstance(value["reset_count"], int) or value["reset_count"] < 0:
        raise PracticeRefused("INVALID_PRACTICE", "reset count")
    expected = _safe_json(value["expected_result"], "expected result")
    if _json_digest(expected) != value["expected_result_sha256"]:
        raise PracticeRefused("INVALID_PRACTICE", "expected result binding changed")
    accounting = _exact(value["reveal_accounting"],
                        ("assistance", "revealed_elements", "independence_eligible"),
                        "reveal accounting")
    if (accounting["assistance"] not in ASSISTANCE
            or isinstance(accounting["revealed_elements"], bool)
            or not isinstance(accounting["revealed_elements"], int)
            or not isinstance(accounting["independence_eligible"], bool)):
        raise PracticeRefused("INVALID_PRACTICE", "reveal accounting")
    return value


def _assert_watched_unchanged(home, session):
    current = _digest_refs(home, list(session["watch_digests"]))
    changed = sorted(ref for ref, digest in current.items()
                     if digest != session["watch_digests"][ref])
    if changed:
        raise PracticeRefused("UNINTENDED_CHANGE", ", ".join(changed))


def verify_practice(home, session):
    session = _session(session)
    if session["status"] != "ACTIVE":
        raise PracticeRefused("PRACTICE_STOPPED", "stopped practice cannot verify")
    _assert_watched_unchanged(home, session)
    try:
        path = fileauth.resolve(home, session["artifact_ref"], "read", "agent")
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            raise PracticeRefused("PRACTICE_ARTIFACT_TOO_LARGE", session["artifact_ref"])
        text = fileauth.read_text(home, session["artifact_ref"], limit=MAX_SOURCE_BYTES + 1)
    except PracticeRefused:
        raise
    except (OSError, fileauth.Denied) as error:
        raise PracticeRefused("PRACTICE_ARTIFACT_UNAVAILABLE", str(error)) from error
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if session["verifier"] == "HUMAN_SUBJECTIVE":
        return {"mechanical_status": "NOT_APPLICABLE",
                "human_review_required": True,
                "protected_sources_unchanged": True,
                "artifact_sha256": digest,
                "evidence_scope": "SUBJECTIVE_REVIEW_PENDING"}
    try:
        actual = json.loads(
            text, object_pairs_hook=_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
        actual = _safe_json(actual, "practice artifact")
    except (json.JSONDecodeError, ValueError, PracticeRefused) as error:
        if isinstance(error, PracticeRefused):
            raise
        raise PracticeRefused("ARTIFACT_VERIFICATION_FAILED",
                              "artifact is not bounded canonical JSON") from error
    passed = actual == session["expected_result"]
    return {"mechanical_status": "PASSED" if passed else "FAILED",
            "human_review_required": False,
            "protected_sources_unchanged": True,
            "artifact_sha256": digest,
            "evidence_scope": "MECHANICAL_ARTIFACT_ONLY"}


def reset_practice(home, session):
    session = _session(session)
    if session["status"] != "ACTIVE":
        raise PracticeRefused("PRACTICE_STOPPED", "stopped practice cannot reset")
    _assert_watched_unchanged(home, session)
    try:
        payload = fileauth.read_bytes(home, session["source_ref"])
    except (OSError, fileauth.Denied) as error:
        raise PracticeRefused("PRACTICE_SOURCE_UNAVAILABLE", str(error)) from error
    if hashlib.sha256(payload).hexdigest() != session["source_sha256"]:
        raise PracticeRefused("PRACTICE_SOURCE_CHANGED", session["source_ref"])
    try:
        fileauth.write_bytes(home, session["artifact_ref"], payload)
    except (OSError, fileauth.Denied) as error:
        raise PracticeRefused("PRACTICE_RESET_FAILED", str(error)) from error
    result = copy.deepcopy(session)
    result["reset_count"] += 1
    return result


def stop_practice(session):
    session = _session(session)
    result = copy.deepcopy(session)
    result["status"] = "STOPPED"
    return result


def _variant(value, where):
    _exact(value, ("schema", "variant_id", "mode", "artifact_name",
                   "content_sha256", "task_signature", "novelty_dimensions",
                   "revealed_elements", "assistance", "status"), where)
    if value["schema"] != "tutor.practice-variant/1" or value["status"] != "CANDIDATE":
        raise PracticeRefused("INVALID_PRACTICE", "variant schema or status")
    _ident(value["variant_id"], "variant id")
    _ident(value["task_signature"], "task signature")
    _sha(value["content_sha256"], "variant digest")
    if not isinstance(value["artifact_name"], str) or not FILENAME.fullmatch(value["artifact_name"]):
        raise PracticeRefused("INVALID_PRACTICE", "variant artifact name")
    if value["mode"] not in MODES or value["assistance"] not in ASSISTANCE:
        raise PracticeRefused("INVALID_PRACTICE", "variant mode or assistance")
    dimensions = value["novelty_dimensions"]
    if (not isinstance(dimensions, list) or len(dimensions) > len(NOVELTY)
            or any(item not in NOVELTY for item in dimensions)
            or len(set(dimensions)) != len(dimensions)):
        raise PracticeRefused("INVALID_PRACTICE", "novelty dimensions")
    reveals = value["revealed_elements"]
    if isinstance(reveals, bool) or not isinstance(reveals, int) or not 0 <= reveals <= 1000:
        raise PracticeRefused("INVALID_PRACTICE", "revealed element count")
    if value["mode"] == "INDEPENDENT" and (reveals != 0 or value["assistance"] != "NONE"):
        raise PracticeRefused("INDEPENDENT_VARIANT_EXPOSED", value["variant_id"])
    if value["mode"] == "WORKED" and (reveals == 0 or value["assistance"] != "ANSWER"):
        raise PracticeRefused("INVALID_PRACTICE", "worked variant reveal accounting")
    if value["mode"] == "PARTIAL" and (reveals == 0 or value["assistance"] != "HINT"):
        raise PracticeRefused("INVALID_PRACTICE", "partial variant reveal accounting")
    return dict(value)


def assess_variant(baseline, candidate):
    baseline = _variant(baseline, "baseline variant")
    candidate = _variant(candidate, "candidate variant")
    if (candidate["content_sha256"] == baseline["content_sha256"]
            and candidate["task_signature"] == baseline["task_signature"]):
        return {"transfer_eligible": False,
                "reason": "IDENTICAL_CONTENT_FILENAME_ONLY"}
    if candidate["mode"] != "INDEPENDENT":
        return {"transfer_eligible": False, "reason": "NOT_INDEPENDENT"}
    if not candidate["novelty_dimensions"]:
        return {"transfer_eligible": False, "reason": "NO_DECLARED_NOVELTY"}
    if candidate["task_signature"] == baseline["task_signature"]:
        return {"transfer_eligible": False, "reason": "TASK_SIGNATURE_UNCHANGED"}
    return {"transfer_eligible": True,
            "reason": "NOVEL_INDEPENDENT_CANDIDATE"}
