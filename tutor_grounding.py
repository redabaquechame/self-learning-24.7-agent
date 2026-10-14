#!/usr/bin/env python3
"""Revision-bound semantic grounding and inert overlay scheduling.

All coordinates enter as model pixels over the observation's resized crop and
leave as desktop device-independent pixels (DIPs). A target or overlay is valid
only for the exact source, capture epoch and geometry revision that produced it.
"""

import math
import re


PRIMITIVES = ("RECT", "ARROW", "POINT", "LABEL")
MODALITIES = ("ACCESSIBILITY", "VISUAL")
MODES = ("EXPLAIN", "GUIDE")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}")
MAX_CANDIDATES = 64
MAX_PRIMITIVES = 16
MAX_TTL_MS = 30_000


class GroundingRefused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


def _exact(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise GroundingRefused("INVALID_GROUNDING", f"invalid {where} fields")
    return value


def _ident(value, name):
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise GroundingRefused("INVALID_GROUNDING", f"invalid {name}")
    return value


def _number(value, name, *, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (positive and value <= 0)):
        raise GroundingRefused("INVALID_GROUNDING", f"invalid {name}")
    return float(value)


def _text(value, name, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise GroundingRefused("INVALID_GROUNDING", f"invalid {name}")
    return value.strip()


def validate_geometry(value):
    _exact(value, ("coordinate_space", "source_width", "source_height", "crop",
                   "model_width", "model_height", "desktop_origin_x",
                   "desktop_origin_y", "native_dpi_scale"), "geometry")
    if value["coordinate_space"] != "source_pixels":
        raise GroundingRefused("INVALID_GROUNDING", "coordinate space")
    for field in ("source_width", "source_height", "model_width", "model_height"):
        size = _number(value[field], field, positive=True)
        if not size.is_integer():
            raise GroundingRefused("INVALID_GROUNDING", f"{field} must be integer")
    origin_x = _number(value["desktop_origin_x"], "desktop_origin_x")
    origin_y = _number(value["desktop_origin_y"], "desktop_origin_y")
    scale = _number(value["native_dpi_scale"], "native_dpi_scale", positive=True)
    crop = _exact(value["crop"], ("x", "y", "width", "height"), "crop")
    for field in ("x", "y", "width", "height"):
        number = _number(crop[field], f"crop.{field}", positive=field in ("width", "height"))
        if number < 0 or not number.is_integer():
            raise GroundingRefused("INVALID_GROUNDING", f"invalid crop.{field}")
    if (crop["x"] + crop["width"] > value["source_width"]
            or crop["y"] + crop["height"] > value["source_height"]):
        raise GroundingRefused("INVALID_GROUNDING", "crop outside source")
    return {
        "source_width": float(value["source_width"]),
        "source_height": float(value["source_height"]),
        "crop_x": float(crop["x"]), "crop_y": float(crop["y"]),
        "crop_width": float(crop["width"]), "crop_height": float(crop["height"]),
        "model_width": float(value["model_width"]),
        "model_height": float(value["model_height"]),
        "desktop_origin_x": origin_x, "desktop_origin_y": origin_y,
        "native_dpi_scale": scale,
    }


def model_to_desktop(geometry, x, y):
    g = validate_geometry(geometry)
    x = _number(x, "x"); y = _number(y, "y")
    if not 0 <= x <= g["model_width"] or not 0 <= y <= g["model_height"]:
        raise GroundingRefused("POINT_OUTSIDE_MODEL", "model point outside resized crop")
    source_x = g["crop_x"] + x * g["crop_width"] / g["model_width"]
    source_y = g["crop_y"] + y * g["crop_height"] / g["model_height"]
    return {"x": (g["desktop_origin_x"] + source_x) / g["native_dpi_scale"],
            "y": (g["desktop_origin_y"] + source_y) / g["native_dpi_scale"],
            "space": "desktop_dip"}


def desktop_to_model(geometry, x, y):
    g = validate_geometry(geometry)
    x = _number(x, "x"); y = _number(y, "y")
    source_x = x * g["native_dpi_scale"] - g["desktop_origin_x"]
    source_y = y * g["native_dpi_scale"] - g["desktop_origin_y"]
    model_x = (source_x - g["crop_x"]) * g["model_width"] / g["crop_width"]
    model_y = (source_y - g["crop_y"]) * g["model_height"] / g["crop_height"]
    if not 0 <= model_x <= g["model_width"] or not 0 <= model_y <= g["model_height"]:
        raise GroundingRefused("POINT_OUTSIDE_MODEL", "desktop point outside resized crop")
    return {"x": model_x, "y": model_y, "space": "model_pixels"}


def _bounds(value, geometry):
    _exact(value, ("x", "y", "width", "height"), "bounds")
    x = _number(value["x"], "bounds.x")
    y = _number(value["y"], "bounds.y")
    width = _number(value["width"], "bounds.width", positive=True)
    height = _number(value["height"], "bounds.height", positive=True)
    g = validate_geometry(geometry)
    if x < 0 or y < 0 or x + width > g["model_width"] or y + height > g["model_height"]:
        raise GroundingRefused("TARGET_OUTSIDE_MODEL", "target bounds outside model input")
    return {"x": x, "y": y, "width": width, "height": height}


def _candidate(row, binding, geometry):
    _exact(row, ("target_id", "source_id", "source_revision",
                 "geometry_revision", "modality", "name", "role", "context",
                 "bounds", "confidence", "origin"), "candidate")
    for field in ("target_id", "source_id", "source_revision", "geometry_revision"):
        _ident(row[field], field)
    if any(row[field] != binding[field] for field in (
            "source_id", "source_revision", "geometry_revision")):
        raise GroundingRefused("STALE_TARGET", row["target_id"])
    if row["modality"] not in MODALITIES or row["origin"] not in (
            "APPLICATION", "TUTOR_OVERLAY"):
        raise GroundingRefused("INVALID_GROUNDING", "candidate modality or origin")
    for field in ("name", "role", "context"):
        _text(row[field], field)
    confidence = _number(row["confidence"], "confidence")
    if not 0 <= confidence <= 1:
        raise GroundingRefused("INVALID_GROUNDING", "confidence outside 0..1")
    result = dict(row)
    result["bounds"] = _bounds(row["bounds"], geometry)
    result["confidence"] = confidence
    return result


def choose_target(candidates, *, source_id, source_revision, geometry_revision,
                  geometry, query, visual_adapter_qualified=False,
                  minimum_visual_pixels=8):
    """Prefer a unique semantic target; otherwise use qualified visual evidence."""
    for value, name in ((source_id, "source_id"),
                        (source_revision, "source_revision"),
                        (geometry_revision, "geometry_revision")):
        _ident(value, name)
    query = _text(query, "query", 1000)
    if not isinstance(candidates, list) or len(candidates) > MAX_CANDIDATES:
        raise GroundingRefused("INVALID_GROUNDING", "candidate list exceeds bound")
    if not isinstance(visual_adapter_qualified, bool):
        raise GroundingRefused("INVALID_GROUNDING", "visual qualification flag")
    minimum = _number(minimum_visual_pixels, "minimum_visual_pixels", positive=True)
    binding = {"source_id": source_id, "source_revision": source_revision,
               "geometry_revision": geometry_revision}
    rows = [_candidate(row, binding, geometry) for row in candidates]
    rows = [row for row in rows if row["origin"] == "APPLICATION"]
    terms = {word.lower() for word in WORD.findall(query)}

    def score(row):
        name = {word.lower() for word in WORD.findall(row["name"] + " " + row["role"])}
        context = {word.lower() for word in WORD.findall(row["context"])}
        return 3 * len(terms & name) + len(terms & context)

    semantic = [(score(row), row) for row in rows if row["modality"] == "ACCESSIBILITY"]
    semantic = [item for item in semantic if item[0] > 0]
    semantic.sort(key=lambda item: (-item[0], item[1]["target_id"]))
    if semantic:
        if len(semantic) == 1 or semantic[0][0] > semantic[1][0]:
            return {"status": "GROUNDED", "reason": "UNIQUE_SEMANTIC_TARGET",
                    "target": semantic[0][1], "abstained": False}
        return {"status": "ABSTAIN", "reason": "AMBIGUOUS_SEMANTIC_TARGET",
                "target": None, "abstained": True}

    visual = [(score(row), row) for row in rows if row["modality"] == "VISUAL"]
    visual = [item for item in visual if item[0] > 0]
    visual.sort(key=lambda item: (-item[0], -item[1]["confidence"], item[1]["target_id"]))
    if not visual:
        return {"status": "ABSTAIN", "reason": "TARGET_NOT_FOUND",
                "target": None, "abstained": True}
    if not visual_adapter_qualified:
        return {"status": "ABSTAIN", "reason": "VISUAL_ADAPTER_UNQUALIFIED",
                "target": None, "abstained": True}
    first = visual[0]
    if first[1]["confidence"] < 0.9:
        return {"status": "ABSTAIN", "reason": "VISUAL_CONFIDENCE_TOO_LOW",
                "target": None, "abstained": True}
    if (first[1]["bounds"]["width"] < minimum
            or first[1]["bounds"]["height"] < minimum):
        return {"status": "ABSTAIN", "reason": "BOUNDED_CROP_REQUIRED",
                "target": None, "abstained": True}
    if len(visual) > 1 and visual[0][0] == visual[1][0] and math.isclose(
            visual[0][1]["confidence"], visual[1][1]["confidence"]):
        return {"status": "ABSTAIN", "reason": "AMBIGUOUS_VISUAL_TARGET",
                "target": None, "abstained": True}
    return {"status": "GROUNDED", "reason": "QUALIFIED_VISUAL_TARGET",
            "target": first[1], "abstained": False}


def _primitive(row, target, geometry):
    _exact(row, ("kind", "target_id", "label", "points", "style"), "primitive")
    if row["kind"] not in PRIMITIVES or row["target_id"] != target["target_id"]:
        raise GroundingRefused("INVALID_PRIMITIVE", "kind or target")
    label = _text(row["label"], "label", 256)
    style = _exact(row["style"], ("color", "stroke"), "style")
    if not isinstance(style["color"], str) or not COLOR.fullmatch(style["color"]):
        raise GroundingRefused("INVALID_PRIMITIVE", "color")
    stroke = _number(style["stroke"], "stroke", positive=True)
    if stroke > 8:
        raise GroundingRefused("INVALID_PRIMITIVE", "stroke exceeds bound")
    expected = {"POINT": 1, "LABEL": 1, "RECT": 2, "ARROW": 2}[row["kind"]]
    if not isinstance(row["points"], list) or len(row["points"]) != expected:
        raise GroundingRefused("INVALID_PRIMITIVE", "point count")
    points = []
    for point in row["points"]:
        _exact(point, ("x", "y"), "point")
        mapped = model_to_desktop(geometry, point["x"], point["y"])
        points.append({"x": mapped["x"], "y": mapped["y"]})
    return {"kind": row["kind"], "target_id": target["target_id"],
            "label": label, "points": points,
            "style": {"color": style["color"].upper(), "stroke": stroke},
            "text_alternative": f"{row['kind'].lower()}: {label}"}


def schedule_overlay(*, ticket_id, observation_id, source_id, source_revision,
                     capture_epoch, geometry_revision, mode, geometry, target,
                     primitives, now_monotonic_ms, expires_at_monotonic_ms):
    for value, name in ((ticket_id, "ticket_id"),
                        (observation_id, "observation_id"),
                        (source_id, "source_id"),
                        (source_revision, "source_revision"),
                        (geometry_revision, "geometry_revision")):
        _ident(value, name)
    if mode not in MODES:
        raise GroundingRefused("MODE_DENIED", "overlays require Explain or Guide")
    if isinstance(capture_epoch, bool) or not isinstance(capture_epoch, int) or capture_epoch < 0:
        raise GroundingRefused("INVALID_GROUNDING", "capture epoch")
    now = _number(now_monotonic_ms, "now_monotonic_ms")
    expires = _number(expires_at_monotonic_ms, "expires_at_monotonic_ms")
    if expires <= now or expires - now > MAX_TTL_MS:
        raise GroundingRefused("INVALID_GROUNDING", "overlay expiry")
    if (target.get("source_id") != source_id
            or target.get("source_revision") != source_revision
            or target.get("geometry_revision") != geometry_revision):
        raise GroundingRefused("STALE_TARGET", "target binding")
    if not isinstance(primitives, list) or not 1 <= len(primitives) <= MAX_PRIMITIVES:
        raise GroundingRefused("INVALID_PRIMITIVE", "primitive count")
    mapped = [_primitive(row, target, geometry) for row in primitives]
    return {
        "schema": "tutor.overlay-ticket/1", "ticket_id": ticket_id,
        "observation_id": observation_id, "source_id": source_id,
        "source_revision": source_revision, "capture_epoch": capture_epoch,
        "geometry_revision": geometry_revision, "mode": mode,
        "expires_at_monotonic_ms": expires_at_monotonic_ms,
        "primitives": mapped, "input_privileges": [], "hit_test_visible": False,
    }


def render_overlay(ticket, current, *, now_monotonic_ms):
    _exact(current, ("observation_id", "source_id", "source_revision",
                     "capture_epoch", "geometry_revision", "mode"), "current state")
    now = _number(now_monotonic_ms, "now_monotonic_ms")
    if now >= ticket.get("expires_at_monotonic_ms", -1):
        return {"status": "SUPPRESSED", "reason": "OVERLAY_EXPIRED", "primitives": []}
    for field in ("observation_id", "source_id", "source_revision",
                  "capture_epoch", "geometry_revision", "mode"):
        if ticket.get(field) != current[field]:
            return {"status": "SUPPRESSED", "reason": f"STALE_{field.upper()}",
                    "primitives": []}
    if ticket.get("input_privileges") != [] or ticket.get("hit_test_visible") is not False:
        return {"status": "SUPPRESSED", "reason": "OVERLAY_INPUT_DENIED",
                "primitives": []}
    return {"status": "RENDER", "reason": "CURRENT_BINDING",
            "primitives": ticket["primitives"], "input_privileges": []}


def exclude_overlay_layers(layer_ids, overlay_layer_ids):
    if (not isinstance(layer_ids, list) or not isinstance(overlay_layer_ids, list)
            or len(layer_ids) > 256 or len(overlay_layer_ids) > 64):
        raise GroundingRefused("INVALID_GROUNDING", "layer list")
    layers = [_ident(value, "layer_id") for value in layer_ids]
    overlays = set(_ident(value, "overlay_layer_id") for value in overlay_layer_ids)
    return {"application_layers": [value for value in layers if value not in overlays],
            "excluded_overlay_layers": [value for value in layers if value in overlays],
            "overlay_content_is_application_evidence": False}
