#!/usr/bin/env python3
"""Timestamp-grounded media explanations and semantic app transfer.

This layer consumes an already-authorized ``tutor_media_index`` snapshot.  It
does not fetch media, call a model, control playback, inspect an application or
execute a tutorial step.  Its records keep evidence modality and timeline
identity explicit so downstream UI code can show exactly what was processed.
"""

import copy
import hashlib
import json
import re

import tutor_grounding
import tutor_sources


INDEX_KEYS = (
    "schema", "media_id", "tenant_id", "project_id", "source_revision",
    "content_sha256", "source_access_method", "duration_ms",
    "authorized_intervals", "content_epoch", "timeline_epoch", "playback_ms",
    "playback_rate", "request_budget_remaining", "captions", "frames", "gaps",
    "transitions", "retrieval_decisions")
MODES = ("FRAME", "CAPTURED_INTERVAL", "SELECTED_CLIP",
         "FULL_ACCESSIBLE_SOURCE")
CLAIM_KINDS = {
    "NARRATOR_CLAIM": ("CAPTION", "AUDIO"),
    "VISIBLE_STATE": ("VISUAL",),
    "VISIBLE_TRANSITION": ("VISUAL",),
    "AUDIO_EVENT": ("AUDIO",),
}
CERTAINTIES = ("OBSERVED", "REPORTED", "CONTESTED")
PLAYBACK_ACTIONS = ("PLAY", "PAUSE", "SEEK", "RATE")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_CLAIMS = 64
MAX_EVIDENCE_IDS = 16
MAX_AUDIO = 256
MAX_TEXT = 4000


class MediaTutoringRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {name}")
    return value


def _digest(value, name):
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {name}")
    return value


def _integer(value, name, low=0, high=2**63 - 1):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {name}")
    return value


def _text(value, name, maximum=MAX_TEXT):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {name}")
    return value


def _version(value, name):
    try:
        return tutor_sources.parse_version(value)
    except tutor_sources.SourceRefused as error:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {name}") from error


def _interval(start_ms, end_ms, duration_ms, where="interval"):
    start = _integer(start_ms, f"{where} start", 0, duration_ms)
    end = _integer(end_ms, f"{where} end", 1, duration_ms)
    if end <= start:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {where}")
    return start, end


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and a_end > b_start


def _snapshot(value):
    value = copy.deepcopy(value)
    _exact(value, INDEX_KEYS, "media index")
    if value["schema"] != "tutor.media-index/1":
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "unsupported media index")
    for field in ("media_id", "tenant_id", "project_id", "source_revision"):
        _ident(value[field], field)
    _digest(value["content_sha256"], "content_sha256")
    duration = _integer(value["duration_ms"], "duration_ms", 1)
    for field in ("content_epoch", "timeline_epoch", "playback_ms",
                  "request_budget_remaining"):
        _integer(value[field], field)
    if not isinstance(value["playback_rate"], (int, float)) or isinstance(
            value["playback_rate"], bool):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "invalid playback_rate")
    for field in ("authorized_intervals", "captions", "frames", "gaps",
                  "transitions", "retrieval_decisions"):
        if not isinstance(value[field], list):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"invalid {field}")
    if value["source_access_method"] not in ("UPLOAD", "AUTHORIZED_URL", "CURRENT_SCREEN"):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "source access method")
    if not 0 <= value["playback_ms"] <= duration or not 0.25 <= value["playback_rate"] <= 4.0:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "playback state")
    checked_intervals = []
    for row in value["authorized_intervals"]:
        _exact(row, ("start_ms", "end_ms"), "authorized interval")
        checked_intervals.append(_interval(
            row["start_ms"], row["end_ms"], duration, "authorized interval"))
    if (not checked_intervals or checked_intervals != sorted(checked_intervals)
            or any(checked_intervals[index][0] < checked_intervals[index - 1][1]
                   for index in range(1, len(checked_intervals)))):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "authorized intervals overlap or are unordered")
    for row in value["captions"]:
        _exact(row, ("caption_id", "start_ms", "end_ms", "text", "language",
                     "provenance_ref", "state", "content_epoch", "timeline_epoch",
                     "source_revision", "content_sha256"), "caption evidence")
        for field in ("caption_id", "provenance_ref", "source_revision"):
            _ident(row[field], field)
        _digest(row["content_sha256"], "caption content_sha256")
        _interval(row["start_ms"], row["end_ms"], duration, "caption interval")
        _integer(row["content_epoch"], "caption content_epoch")
        _integer(row["timeline_epoch"], "caption timeline_epoch")
        _text(row["text"], "caption text", 12000)
        if row["state"] not in ("RAW", "CONTESTED", "CORRECTED"):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "caption state")
    for row in value["frames"]:
        _exact(row, ("frame_id", "timestamp_ms", "mime", "byte_count", "sha256",
                     "provenance_ref", "content_epoch", "timeline_epoch",
                     "source_revision", "content_sha256"), "frame evidence")
        for field in ("frame_id", "provenance_ref", "source_revision"):
            _ident(row[field], field)
        _digest(row["sha256"], "frame sha256")
        _digest(row["content_sha256"], "frame content_sha256")
        _integer(row["timestamp_ms"], "frame timestamp_ms", 0, duration - 1)
        _integer(row["byte_count"], "frame byte_count", 1)
        _integer(row["content_epoch"], "frame content_epoch")
        _integer(row["timeline_epoch"], "frame timeline_epoch")
    for row in value["gaps"]:
        _exact(row, ("gap_id", "start_ms", "end_ms", "modality", "reason",
                     "timeline_epoch", "content_epoch"), "evidence gap")
        _ident(row["gap_id"], "gap_id"); _ident(row["reason"], "gap reason")
        _interval(row["start_ms"], row["end_ms"], duration, "gap interval")
        _integer(row["timeline_epoch"], "gap timeline_epoch")
        _integer(row["content_epoch"], "gap content_epoch")
        if row["modality"] not in ("CAPTION", "AUDIO", "FRAME", "ALL"):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "gap modality")
    for row in value["transitions"]:
        _exact(row, ("transition_id", "at_ms", "kind", "timeline_epoch",
                     "content_epoch"), "transition")
        _ident(row["transition_id"], "transition_id")
        _integer(row["at_ms"], "transition at_ms", 0, duration)
        _integer(row["timeline_epoch"], "transition timeline_epoch")
        _integer(row["content_epoch"], "transition content_epoch")
        if row["kind"] not in ("SCENE", "AD_START", "AD_END", "SOURCE_CHANGE"):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "transition kind")
    for row in value["retrieval_decisions"]:
        _exact(row, ("timestamp_ms", "reason", "timeline_epoch"), "retrieval decision")
        _integer(row["timestamp_ms"], "retrieval timestamp_ms", 0, duration - 1)
        _integer(row["timeline_epoch"], "retrieval timeline_epoch")
        if row["reason"] not in ("TRANSITION", "BASELINE", "FILL"):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "retrieval reason")
    for field, identity in (("captions", "caption_id"), ("frames", "frame_id"),
                            ("gaps", "gap_id"), ("transitions", "transition_id")):
        if len({row[identity] for row in value[field]}) != len(value[field]):
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", f"duplicate {identity}")
    for row in _current_rows(value, "captions") + _current_rows(value, "frames"):
        if (row["source_revision"] != value["source_revision"]
                or row["content_sha256"] != value["content_sha256"]):
            raise MediaTutoringRefused("STALE_MEDIA", "current evidence source binding differs")
    return value


def _current_rows(snapshot, field):
    return [row for row in snapshot[field]
            if row.get("timeline_epoch") == snapshot["timeline_epoch"]
            and row.get("content_epoch") == snapshot["content_epoch"]]


def _audio_rows(rows, snapshot):
    if not isinstance(rows, list) or len(rows) > MAX_AUDIO:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "audio evidence exceeds bound")
    checked = []
    keys = ("audio_id", "start_ms", "end_ms", "origin", "sha256",
            "source_revision", "content_sha256", "content_epoch",
            "timeline_epoch", "provenance_ref")
    for original in rows:
        row = copy.deepcopy(original)
        _exact(row, keys, "audio evidence")
        for field in ("audio_id", "provenance_ref"):
            _ident(row[field], field)
        _digest(row["sha256"], "audio sha256")
        _interval(row["start_ms"], row["end_ms"], snapshot["duration_ms"], "audio interval")
        if row["origin"] != "MEDIA":
            raise MediaTutoringRefused("AUDIO_ORIGIN_DENIED", "only media audio supports media claims")
        for field in ("source_revision", "content_sha256", "content_epoch",
                      "timeline_epoch"):
            if row[field] != snapshot[field]:
                raise MediaTutoringRefused("STALE_MEDIA", f"audio {field} differs")
        checked.append(row)
    if len({row["audio_id"] for row in checked}) != len(checked):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "duplicate audio identity")
    return checked


def _window_authorized(snapshot, start_ms, end_ms):
    return any(row["start_ms"] <= start_ms and end_ms <= row["end_ms"]
               for row in snapshot["authorized_intervals"])


def _fingerprint(snapshot):
    payload = {
        "media_id": snapshot["media_id"],
        "source_revision": snapshot["source_revision"],
        "content_sha256": snapshot["content_sha256"],
        "content_epoch": snapshot["content_epoch"],
        "timeline_epoch": snapshot["timeline_epoch"],
        "transitions": _current_rows(snapshot, "transitions"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _gap_labels(snapshot, start_ms, end_ms):
    rows = []
    for gap in _current_rows(snapshot, "gaps"):
        if _overlaps(start_ms, end_ms, gap["start_ms"], gap["end_ms"]):
            rows.append({"gap_id": gap["gap_id"], "start_ms": gap["start_ms"],
                         "end_ms": gap["end_ms"], "modality": gap["modality"],
                         "reason": gap["reason"]})
    return rows


def _claim(row, snapshot, audio_by_id, captions_by_id, frames_by_id,
           window_start, window_end):
    row = copy.deepcopy(row)
    _exact(row, ("claim_id", "kind", "text", "modality", "start_ms",
                 "end_ms", "evidence_ids", "certainty"), "claim")
    _ident(row["claim_id"], "claim_id")
    _text(row["text"], "claim text")
    if row["kind"] not in CLAIM_KINDS or row["modality"] not in CLAIM_KINDS[row["kind"]]:
        raise MediaTutoringRefused("MODALITY_MISMATCH", row["claim_id"])
    if row["certainty"] not in CERTAINTIES:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "invalid certainty")
    start, end = _interval(row["start_ms"], row["end_ms"],
                           snapshot["duration_ms"], "claim interval")
    if start < window_start or end > window_end:
        raise MediaTutoringRefused("CLAIM_OUTSIDE_WINDOW", row["claim_id"])
    ids = row["evidence_ids"]
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_EVIDENCE_IDS
            or len(set(ids)) != len(ids)):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "invalid evidence IDs")
    for value in ids:
        _ident(value, "evidence_id")
    if row["modality"] == "CAPTION":
        evidence = [captions_by_id.get(value) for value in ids]
        if any(value is None for value in evidence):
            raise MediaTutoringRefused("MISSING_CAPTION_EVIDENCE", row["claim_id"])
        if row["certainty"] not in ("REPORTED", "CONTESTED"):
            raise MediaTutoringRefused("MODALITY_MISMATCH", "captions report speech; they do not observe pixels")
        if any(value.get("state") == "CONTESTED" for value in evidence) \
                and row["certainty"] != "CONTESTED":
            raise MediaTutoringRefused("CONTESTED_CAPTION", row["claim_id"])
    elif row["modality"] == "VISUAL":
        evidence = [frames_by_id.get(value) for value in ids]
        if any(value is None for value in evidence):
            raise MediaTutoringRefused("MISSING_VISUAL_EVIDENCE", row["claim_id"])
        if row["certainty"] != "OBSERVED":
            raise MediaTutoringRefused("MODALITY_MISMATCH", "visual evidence must be labelled observed")
        if row["kind"] == "VISIBLE_TRANSITION":
            timestamps = sorted({value["timestamp_ms"] for value in evidence})
            if len(timestamps) < 2:
                raise MediaTutoringRefused("INSUFFICIENT_VISUAL_COVERAGE",
                                           "a transition requires distinct before/after frames")
    else:
        evidence = [audio_by_id.get(value) for value in ids]
        if any(value is None for value in evidence):
            raise MediaTutoringRefused("MISSING_AUDIO_EVIDENCE", row["claim_id"])
        if row["certainty"] != "OBSERVED":
            raise MediaTutoringRefused("MODALITY_MISMATCH", "audio event certainty")
    if not all(_overlaps(start, end,
                         value.get("start_ms", value.get("timestamp_ms")),
                         value.get("end_ms", value.get("timestamp_ms", -1) + 1))
               for value in evidence):
        raise MediaTutoringRefused("EVIDENCE_OUTSIDE_CLAIM", row["claim_id"])
    gap_modalities = {"FRAME" if row["modality"] == "VISUAL" else row["modality"],
                      "ALL"}
    if any(gap.get("modality") in gap_modalities
           and _overlaps(start, end, gap["start_ms"], gap["end_ms"])
           for gap in _current_rows(snapshot, "gaps")):
        raise MediaTutoringRefused("EVIDENCE_GAP", row["claim_id"])
    return row


def build_explanation(*, explanation_id, question, index_snapshot, start_ms,
                      end_ms, mode, requested_scope, claims, audio_evidence=()):
    """Build data-only claims from exact current evidence and expose its gaps."""
    _ident(explanation_id, "explanation_id")
    _text(question, "question", 1000)
    snapshot = _snapshot(index_snapshot)
    start, end = _interval(start_ms, end_ms, snapshot["duration_ms"], "question window")
    if not _window_authorized(snapshot, start, end):
        raise MediaTutoringRefused("RIGHTS_DENIED", "question window is not authorized")
    if mode not in MODES or requested_scope not in ("WINDOW", "ENTIRE_SOURCE"):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "mode or requested scope")
    if mode == "FRAME" and end - start > 1000:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "frame mode exceeds one second")
    if requested_scope == "ENTIRE_SOURCE" and (start != 0 or end != snapshot["duration_ms"]):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "entire-source scope needs full duration")
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "claims exceed bound")
    captions = {row["caption_id"]: row for row in _current_rows(snapshot, "captions")}
    frames = {row["frame_id"]: row for row in _current_rows(snapshot, "frames")}
    audio = _audio_rows(list(audio_evidence), snapshot)
    audio_by_id = {row["audio_id"]: row for row in audio}
    checked = [_claim(row, snapshot, audio_by_id, captions, frames, start, end)
               for row in claims]
    if len({row["claim_id"] for row in checked}) != len(checked):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "duplicate claim identity")
    current_captions = [row for row in captions.values()
                        if _overlaps(start, end, row["start_ms"], row["end_ms"])]
    current_frames = [row for row in frames.values()
                      if start <= row["timestamp_ms"] < end]
    current_audio = [row for row in audio
                     if _overlaps(start, end, row["start_ms"], row["end_ms"])]
    gaps = _gap_labels(snapshot, start, end)
    sparse_entire = requested_scope == "ENTIRE_SOURCE"
    limitations = []
    needed_modalities = {row["modality"] for row in checked}
    if requested_scope == "ENTIRE_SOURCE":
        needed_modalities.update(("CAPTION", "VISUAL", "AUDIO"))
    if "CAPTION" in needed_modalities and not current_captions:
        limitations.append("NO_CAPTION_EVIDENCE_IN_WINDOW")
    if "VISUAL" in needed_modalities and not current_frames:
        limitations.append("NO_VISUAL_EVIDENCE_IN_WINDOW")
    if "AUDIO" in needed_modalities and not current_audio:
        limitations.append("NO_AUDIO_EVIDENCE_IN_WINDOW")
    if not checked:
        limitations.append("NO_SUPPORTED_CLAIMS")
    limitations.extend("GAP_" + row["modality"] + "_" + row["reason"] for row in gaps)
    if sparse_entire:
        limitations.append("INSUFFICIENT_FOR_COMPLETE_SOURCE_CLAIM")
    answer_status = "PARTIAL_EVIDENCE" if limitations else "GROUNDED_EVIDENCE"
    return {
        "schema": "tutor.media-explanation/1",
        "explanation_id": explanation_id,
        "question": question,
        "binding": {
            "media_id": snapshot["media_id"],
            "tenant_id": snapshot["tenant_id"],
            "project_id": snapshot["project_id"],
            "source_revision": snapshot["source_revision"],
            "content_sha256": snapshot["content_sha256"],
            "content_epoch": snapshot["content_epoch"],
            "timeline_epoch": snapshot["timeline_epoch"],
            "timeline_fingerprint": _fingerprint(snapshot),
        },
        "window": {"start_ms": start, "end_ms": end, "mode": mode,
                   "requested_scope": requested_scope},
        "answer_status": answer_status,
        "claims": checked,
        "processed_coverage": {
            "caption_intervals": [{"caption_id": row["caption_id"],
                                   "start_ms": row["start_ms"],
                                   "end_ms": row["end_ms"]}
                                  for row in current_captions],
            "frame_timestamps": [{"frame_id": row["frame_id"],
                                  "timestamp_ms": row["timestamp_ms"]}
                                 for row in current_frames],
            "audio_intervals": [{"audio_id": row["audio_id"],
                                 "start_ms": row["start_ms"],
                                 "end_ms": row["end_ms"]}
                                for row in current_audio],
            "gaps": gaps,
            "authorized_intervals": copy.deepcopy(snapshot["authorized_intervals"]),
        },
        "limitations": sorted(set(limitations)),
        "complete_source_understanding_claimed": False,
    }


def validate_current(explanation, index_snapshot):
    snapshot = _snapshot(index_snapshot)
    binding = explanation.get("binding", {}) if isinstance(explanation, dict) else {}
    for field in ("media_id", "source_revision", "content_sha256",
                  "content_epoch", "timeline_epoch"):
        if binding.get(field) != snapshot[field]:
            return {"status": "SUPPRESSED", "reason": "STALE_" + field.upper()}
    if binding.get("timeline_fingerprint") != _fingerprint(snapshot):
        return {"status": "SUPPRESSED", "reason": "STALE_TIMELINE_FINGERPRINT"}
    return {"status": "CURRENT", "reason": "EXACT_MEDIA_BINDING"}


def plan_decisive_visual_evidence(index_snapshot, intervals, max_requests):
    """Name missing before/after frame samples; this does not retrieve them."""
    snapshot = _snapshot(index_snapshot)
    cap = _integer(max_requests, "max_requests", 1, 64)
    if not isinstance(intervals, list) or len(intervals) > 32:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "decisive intervals")
    frames = _current_rows(snapshot, "frames")
    requests = []
    for item in intervals:
        _exact(item, ("interval_id", "start_ms", "end_ms"), "decisive interval")
        _ident(item["interval_id"], "interval_id")
        start, end = _interval(item["start_ms"], item["end_ms"],
                               snapshot["duration_ms"], "decisive interval")
        if not _window_authorized(snapshot, start, end):
            raise MediaTutoringRefused("RIGHTS_DENIED", item["interval_id"])
        inside = sorted(row["timestamp_ms"] for row in frames
                        if start <= row["timestamp_ms"] < end)
        wanted = []
        if not inside or inside[0] > start:
            wanted.append(start)
        if not inside or inside[-1] < end - 1:
            wanted.append(end - 1)
        for timestamp in wanted:
            if len(requests) == cap:
                return {"requests": requests, "truncated": True,
                        "retrieval_performed": False}
            requests.append({"interval_id": item["interval_id"],
                             "timestamp_ms": timestamp,
                             "reason": "DECISIVE_BEFORE_AFTER_FRAME",
                             "timeline_epoch": snapshot["timeline_epoch"]})
    return {"requests": requests, "truncated": False,
            "retrieval_performed": False}


def bind_application_transfer(*, explanation, index_snapshot, current_app,
                              geometry, candidates, demonstrated_goal,
                              pack_binding, visual_adapter_qualified=False):
    """Ground a concept in the current app; tutorial pixels provide no target."""
    current = validate_current(explanation, index_snapshot)
    if current["status"] != "CURRENT":
        raise MediaTutoringRefused("STALE_MEDIA", current["reason"])
    _text(demonstrated_goal, "demonstrated_goal", 1000)
    app_keys = ("observation_id", "source_id", "source_revision",
                "capture_epoch", "geometry_revision", "app_id", "app_version")
    _exact(current_app, app_keys, "current app")
    for field in ("observation_id", "source_id", "source_revision",
                  "geometry_revision", "app_id"):
        _ident(current_app[field], field)
    _integer(current_app["capture_epoch"], "capture_epoch")
    _version(current_app["app_version"], "current app version")
    pack_keys = ("schema", "status", "pack_id", "pack_digest", "review_scope",
                 "app_id", "version_min", "version_max", "route_claims",
                 "sample_ids")
    _exact(pack_binding, pack_keys, "pack binding")
    if (pack_binding["schema"] != "tutor.media-transfer-pack/1"
            or pack_binding["status"] != "QUALIFIED"
            or pack_binding["review_scope"] != "subject_matter_human"):
        raise MediaTutoringRefused("PACK_NOT_QUALIFIED", "transfer needs qualified reviewed content")
    _ident(pack_binding["pack_id"], "pack_id")
    _digest(pack_binding["pack_digest"], "pack_digest")
    if pack_binding["app_id"] != current_app["app_id"]:
        raise MediaTutoringRefused("APP_MISMATCH", "pack targets another application")
    requested = _version(current_app["app_version"], "current app version")
    if not (_version(pack_binding["version_min"], "minimum pack version") <= requested
            <= _version(pack_binding["version_max"], "maximum pack version")):
        raise MediaTutoringRefused("APP_VERSION_UNQUALIFIED", current_app["app_version"])
    if (not isinstance(pack_binding["route_claims"], list)
            or not pack_binding["route_claims"]
            or any(not isinstance(value, str) or not value.strip()
                   for value in pack_binding["route_claims"])):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "route claims")
    if (not isinstance(pack_binding["sample_ids"], list)
            or not pack_binding["sample_ids"]):
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "sample IDs")
    for sample_id in pack_binding["sample_ids"]:
        _ident(sample_id, "sample_id")
    try:
        grounded = tutor_grounding.choose_target(
            candidates, source_id=current_app["source_id"],
            source_revision=current_app["source_revision"],
            geometry_revision=current_app["geometry_revision"], geometry=geometry,
            query=demonstrated_goal,
            visual_adapter_qualified=visual_adapter_qualified)
    except (tutor_grounding.GroundingRefused, tutor_sources.SourceRefused) as exc:
        raise MediaTutoringRefused("APP_GROUNDING_REFUSED", str(exc)) from exc
    base = {
        "schema": "tutor.media-app-transfer/1",
        "explanation_id": explanation["explanation_id"],
        "demonstrated_goal": demonstrated_goal,
        "current_app": copy.deepcopy(current_app),
        "tutorial_coordinates_used": False,
        "pack": {"pack_id": pack_binding["pack_id"],
                 "pack_digest": pack_binding["pack_digest"],
                 "review_scope": pack_binding["review_scope"]},
    }
    if grounded["status"] != "GROUNDED":
        return {**base, "status": "ABSTAIN", "reason": grounded["reason"],
                "current_app_target": None, "practice_handoff": None}
    target = grounded["target"]
    return {
        **base, "status": "GROUNDED", "reason": grounded["reason"],
        "current_app_target": target,
        "practice_handoff": {
            "schema": "tutor.media-practice-handoff/1",
            "pack_id": pack_binding["pack_id"],
            "pack_digest": pack_binding["pack_digest"],
            "sample_ids": copy.deepcopy(pack_binding["sample_ids"]),
            "route_claims": copy.deepcopy(pack_binding["route_claims"]),
            "source_observation_id": current_app["observation_id"],
            "source_revision": current_app["source_revision"],
            "capture_epoch": current_app["capture_epoch"],
            "learner_success_claimed": False,
        },
    }


def request_playback_change(*, explanation, index_snapshot, action,
                            value, authority, now_monotonic_ms):
    """Return a bounded intent only after an explicit current user grant."""
    if validate_current(explanation, index_snapshot)["status"] != "CURRENT":
        raise MediaTutoringRefused("STALE_MEDIA", "explanation is not current")
    snapshot = _snapshot(index_snapshot)
    if action not in PLAYBACK_ACTIONS:
        raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "playback action")
    _exact(authority, ("schema", "grant_id", "actor", "user_initiated",
                       "media_id", "source_revision", "timeline_epoch",
                       "expires_at_monotonic_ms"), "playback authority")
    if authority["schema"] != "tutor.playback-authority/1":
        raise MediaTutoringRefused("PLAYBACK_AUTHORITY_DENIED", "authority schema")
    for field in ("grant_id", "actor"):
        _ident(authority[field], field)
    now = _integer(now_monotonic_ms, "now_monotonic_ms")
    if (authority["user_initiated"] is not True
            or authority["media_id"] != snapshot["media_id"]
            or authority["source_revision"] != snapshot["source_revision"]
            or authority["timeline_epoch"] != snapshot["timeline_epoch"]
            or _integer(authority["expires_at_monotonic_ms"], "authority expiry") <= now):
        raise MediaTutoringRefused("PLAYBACK_AUTHORITY_DENIED", "grant is absent, stale or expired")
    if action == "SEEK":
        checked_value = _integer(value, "seek value", 0, snapshot["duration_ms"])
    elif action == "RATE":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.25 <= value <= 4.0:
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "rate value")
        checked_value = float(value)
    else:
        if value is not None:
            raise MediaTutoringRefused("INVALID_MEDIA_TUTORING", "play/pause value must be null")
        checked_value = None
    return {
        "schema": "tutor.playback-intent/1", "action": action,
        "value": checked_value, "grant_id": authority["grant_id"],
        "actor": authority["actor"], "media_id": snapshot["media_id"],
        "source_revision": snapshot["source_revision"],
        "timeline_epoch": snapshot["timeline_epoch"],
        "executor": "NONE_INTENT_ONLY", "executed": False,
    }
