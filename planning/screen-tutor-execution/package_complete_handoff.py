#!/usr/bin/env python3
"""Create and verify the complete Screen Tutor build handoff archive."""

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


BUILD = Path(__file__).resolve().parents[2]
WORKSPACE = BUILD.parent
PLAN = WORKSPACE / "planning" / "screen-tutor-v2-2026-09-14"
EXPORTS = WORKSPACE / "exports"
ARCHIVE = EXPORTS / "Screen_Tutor_Complete_Build_Handoff_2026-09-15.zip"
VALIDATION = EXPORTS / "Screen_Tutor_Complete_Build_Handoff_2026-09-15_VALIDATION.json"
LOGS = (
    Path(os.environ.get("TEMP", "")) / "screen-tutor-sc5a-runall-final-v2.log",
    Path(os.environ.get("TEMP", "")) / "screen-tutor-sc5a-native-final-v1.log",
    Path(os.environ.get("TEMP", "")) / "screen-tutor-sc5a-mutation-final-v1.log",
)
PLAN_SKIP_DIRS = {".git", "__pycache__", "node_modules", "bin", "obj"}
SECRET_NAMES = {".env", ".env.local", "agent.env", "credentials.env",
                "identity.json"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".pyc", ".tmp"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def git_text(*args):
    run = subprocess.run(["git", *args], cwd=BUILD, capture_output=True,
                         text=True, encoding="utf-8", errors="replace",
                         check=True)
    return run.stdout


def payload_files():
    sys.path.insert(0, os.fspath(BUILD))
    import package

    rows = []
    for path in sorted(BUILD.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(BUILD).as_posix()
        if package.should_skip(rel, os.fspath(path)):
            continue
        rows.append((path, "build/" + rel, "build-worktree"))
    for path in sorted(PLAN.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.is_symlink():
            continue
        rel_path = path.relative_to(PLAN)
        if (any(part in PLAN_SKIP_DIRS for part in rel_path.parts)
                or path.name.lower() in SECRET_NAMES
                or path.suffix.lower() in SECRET_SUFFIXES):
            continue
        rows.append((path, "authoritative-plan/" + rel_path.as_posix(),
                     "authoritative-plan"))
    for path in LOGS:
        if not path.is_file():
            raise FileNotFoundError(f"required verification log missing: {path}")
        rows.append((path, "verification-logs/" + path.name,
                     "verification-log"))
    archive_names = [row[1] for row in rows]
    if len(archive_names) != len(set(archive_names)):
        raise RuntimeError("duplicate archive path")
    return rows


def main():
    if not PLAN.is_dir():
        raise FileNotFoundError(PLAN)
    EXPORTS.mkdir(parents=True, exist_ok=True)
    rows = payload_files()
    status = git_text("status", "--short")
    diffstat = git_text("diff", "--stat")
    branch = git_text("branch", "--show-current").strip()
    head = git_text("rev-parse", "HEAD").strip()
    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    readme = f"""# Screen Tutor complete build handoff

Generated: {generated}

This archive contains:

- the complete current `screen-tutor-build` source snapshot, including all
  uncommitted implementation, tests, native source, planning decisions and
  packet evidence;
- the complete authoritative `screen-tutor-v2-2026-09-14` planning package,
  including preserved source material and its delivered archive;
- the final clean SC-5A full-suite, native and mutation verification logs;
- `MANIFEST.json`, with the byte length and SHA-256 of every payload file;
- `WORKTREE_STATUS.txt`, recording the branch, HEAD, dirty paths and diffstat.

Excluded from the build snapshot: Git internals, dependencies, `bin/`, `obj/`,
caches, generated ZIP/log/tmp files, private runtime state, expert memories,
contexts, task state and credential files. These exclusions follow the tested
repository packaging boundary. Native binaries are reproducible from the
included locked source and dependency graph.

Evidence boundary: this is a source/planning/local-evidence handoff. It is not
proof of provider, human-study, deployment or production-release qualification.
""".encode("utf-8")
    worktree = (f"branch: {branch}\nhead: {head}\n\n"
                f"git status --short:\n{status or '(clean)\n'}\n"
                f"git diff --stat:\n{diffstat or '(none)\n'}").encode("utf-8")

    manifest_rows = []
    file_bytes = []
    for source, archive_name, group in rows:
        data = source.read_bytes()
        file_bytes.append((archive_name, data))
        manifest_rows.append({"path": archive_name, "group": group,
                              "bytes": len(data), "sha256": digest(data)})
    for archive_name, data, group in (
            ("HANDOFF_README.md", readme, "handoff-metadata"),
            ("WORKTREE_STATUS.txt", worktree, "handoff-metadata")):
        file_bytes.append((archive_name, data))
        manifest_rows.append({"path": archive_name, "group": group,
                              "bytes": len(data), "sha256": digest(data)})
    manifest = {
        "schema": "screen-tutor-complete-handoff-manifest/1",
        "generated_at_utc": generated,
        "branch": branch,
        "head": head,
        "plan_manifest_sha256":
            "542865669529667d58b50ff98b75db5d7db93a925e4771ff4ebadffe144d6974",
        "payload_file_count": len(manifest_rows),
        "payload_bytes": sum(row["bytes"] for row in manifest_rows),
        "files": manifest_rows,
    }
    manifest_data = json.dumps(manifest, indent=2, ensure_ascii=True).encode("utf-8") + b"\n"

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, allowZip64=True) as archive:
        for archive_name, data in file_bytes:
            archive.writestr(archive_name, data)
        archive.writestr("MANIFEST.json", manifest_data)

    archive_sha = digest(ARCHIVE.read_bytes())
    with zipfile.ZipFile(ARCHIVE, "r") as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise RuntimeError("duplicate ZIP member")
        if archive.testzip() is not None:
            raise RuntimeError("ZIP CRC validation failed")
        loaded = json.loads(archive.read("MANIFEST.json"))
        if canonical(loaded) != canonical(manifest):
            raise RuntimeError("embedded manifest changed")
        for row in manifest_rows:
            data = archive.read(row["path"])
            if len(data) != row["bytes"] or digest(data) != row["sha256"]:
                raise RuntimeError("payload validation failed: " + row["path"])

    validation = {
        "schema": "screen-tutor-complete-handoff-validation/1",
        "archive": os.fspath(ARCHIVE),
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": archive_sha,
        "zip_member_count": len(manifest_rows) + 1,
        "payload_file_count": len(manifest_rows),
        "payload_bytes": manifest["payload_bytes"],
        "manifest_sha256": digest(manifest_data),
        "crc_check": "PASS",
        "duplicate_member_check": "PASS",
        "payload_hash_check": "PASS",
        "branch": branch,
        "head": head,
        "generated_at_utc": generated,
    }
    VALIDATION.write_text(json.dumps(validation, indent=2) + "\n",
                          encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
