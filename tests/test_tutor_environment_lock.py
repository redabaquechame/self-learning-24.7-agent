#!/usr/bin/env python3
"""SC-0C: exact environment locks isolate native and core qualification."""

import copy
import hashlib
import json
import os
import re
import subprocess
import sys

from common import AGENT_DIR


LOCK_PATH = os.path.join(
    AGENT_DIR, "planning", "screen-tutor", "ENVIRONMENT_LOCK.json")
WINDOWS_ROOT = os.path.join(AGENT_DIR, "companion", "windows")
ADR_ROOT = os.path.join(
    AGENT_DIR, "planning", "screen-tutor", "adr")
FIXTURE_MANIFEST = os.path.join(
    AGENT_DIR, "tests", "fixtures", "screen_tutor", "MANIFEST.json")
REQUIRED_ADRS = {
    "ADR-001-native-shell.md",
    "ADR-002-local-transport.md",
    "ADR-003-persistence.md",
    "ADR-004-packaging.md",
}


def load_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def digest(path):
    value = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def installed_sdks(dotnet="dotnet"):
    try:
        result = subprocess.run(
            [dotnet, "--list-sdks"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15, check=False)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.split(" ", 1)[0].strip() for line in result.stdout.splitlines()
            if line.strip()]


def classify(lock, sdks, package_hashes, windows_build, fixture_manifest):
    core_reasons = []
    for name in lock["core_ci"]["root_dependency_files_forbidden"]:
        if os.path.exists(os.path.join(AGENT_DIR, name)):
            core_reasons.append(f"forbidden root dependency file: {name}")

    native_reasons = []
    required_sdk = lock["windows_native"]["dotnet"]["sdk"]
    if required_sdk not in sdks:
        native_reasons.append(f"missing exact .NET SDK {required_sdk}")
    required_build = int(
        lock["windows_native"]["qualified_target_os_build"].split(".")[-1])
    if windows_build < required_build:
        native_reasons.append(
            f"Windows build {windows_build} is below {required_build}")
    app = lock["windows_native"]["windows_app_sdk"]
    for key in ("nupkg_sha256", "license_sha256", "notice_sha256",
                "nuspec_sha256"):
        if package_hashes.get(key) != app[key]:
            native_reasons.append(f"missing or mismatched {key}")
    if (fixture_manifest.get("schema")
            != "screen-tutor-fixture-manifest/1"
            or fixture_manifest.get("root_policy") != "synthetic-only"):
        native_reasons.append("synthetic fixture manifest is invalid")
    return {
        "core": {"status": "BLOCKED" if core_reasons else "READY",
                 "reasons": core_reasons},
        "native": {"status": "BLOCKED" if native_reasons else "READY",
                   "reasons": native_reasons},
    }


def check_lock_and_decisions():
    lock = load_json(LOCK_PATH)
    assert lock["schema"] == "screen-tutor-environment-lock/1"
    assert lock["policy"]["preview_is_default"] is False
    assert lock["policy"]["unlisted_version_status"] == "UNQUALIFIED"
    assert lock["core_ci"]["python_versions"] == ["3.11", "3.12", "3.13"]
    assert lock["core_ci"]["root_dependency_files_forbidden"] == [
        "requirements.txt", "pyproject.toml"]
    dotnet = lock["windows_native"]["dotnet"]
    assert dotnet == {
        "sdk": "10.0.401",
        "channel": "10.0 LTS",
        "global_json": "companion/windows/global.json",
        "expected_executable": "dotnet",
        "roll_forward": "disable",
        "allow_prerelease": False,
    }
    global_json = load_json(os.path.join(WINDOWS_ROOT, "global.json"))
    assert global_json["sdk"] == {
        "version": dotnet["sdk"],
        "rollForward": dotnet["roll_forward"],
        "allowPrerelease": dotnet["allow_prerelease"],
    }
    app = lock["windows_native"]["windows_app_sdk"]
    for key in ("nupkg_sha256", "license_sha256", "notice_sha256",
                "nuspec_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", app[key]), (key, app[key])
    project = open(os.path.join(
        WINDOWS_ROOT, "environment-probe", "EnvironmentProbe.csproj"),
        encoding="utf-8").read()
    assert f'Include="{app["package"]}" Version="{app["version"]}"' in project
    package_lock_path = os.path.join(
        WINDOWS_ROOT, "environment-probe", "packages.lock.json")
    package_lock = load_json(package_lock_path)
    assert digest(package_lock_path) == lock["windows_native"][
        "package_graph_lock_sha256"]
    direct = package_lock["dependencies"][
        "net10.0-windows10.0.26100"]["Microsoft.WindowsAppSDK"]
    assert direct["type"] == "Direct" and direct["resolved"] == app["version"]
    resolved = lock["windows_native"]["resolved_build_packages"]
    graph = package_lock["dependencies"]["net10.0-windows10.0.26100"]
    assert all(graph[name]["resolved"] == version
               for name, version in resolved.items())
    fixture = load_json(FIXTURE_MANIFEST)
    assert fixture == {"schema": "screen-tutor-fixture-manifest/1",
                       "root_policy": "synthetic-only", "fixtures": []}
    assert not os.path.exists(os.path.join(AGENT_DIR, "requirements.txt"))
    assert not os.path.exists(os.path.join(AGENT_DIR, "pyproject.toml"))

    adr_names = set(os.listdir(ADR_ROOT))
    assert REQUIRED_ADRS <= adr_names
    assert all(re.fullmatch(r"ADR-\d{3}-[a-z0-9-]+\.md", name)
               for name in adr_names), adr_names
    for name in adr_names:
        body = open(os.path.join(ADR_ROOT, name), encoding="utf-8").read()
        assert "**Status:** Accepted for implementation" in body, name
        for heading in ("## Context", "## Decision", "## Failure criteria",
                        "## Reversal"):
            assert heading in body, (name, heading)
    for name in REQUIRED_ADRS:
        body = open(os.path.join(ADR_ROOT, name), encoding="utf-8").read()
        assert "## Focused spike" in body, name
    print("[environment-lock] .NET 10.0.401, Windows App SDK 2.4.0, "
          "four dependency hashes, core CI versions, synthetic fixtures, "
          "and four implementation ADRs are exact and machine-readable")


def check_lane_classification_and_negative_witness():
    lock = load_json(LOCK_PATH)
    app = lock["windows_native"]["windows_app_sdk"]
    hashes = {key: app[key] for key in (
        "nupkg_sha256", "license_sha256", "notice_sha256", "nuspec_sha256")}
    fixture = load_json(FIXTURE_MANIFEST)
    actual = classify(lock, installed_sdks(), hashes, 26200, fixture)
    assert actual["core"]["status"] == "READY", actual
    assert actual["native"]["status"] in ("READY", "BLOCKED"), actual

    no_sdk = classify(lock, [], hashes, 26200, fixture)
    assert no_sdk["core"]["status"] == "READY", no_sdk
    assert no_sdk["native"]["status"] == "BLOCKED", no_sdk
    assert any("missing exact .NET SDK" in reason
               for reason in no_sdk["native"]["reasons"]), no_sdk

    bad_license = copy.deepcopy(hashes)
    bad_license["license_sha256"] = hashlib.sha256(
        b"wrong license").hexdigest()
    no_license = classify(
        lock, ["10.0.401"], bad_license, 26200, fixture)
    assert no_license["core"]["status"] == "READY", no_license
    assert no_license["native"]["status"] == "BLOCKED", no_license
    assert "missing or mismatched license_sha256" in (
        no_license["native"]["reasons"]), no_license
    print("[lane-isolation] missing exact SDK and mismatched license each block "
          "the native lane while the dependency-free core remains READY; "
          f"this process observed native={actual['native']['status']}")


def main():
    check_lock_and_decisions()
    check_lane_classification_and_negative_witness()
    print("PASS test_tutor_environment_lock")


if __name__ == "__main__":
    main()
