#!/usr/bin/env python3
"""Explicit, provenance-preserving context attachments for Screen Tutor.

The module owns no connector and performs no background capture. Imported text
is data with zero authority. Capture, transmission and retention are distinct
scopes; removal, revocation and account changes invalidate old request views.
"""

import copy
import datetime as dt
import hashlib
import json
import re


KINDS = ("FILE", "MESSAGE", "MEETING", "SCREEN")
TRUST = ("UNTRUSTED", "USER_SELECTED", "REVIEWED")
TRUST_RANK = {value: index for index, value in enumerate(TRUST)}
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,255}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_ITEMS = 128
MAX_CONTENT = 32_000
MAX_SUMMARY = 8_000


class ContextRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ContextRefused("INVALID_CONTEXT", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}")
    return value


def _text(value, name, maximum):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum):
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}")
    return value


def _digest(value, name):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}")
    return value


def _utc(value, name):
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}") from error
    if parsed.tzinfo != dt.timezone.utc:
        raise ContextRefused("INVALID_CONTEXT", f"invalid {name}")
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def validate_source(value):
    value = copy.deepcopy(value)
    keys = ("schema", "item_id", "kind", "origin_ref", "user_id",
            "account_id", "tenant_id", "project_id", "source_revision",
            "content_sha256", "observed_at_utc", "access",
            "deletion_eligible", "content", "trust", "user_selected")
    _exact(value, keys, "context source")
    if value["schema"] != "tutor.context-source/1" or value["kind"] not in KINDS:
        raise ContextRefused("INVALID_CONTEXT", "source schema or kind")
    for field in ("item_id", "origin_ref", "user_id", "account_id", "tenant_id",
                  "project_id", "source_revision"):
        _ident(value[field], field)
    _digest(value["content_sha256"], "content_sha256")
    _utc(value["observed_at_utc"], "observed_at_utc")
    if value["access"] not in ("PERMITTED", "REVOKED"):
        raise ContextRefused("INVALID_CONTEXT", "access state")
    if not isinstance(value["deletion_eligible"], bool) \
            or not isinstance(value["user_selected"], bool):
        raise ContextRefused("INVALID_CONTEXT", "selection/deletion flags")
    _text(value["content"], "content", MAX_CONTENT)
    if hashlib.sha256(value["content"].encode()).hexdigest() != value["content_sha256"]:
        raise ContextRefused("CONTENT_DIGEST_MISMATCH", value["item_id"])
    if value["trust"] not in TRUST:
        raise ContextRefused("INVALID_CONTEXT", "trust")
    return value


class ContextSession:
    def __init__(self, *, session_id, user_id, account_id, tenant_id, project_id,
                 scopes):
        for value, name in ((session_id, "session_id"), (user_id, "user_id"),
                            (account_id, "account_id"), (tenant_id, "tenant_id"),
                            (project_id, "project_id")):
            _ident(value, name)
        _exact(scopes, ("capture", "transmit", "retain"), "context scopes")
        checked = {}
        for name in ("capture", "transmit", "retain"):
            values = scopes[name]
            if (not isinstance(values, list) or len(values) > len(KINDS)
                    or len(set(values)) != len(values)
                    or any(value not in KINDS for value in values)):
                raise ContextRefused("INVALID_SCOPE", name)
            checked[name] = tuple(values)
        self.session_id = session_id
        self.user_id = user_id
        self.account_id = account_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.scopes = checked
        self.generation = 0
        self.items = {}
        self.summaries = {}
        self.contradictions = []
        self.draft = None
        self.goal = None
        self.closed = False

    def _active(self):
        if self.closed:
            raise ContextRefused("SESSION_CLOSED", self.session_id)

    def attach(self, source):
        self._active()
        row = validate_source(source)
        if not row["user_selected"]:
            raise ContextRefused("SELECTION_REQUIRED", row["item_id"])
        if row["access"] != "PERMITTED":
            raise ContextRefused("ACCESS_REVOKED", row["item_id"])
        if row["kind"] not in self.scopes["capture"]:
            raise ContextRefused("CAPTURE_SCOPE_DENIED", row["kind"])
        expected = {"user_id": self.user_id, "account_id": self.account_id,
                    "tenant_id": self.tenant_id, "project_id": self.project_id}
        if any(row[field] != value for field, value in expected.items()):
            raise ContextRefused("CONTEXT_SCOPE_DENIED", row["item_id"])
        current = self.items.get(row["item_id"])
        if current:
            if current["source"] == row and current["status"] == "ATTACHED":
                return self._public_item(current)
            raise ContextRefused("CONTEXT_CONFLICT", row["item_id"])
        if len(self.items) >= MAX_ITEMS:
            raise ContextRefused("CONTEXT_LIMIT", "attachment limit reached")
        stored = {"source": row, "status": "ATTACHED",
                  "attached_generation": self.generation,
                  "detached_reason": None}
        self.items[row["item_id"]] = stored
        return self._public_item(stored)

    def _public_item(self, stored, include_content=False):
        row = stored["source"]
        result = {key: copy.deepcopy(row[key]) for key in (
            "item_id", "kind", "origin_ref", "user_id", "account_id",
            "tenant_id", "project_id", "source_revision", "content_sha256",
            "observed_at_utc", "access", "deletion_eligible", "trust")}
        result.update({"status": stored["status"],
                       "attached_generation": stored["attached_generation"],
                       "detached_reason": stored["detached_reason"],
                       "instructions_executable": False,
                       "authority": "UNTRUSTED_CONTEXT_DATA"})
        if include_content:
            result["content"] = row["content"]
        return result

    def _detach(self, item_id, reason):
        stored = self.items.get(item_id)
        if not stored or stored["status"] != "ATTACHED":
            raise ContextRefused("CONTEXT_NOT_ATTACHED", item_id)
        stored["status"] = "DETACHED"
        stored["detached_reason"] = reason
        stored["source"]["content"] = "[removed]"
        stored["source"]["content_sha256"] = hashlib.sha256(b"[removed]").hexdigest()
        self.generation += 1
        return self._public_item(stored)

    def remove(self, item_id):
        self._active(); _ident(item_id, "item_id")
        return self._detach(item_id, "USER_REMOVED")

    def revoke(self, item_id):
        self._active(); _ident(item_id, "item_id")
        return self._detach(item_id, "ACCESS_REVOKED")

    def summarize(self, *, summary_id, source_item_ids, text, created_at_utc,
                  claimed_trust):
        self._active(); _ident(summary_id, "summary_id")
        _text(text, "summary text", MAX_SUMMARY); _utc(created_at_utc, "created_at_utc")
        if (not isinstance(source_item_ids, list) or not source_item_ids
                or len(source_item_ids) > 32 or len(set(source_item_ids)) != len(source_item_ids)):
            raise ContextRefused("INVALID_CONTEXT", "summary source IDs")
        sources = []
        for item_id in source_item_ids:
            _ident(item_id, "item_id")
            stored = self.items.get(item_id)
            if not stored or stored["status"] != "ATTACHED":
                raise ContextRefused("SUMMARY_SOURCE_UNAVAILABLE", item_id)
            sources.append(stored["source"])
        if claimed_trust not in TRUST:
            raise ContextRefused("INVALID_CONTEXT", "summary trust")
        ceiling = min(sources, key=lambda row: TRUST_RANK[row["trust"]])["trust"]
        if TRUST_RANK[claimed_trust] > TRUST_RANK[ceiling]:
            raise ContextRefused("TRUST_ESCALATION", summary_id)
        record = {
            "schema": "tutor.context-summary/1", "summary_id": summary_id,
            "text": text, "created_at_utc": created_at_utc,
            "trust": claimed_trust, "trust_ceiling": ceiling,
            "source_items": [{"item_id": row["item_id"],
                              "origin_ref": row["origin_ref"],
                              "source_revision": row["source_revision"],
                              "content_sha256": row["content_sha256"],
                              "observed_at_utc": row["observed_at_utc"],
                              "access": row["access"],
                              "deletion_eligible": row["deletion_eligible"]}
                             for row in sources],
            "generation": self.generation, "instructions_executable": False,
        }
        self.summaries[summary_id] = record
        return copy.deepcopy(record)

    def record_contradiction(self, *, contradiction_id, left_item_id,
                             right_item_id, detail):
        self._active(); _ident(contradiction_id, "contradiction_id")
        _text(detail, "contradiction detail", 1000)
        if left_item_id == right_item_id:
            raise ContextRefused("INVALID_CONTEXT", "contradiction needs two sources")
        sources = []
        for item_id in (left_item_id, right_item_id):
            _ident(item_id, "item_id")
            stored = self.items.get(item_id)
            if not stored or stored["status"] != "ATTACHED":
                raise ContextRefused("CONTEXT_NOT_ATTACHED", item_id)
            sources.append(stored["source"])
        row = {"contradiction_id": contradiction_id,
               "source_item_ids": [left_item_id, right_item_id],
               "detail": detail, "status": "UNRESOLVED_VISIBLE",
               "generation": self.generation}
        if any(value["tenant_id"] != self.tenant_id
               or value["project_id"] != self.project_id for value in sources):
            raise ContextRefused("CONTEXT_SCOPE_DENIED", contradiction_id)
        self.contradictions.append(row)
        return copy.deepcopy(row)

    def set_continuity(self, *, draft, goal):
        self._active()
        self.draft = _text(draft, "draft", 8000) if draft is not None else None
        self.goal = _text(goal, "goal", 2000) if goal is not None else None
        return {"draft": self.draft, "goal": self.goal,
                "source_references_current": False}

    def request_view(self):
        self._active()
        attached = []
        for stored in self.items.values():
            row = stored["source"]
            if stored["status"] == "ATTACHED" and row["kind"] in self.scopes["transmit"]:
                attached.append(self._public_item(stored, include_content=True))
        summaries = []
        for summary in self.summaries.values():
            if (summary["generation"] == self.generation
                    and all(self.items.get(ref["item_id"], {}).get("status") == "ATTACHED"
                            and self.items[ref["item_id"]]["source"]["kind"]
                                in self.scopes["transmit"]
                            for ref in summary["source_items"])):
                summaries.append(copy.deepcopy(summary))
        visible_ids = {row["item_id"] for row in attached}
        return {
            "schema": "tutor.context-view/1", "session_id": self.session_id,
            "generation": self.generation, "user_id": self.user_id,
            "account_id": self.account_id, "tenant_id": self.tenant_id,
            "project_id": self.project_id, "items": attached,
            "summaries": summaries,
            "contradictions": [copy.deepcopy(row) for row in self.contradictions
                               if (row["generation"] == self.generation
                                   and set(row["source_item_ids"]) <= visible_ids)],
            "draft": self.draft, "goal": self.goal,
            "connector": None, "global_capture_enabled": False,
        }

    def validate_view_current(self, view):
        if (not isinstance(view, dict) or view.get("session_id") != self.session_id
                or view.get("generation") != self.generation
                or any(view.get(field) != getattr(self, field)
                       for field in ("user_id", "account_id", "tenant_id", "project_id"))):
            return {"status": "STALE", "usable": False}
        if _canonical(view) != _canonical(self.request_view()):
            return {"status": "STALE", "usable": False}
        return {"status": "CURRENT", "usable": True}

    def switch_account(self, *, account_id, tenant_id, project_id):
        self._active()
        for value, name in ((account_id, "account_id"), (tenant_id, "tenant_id"),
                            (project_id, "project_id")):
            _ident(value, name)
        for stored in self.items.values():
            if stored["status"] == "ATTACHED":
                stored["status"] = "DETACHED"
                stored["detached_reason"] = "ACCOUNT_SWITCH"
                stored["source"]["content"] = "[removed]"
                stored["source"]["content_sha256"] = hashlib.sha256(b"[removed]").hexdigest()
        self.account_id, self.tenant_id, self.project_id = account_id, tenant_id, project_id
        self.generation += 1
        return {"generation": self.generation, "draft": self.draft,
                "goal": self.goal, "source_references_current": False}

    def close(self):
        if self.closed:
            return
        for stored in self.items.values():
            row = stored["source"]
            if row["kind"] not in self.scopes["retain"]:
                row["content"] = "[removed]"
                row["content_sha256"] = hashlib.sha256(b"[removed]").hexdigest()
                stored["status"] = "DETACHED"
                stored["detached_reason"] = "RETENTION_SCOPE_ENDED"
        self.closed = True


def core_response(question, view=None):
    """Prove the platform-owned route remains usable with no connector."""
    _text(question, "question", 1000)
    count = len(view.get("items", [])) if isinstance(view, dict) else 0
    return {"schema": "tutor.context-core-response/1", "status": "READY",
            "context_status": "SELECTED_CONTEXT" if count else "NO_CONTEXT",
            "selected_item_count": count, "connector_required": False,
            "answer_generated": False}
