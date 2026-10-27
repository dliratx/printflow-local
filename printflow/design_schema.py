"""Portable design contracts shared by the web API and the isolated CAD worker."""
from __future__ import annotations
import math
import re


def parameter(default, minimum, maximum, label):
    return {"default": default, "min": minimum, "max": maximum, "label": label}


TEMPLATES = [
    {"id": "roadster_2026", "label": "Roadster 2026 display miniature", "parameters": {
        "length": parameter(180, 140, 220, "Length (mm)")}},
    {"id": "box", "label": "Open storage box", "parameters": {
        "width": parameter(100, 15, 500, "Width (mm)"),
        "depth": parameter(70, 15, 500, "Depth (mm)"),
        "height": parameter(40, 10, 500, "Height (mm)"),
        "wall": parameter(2, 1.2, 12, "Wall / base thickness (mm)")}},
    {"id": "table", "label": "Modular display table · prototype", "parameters": {
        "width": parameter(180, 80, 600, "Width (mm)"),
        "depth": parameter(140, 80, 600, "Depth (mm)"),
        "height": parameter(120, 40, 600, "Height (mm)"),
        "top_thickness": parameter(12, 8, 30, "Top thickness (mm)"),
        "leg_width": parameter(20, 12, 50, "Leg width (mm)")}},
    {"id": "spacer", "label": "Round spacer / washer", "parameters": {
        "outer_diameter": parameter(20, 4, 200, "Outside diameter (mm)"),
        "inner_diameter": parameter(6.4, 1, 190, "Hole diameter (mm)"),
        "height": parameter(10, 1, 250, "Height (mm)")}},
]

U1 = {"build_volume": [270, 270, 270], "color_system": "independent_tools", "max_colors": 4}


def validate_request(body, printer):
    if not isinstance(body, dict):
        raise ValueError("A design request must be an object")
    spec = next((t for t in TEMPLATES if t["id"] == body.get("template")), None)
    if not spec:
        raise ValueError("Choose an available parametric template")
    supplied = body.get("parameters", {})
    if not isinstance(supplied, dict) or set(supplied) - set(spec["parameters"]):
        raise ValueError("Unknown design parameter")
    params = {}
    for key, field in spec["parameters"].items():
        value = float(supplied.get(key, field["default"]))
        if not math.isfinite(value) or not field["min"] <= value <= field["max"]:
            raise ValueError(f'{field["label"]}: use {field["min"]}–{field["max"]}')
        params[key] = value
    if spec["id"] == "box" and params["wall"] * 2 >= min(params["width"], params["depth"], params["height"]):
        raise ValueError("The walls must leave a usable interior")
    if spec["id"] == "spacer" and params["inner_diameter"] > params["outer_diameter"] - 2.4:
        raise ValueError("The spacer needs at least 1.2 mm of material around the hole")
    if spec["id"] == "table" and (params["height"] < params["top_thickness"] + 20 or params["leg_width"] * 3 > min(params["width"], params["depth"])):
        raise ValueError("The table needs room for four legs and their connectors")
    mode = body.get("color_mode", "single")
    if mode not in {"single", "separate_parts", "multi_tool", "ams"}:
        raise ValueError("Choose a supported color strategy")
    system = printer.get("color_system", "single")
    if mode == "ams" and system != "ams":
        raise ValueError("This printer does not use AMS. Choose independent tools or separate parts")
    if mode == "multi_tool" and system != "independent_tools":
        raise ValueError("This printer does not have independent color tools")
    colors = body.get("colors") or ["#92A9CB"]
    if not isinstance(colors, list) or not 1 <= len(colors) <= 16 or any(not re.fullmatch(r"#[0-9a-fA-F]{6}", str(c)) for c in colors):
        raise ValueError("Use one to sixteen hexadecimal colors")
    if mode == "single":
        colors = colors[:1]
    if mode in {"multi_tool", "ams"} and len(colors) > printer["max_colors"]:
        raise ValueError(f'This printer supports {printer["max_colors"]} simultaneous colors')
    if spec["id"] == "roadster_2026" and (mode!="multi_tool" or len(colors)!=3):
        raise ValueError("The Roadster assembly needs independent tools and three colors: trim, rear lightbar, then body")
    usage = body.get("usage") or {}
    if not isinstance(usage, dict) or any(not isinstance(v, bool) for k, v in usage.items() if k in {"outdoor", "flexible", "heat", "loaded"}):
        raise ValueError("Usage selections must be true or false")
    return {"name": str(body.get("name") or spec["label"])[:100], "template": spec["id"], "parameters": params,
            "printer_id": printer["id"], "printer": printer, "color_mode": mode, "colors": colors,
            "usage": {k: usage.get(k, False) for k in ("outdoor", "flexible", "heat", "loaded")},
            "revision_of": body.get("revision_of")}


def material_advice(request):
    usage = request["usage"]
    material, reason = "PLA", "Good starting point for indoor decorative parts and dimension checks."
    questions = []
    if usage["loaded"]:
        material, reason = "PETG", "Consider PETG for a tougher functional prototype; layer direction and creep still matter."
        questions.append("What load, load direction and service life must the part withstand?")
    if usage["outdoor"]:
        material, reason = "ASA", "Consider ASA for UV exposure only after checking the printer enclosure, ventilation and material profile."
    if usage["heat"]:
        questions.append("What is the highest operating temperature? Check the specific filament datasheet before choosing a material.")
    if usage["flexible"]:
        material, reason = "TPU", "Consider TPU for flexible grips or feet; choose its hardness for the intended deflection."
        if request["template"] in {"table", "spacer"}:
            questions.append("Does the whole part need to flex? Keep rigid load-bearing parts separate from flexible pads.")
    if request["template"] == "table":
        questions.append("This is an assembly/fit prototype, not a load-rated piece of furniture. Test the joints before applying load.")
    return {"material": material, "reason": reason, "questions": questions,
            "note": "A recommendation is not loaded inventory. Confirm the actual brand, material and spool before slicing.",
            "sources": ["https://help.prusa3d.com/article/petg_2059", "https://help.prusa3d.com/article/flexible-materials_2057"]}
