"""Versioned print-quality knowledge and explicit experiments, not magic presets."""
RESEARCH_DATE = "2026-10-24"
SOURCES = [
    {"title":"Snapmaker U1 multi-color guide","url":"https://wiki.snapmaker.com/en/snapmaker_u1/printing_guides/multi-color_printing_guide",
     "findings":["Prime towers stabilize resumed extrusion; retain native defaults until results justify changes.","Check the mapping against loaded filament. Three or more walls can reduce dark infill showing through light surfaces.","Calibration and PEI cleanliness affect results independently of slicer estimates."]},
    {"title":"Snapmaker PLA/PETG support guide","url":"https://wiki.snapmaker.com/en/snapmaker_u1/printing_guides/pla_and_petg",
     "findings":["Different-material support interfaces have different contact requirements. Zero-gap PLA/PETG guidance is not a same-material PLA recipe."]},
    {"title":"OrcaSlicer advanced support settings","url":"https://github.com/OrcaSlicer/OrcaSlicer/wiki/support_settings_advanced",
     "findings":["Z gaps can round to layer-height multiples. Verify the installed version and emitted settings.","Denser or thicker interfaces improve underside support but can be harder to remove. Zero interface spacing means a solid interface.","Newer upstream options are not automatically available in the installed Snapmaker fork."]},
    {"title":"Snapmaker U1 FAQ","url":"https://wiki.snapmaker.com/en/FAQ/u1",
     "findings":["The documented U1 layer-height range is 0.08 to 0.24 mm."]},
]


def quality_candidates(priority="finish", supports=False, multicolor=False):
    if priority not in {"finish","premium"}:raise ValueError("Choose finish or premium")
    common={"wall_loops":3,"sparse_infill_density":15,"sparse_infill_pattern":"gyroid",
            "outer_wall_speed":45,"top_surface_speed":30,"flush_into_infill":False}
    if multicolor:common["enable_prime_tower"]=True
    if supports:
        common.update(enable_support=True,support_type="tree(auto)",support_top_z_distance=.24,
                      support_bottom_z_distance=.24,support_object_xy_distance=.35,
                      support_interface_top_layers=3,support_interface_spacing=.3)
    heights=(.08,.12) if priority=="premium" else (.12,.16)
    variants=[{"name":f"{priority.title()} finish · {h:.2f} mm", "changes":common|{"layer_height":h,
               "top_shell_layers":round(.72/h),"bottom_shell_layers":round(.72/h)}} for h in heights]
    if supports:
        h=heights[-1]
        variants.append({"name":f"Support removal comparison · {h:.2f} mm", "changes":variants[-1]["changes"]|{
            "support_interface_top_layers":2,"support_interface_spacing":.4}})
    return {"priority":priority,"variants":variants,"research_date":RESEARCH_DATE,"sources":SOURCES,
            "evidence":"Candidate numbers are local test hypotheses, not universal manufacturer recommendations.",
            "review":["Verify reference/model fidelity before printing a replica.","Inspect orientation, thin features and support contacts on visible surfaces.",
                      "Compare emitted G-code, actual tool use, estimates and warnings. Preserve native temperature, motion limits and priming volumes.",
                      "All-PLA inventory does not qualify for different-material zero-gap interfaces.",
                      "Slicer success does not validate adhesion, color accuracy, finish or easy support removal. Record physical observations separately."]}


def review_emitted(plate, require_multicolor=False):
    settings=plate.get("effective_settings",{});tools=plate.get("tools_zero_based",[])
    errors=[];warnings=[]
    if plate.get("printer_model")!="Snapmaker U1":errors.append("Unexpected printer profile")
    if not tools or any(t not in range(4) for t in tools):errors.append("Invalid emitted tools")
    try:
        if not .08<=float(settings.get("layer_height",0))<=.24:errors.append("Layer height outside the documented U1 range")
    except (TypeError,ValueError):errors.append("Missing layer height")
    if require_multicolor and len(tools)<2:errors.append("Expected color parts were not emitted")
    if len(tools)>1 and str(settings.get("enable_prime_tower")) not in {"1","True","true"}:errors.append("Multi-color prime tower is disabled")
    if len(tools)>1 and not any("prime" in k.lower() or "wipe tower" in k.lower() for k in plate.get("extrusion_moves_by_feature",{})):errors.append("No prime tower extrusion was found")
    if str(settings.get("flush_into_infill")) in {"1","True","true"}:warnings.append("Infill flushing may show through white or translucent surfaces")
    if str(settings.get("enable_support")) in {"1","True","true"}:
        warnings.append("Support removal and underside finish require physical inspection; inspect contact locations")
    return {"passed":not errors,"errors":errors,"warnings":warnings,"physical_quality_verified":False}
