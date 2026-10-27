import asyncio
import json
import httpx
import pytest
import time
from email.utils import formatdate
from printflow.printers import SnapmakerU1,normalize_host
from printflow.api import parse_toolpaths,app

def test_printer_hosts_are_lan_only():
    assert normalize_host("192.168.1.20")=="http://192.168.1.20:7125"
    for host in ["https://example.com","http://127.0.0.1:8841","http://8.8.8.8:80","http://user:pass@192.168.1.2:7125","http://192.168.1.2:7125/admin"]:
        with pytest.raises(ValueError): normalize_host(host)

def test_active_print_blocks_all_mutations():
    async def run():
        adapter=SnapmakerU1({"id":"test","name":"Test","host":"192.168.1.20"})
        calls=[]
        async def status(): return {"connected":True,"state":"printing","raw":{"webhooks":{"state":"ready"}}}
        async def post(*args,**kwargs): calls.append(args)
        adapter.status=status; adapter.post=post
        with pytest.raises(ValueError): await adapter.print_file(b"gcode","test.gcode",{0:0})
        assert calls==[]
        await adapter.close()
    asyncio.run(run())

def test_idle_print_has_explicit_upload_mapping_then_start():
    async def run():
        adapter=SnapmakerU1({"id":"test","name":"Test","host":"192.168.1.20"})
        calls=[]; checks=[]
        async def status():
            checks.append(True)
            return {"connected":True,"state":"standby","raw":{"webhooks":{"state":"ready"}},"filaments":[{"loaded":True} for _ in range(4)]}
        async def post(path,**kwargs): calls.append((path,kwargs)); return {"result":"ok"}
        adapter.status=status; adapter.post=post
        await adapter.print_file(b"G1 X1 Y1 E1","test.gcode",{0:1,1:0})
        assert len(checks)==2
        assert [p for p,_ in calls]==["/server/files/upload","/printer/gcode/script","/printer/print/start"]
        assert "print" not in calls[0][1]["data"]
        assert "CONFIG_EXTRUDER=0 MAP_EXTRUDER=1" in calls[1][1]["params"]["script"]
        await adapter.close()
    asyncio.run(run())

def test_job_start_race_after_upload_does_not_change_mapping():
    async def run():
        adapter=SnapmakerU1({"id":"test","name":"Test","host":"192.168.1.20"}); calls=[]; n=0
        async def status():
            nonlocal n
            n+=1
            return {"connected":True,"state":"standby" if n==1 else "printing","raw":{"webhooks":{"state":"ready"}},"filaments":[{"loaded":True} for _ in range(4)]}
        async def post(path,**kwargs): calls.append(path); return {}
        adapter.status=status; adapter.post=post
        with pytest.raises(ValueError): await adapter.print_file(b"Gcode","test.gcode",{0:0})
        assert calls==["/server/files/upload"]
        await adapter.close()
    asyncio.run(run())

def test_toolpaths_are_from_extrusion_and_not_travel():
    value=parse_toolpaths("M83\n;TYPE:Outer wall\nG1 X10 Y10 Z0.2\nG1 X20 Y10 E1\n;TYPE:Support\nG1 X20 Y20 E1\nG1 X50 Y50\nT1\nG1 X60 Y50 Z0.4 E1")
    assert [x["z"] for x in value["layers"]]==[.2,.4]
    assert len(value["layers"][0]["segments"])==2
    assert value["layers"][0]["segments"][1][4]=="Support"
    assert value["layers"][1]["segments"][0][5]==1


def test_native_orca_decimal_extrusion_without_leading_zero():
    # Actual Snapmaker Orca output uses E.30421 and Z.2.
    value=parse_toolpaths("M83\n;TYPE:Inner wall\nG1 X131.357 Y131.857 Z.2\nG1 X139.643 Y131.857 E.30421\nG1 X139.643 Y140.103 E.30274\nG1 X138.1 Y140.569 E-1.2")
    assert len(value["layers"])==1
    assert value["layers"][0]["z"]==.2
    assert len(value["layers"][0]["segments"])==2

def test_cross_origin_mutations_rejected_before_any_printer_action():
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://localhost") as client:
            response=await client.post("/api/printers/u1/pause")
            assert response.status_code==403
            response=await client.post("/api/printers/u1/pause",headers={"X-PrintFlow":"local","Origin":"https://untrusted.example"})
            assert response.status_code==403
    asyncio.run(run())


def test_camera_keeps_monitor_connection_across_frames(monkeypatch):
    class Socket:
        def __init__(self): self.replies=[{"method":"notify_camera_status_change"},{"id":1,"result":{}}]; self.closed=False; self.sent=[]
        async def send(self,value): self.sent.append(json.loads(value))
        async def recv(self):
            if self.replies: return json.dumps(self.replies.pop(0))
            await asyncio.Future()
        async def close(self): self.closed=True
    async def run():
        adapter=SnapmakerU1({"id":"test","name":"Test","host":"192.168.1.20"})
        socket=Socket(); connections=[]; frames=[]
        async def connect(*args,**kwargs): connections.append(args); return socket
        def snapshot(request):
            frames.append(True)
            return httpx.Response(200,content=f"frame-{len(frames)}".encode(),headers={"content-type":"image/jpeg","last-modified":formatdate(time.time(),usegmt=True)})
        monkeypatch.setattr("printflow.printers.connect",connect)
        await adapter.http.aclose()
        adapter.http=httpx.AsyncClient(base_url=adapter.url,transport=httpx.MockTransport(snapshot))
        first=await adapter.camera(); second=await adapter.camera()
        assert first[0]!=second[0]
        assert len(connections)==1 and not socket.closed
        assert socket.sent[0]["method"]=="camera.start_monitor"
        await adapter.close()
        assert socket.closed
    asyncio.run(run())


def test_stale_camera_snapshot_forces_monitor_reconnection():
    class Socket:
        closed=False
        async def close(self): self.closed=True
    async def run():
        adapter=SnapmakerU1({"id":"test","name":"Test","host":"192.168.1.20"})
        socket=Socket(); adapter.camera_socket=socket
        await adapter.http.aclose()
        adapter.http=httpx.AsyncClient(base_url=adapter.url,transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b"old-frame",headers={"content-type":"image/jpeg","last-modified":formatdate(time.time()-90,usegmt=True)})))
        with pytest.raises(ValueError,match="outdated"):
            await adapter.camera()
        assert adapter.camera_socket is None and socket.closed
        await adapter.close()
    asyncio.run(run())
