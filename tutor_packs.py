#!/usr/bin/env python3
"""Reviewed teaching-pack lifecycle and deterministic practice checks."""

import hashlib
import json
import os
import re
import shutil
import tempfile
import time

import tutor_sources


PACK_SCHEMA = "tutor.teaching-pack/1"
FILES = ("pack.json", "sources.json", "examples.json", "practice.json",
         "assessment_manifest.json")
PACK_ROOT = "teaching_packs"
REVIEWS = os.path.join("org", "tutor-pack-reviews.jsonl")
QUALIFICATIONS = os.path.join("org", "tutor-pack-qualifications.jsonl")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHECKLIST = frozenset(("source_rights", "version_scope", "worked_examples",
                       "misconceptions", "valid_methods", "sample_checks",
                       "assessment_separation"))


class PackRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise PackRefused("INVALID_PACK", f"invalid {name}")
    return value


def _reviewer_principal(value):
    if (not isinstance(value, str) or not value or len(value) > 320
            or value != value.strip() or any(ch.isspace() for ch in value)):
        raise PackRefused("INVALID_REVIEW", "invalid reviewer principal")
    return value.lower()


def _require_subject_reviewer(home, reviewer_id, pack_id):
    """Bind a human-review claim to an active organization reviewer role."""
    import org
    principal = _reviewer_principal(reviewer_id)
    if org.load(home) is None:
        raise PackRefused("REVIEW_AUTHORITY_DENIED",
                          "subject review requires an organization identity")
    try:
        org.check(home, principal, "comment", pack_id)
    except (org.Denied, KeyError, ValueError) as exc:
        raise PackRefused("REVIEW_AUTHORITY_DENIED", str(exc)) from exc
    return principal


def _pack_dir(home, pack_id):
    _ident(pack_id, "pack_id")
    base = os.path.realpath(os.path.join(os.path.abspath(home), PACK_ROOT))
    path = os.path.join(base, pack_id)
    if os.path.commonpath((base, os.path.realpath(path))) != base:
        raise PackRefused("INVALID_PACK", "pack path escapes root")
    return path


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise PackRefused("INVALID_PACK", f"duplicate key {key}")
        out[key] = value
    return out


def _read(path):
    try:
        raw = open(path, "rb").read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise PackRefused("INVALID_PACK", "pack file exceeds one MiB")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=lambda x: (_ for _ in ()).throw(
                              PackRefused("INVALID_PACK", f"non-finite {x}")))
    except PackRefused:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PackRefused("INVALID_PACK", str(exc)) from exc


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise PackRefused("INVALID_PACK", f"invalid {where} fields")
    return value


def _digest(directory):
    h = hashlib.sha256()
    for name in FILES:
        path = os.path.join(directory, name)
        if os.path.islink(path) or not os.path.isfile(path):
            raise PackRefused("INVALID_PACK", f"missing regular {name}")
        h.update(name.encode())
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    extras = sorted(set(os.listdir(directory)) - set(FILES))
    if extras:
        raise PackRefused("INVALID_PACK", f"unexpected pack files: {extras}")
    return h.hexdigest()


def install_candidate(home, source_directory):
    """Copy one immutable candidate into the fleet pack root."""
    source = os.path.realpath(source_directory)
    pack = _read(os.path.join(source, "pack.json"))
    pack_id = _ident(pack.get("pack_id"), "pack_id")
    destination = _pack_dir(home, pack_id)
    if os.path.exists(destination):
        if _digest(destination) == _digest(source):
            return {"created": False, "pack_id": pack_id, "digest": _digest(source)}
        raise PackRefused("PACK_CONFLICT", "pack ID is immutable; publish a new version")
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    temp = tempfile.mkdtemp(prefix=".pack-", dir=os.path.dirname(destination))
    try:
        for name in FILES:
            path = os.path.join(source, name)
            if os.path.islink(path) or not os.path.isfile(path):
                raise PackRefused("INVALID_PACK", f"missing regular {name}")
            shutil.copyfile(path, os.path.join(temp, name))
        _digest(temp)
        os.replace(temp, destination)
        temp = None
    finally:
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
    return {"created": True, "pack_id": pack_id, "digest": _digest(destination)}


def _problem(problems, code, detail):
    problems.append({"code": code, "detail": detail})


def _cycle(skills):
    graph = {s.get("skill_id"): list(s.get("prerequisites") or []) for s in skills}
    visiting, visited, trail = set(), set(), []
    def walk(node):
        if node in visiting:
            at = trail.index(node)
            return trail[at:] + [node]
        if node in visited:
            return None
        visiting.add(node); trail.append(node)
        for child in graph.get(node, []):
            found = walk(child)
            if found:
                return found
        trail.pop(); visiting.remove(node); visited.add(node)
        return None
    for node in sorted(graph):
        found = walk(node)
        if found:
            return found
    return None


def _group_sum(sample):
    operation = sample.get("operation")
    if operation != "group_sum":
        raise PackRefused("INVALID_SAMPLE", f"unsupported operation {operation!r}")
    rows = sample.get("input")
    if not isinstance(rows, list) or not rows or len(rows) > 100:
        raise PackRefused("INVALID_SAMPLE", "input must contain 1..100 rows")
    totals = {}
    for row in rows:
        _exact(row, ("group", "amount"), "sample row")
        group = row["group"]
        amount = row["amount"]
        if not isinstance(group, str) or not group or len(group) > 80:
            raise PackRefused("INVALID_SAMPLE", "invalid group")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise PackRefused("INVALID_SAMPLE", "amount must be integer minor units")
        totals[group] = totals.get(group, 0) + amount
    return [{"group": key, "total": totals[key]} for key in sorted(totals)]


def validate_pack(home, pack_id):
    problems = []
    known_source_refs = set()
    try:
        directory = _pack_dir(home, pack_id)
        data = {name: _read(os.path.join(directory, name)) for name in FILES}
        digest = _digest(directory)
    except PackRefused as exc:
        return {"ok": False, "pack_id": pack_id, "digest": None,
                "problems": [{"code": exc.code, "detail": exc.detail}]}
    pack = data["pack.json"]
    try:
        _exact(pack, ("schema", "pack_id", "version", "author", "tenant_id",
                      "project_id", "title", "app", "objectives", "skills",
                      "route_claims"), "pack")
        if pack["schema"] != PACK_SCHEMA or pack["pack_id"] != pack_id:
            raise PackRefused("INVALID_PACK", "schema or pack ID differs")
        for key in ("pack_id", "author", "tenant_id", "project_id"):
            _ident(pack[key], key)
        tutor_sources.parse_version(pack["version"])
        app = _exact(pack["app"], ("app_id", "qualified_versions"), "app")
        _ident(app["app_id"], "app_id")
        versions = _exact(app["qualified_versions"], ("min", "max"), "qualified_versions")
        pack_low = tutor_sources.parse_version(versions["min"])
        pack_high = tutor_sources.parse_version(versions["max"])
        if pack_low > pack_high:
            raise PackRefused("INVALID_VERSION", "pack version range is reversed")
        objectives = pack["objectives"]
        if not isinstance(objectives, list) or not objectives:
            raise PackRefused("INVALID_PACK", "objectives missing")
        objective_types, objective_ids = set(), set()
        for obj in objectives:
            _exact(obj, ("objective_id", "type", "text"), "objective")
            _ident(obj["objective_id"], "objective_id")
            if obj["objective_id"] in objective_ids or obj["type"] not in ("conceptual", "procedural"):
                raise PackRefused("INVALID_PACK", "objective IDs/types invalid")
            objective_ids.add(obj["objective_id"]); objective_types.add(obj["type"])
        if objective_types != {"conceptual", "procedural"}:
            raise PackRefused("INVALID_PACK", "conceptual and procedural objectives are both required")
        skills = pack["skills"]
        if not isinstance(skills, list) or not skills:
            raise PackRefused("INVALID_PACK", "skills missing")
        skill_ids = set()
        for skill in skills:
            _exact(skill, ("skill_id", "type", "objective_ids", "prerequisites"), "skill")
            _ident(skill["skill_id"], "skill_id")
            if skill["skill_id"] in skill_ids or skill["type"] not in ("conceptual", "procedural"):
                raise PackRefused("INVALID_PACK", "skill IDs/types invalid")
            skill_ids.add(skill["skill_id"])
            if (not isinstance(skill["objective_ids"], list)
                    or not set(skill["objective_ids"]) <= objective_ids
                    or not isinstance(skill["prerequisites"], list)):
                raise PackRefused("INVALID_PACK", "skill references invalid")
        for skill in skills:
            if not set(skill["prerequisites"]) <= skill_ids:
                raise PackRefused("INVALID_PACK", "unknown prerequisite")
        found_cycle = _cycle(skills)
        if found_cycle:
            _problem(problems, "PREREQUISITE_CYCLE", " -> ".join(found_cycle))
        claims = pack["route_claims"]
        if not isinstance(claims, list) or not claims or any(
                not isinstance(c, str) or not c or len(c) > 300 for c in claims):
            raise PackRefused("INVALID_PACK", "route_claims invalid")
    except PackRefused as exc:
        _problem(problems, exc.code, exc.detail)
        return {"ok": False, "pack_id": pack_id, "digest": digest, "problems": problems}

    try:
        refs = _exact(data["sources.json"], ("schema", "references"), "sources")
        if refs["schema"] != "tutor.pack-sources/1" or not isinstance(refs["references"], list):
            raise PackRefused("INVALID_PACK", "source reference manifest invalid")
        for ref in refs["references"]:
            status = tutor_sources.source_reference_status(home, ref)
            if not status["ok"]:
                _problem(problems, status["code"], status["detail"])
                continue
            source = status["record"]
            if source["tenant_id"] != pack["tenant_id"] or source["project_id"] != pack["project_id"]:
                _problem(problems, "ACL_MISMATCH", f"source {ref['source_id']} differs from pack scope")
            if source["app_id"] != pack["app"]["app_id"]:
                _problem(problems, "APP_MISMATCH", f"source {ref['source_id']} names another app")
            low = tutor_sources.parse_version(source["app_versions"]["min"])
            high = tutor_sources.parse_version(source["app_versions"]["max"])
            if low > pack_low or high < pack_high:
                _problem(problems, "VERSION_CONFLICT",
                         f"source {ref['source_id']} does not cover the pack range")
            known_source_refs.add(
                f"{ref['source_id']}:{ref['revision']}:{ref['excerpt_id']}")
    except (PackRefused, tutor_sources.SourceRefused) as exc:
        _problem(problems, getattr(exc, "code", "INVALID_PACK"), str(exc))

    try:
        examples = _exact(data["examples.json"], ("schema", "examples"), "examples")
        if examples["schema"] != "tutor.examples/1" or not isinstance(examples["examples"], list) or not examples["examples"]:
            raise PackRefused("INVALID_PACK", "worked examples missing")
        for example in examples["examples"]:
            _exact(example, ("example_id", "skill_ids", "source_refs", "problem",
                             "methods", "misconceptions"), "example")
            _ident(example["example_id"], "example_id")
            if not set(example["skill_ids"]) <= skill_ids:
                raise PackRefused("INVALID_PACK", "example names unknown skill")
            if (not isinstance(example["source_refs"], list)
                    or not example["source_refs"]
                    or not set(example["source_refs"]) <= known_source_refs):
                raise PackRefused("MISSING_SOURCE", "worked example has an unverified source link")
            if not isinstance(example["methods"], list) or len(example["methods"]) < 2:
                raise PackRefused("INVALID_PACK", "worked example needs multiple valid methods")
            if not isinstance(example["misconceptions"], list) or not example["misconceptions"]:
                raise PackRefused("INVALID_PACK", "worked example needs misconceptions")
            for method in example["methods"]:
                _exact(method, ("method_id", "steps"), "method")
                if not isinstance(method["steps"], list) or not method["steps"]:
                    raise PackRefused("INVALID_PACK", "method steps missing")
    except PackRefused as exc:
        _problem(problems, exc.code, exc.detail)

    try:
        practice = _exact(data["practice.json"], ("schema", "samples"), "practice")
        if practice["schema"] != "tutor.practice/1" or not isinstance(practice["samples"], list) or not practice["samples"]:
            raise PackRefused("INVALID_PACK", "practice samples missing")
        for sample in practice["samples"]:
            _exact(sample, ("sample_id", "skill_ids", "safe", "operation", "input", "expected"), "sample")
            _ident(sample["sample_id"], "sample_id")
            if sample["safe"] is not True or not set(sample["skill_ids"]) <= skill_ids:
                raise PackRefused("INVALID_SAMPLE", "sample is unsafe or names unknown skills")
            actual = _group_sum(sample)
            if actual != sample["expected"]:
                _problem(problems, "SAMPLE_MISMATCH",
                         f"sample {sample['sample_id']} expected {sample['expected']!r} but computed {actual!r}")
    except PackRefused as exc:
        _problem(problems, exc.code, exc.detail)

    try:
        manifest = _exact(data["assessment_manifest.json"], ("schema", "items"), "assessment manifest")
        if manifest["schema"] != "tutor.assessment-manifest/1" or not isinstance(manifest["items"], list) or not manifest["items"]:
            raise PackRefused("INVALID_ASSESSMENT", "assessment manifest missing")
        for item in manifest["items"]:
            status = tutor_sources.verify_assessment_reference(home, item)
            if not status["ok"]:
                _problem(problems, status["code"], status["detail"])
    except (PackRefused, tutor_sources.SourceRefused) as exc:
        _problem(problems, getattr(exc, "code", "INVALID_ASSESSMENT"), str(exc))
    return {"ok": not problems, "pack_id": pack_id, "digest": digest,
            "problems": problems}


def _append(home, relative, row, unique=()):
    import locks
    path = os.path.join(os.path.abspath(home), relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with locks.holding(path, timeout=10.0, stale=8.0):
        if unique:
            try:
                for line in open(path, encoding="utf-8"):
                    current = json.loads(line, object_pairs_hook=_pairs)
                    if all(current.get(key) == row.get(key) for key in unique):
                        return current
            except OSError:
                pass
            except (json.JSONDecodeError, PackRefused) as exc:
                raise PackRefused("REVIEW_LEDGER_CORRUPT", str(exc)) from exc
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
            f.flush(); os.fsync(f.fileno())
    return row


def _rows(home, relative):
    path = os.path.join(os.path.abspath(home), relative)
    out = []
    try:
        for line in open(path, encoding="utf-8"):
            if line.strip():
                out.append(json.loads(line, object_pairs_hook=_pairs))
    except OSError:
        pass
    except (json.JSONDecodeError, PackRefused) as exc:
        raise PackRefused("REVIEW_LEDGER_CORRUPT", str(exc)) from exc
    return out


def review_pack(home, pack_id, *, reviewer_id, reviewer_kind, checklist):
    validation = validate_pack(home, pack_id)
    if not validation["ok"]:
        raise PackRefused("PACK_NOT_REVIEWABLE", validation["problems"][0]["detail"])
    pack = _read(os.path.join(_pack_dir(home, pack_id), "pack.json"))
    if reviewer_kind not in ("local_fixture", "subject_matter_human"):
        raise PackRefused("INVALID_REVIEW", "unknown reviewer kind")
    if reviewer_kind == "subject_matter_human":
        reviewer_id = _require_subject_reviewer(home, reviewer_id, pack_id)
    else:
        _ident(reviewer_id, "reviewer_id")
    if reviewer_id == pack["author"]:
        raise PackRefused("REVIEW_NOT_INDEPENDENT", "pack author cannot review the same version")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST or not all(
            value is True for value in checklist.values()):
        raise PackRefused("INVALID_REVIEW", "every review checklist item must be true")
    row = {"schema": "tutor.pack-review/1", "pack_id": pack_id,
           "pack_digest": validation["digest"], "reviewer_id": reviewer_id,
           "reviewer_kind": reviewer_kind, "checklist": checklist,
           "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return _append(home, REVIEWS, row,
                   unique=("schema", "pack_id", "pack_digest", "reviewer_id",
                           "reviewer_kind"))


def status(home, pack_id):
    validation = validate_pack(home, pack_id)
    if not validation["ok"]:
        return {"status": "CANDIDATE", "assignable": False,
                "validation": validation, "review_scope": None}
    reviews = [r for r in _rows(home, REVIEWS)
               if r.get("pack_id") == pack_id and r.get("pack_digest") == validation["digest"]]
    qualifications = [r for r in _rows(home, QUALIFICATIONS)
                      if r.get("pack_id") == pack_id and r.get("pack_digest") == validation["digest"]]
    if qualifications:
        return {"status": "QUALIFIED", "assignable": True,
                "validation": validation, "review_scope": "subject_matter_human"}
    human_reviews = [row for row in reviews
                     if row.get("reviewer_kind") == "subject_matter_human"]
    if human_reviews:
        return {"status": "REVIEWED", "assignable": False,
                "validation": validation, "review_scope": "subject_matter_human"}
    if reviews:
        return {"status": "CANDIDATE", "assignable": False,
                "validation": validation, "review_scope": "local_fixture",
                "fixture_validated": True}
    return {"status": "CANDIDATE", "assignable": False,
            "validation": validation, "review_scope": None}


def qualify_pack(home, pack_id, *, reviewer_id, evidence_ref):
    current = status(home, pack_id)
    reviewer_id = _require_subject_reviewer(home, reviewer_id, pack_id)
    reviews = [r for r in _rows(home, REVIEWS)
               if r.get("pack_id") == pack_id
               and r.get("pack_digest") == current["validation"]["digest"]
               and r.get("reviewer_id") == reviewer_id
               and r.get("reviewer_kind") == "subject_matter_human"]
    if not reviews or not isinstance(evidence_ref, str) or not evidence_ref.strip():
        raise PackRefused("QUALIFICATION_DENIED", "independent subject review evidence is required")
    row = {"schema": "tutor.pack-qualification/1", "pack_id": pack_id,
           "pack_digest": current["validation"]["digest"],
           "reviewer_id": reviewer_id, "evidence_ref": evidence_ref,
           "qualified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return _append(home, QUALIFICATIONS, row,
                   unique=("schema", "pack_id", "pack_digest", "reviewer_id",
                           "evidence_ref"))


def assignment_manifest(home, pack_id):
    current = status(home, pack_id)
    if not current["assignable"]:
        raise PackRefused("PACK_NOT_ASSIGNABLE",
                          "trusted practice requires subject review and qualification")
    practice = _read(os.path.join(_pack_dir(home, pack_id), "practice.json"))
    return {"schema": "tutor.assignment-manifest/1", "pack_id": pack_id,
            "pack_digest": current["validation"]["digest"],
            "review_scope": current["review_scope"],
            "learner_success_claimed": False,
            "sample_ids": [item["sample_id"] for item in practice["samples"]]}


def route_for_version(home, pack_id, app_version):
    current = status(home, pack_id)
    pack = _read(os.path.join(_pack_dir(home, pack_id), "pack.json"))
    requested = tutor_sources.parse_version(app_version)
    versions = pack["app"]["qualified_versions"]
    inside = (tutor_sources.parse_version(versions["min"]) <= requested
              <= tutor_sources.parse_version(versions["max"]))
    if current["status"] == "CANDIDATE":
        return {"exact_route": False, "claims": [], "status": "PACK_NOT_REVIEWED",
                "scope_limit": "Teaching pack has no current independent review."}
    if not inside:
        return {"exact_route": False, "claims": [], "status": "APP_VERSION_OUTSIDE_QUALIFICATION",
                "scope_limit": f"Qualified only for {versions['min']} through {versions['max']}; requested {app_version}."}
    if not current["assignable"]:
        return {"exact_route": False, "claims": [], "status": "PACK_NOT_QUALIFIED",
                "scope_limit": "Subject review exists, but qualification evidence is not sealed."}
    return {"exact_route": True, "claims": pack["route_claims"],
            "status": "OK", "scope_limit": None}


def retrieve(home, pack_id, *, tenant_id, project_id, query, app_version,
             limit=5, max_chars=6000):
    current = status(home, pack_id)
    if not current["assignable"]:
        raise PackRefused("PACK_NOT_ASSIGNABLE", "retrieval requires a reviewed pack")
    pack = _read(os.path.join(_pack_dir(home, pack_id), "pack.json"))
    if tenant_id != pack["tenant_id"] or project_id != pack["project_id"]:
        raise PackRefused("ACL_DENIED", "pack is outside the caller scope")
    route = route_for_version(home, pack_id, app_version)
    result = tutor_sources.retrieve(home, tenant_id=tenant_id, project_id=project_id,
                                    query=query, app_id=pack["app"]["app_id"],
                                    app_version=app_version, limit=limit,
                                    max_chars=max_chars)
    result["pack"] = {"pack_id": pack_id, "digest": current["validation"]["digest"],
                      "review_scope": current["review_scope"]}
    result["route"] = route
    return result
