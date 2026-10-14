#!/usr/bin/env python3
"""SC-1C pack lifecycle, graph, sample and version witnesses."""

import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import tutor_packs
import tutor_sources
import org
from test_tutor_sources import FINAL_TEXT, source_record


PACK_SOURCE = os.path.join(ROOT, "teaching_packs", "reporting-v1")
CHECKLIST = {name: True for name in tutor_packs.CHECKLIST}
OWNER = "owner@example.test"
REVIEWER = "reviewer@example.test"


def seed(home, official_max="1.9.9"):
    tutor_sources.register_source(home, source_record(version_max=official_max))
    tutor_sources.register_source(home, source_record(
        source_id="reporting-asset", excerpt_id="safe-data",
        text="Synthetic rows contain only invented region labels and integer minor-unit amounts.",
        source_type="licensed_asset"))
    tutor_sources.register_source(home, source_record(
        source_id="reporting-final", excerpt_id="final-solution", text=FINAL_TEXT,
        purpose="final_assessment", source_type="fixture"))


def install_variant(home, pack_id, mutate):
    stage = tempfile.mkdtemp(prefix="pack-stage-")
    try:
        directory = os.path.join(stage, pack_id)
        shutil.copytree(PACK_SOURCE, directory)
        pack_path = os.path.join(directory, "pack.json")
        pack = json.load(open(pack_path, encoding="utf-8"))
        pack["pack_id"] = pack_id
        with open(pack_path, "w", encoding="utf-8") as f:
            json.dump(pack, f, indent=2)
        mutate(directory)
        return tutor_packs.install_candidate(home, directory)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def new_home(name):
    home = tempfile.mkdtemp(prefix=name)
    seed(home)
    return home


def authorize_reviewer(home):
    org.create(home, "Synthetic test organization", OWNER)
    org.add_user(home, OWNER, REVIEWER, "reviewer")


def main():
    homes = []
    try:
        home = new_home("pack-happy-"); homes.append(home)
        installed = tutor_packs.install_candidate(home, PACK_SOURCE)
        assert installed["created"]
        validation = tutor_packs.validate_pack(home, "reporting-v1")
        assert validation["ok"], validation
        assert tutor_packs.status(home, "reporting-v1")["status"] == "CANDIDATE"
        review = tutor_packs.review_pack(
            home, "reporting-v1", reviewer_id="independent-fixture-reviewer",
            reviewer_kind="local_fixture", checklist=CHECKLIST)
        assert review["pack_digest"] == validation["digest"]
        current = tutor_packs.status(home, "reporting-v1")
        assert current["status"] == "CANDIDATE" and current["fixture_validated"]
        try:
            tutor_packs.assignment_manifest(home, "reporting-v1")
            raise AssertionError("fixture-reviewed candidate was assignable")
        except tutor_packs.PackRefused as exc:
            assert exc.code == "PACK_NOT_ASSIGNABLE"
        print("[candidate-pack] conceptual/procedural objectives, rights-bound sources, two valid methods, misconceptions, a safe deterministic sample and hidden assessment digest passed local fixture validation; it remains candidate and unassignable without subject review")

        try:
            tutor_packs.review_pack(home, "reporting-v1",
                                    reviewer_id="pack-author-fixture",
                                    reviewer_kind="local_fixture", checklist=CHECKLIST)
            raise AssertionError("author reviewed own pack")
        except tutor_packs.PackRefused as exc:
            assert exc.code == "REVIEW_NOT_INDEPENDENT"
        try:
            tutor_packs.review_pack(
                home, "reporting-v1", reviewer_id=REVIEWER,
                reviewer_kind="subject_matter_human", checklist=CHECKLIST)
            raise AssertionError("subject review accepted without organization authority")
        except tutor_packs.PackRefused as exc:
            assert exc.code == "REVIEW_AUTHORITY_DENIED"
        authorize_reviewer(home)
        tutor_packs.review_pack(
            home, "reporting-v1", reviewer_id=REVIEWER,
            reviewer_kind="subject_matter_human", checklist=CHECKLIST)
        reviewed = tutor_packs.status(home, "reporting-v1")
        assert reviewed["status"] == "REVIEWED" and not reviewed["assignable"]
        tutor_packs.qualify_pack(home, "reporting-v1",
                                 reviewer_id=REVIEWER,
                                 evidence_ref="synthetic-contract-witness-only")
        assert tutor_packs.status(home, "reporting-v1")["status"] == "QUALIFIED"
        assignment = tutor_packs.assignment_manifest(home, "reporting-v1")
        assert assignment["sample_ids"] == ["safe-group-sum-1"]
        assert assignment["learner_success_claimed"] is False
        retrieved = tutor_packs.retrieve(
            home, "reporting-v1", tenant_id="tenant-alpha",
            project_id="project-reporting", query="Group rows integer amount",
            app_version="1.5.0", limit=3, max_chars=2000)
        assert retrieved["status"] == "OK" and retrieved["route"]["exact_route"]
        assert all("source" in row and "revision" in row["source"]
                   for row in retrieved["results"])
        print("[lifecycle-contract] synthetic authority records exercised reviewed-to-qualified transitions and bounded labelled retrieval; they prove the mechanism only, not that a real subject reviewer approved this pack")
        print("[review-authority] author self-review and an unbound human label refused; only an active organization reviewer exercised the synthetic transition, while local fixture review could not authorize trusted practice")

        cycle_home = new_home("pack-cycle-"); homes.append(cycle_home)
        def make_cycle(directory):
            path = os.path.join(directory, "pack.json")
            pack = json.load(open(path, encoding="utf-8"))
            pack["skills"][0]["prerequisites"] = ["reporting-procedure-group"]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(pack, f, indent=2)
        install_variant(cycle_home, "reporting-cycle", make_cycle)
        cycle = tutor_packs.validate_pack(cycle_home, "reporting-cycle")
        assert not cycle["ok"]
        cycle_problem = next(p for p in cycle["problems"] if p["code"] == "PREREQUISITE_CYCLE")
        assert "reporting-concept-total" in cycle_problem["detail"]
        try:
            tutor_packs.review_pack(cycle_home, "reporting-cycle",
                                    reviewer_id="reviewer", reviewer_kind="local_fixture",
                                    checklist=CHECKLIST)
            raise AssertionError("cyclic pack reviewed")
        except tutor_packs.PackRefused as exc:
            assert exc.code == "PACK_NOT_REVIEWABLE"
        print("[T023] cyclic prerequisites kept the pack candidate and named the complete cycle before review")

        wrong_home = new_home("pack-wrong-"); homes.append(wrong_home)
        def wrong_expected(directory):
            path = os.path.join(directory, "practice.json")
            practice = json.load(open(path, encoding="utf-8"))
            practice["samples"][0]["expected"][0]["total"] = 999999
            with open(path, "w", encoding="utf-8") as f:
                json.dump(practice, f, indent=2)
        install_variant(wrong_home, "reporting-wrong", wrong_expected)
        wrong = tutor_packs.validate_pack(wrong_home, "reporting-wrong")
        assert any(p["code"] == "SAMPLE_MISMATCH" for p in wrong["problems"])
        assert tutor_packs.status(wrong_home, "reporting-wrong")["status"] == "CANDIDATE"
        try:
            tutor_packs.assignment_manifest(wrong_home, "reporting-wrong")
            raise AssertionError("wrong sample assigned")
        except tutor_packs.PackRefused as exc:
            assert exc.code == "PACK_NOT_ASSIGNABLE"
        print("[T026] an incorrect generated expected result failed independent recomputation, remained candidate and could not become trusted practice")

        route = tutor_packs.route_for_version(home, "reporting-v1", "2.0.0")
        assert route["status"] == "APP_VERSION_OUTSIDE_QUALIFICATION"
        assert route["exact_route"] is False and route["claims"] == []
        assert "1.0.0 through 1.9.9" in route["scope_limit"]
        print("[T024] an unsupported app version disabled every exact route claim and returned the qualified range as a scope limit")

        conflict_home = tempfile.mkdtemp(prefix="pack-version-conflict-"); homes.append(conflict_home)
        seed(conflict_home, official_max="1.5.0")
        tutor_packs.install_candidate(conflict_home, PACK_SOURCE)
        conflict = tutor_packs.validate_pack(conflict_home, "reporting-v1")
        assert any(p["code"] == "VERSION_CONFLICT" for p in conflict["problems"])
        print("[version-conflict] a cited source that does not cover the pack's complete app range prevents review")
        print("PASS test_tutor_packs")
    finally:
        for home in homes:
            shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    main()
