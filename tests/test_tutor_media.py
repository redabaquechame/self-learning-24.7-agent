#!/usr/bin/env python3
"""SC-4 offline timestamped explanation and app-transfer witnesses."""

import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import tutor_media as media  # noqa: E402
import tutor_media_index  # noqa: E402
import tutor_packs  # noqa: E402
import tutor_sources  # noqa: E402


PACK_SOURCE = os.path.join(AGENT_DIR, "teaching_packs", "video-transfer-v1")
FINAL_TEXT = "SEALED-VIDEO-TRANSFER-ANSWER: east 10 west 5"


def refused(call, code):
    try:
        call()
    except media.MediaTutoringRefused as error:
        assert error.code == code, (error.code, error.detail)
        return
    raise AssertionError("expected " + code)


def fixture():
    path = os.path.join(AGENT_DIR, "evaluation", "tutor", "media_fixtures",
                        "caption-frame-seek-v1.json")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def media_index(*, frame=True, caption=True):
    value = fixture()
    source = value["source"]
    index = tutor_media_index.MediaIndex(source, 1000, 12)
    if caption:
        for row in value["captions"]:
            index.ingest_caption(**row, source_revision=source["source_revision"],
                                 content_sha256=source["content_sha256"],
                                 timeline_epoch=0)
    if frame:
        for row in value["frames"]:
            index.ingest_frame(
                row["frame_id"], row["timestamp_ms"], row["payload_utf8"].encode(),
                row["mime"], row["provenance_ref"], source["source_revision"],
                source["content_sha256"], 0)
        index.ingest_frame("frame-before", 1100, b"synthetic closed menu",
                           "application/x-test-frame", "fixture-decoder",
                           source["source_revision"], source["content_sha256"], 0)
        index.ingest_frame("frame-after", 1300, b"synthetic open menu",
                           "application/x-test-frame", "fixture-decoder",
                           source["source_revision"], source["content_sha256"], 0)
    for row in value["gaps"]:
        index.record_gap(**row, timeline_epoch=0)
    for row in value["transitions"]:
        index.record_transition(**row, timeline_epoch=0)
    return index


def audio(snapshot):
    return [{
        "audio_id": "audio-1", "start_ms": 1000, "end_ms": 1400,
        "origin": "MEDIA", "sha256": hashlib.sha256(b"synthetic audio").hexdigest(),
        "source_revision": snapshot["source_revision"],
        "content_sha256": snapshot["content_sha256"],
        "content_epoch": snapshot["content_epoch"],
        "timeline_epoch": snapshot["timeline_epoch"],
        "provenance_ref": "fixture-audio-decoder",
    }]


def claims():
    return [
        {"claim_id": "narrator-1", "kind": "NARRATOR_CLAIM",
         "text": "The narrator says to choose Save As.", "modality": "CAPTION",
         "start_ms": 500, "end_ms": 1000, "evidence_ids": ["caption-1"],
         "certainty": "REPORTED"},
        {"claim_id": "transition-1", "kind": "VISIBLE_TRANSITION",
         "text": "The menu changes from closed to open.", "modality": "VISUAL",
         "start_ms": 1050, "end_ms": 1350,
         "evidence_ids": ["frame-before", "frame-after"],
         "certainty": "OBSERVED"},
        {"claim_id": "audio-event-1", "kind": "AUDIO_EVENT",
         "text": "A media audio cue occurs.", "modality": "AUDIO",
         "start_ms": 1000, "end_ms": 1400, "evidence_ids": ["audio-1"],
         "certainty": "OBSERVED"},
    ]


def explanation(index):
    snapshot = index.snapshot()
    return media.build_explanation(
        explanation_id="explanation-1", question="What changed in the menu?",
        index_snapshot=snapshot, start_ms=0, end_ms=5000,
        mode="FULL_ACCESSIBLE_SOURCE", requested_scope="ENTIRE_SOURCE",
        claims=claims(), audio_evidence=audio(snapshot))


def candidate(target_id="group-control", name="Group", context="Data toolbar"):
    return {
        "target_id": target_id, "source_id": "current-app-window",
        "source_revision": "app-revision-7", "geometry_revision": "geometry-4",
        "modality": "ACCESSIBILITY", "name": name, "role": "button",
        "context": context,
        "bounds": {"x": 700, "y": 80, "width": 90, "height": 36},
        "confidence": 1.0, "origin": "APPLICATION",
    }


GEOMETRY = {
    "coordinate_space": "source_pixels", "source_width": 1600,
    "source_height": 900,
    "crop": {"x": 0, "y": 0, "width": 1600, "height": 900},
    "model_width": 1600, "model_height": 900,
    "desktop_origin_x": 0, "desktop_origin_y": 0, "native_dpi_scale": 1.0,
}

CURRENT_APP = {
    "observation_id": "observation-current-1", "source_id": "current-app-window",
    "source_revision": "app-revision-7", "capture_epoch": 4,
    "geometry_revision": "geometry-4", "app_id": "sheet-app",
    "app_version": "1.5.0",
}


def qualified_binding(pack_digest="c" * 64):
    return {
        "schema": "tutor.media-transfer-pack/1", "status": "QUALIFIED",
        "pack_id": "video-transfer-v1", "pack_digest": pack_digest,
        "review_scope": "subject_matter_human", "app_id": "sheet-app",
        "version_min": "1.0.0", "version_max": "1.9.9",
        "route_claims": ["Use the current semantic grouping control."],
        "sample_ids": ["safe-video-transfer-1"],
    }


def source_record(source_id, excerpt_id, text, purpose="teaching"):
    return {
        "schema": "tutor.source/1", "source_id": source_id, "revision": "rev-1",
        "tenant_id": "tenant-1", "project_id": "project-1",
        "title": "Synthetic video transfer source", "source_type": "fixture",
        "locator": "fixture://video-transfer/" + source_id, "app_id": "sheet-app",
        "app_versions": {"min": "1.0.0", "max": "1.9.9"},
        "rights": {"status": "permitted", "license_id": "fixture-license",
                   "permitted_ranges": [{"start": 0, "end": 20}]},
        "purpose": purpose,
        "excerpts": [{"excerpt_id": excerpt_id, "start": 1, "end": 2,
                      "text": text, "source_revision": "rev-1",
                      "tenant_id": "tenant-1", "project_id": "project-1",
                      "license_id": "fixture-license", "purpose": purpose}],
    }


def main():
    index = media_index()
    snapshot = index.snapshot()
    answer = explanation(index)
    assert answer["answer_status"] == "PARTIAL_EVIDENCE"
    assert answer["complete_source_understanding_claimed"] is False
    assert answer["processed_coverage"]["caption_intervals"] == [
        {"caption_id": "caption-1", "start_ms": 500, "end_ms": 1800}]
    assert {row["claim_id"] for row in answer["claims"]} == {
        "narrator-1", "transition-1", "audio-event-1"}
    assert "GAP_CAPTION_NO_CAPTION_TRACK" in answer["limitations"]
    print("[T052-offline] full-source mode exposed exact authorized caption/frame/audio coverage and gaps while refusing to claim complete-source understanding")

    old = copy.deepcopy(answer)
    index.seek(2600, 1.5)
    assert media.validate_current(old, index.snapshot()) == {
        "status": "SUPPRESSED", "reason": "STALE_TIMELINE_EPOCH"}
    missing_timeline = copy.deepcopy(old)
    del missing_timeline["binding"]["timeline_epoch"]
    assert media.validate_current(missing_timeline, snapshot)["status"] == "SUPPRESSED"
    forged_snapshot = copy.deepcopy(snapshot)
    forged_snapshot["frames"][0]["source_revision"] = "foreign-revision"
    refused(lambda: media.validate_current(old, forged_snapshot), "STALE_MEDIA")
    print("[T053-offline] a seek changed only the timeline epoch and suppressed the old explanation; a missing epoch could not validate as current")

    one_frame = copy.deepcopy(claims()[1])
    one_frame["evidence_ids"] = ["frame-1"]
    refused(lambda: media.build_explanation(
        explanation_id="bad-transition", question="Did the menu change?",
        index_snapshot=snapshot, start_ms=1000, end_ms=1500,
        mode="CAPTURED_INTERVAL", requested_scope="WINDOW", claims=[one_frame]),
        "INSUFFICIENT_VISUAL_COVERAGE")
    requests = media.plan_decisive_visual_evidence(
        media_index(frame=False).snapshot(),
        [{"interval_id": "fast-menu", "start_ms": 1000, "end_ms": 1400}], 2)
    assert [row["timestamp_ms"] for row in requests["requests"]] == [1000, 1399]
    assert requests["retrieval_performed"] is False
    frame_gapped = media_index()
    frame_gapped.record_gap("gap-fast-menu", 1050, 1350, "FRAME",
                            "DECODER_DROPPED_FRAMES", 0)
    refused(lambda: media.build_explanation(
        explanation_id="gapped-transition", question="Did the menu change?",
        index_snapshot=frame_gapped.snapshot(), start_ms=1000, end_ms=1500,
        mode="CAPTURED_INTERVAL", requested_scope="WINDOW",
        claims=[claims()[1]]), "EVIDENCE_GAP")
    print("[T054-offline] a transition needed distinct before/after frame bytes and missing decisive coverage produced a bounded retrieval plan, never fabricated observations")

    contested = media_index()
    contested.ingest_caption(
        "caption-contested", 2500, 2800, "Possibly choose Export", "en-CA",
        "synthetic-wrong-subtitle", "CONTESTED", snapshot["source_revision"],
        snapshot["content_sha256"], 0)
    wrong_claim = {
        "claim_id": "wrong-caption", "kind": "NARRATOR_CLAIM",
        "text": "The narrator says Export.", "modality": "CAPTION",
        "start_ms": 2500, "end_ms": 2800,
        "evidence_ids": ["caption-contested"], "certainty": "REPORTED"}
    refused(lambda: media.build_explanation(
        explanation_id="wrong-subtitle-answer", question="What was said?",
        index_snapshot=contested.snapshot(), start_ms=2400, end_ms=3000,
        mode="SELECTED_CLIP", requested_scope="WINDOW", claims=[wrong_claim]),
        "CONTESTED_CAPTION")
    print("[T055-offline] narrator, pixel and audio claims retained distinct evidence IDs; a contested subtitle could not silently become a reported fact")

    current_index = media_index()
    current_answer = explanation(current_index)
    transfer = media.bind_application_transfer(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        current_app=CURRENT_APP, geometry=GEOMETRY, candidates=[candidate()],
        demonstrated_goal="Use the Group control in the Data toolbar",
        pack_binding=qualified_binding())
    assert transfer["status"] == "GROUNDED"
    assert transfer["current_app_target"]["source_id"] == "current-app-window"
    assert transfer["tutorial_coordinates_used"] is False
    assert transfer["practice_handoff"]["learner_success_claimed"] is False
    ambiguous = media.bind_application_transfer(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        current_app=CURRENT_APP, geometry=GEOMETRY,
        candidates=[candidate("group-top"), candidate("group-bottom")],
        demonstrated_goal="Use Group", pack_binding=qualified_binding())
    assert ambiguous["status"] == "ABSTAIN" and ambiguous["current_app_target"] is None
    old_app = dict(CURRENT_APP); old_app["app_version"] = "2.0.0"
    refused(lambda: media.bind_application_transfer(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        current_app=old_app, geometry=GEOMETRY, candidates=[candidate()],
        demonstrated_goal="Use Group", pack_binding=qualified_binding()),
        "APP_VERSION_UNQUALIFIED")
    print("[T056-offline] the demonstrated goal re-grounded through a unique current-app semantic control; tutorial coordinates were absent, ambiguity abstained and an unqualified app version refused")

    denied_authority = {
        "schema": "tutor.playback-authority/1", "grant_id": "grant-1",
        "actor": "user-1", "user_initiated": False,
        "media_id": snapshot["media_id"], "source_revision": snapshot["source_revision"],
        "timeline_epoch": snapshot["timeline_epoch"],
        "expires_at_monotonic_ms": 5000,
    }
    refused(lambda: media.request_playback_change(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        action="SEEK", value=2000, authority=denied_authority,
        now_monotonic_ms=1000), "PLAYBACK_AUTHORITY_DENIED")
    allowed_authority = dict(denied_authority); allowed_authority["user_initiated"] = True
    intent = media.request_playback_change(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        action="SEEK", value=2000, authority=allowed_authority,
        now_monotonic_ms=1000)
    assert intent["executed"] is False and intent["executor"] == "NONE_INTENT_ONLY"
    print("[T057-offline] media words granted no playback authority; an explicit current user grant produced a bounded unexecuted seek intent")

    screenshot_only = media_index(frame=True, caption=False)
    screenshot_summary = media.build_explanation(
        explanation_id="screenshot-only", question="Explain the complete video",
        index_snapshot=screenshot_only.snapshot(), start_ms=0, end_ms=5000,
        mode="FULL_ACCESSIBLE_SOURCE", requested_scope="ENTIRE_SOURCE", claims=[])
    assert screenshot_summary["answer_status"] == "PARTIAL_EVIDENCE"
    assert "INSUFFICIENT_FOR_COMPLETE_SOURCE_CLAIM" in screenshot_summary["limitations"]
    assert screenshot_summary["complete_source_understanding_claimed"] is False
    print("[X010A-X010B-offline] a screenshot-only source stayed partial for a complete-video question, and stale or missing timeline identity suppressed old guidance")

    home = tempfile.mkdtemp(prefix="video-transfer-pack-")
    try:
        tutor_sources.register_source(home, source_record(
            "video-transfer-official", "grouping-concept",
            "Grouping counts every safe source row exactly once."))
        tutor_sources.register_source(home, source_record(
            "video-transfer-asset", "safe-rows",
            "Synthetic east and west rows contain integer amounts only."))
        tutor_sources.register_source(home, source_record(
            "video-transfer-final", "sealed-answer", FINAL_TEXT,
            purpose="final_assessment"))
        tutor_packs.install_candidate(home, PACK_SOURCE)
        validation = tutor_packs.validate_pack(home, "video-transfer-v1")
        assert validation["ok"], validation
        assert tutor_packs.status(home, "video-transfer-v1")["status"] == "CANDIDATE"
        try:
            tutor_packs.assignment_manifest(home, "video-transfer-v1")
            raise AssertionError("candidate media transfer pack became assignable")
        except tutor_packs.PackRefused as error:
            assert error.code == "PACK_NOT_ASSIGNABLE"
    finally:
        shutil.rmtree(home, ignore_errors=True)
    refused(lambda: media.bind_application_transfer(
        explanation=current_answer, index_snapshot=current_index.snapshot(),
        current_app=CURRENT_APP, geometry=GEOMETRY, candidates=[candidate()],
        demonstrated_goal="Use Group",
        pack_binding={**qualified_binding(), "status": "CANDIDATE"}),
        "PACK_NOT_QUALIFIED")
    print("[content-boundary] the mechanically valid video-transfer pack remained candidate and unassignable; only a synthetic qualified-binding record exercised the downstream contract")
    print("PASS test_tutor_media")


if __name__ == "__main__":
    main()
