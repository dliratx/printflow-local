"""Auditable parametric CAD; no generated or user-supplied code is executed."""
from __future__ import annotations
import json
import math
from pathlib import Path
import zipfile
from xml.sax.saxutils import escape


def generate(request, destination):
    import cadquery as cq
    from .design_schema import validate_request
    request = validate_request(request, request["printer"])
    if request["template"] == "roadster_2026":
        from .roadster_geometry import generate_roadster
        return generate_roadster(request, destination)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    p = request["parameters"]
    bed = [float(n) - 12 for n in request["printer"]["build_volume"]]
    if min(bed) < 40:
        raise ValueError("The build volume is too small for this template")
    parts, solids, notes = [], [], []

    def add(name, shape, quantity=1, group=0):
        value = shape.val()
        if not value.isValid() or value.Volume() <= 0:
            raise ValueError(f"Invalid solid generated: {name}")
        bb = value.BoundingBox()
        shape = shape.translate((-bb.xmin, -bb.ymin, -bb.zmin))
        dims = [bb.xlen, bb.ylen, bb.zlen]
        if any(d > limit + .01 for d, limit in zip(dims, bed)):
            raise ValueError(f"{name} is too large for the selected printer; reduce its dimensions")
        color = request["colors"][group % len(request["colors"])]
        filename = name + ".stl"
        cq.exporters.export(shape, str(destination / filename), tolerance=.05, angularTolerance=.15)
        parts.append({"name": name, "file": filename, "quantity": quantity, "dimensions": [round(d, 3) for d in dims], "color": color,
                      "planned_tool": group % len(request["colors"]) if request["color_mode"] in {"multi_tool", "ams"} else None})
        solids.append(shape.val())
        return shape

    if request["template"] == "box":
        w, d, h, wall = (p[k] for k in ("width", "depth", "height", "wall"))
        outer = cq.Workplane("XY").box(w, d, h, centered=(False, False, False))
        cavity = cq.Workplane("XY").box(w - 2*wall, d - 2*wall, h, centered=(False, False, False)).translate((wall, wall, wall))
        add("storage_box", outer.cut(cavity))
        notes.append("Print with the base on the bed and the open face up. No lid is included.")
    elif request["template"] == "spacer":
        add("spacer", cq.Workplane("XY").circle(p["outer_diameter"] / 2).circle(p["inner_diameter"] / 2).extrude(p["height"]))
        notes.append("Measure the printed hole and adjust its diameter for the required fit.")
    else:
        width, depth, height, thick, leg = (p[k] for k in ("width", "depth", "height", "top_thickness", "leg_width"))
        nx, ny = math.ceil(width / bed[0]), math.ceil(depth / bed[1])
        tw, td = width / nx, depth / ny
        if min(tw, td) < leg * 2.5:
            raise ValueError("The tile size leaves insufficient room for legs and seams")
        clearance = .3  # diametral allowance; validate with a real fit test
        pin_radius = min(2.5, thick / 5)
        pin_depth = min(10, leg / 2)
        hole_radius = pin_radius + clearance / 2
        seam_pins = 0
        for x in range(nx):
            for y in range(ny):
                shape = cq.Workplane("XY").box(tw, td, thick, centered=(False, False, False))
                # Top is printed upside-down: open blind leg sockets face upwards.
                for px, outerx in ((leg / 2 + 4, x == 0), (tw - leg / 2 - 4, x == nx-1)):
                    for py, outery in ((leg / 2 + 4, y == 0), (td - leg / 2 - 4, y == ny-1)):
                        if outerx and outery:
                            hole = cq.Workplane("XY").center(px, py).circle(hole_radius).extrude(thick / 2 + 1).translate((0, 0, thick / 2))
                            shape = shape.cut(hole)
                for side, present in ((0, x > 0), (tw, x < nx-1)):
                    if present:
                        for pos in (td / 3, td * 2 / 3):
                            hole = cq.Workplane("YZ").center(pos, thick/2).circle(hole_radius).extrude(pin_depth).translate((side if side == 0 else side-pin_depth, 0, 0))
                            shape = shape.cut(hole)
                        if side == tw: seam_pins += 2
                for side, present in ((0, y > 0), (td, y < ny-1)):
                    if present:
                        for pos in (tw / 3, tw * 2 / 3):
                            hole = cq.Workplane("XZ").center(pos, thick/2).circle(hole_radius).extrude(pin_depth).translate((0, side+pin_depth if side == 0 else side, 0))
                            shape = shape.cut(hole)
                        if side == td: seam_pins += 2
                add(f"top_{x+1}_{y+1}", shape, group=0)
        leg_height = height - thick
        sections = math.ceil(leg_height / bed[2])
        segment_height = leg_height / sections
        if segment_height < pin_depth*2 + 1:
            raise ValueError("Increase the table height to leave room for the leg joints")
        for section in range(sections):
            shape = cq.Workplane("XY").box(leg, leg, segment_height, centered=(True, True, False))
            # Last section plugs into the table; other sections join with loose dowels.
            shape = shape.cut(cq.Workplane("XY").circle(hole_radius).extrude(pin_depth + .5).translate((0, 0, segment_height-pin_depth)))
            if section > 0:
                shape = shape.cut(cq.Workplane("XY").circle(hole_radius).extrude(pin_depth + .5))
            add(f"leg_segment_{section+1}", shape, quantity=4, group=1)
        add("leg_join_pin", cq.Workplane("XY").circle(pin_radius).extrude(pin_depth*2-.5), quantity=max(4*(sections-1), 1), group=1) if sections > 1 else None
        add("top_leg_pin", cq.Workplane("XY").circle(pin_radius).extrude(pin_depth + thick/2 - .5), quantity=4, group=1)
        if seam_pins:
            add("top_seam_pin", cq.Workplane("XY").circle(pin_radius).extrude(pin_depth*2-.5), quantity=seam_pins)
        notes += ["Print each unique part in the listed quantity. Top tiles are oriented with their leg sockets facing up.",
                  "Dry-fit the 0.3 mm diametral-clearance dowels first. Bond the joints for a display prototype; dowels are not a load rating.",
                  "Tile seams use horizontal holes which may need bridge tuning or cleanup. No automatic strength validation is performed."]
    cq.exporters.export(cq.Compound.makeCompound(solids), str(destination / "model.step"))
    (destination / "parameters.json").write_text(json.dumps(request, indent=2), encoding="utf-8")
    (destination / "model.py").write_text('"""Regenerate this revision inside the matching PrintFlow source checkout."""\nimport json\nfrom pathlib import Path\nfrom printflow.design_geometry import generate\nroot = Path(__file__).resolve().parent\ngenerate(json.loads((root / "parameters.json").read_text()), root / "regenerated")\n', encoding="utf-8")
    manifest = {"parts": parts, "notes": notes, "engine": "CadQuery 2.8.0", "request": request,
                "color_note": "Colors and tool numbers are a preparation plan. STL geometry has no stored material assignments; review mapping before slicing."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
