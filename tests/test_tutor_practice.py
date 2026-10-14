#!/usr/bin/env python3
"""SC-2C safe-copy, variant and artifact-integrity witnesses (T042/T044/T045)."""

import copy
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import make_sandbox
import fileauth
import tutor_practice


def refused(fn, code):
    try:
        fn()
    except tutor_practice.PracticeRefused as error:
        assert error.code == code, (error.code, error.detail)
        return
    raise AssertionError(f"expected {code}")


def source_record(content_sha256, kind="SYNTHETIC_SAMPLE"):
    return {
        "source_ref": "courses/reporting/source.json",
        "content_sha256": content_sha256,
        "source_revision": "source-r1",
        "source_kind": kind,
        "rights": "SYNTHETIC" if kind == "SYNTHETIC_SAMPLE" else "OWNER_DOCUMENT",
        "license_id": "synthetic-fixture" if kind == "SYNTHETIC_SAMPLE" else "owner-document",
        "practice_eligible": kind == "SYNTHETIC_SAMPLE",
        "pack_id": "reporting-v1",
        "pack_version": "1.0.0",
    }


def specification():
    return {
        "practice_id": "practice-1",
        "user_id": "user-1",
        "project_id": "project-1",
        "sample_id": "safe-group-sum-1",
        "mode": "PARTIAL",
        "artifact_name": "grouped-result.json",
        "verifier": "CANONICAL_JSON_EQUALS",
        "expected_result": [
            {"group": "east", "total": 1000},
            {"group": "west", "total": 500},
        ],
        "watch_refs": ["courses/reporting/source.json"],
        "revealed_elements": 2,
    }


def variant(variant_id, artifact_name, content_sha256, *, mode="INDEPENDENT",
            signature="grouped-v1", novelty=None, reveals=0, assistance="NONE"):
    return {
        "schema": "tutor.practice-variant/1",
        "variant_id": variant_id,
        "mode": mode,
        "artifact_name": artifact_name,
        "content_sha256": content_sha256,
        "task_signature": signature,
        "novelty_dimensions": list(novelty or []),
        "revealed_elements": reveals,
        "assistance": assistance,
        "status": "CANDIDATE",
    }


def main():
    root = make_sandbox("test_tutor_practice", {}, {}, {})
    source = [
        {"group": "east", "amount": 1200},
        {"group": "west", "amount": 500},
        {"group": "east", "amount": -200},
    ]
    source_bytes = (json.dumps(source, sort_keys=True) + "\n").encode("utf-8")
    fileauth.write_bytes(root, "courses/reporting/source.json", source_bytes)
    digest = hashlib.sha256(source_bytes).hexdigest()

    production = source_record(digest, "PRODUCTION_DOCUMENT")
    before = set(os.listdir(os.path.join(root, "courses")))
    refused(lambda: tutor_practice.create_practice_copy(
        root, production, specification()), "SAFE_COPY_REQUIRED")
    assert set(os.listdir(os.path.join(root, "courses"))) == before

    session = tutor_practice.create_practice_copy(
        root, source_record(digest), specification())
    assert session["status"] == "ACTIVE"
    assert session["executor"] == "NONE_DETERMINISTIC_IN_PROCESS"
    assert fileauth.sha256_bytes(root, session["artifact_ref"]) == digest

    output = specification()["expected_result"]
    fileauth.write_text(root, session["artifact_ref"],
                        json.dumps(output, sort_keys=True) + "\n")
    result = tutor_practice.verify_practice(root, session)
    assert result["mechanical_status"] == "PASSED"
    assert result["protected_sources_unchanged"] is True
    assert result["human_review_required"] is False

    forged_target = copy.deepcopy(session)
    forged_target["artifact_ref"] = "courses/reporting/source.json"
    refused(lambda: tutor_practice.reset_practice(root, forged_target),
            "INVALID_PRACTICE")
    forged_answer = copy.deepcopy(session)
    forged_answer["expected_result"] = source
    refused(lambda: tutor_practice.verify_practice(root, forged_answer),
            "INVALID_PRACTICE")
    fileauth.write_text(root, session["artifact_ref"],
                        '{"group":"east","group":"west"}\n')
    refused(lambda: tutor_practice.verify_practice(root, session),
            "ARTIFACT_VERIFICATION_FAILED")
    fileauth.write_text(root, session["artifact_ref"],
                        json.dumps(output, sort_keys=True) + "\n")

    baseline = variant("base", "answer.json", digest)
    renamed = variant("renamed", "answer-copy.json", digest)
    transfer = tutor_practice.assess_variant(baseline, renamed)
    assert transfer == {"transfer_eligible": False,
                        "reason": "IDENTICAL_CONTENT_FILENAME_ONLY"}
    novel = variant("novel", "answer.json", "1" * 64,
                    signature="grouped-v2", novelty=["INPUT_VALUES"])
    assert tutor_practice.assess_variant(baseline, novel)["transfer_eligible"] is True
    refused(lambda: tutor_practice.assess_variant(
        baseline, variant("bad", "bad.json", "2" * 64, mode="INDEPENDENT",
                          novelty=["INPUT_VALUES"], reveals=1)),
            "INDEPENDENT_VARIANT_EXPOSED")

    reset = tutor_practice.reset_practice(root, session)
    assert reset["status"] == "ACTIVE"
    assert fileauth.sha256_bytes(root, session["artifact_ref"]) == digest

    fileauth.write_text(root, "courses/reporting/source.json", "tampered\n")
    refused(lambda: tutor_practice.verify_practice(root, session),
            "UNINTENDED_CHANGE")
    fileauth.write_bytes(root, "courses/reporting/source.json", source_bytes)
    stopped = tutor_practice.stop_practice(session)
    assert stopped["status"] == "STOPPED"
    refused(lambda: tutor_practice.reset_practice(root, stopped),
            "PRACTICE_STOPPED")

    print("[T042] production document declined; qualified synthetic source copied through File Authority")
    print("[T044] filename-only candidate was not accepted as novel transfer")
    print("[T045-offline] source digest stayed unchanged while the isolated practice artifact changed")
    print("[practice] mechanical verifier, reset, Stop and reveal accounting passed")


if __name__ == "__main__":
    main()
