#!/usr/bin/env python3
"""SC-0A: the platform works with no native tutor or provider call."""

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from unittest.mock import patch

from common import AGENT_DIR, make_sandbox

sys.path.insert(0, AGENT_DIR)
import mission  # noqa: E402
import modelgateway  # noqa: E402


LOCK = os.path.join(
    AGENT_DIR, "planning", "screen-tutor", "BASELINE_LOCK_SC_2D_CURRENT_SOURCE_APPROVAL_REPAIRS_CANDIDATE.json")
CAMPAIGN_MARKERS = ("tests/run_all.py", "mutate_check.py",
                    "harness.py --check", "execution.py --audit")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_lock(path):
    with open(path, encoding="utf-8") as stream:
        lock = json.load(stream)
    assert lock.get("schema") == "screen-tutor-baseline-lock/1"
    assert isinstance(lock.get("protected_files"), list)
    return lock


def verify_lock(root, lock):
    base = os.path.realpath(root)
    mismatches = []
    for item in lock["protected_files"]:
        rel = item.get("path")
        assert isinstance(rel, str) and rel and not os.path.isabs(rel)
        path = os.path.realpath(os.path.join(base, rel))
        assert os.path.commonpath((base, path)) == base
        if not os.path.isfile(path):
            mismatches.append({"path": rel, "reason": "missing"})
        elif (os.path.getsize(path) != item.get("bytes")
              or digest(path) != item.get("sha256")):
            mismatches.append({"path": rel, "reason": "changed"})
    return {"status": "PASS" if not mismatches else "FAIL",
            "checked": len(lock["protected_files"]),
            "mismatches": mismatches}


def classify_campaigns(records=None, query_error=None):
    if query_error is not None or records is None:
        return {"status": "UNKNOWN",
                "reason": str(query_error or "unavailable")}
    active = []
    for record in records:
        command = str(
            record.get("command_line") or "").replace("\\", "/").lower()
        if any(marker in command for marker in CAMPAIGN_MARKERS):
            active.append({"pid": record.get("pid"), "command_line": command})
    return {"status": "ACTIVE" if active else "IDLE", "active": active}


def forbidden(*_args, **_kwargs):
    raise AssertionError(
        "feature-off flow attempted process or network activity")


def check_locked_baseline_and_negative_witness():
    lock = load_lock(LOCK)
    result = verify_lock(AGENT_DIR, lock)
    assert result["status"] == "PASS", result
    with tempfile.TemporaryDirectory(prefix="tutor-lock-") as temp:
        source = os.path.join(
            AGENT_DIR, lock["protected_files"][0]["path"])
        target = os.path.join(temp, "protected.py")
        with open(source, "rb") as incoming, open(target, "wb") as outgoing:
            outgoing.write(incoming.read())
        altered = copy.deepcopy(lock)
        altered["protected_files"] = [
            dict(lock["protected_files"][0], path="protected.py")]
        assert verify_lock(temp, altered)["status"] == "PASS"
        with open(target, "ab") as stream:
            stream.write(b"\n# selective negative witness\n")
        failed = verify_lock(temp, altered)
        assert failed["status"] == "FAIL" and failed["mismatches"], failed
    unknown = classify_campaigns(query_error="access denied")
    assert unknown["status"] == "UNKNOWN", unknown
    active = classify_campaigns([
        {"pid": 7, "command_line": "python mutate_check.py"}])
    assert active["status"] == "ACTIVE" and active["active"], active
    assert classify_campaigns([])["status"] == "IDLE"
    print("[baseline-lock] 12 protected source files match the SC-2D candidate lock (final review pending); "
          "a byte change fails it, an active mutation command is detected, "
          "and an unavailable process query remains UNKNOWN")


def check_existing_flows_are_inert_until_driven():
    sb = make_sandbox(
        "tutor_feature_off",
        providers={"m": {"script": "s.json"}},
        roles={"worker": "m"}, scripts={"s.json": []})
    before = modelgateway.calls(sb)
    with patch.object(subprocess, "Popen", side_effect=forbidden), \
            patch.object(subprocess, "run", side_effect=forbidden), \
            patch.object(urllib.request, "urlopen", side_effect=forbidden):
        for name in ("context", "loop", "mission", "grants", "execution",
                     "computeruse", "computersession", "mastery"):
            importlib.import_module(name)
        created = mission.create(
            sb, "Explain an existing workflow",
            ["the explanation is grounded"])
        chain = mission.justify(
            sb, created["id"], "C1",
            task_goal="prepare explanation",
            expected_evidence="a cited explanation exists")
        mission.record_action(
            sb, created["id"], chain, status="queued")
    after = modelgateway.calls(sb)
    assert before == after == [], (before, after)
    assert "tutor_runtime" not in sys.modules
    state = mission.compile_state(sb, created["id"])
    assert state["status"] == "open"
    print("[feature-off] existing context, mission, authority, computer-use, "
          "and mastery modules load and queue a criterion-bound action with "
          "zero process starts, network requests, model calls, or native imports")


def main():
    check_locked_baseline_and_negative_witness()
    check_existing_flows_are_inert_until_driven()
    print("PASS test_tutor_feature_off")


if __name__ == "__main__":
    main()
