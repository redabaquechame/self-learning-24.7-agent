#!/usr/bin/env python3
"""Offline locale, caption and accessible audio-resilience contracts.

This module does not recognize, translate or synthesize speech.  It preserves
the facts those adapters must not erase: source language, terminology
uncertainty, immutable raw recognition, correction history, input equivalence
and device-change reauthorization.  A candidate locale always exposes a
visible fallback until independently qualified evidence is attached.
"""

import copy
import json
import re


LOCALE_SCHEMA = "tutor.locale-pack/1"
CAPTION_SCHEMA = "tutor.caption-ledger/1"
MATRIX_SCHEMA = "tutor.audio-locale-matrix/1"
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2}|-[0-9]{3})?$")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
UNCERTAINTY = ("KNOWN", "AMBIGUOUS", "UNTRANSLATED")
QUALIFICATION = ("CANDIDATE", "QUALIFIED")
MIN_SPEECH_RATE = 0.5
MAX_SPEECH_RATE = 2.0
MAX_TEXT = 8_000
MAX_CAPTIONS = 256
MAX_CORRECTIONS = 16

KEYBOARD_EQUIVALENTS = {
    "PUSH_TO_TALK": "Space (hold)",
    "BARGE_IN": "Escape",
    "STOP_SPEECH": "Ctrl+Shift+S",
    "FOCUS_TEXT_FALLBACK": "Ctrl+Shift+Q",
}


class LocaleRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise LocaleRefused("INVALID_LOCALE_RECORD", f"invalid {where} fields")
    return value


def _locale(value, name):
    if not isinstance(value, str) or not LOCALE.fullmatch(value):
        raise LocaleRefused("INVALID_LOCALE_RECORD", f"invalid {name}")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise LocaleRefused("INVALID_LOCALE_RECORD", f"invalid {name}")
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise LocaleRefused("INVALID_LOCALE_RECORD", f"invalid {name}")
    return value.strip()


def validate_locale_pack(value):
    """Validate a pack without converting its evidence tier into a claim."""
    value = copy.deepcopy(value)
    _exact(value, ("schema", "locale_id", "status", "source_language",
                   "target_language", "fallback_locale", "qualification",
                   "glossary"), "locale pack")
    if value["schema"] != LOCALE_SCHEMA or value["status"] not in QUALIFICATION:
        raise LocaleRefused("INVALID_LOCALE_RECORD", "schema or status")
    for field in ("locale_id", "source_language", "target_language",
                  "fallback_locale"):
        _locale(value[field], field)
    qualification = value["qualification"]
    _exact(qualification, ("provider_ref", "content_review_ref",
                           "human_comprehension_ref", "device_matrix_ref"),
           "qualification")
    refs = []
    for field, ref in qualification.items():
        if ref is not None:
            refs.append(_ident(ref, field))
    if value["status"] == "QUALIFIED" and len(refs) != 4:
        raise LocaleRefused("UNQUALIFIED_LOCALE",
                            "qualified locale requires all four external evidence references")
    if value["status"] == "CANDIDATE" and refs:
        raise LocaleRefused("INVALID_LOCALE_RECORD",
                            "candidate locale cannot carry qualification references")
    if not isinstance(value["glossary"], list) or len(value["glossary"]) > 512:
        raise LocaleRefused("INVALID_LOCALE_RECORD", "invalid glossary")
    ids = set()
    for entry in value["glossary"]:
        _exact(entry, ("term_id", "source_term", "source_language",
                       "preferred_term", "target_language", "uncertainty",
                       "source_refs"), "glossary entry")
        term_id = _ident(entry["term_id"], "term_id")
        if term_id in ids:
            raise LocaleRefused("INVALID_LOCALE_RECORD", "duplicate glossary term")
        ids.add(term_id)
        _text(entry["source_term"], "source_term")
        _locale(entry["source_language"], "source_language")
        _locale(entry["target_language"], "target_language")
        if entry["uncertainty"] not in UNCERTAINTY:
            raise LocaleRefused("INVALID_LOCALE_RECORD", "invalid uncertainty")
        if entry["preferred_term"] is not None:
            _text(entry["preferred_term"], "preferred_term")
        if entry["uncertainty"] == "UNTRANSLATED" and entry["preferred_term"] is not None:
            raise LocaleRefused("INVALID_LOCALE_RECORD",
                                "untranslated term cannot invent a preferred translation")
        refs = entry["source_refs"]
        if (not isinstance(refs, list) or not refs or len(refs) > 16
                or len(set(refs)) != len(refs)):
            raise LocaleRefused("INVALID_LOCALE_RECORD", "invalid glossary source refs")
        for ref in refs:
            _ident(ref, "source_ref")
    return value


def effective_locale(pack, verified_evidence_refs=()):
    pack = validate_locale_pack(pack)
    required = set(pack["qualification"].values()) - {None}
    verified = set(verified_evidence_refs)
    if pack["status"] == "QUALIFIED" and required <= verified:
        return {"locale": pack["locale_id"], "fallback": False,
                "disclosure": None}
    return {
        "locale": pack["fallback_locale"],
        "fallback": True,
        "disclosure": (f"{pack['locale_id']} is not yet qualified. "
                       f"Using visible text fallback in {pack['fallback_locale']}.")
    }


def validate_audio_locale_matrix(value):
    """Keep unrun measurements unknown and passed rows fully evidenced."""
    value = copy.deepcopy(value)
    _exact(value, ("schema", "status", "generated_for", "rows",
                   "qualification_rule"), "audio locale matrix")
    if value["schema"] != MATRIX_SCHEMA or value["status"] not in ("NOT_RUN", "PARTIAL", "PASSED"):
        raise LocaleRefused("INVALID_LOCALE_MATRIX", "schema or status")
    _ident(value["generated_for"], "generated_for")
    _text(value["qualification_rule"], "qualification_rule")
    if not isinstance(value["rows"], list) or not value["rows"]:
        raise LocaleRefused("INVALID_LOCALE_MATRIX", "rows required")
    for row in value["rows"]:
        _exact(row, ("locale_id", "device_class", "provider_model",
                     "content_pack_sha256", "comprehension_rate",
                     "word_error_rate", "caption_error_rate",
                     "barge_in_passed", "authority_isolation_passed",
                     "device_change_pause_passed", "evidence_tiers", "status"),
               "audio locale row")
        _locale(row["locale_id"], "locale_id")
        _ident(row["device_class"], "device_class")
        _ident(row["provider_model"], "provider_model")
        if row["status"] not in ("NOT_RUN", "FAILED", "PASSED"):
            raise LocaleRefused("INVALID_LOCALE_MATRIX", "invalid row status")
        metrics = [row[name] for name in (
            "comprehension_rate", "word_error_rate", "caption_error_rate")]
        booleans = [row[name] for name in (
            "barge_in_passed", "authority_isolation_passed",
            "device_change_pause_passed")]
        tiers = row["evidence_tiers"]
        if not isinstance(tiers, list) or len(set(tiers)) != len(tiers) \
                or any(tier not in ("NATIVE", "PROVIDER", "CONTENT_REVIEW") for tier in tiers):
            raise LocaleRefused("INVALID_LOCALE_MATRIX", "invalid evidence tiers")
        if row["status"] == "NOT_RUN":
            if any(item is not None for item in metrics + booleans) or tiers \
                    or row["content_pack_sha256"] is not None:
                raise LocaleRefused("INVALID_LOCALE_MATRIX",
                                    "unrun measurements and evidence must remain unknown")
            continue
        for metric in metrics:
            if (isinstance(metric, bool) or not isinstance(metric, (int, float))
                    or not 0 <= metric <= 1):
                raise LocaleRefused("INVALID_LOCALE_MATRIX", "invalid measured rate")
        if any(type(item) is not bool for item in booleans):
            raise LocaleRefused("INVALID_LOCALE_MATRIX", "invalid measured result")
        digest = row["content_pack_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise LocaleRefused("INVALID_LOCALE_MATRIX", "invalid content digest")
        if row["status"] == "PASSED" and (set(tiers) != {"NATIVE", "PROVIDER", "CONTENT_REVIEW"}
                                            or not all(booleans)):
            raise LocaleRefused("INVALID_LOCALE_MATRIX",
                                "passed row lacks required tiers or controls")
    if value["status"] == "PASSED" and any(row["status"] != "PASSED" for row in value["rows"]):
        raise LocaleRefused("INVALID_LOCALE_MATRIX", "matrix passed with incomplete row")
    return value


def speech_rate(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LocaleRefused("INVALID_SPEECH_RATE", "speech rate must be numeric")
    value = float(value)
    if not MIN_SPEECH_RATE <= value <= MAX_SPEECH_RATE:
        raise LocaleRefused("INVALID_SPEECH_RATE", "speech rate outside 0.5 through 2.0")
    return value


def keyboard_equivalents():
    return copy.deepcopy(KEYBOARD_EQUIVALENTS)


def new_caption_ledger(session_id):
    return {"schema": CAPTION_SCHEMA, "session_id": _ident(session_id, "session_id"),
            "next_sequence": 1, "captions": []}


def _validate_segment(value):
    _exact(value, ("start", "end", "language"), "language segment")
    start, end = value["start"], value["end"]
    if (isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, int) or not isinstance(end, int)
            or start < 0 or end <= start):
        raise LocaleRefused("INVALID_CAPTION", "invalid language segment range")
    _locale(value["language"], "segment language")
    return value


def _validate_ledger(value):
    _exact(value, ("schema", "session_id", "next_sequence", "captions"),
           "caption ledger")
    if value["schema"] != CAPTION_SCHEMA:
        raise LocaleRefused("INVALID_CAPTION", "invalid caption schema")
    _ident(value["session_id"], "session_id")
    if (isinstance(value["next_sequence"], bool)
            or not isinstance(value["next_sequence"], int)
            or value["next_sequence"] < 1):
        raise LocaleRefused("INVALID_CAPTION", "invalid next sequence")
    captions = value["captions"]
    if not isinstance(captions, list) or len(captions) > MAX_CAPTIONS:
        raise LocaleRefused("INVALID_CAPTION", "invalid caption collection")
    ids, expected = set(), 1
    for row in captions:
        _exact(row, ("caption_id", "sequence", "origin", "raw_text",
                     "raw_language", "language_segments", "corrections"),
               "caption")
        caption_id = _ident(row["caption_id"], "caption_id")
        if caption_id in ids or row["sequence"] != expected:
            raise LocaleRefused("INVALID_CAPTION", "caption identity or sequence")
        ids.add(caption_id); expected += 1
        if row["origin"] not in ("MICROPHONE", "MEDIA", "ASSISTANT"):
            raise LocaleRefused("INVALID_CAPTION", "invalid caption origin")
        raw = _text(row["raw_text"], "raw_text")
        _locale(row["raw_language"], "raw_language")
        segments = row["language_segments"]
        if not isinstance(segments, list) or not segments:
            raise LocaleRefused("INVALID_CAPTION", "missing language segments")
        cursor = 0
        for segment in segments:
            _validate_segment(segment)
            if segment["start"] != cursor or segment["end"] > len(raw):
                raise LocaleRefused("INVALID_CAPTION", "segments must cover raw text in order")
            cursor = segment["end"]
        if cursor != len(raw):
            raise LocaleRefused("INVALID_CAPTION", "segments do not cover raw text")
        corrections = row["corrections"]
        if not isinstance(corrections, list) or len(corrections) > MAX_CORRECTIONS:
            raise LocaleRefused("INVALID_CAPTION", "invalid corrections")
        correction_ids = set()
        for index, correction in enumerate(corrections, 1):
            _exact(correction, ("correction_id", "revision", "corrected_text",
                                "reason", "actor"), "caption correction")
            correction_id = _ident(correction["correction_id"], "correction_id")
            if correction_id in correction_ids or correction["revision"] != index:
                raise LocaleRefused("INVALID_CAPTION", "correction identity or revision")
            correction_ids.add(correction_id)
            _text(correction["corrected_text"], "corrected_text")
            _text(correction["reason"], "reason")
            if correction["actor"] not in ("USER", "SYSTEM"):
                raise LocaleRefused("INVALID_CAPTION", "invalid correction actor")
    if value["next_sequence"] != expected:
        raise LocaleRefused("INVALID_CAPTION", "next sequence mismatch")
    return value


def append_caption(ledger, caption_id, origin, raw_text, raw_language, segments):
    result = copy.deepcopy(_validate_ledger(copy.deepcopy(ledger)))
    if len(result["captions"]) >= MAX_CAPTIONS:
        raise LocaleRefused("CAPTION_LIMIT", "caption history is full")
    if any(row["caption_id"] == caption_id for row in result["captions"]):
        raise LocaleRefused("INVALID_CAPTION", "duplicate caption identity")
    result["captions"].append({
        "caption_id": _ident(caption_id, "caption_id"),
        "sequence": result["next_sequence"],
        "origin": origin,
        "raw_text": _text(raw_text, "raw_text"),
        "raw_language": _locale(raw_language, "raw_language"),
        "language_segments": copy.deepcopy(segments),
        "corrections": [],
    })
    result["next_sequence"] += 1
    return _validate_ledger(result)


def append_correction(ledger, caption_id, correction_id, corrected_text, reason,
                      actor="USER"):
    result = copy.deepcopy(_validate_ledger(copy.deepcopy(ledger)))
    row = next((item for item in result["captions"]
                if item["caption_id"] == caption_id), None)
    if row is None:
        raise LocaleRefused("CAPTION_NOT_FOUND", "caption does not exist")
    if len(row["corrections"]) >= MAX_CORRECTIONS:
        raise LocaleRefused("CAPTION_LIMIT", "correction history is full")
    if any(item["correction_id"] == correction_id
           for item in row["corrections"]):
        raise LocaleRefused("INVALID_CAPTION", "duplicate correction identity")
    row["corrections"].append({
        "correction_id": _ident(correction_id, "correction_id"),
        "revision": len(row["corrections"]) + 1,
        "corrected_text": _text(corrected_text, "corrected_text"),
        "reason": _text(reason, "reason"),
        "actor": actor,
    })
    return _validate_ledger(result)


def display_caption(ledger, caption_id):
    ledger = _validate_ledger(copy.deepcopy(ledger))
    row = next((item for item in ledger["captions"]
                if item["caption_id"] == caption_id), None)
    if row is None:
        raise LocaleRefused("CAPTION_NOT_FOUND", "caption does not exist")
    return row["corrections"][-1]["corrected_text"] if row["corrections"] else row["raw_text"]


class DeviceCaptureGuard:
    """Requires explicit authorization after every device identity change."""
    def __init__(self, device_id):
        self.device_id = _ident(device_id, "device_id")
        self.generation = 0
        self.capture_authorized = False
        self.capture_paused = True

    def authorize(self, device_id, generation):
        if device_id != self.device_id or generation != self.generation:
            raise LocaleRefused("STALE_DEVICE_AUTHORIZATION", "device identity changed")
        self.capture_authorized = True
        self.capture_paused = False

    def change_device(self, device_id):
        device_id = _ident(device_id, "device_id")
        if device_id != self.device_id:
            self.device_id = device_id
            self.generation += 1
        self.capture_authorized = False
        self.capture_paused = True

    def may_capture(self):
        return self.capture_authorized and not self.capture_paused


def canonical_locale_json(value):
    return json.dumps(validate_locale_pack(value), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def canonical_caption_json(value):
    return json.dumps(_validate_ledger(copy.deepcopy(value)), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
