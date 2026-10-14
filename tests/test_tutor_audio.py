#!/usr/bin/env python3
"""SC-3 offline audio-source, PTT, interruption and retry witnesses."""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tutor_audio


def refused(fn, code):
    try:
        fn()
    except tutor_audio.AudioRefused as error:
        assert error.code == code, (error.code, error.detail)
        return
    raise AssertionError(f"expected {code}")


def event(event_id, origin, transcript, source_epoch=0):
    return {"schema": "tutor.audio-event/1", "event_id": event_id,
            "origin": origin, "transcript": transcript,
            "source_epoch": source_epoch}


def request(session, request_id):
    return next(item for item in session["requests"]
                if item["request_id"] == request_id)


def submitted(session, request_id="request-1", transcript="explain this chart"):
    held = tutor_audio.press_to_talk(session)
    result = tutor_audio.release_to_submit(
        held, event("mic-event-1", "MICROPHONE", transcript,
                    held["source_epoch"]), request_id)
    assert result["execution_authorized"] is False
    return result["session"], result["request"]


def main():
    session = tutor_audio.start_session(
        "audio-session-1", "user-1", "project-1",
        ["MICROPHONE", "MEDIA", "ASSISTANT_PLAYBACK"])
    assert session["status"] == "IDLE"
    assert session["push_to_talk"] == "RELEASED"
    assert session["playback_active"] is False
    assert session["captions_enabled"] and session["text_fallback"]
    assert session["requests"] == []

    # T046: approval words from media and assistant playback are source-tagged
    # and never become execution consent or outbound requests.
    media = tutor_audio.observe_event(
        session, event("media-1", "MEDIA", "yes approve and continue"))
    assistant = tutor_audio.observe_event(
        session, event("assistant-1", "ASSISTANT", "yes approve and continue"))
    assert media["disposition"] == "CONTEXT_ONLY"
    assert assistant["disposition"] == "IGNORED_SELF_AUDIO"
    assert not media["execution_authorized"] and not assistant["execution_authorized"]
    assert session["requests"] == []

    # Even a current microphone transcript is never an execution approval.
    mic_observation = tutor_audio.observe_event(
        session, event("mic-observation", "MICROPHONE", "yes approve"))
    assert mic_observation["execution_authorized"] is False
    refused(lambda: tutor_audio.release_to_submit(
        session, event("idle-mic", "MICROPHONE", "do it"), "idle-request"),
        "PUSH_TO_TALK_REQUIRED")

    # A held microphone capture may create one tutoring request. Dispatch still
    # requires a cost/accounting reservation, and retry preserves the effect key.
    session, original = submitted(session)
    refused(lambda: tutor_audio.begin_dispatch(
        session, original["request_id"], "missing-reservation"),
        "AUDIO_RESERVATION_REQUIRED")
    session = tutor_audio.reserve_request(
        session, original["request_id"], "reservation-1", 40)
    session = tutor_audio.begin_dispatch(
        session, original["request_id"], "reservation-1")
    assert request(session, "request-1")["attempts"] == 1
    effect_key = request(session, "request-1")["effect_key"]
    session = tutor_audio.record_network_failure(session, "request-1")
    assert request(session, "request-1")["state"] == "QUEUED"
    session = tutor_audio.begin_dispatch(session, "request-1", "reservation-1")
    assert request(session, "request-1")["attempts"] == tutor_audio.MAX_ATTEMPTS
    assert request(session, "request-1")["effect_key"] == effect_key
    session = tutor_audio.record_network_failure(session, "request-1")
    assert request(session, "request-1")["state"] == "FAILED"
    refused(lambda: tutor_audio.begin_dispatch(session, "request-1", "reservation-1"),
            "AUDIO_RESERVATION_REQUIRED")
    assert session["text_fallback"] is True
    assert len({item["effect_key"] for item in session["requests"]}) == len(session["requests"])

    # A successful response is captioned and may start playback. Barge-in is a
    # local cancellation that increments epochs and suppresses late responses.
    session, second = submitted(session, "request-2", "show the next step")
    session = tutor_audio.reserve_request(session, "request-2", "reservation-2", 20)
    session = tutor_audio.begin_dispatch(session, "request-2", "reservation-2")
    accepted = tutor_audio.accept_response(
        session, "request-2", "response-2", session["generation_epoch"],
        "Here is the next step.", "Here is the next step.")
    session = accepted["session"]
    assert accepted["origin"] == "ASSISTANT"
    assert accepted["caption_text"] and session["playback_active"]
    session, third = submitted(session, "request-3", "wait, go back")
    session = tutor_audio.reserve_request(session, "request-3", "reservation-3", 20)
    session = tutor_audio.begin_dispatch(session, "request-3", "reservation-3")
    stale_epoch = session["generation_epoch"]
    interrupted = tutor_audio.barge_in(session)
    assert not interrupted["playback_active"]
    assert request(interrupted, "request-3")["state"] == "CANCELLED"
    refused(lambda: tutor_audio.accept_response(
        interrupted, "request-3", "late-response", stale_epoch,
        "obsolete", "obsolete"), "STALE_AUDIO_RESPONSE")

    # Scope changes and device loss invalidate work while preserving a usable
    # text route. Stop is terminal and idempotent.
    changed = tutor_audio.set_scopes(interrupted, ["MICROPHONE"])
    assert changed["source_epoch"] == interrupted["source_epoch"] + 1
    refused(lambda: tutor_audio.observe_event(
        changed, event("old-media", "MEDIA", "old", 0)), "STALE_AUDIO")
    disconnected = tutor_audio.device_changed(changed, "DISCONNECTED")
    assert disconnected["device_state"] == "DISCONNECTED"
    assert disconnected["status"] == "IDLE" and disconnected["text_fallback"]
    refused(lambda: tutor_audio.press_to_talk(disconnected), "MICROPHONE_UNAVAILABLE")
    stopped = tutor_audio.stop_session(disconnected)
    assert stopped["status"] == "STOPPED" and not stopped["playback_active"]
    assert tutor_audio.stop_session(stopped) == stopped
    refused(lambda: tutor_audio.press_to_talk(stopped), "AUDIO_STOPPED")

    # Returned records are revalidated so a caller cannot enlarge the queue,
    # forge state fields or smuggle active audio into Stop.
    forged = copy.deepcopy(stopped)
    forged["unexpected"] = True
    refused(lambda: tutor_audio.canonical_session_json(forged), "INVALID_AUDIO_STATE")
    encoded = tutor_audio.canonical_session_json(stopped)
    assert json.loads(encoded) == stopped

    # The serialized PTT path normally permits only one active generation.
    # Revalidation still refuses a forged host record above the hard queue cap.
    bounded = tutor_audio.start_session(
        "bounded-session", "user-1", "project-1", ["MICROPHONE"])
    bounded, template = submitted(bounded, "bounded-0", "question zero")
    for index in range(1, tutor_audio.MAX_ACTIVE_REQUESTS + 1):
        forged_request = copy.deepcopy(template)
        forged_request["request_id"] = f"bounded-{index}"
        forged_request["effect_key"] = f"audio-forged-{index}"
        bounded["requests"].append(forged_request)
    refused(lambda: tutor_audio.canonical_session_json(bounded),
            "INVALID_AUDIO_STATE")

    print("[T046] media/assistant approval words remained context; voice granted no execution consent")
    print("[T048-offline] barge-in stopped playback and invalidated the late response epoch")
    print("[T049-offline] device loss exposed text fallback and disabled microphone capture")
    print("[T050-offline] idle push-to-talk produced zero outbound requests")
    print("[T051] queue, reservation, retries and effect identity remained bounded and idempotent")


if __name__ == "__main__":
    main()
