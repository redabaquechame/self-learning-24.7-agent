#!/usr/bin/env python3
"""SC-4A offline authorized temporal-media indexing witnesses."""

import copy
import json
import os
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import tutor_media_index as media  # noqa: E402


def refused(call, code):
    try:
        call()
    except media.MediaRefused as error:
        assert error.code == code, (error.code, error.detail)
        return
    raise AssertionError("expected " + code)


def fixture():
    path = os.path.join(AGENT_DIR, "evaluation", "tutor", "media_fixtures",
                        "caption-frame-seek-v1.json")
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def ingest(value, include_frame=True):
    source = value["source"]
    index = media.MediaIndex(source, now_monotonic_ms=1000, request_budget=7)
    for row in value["captions"]:
        index.ingest_caption(**row, source_revision=source["source_revision"],
                             content_sha256=source["content_sha256"],
                             timeline_epoch=index.timeline_epoch)
    if include_frame:
        for row in value["frames"]:
            index.ingest_frame(
                row["frame_id"], row["timestamp_ms"], row["payload_utf8"].encode(),
                row["mime"], row["provenance_ref"], source["source_revision"],
                source["content_sha256"], index.timeline_epoch)
    for row in value["gaps"]:
        index.record_gap(**row, timeline_epoch=index.timeline_epoch)
    for row in value["transitions"]:
        index.record_transition(**row, timeline_epoch=index.timeline_epoch)
    return index


def main():
    value = fixture()
    assert value["synthetic_only"] is True
    source = media.validate_source(value["source"])
    assert media.source_access(source, 1000) == {
        "available": True, "reason": "AUTHORIZED"}

    index = ingest(value)
    assert index.support("CAPTION", 500, 1800, 0) == {
        "supported": True, "reason": "CAPTION_EVIDENCE"}
    assert index.support("VISUAL", 1100, 1300, 0) == {
        "supported": True, "reason": "FRAME_EVIDENCE"}
    snapshot = index.snapshot()
    assert snapshot["captions"][0]["provenance_ref"] == "embedded-caption-track-1"
    assert snapshot["frames"][0]["byte_count"] == len(b"synthetic frame: menu open")
    assert snapshot["gaps"][0]["reason"] == "NO_CAPTION_TRACK"
    assert {row["kind"] for row in snapshot["transitions"]} == {"SCENE", "AD_START"}

    plan = index.plan_retrieval(0, 2000, [1200], 5)
    assert len(plan) == 5 and index.request_budget == 2
    assert [row["timestamp_ms"] for row in plan[:3]] == [1100, 1200, 1300]
    assert all(row["timeline_epoch"] == 0 for row in plan)
    refused(lambda: index.plan_retrieval(0, 2000, [], 3), "RETRIEVAL_BUDGET")

    old_epoch = index.timeline_epoch
    new_epoch = index.seek(2500, 1.5)
    assert new_epoch == old_epoch + 1 and index.playback_ms == 2500
    assert index.support("CAPTION", 500, 1800, old_epoch)["reason"] == "STALE_TIMELINE"
    refused(lambda: index.ingest_caption(
        "late-caption", 2500, 2600, "late", "en-CA", "track-1", "RAW",
        source["source_revision"], source["content_sha256"], old_epoch),
        "STALE_MEDIA")

    replacement = copy.deepcopy(source)
    replacement["source_revision"] = "revision-2"
    replacement["content_sha256"] = "b" * 64
    replacement_identity = index.replace_content(replacement, 1000)
    assert replacement_identity == {"content_epoch": 1, "timeline_epoch": 2}
    assert index.snapshot()["frames"][0]["source_revision"] == "revision-1"
    refused(lambda: index.ingest_frame(
        "stale-content-frame", 2500, b"frame", "application/x-test-frame",
        "decoder-1", source["source_revision"], source["content_sha256"], 2),
        "STALE_MEDIA")

    # Replacing content must not freeze a caller-supplied live expiry clock.
    replacement_clock = [1000]
    replacement_live = media.MediaIndex(
        source, 1000, 1, clock_ms=lambda: replacement_clock[0])
    replacement_live.replace_content(replacement, 1000)
    replacement_clock[0] = replacement["expires_at_monotonic_ms"]
    refused(lambda: replacement_live.seek(100), "MEDIA_UNAVAILABLE")

    # X025B: a transcript-only index can support a narrator/caption claim but
    # cannot relabel it as an independently observed visual action.
    transcript_only = ingest(value, include_frame=False)
    assert transcript_only.support("CAPTION", 500, 1800, 0)["supported"]
    assert transcript_only.support("VISUAL", 500, 1800, 0) == {
        "supported": False, "reason": "VISUAL_EVIDENCE_MISSING"}

    expired = copy.deepcopy(source)
    expired["expires_at_monotonic_ms"] = 1000
    assert media.source_access(expired, 1000)["reason"] == "SOURCE_EXPIRED"
    refused(lambda: media.MediaIndex(expired, 1000, 1), "MEDIA_UNAVAILABLE")
    clock = [1000]
    expiring_live = media.MediaIndex(source, 1000, 1, clock_ms=lambda: clock[0])
    clock[0] = 9000
    refused(lambda: expiring_live.ingest_frame(
        "after-expiry", 1200, b"frame", "application/x-test-frame", "decoder-1",
        source["source_revision"], source["content_sha256"], 0),
        "MEDIA_UNAVAILABLE")
    revoked = copy.deepcopy(source); revoked["rights"] = "REVOKED"
    refused(lambda: media.MediaIndex(revoked, 1000, 1), "MEDIA_UNAVAILABLE")
    denied = copy.deepcopy(source); denied["rights"] = "DENIED"
    refused(lambda: media.MediaIndex(denied, 1000, 1), "MEDIA_UNAVAILABLE")
    revoked_live = ingest(value)
    revoked_live.revoke()
    refused(lambda: revoked_live.ingest_frame(
        "after-revoke", 1200, b"frame", "application/x-test-frame", "decoder-1",
        source["source_revision"], source["content_sha256"],
        revoked_live.timeline_epoch), "MEDIA_UNAVAILABLE")
    refused(lambda: revoked_live.plan_retrieval(0, 1000, [], 1),
            "MEDIA_UNAVAILABLE")

    rights_limited = copy.deepcopy(source)
    rights_limited["allowed_intervals"] = [{"start_ms": 0, "end_ms": 1000}]
    limited = media.MediaIndex(rights_limited, 1000, 2)
    refused(lambda: limited.ingest_frame(
        "outside", 1200, b"frame", "application/x-test-frame", "decoder-1",
        source["source_revision"], source["content_sha256"], 0), "RIGHTS_DENIED")
    assert limited.snapshot()["frames"] == [] and limited.snapshot()["captions"] == []

    print("[X025A-offline] authorized captions/frames/intervals/gaps and transitions were indexed under exact content/timeline identity; seek invalidated old evidence and adaptive sampling stayed inside budget")
    print("[X025B-offline] transcript-only evidence refused an independently observed visual-action claim; expired, revoked, denied and out-of-rights sources remained unavailable")
    print("PASS test_tutor_media_index")


if __name__ == "__main__":
    main()
