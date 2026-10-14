#!/usr/bin/env python3
"""Deterministic, declarative explanatory scenes for Screen Tutor.

The canvas accepts data, never code. Every graph sample is recomputed from a
small closed expression tree before a scene can render. Interactive state is
bounded and disposable, and every scene carries a text alternative.
"""

import copy
import math
import re


SCHEMA = "tutor.scene/1"
KINDS = ("TEXT", "AXES", "EQUATION", "GRAPH", "NODE", "EDGE", "SLIDER")
OPS = {"ADD": (2, 8), "SUB": (2, 2), "MUL": (2, 8),
       "DIV": (2, 2), "POW": (2, 2), "MIN": (2, 8), "MAX": (2, 8)}
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,127}$")
MAX_PRIMITIVES = 64
MAX_EXPRESSION_NODES = 64
MAX_EXPRESSION_DEPTH = 8
MAX_SAMPLES = 64
MAX_TEXT = 4000
NUMBER_LIMIT = 1_000_000_000.0


class CanvasRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CanvasRefused("INVALID_SCENE", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise CanvasRefused("INVALID_SCENE", f"invalid {name}")
    return value


def _text(value, name, maximum=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CanvasRefused("INVALID_SCENE", f"invalid {name}")
    return value.strip()


def _number(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or abs(value) > NUMBER_LIMIT):
        raise CanvasRefused("INVALID_SCENE", f"invalid {name}")
    return float(value)


def _unit(value, name):
    number = _number(value, name)
    if not 0 <= number <= 1:
        raise CanvasRefused("INVALID_SCENE", f"{name} outside 0..1")
    return number


def _expression(value, *, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    if count[0] > MAX_EXPRESSION_NODES or depth > MAX_EXPRESSION_DEPTH:
        raise CanvasRefused("INVALID_SCENE", "expression exceeds bounds")
    if not isinstance(value, dict) or "kind" not in value:
        raise CanvasRefused("INVALID_SCENE", "expression node")
    kind = value.get("kind")
    if kind not in ("CONSTANT", "VARIABLE", "OP"):
        raise CanvasRefused("EXECUTABLE_SCENE_DENIED",
                            "only constant, variable and approved operation nodes are allowed")
    if kind == "CONSTANT":
        _exact(value, ("kind", "value"), "constant")
        return {"kind": kind, "value": _number(value["value"], "constant")}
    if kind == "VARIABLE":
        _exact(value, ("kind", "name"), "variable")
        return {"kind": kind, "name": _ident(value["name"], "variable")}
    _exact(value, ("kind", "op", "args"), "operation")
    op = value["op"]
    args = value["args"]
    if op not in OPS or not isinstance(args, list) or not OPS[op][0] <= len(args) <= OPS[op][1]:
        raise CanvasRefused("EXECUTABLE_SCENE_DENIED", "operation is outside the approved set")
    normalized = [_expression(arg, depth=depth + 1, count=count) for arg in args]
    if op == "POW":
        exponent = normalized[1]
        if (exponent.get("kind") != "CONSTANT"
                or not exponent["value"].is_integer()
                or not 0 <= exponent["value"] <= 8):
            raise CanvasRefused("INVALID_SCENE", "power exponent must be an integer from 0 to 8")
    return {"kind": kind, "op": op, "args": normalized}


def _variables(expression):
    if expression["kind"] == "VARIABLE":
        return {expression["name"]}
    if expression["kind"] == "CONSTANT":
        return set()
    result = set()
    for arg in expression["args"]:
        result.update(_variables(arg))
    return result


def evaluate_expression(expression, variables):
    """Evaluate an already declarative expression with bounded arithmetic."""
    node = _expression(expression)
    if not isinstance(variables, dict) or len(variables) > 16:
        raise CanvasRefused("INVALID_SCENE", "invalid variable values")
    values = {_ident(key, "variable"): _number(value, f"variable {key}")
              for key, value in variables.items()}

    def visit(item):
        if item["kind"] == "CONSTANT":
            return item["value"]
        if item["kind"] == "VARIABLE":
            if item["name"] not in values:
                raise CanvasRefused("INVALID_SCENE", f"missing variable {item['name']}")
            return values[item["name"]]
        operands = [visit(arg) for arg in item["args"]]
        try:
            if item["op"] == "ADD": result = sum(operands)
            elif item["op"] == "SUB": result = operands[0] - operands[1]
            elif item["op"] == "MUL": result = math.prod(operands)
            elif item["op"] == "DIV": result = operands[0] / operands[1]
            elif item["op"] == "POW": result = operands[0] ** int(operands[1])
            elif item["op"] == "MIN": result = min(operands)
            else: result = max(operands)
        except (ZeroDivisionError, OverflowError) as error:
            raise CanvasRefused("INVALID_SCENE", "undefined deterministic expression") from error
        return _number(result, "expression result")

    return visit(node)


def _primitive(value):
    if not isinstance(value, dict) or value.get("kind") not in KINDS:
        raise CanvasRefused("INVALID_SCENE", "unknown primitive")
    kind = value["kind"]
    if kind == "TEXT":
        _exact(value, ("kind", "id", "text", "x", "y"), "text primitive")
        return {"kind": kind, "id": _ident(value["id"], "primitive id"),
                "text": _text(value["text"], "text", 1000),
                "x": _unit(value["x"], "x"), "y": _unit(value["y"], "y")}
    if kind == "AXES":
        _exact(value, ("kind", "id", "x_min", "x_max", "y_min", "y_max",
                       "x_label", "y_label"), "axes primitive")
        row = {"kind": kind, "id": _ident(value["id"], "primitive id"),
               "x_min": _number(value["x_min"], "x_min"),
               "x_max": _number(value["x_max"], "x_max"),
               "y_min": _number(value["y_min"], "y_min"),
               "y_max": _number(value["y_max"], "y_max"),
               "x_label": _text(value["x_label"], "x_label", 80),
               "y_label": _text(value["y_label"], "y_label", 80)}
        if row["x_min"] >= row["x_max"] or row["y_min"] >= row["y_max"]:
            raise CanvasRefused("INVALID_SCENE", "axes ranges")
        return row
    if kind == "EQUATION":
        _exact(value, ("kind", "id", "output", "label", "expression"),
               "equation primitive")
        return {"kind": kind, "id": _ident(value["id"], "primitive id"),
                "output": _ident(value["output"], "equation output"),
                "label": _text(value["label"], "equation label", 500),
                "expression": _expression(value["expression"])}
    if kind == "GRAPH":
        _exact(value, ("kind", "id", "equation_id", "input_variable", "samples"),
               "graph primitive")
        samples = value["samples"]
        if not isinstance(samples, list) or not 2 <= len(samples) <= MAX_SAMPLES:
            raise CanvasRefused("INVALID_SCENE", "graph sample count")
        normalized = []
        for sample in samples:
            _exact(sample, ("inputs", "output"), "graph sample")
            if not isinstance(sample["inputs"], dict) or len(sample["inputs"]) > 16:
                raise CanvasRefused("INVALID_SCENE", "graph inputs")
            inputs = {_ident(key, "graph variable"): _number(number, f"input {key}")
                      for key, number in sample["inputs"].items()}
            normalized.append({"inputs": inputs,
                               "output": _number(sample["output"], "graph output")})
        return {"kind": kind, "id": _ident(value["id"], "primitive id"),
                "equation_id": _ident(value["equation_id"], "equation id"),
                "input_variable": _ident(value["input_variable"], "graph input variable"),
                "samples": normalized}
    if kind == "NODE":
        _exact(value, ("kind", "id", "label", "x", "y"), "node primitive")
        return {"kind": kind, "id": _ident(value["id"], "primitive id"),
                "label": _text(value["label"], "node label", 200),
                "x": _unit(value["x"], "x"), "y": _unit(value["y"], "y")}
    if kind == "EDGE":
        _exact(value, ("kind", "id", "from_id", "to_id", "label"), "edge primitive")
        return {"kind": kind, "id": _ident(value["id"], "primitive id"),
                "from_id": _ident(value["from_id"], "from id"),
                "to_id": _ident(value["to_id"], "to id"),
                "label": _text(value["label"], "edge label", 200)}
    _exact(value, ("kind", "id", "variable", "label", "min", "max", "step", "value"),
           "slider primitive")
    row = {"kind": kind, "id": _ident(value["id"], "primitive id"),
           "variable": _ident(value["variable"], "slider variable"),
           "label": _text(value["label"], "slider label", 120),
           "min": _number(value["min"], "slider min"),
           "max": _number(value["max"], "slider max"),
           "step": _number(value["step"], "slider step"),
           "value": _number(value["value"], "slider value")}
    if row["min"] >= row["max"] or row["step"] <= 0 or not row["min"] <= row["value"] <= row["max"]:
        raise CanvasRefused("INVALID_SCENE", "slider range")
    offset = (row["value"] - row["min"]) / row["step"]
    if not math.isfinite(offset) or not math.isclose(offset, round(offset), rel_tol=0, abs_tol=1e-9):
        raise CanvasRefused("INVALID_SCENE", "slider value is not aligned to step")
    return row


def validate_scene(scene):
    _exact(scene, ("schema", "scene_id", "concept_id", "title",
                   "text_alternative", "primitives"), "scene")
    if scene["schema"] != SCHEMA:
        raise CanvasRefused("INVALID_SCENE", "unsupported schema")
    primitives = scene["primitives"]
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= MAX_PRIMITIVES:
        raise CanvasRefused("INVALID_SCENE", "primitive count")
    rows = [_primitive(row) for row in primitives]
    if any(row['kind']=='GRAPH' for row in rows) and sum(row['kind']=='AXES' for row in rows)!=1:
        raise CanvasRefused('INVALID_SCENE','graphs require one unambiguous common axes primitive')
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise CanvasRefused("INVALID_SCENE", "duplicate primitive id")
    nodes = {row["id"] for row in rows if row["kind"] == "NODE"}
    equations = {row["id"]: row for row in rows if row["kind"] == "EQUATION"}
    sliders = {row["variable"] for row in rows if row["kind"] == "SLIDER"}
    if len(sliders) != len([row for row in rows if row["kind"] == "SLIDER"]):
        raise CanvasRefused("INVALID_SCENE", "duplicate slider variable")
    for row in rows:
        if row["kind"] == "EDGE" and (row["from_id"] not in nodes or row["to_id"] not in nodes):
            raise CanvasRefused("INVALID_SCENE", "edge endpoint")
        if row["kind"] != "GRAPH":
            continue
        equation = equations.get(row["equation_id"])
        if equation is None:
            raise CanvasRefused("INVALID_SCENE", "graph equation missing")
        variables = _variables(equation["expression"])
        if row["input_variable"] not in variables:
            raise CanvasRefused("INVALID_SCENE", "graph input variable is not in equation")
        for sample in row["samples"]:
            if set(sample["inputs"]) != variables:
                raise CanvasRefused("INVALID_SCENE", "graph inputs do not match equation")
            result = evaluate_expression(equation["expression"], sample["inputs"])
            if not math.isclose(result, sample["output"], rel_tol=1e-9, abs_tol=1e-9):
                raise CanvasRefused("GRAPH_CONTRADICTS_EQUATION", row["id"])
    return {"schema": SCHEMA, "scene_id": _ident(scene["scene_id"], "scene id"),
            "concept_id": _ident(scene["concept_id"], "concept id"),
            "title": _text(scene["title"], "title", 300),
            "text_alternative": _text(scene["text_alternative"], "text alternative"),
            "primitives": rows, "executable_content": False}


def _validated_again(scene):
    if not isinstance(scene, dict):
        raise CanvasRefused("INVALID_SCENE", "scene")
    raw = {key: copy.deepcopy(value) for key, value in scene.items()
           if key != "executable_content"}
    return validate_scene(raw)


def start_scene(scene):
    scene = _validated_again(scene)
    controls = {row["id"]: {key: row[key] for key in ("variable", "min", "max", "step")}
                for row in scene["primitives"] if row["kind"] == "SLIDER"}
    values = {row["variable"]: row["value"] for row in scene["primitives"]
              if row["kind"] == "SLIDER"}
    return {"schema": "tutor.canvas-session/1", "scene_id": scene["scene_id"],
            "session_revision": 0, "status": "ACTIVE",
            "slider_values": values, "initial_slider_values": dict(values),
            "slider_controls": controls, "adjustments": 0}


def _session(value):
    _exact(value, ("schema", "scene_id", "session_revision", "status",
                   "slider_values", "initial_slider_values", "slider_controls",
                   "adjustments"), "canvas session")
    if value["schema"] != "tutor.canvas-session/1" or value["status"] not in ("ACTIVE", "STOPPED"):
        raise CanvasRefused("INVALID_SCENE", "canvas session schema or status")
    _ident(value["scene_id"], "scene id")
    for field in ("session_revision", "adjustments"):
        if isinstance(value[field], bool) or not isinstance(value[field], int) or value[field] < 0:
            raise CanvasRefused("INVALID_SCENE", f"invalid {field}")
    if not all(isinstance(value[field], dict) and len(value[field]) <= 16
               for field in ("slider_values", "initial_slider_values", "slider_controls")):
        raise CanvasRefused("INVALID_SCENE", "invalid slider session state")
    for slider_id, control in value["slider_controls"].items():
        _ident(slider_id, "slider id")
        _exact(control, ("variable", "min", "max", "step"), "slider control")
        _ident(control["variable"], "slider variable")
        minimum = _number(control["min"], "slider min")
        maximum = _number(control["max"], "slider max")
        step = _number(control["step"], "slider step")
        if minimum >= maximum or step <= 0:
            raise CanvasRefused("INVALID_SCENE", "slider control range")
    expected_variables = {control["variable"]
                          for control in value["slider_controls"].values()}
    if (set(value["slider_values"]) != expected_variables
            or set(value["initial_slider_values"]) != expected_variables):
        raise CanvasRefused("INVALID_SCENE", "slider state does not match controls")
    for field in ("slider_values", "initial_slider_values"):
        for variable, number in value[field].items():
            _ident(variable, "slider variable")
            _number(number, "slider value")
    return value


def update_slider(session, slider_id, value):
    session = _session(session)
    if session["status"] != "ACTIVE":
        raise CanvasRefused("CANVAS_STOPPED", "stopped canvas cannot change")
    control = session["slider_controls"].get(_ident(slider_id, "slider id"))
    if control is None or set(control) != {"variable", "min", "max", "step"}:
        raise CanvasRefused("INVALID_SCENE", "unknown slider")
    number = _number(value, "slider value")
    if not control["min"] <= number <= control["max"]:
        raise CanvasRefused("INVALID_SCENE", "slider value outside range")
    offset = (number - control["min"]) / control["step"]
    if not math.isfinite(offset) or not math.isclose(offset, round(offset), rel_tol=0, abs_tol=1e-9):
        raise CanvasRefused("INVALID_SCENE", "slider value is not aligned to step")
    result = copy.deepcopy(session)
    result["slider_values"][control["variable"]] = number
    result["adjustments"] += 1
    result["session_revision"] += 1
    return result


def reset_scene(session):
    session = _session(session)
    if session["status"] != "ACTIVE":
        raise CanvasRefused("CANVAS_STOPPED", "stopped canvas cannot reset")
    result = copy.deepcopy(session)
    result["slider_values"] = dict(result["initial_slider_values"])
    result["session_revision"] += 1
    return result


def stop_scene(session):
    session = _session(session)
    result = copy.deepcopy(session)
    result["status"] = "STOPPED"
    result["session_revision"] += 1
    return result


def render_scene(scene, session):
    scene = _validated_again(scene)
    session = _session(session)
    if session["scene_id"] != scene["scene_id"]:
        raise CanvasRefused("INVALID_SCENE", "session belongs to another scene")
    expected_controls = {
        row["id"]: {key: row[key] for key in ("variable", "min", "max", "step")}
        for row in scene["primitives"] if row["kind"] == "SLIDER"}
    expected_values = {row["variable"]: row["value"]
                       for row in scene["primitives"] if row["kind"] == "SLIDER"}
    if (session["slider_controls"] != expected_controls
            or session["initial_slider_values"] != expected_values):
        raise CanvasRefused("INVALID_SCENE", "session slider binding changed")
    if session["status"] == "STOPPED":
        return {"schema": "tutor.canvas-render/1", "status": "STOPPED",
                "scene_id": scene["scene_id"],
                "primitives": [], "slider_values": {},
                "text_alternative": scene["text_alternative"],
                "executable_content": False}
    rendered = []
    equations = {row["id"]: row for row in scene["primitives"]
                 if row["kind"] == "EQUATION"}
    for row in scene["primitives"]:
        row = copy.deepcopy(row)
        if row["kind"] == "SLIDER":
            row["value"] = session["slider_values"][row["variable"]]
        elif row["kind"] == "GRAPH":
            equation = equations[row["equation_id"]]
            for sample in row["samples"]:
                for variable, number in session["slider_values"].items():
                    if variable in sample["inputs"]:
                        sample["inputs"][variable] = number
                sample["output"] = evaluate_expression(
                    equation["expression"], sample["inputs"])
        rendered.append({"kind": row["kind"], "id": row["id"],
                         "payload": {key: copy.deepcopy(value)
                                     for key, value in row.items()
                                     if key not in ("kind", "id")}})
    return {"schema": "tutor.canvas-render/1", "status": "RENDER",
            "scene_id": scene["scene_id"],
            "primitives": rendered,
            "slider_values": dict(session["slider_values"]),
            "text_alternative": scene["text_alternative"],
            "executable_content": False}
