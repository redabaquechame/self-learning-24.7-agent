#!/usr/bin/env python3
"""Bounded offline audio-control contracts for Screen Tutor.

This module opens no device and calls no provider.  It models the state that a
native microphone/playback adapter and the existing provider gateway must obey:
explicit source scopes, hold-to-talk capture, non-authoritative transcripts,
reservation before dispatch, idempotent bounded retries, epoch invalidation,
captions, text fallback, device loss and local Stop.
"""

import copy
import hashlib
import json
import re


SCHEMA = "tutor.audio-session/1"
EVENT_SCHEMA = "tutor.audio-event/1"
SCOPES = ("MICROPHONE", "MEDIA", "ASSISTANT_PLAYBACK")
ORIGINS = ("MICROPHONE", "MEDIA", "ASSISTANT")
DEVICE_STATES = ("AVAILABLE", "DISCONNECTED")
SESSION_STATES = ("IDLE", "CAPTURING", "STOPPED")
REQUEST_STATES = ("QUEUED", "RESERVED", "IN_FLIGHT", "COMPLETED", "FAILED", "CANCELLED")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MAX_TRANSCRIPT_CHARS = 8_000
MAX_RESPONSE_CHARS = 16_000
MAX_REQUESTS = 32
MAX_ACTIVE_REQUESTS = 4
MAX_ATTEMPTS = 2
MAX_COST_UNITS = 1_000_000


class AudioRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise AudioRefused("INVALID_AUDIO_STATE", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise AudioRefused("INVALID_AUDIO_STATE", f"invalid {name}")
    return value


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AudioRefused("INVALID_AUDIO_STATE", f"invalid {name}")
    return value.strip()


def _integer(value, name, low=0, high=1_000_000_000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AudioRefused("INVALID_AUDIO_STATE", f"invalid {name}")
    return value


def _request(value):
    _exact(value, ("request_id", "effect_key", "transcript", "origin",
                   "state", "attempts", "reservation_id", "reserved_cost_units",
                   "generation_epoch", "source_epoch", "response_id"), "request")
    for field in ("request_id", "effect_key"):
        _ident(value[field], field)
    if value["origin"] != "MICROPHONE" or value["state"] not in REQUEST_STATES:
        raise AudioRefused("INVALID_AUDIO_STATE", "request origin or state")
    _text(value["transcript"], "transcript", MAX_TRANSCRIPT_CHARS)
    _integer(value["attempts"], "attempts", 0, MAX_ATTEMPTS)
    _integer(value["reserved_cost_units"], "reserved cost", 0, MAX_COST_UNITS)
    _integer(value["generation_epoch"], "generation epoch")
    _integer(value["source_epoch"], "source epoch")
    for field in ("reservation_id", "response_id"):
        if value[field] is not None:
            _ident(value[field], field)
    if value["state"] in ("RESERVED", "IN_FLIGHT") and value["reservation_id"] is None:
        raise AudioRefused("INVALID_AUDIO_STATE", "dispatch state lacks reservation")
    return value


def _session(value):
    _exact(value, ("schema", "session_id", "user_id", "project_id", "status",
                   "device_state", "scopes", "push_to_talk", "generation_epoch",
                   "source_epoch", "playback_epoch", "playback_active",
                   "captions_enabled", "text_fallback", "requests"), "session")
    if value["schema"] != SCHEMA or value["status"] not in SESSION_STATES:
        raise AudioRefused("INVALID_AUDIO_STATE", "session schema or status")
    for field in ("session_id", "user_id", "project_id"):
        _ident(value[field], field)
    scopes = value["scopes"]
    if (not isinstance(scopes, list) or not scopes or len(scopes) > len(SCOPES)
            or len(set(scopes)) != len(scopes) or any(scope not in SCOPES for scope in scopes)):
        raise AudioRefused("INVALID_AUDIO_STATE", "invalid audio scopes")
    if value["device_state"] not in DEVICE_STATES or value["push_to_talk"] not in ("RELEASED", "HELD"):
        raise AudioRefused("INVALID_AUDIO_STATE", "device or push-to-talk state")
    for field in ("playback_active", "captions_enabled", "text_fallback"):
        if not isinstance(value[field], bool):
            raise AudioRefused("INVALID_AUDIO_STATE", f"invalid {field}")
    for field in ("generation_epoch", "source_epoch", "playback_epoch"):
        _integer(value[field], field)
    requests = value["requests"]
    if not isinstance(requests, list) or len(requests) > MAX_REQUESTS:
        raise AudioRefused("INVALID_AUDIO_STATE", "request history exceeds bounds")
    for request in requests:
        _request(request)
    ids = [request["request_id"] for request in requests]
    effects = [request["effect_key"] for request in requests]
    if len(ids) != len(set(ids)) or len(effects) != len(set(effects)):
        raise AudioRefused("INVALID_AUDIO_STATE", "duplicate request identity")
    if sum(request["state"] in ("QUEUED", "RESERVED", "IN_FLIGHT") for request in requests) > MAX_ACTIVE_REQUESTS:
        raise AudioRefused("INVALID_AUDIO_STATE", "active queue exceeds bound")
    if value["status"] == "STOPPED" and (value["push_to_talk"] != "RELEASED" or value["playback_active"]):
        raise AudioRefused("INVALID_AUDIO_STATE", "stopped session retained active audio")
    if (value["status"] == "STOPPED"
            and any(request["state"] in ("QUEUED", "RESERVED", "IN_FLIGHT")
                    for request in requests)):
        raise AudioRefused("INVALID_AUDIO_STATE", "stopped session retained active request")
    return value


def _copy_session(session):
    _session(session)
    return copy.deepcopy(session)


def start_session(session_id, user_id, project_id, scopes):
    value = {
        "schema": SCHEMA,
        "session_id": _ident(session_id, "session_id"),
        "user_id": _ident(user_id, "user_id"),
        "project_id": _ident(project_id, "project_id"),
        "status": "IDLE",
        "device_state": "AVAILABLE",
        "scopes": list(scopes),
        "push_to_talk": "RELEASED",
        "generation_epoch": 0,
        "source_epoch": 0,
        "playback_epoch": 0,
        "playback_active": False,
        "captions_enabled": True,
        "text_fallback": True,
        "requests": [],
    }
    _session(value)
    return value


def press_to_talk(session):
    result = _copy_session(session)
    if result["status"] == "STOPPED":
        raise AudioRefused("AUDIO_STOPPED", "audio session is stopped")
    if "MICROPHONE" not in result["scopes"]:
        raise AudioRefused("MICROPHONE_SCOPE_REQUIRED", "microphone scope is not active")
    if result["device_state"] != "AVAILABLE":
        raise AudioRefused("MICROPHONE_UNAVAILABLE", "microphone device is disconnected")
    if result["push_to_talk"] == "HELD":
        return result
    result["push_to_talk"] = "HELD"
    result["status"] = "CAPTURING"
    result["generation_epoch"] += 1
    result["playback_epoch"] += 1
    result["playback_active"] = False
    for request in result["requests"]:
        if request["state"] in ("QUEUED", "RESERVED", "IN_FLIGHT"):
            request["state"] = "CANCELLED"
    return result


def _event(value):
    _exact(value, ("schema", "event_id", "origin", "transcript", "source_epoch"), "event")
    if value["schema"] != EVENT_SCHEMA or value["origin"] not in ORIGINS:
        raise AudioRefused("INVALID_AUDIO_STATE", "event schema or origin")
    _ident(value["event_id"], "event_id")
    _text(value["transcript"], "transcript", MAX_TRANSCRIPT_CHARS)
    _integer(value["source_epoch"], "source_epoch")
    return value


def observe_event(session, event):
    """Classify a transcript without ever turning speech into execution consent."""
    current = _copy_session(session)
    _event(event)
    if current["status"] == "STOPPED":
        raise AudioRefused("AUDIO_STOPPED", "audio session is stopped")
    if event["source_epoch"] != current["source_epoch"]:
        raise AudioRefused("STALE_AUDIO", "event source epoch is stale")
    if event["origin"] == "MEDIA" and "MEDIA" not in current["scopes"]:
        raise AudioRefused("MEDIA_SCOPE_REQUIRED", "media audio scope is not active")
    if event["origin"] == "ASSISTANT":
        disposition = "IGNORED_SELF_AUDIO"
    elif event["origin"] == "MEDIA":
        disposition = "CONTEXT_ONLY"
    else:
        disposition = "TRANSCRIPT_ONLY"
    return {
        "event_id": event["event_id"],
        "origin": event["origin"],
        "disposition": disposition,
        "execution_authorized": False,
        "reason": "VOICE_CANNOT_GRANT_EXECUTION_CONSENT",
    }


def release_to_submit(session, event, request_id):
    result = _copy_session(session)
    _event(event)
    _ident(request_id, "request_id")
    if result["status"] == "STOPPED":
        raise AudioRefused("AUDIO_STOPPED", "audio session is stopped")
    if result["status"] != "CAPTURING" or result["push_to_talk"] != "HELD":
        raise AudioRefused("PUSH_TO_TALK_REQUIRED", "no held microphone capture")
    if event["origin"] != "MICROPHONE" or event["source_epoch"] != result["source_epoch"]:
        raise AudioRefused("STALE_OR_UNTRUSTED_AUDIO", "only the current microphone capture may submit")
    result["push_to_talk"] = "RELEASED"
    result["status"] = "IDLE"
    existing = next((item for item in result["requests"] if item["request_id"] == request_id), None)
    if existing is not None:
        return {"session": result, "request": copy.deepcopy(existing),
                "execution_authorized": False}
    active = sum(item["state"] in ("QUEUED", "RESERVED", "IN_FLIGHT") for item in result["requests"])
    if active >= MAX_ACTIVE_REQUESTS or len(result["requests"]) >= MAX_REQUESTS:
        raise AudioRefused("AUDIO_QUEUE_FULL", "bounded request queue is full")
    seed = f"{result['session_id']}:{request_id}:{result['source_epoch']}".encode("utf-8")
    request = {
        "request_id": request_id,
        "effect_key": "audio-" + hashlib.sha256(seed).hexdigest()[:32],
        "transcript": event["transcript"].strip(),
        "origin": "MICROPHONE",
        "state": "QUEUED",
        "attempts": 0,
        "reservation_id": None,
        "reserved_cost_units": 0,
        "generation_epoch": result["generation_epoch"],
        "source_epoch": result["source_epoch"],
        "response_id": None,
    }
    result["requests"].append(request)
    return {"session": result, "request": copy.deepcopy(request),
            "execution_authorized": False}


def _find(result, request_id):
    _ident(request_id, "request_id")
    request = next((item for item in result["requests"] if item["request_id"] == request_id), None)
    if request is None:
        raise AudioRefused("AUDIO_REQUEST_UNKNOWN", request_id)
    return request


def reserve_request(session, request_id, reservation_id, cost_units):
    result = _copy_session(session)
    request = _find(result, request_id)
    _ident(reservation_id, "reservation_id")
    _integer(cost_units, "cost_units", 1, MAX_COST_UNITS)
    if request["state"] == "RESERVED" and request["reservation_id"] == reservation_id:
        return result
    if request["state"] != "QUEUED":
        raise AudioRefused("AUDIO_REQUEST_STATE", "only a queued request can be reserved")
    request["reservation_id"] = reservation_id
    request["reserved_cost_units"] = cost_units
    request["state"] = "RESERVED"
    return result


def begin_dispatch(session, request_id, reservation_id):
    """Record an offline dispatch intent; no provider call occurs here."""
    result = _copy_session(session)
    request = _find(result, request_id)
    _ident(reservation_id, "reservation_id")
    if request["reservation_id"] != reservation_id or request["state"] not in ("RESERVED", "QUEUED"):
        raise AudioRefused("AUDIO_RESERVATION_REQUIRED", "matching accounting reservation required")
    if request["state"] == "QUEUED" and request["attempts"] == 0:
        raise AudioRefused("AUDIO_RESERVATION_REQUIRED", "first dispatch must be reserved")
    if request["attempts"] >= MAX_ATTEMPTS:
        raise AudioRefused("AUDIO_RETRY_EXHAUSTED", request_id)
    if (request["generation_epoch"] != result["generation_epoch"]
            or request["source_epoch"] != result["source_epoch"]):
        request["state"] = "CANCELLED"
        raise AudioRefused("STALE_AUDIO", "request epoch is stale")
    request["attempts"] += 1
    request["state"] = "IN_FLIGHT"
    return result


def record_network_failure(session, request_id):
    result = _copy_session(session)
    request = _find(result, request_id)
    if request["state"] != "IN_FLIGHT":
        raise AudioRefused("AUDIO_REQUEST_STATE", "network failure requires an in-flight request")
    if request["attempts"] >= MAX_ATTEMPTS:
        request["state"] = "FAILED"
        result["text_fallback"] = True
    else:
        request["state"] = "QUEUED"
    return result


def accept_response(session, request_id, response_id, generation_epoch,
                    playback_text, caption_text):
    result = _copy_session(session)
    request = _find(result, request_id)
    _ident(response_id, "response_id")
    _integer(generation_epoch, "generation_epoch")
    playback = _text(playback_text, "playback_text", MAX_RESPONSE_CHARS)
    caption = _text(caption_text, "caption_text", MAX_RESPONSE_CHARS)
    if (request["state"] != "IN_FLIGHT" or generation_epoch != result["generation_epoch"]
            or request["generation_epoch"] != result["generation_epoch"]
            or request["source_epoch"] != result["source_epoch"]):
        raise AudioRefused("STALE_AUDIO_RESPONSE", response_id)
    request["state"] = "COMPLETED"
    request["response_id"] = response_id
    result["playback_epoch"] += 1
    result["playback_active"] = "ASSISTANT_PLAYBACK" in result["scopes"]
    return {"session": result, "origin": "ASSISTANT", "playback_text": playback,
            "caption_text": caption, "playback_epoch": result["playback_epoch"]}


def barge_in(session):
    result = _copy_session(session)
    if result["status"] == "STOPPED":
        return result
    result["generation_epoch"] += 1
    result["playback_epoch"] += 1
    result["playback_active"] = False
    for request in result["requests"]:
        if request["state"] in ("QUEUED", "RESERVED", "IN_FLIGHT"):
            request["state"] = "CANCELLED"
    return result


def set_scopes(session, scopes):
    result = _copy_session(session)
    proposed = list(scopes)
    probe = copy.deepcopy(result)
    probe["scopes"] = proposed
    _session(probe)
    result = barge_in(result)
    result["source_epoch"] += 1
    result["scopes"] = proposed
    result["push_to_talk"] = "RELEASED"
    result["status"] = "IDLE"
    return result


def device_changed(session, state):
    result = _copy_session(session)
    if state not in DEVICE_STATES:
        raise AudioRefused("INVALID_AUDIO_STATE", "unknown device state")
    result["device_state"] = state
    if state == "DISCONNECTED":
        result = barge_in(result)
        result["push_to_talk"] = "RELEASED"
        result["status"] = "IDLE"
        result["text_fallback"] = True
    return result


def stop_session(session):
    result = _copy_session(session)
    if result["status"] == "STOPPED":
        return result
    result = barge_in(result)
    result["push_to_talk"] = "RELEASED"
    result["status"] = "STOPPED"
    return result


def canonical_session_json(session):
    _session(session)
    return json.dumps(session, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
