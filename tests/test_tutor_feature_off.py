#!/usr/bin/env python3
"""SC-0A — Screen Tutor is inert until an owner deliberately enables it.

This is the preservation test for the new program.  It does not prove any
Screen Tutor feature works; it proves the existing fleet still has a known
baseline while the feature is OFF, and that the baseline record is capable of
detecting a changed protected anchor.
"""

import hashlib
import importlib
import json
import os
import re
import sys

from common import AGENT_DIR, make_sandbox, read_state, run_drain

sys.path.insert(0, AGENT_DIR)
import consult                 # noqa: E402
import evidence                # noqa: E402
import grants                  # noqa: E402
import loop                    # noqa: E402
import modelgateway            # noqa: E402

TEST_NAME = "test_tutor_feature_off.py"
BASELINE_REL = os.path.join("planning", "screen-tutor", "BASELINE_LOCK.json")
BASELINE_PATH = os.path.join(AGENT_DIR, BASELINE_REL)
CORE_MODULES = (
    "context", "modelgateway", "grants", "execution", "fileauth", "contract",
    "computersession", "computerverify", "training", "consult", "evidence",
)


def git_blob_sha(raw):
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw).hexdigest()


def _load_baseline():
    assert os.path.exists(BASELINE_PATH), (
        "SC-0A baseline lock is missing; feature-off behavior must not be "
        "accepted until the current source and planning package are pinned")
    with open(BASELINE_PATH, encoding="utf-8") as f:
        lock = json.load(f)
    assert lock.get("schema") == "screen-tutor.baseline-lock.v1"
    base = (lock.get("source") or {}).get("base_commit")
    assert isinstance(base, str) and re.fullmatch(r"[0-9a-f]{40}", base), base
    anchors = lock.get("protected_anchors") or []
    seams = lock.get("interface_seams") or []
    assert anchors, "the lock needs at least one protected source anchor"
    assert seams, "the lock needs the audited Screen Tutor interface seams"
    assert str((lock.get("process_observation") or {}).get("local_campaign_status", "")).startswith(
        "UNKNOWN"), "a process campaign we cannot inspect must stay UNKNOWN, never guessed idle"
    return lock


def _check_anchors(lock):
    for row in lock["protected_anchors"]:
        rel = row["path"]
        expected = row["git_blob_sha"]
        path = os.path.join(AGENT_DIR, *rel.split("/"))
        assert os.path.isfile(path), f"protected anchor disappeared: {rel}"
        raw = open(path, "rb").read()
        got = git_blob_sha(raw)
        assert got == expected, f"protected anchor changed: {rel}: {got} != {expected}"
    # Negative witness without touching the checkout: a one-byte source change
    # must not compare equal to the frozen anchor.
    first = lock["protected_anchors"][0]
    path = os.path.join(AGENT_DIR, *first["path"].split("/"))
    raw = open(path, "rb").read()
    assert git_blob_sha(raw + b"\n# SC-0A negative witness\n") != first["git_blob_sha"]
    print(f"[baseline] {len(lock['protected_anchors'])} protected anchors match; "
          "an in-memory mutation is rejected by the same digest comparison")


def _import_core_without_native_tutor():
    for name in CORE_MODULES:
        importlib.import_module(name)
    assert "screen_tutor_native" not in sys.modules
    assert "companion_native" not in sys.modules
    print(f"[imports] {len(CORE_MODULES)} existing core modules import with no native tutor loaded")


def _representative_task_flow():
    script = [{"tool": "finish_task", "args": {"summary": "feature-off baseline task"}}]
    sb = make_sandbox(
        "tutor-feature-off-task",
        providers={"m": {"script": "script.json"}},
        roles={"practitioner": "m"},
        scripts={"script.json": script},
        role_tools={"practitioner": ["finish_task"]},
    )
    agent = loop.Agent(sb)
    done = f'"{sys.executable}" -c "pass"'
    tid = agent.add_task("practitioner", "complete the feature-off baseline task",
                         done_check=done)
    assert run_drain(sb) == 0
    task = next(t for t in read_state(sb)["tasks"] if t["id"] == tid)
    assert task["status"] == "done", (task["status"], task.get("error"))
    calls = modelgateway.calls(sb, task=tid)
    assert calls, "the representative existing task must really exercise the model gateway"
    assert not [c for c in calls if c.get("purpose") in ("vision", "transcription")], calls
    assert grants.load(sb) == [], "feature-off work must not mint standing grants"
    for rel in ("captures", "screen-tutor", "screen_tutor", "companion"):
        assert not os.path.exists(os.path.join(sb, rel)), f"feature-off created {rel} runtime state"
    assert not os.path.exists(os.path.join(sb, "effects", "computer")), \
        "feature-off baseline task must not start a computer session"
    print("[task flow] existing mock task completes through the normal gateway with no "
          "vision/transcription call, tutor state, grant, or computer session")


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _representative_consult_flow():
    sb = make_sandbox(
        "tutor-feature-off-consult",
        providers={"m": {"script": "script.json"}},
        roles={"consultant": "m"},
        scripts={"script.json": []},
    )
    _write(sb, "courses/demo/index.md", "01 | alpha fact |\n")
    _write(sb, "courses/demo/lessons/01/notes.md",
           "- C-0001 The alpha fact is preserved [src: fixture].\n")
    tid, answer = consult.start_consult(sb, "What is the alpha fact?")
    task = next(t for t in read_state(sb)["tasks"] if t["id"] == tid)
    assert task["status"] == "queued"
    assert answer.startswith("consults/") and task.get("done_check")
    assert "citecheck.py" in task["done_check"]
    calls = modelgateway.calls(sb)
    assert not [c for c in calls if c.get("purpose") in ("vision", "transcription")], calls
    print("[consult flow] existing consultation queues with its citation gate and no "
          "screen capture or multimodal provider call")


def _evidence_registration():
    assert TEST_NAME in evidence.registered_tests(), "SC-0A test is not in tests/run_all.py"
    owners = [name for name, spec in evidence.SYSTEMS.items()
              if TEST_NAME in spec.get("tests", [])]
    assert owners == ["1. Harness & loop"], f"SC-0A evidence must have one owner, got {owners}"
    print("[evidence] feature-off preservation test is registered and mapped to one system")


def main():
    lock = _load_baseline()
    _check_anchors(lock)
    _import_core_without_native_tutor()
    _representative_task_flow()
    _representative_consult_flow()
    _evidence_registration()
    print("PASS test_tutor_feature_off")


if __name__ == "__main__":
    main()
