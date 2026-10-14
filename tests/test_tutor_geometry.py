#!/usr/bin/env python3
"""SC-2A geometry, grounding, primitive and overlay-layer witnesses."""

import copy
import os
import sys

from common import AGENT_DIR

sys.path.insert(0, AGENT_DIR)
import tutor_grounding as G  # noqa: E402


GEOMETRY = {
    "coordinate_space": "source_pixels", "source_width": 2560,
    "source_height": 1440, "crop": {"x": 160, "y": 90,
                                      "width": 1920, "height": 1080},
    "model_width": 1280, "model_height": 720,
    "desktop_origin_x": -2560, "desktop_origin_y": 120,
    "native_dpi_scale": 1.5,
}
BINDING = {"source_id": "source-1", "source_revision": "source-r4",
           "geometry_revision": "geometry-r2"}


def candidate(target_id="save-button", modality="ACCESSIBILITY", name="Save",
              context="Report toolbar", x=1000, y=100, width=80, height=40,
              confidence=1.0, origin="APPLICATION"):
    return {"target_id": target_id, **BINDING, "modality": modality,
            "name": name, "role": "button", "context": context,
            "bounds": {"x": x, "y": y, "width": width, "height": height},
            "confidence": confidence, "origin": origin}


def main():
    mapped = G.model_to_desktop(GEOMETRY, 640, 360)
    assert abs(mapped["x"] - (-960.0)) < 1e-9
    assert abs(mapped["y"] - 500.0) < 1e-9
    round_trip = G.desktop_to_model(GEOMETRY, mapped["x"], mapped["y"])
    assert abs(round_trip["x"] - 640) < 1e-9
    assert abs(round_trip["y"] - 360) < 1e-9
    print("[T027] crop/resize/source/negative-desktop-origin/150%-DPI mapping round-tripped exactly in the synthetic geometry contract")

    unique = G.choose_target([candidate()], geometry=GEOMETRY,
                             query="Select Save in the Report toolbar",
                             visual_adapter_qualified=False, **BINDING)
    assert unique["status"] == "GROUNDED"
    duplicate = G.choose_target([
        candidate("save-top", context="Report toolbar"),
        candidate("save-bottom", context="Report toolbar")],
        geometry=GEOMETRY, query="Select Save in the Report toolbar",
        visual_adapter_qualified=False, **BINDING)
    assert duplicate == {"status": "ABSTAIN",
                         "reason": "AMBIGUOUS_SEMANTIC_TARGET",
                         "target": None, "abstained": True}
    print("[T029-offline] a unique semantic control grounded; equally matching duplicate controls abstained without guessing")

    tiny = G.choose_target([
        candidate("tiny-menu", modality="VISUAL", name="Menu", x=50, y=50,
                  width=3, height=3, confidence=0.99)], geometry=GEOMETRY,
        query="Open Menu", visual_adapter_qualified=True, **BINDING)
    assert tiny["reason"] == "BOUNDED_CROP_REQUIRED" and tiny["abstained"]
    unqualified = G.choose_target([
        candidate("visual-menu", modality="VISUAL", name="Menu", confidence=0.99)],
        geometry=GEOMETRY, query="Open Menu",
        visual_adapter_qualified=False, **BINDING)
    assert unqualified["reason"] == "VISUAL_ADAPTER_UNQUALIFIED"
    print("[T030-offline] tiny visual targets requested a bounded crop and an unqualified visual adapter could not ground")

    primitive = {"kind": "ARROW", "target_id": "save-button",
                 "label": "Choose Save", "points": [{"x": 900, "y": 140},
                                                          {"x": 1000, "y": 120}],
                 "style": {"color": "#1166CC", "stroke": 3}}
    ticket = G.schedule_overlay(
        ticket_id="ticket-1", observation_id="observation-1", capture_epoch=7,
        mode="GUIDE", geometry=GEOMETRY, target=unique["target"],
        primitives=[primitive], now_monotonic_ms=1000,
        expires_at_monotonic_ms=5000, **BINDING)
    assert ticket["input_privileges"] == [] and not ticket["hit_test_visible"]
    current = {"observation_id": "observation-1", "capture_epoch": 7,
               "mode": "GUIDE", **BINDING}
    assert G.render_overlay(ticket, current, now_monotonic_ms=1200)["status"] == "RENDER"
    moved = dict(current); moved["geometry_revision"] = "geometry-r3"
    stale = G.render_overlay(ticket, moved, now_monotonic_ms=1200)
    assert stale["status"] == "SUPPRESSED" and stale["primitives"] == []
    print("[T028-offline] changing only the geometry revision suppressed every scheduled primitive before render")

    hostile = copy.deepcopy(primitive)
    hostile["script"] = "open('project','w').write('changed')"
    try:
        G.schedule_overlay(
            ticket_id="ticket-2", observation_id="observation-1", capture_epoch=7,
            mode="GUIDE", geometry=GEOMETRY, target=unique["target"],
            primitives=[hostile], now_monotonic_ms=1000,
            expires_at_monotonic_ms=5000, **BINDING)
        raise AssertionError("active primitive content accepted")
    except G.GroundingRefused as exc:
        assert exc.code == "INVALID_GROUNDING"
    print("[T031] a script-bearing otherwise-valid arrow failed the closed inert primitive schema")

    layers = G.exclude_overlay_layers(
        ["application-window", "tutor-overlay-1", "application-menu"],
        ["tutor-overlay-1"])
    assert layers["application_layers"] == ["application-window", "application-menu"]
    assert layers["excluded_overlay_layers"] == ["tutor-overlay-1"]
    assert not layers["overlay_content_is_application_evidence"]
    overlay_candidate = candidate(origin="TUTOR_OVERLAY")
    overlay_only = G.choose_target([overlay_candidate], geometry=GEOMETRY,
                                   query="Select Save", visual_adapter_qualified=True,
                                   **BINDING)
    assert overlay_only["reason"] == "TARGET_NOT_FOUND"
    print("[T032-offline] companion layers and targets were excluded from application evidence and grounding")
    print("PASS test_tutor_geometry")


if __name__ == "__main__":
    main()
