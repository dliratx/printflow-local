"""Local spool bookkeeping from reported extrusion length, with visible uncertainty."""
from __future__ import annotations
import math
import time
import uuid
from pathlib import Path
from .common import DATA,now,read_json,save_json

class SpoolLedger:
    def __init__(self,path:Path|None=None):
        self.path=path or DATA/"spools.json"
        data=read_json(self.path,{})
        self.spools=data.get("spools",[]); self.baselines=data.get("baselines",{})
        self.last_saved=0
    def save(self):
        save_json(self.path,{"spools":self.spools,"baselines":self.baselines}); self.last_saved=time.monotonic()
    def register(self,body,status=None):
        mass=float(body.get("starting_mass_g",1000)); density=float(body.get("density_g_cm3",1.24)); diameter=float(body.get("diameter_mm",1.75))
        if not all(math.isfinite(x) for x in (mass,density,diameter)) or not 0<mass<=10000 or not .5<=density<=5 or not 1<=diameter<=3.5: raise ValueError("Check spool weight, density and filament diameter")
        slot=int(body["tool_index"])
        if slot not in range(4): raise ValueError("Tool index must be 0-3")
        pid=body["printer_id"]
        for spool in self.spools:
            if spool.get("printer_id")==pid and spool.get("tool_index")==slot and spool.get("active"):
                spool.update(active=False,unloaded_at=now())
        record={"id":uuid.uuid4().hex[:12],"label":str(body.get("label") or "New spool")[:100],"printer_id":pid,"tool_index":slot,"material":str(body.get("material","PLA"))[:30],"brand":str(body.get("brand",""))[:60],"starting_mass_g":mass,"remaining_mass_g":mass,"estimated_used_g":0.,"uncertain_usage_g":0.,"density_g_cm3":density,"diameter_mm":diameter,"active":True,"registered_at":now(),"basis":"User-entered starting filament mass; spool tare excluded","print_usage":{}}
        self.spools.append(record)
        if status: self.set_baseline(status)
        self.save(); return record
    def weigh(self,spool_id,mass):
        spool=next((s for s in self.spools if s["id"]==spool_id),None)
        if not spool: raise ValueError("Spool not found")
        mass=float(mass)
        if not math.isfinite(mass) or not 0<=mass<=spool["starting_mass_g"]: raise ValueError("Enter net remaining filament weight between zero and the initial weight")
        spool.update(remaining_mass_g=mass,basis="Corrected from a user-entered net filament weight",last_weighed_at=now())
        self.save(); return spool
    def set_baseline(self,status):
        self.baselines[status["id"]]={"filename":status.get("filename"),"mm":float(status.get("filament_used_mm") or 0),"tool":status.get("active_tool_index"),"time":time.time(),"state":status.get("state")}
    def observe(self,status):
        if not status.get("connected"): return
        previous=self.baselines.get(status["id"])
        self.set_baseline(status)
        current=self.baselines[status["id"]]
        if not previous or not current["filename"] or previous["filename"]!=current["filename"]: return
        delta=current["mm"]-previous["mm"]; elapsed=max(0,current["time"]-previous["time"])
        if delta<=0 or delta>1000+elapsed*1000: return
        if previous.get("state")!="printing" and current["state"]!="printing": return
        a,b=previous.get("tool"),current.get("tool")
        if b is None: return
        split=a is not None and a!=b
        allocations=[(a,.5),(b,.5)] if split else [(b,1.)]
        for tool,fraction in allocations:
            spool=next((s for s in self.spools if s.get("active") and s["printer_id"]==status["id"] and s["tool_index"]==tool),None)
            if not spool: continue
            grams=delta*fraction*math.pi*(spool["diameter_mm"]/2)**2*spool["density_g_cm3"]/1000
            spool["estimated_used_g"]+=grams
            spool["remaining_mass_g"]=max(0,spool["remaining_mass_g"]-grams)
            if split or elapsed>30: spool["uncertain_usage_g"]+=grams
            usage=spool["print_usage"]
            usage[current["filename"]]=round(usage.get(current["filename"],0)+grams,4)
            spool["last_usage_at"]=now()
        if time.monotonic()-self.last_saved>15: self.save()
    def active_for(self,printer_id,tool):
        return next((s for s in self.spools if s.get("active") and s["printer_id"]==printer_id and s["tool_index"]==tool),None)
    def summary(self):
        return {"spools":self.spools,"formula":"grams = length_mm × π × (diameter_mm / 2)² × density_g_cm³ / 1000","tracking_note":"Tracking starts at registration. Tool-switch intervals are split between adjacent tools and marked uncertain. Length is reported by firmware; weighing net filament gives a better remaining-weight correction."}
