#!/usr/bin/env python3
"""Tenant-bound, rights-aware source registry for Screen Tutor.

This module stores reviewable excerpts under the fleet control root. Retrieval
is deliberately narrower than ingestion: normal tutor retrieval can see only
teaching excerpts in the caller's exact tenant/project scope. Hidden assessment
content may be verified by digest, but no public read route returns its text.
"""

import hashlib
import json
import os
import re
import tempfile


SCHEMA = "tutor.source/1"
ROOT = os.path.join("org", "tutor-source-registry")
MAX_SOURCE_BYTES = 256 * 1024
MAX_EXCERPTS = 64
MAX_EXCERPT_CHARS = 12_000
MAX_RESULTS = 8
MAX_RETRIEVAL_CHARS = 12_000
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
WORDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}")
SOURCE_TYPES = frozenset(("official_docs", "licensed_asset", "internal_sop", "fixture"))
PURPOSES = frozenset(("teaching", "final_assessment"))


class SourceRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, required, where):
    if not isinstance(value, dict) or set(value) != set(required):
        got = sorted(value) if isinstance(value, dict) else type(value).__name__
        raise SourceRefused("INVALID_SOURCE", f"{where} fields are {got}")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise SourceRefused("INVALID_SOURCE", f"invalid {name}")
    return value


def parse_version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise SourceRefused("INVALID_VERSION", f"expected major.minor.patch, got {value!r}")
    return tuple(int(part) for part in value.split("."))


def _path(home, tenant_id, project_id, source_id, revision):
    parts = [_ident(v, n) for v, n in (
        (tenant_id, "tenant_id"), (project_id, "project_id"),
        (source_id, "source_id"), (revision, "revision"))]
    base = os.path.realpath(os.path.join(os.path.abspath(home), ROOT))
    path = os.path.join(base, *parts) + ".json"
    if os.path.commonpath((base, os.path.realpath(path))) != base:
        raise SourceRefused("INVALID_SOURCE", "source path escapes registry")
    return path


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SourceRefused("INVALID_SOURCE", str(exc)) from exc


def _validate(record):
    _exact(record, ("schema", "source_id", "revision", "tenant_id",
                    "project_id", "title", "source_type", "locator", "app_id",
                    "app_versions", "rights", "purpose", "excerpts"), "source")
    if record["schema"] != SCHEMA:
        raise SourceRefused("INVALID_SOURCE", "unsupported source schema")
    for key in ("source_id", "revision", "tenant_id", "project_id", "app_id"):
        _ident(record[key], key)
    if record["source_type"] not in SOURCE_TYPES:
        raise SourceRefused("INVALID_SOURCE", "unsupported source_type")
    if record["purpose"] not in PURPOSES:
        raise SourceRefused("INVALID_SOURCE", "unsupported purpose")
    for key, cap in (("title", 300), ("locator", 2048)):
        if not isinstance(record[key], str) or not record[key] or len(record[key]) > cap:
            raise SourceRefused("INVALID_SOURCE", f"invalid {key}")
    versions = _exact(record["app_versions"], ("min", "max"), "app_versions")
    low, high = parse_version(versions["min"]), parse_version(versions["max"])
    if low > high:
        raise SourceRefused("INVALID_VERSION", "app version range is reversed")
    rights = _exact(record["rights"], ("status", "license_id", "permitted_ranges"),
                    "rights")
    if rights["status"] != "permitted":
        raise SourceRefused("RIGHTS_DENIED", "only permitted material may be registered")
    _ident(rights["license_id"], "license_id")
    ranges = rights["permitted_ranges"]
    if not isinstance(ranges, list) or not ranges or len(ranges) > 64:
        raise SourceRefused("INVALID_SOURCE", "permitted_ranges must be a bounded list")
    checked_ranges = []
    for item in ranges:
        _exact(item, ("start", "end"), "permitted range")
        if (isinstance(item["start"], bool) or not isinstance(item["start"], int)
                or not isinstance(item["end"], int) or item["start"] < 0
                or item["end"] < item["start"]):
            raise SourceRefused("INVALID_SOURCE", "invalid permitted range")
        checked_ranges.append((item["start"], item["end"]))
    excerpts = record["excerpts"]
    if not isinstance(excerpts, list) or not excerpts or len(excerpts) > MAX_EXCERPTS:
        raise SourceRefused("INVALID_SOURCE", "excerpts must be a bounded non-empty list")
    seen = set()
    for excerpt in excerpts:
        _exact(excerpt, ("excerpt_id", "start", "end", "text", "source_revision",
                         "tenant_id", "project_id", "license_id", "purpose"), "excerpt")
        _ident(excerpt["excerpt_id"], "excerpt_id")
        if excerpt["excerpt_id"] in seen:
            raise SourceRefused("INVALID_SOURCE", "duplicate excerpt_id")
        seen.add(excerpt["excerpt_id"])
        if (isinstance(excerpt["start"], bool) or not isinstance(excerpt["start"], int)
                or not isinstance(excerpt["end"], int)
                or excerpt["start"] < 0 or excerpt["end"] < excerpt["start"]):
            raise SourceRefused("INVALID_SOURCE", "invalid excerpt range")
        if not any(a <= excerpt["start"] and excerpt["end"] <= b
                   for a, b in checked_ranges):
            raise SourceRefused("RIGHTS_DENIED", "excerpt exceeds its permitted range")
        bindings = (("source_revision", "revision"), ("tenant_id", "tenant_id"),
                    ("project_id", "project_id"), ("license_id", None),
                    ("purpose", "purpose"))
        for excerpt_key, record_key in bindings:
            expected = rights["license_id"] if excerpt_key == "license_id" else record[record_key]
            if excerpt[excerpt_key] != expected:
                raise SourceRefused("INVALID_SOURCE", f"excerpt {excerpt_key} binding differs")
        if (not isinstance(excerpt["text"], str) or not excerpt["text"]
                or len(excerpt["text"]) > MAX_EXCERPT_CHARS):
            raise SourceRefused("INVALID_SOURCE", "invalid excerpt text")
    encoded = _canonical(record).encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise SourceRefused("INVALID_SOURCE", "source record exceeds byte limit")
    return record


def _atomic_write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".source-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def register_source(home, record):
    """Register one immutable source revision; identical retries are idempotent."""
    import locks
    _validate(record)
    text = _canonical(record) + "\n"
    path = _path(home, record["tenant_id"], record["project_id"],
                 record["source_id"], record["revision"])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locks.holding(path, timeout=10.0, stale=8.0):
        if os.path.exists(path):
            try:
                current = open(path, encoding="utf-8").read()
            except OSError as exc:
                raise SourceRefused("SOURCE_UNAVAILABLE", str(exc)) from exc
            if current == text:
                return {"created": False, "digest": hashlib.sha256(text.encode()).hexdigest()}
            raise SourceRefused("SOURCE_CONFLICT", "source revision is immutable")
        _atomic_write(path, text)
        return {"created": True, "digest": hashlib.sha256(text.encode()).hexdigest()}


def _load_path(path):
    try:
        raw = open(path, "rb").read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise SourceRefused("SOURCE_UNAVAILABLE", "stored source exceeds byte limit")
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                            parse_constant=_nonfinite)
        return _validate(record)
    except SourceRefused:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceRefused("SOURCE_UNAVAILABLE", str(exc)) from exc


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise SourceRefused("SOURCE_UNAVAILABLE", f"duplicate stored key {key}")
        out[key] = value
    return out


def _nonfinite(value):
    raise SourceRefused("SOURCE_UNAVAILABLE", f"non-finite stored number {value}")


def _scoped_records(home, tenant_id, project_id):
    base = os.path.dirname(_path(home, tenant_id, project_id, "probe", "probe"))
    base = os.path.dirname(base)
    if not os.path.isdir(base):
        return []
    paths = []
    for source_id in sorted(os.listdir(base)):
        directory = os.path.join(base, source_id)
        if os.path.isdir(directory) and not os.path.islink(directory):
            paths.extend(os.path.join(directory, name) for name in sorted(os.listdir(directory))
                         if name.endswith(".json"))
    records = []
    for path in paths:
        record = _load_path(path)
        if record["tenant_id"] != tenant_id or record["project_id"] != project_id:
            raise SourceRefused("SOURCE_UNAVAILABLE", "stored ACL differs from registry path")
        records.append(record)
    return records


def retrieve(home, *, tenant_id, project_id, query, app_id=None,
             app_version=None, limit=5, max_chars=6000):
    """Return bounded, labelled teaching excerpts from one exact ACL scope."""
    _ident(tenant_id, "tenant_id")
    _ident(project_id, "project_id")
    if not isinstance(query, str) or not query.strip() or len(query) > 512:
        raise SourceRefused("INVALID_QUERY", "query must contain 1..512 characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
        raise SourceRefused("INVALID_QUERY", "invalid result limit")
    if (isinstance(max_chars, bool) or not isinstance(max_chars, int)
            or not 256 <= max_chars <= MAX_RETRIEVAL_CHARS):
        raise SourceRefused("INVALID_QUERY", "invalid character budget")
    if app_id is not None:
        _ident(app_id, "app_id")
    wanted_version = parse_version(app_version) if app_version is not None else None
    terms = {x.lower() for x in WORDS.findall(query)}
    candidates, hidden_matches, scope_limits = [], 0, []
    for record in _scoped_records(home, tenant_id, project_id):
        if app_id is not None and record["app_id"] != app_id:
            continue
        if wanted_version is not None:
            low = parse_version(record["app_versions"]["min"])
            high = parse_version(record["app_versions"]["max"])
            if not low <= wanted_version <= high:
                scope_limits.append({"source_id": record["source_id"],
                                     "reason": "APP_VERSION_OUTSIDE_SOURCE_RANGE"})
                continue
        for excerpt in record["excerpts"]:
            hay = (record["title"] + " " + excerpt["text"]).lower()
            score = sum(1 for term in terms if term in hay)
            if score <= 0:
                continue
            if record["purpose"] == "final_assessment":
                hidden_matches += 1
                continue
            candidates.append((score, record, excerpt))
    candidates.sort(key=lambda row: (-row[0], row[1]["source_id"], row[2]["excerpt_id"]))
    results, used = [], 0
    for score, record, excerpt in candidates:
        if len(results) >= limit:
            break
        if used + len(excerpt["text"]) > max_chars:
            continue
        used += len(excerpt["text"])
        results.append({
            "content": excerpt["text"], "score": score,
            "source": {"source_id": record["source_id"],
                       "revision": record["revision"],
                       "excerpt_id": excerpt["excerpt_id"],
                       "title": record["title"], "locator": record["locator"],
                       "license_id": excerpt["license_id"],
                       "tenant_id": tenant_id, "project_id": project_id,
                       "app_id": record["app_id"],
                       "app_versions": record["app_versions"]}})
    status = "OK" if results else ("ACCESS_DENIED" if hidden_matches else "MISSING_SOURCE")
    return {"schema": "tutor.retrieval/1", "status": status,
            "results": results, "result_count": len(results),
            "characters": used, "hidden_matches_denied": hidden_matches,
            "scope_limits": scope_limits}


def read_excerpt(home, *, tenant_id, project_id, source_id, revision, excerpt_id):
    record = _load_path(_path(home, tenant_id, project_id, source_id, revision))
    if record["tenant_id"] != tenant_id or record["project_id"] != project_id:
        raise SourceRefused("ACL_DENIED", "source is outside the caller scope")
    if record["purpose"] == "final_assessment":
        raise SourceRefused("ASSESSMENT_ACCESS_DENIED", "hidden assessment text is never tutor-readable")
    for excerpt in record["excerpts"]:
        if excerpt["excerpt_id"] == excerpt_id:
            return excerpt["text"]
    raise SourceRefused("MISSING_SOURCE", "excerpt does not exist")


def source_reference_status(home, reference):
    _exact(reference, ("source_id", "revision", "excerpt_id", "tenant_id",
                       "project_id"), "source reference")
    try:
        record = _load_path(_path(home, reference["tenant_id"], reference["project_id"],
                                  reference["source_id"], reference["revision"]))
    except SourceRefused as exc:
        return {"ok": False, "code": exc.code, "detail": exc.detail}
    if record["purpose"] != "teaching":
        return {"ok": False, "code": "ASSESSMENT_ACCESS_DENIED",
                "detail": "teaching references cannot name final assessment material"}
    excerpt = next((e for e in record["excerpts"]
                    if e["excerpt_id"] == reference["excerpt_id"]), None)
    if excerpt is None:
        return {"ok": False, "code": "MISSING_SOURCE", "detail": "excerpt missing"}
    return {"ok": True, "record": record,
            "excerpt_sha256": hashlib.sha256(excerpt["text"].encode()).hexdigest()}


def verify_assessment_reference(home, reference):
    """Verify hidden content by digest without returning it."""
    _exact(reference, ("source_id", "revision", "excerpt_id", "tenant_id",
                       "project_id", "content_sha256"), "assessment reference")
    try:
        record = _load_path(_path(home, reference["tenant_id"], reference["project_id"],
                                  reference["source_id"], reference["revision"]))
    except SourceRefused as exc:
        return {"ok": False, "code": exc.code, "detail": exc.detail}
    if record["purpose"] != "final_assessment":
        return {"ok": False, "code": "INVALID_ASSESSMENT", "detail": "reference is not hidden"}
    excerpt = next((e for e in record["excerpts"]
                    if e["excerpt_id"] == reference["excerpt_id"]), None)
    if excerpt is None:
        return {"ok": False, "code": "MISSING_SOURCE", "detail": "hidden item missing"}
    actual = hashlib.sha256(excerpt["text"].encode()).hexdigest()
    return {"ok": actual == reference["content_sha256"],
            "code": "OK" if actual == reference["content_sha256"] else "ASSESSMENT_DIGEST_MISMATCH",
            "detail": "" if actual == reference["content_sha256"] else "hidden item digest differs"}
