#!/usr/bin/env python3
"""SC-1A local boundary tests; real Windows capture remains a native gate."""

import copy
import json
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import tutor_contracts as T  # noqa: E402
from tutor_service import TutorService, TutorUnavailable  # noqa: E402
from tutor_session import (AuthenticatedLocalBridge, SelectedSource,  # noqa: E402
                           SessionRefusal, TutorSession)


def expect(error, call, contains=""):
    try:
        call()
    except error as exc:
        assert contains in str(exc), (contains, str(exc))
        return
    raise AssertionError("expected " + error.__name__)


def session():
    value = TutorSession("session-1", "user-1", "tenant-1", "project-1",
                         ["source-1"])
    value.invoke()
    value.select_source(SelectedSource("source-1", "WINDOW", "source-r4",
                                       "a" * 64))
    return value


def owner_state(value):
    return {"user_id": "user-1", "tenant_id": "tenant-1", "project_id": "project-1",
            "consent_revision": "consent-r3", "capture_epoch": value.capture_epoch,
            "source_ids": ["source-1"], "source_revisions": {"source-1": "source-r4"},
            "observation_ids": ["obs-1"], "artifact_refs": ["artifact-1"],
            "now_monotonic_ms": 2000, "cancellation_generation": value.cancellation_generation,
            "current_cancellation_generation": value.cancellation_generation,
            "grant_expires_at_monotonic_ms": 9000, "mode": "GUIDE", "actor": "SYSTEM",
            "grant_view": ["observe", "explain", "annotate"],
            "budget_reservation_ids": ["budget-1"], "retention_policy_ids": ["retention-1"]}


def check_selected_source_and_buffer():
    value = session()
    first = value.add_frame("frame-1", "source-1", "source-r4",
                            value.capture_epoch, 1000, b"private frame")
    assert first["size_bytes"] == 13
    assert value.frame_bytes("frame-1", "source-1", value.capture_epoch) == b"private frame"
    expect(SessionRefusal, lambda: value.add_frame(
        "frame-2", "private-window", "source-r4", value.capture_epoch, 1001, b"leak"),
        "stale or foreign")
    for index in range(2, 6):
        value.add_frame(f"frame-{index}", "source-1", "source-r4",
                        value.capture_epoch, 1000 + index, bytes([index]))
    assert value.buffer_status == {"frames": 3, "bytes": 3}
    assert all("content" not in event for event in value.diagnostics())
    print("[T011 T016] foreground/private source substitution refuses and the three-frame buffer exposes no diagnostic content")


def check_unavailable_pause_stop():
    value = session(); epoch = value.capture_epoch
    value.add_frame("frame-1", "source-1", "source-r4", epoch, 1000, b"secret")
    value.pause(); assert value.state == "PAUSED" and value.buffer_status["bytes"] == 0
    value.resume(); value.source_unavailable("window closed")
    assert value.state == "SOURCE_UNAVAILABLE" and value.source is None
    expect(SessionRefusal, lambda: value.frame_bytes("frame-1", "source-1", epoch), "stale")
    assert value.stop() and value.state == "CLOSED" and value.stop() is False
    assert value.source_unavailable("late close callback") is False
    print("[T012 T014] pause, source loss, crash-style reconnect and idempotent Stop invalidate epochs and wipe transient frames")


def check_authenticated_bridge():
    value = session(); bridge = AuthenticatedLocalBridge(value, b"k" * 32)
    token = bridge.open_channel("native-1", "sid-user-1", 5000)
    payload = json.dumps({"schema": "ping.v1"}).encode()
    expect(SessionRefusal, lambda: bridge.receive(token, "sid-user-2", 1, 0, 1000, payload),
           "unauthenticated")
    accepted = bridge.receive(token, "sid-user-1", 1, 0, 1000, payload)
    assert accepted["payload"] == {"schema": "ping.v1"}
    assert bridge.receive(token, "sid-user-1", 1, 0, 1000, payload)["idempotent_replay"]
    expect(SessionRefusal, lambda: bridge.receive(token, "sid-user-1", 1, 0, 1000, b'{"x":2}'),
           "conflicting")
    value.reconnect()
    expect(SessionRefusal, lambda: bridge.receive(token, "sid-user-1", 2, 0, 1000, payload),
           "stale bridge")
    print("[T013] peer identity is checked before payload decoding; sequence conflicts and prior bridge epochs refuse")


def check_feature_gate_and_request_path():
    value = session(); data = copy.deepcopy(T.fixture_bundle()["records"])
    request, observation, instruction = data["request"], data["observation"], data["instruction"]
    request["cancellation_generation"] = value.cancellation_generation
    observation["capture_epoch"] = value.capture_epoch
    state = owner_state(value)
    calls = []
    disabled = TutorService(enabled=False, dispatch=lambda *args: calls.append(args))
    expect(TutorUnavailable, lambda: disabled.ask(request, state, [observation], value), "disabled")
    assert calls == []
    service = TutorService(enabled=True,
                           dispatch=lambda req, obs: calls.append((req, obs)) or instruction)
    assert service.ask(request, state, [observation], value)["allowed"]
    assert len(calls) == 1
    empty = copy.deepcopy(request); empty["observation_ids"] = []
    assert service.ask(empty, state, [observation], value)["reason_code"] == "STALE_SOURCE"
    wrong_first = copy.deepcopy(observation); wrong_first["observation_id"] = "obs-unused"
    assert service.ask(request, state, [wrong_first, observation], value)["allowed"]
    assert len(calls) == 2
    assert calls[-1][1] == [observation]
    wrong_source = copy.deepcopy(request); wrong_source["source_ids"] = ["source-2"]
    wrong_state = copy.deepcopy(state); wrong_state["source_ids"].append("source-2")
    wrong_state["source_revisions"]["source-2"] = "source-r5"
    assert service.ask(wrong_source, wrong_state, [observation], value)["reason_code"] == "STALE_SOURCE"
    assert len(calls) == 2
    value.stop()
    expect(TutorUnavailable, lambda: service.ask(request, state, [observation], value), "not ready")
    assert len(calls) == 2
    print("[request-path] disabled and stopped sessions dispatch nothing; a valid selected-source request reaches one injected gateway and validates before render")


def main():
    check_selected_source_and_buffer()
    check_unavailable_pause_stop()
    check_authenticated_bridge()
    check_feature_gate_and_request_path()
    print("PASS test_tutor_native_session")


if __name__ == "__main__":
    main()
