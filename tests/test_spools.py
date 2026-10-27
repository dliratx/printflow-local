import math
import pytest
from printflow.spools import SpoolLedger

def status(mm,tool=0,filename="part.gcode"):
    return {"id":"u1","connected":True,"filename":filename,"state":"printing","filament_used_mm":mm,"active_tool_index":tool}

def register(ledger,tool=0,current=None):
    return ledger.register({"printer_id":"u1","tool_index":tool,"label":"Test PLA 1 kg","starting_mass_g":1000,"material":"PLA","diameter_mm":1.75,"density_g_cm3":1.24},current)

def test_mass_conversion_and_no_historical_debit(tmp_path):
    ledger=SpoolLedger(tmp_path/"spools.json")
    spool=register(ledger,current=status(5000))
    assert spool["remaining_mass_g"]==1000
    ledger.observe(status(6000))
    expected=math.pi*(1.75/2)**2*1.24
    assert spool["estimated_used_g"]==pytest.approx(expected)
    assert spool["remaining_mass_g"]==pytest.approx(1000-expected)
    assert spool["uncertain_usage_g"]==0

def test_tool_switch_is_split_and_marked_uncertain(tmp_path):
    ledger=SpoolLedger(tmp_path/"spools.json")
    a=register(ledger,0,status(0)); b=register(ledger,1,status(0))
    ledger.observe(status(1000,1))
    assert a["estimated_used_g"]==pytest.approx(b["estimated_used_g"])
    assert a["uncertain_usage_g"]==a["estimated_used_g"]
    assert b["uncertain_usage_g"]==b["estimated_used_g"]

def test_job_change_and_counter_reset_do_not_double_count(tmp_path):
    ledger=SpoolLedger(tmp_path/"spools.json"); spool=register(ledger,current=status(5000))
    ledger.observe(status(10000,filename="another.gcode"))
    ledger.observe(status(0,filename="another.gcode"))
    assert spool["remaining_mass_g"]==1000
    ledger.observe(status(100,filename="another.gcode"))
    assert spool["remaining_mass_g"]<1000

def test_weighing_replaces_estimate_and_reassignment_unloads_old_spool(tmp_path):
    ledger=SpoolLedger(tmp_path/"spools.json"); old=register(ledger,current=status(0))
    ledger.weigh(old["id"],625)
    assert old["remaining_mass_g"]==625
    new=register(ledger,current=status(0))
    assert not old["active"] and ledger.active_for("u1",0)["id"]==new["id"]
    reloaded=SpoolLedger(tmp_path/"spools.json")
    assert reloaded.active_for("u1",0)["remaining_mass_g"]==1000

def test_nonfinite_mass_rejected(tmp_path):
    ledger=SpoolLedger(tmp_path/"spools.json")
    with pytest.raises(ValueError): ledger.register({"printer_id":"u1","tool_index":0,"starting_mass_g":float("nan")})
