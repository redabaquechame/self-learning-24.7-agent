#!/usr/bin/env python3
"""SC-2C deterministic explanatory-scene witnesses (T041/T043)."""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tutor_canvas


def refused(fn, code):
    try:
        fn()
    except tutor_canvas.CanvasRefused as error:
        assert error.code == code, (error.code, error.detail)
        return
    raise AssertionError(f"expected {code}")


def scene():
    return {
        "schema": "tutor.scene/1",
        "scene_id": "linear-balance-1",
        "concept_id": "reporting-concept-total",
        "title": "A grouped total as a line",
        "text_alternative": (
            "The graph plots y = 2x + 1. Moving slope changes how much y "
            "rises for each one-unit increase in x."
        ),
        "primitives": [
            {"kind": "TEXT", "id": "intro", "text": "y = 2x + 1",
             "x": 0.08, "y": 0.06},
            {"kind": "AXES", "id": "axes", "x_min": -2, "x_max": 3,
             "y_min": -4, "y_max": 8, "x_label": "x", "y_label": "y"},
            {"kind": "EQUATION", "id": "line", "output": "y",
             "label": "y equals slope times x plus one",
             "expression": {"kind": "OP", "op": "ADD", "args": [
                 {"kind": "OP", "op": "MUL", "args": [
                     {"kind": "VARIABLE", "name": "slope"},
                     {"kind": "VARIABLE", "name": "x"}]},
                 {"kind": "CONSTANT", "value": 1}]}} ,
            {"kind": "GRAPH", "id": "line-graph", "equation_id": "line",
             "input_variable": "x",
             "samples": [
                 {"inputs": {"slope": 2, "x": -1}, "output": -1},
                 {"inputs": {"slope": 2, "x": 0}, "output": 1},
                 {"inputs": {"slope": 2, "x": 2}, "output": 5}]},
            {"kind": "NODE", "id": "east", "label": "East rows",
             "x": 0.2, "y": 0.78},
            {"kind": "NODE", "id": "total", "label": "Grouped total",
             "x": 0.72, "y": 0.78},
            {"kind": "EDGE", "id": "sum-edge", "from_id": "east",
             "to_id": "total", "label": "sum once"},
            {"kind": "SLIDER", "id": "slope-slider", "variable": "slope",
             "label": "Slope", "min": -4, "max": 4, "step": 0.5,
             "value": 2},
        ],
    }


def main():
    valid = tutor_canvas.validate_scene(scene())
    assert valid["scene_id"] == "linear-balance-1"
    assert valid["executable_content"] is False

    default_render = tutor_canvas.render_scene(valid, tutor_canvas.start_scene(valid))
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures",
                                "tutor_canvas_render_v1.json")
    with open(fixture_path, encoding="utf-8") as handle:
        assert default_render == json.load(handle)

    active = tutor_canvas.start_scene(valid)
    changed = tutor_canvas.update_slider(active, "slope-slider", 3.5)
    rendered = tutor_canvas.render_scene(valid, changed)
    assert rendered["status"] == "RENDER"
    assert rendered["slider_values"] == {"slope": 3.5}
    graph = next(row for row in rendered["primitives"] if row["kind"] == "GRAPH")
    assert graph["payload"]["samples"][2]["output"] == 8.0
    assert rendered["text_alternative"] == scene()["text_alternative"]
    assert all(set(row) <= {"kind", "id", "payload"}
               for row in rendered["primitives"])
    forged = copy.deepcopy(changed)
    forged["slider_controls"]["slope-slider"]["max"] = 500
    refused(lambda: tutor_canvas.render_scene(valid, forged), "INVALID_SCENE")

    reset = tutor_canvas.reset_scene(changed)
    assert reset["slider_values"] == {"slope": 2.0}
    stopped = tutor_canvas.stop_scene(reset)
    assert tutor_canvas.render_scene(valid, stopped)["status"] == "STOPPED"

    active_code = scene()
    active_code["primitives"][0]["code"] = "open('real.doc','w')"
    refused(lambda: tutor_canvas.validate_scene(active_code), "INVALID_SCENE")

    expression_code = scene()
    expression_code["primitives"][2]["expression"] = {
        "kind": "CODE", "source": "return process.mainModule"}
    refused(lambda: tutor_canvas.validate_scene(expression_code), "EXECUTABLE_SCENE_DENIED")

    contradictory = copy.deepcopy(scene())
    contradictory["primitives"][3]["samples"][2]["output"] = 500
    refused(lambda: tutor_canvas.validate_scene(contradictory),
            "GRAPH_CONTRADICTS_EQUATION")

    print("[T041] arbitrary primitive fields and executable expression nodes refused")
    print("[T043] graph samples were checked against the declared deterministic equation")
    print("[canvas] bounded slider, reset, Stop and text alternative passed")


if __name__ == "__main__":
    main()
