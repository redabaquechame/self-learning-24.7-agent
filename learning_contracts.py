#!/usr/bin/env python3
"""One host-authorized learning contract for every product surface.

This is the in-process boundary, not a public HTTP API. Frontends receive an
adapter whose authority was sealed by the host. Branding and request payloads
cannot supply a principal, tenant, entitlement, grant, policy revision, score,
or passing state. Later learning packets add domain depth behind this contract;
they do not fork it per surface.
"""

import base64
import copy
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


API_VERSION = "learning.v1"
# Contract constants are code-owned and never accepted from a surface payload.
SURFACES = frozenset(("main_learn", "native_companion",
                      "standalone_portal", "embed_sdk"))
RETENTION_CLASSES = frozenset(("operational", "assessment", "ephemeral"))
BRAND_FIELDS = frozenset(("title", "logo_url", "accent_color"))
AUTHORITY_FIELDS = frozenset((
    "principal", "principal_id", "learner_id", "tenant", "tenant_id",
    "role", "roles", "entitlement", "entitlements", "grant", "grants",
    "local_grant", "local_grants", "policy_revision", "grant_revision",
    "score", "passed", "verdict", "authority",
))


class ContractError(ValueError):
    """The request does not satisfy the versioned learning contract."""


class Unauthorized(ContractError):
    """The sealed host identity does not hold the required entitlement."""


class Conflict(ContractError):
    """An idempotency key or state transition conflicts with prior truth."""


class NotFound(ContractError):
    """A tenant-scoped record is unavailable to this principal."""


@dataclass(frozen=True)
class HostBinding:
    principal_id: str
    tenant_id: str
    policy_revision: str
    grant_revision: str
    course_revision: str
    entitlements: frozenset = field(default_factory=frozenset)
    local_capabilities: frozenset = field(default_factory=frozenset)
    _seal: str = field(default="", repr=False, compare=False)


OPERATION_CATALOG = {
    "learning.capabilities": {
        "entitlement": "learning:read", "mutation": False,
        "availability": "implemented",
    },
    "course.register": {
        "entitlement": "course:write", "mutation": True,
        "availability": "implemented",
    },
    "assignment.create": {
        "entitlement": "assignment:write", "mutation": True,
        "availability": "implemented",
    },
    "session.open": {
        "entitlement": "session:write", "mutation": True,
        "availability": "implemented",
    },
    "attempt.begin": {
        "entitlement": "attempt:write", "mutation": True,
        "availability": "implemented",
    },
    "evidence.append": {
        "entitlement": "evidence:write", "mutation": True,
        "availability": "implemented",
    },
    "attempt.submit": {
        "entitlement": "attempt:write", "mutation": True,
        "availability": "implemented",
    },
    "records.list": {
        "entitlement": "learning:read", "mutation": False,
        "availability": "implemented",
    },
    "request.cancel": {
        "entitlement": "session:write", "mutation": True,
        "availability": "implemented",
    },
    "curriculum.import": {
        "entitlement": "course:write", "mutation": True,
        "availability": "reserved_for_SC-1C",
    },
    "curriculum.review": {
        "entitlement": "course:review", "mutation": True,
        "availability": "reserved_for_SC-1C",
    },
    "assessment.evaluate": {
        "entitlement": "assessment:evaluate", "mutation": True,
        "availability": "reserved_for_SC-2F",
    },
    "evidence.correct": {
        "entitlement": "evidence:correct", "mutation": True,
        "availability": "reserved_for_SC-2E",
    },
    "learning.export": {
        "entitlement": "learning:export", "mutation": True,
        "availability": "reserved_for_retention_packet",
    },
    "learning.delete": {
        "entitlement": "learning:delete", "mutation": True,
        "availability": "reserved_for_retention_packet",
    },
    "handoff.propose": {
        "entitlement": "handoff:propose", "mutation": True,
        "availability": "reserved_for_fleet_handoff_packet",
    },
}


_PAYLOADS = {
    "learning.capabilities": (frozenset(), frozenset()),
    "course.register": (
        frozenset(("title", "course_revision")),
        frozenset(("retention_class",))),
    "assignment.create": (
        frozenset(("course_id", "assignee_id")),
        frozenset(("due_policy", "retention_class"))),
    "session.open": (
        frozenset(),
        frozenset(("assignment_id", "objective", "intention",
                   "retention_class"))),
    "attempt.begin": (
        frozenset(("session_id", "variant_revision")),
        frozenset(("assignment_id", "retention_class"))),
    "evidence.append": (
        frozenset(("attempt_id", "evidence_kind", "digest")),
        frozenset(("assistance", "retention_class"))),
    "attempt.submit": (
        frozenset(("attempt_id", "artifact_digests")),
        frozenset(("retention_class",))),
    "records.list": (
        frozenset(), frozenset(("kind", "limit", "cursor"))),
    "request.cancel": (
        frozenset(("target_id", "reason")), frozenset()),
    "assessment.evaluate": (frozenset(("submission_id",)), frozenset()),
}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value, name, maximum=200):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise ContractError(f"{name} exceeds {maximum} characters")
    return value.strip()


def _copy(value):
    return copy.deepcopy(value)


class LearningService:
    """Thread-safe, in-process authoritative contract and record projection."""

    def __init__(self, clock=None, host_key=None, cursor_key=None, human_assessment=None):
        if human_assessment is not None:
            from tutor_assessment import HumanAssessmentAuthority, HumanAssessmentDirectory
            if not isinstance(human_assessment, (HumanAssessmentAuthority, HumanAssessmentDirectory)):
                raise ContractError("typed host human assessment authority is required")
        self._human_assessment = human_assessment
        self._clock = clock or (lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                     time.gmtime()))
        self._host_key = host_key or secrets.token_bytes(32)
        self._cursor_key = cursor_key or secrets.token_bytes(32)
        self._records = {}
        self._events = []
        self._idempotency = {}
        self._sequence = 0
        self._lock = threading.RLock()

    def _binding_body(self, binding):
        return {
            "principal_id": binding.principal_id,
            "tenant_id": binding.tenant_id,
            "policy_revision": binding.policy_revision,
            "grant_revision": binding.grant_revision,
            "course_revision": binding.course_revision,
            "entitlements": sorted(binding.entitlements),
            "local_capabilities": sorted(binding.local_capabilities),
        }

    def bind_host(self, principal_id, tenant_id, policy_revision,
                  grant_revision, course_revision, entitlements,
                  local_capabilities=()):
        """Seal values supplied by the authenticated host boundary."""
        values = {
            "principal_id": _text(principal_id, "principal_id", 160),
            "tenant_id": _text(tenant_id, "tenant_id", 160),
            "policy_revision": _text(
                policy_revision, "policy_revision", 160),
            "grant_revision": _text(grant_revision, "grant_revision", 160),
            "course_revision": _text(
                course_revision, "course_revision", 160),
            "entitlements": frozenset(
                _text(item, "entitlement", 100) for item in entitlements),
            "local_capabilities": frozenset(
                _text(item, "local_capability", 100)
                for item in local_capabilities),
        }
        unsigned = HostBinding(**values)
        seal = hmac.new(self._host_key,
                        _canonical(self._binding_body(unsigned)).encode(),
                        hashlib.sha256).hexdigest()
        return HostBinding(**values, _seal=seal)

    def _verify_binding(self, binding):
        if not isinstance(binding, HostBinding):
            raise Unauthorized("host binding is missing")
        expected = hmac.new(
            self._host_key,
            _canonical(self._binding_body(binding)).encode(),
            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, binding._seal):
            raise Unauthorized("host binding is forged or belongs to another service")

    def adapter(self, surface, binding, branding=None):
        self._verify_binding(binding)
        return LearningAdapter(self, surface, binding, branding or {})

    def _authorize(self, binding, operation):
        spec = OPERATION_CATALOG.get(operation)
        if not spec:
            raise ContractError(f"unknown operation {operation!r}")
        if operation == "assessment.evaluate" and self._human_assessment is not None:
            spec = {**spec, "availability": "implemented"}
        if spec["availability"] != "implemented":
            raise ContractError(
                f"{operation} is contract-reserved and not implemented")
        required = spec["entitlement"]
        if required not in binding.entitlements:
            raise Unauthorized(f"missing host entitlement {required}")
        return spec

    def _validate_envelope(self, envelope):
        if not isinstance(envelope, dict) or set(envelope) != {
                "api_version", "request_id", "operation",
                "idempotency_key", "payload"}:
            raise ContractError("command envelope fields do not match learning.v1")
        if envelope["api_version"] != API_VERSION:
            raise ContractError(
                f"unsupported api_version {envelope['api_version']!r}")
        _text(envelope["request_id"], "request_id", 160)
        operation = _text(envelope["operation"], "operation", 100)
        payload = envelope["payload"]
        if not isinstance(payload, dict):
            raise ContractError("payload must be an object")
        forbidden = sorted(AUTHORITY_FIELDS.intersection(payload))
        if forbidden:
            raise Unauthorized(
                "request payload cannot supply host authority: "
                + ", ".join(forbidden))
        if operation not in _PAYLOADS:
            return operation, payload
        if operation == "assessment.evaluate" and self._human_assessment is None:
            return operation, payload
        required, optional = _PAYLOADS[operation]
        missing = sorted(required - set(payload))
        unknown = sorted(set(payload) - required - optional)
        if missing or unknown:
            raise ContractError(
                f"invalid {operation} payload; missing={missing}, unknown={unknown}")
        return operation, payload

    def dispatch(self, surface, binding, envelope):
        self._verify_binding(binding)
        if surface not in SURFACES:
            raise ContractError(f"unknown learning surface {surface!r}")
        operation, payload = self._validate_envelope(envelope)
        spec = self._authorize(binding, operation)
        key = envelope["idempotency_key"]
        if spec["mutation"]:
            _text(key, "idempotency_key", 200)
        elif key not in (None, ""):
            raise ContractError("read operations use an empty idempotency_key")
        with self._lock:
            if spec["mutation"]:
                scope = (binding.principal_id, binding.tenant_id,
                         operation, key)
                payload_digest = _digest(payload)
                prior = self._idempotency.get(scope)
                if prior:
                    if prior["payload_digest"] != payload_digest:
                        raise Conflict(
                            "idempotency key was already bound to different content")
                    if operation == "assessment.evaluate" and self._human_assessment is not None:
                        self._human_assessment.evaluate(payload["submission_id"], binding)
                    return self._transport(
                        surface, binding, prior["response"], replay=True)
                response = self._execute(binding, operation, payload, key)
                self._idempotency[scope] = {
                    "payload_digest": payload_digest,
                    "response": _copy(response),
                }
                return self._transport(surface, binding, response, replay=False)
            response = self._execute(binding, operation, payload, key)
            return self._transport(surface, binding, response, replay=False)

    def _transport(self, surface, binding, response, replay):
        result = _copy(response)
        result["transport"] = {
            "surface": surface,
            "replay": bool(replay),
            "native_capture": (
                surface == "native_companion"
                and "capture.selected" in binding.local_capabilities),
        }
        return result

    def _new_id(self, kind, binding, operation, key, payload):
        material = {
            "kind": kind, "tenant_id": binding.tenant_id,
            "principal_id": binding.principal_id, "operation": operation,
            "idempotency_key": key, "payload_digest": _digest(payload),
        }
        return f"{kind[:3]}-{_digest(material)[:24]}"

    def _store(self, kind, binding, operation, key, payload, fields):
        record_id = self._new_id(kind, binding, operation, key, payload)
        self._sequence += 1
        record = {
            "schema": f"learning.{kind}.v1",
            "id": record_id,
            "kind": kind,
            "sequence": self._sequence,
            "tenant_id": binding.tenant_id,
            "created_by": binding.principal_id,
            "created_at": self._clock(),
            "policy_revision": binding.policy_revision,
            "grant_revision": binding.grant_revision,
            **fields,
        }
        self._records[record_id] = record
        self._events.append({
            "schema": "learning.event.v1",
            "sequence": self._sequence,
            "tenant_id": binding.tenant_id,
            "principal_id": binding.principal_id,
            "operation": operation,
            "record_id": record_id,
            "at": record["created_at"],
        })
        return _copy(record)

    def _owned(self, binding, record_id, kinds=None):
        record = self._records.get(record_id)
        if (not record or record["tenant_id"] != binding.tenant_id
                or (kinds and record["kind"] not in kinds)):
            raise NotFound("tenant-scoped learning record was not found")
        return record

    def _retention(self, payload, default="operational"):
        value = payload.get("retention_class", default)
        if value not in RETENTION_CLASSES:
            raise ContractError("unknown retention_class")
        return value

    def _execute(self, binding, operation, payload, key):
        if operation == "learning.capabilities":
            available = sorted(name for name, spec in OPERATION_CATALOG.items()
                               if (spec["availability"] == "implemented"
                                   or name == "assessment.evaluate" and self._human_assessment is not None)
                               and spec["entitlement"] in binding.entitlements)
            return {
                "schema": "learning.capabilities.v1",
                "api_version": API_VERSION,
                "operations": available,
            }
        if operation == "course.register":
            if payload["course_revision"] != binding.course_revision:
                raise Conflict("course revision differs from the host binding")
            record = self._store("course", binding, operation, key, payload, {
                "title": _text(payload["title"], "title", 300),
                "course_revision": payload["course_revision"],
                "retention_class": self._retention(payload),
                "state": "REGISTERED",
            })
            return {"record": record}
        if operation == "assignment.create":
            course = self._owned(binding, payload["course_id"], ("course",))
            record = self._store("assignment", binding, operation, key,
                                 payload, {
                "course_id": course["id"],
                "course_revision": course["course_revision"],
                "assignee_id": _text(
                    payload["assignee_id"], "assignee_id", 160),
                "due_policy": (_text(payload["due_policy"], "due_policy", 300)
                               if payload.get("due_policy") else "none"),
                "retention_class": self._retention(payload, "assessment"),
                "state": "ASSIGNED",
            })
            return {"record": record}
        if operation == "session.open":
            assignment_id = payload.get("assignment_id")
            objective = payload.get("objective")
            if bool(assignment_id) == bool(objective):
                raise ContractError(
                    "session.open needs exactly one assignment_id or objective")
            if assignment_id:
                assignment = self._owned(
                    binding, assignment_id, ("assignment",))
                if (assignment["assignee_id"] != binding.principal_id
                        and "session:write:any" not in binding.entitlements):
                    raise Unauthorized("assignment belongs to another learner")
            record = self._store("session", binding, operation, key, payload, {
                "learner_id": binding.principal_id,
                "assignment_id": assignment_id,
                "objective": (_text(objective, "objective", 500)
                              if objective else None),
                "intention": (_text(payload["intention"], "intention", 300)
                              if payload.get("intention") else ""),
                "retention_class": self._retention(payload),
                "state": "OPEN",
            })
            return {"record": record}
        if operation == "attempt.begin":
            session = self._owned(binding, payload["session_id"], ("session",))
            if session["learner_id"] != binding.principal_id:
                raise Unauthorized("session belongs to another learner")
            assignment_id = payload.get("assignment_id")
            if assignment_id and assignment_id != session.get("assignment_id"):
                raise Conflict("attempt assignment differs from its session")
            fields = {
                "learner_id": binding.principal_id,
                "session_id": session["id"],
                "assignment_id": session.get("assignment_id"),
                "variant_revision": _text(
                    payload["variant_revision"], "variant_revision", 160),
                "retention_class": self._retention(payload, "assessment"),
                "state": "ACTIVE",
                "passing": None,
            }
            if self._human_assessment is not None:
                provisional = {"id": self._new_id("attempt", binding, operation, key, payload),
                               "tenant_id": binding.tenant_id, **fields}
                custody = self._human_assessment.begin(provisional, binding)
                fields["human_custody"] = {"project_id":custody["scope"]["project_id"],
                                          "rubric_binding":custody["rubric_binding"]}
            record = self._store("attempt", binding, operation, key, payload, fields)
            return {"record": record}
        if operation == "evidence.append":
            attempt = self._owned(binding, payload["attempt_id"], ("attempt",))
            if attempt["learner_id"] != binding.principal_id:
                raise Unauthorized("attempt belongs to another learner")
            if attempt["state"] != "ACTIVE":
                raise Conflict("evidence can be appended only to an active attempt")
            digest = str(payload["digest"]).lower()
            if not all(c in "0123456789abcdef" for c in digest) or len(digest) != 64:
                raise ContractError("evidence digest must be lowercase SHA-256")
            assistance = payload.get("assistance", "UNKNOWN")
            if assistance not in ("ASSISTED", "INDEPENDENT", "UNKNOWN"):
                raise ContractError("assistance must be ASSISTED, INDEPENDENT or UNKNOWN")
            record = self._store("evidence", binding, operation, key, payload, {
                "attempt_id": attempt["id"],
                "evidence_kind": _text(
                    payload["evidence_kind"], "evidence_kind", 100),
                "digest": digest,
                "assistance": assistance,
                "retention_class": self._retention(payload, "assessment"),
            })
            return {"record": record}
        if operation == "attempt.submit":
            attempt = self._owned(binding, payload["attempt_id"], ("attempt",))
            if attempt["learner_id"] != binding.principal_id:
                raise Unauthorized("attempt belongs to another learner")
            if attempt["state"] != "ACTIVE":
                raise Conflict("only an active attempt can be submitted")
            digests = payload["artifact_digests"]
            if (not isinstance(digests, list) or not digests
                    or any(not isinstance(item, str) or len(item) != 64
                           or any(c not in "0123456789abcdef" for c in item)
                           for item in digests)):
                raise ContractError(
                    "artifact_digests must be non-empty lowercase SHA-256 values")
            if self._human_assessment is not None:
                self._human_assessment.submit({"id":self._new_id("submission",binding,operation,key,payload),
                    "attempt_id":attempt["id"],"learner_id":binding.principal_id,
                    "tenant_id":binding.tenant_id,"artifact_digests":digests},binding)
            record = self._store("submission", binding, operation, key,
                                 payload, {
                "attempt_id": attempt["id"],
                "learner_id": binding.principal_id,
                "artifact_digests": list(digests),
                "content_digest": _digest(digests),
                "retention_class": self._retention(payload, "assessment"),
                "state": "SUBMITTED",
                "passing": None,
            })
            attempt["state"] = "SUBMITTED"
            return {"record": record}
        if operation == "assessment.evaluate":
            submission = self._owned(binding,payload["submission_id"],("submission",))
            if self._human_assessment is None:
                raise ContractError("human assessment is not implemented on this host")
            verdict = self._human_assessment.evaluate(submission["id"],binding)
            for existing in self._records.values():
                if (existing["kind"] == "assessment" and existing["tenant_id"] == binding.tenant_id
                        and existing.get("submission_id") == submission["id"]
                        and existing.get("verdict_id") == verdict["verdict_id"]):
                    return {"record":_copy(existing)}
            fields = {**verdict,"learner_id":submission["learner_id"],
                      "project_id":self._human_assessment.project_for_submission(submission["id"],binding),
                      "retention_class":submission["retention_class"]}
            fields.pop("schema")
            record = self._store("assessment",binding,operation,key,payload,fields)
            attempt = self._owned(binding,submission["attempt_id"],("attempt",))
            attempt["state"] = verdict["state"]
            attempt["passing"] = verdict["passing"]
            return {"record":record}
        if operation == "records.list":
            return self._list(binding, payload)
        if operation == "request.cancel":
            target = self._owned(
                binding, payload["target_id"], ("session", "attempt"))
            if (target.get("learner_id") != binding.principal_id
                    and "learning:cancel:any" not in binding.entitlements):
                raise Unauthorized("learning record belongs to another learner")
            if target["state"] in ("SUBMITTED", "SCORED", "REVIEW_REQUIRED", "INVALIDATED", "CANCELLED"):
                raise Conflict(f"cannot cancel record in {target['state']} state")
            target["state"] = "CANCELLED"
            record = self._store("cancellation", binding, operation, key,
                                 payload, {
                "target_id": target["id"],
                "reason": _text(payload["reason"], "reason", 300),
                "retention_class": target["retention_class"],
                "state": "RECORDED",
            })
            return {"record": record}
        raise ContractError(f"operation {operation!r} has no implementation")

    def ingest_human_artifact(self, binding, attempt_id, payload):
        """Authenticated host ingress; a frontend digest alone proves no custody."""
        self._verify_binding(binding)
        if "attempt:write" not in binding.entitlements:
            raise Unauthorized("missing host entitlement attempt:write")
        if self._human_assessment is None:
            raise ContractError("human artifact ingress is unavailable")
        with self._lock:
            attempt=self._owned(binding,attempt_id,("attempt",))
            if attempt["learner_id"]!=binding.principal_id:
                raise Unauthorized("attempt belongs to another learner")
            if attempt["state"]!="ACTIVE":
                raise Conflict("human artifacts require an active attempt")
            return self._human_assessment.ingest(attempt_id,binding,payload)

    def record_human_exposure(self, binding, attempt_id, facts):
        """Host publication hook; record help before releasing it to a learner."""
        self._verify_binding(binding)
        if "attempt:write" not in binding.entitlements:
            raise Unauthorized("missing host entitlement attempt:write")
        if self._human_assessment is None:
            raise ContractError("human exposure recording is unavailable")
        with self._lock:
            self._owned(binding,attempt_id,("attempt",))
            result=self._human_assessment.record_exposure(attempt_id,binding,facts)
            for row in self._records.values():
                if row["kind"]=="assessment" and row.get("attempt_id")==attempt_id:
                    if self._human_assessment.current_projection(row["submission_id"],binding)!="CURRENT":
                        attempt=self._owned(binding,attempt_id,("attempt",))
                        attempt["state"]="REVIEW_REQUIRED";attempt["passing"]=None
            return result

    def _human_record_view(self,binding,row):
        result=_copy(row)
        if self._human_assessment is None:
            return result
        assessed=row if row["kind"]=="assessment" else next((item for item in self._records.values()
            if row["kind"]=="attempt" and item["kind"]=="assessment" and item.get("attempt_id")==row["id"]),None)
        if assessed is None:
            return result
        status=self._human_assessment.current_projection(assessed["submission_id"],binding)
        result["projection_status"]=status
        if status!="CURRENT":
            result["original_judgment"]={name:assessed[name] for name in ("state","passing","independent_success","verdict_id")}
            result["state"]="REVIEW_REQUIRED";result["passing"]=None
            if row["kind"]=="assessment":result["independent_success"]=False
        return result

    def _cursor(self, binding, kind, offset):
        body = _canonical({
            "v": 1, "tenant": binding.tenant_id,
            "principal": binding.principal_id, "kind": kind,
            "offset": offset,
        }).encode()
        mac = hmac.new(self._cursor_key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + mac).decode().rstrip("=")

    def _read_cursor(self, binding, token, kind):
        if not token:
            return 0
        try:
            padded = token + "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(padded.encode())
            body, supplied = raw[:-32], raw[-32:]
            expected = hmac.new(self._cursor_key, body, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, supplied):
                raise ValueError("bad mac")
            data = json.loads(body.decode())
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise Unauthorized("cursor is invalid or was changed") from error
        if (data != {"v": 1, "tenant": binding.tenant_id,
                     "principal": binding.principal_id, "kind": kind,
                     "offset": data.get("offset")}
                or not isinstance(data.get("offset"), int)
                or isinstance(data.get("offset"), bool)
                or data["offset"] < 0):
            raise Unauthorized("cursor is outside this principal and tenant")
        return data["offset"]

    def _list(self, binding, payload):
        kind = payload.get("kind")
        if kind is not None:
            kind = _text(kind, "kind", 80)
        limit = payload.get("limit", 50)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ContractError("limit must be an integer from 1 through 100")
        offset = self._read_cursor(binding, payload.get("cursor"), kind)
        def visible(row):
            if "learning:read:any" in binding.entitlements:
                return True
            return binding.principal_id in {
                row.get("created_by"), row.get("learner_id"),
                row.get("assignee_id")}

        rows = [row for row in self._records.values()
                if row["tenant_id"] == binding.tenant_id and visible(row)
                and (kind is None or row["kind"] == kind)]
        rows.sort(key=lambda row: (row["sequence"], row["id"]))
        page = rows[offset:offset + limit]
        next_offset = offset + len(page)
        cursor = (self._cursor(binding, kind, next_offset)
                  if next_offset < len(rows) else None)
        return {"records": [self._human_record_view(binding,row) for row in page], "next_cursor": cursor,
                "stable_order": "sequence,id"}

    def events(self, binding):
        self._verify_binding(binding)
        return _copy([event for event in self._events
                      if event["tenant_id"] == binding.tenant_id])


class LearningAdapter:
    """Thin surface adapter: branding and transport metadata only."""

    def __init__(self, service, surface, binding, branding):
        if surface not in SURFACES:
            raise ContractError(f"unknown learning surface {surface!r}")
        if not isinstance(branding, dict) or set(branding) - BRAND_FIELDS:
            raise ContractError("branding contains executable or unknown fields")
        clean = {}
        for name, value in branding.items():
            if not isinstance(value, str) or len(value) > 500:
                raise ContractError(f"branding {name} must be a bounded string")
            lowered = value.lower()
            if any(mark in lowered for mark in (
                    "<script", "javascript:", "data:text/html", "onerror=")):
                raise ContractError("branding cannot contain executable content")
            if name == "logo_url":
                parsed = urlparse(value)
                if parsed.scheme != "https" or not parsed.netloc:
                    raise ContractError("branding logo_url must be an https URL")
            if name == "accent_color" and not re.fullmatch(
                    r"#[0-9a-fA-F]{6}", value):
                raise ContractError("branding accent_color must be #RRGGBB")
            clean[name] = value
        self._service = service
        self._surface = surface
        self._binding = binding
        self.branding = copy.deepcopy(clean)

    def command(self, operation, payload=None, request_id="request-1",
                idempotency_key=""):
        return self._service.dispatch(self._surface, self._binding, {
            "api_version": API_VERSION,
            "request_id": request_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
            "payload": {} if payload is None else payload,
        })


def contract_summary():
    return {
        "api_version": API_VERSION,
        "surfaces": sorted(SURFACES),
        "operations": copy.deepcopy(OPERATION_CATALOG),
        "authority_source": "sealed host binding",
        "execution_model": "in-process",
    }
