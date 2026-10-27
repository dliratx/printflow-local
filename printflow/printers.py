"""Printer adapter contract and Snapmaker U1 Moonraker implementation."""
from __future__ import annotations
from abc import ABC, abstractmethod
import asyncio
import hashlib
import ipaddress
import json
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
import httpx
from websockets.asyncio.client import connect
from .common import now

def normalize_host(value):
    value=value.strip().rstrip("/")
    if "://" not in value: value="http://"+value+(":7125" if ":" not in value else "")
    parsed=urlparse(value)
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"","/"}: raise ValueError("Use a LAN printer URL without credentials or a path")
    try:
        address=ipaddress.ip_address(parsed.hostname)
        if not address.is_private or address.is_loopback or address.is_link_local: raise ValueError("The printer must use a local network address")
    except ValueError as exc:
        if not parsed.hostname.endswith(".local"): raise ValueError("Use a private IP address or a .local hostname") from exc
    return value

class PrinterAdapter(ABC):
    @abstractmethod
    async def status(self): pass
    @abstractmethod
    async def camera(self): pass
    @abstractmethod
    async def print_file(self,data:bytes,filename:str,mapping:dict): pass

class SnapmakerU1(PrinterAdapter):
    kind="snapmaker_u1"
    def __init__(self,config):
        self.config=config; self.url=normalize_host(config["host"])
        headers={"X-Api-Key":config["api_key"]} if config.get("api_key") else {}
        self.http=httpx.AsyncClient(base_url=self.url,headers=headers,timeout=6,trust_env=False)
        self.details={}; self.last_details=0; self.lock=asyncio.Lock()
        self.camera_lock=asyncio.Lock(); self.last_camera_start=0
        self.camera_socket=None; self.camera_reader=None; self.camera_last_request=0
    async def get(self,path):
        r=await self.http.get(path); r.raise_for_status(); return r.json().get("result",{})
    async def status(self):
        base={"id":self.config["id"],"name":self.config["name"],"kind":self.kind,"host":self.url,"camera_url":f'/api/printers/{self.config["id"]}/camera.jpg',"updated_at":now()}
        try:
            query="print_task_config&print_stats&display_status&virtual_sdcard&heater_bed&extruder&extruder1&extruder2&extruder3&toolhead&webhooks&gcode_move&fan&motion_report&systemload&idle_timeout&pause_resume&heaters"
            result=await self.get("/printer/objects/query?"+query); raw=result.get("status",{})
            stats=raw.get("print_stats",{}); tasks=raw.get("print_task_config",{}); hooks=raw.get("webhooks",{})
            state=stats.get("state","unknown")
            if hooks.get("state") not in {None,"ready"}: state=hooks["state"]
            def at(key,i,default=None):
                items=tasks.get(key,[]); return items[i] if len(items)>i else default
            filament=[{"slot":i+1,"material":at("filament_type",i),"brand":at("filament_vendor",i),"series":at("filament_sub_type",i),"color":"#"+str(at("filament_color_rgba",i,"808080"))[:6],"loaded":at("filament_exist",i,False),"nozzle_diameter":raw.get("extruder"+(str(i) if i else ""),{}).get("nozzle_diameter"),"nozzle_flow":raw.get("extruder"+(str(i) if i else ""),{}).get("nozzle_volume_type")} for i in range(4)]
            progress=raw.get("display_status",{}).get("progress")
            duration=stats.get("print_duration",0)
            active_name=raw.get("toolhead",{}).get("extruder")
            active_index=(int(active_name[8:]) if active_name and active_name[8:].isdigit() else 0) if active_name else None
            active_stats=raw.get(active_name,{}) if active_name else {}
            active_filament=filament[active_index] if active_index in range(4) else {}
            base.update(active_tool_index=active_index,active_nozzle={"index":active_index,"tool":active_name,"diameter":active_stats.get("nozzle_diameter"),"material":active_filament.get("material"),"color":active_filament.get("color"),"state":active_stats.get("state")},homed_axes=raw.get("toolhead",{}).get("homed_axes"))
            if asyncio.get_running_loop().time()-self.last_details>120:
                try:
                    info,machine,server=await asyncio.gather(self.get("/printer/info"),self.get("/machine/system_info"),self.get("/server/info"))
                    self.details={"printer_info":info,"machine":machine,"server":server}; self.last_details=asyncio.get_running_loop().time()
                except (httpx.HTTPError,ValueError): pass
            return base|{"connected":True,"state":state,"filename":stats.get("filename"),"progress":progress,"sd_progress":raw.get("virtual_sdcard",{}).get("progress"),"print_duration":duration,"total_duration":stats.get("total_duration"),"eta_seconds":round(duration*(1-progress)/progress) if progress and progress>.01 else None,"filament_used_mm":stats.get("filament_used"),"layers":stats.get("info"),"active_tool":raw.get("toolhead",{}).get("extruder"),"position":raw.get("toolhead",{}).get("position"),"temperatures":{"bed":{"current":raw.get("heater_bed",{}).get("temperature"),"target":raw.get("heater_bed",{}).get("target")},"tools":[{"index":i,"current":raw.get("extruder"+(str(i) if i else ""),{}).get("temperature"),"target":raw.get("extruder"+(str(i) if i else ""),{}).get("target")} for i in range(4)]},"filaments":filament,"raw":raw,"details":self.details,"firmware_version":self.details.get("printer_info",{}).get("software_version"),"status_message":stats.get("message") or hooks.get("state_message") or "","capabilities":{"status":True,"camera":True,"upload":True,"start":True,"pause":True,"resume":True,"cancel":True}}
        except Exception as exc: return base|{"connected":False,"state":"offline","status_message":str(exc),"filaments":[],"temperatures":{"bed":{},"tools":[]},"raw":{}}
    async def camera(self):
        self.camera_last_request=time.monotonic()
        async with self.camera_lock:
            if self.camera_socket is None:
                if time.monotonic()-self.last_camera_start<5: raise ValueError("Camera is reconnecting")
                self.last_camera_start=time.monotonic()
                endpoint=self.url.replace("http://","ws://",1).replace("https://","wss://",1)+"/websocket"
                ws=await connect(endpoint,additional_headers=dict(self.http.headers),proxy=None,open_timeout=5,close_timeout=2)
                try:
                    await ws.send(json.dumps({"jsonrpc":"2.0","id":1,"method":"camera.start_monitor","params":{"domain":"lan","interval":0}}))
                    while True:
                        reply=json.loads(await asyncio.wait_for(ws.recv(),5))
                        if reply.get("id")==1:
                            if "error" in reply: raise ValueError(str(reply["error"]))
                            break
                except Exception:
                    await ws.close(); raise
                self.camera_socket=ws
                self.camera_reader=asyncio.create_task(self.watch_camera_socket(ws))
                await asyncio.sleep(1.2)
        r=await self.http.get("/server/files/camera/monitor.jpg",params={"_":now()},timeout=5)
        r.raise_for_status()
        if not r.headers.get("content-type","").startswith("image/"): raise ValueError("The camera did not return an image")
        modified=r.headers.get("last-modified")
        if modified and time.time()-parsedate_to_datetime(modified).timestamp()>20:
            # A LAN interruption can leave the monitor subscribed without new
            # frames. Re-subscribe on the next request instead of staying stuck.
            async with self.camera_lock:
                ws=self.camera_socket
                self.camera_socket=None
                if ws is not None: await ws.close()
            raise ValueError("The camera is returning an outdated snapshot")
        return r.content,r.headers.get("content-type","image/jpeg")
    async def watch_camera_socket(self,ws):
        try:
            while time.monotonic()-self.camera_last_request<60:
                try: await asyncio.wait_for(ws.recv(),10)
                except TimeoutError: pass
        except Exception: pass
        finally:
            if self.camera_socket is ws: self.camera_socket=None
            await ws.close()
    async def require_idle(self):
        status=await self.status()
        if not status["connected"] or status["state"] not in {"standby","complete","cancelled","error"}: raise ValueError(f'The U1 is currently {status["state"]}; another job will not be started')
        if status.get("raw",{}).get("webhooks",{}).get("state")!="ready": raise ValueError("The printer controller is not ready")
        return status
    async def post(self,path,**kwargs):
        # Physical mutations must never be automatically retried.
        r=await self.http.post(path,**kwargs); r.raise_for_status(); return r.json()
    async def print_file(self,data,filename,mapping):
        async with self.lock:
            status=await self.require_idle()
            for logical,physical in mapping.items():
                if not 0<=int(logical)<=3 or not 0<=int(physical)<=3: raise ValueError("Tool number is outside the U1 range")
                if not status["filaments"][int(physical)]["loaded"]: raise ValueError(f"No filament loaded in tool {int(physical)+1}")
            upload=await self.post("/server/files/upload",data={"root":"gcodes","checksum":hashlib.sha256(data).hexdigest()},files={"file":(filename,data,"application/octet-stream")},timeout=90)
            # Another controller may have started a job during upload.
            await self.require_idle()
            commands=[f"SET_PRINT_EXTRUDER_MAP CONFIG_EXTRUDER={int(a)} MAP_EXTRUDER={int(b)}" for a,b in mapping.items()]
            commands.append("SET_PRINT_USED_EXTRUDERS EXTRUDERS="+",".join(str(int(x)) for x in sorted(set(mapping.values()))))
            await self.post("/printer/gcode/script",params={"script":"\n".join(commands)})
            started=await self.post("/printer/print/start",params={"filename":filename})
            return {"upload":upload,"start":started,"filename":filename,"mapping":mapping,"outcome":"start_request_accepted; verify live printer state"}
    async def action(self,name):
        if name not in {"pause","resume","cancel"}: raise ValueError("Unknown action")
        async with self.lock:
            status=await self.status()
            if name=="pause" and status["state"]!="printing": raise ValueError("The printer is not printing")
            if name=="resume" and status["state"]!="paused": raise ValueError("The printer is not paused")
            if name=="cancel" and status["state"] not in {"printing","paused"}: raise ValueError("No active print job")
            return await self.post("/printer/print/"+name)
    async def close(self):
        if self.camera_reader:
            self.camera_reader.cancel()
            await asyncio.gather(self.camera_reader,return_exceptions=True)
        if self.camera_socket: await self.camera_socket.close()
        await self.http.aclose()

ADAPTERS={"snapmaker_u1":SnapmakerU1}
# Future Flashforge adapters implement the same contract, with model-specific
# authentication, upload formats and capability flags. No false support claim.
