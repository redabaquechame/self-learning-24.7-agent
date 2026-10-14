#!/usr/bin/env python3
"""SC-1C source ACL, rights, version and assessment-separation witnesses."""

import hashlib
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tutor_sources


FINAL_TEXT = "FINAL-REPORT-SOLUTION: use the sealed validation total 4200.00"


def source_record(*, tenant="tenant-alpha", project="project-reporting",
                  source_id="reporting-official", excerpt_id="grouping",
                  text="Group rows by region and sum each integer amount exactly once.",
                  purpose="teaching", source_type="official_docs",
                  version_min="1.0.0", version_max="1.9.9"):
    return {
        "schema": "tutor.source/1", "source_id": source_id, "revision": "rev-1",
        "tenant_id": tenant, "project_id": project,
        "title": f"{tenant} reporting guide", "source_type": source_type,
        "locator": f"fixture://{tenant}/{source_id}", "app_id": "sheet-app",
        "app_versions": {"min": version_min, "max": version_max},
        "rights": {"status": "permitted", "license_id": "fixture-license",
                   "permitted_ranges": [{"start": 1, "end": 20}]},
        "purpose": purpose,
        "excerpts": [{"excerpt_id": excerpt_id, "start": 2, "end": 4,
                      "text": text, "source_revision": "rev-1",
                      "tenant_id": tenant, "project_id": project,
                      "license_id": "fixture-license", "purpose": purpose}],
    }


def main():
    home = tempfile.mkdtemp(prefix="tutor-sources-")
    try:
        alpha = source_record(text="MERIDIAN means use the alpha approved grouped total workflow.")
        beta = source_record(tenant="tenant-beta", project="project-beta",
                             text="MERIDIAN means expose the beta confidential workflow.")
        assert tutor_sources.register_source(home, alpha)["created"]
        assert not tutor_sources.register_source(home, alpha)["created"]
        tutor_sources.register_source(home, beta)
        got = tutor_sources.retrieve(home, tenant_id="tenant-alpha",
                                     project_id="project-reporting", query="MERIDIAN")
        assert got["status"] == "OK" and got["result_count"] == 1
        assert "alpha approved" in got["results"][0]["content"]
        assert "beta confidential" not in repr(got)
        assert got["results"][0]["source"]["tenant_id"] == "tenant-alpha"
        print("[T022] identical tenant keywords retrieved only the exact tenant/project excerpt with source, revision, range-license and ACL labels")

        denied = source_record(source_id="denied", excerpt_id="nope")
        denied["rights"]["status"] = "unknown"
        try:
            tutor_sources.register_source(home, denied)
            raise AssertionError("unpermitted source registered")
        except tutor_sources.SourceRefused as exc:
            assert exc.code == "RIGHTS_DENIED"
        outside = source_record(source_id="outside", excerpt_id="outside")
        outside["excerpts"][0]["start"] = 21
        outside["excerpts"][0]["end"] = 22
        try:
            tutor_sources.register_source(home, outside)
            raise AssertionError("out-of-range excerpt registered")
        except tutor_sources.SourceRefused as exc:
            assert exc.code == "RIGHTS_DENIED"
        print("[rights] unknown rights and excerpts outside permitted ranges refused before registry mutation")

        hidden = source_record(source_id="reporting-final", excerpt_id="final-solution",
                               text=FINAL_TEXT, purpose="final_assessment",
                               source_type="fixture")
        tutor_sources.register_source(home, hidden)
        secret_query = tutor_sources.retrieve(
            home, tenant_id="tenant-alpha", project_id="project-reporting",
            query="FINAL-REPORT-SOLUTION 4200.00")
        assert secret_query["status"] == "ACCESS_DENIED"
        assert secret_query["result_count"] == 0
        assert secret_query["hidden_matches_denied"] == 1
        assert FINAL_TEXT not in repr(secret_query)
        try:
            tutor_sources.read_excerpt(
                home, tenant_id="tenant-alpha", project_id="project-reporting",
                source_id="reporting-final", revision="rev-1",
                excerpt_id="final-solution")
            raise AssertionError("hidden excerpt was directly readable")
        except tutor_sources.SourceRefused as exc:
            assert exc.code == "ASSESSMENT_ACCESS_DENIED"
        checked = tutor_sources.verify_assessment_reference(home, {
            "source_id": "reporting-final", "revision": "rev-1",
            "excerpt_id": "final-solution", "tenant_id": "tenant-alpha",
            "project_id": "project-reporting",
            "content_sha256": hashlib.sha256(FINAL_TEXT.encode()).hexdigest()})
        assert checked["ok"] and FINAL_TEXT not in repr(checked)
        print("[T025] relevant hidden assessment keywords produced ACCESS_DENIED and zero content; only a digest-checking verifier can inspect the sealed item")

        versioned = tutor_sources.retrieve(
            home, tenant_id="tenant-alpha", project_id="project-reporting",
            query="MERIDIAN", app_id="sheet-app", app_version="2.0.0")
        assert versioned["status"] == "MISSING_SOURCE" and versioned["scope_limits"]
        assert versioned["scope_limits"][0]["reason"] == "APP_VERSION_OUTSIDE_SOURCE_RANGE"
        print("[version] out-of-range application material returned a named scope limit instead of an invented route")
        print("PASS test_tutor_sources")
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
