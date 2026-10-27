import pytest
from printflow.quality import quality_candidates, review_emitted


def test_premium_is_a_comparison_not_a_temperature_or_firmware_override():
    plan=quality_candidates("premium",True,True)
    assert {v["changes"]["layer_height"] for v in plan["variants"]}=={.08,.12}
    for variant in plan["variants"]:
        changes=variant["changes"]
        assert changes["support_top_z_distance"]>0
        assert changes["enable_prime_tower"] is True
        assert changes["flush_into_infill"] is False
        assert not any("temperature" in k or "gcode" in k or "prime_volume" in k for k in changes)


def test_review_rejects_missing_color_and_missing_prime_tower():
    p={"printer_model":"Snapmaker U1","tools_zero_based":[0],"effective_settings":{"layer_height":"0.12"}}
    assert not review_emitted(p,True)["passed"]
    p["tools_zero_based"]=[0,1]
    assert not review_emitted(p,True)["passed"]
    p["effective_settings"]["enable_prime_tower"]="1"
    p["extrusion_moves_by_feature"]={"Prime tower":10}
    assert review_emitted(p,True)["passed"]
    assert not review_emitted(p,True)["physical_quality_verified"]


def test_rejects_unknown_quality_priority():
    with pytest.raises(ValueError):quality_candidates("magic")
