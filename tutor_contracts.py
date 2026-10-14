#!/usr/bin/env python3
"""Fail-closed Screen Tutor wire contracts.

The records in this module describe observations, tutor requests, instruction
plans, and learning evidence.  They carry references to authority; they never
mint capture, execution, retention, or research grants.  Native handles,
signing material, and executable tools stay outside model-visible records.
"""

import hashlib
import json
import math
import re
from copy import deepcopy


MAX_WIRE_BYTES = 1024 * 1024
PROTOCOL_CURRENT = "1.1"
PROTOCOL_MINIMUM = "1.0"
FEATURE_DEFAULTS = {"screen_tutor": False, "screen_capture": False,
                    "screen_actions": False}
MODES = ("EXPLAIN", "GUIDE", "COLLABORATE", "DELEGATE")
LEARNING_INTENTS = ("UNDERSTAND", "FINISH", "LEARN", "ASSESS")
ACTORS = ("USER", "AGENT", "SHARED")
ASSISTANCE = ("NONE", "ACCOMMODATION", "HINT", "ANSWER", "EXECUTION")
SOURCE_KINDS = (
    "WINDOW", "REGION", "DISPLAY", "SELECTED_SURFACE",
    "BROWSER_TAB", "DOCUMENT", "MEDIA",
)
MODALITIES = frozenset(("pixels", "accessibility", "text", "audio", "video"))
EVIDENCE_CLASSES = ("NOT_ASSESSABLE", "ASSISTED",
                    "INDEPENDENT_ELIGIBLE", "INVALIDATED")
STAGES = ("capture", "retrieval", "provider_dispatch", "render",
          "downstream_handoff", "action")
SESSION_STATES = ("DORMANT", "SELECTING", "READY", "OBSERVING", "THINKING",
                  "PRESENTING", "PAUSED", "SOURCE_UNAVAILABLE",
                  "AWAITING_USER", "STOPPING", "CLOSED", "ERROR")
SESSION_TRANSITIONS = {
    "DORMANT": {"INVOKE": "SELECTING", "CLOSE": "CLOSED"},
    "SELECTING": {"SELECT_SOURCE": "READY", "CLOSE": "CLOSED"},
    "READY": {"ASK": "OBSERVING", "PAUSE": "PAUSED",
              "SOURCE_LOST": "SOURCE_UNAVAILABLE", "STOP": "STOPPING",
              "CLOSE": "CLOSED"},
    "OBSERVING": {"OBSERVED": "THINKING", "CANCEL": "READY",
                  "SOURCE_LOST": "SOURCE_UNAVAILABLE", "STOP": "STOPPING"},
    "THINKING": {"RESULT": "PRESENTING", "NEED_USER": "AWAITING_USER",
                 "SOURCE_CHANGED": "OBSERVING", "CANCEL": "READY",
                 "FAIL": "ERROR", "STOP": "STOPPING"},
    "PRESENTING": {"PRESENTED": "READY", "SOURCE_CHANGED": "READY",
                   "STOP": "STOPPING"},
    "PAUSED": {"RESUME": "READY", "SOURCE_LOST": "SOURCE_UNAVAILABLE",
               "CLOSE": "CLOSED"},
    "SOURCE_UNAVAILABLE": {"SELECT_SOURCE": "READY", "CLOSE": "CLOSED"},
    "AWAITING_USER": {"RESPOND": "OBSERVING", "CANCEL": "READY",
                      "CLOSE": "CLOSED"},
    "STOPPING": {"STOPPED": "CLOSED", "FAIL": "ERROR"},
    "ERROR": {"RETRY": "READY", "CLOSE": "CLOSED"},
    "CLOSED": {},
}
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

ERRORS = {
    "INVALID_JSON": "Message is not strict JSON.",
    "MESSAGE_TOO_LARGE": "Message exceeds the one MiB wire limit.",
    "INVALID_SCHEMA": "Record shape or field value is invalid.",
    "UNSUPPORTED_PROTOCOL": "Protocol major or minor version is unsupported.",
    "REFUSE_CONTEXT_ACCESS": "Identity or project binding does not match.",
    "REFUSE_PERMISSION": "The current host grant lacks a required capability.",
    "REFUSE_MODE_ESCALATION": "The requested mode exceeds host authority.",
    "STALE_CONSENT": "Consent revision is stale.",
    "STALE_SOURCE": "Source or capture epoch is stale.",
    "STALE_GEOMETRY": "Overlay geometry revision is stale.",
    "CANCELLED_GENERATION": "Work belongs to an old cancellation generation.",
    "EXPIRED_OBSERVATION": "Observation is no longer fresh.",
    "SUPPRESS_STALE_RESPONSE": "A late result cannot cross this stage.",
    "REFUSE_MODE_ACTION": "This mode cannot request execution.",
}


class ContractViolation(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        self.detail = detail or ERRORS.get(code, code)
        super().__init__(f"{code}: {self.detail}")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractViolation("INVALID_JSON", f"duplicate key: {key}")
        result[key] = value
    return result


def _nonfinite(value):
    raise ContractViolation("INVALID_JSON", f"non-finite number: {value}")


def decode_wire(payload):
    """Decode bounded strict JSON without first allocating an oversized string."""
    if isinstance(payload, str):
        try:
            raw = payload.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ContractViolation("INVALID_JSON", str(exc)) from exc
    elif isinstance(payload, bytes):
        raw = payload
    else:
        raise ContractViolation("INVALID_JSON", "wire payload must be bytes or text")
    if len(raw) > MAX_WIRE_BYTES:
        raise ContractViolation("MESSAGE_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_nonfinite)
    except ContractViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractViolation("INVALID_JSON", str(exc)) from exc
    if not isinstance(value, dict):
        raise ContractViolation("INVALID_SCHEMA", "top level must be an object")
    return value


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def negotiate_protocol(offered):
    if not isinstance(offered, str) or not re.fullmatch(r"\d+\.\d+", offered):
        raise ContractViolation("UNSUPPORTED_PROTOCOL", "expected major.minor")
    major, minor = map(int, offered.split("."))
    if major != 1 or minor > 1:
        raise ContractViolation("UNSUPPORTED_PROTOCOL", offered)
    return {"selected": PROTOCOL_CURRENT if minor >= 1 else PROTOCOL_MINIMUM,
            "compatible": True}


def _record(record, required, optional=()):
    if not isinstance(record, dict):
        raise ContractViolation("INVALID_SCHEMA", "record must be an object")
    keys, allowed = set(record), set(required) | set(optional)
    missing, unknown = set(required) - keys, keys - allowed
    if missing or unknown:
        raise ContractViolation("INVALID_SCHEMA",
                                f"missing={sorted(missing)} unknown={sorted(unknown)}")
    return record


def _ident(value, name):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractViolation("INVALID_SCHEMA", f"invalid {name}")
    return value


def _string(value, name, maximum, nullable=False):
    if value is None and nullable:
        return value
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractViolation("INVALID_SCHEMA", f"invalid {name}")
    return value


def _integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractViolation("INVALID_SCHEMA", f"invalid {name}")
    return value


def _enum(value, name, choices):
    if value not in choices or not isinstance(value, str):
        raise ContractViolation("INVALID_SCHEMA", f"invalid {name}: {value!r}")
    return value


def _ident_list(value, name, maximum=64):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractViolation("INVALID_SCHEMA", f"invalid {name}")
    result = [_ident(item, name) for item in value]
    if len(set(result)) != len(result):
        raise ContractViolation("INVALID_SCHEMA", f"duplicate {name}")
    return result


def _ok(record_id, **extra):
    return {"allowed": True, "reason_code": "OK", "record_id": record_id,
            **extra}


def _deny(exc, record_id=None, **extra):
    return {"allowed": False, "reason_code": exc.code,
            "record_id": record_id, "detail": exc.detail, **extra}


def _identity(record, current):
    for field in ("user_id", "tenant_id", "project_id"):
        if record[field] != current.get(field):
            raise ContractViolation("REFUSE_CONTEXT_ACCESS", field)


def validate_session_transition(current_state, event, proposed_state):
    """Validate the UI session machine without changing Fleet task state."""
    try:
        _enum(current_state, "current_state", SESSION_STATES)
        _ident(event, "event")
        _enum(proposed_state, "proposed_state", SESSION_STATES)
        expected = SESSION_TRANSITIONS[current_state].get(event)
        if expected != proposed_state:
            raise ContractViolation("INVALID_SCHEMA",
                                    f"{current_state}+{event} cannot become {proposed_state}")
        return _ok(None, state=proposed_state)
    except ContractViolation as exc:
        return _deny(exc)


def validate_session_grant_view(record, current):
    record_id = record.get("session_id") if isinstance(record, dict) else None
    try:
        required = ("schema", "revision", "session_id", "user_id", "tenant_id",
                    "project_id", "source_ids", "capabilities", "purpose",
                    "granted_by_ref", "consent_revision", "valid_from_monotonic_ms",
                    "expires_at_monotonic_ms", "provider_destinations",
                    "retention_policy_id", "budget_policy_id",
                    "cancellation_generation")
        _record(record, required)
        if record["schema"] != "fleet.tutor.session_grant_view.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        for field in ("revision", "session_id", "user_id", "tenant_id", "project_id",
                      "purpose", "granted_by_ref", "consent_revision",
                      "retention_policy_id", "budget_policy_id"):
            _ident(record[field], field)
        sources = _ident_list(record["source_ids"], "source_ids")
        capabilities = _ident_list(record["capabilities"], "capabilities")
        _ident_list(record["provider_destinations"], "provider_destinations")
        known = frozenset().union(*MODE_CAPABILITIES.values())
        if not set(capabilities).issubset(known):
            raise ContractViolation("REFUSE_PERMISSION", "unknown capability")
        start = _integer(record["valid_from_monotonic_ms"], "valid_from_monotonic_ms")
        end = _integer(record["expires_at_monotonic_ms"], "expires_at_monotonic_ms")
        generation = _integer(record["cancellation_generation"], "cancellation_generation")
        now = _integer(current.get("now_monotonic_ms"), "now_monotonic_ms")
        if not start <= now < end:
            raise ContractViolation("REFUSE_PERMISSION", "grant outside validity interval")
        _identity(record, current); _epoch(record, current)
        if generation != current.get("cancellation_generation"):
            raise ContractViolation("CANCELLED_GENERATION")
        if not set(sources).issubset(set(current.get("source_ids", ()))):
            raise ContractViolation("STALE_SOURCE", "source_ids")
        return _ok(record_id, capabilities=sorted(capabilities), grant_created=False)
    except ContractViolation as exc:
        return _deny(exc, record_id, grant_created=False)


def _epoch(record, current):
    if record.get("consent_revision") != current.get("consent_revision"):
        raise ContractViolation("STALE_CONSENT")
    if "capture_epoch" in record and record["capture_epoch"] != current.get("capture_epoch"):
        raise ContractViolation("STALE_SOURCE", "capture_epoch")


def _geometry(value):
    required = ("coordinate_space", "source_width", "source_height", "crop",
                "model_width", "model_height", "desktop_origin_x",
                "desktop_origin_y", "native_dpi_scale")
    _record(value, required)
    if value["coordinate_space"] != "source_pixels":
        raise ContractViolation("INVALID_SCHEMA", "coordinate_space")
    for field in ("source_width", "source_height", "model_width", "model_height"):
        _integer(value[field], field, 1)
    placement = [value[field] for field in ('desktop_origin_x', 'desktop_origin_y', 'native_dpi_scale')]
    if not all(part is None for part in placement):
        for field in ("desktop_origin_x", "desktop_origin_y"):
            if isinstance(value[field], bool) or not isinstance(value[field], int):
                raise ContractViolation("INVALID_SCHEMA", field)
        scale = value["native_dpi_scale"]
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
            raise ContractViolation("INVALID_SCHEMA", "native_dpi_scale")
    crop = _record(value["crop"], ("x", "y", "width", "height"))
    _integer(crop["x"], "crop.x"); _integer(crop["y"], "crop.y")
    _integer(crop["width"], "crop.width", 1); _integer(crop["height"], "crop.height", 1)
    if crop["x"] + crop["width"] > value["source_width"] or crop["y"] + crop["height"] > value["source_height"]:
        raise ContractViolation("INVALID_SCHEMA", "crop outside source")


def validate_observation(record, current):
    record_id = record.get("observation_id") if isinstance(record, dict) else None
    try:
        required = ("schema", "observation_id", "session_id", "capture_epoch",
                    "source_id", "source_kind", "source_revision", "user_id",
                    "tenant_id", "project_id", "consent_revision", "captured_at_utc",
                    "captured_at_monotonic_ms", "expires_at_monotonic_ms",
                    "geometry_revision", "geometry", "modalities", "media",
                    "artifact_ref", "content_sha256", "retention_policy_id")
        _record(record, required)
        if record["schema"] != "fleet.tutor.observation.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        for field in ("observation_id", "session_id", "source_id",
                      "source_revision", "user_id", "tenant_id", "project_id",
                      "consent_revision", "geometry_revision", "retention_policy_id"):
            _ident(record[field], field)
        _enum(record["source_kind"], "source_kind", SOURCE_KINDS)
        _integer(record["capture_epoch"], "capture_epoch")
        start = _integer(record["captured_at_monotonic_ms"], "captured_at_monotonic_ms")
        end = _integer(record["expires_at_monotonic_ms"], "expires_at_monotonic_ms")
        if end <= start or not isinstance(record["captured_at_utc"], str) or not UTC.fullmatch(record["captured_at_utc"]):
            raise ContractViolation("INVALID_SCHEMA", "timestamps")
        _geometry(record["geometry"])
        modalities = _ident_list(record["modalities"], "modalities", 16)
        if not set(modalities).issubset(MODALITIES):
            raise ContractViolation("INVALID_SCHEMA", "unknown modality")
        if record["media"] is not None and not isinstance(record["media"], dict):
            raise ContractViolation("INVALID_SCHEMA", "media")
        _string(record["artifact_ref"], "artifact_ref", 512)
        if not isinstance(record["content_sha256"], str) or not SHA256.fullmatch(record["content_sha256"]):
            raise ContractViolation("INVALID_SCHEMA", "content_sha256")
        _identity(record, current); _epoch(record, current)
        if current.get("session_id") is not None and record["session_id"] != current["session_id"]:
            raise ContractViolation("REFUSE_CONTEXT_ACCESS", "session_id")
        if record["source_id"] not in current.get("source_ids", ()):
            raise ContractViolation("STALE_SOURCE", "source_id")
        if record["source_revision"] != current.get("source_revisions", {}).get(record["source_id"]):
            raise ContractViolation("STALE_SOURCE", "source_revision")
        if current.get("artifact_refs") is not None and record["artifact_ref"] not in current["artifact_refs"]:
            raise ContractViolation("STALE_SOURCE", "artifact_ref")
        now = _integer(current.get("now_monotonic_ms"), "now_monotonic_ms")
        if now >= end:
            raise ContractViolation("EXPIRED_OBSERVATION")
        required_modalities = set(current.get("required_modalities", ()))
        unavailable = sorted(required_modalities - set(modalities))
        return _ok(record_id, unavailable_modalities=unavailable,
                   answer_scope="LIMITED" if unavailable else "FULL")
    except ContractViolation as exc:
        return _deny(exc, record_id)


MODE_CAPABILITIES = {
    "EXPLAIN": frozenset(("observe", "explain")),
    "GUIDE": frozenset(("observe", "explain", "annotate")),
    "COLLABORATE": frozenset(("observe", "explain", "annotate", "input")),
    "DELEGATE": frozenset(("observe", "explain", "annotate", "input", "execute")),
}


def validate_mode_transition(current_mode, requested_mode, actor, grant_view,
                             explicit_owner_request=False):
    try:
        _enum(current_mode, "current_mode", MODES)
        _enum(requested_mode, "requested_mode", MODES)
        _enum(actor, "actor", ("OWNER", "LEARNER", "MODEL", "SYSTEM"))
        if not isinstance(grant_view, (set, frozenset, list, tuple)):
            raise ContractViolation("REFUSE_PERMISSION", "invalid grant view")
        try:
            grants = frozenset(grant_view)
        except TypeError as exc:
            raise ContractViolation("REFUSE_PERMISSION", "invalid grant view") from exc
        if any(not isinstance(capability, str) for capability in grants):
            raise ContractViolation("REFUSE_PERMISSION", "invalid capability")
        unknown = grants - frozenset().union(*MODE_CAPABILITIES.values())
        if unknown:
            raise ContractViolation("REFUSE_PERMISSION", "unknown capability")
        if MODES.index(requested_mode) > MODES.index(current_mode):
            if actor != "OWNER" or not explicit_owner_request:
                raise ContractViolation("REFUSE_MODE_ESCALATION")
        required = MODE_CAPABILITIES[requested_mode]
        if not required.issubset(grants):
            raise ContractViolation("REFUSE_PERMISSION",
                                    f"missing {sorted(required - grants)}")
        return _ok(None, effective_mode=requested_mode,
                   capabilities=sorted(required & grants))
    except ContractViolation as exc:
        return _deny(exc)


def authorize_tutor_request(record, owner_state):
    record_id = record.get("request_id") if isinstance(record, dict) else None
    try:
        required = ("schema", "request_id", "session_id", "user_id", "tenant_id",
                    "project_id", "mode", "learning_intent", "question",
                    "observation_ids", "source_ids", "skill_ids", "consent_revision",
                    "cancellation_generation", "budget_reservation_id",
                    "retention_policy_id", "deadline_monotonic_ms",
                    "research_scope", "output_preferences")
        _record(record, required)
        if record["schema"] != "fleet.tutor.request.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        for field in ("request_id", "session_id", "user_id", "tenant_id",
                      "project_id", "budget_reservation_id", "retention_policy_id"):
            _ident(record[field], field)
        _enum(record["mode"], "mode", MODES)
        _enum(record["learning_intent"], "learning_intent", LEARNING_INTENTS)
        _string(record["question"], "question", 8192)
        deadline = _integer(record["deadline_monotonic_ms"], "deadline_monotonic_ms", 1)
        if deadline <= owner_state.get("now_monotonic_ms", deadline):
            raise ContractViolation("REFUSE_PERMISSION", "deadline already elapsed")
        if (owner_state.get("grant_expires_at_monotonic_ms") is not None
                and deadline > owner_state["grant_expires_at_monotonic_ms"]):
            raise ContractViolation("REFUSE_PERMISSION", "deadline exceeds grant")
        _enum(record["research_scope"], "research_scope",
              ("SOURCE_ONLY", "PERMITTED_RESEARCH"))
        preferences = _record(record["output_preferences"],
                              ("response_format", "speech", "locale"))
        _enum(preferences["response_format"], "response_format", ("TEXT", "TEXT_AND_SCENE"))
        if not isinstance(preferences["speech"], bool):
            raise ContractViolation("INVALID_SCHEMA", "output_preferences.speech")
        _string(preferences["locale"], "output_preferences.locale", 32)
        for field in ("observation_ids", "source_ids", "skill_ids"):
            _ident_list(record[field], field)
        _ident(record["consent_revision"], "consent_revision")
        _integer(record["cancellation_generation"], "cancellation_generation")
        _identity(record, owner_state); _epoch(record, owner_state)
        if record["cancellation_generation"] != owner_state.get("cancellation_generation"):
            raise ContractViolation("CANCELLED_GENERATION")
        if not set(record["source_ids"]).issubset(set(owner_state.get("source_ids", ()))):
            raise ContractViolation("STALE_SOURCE", "source_ids")
        if not set(record["observation_ids"]).issubset(set(owner_state.get("observation_ids", ()))):
            raise ContractViolation("STALE_SOURCE", "observation_ids")
        for field, state_field in (("budget_reservation_id", "budget_reservation_ids"),
                                   ("retention_policy_id", "retention_policy_ids")):
            allowed_refs = owner_state.get(state_field)
            if allowed_refs is not None and record[field] not in allowed_refs:
                raise ContractViolation("REFUSE_PERMISSION", field)
        request_digest = hashlib.sha256(canonical_json(record).encode("ascii")).hexdigest()
        prior_digest = owner_state.get("request_digests", {}).get(record["request_id"])
        if prior_digest is not None and prior_digest != request_digest:
            raise ContractViolation("INVALID_SCHEMA", "request_id conflicts with prior payload")
        transition = validate_mode_transition(owner_state.get("mode"), record["mode"],
                                              owner_state.get("actor", "SYSTEM"),
                                              owner_state.get("grant_view", ()),
                                              owner_state.get("explicit_owner_request", False))
        if not transition["allowed"]:
            raise ContractViolation(transition["reason_code"], transition.get("detail", ""))
        return _ok(record_id, effective_mode=record["mode"],
                   capabilities=transition["capabilities"], grant_created=False,
                   request_digest=request_digest,
                   idempotent_replay=prior_digest == request_digest)
    except ContractViolation as exc:
        return _deny(exc, record_id, grant_created=False)


def check_generation(expected, current, stage):
    try:
        _enum(stage, "stage", STAGES)
        _integer(expected, "expected_generation"); _integer(current, "current_generation")
        if expected != current:
            code = "CANCELLED_GENERATION" if stage in ("capture", "retrieval") else "SUPPRESS_STALE_RESPONSE"
            raise ContractViolation(code, stage)
        return _ok(None, stage=stage)
    except ContractViolation as exc:
        return _deny(exc, stage=stage)


def validate_instruction(record, observation, policy):
    record_id = record.get("request_id") if isinstance(record, dict) else None
    try:
        required = ("schema", "request_id", "move", "answer", "claims",
                    "annotations", "requested_response", "reveal_level",
                    "expected_progress", "execution_request")
        _record(record, required)
        if record["schema"] != "fleet.tutor.instruction.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        _ident(record["request_id"], "request_id")
        _string(record["move"], "move", 128); _string(record["answer"], "answer", 32768)
        _enum(record["reveal_level"], "reveal_level", ("NONE", "HINT", "PARTIAL", "DIRECT"))
        _string(record["requested_response"], "requested_response", 2048)
        progress = _record(record["expected_progress"], ("kind", "scope"))
        _ident(progress["kind"], "expected_progress.kind")
        _string(progress["scope"], "expected_progress.scope", 2048)
        if not isinstance(record["claims"], list) or len(record["claims"]) > 128:
            raise ContractViolation("INVALID_SCHEMA", "claims")
        for claim in record["claims"]:
            _record(claim, ("kind", "text", "evidence_refs", "uncertainty"))
            _ident(claim["kind"], "claim.kind"); _string(claim["text"], "claim.text", 4096)
            _ident_list(claim["evidence_refs"], "claim.evidence_refs")
            if isinstance(claim["uncertainty"], bool) or not isinstance(claim["uncertainty"], (int, float)) or not 0 <= claim["uncertainty"] <= 1:
                raise ContractViolation("INVALID_SCHEMA", "claim.uncertainty")
        if not isinstance(record["annotations"], list) or len(record["annotations"]) > 128:
            raise ContractViolation("INVALID_SCHEMA", "annotations")
        for annotation in record["annotations"]:
            _record(annotation, ("primitive", "observation_id", "target_id", "label", "geometry_revision"))
            _enum(annotation["primitive"], "annotation.primitive", ("RECT", "ARROW", "POINT", "LABEL"))
            for field in ("observation_id", "target_id", "geometry_revision"):
                _ident(annotation[field], field)
            _string(annotation["label"], "annotation.label", 512)
            if annotation["observation_id"] != observation.get("observation_id"):
                raise ContractViolation("STALE_SOURCE", "annotation observation")
            if observation.get('geometry', {}).get('desktop_origin_x') is None:
                raise ContractViolation('INVALID_SCHEMA', 'annotation requires verified desktop placement')
            if annotation["geometry_revision"] != observation.get("geometry_revision"):
                raise ContractViolation("STALE_GEOMETRY")
        if record["execution_request"] is not None:
            execution = _record(record["execution_request"],
                                ("operation", "target_id", "justification"))
            _ident(execution["operation"], "execution_request.operation")
            _ident(execution["target_id"], "execution_request.target_id")
            _string(execution["justification"], "execution_request.justification", 2048)
        mode = _enum(policy.get("mode"), "policy.mode", MODES)
        if mode in ("EXPLAIN", "GUIDE") and record["execution_request"] is not None:
            raise ContractViolation("REFUSE_MODE_ACTION")
        gate = check_generation(policy.get("cancellation_generation"),
                                policy.get("current_cancellation_generation"), "render")
        if not gate["allowed"]:
            raise ContractViolation(gate["reason_code"], gate.get("detail", ""))
        if policy.get("request_id") is not None and record["request_id"] != policy["request_id"]:
            raise ContractViolation("REFUSE_CONTEXT_ACCESS", "request_id")
        return _ok(record_id)
    except ContractViolation as exc:
        return _deny(exc, record_id)


def validate_evidence_event(record, current):
    record_id = record.get("event_id") if isinstance(record, dict) else None
    try:
        required = ("schema", "event_id", "attempt_id", "session_id", "user_id",
                    "tenant_id", "project_id", "actor", "assistance", "kind",
                    "artifact_digest", "tutor_version", "source_revision",
                    "consent_revision", "recorded_at_utc")
        _record(record, required)
        if record["schema"] != "fleet.tutor.learner_evidence.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        for field in ("event_id", "attempt_id", "session_id", "user_id", "tenant_id",
                      "project_id", "kind", "tutor_version", "source_revision",
                      "consent_revision"):
            _ident(record[field], field)
        _enum(record["actor"], "actor", ACTORS); _enum(record["assistance"], "assistance", ASSISTANCE)
        if (not isinstance(record["artifact_digest"], str)
                or not SHA256.fullmatch(record["artifact_digest"])
                or not isinstance(record["recorded_at_utc"], str)
                or not UTC.fullmatch(record["recorded_at_utc"])):
            raise ContractViolation("INVALID_SCHEMA", "digest or UTC timestamp")
        _identity(record, current); _epoch(record, current)
        revisions = set(current.get("source_revisions", {}).values())
        if revisions and record["source_revision"] not in revisions:
            raise ContractViolation("STALE_SOURCE", "source_revision")
        return _ok(record_id)
    except ContractViolation as exc:
        return _deny(exc, record_id)


def classify_learning_attempt(attempt, exposures):
    """Classify eligibility, never whether the work is correct or mastered."""
    if attempt.get("invalidated") or any(x.get("invalidated") for x in exposures):
        return {"classification": "INVALIDATED", "success": None}
    if attempt.get("assessable") is not True:
        return {"classification": "NOT_ASSESSABLE", "success": None}
    answer_revealing = any(x.get("assistance") in ("ANSWER", "EXECUTION") for x in exposures)
    assisted = answer_revealing or any(x.get("actor") in ("AGENT", "SHARED") or
                                       x.get("assistance") == "HINT" for x in exposures)
    return {"classification": "ASSISTED" if assisted else "INDEPENDENT_ELIGIBLE",
            "success": None}


def build_learner_projection(events):
    projection = {"NOT_ASSESSABLE": 0, "ASSISTED": 0,
                  "INDEPENDENT_ELIGIBLE": 0, "INVALIDATED": 0}
    for event in events:
        result = classify_learning_attempt(event.get("attempt", {}), event.get("exposures", []))
        projection[result["classification"]] += 1
    return {"schema": "fleet.tutor.learner_projection.v1", "counts": projection,
            "mastery": None}


def validate_teaching_pack(pack, source_manifest):
    try:
        _record(pack, ("schema", "pack_id", "source_refs", "moves", "content_sha256"))
        if pack["schema"] != "fleet.tutor.teaching_pack.v1":
            raise ContractViolation("INVALID_SCHEMA", "schema")
        _ident(pack["pack_id"], "pack_id"); refs = _ident_list(pack["source_refs"], "source_refs")
        if not refs or not set(refs).issubset(set(source_manifest)):
            raise ContractViolation("STALE_SOURCE", "source manifest")
        if not isinstance(pack["moves"], list) or not pack["moves"]:
            raise ContractViolation("INVALID_SCHEMA", "moves")
        if not SHA256.fullmatch(pack["content_sha256"] or ""):
            raise ContractViolation("INVALID_SCHEMA", "content_sha256")
        return _ok(pack["pack_id"])
    except ContractViolation as exc:
        return _deny(exc, pack.get("pack_id") if isinstance(pack, dict) else None)


def fixture_bundle():
    """The sole source for Python/native conformance fixtures."""
    observation = {
        "schema": "fleet.tutor.observation.v1", "observation_id": "obs-1",
        "session_id": "session-1", "capture_epoch": 7, "source_id": "source-1",
        "source_kind": "WINDOW", "source_revision": "source-r4", "user_id": "user-1",
        "tenant_id": "tenant-1", "project_id": "project-1", "consent_revision": "consent-r3",
        "captured_at_utc": "2026-09-15T12:00:00Z", "captured_at_monotonic_ms": 1000,
        "expires_at_monotonic_ms": 5000, "geometry_revision": "geometry-r2",
        "geometry": {"coordinate_space": "source_pixels", "source_width": 1920,
                     "source_height": 1080, "crop": {"x": 0, "y": 0, "width": 1920, "height": 1080},
                     "model_width": 1280, "model_height": 720, "desktop_origin_x": 0,
                     "desktop_origin_y": 0, "native_dpi_scale": 1.0},
        "modalities": ["pixels", "accessibility"], "media": None,
        "artifact_ref": "artifact-1", "content_sha256": hashlib.sha256(b"fixture").hexdigest(),
        "retention_policy_id": "retention-1"}
    grant_view = {"schema": "fleet.tutor.session_grant_view.v1", "revision": "grant-r2",
                  "session_id": "session-1", "user_id": "user-1", "tenant_id": "tenant-1",
                  "project_id": "project-1", "source_ids": ["source-1"],
                  "capabilities": ["observe", "explain", "annotate"], "purpose": "guided-learning",
                  "granted_by_ref": "owner-confirmation-1", "consent_revision": "consent-r3",
                  "valid_from_monotonic_ms": 500, "expires_at_monotonic_ms": 9000,
                  "provider_destinations": [], "retention_policy_id": "retention-1",
                  "budget_policy_id": "budget-policy-1", "cancellation_generation": 4}
    request = {"schema": "fleet.tutor.request.v1", "request_id": "request-1",
               "session_id": "session-1", "user_id": "user-1", "tenant_id": "tenant-1",
               "project_id": "project-1", "mode": "GUIDE", "learning_intent": "LEARN",
               "question": "Show me the next safe step.", "observation_ids": ["obs-1"],
               "source_ids": ["source-1"], "skill_ids": ["skill-1"],
               "consent_revision": "consent-r3", "cancellation_generation": 4,
               "budget_reservation_id": "budget-1", "retention_policy_id": "retention-1",
               "deadline_monotonic_ms": 8000, "research_scope": "SOURCE_ONLY",
               "output_preferences": {"response_format": "TEXT_AND_SCENE", "speech": False,
                                      "locale": "en-CA"}}
    instruction = {"schema": "fleet.tutor.instruction.v1", "request_id": "request-1",
                   "move": "POINT_AND_ASK", "answer": "Select the highlighted cell.",
                   "claims": [{"kind": "GROUNDING", "text": "The total cell is visible.",
                               "evidence_refs": ["obs-1"], "uncertainty": 0.05}],
                   "annotations": [{"primitive": "RECT", "observation_id": "obs-1",
                                    "target_id": "cell-a1", "label": "Total",
                                    "geometry_revision": "geometry-r2"}],
                   "requested_response": "Tell me the displayed value.", "reveal_level": "HINT",
                   "expected_progress": {"kind": "OBSERVE", "scope": "cell-a1"},
                   "execution_request": None}
    evidence = {"schema": "fleet.tutor.learner_evidence.v1", "event_id": "event-1",
                "attempt_id": "attempt-1", "session_id": "session-1", "user_id": "user-1",
                "tenant_id": "tenant-1", "project_id": "project-1", "actor": "USER",
                "assistance": "HINT", "kind": "ARTIFACT", "artifact_digest": hashlib.sha256(b"answer").hexdigest(),
                "tutor_version": "tutor-r1", "source_revision": "source-r4",
                "consent_revision": "consent-r3", "recorded_at_utc": "2026-09-15T12:01:00Z"}
    return {"protocol": PROTOCOL_CURRENT, "minimum_protocol": PROTOCOL_MINIMUM,
            "records": {"grant_view": grant_view, "observation": observation, "request": request,
                        "instruction": instruction, "evidence": evidence}}


def fixture_bytes():
    return (canonical_json(fixture_bundle()) + "\n").encode("ascii")


def upgrade_fixture(bundle):
    upgraded = deepcopy(bundle)
    upgraded["protocol"] = PROTOCOL_CURRENT
    return upgraded


def downgrade_fixture(bundle):
    downgraded = deepcopy(bundle)
    downgraded["protocol"] = PROTOCOL_MINIMUM
    return downgraded
