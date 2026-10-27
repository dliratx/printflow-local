"""Authenticated host-only gateway for native MCP and signed-in Codex."""
from __future__ import annotations
import asyncio
from contextlib import AsyncExitStack,asynccontextmanager
import os
from pathlib import Path
import secrets
import subprocess
import sys
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import StreamingResponse,FileResponse
import psutil
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from .common import ROOT,Events,bridge_token
from .codex import CodexClient
from .discovery_search import discover

events=Events(); codex=CodexClient(events)
session=None; native_lock=asyncio.Lock()
TOKEN=bridge_token()
ORCA_BINARY=Path(os.environ.get("SNAPMAKER_ORCA_BIN",r"C:\Program Files\Snapmaker_Orca\snapmaker-orca.exe"))

@asynccontextmanager
async def lifespan(app):
    global session
    async with AsyncExitStack() as stack:
        streams=await stack.enter_async_context(stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/"u1_server.py")],cwd=str(ROOT))))
        session=await stack.enter_async_context(ClientSession(*streams))
        await session.initialize()
        await codex.start()
        yield
        await codex.close()

app=FastAPI(title="PrintFlow Windows Host",lifespan=lifespan)
@app.middleware("http")
async def authentication(request: Request,call_next):
    if not secrets.compare_digest(request.headers.get("X-PrintFlow-Token",""),TOKEN):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail":"Host gateway authentication required"},status_code=401)
    return await call_next(request)

def slicer_state():
    processes=[]
    for p in psutil.process_iter(["name","pid"]):
        if (p.info["name"] or "").lower()=="snapmaker-orca.exe": processes.append(p.info["pid"])
    return {"available":ORCA_BINARY.exists(),"process_running":bool(processes),"process_ids":processes,"control_mode":"native projects + MCP", "visible_control_available":False,"detail":"Independent native bridge. Opens real projects in Orca and shows slicing results in the web app. Unsaved GUI edits are not synchronized."}

@app.get("/status")
async def status(): return {"slicer":slicer_state(),"codex":codex.state,"chat":codex.messages[-60:]}
@app.get("/tools")
async def tools(): return {"tools":[t.model_dump(mode="json") for t in (await session.list_tools()).tools]}
@app.post('/discover')
async def discover_models(request:Request):
    from .marketplace import PROVIDERS,search_page
    body=await request.json();query=str(body.get('query','')).strip()[:160];provider=body.get('provider','all')
    if not query or (provider!='all' and provider not in PROVIDERS):raise HTTPException(400,'Choose a query and supported source')
    domains=[v['host'] for k,v in PROVIDERS.items() if provider=='all' or k==provider]
    try:
        page,exclude=search_page(body.get('page',1),body.get('exclude',[]))
        return await discover(query,domains,page,exclude)
    except ValueError as exc:raise HTTPException(503,str(exc))
@app.post("/tools/call")
async def tool_call(request:Request):
    body=await request.json()
    async with native_lock:
        response=await session.call_tool(body["name"],body.get("arguments",{}))
    if response.isError: raise HTTPException(400,str(response.content))
    import json
    return response.structuredContent if response.structuredContent is not None else json.loads(response.content[0].text)
@app.post("/open")
async def open_native(request:Request):
    body=await request.json()
    path=Path(body["path"])
    if not path.is_absolute() and body.get("base")=="models": path=ROOT/"models"/path
    path=path.resolve()
    allowed=[ROOT/"models",ROOT/"runs"]
    if not any(path.is_relative_to(p.resolve()) for p in allowed) or path.suffix.lower() not in {".3mf",".stl",".gcode"} or not path.is_file(): raise HTTPException(400,"Invalid project path")
    binary=ORCA_BINARY
    # Open-file CLI invocation of the existing application, never mouse automation.
    subprocess.Popen([str(binary),str(path)],cwd=str(binary.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    events.emit("slicer",{"action":"open","file":path.name})
    return {"opened":str(path),"note":"The file was sent to the native application; loading has not been verified"}
@app.get("/artifact")
async def artifact(path:str):
    p=Path(path).resolve()
    if not p.is_relative_to((ROOT/"runs").resolve()) or p.suffix.lower() not in {".3mf",".gcode"} or not p.is_file(): raise HTTPException(404)
    return FileResponse(p,filename=p.name)
@app.get('/print-image')
async def print_image(path:str):
    from .print_image import render
    p=Path(path).resolve()
    if not p.is_relative_to((ROOT/'runs').resolve()) or p.suffix.lower()!='.gcode' or not p.is_file():raise HTTPException(404)
    try:return FileResponse(await asyncio.to_thread(render,p),media_type='image/png')
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.get("/events")
async def event_stream(): return StreamingResponse(events.stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache"})
@app.post("/chat")
async def chat(request:Request):
    b=await request.json()
    try: return await codex.chat(b["message"],b.get("context",{}),b.get('image_paths'))
    except Exception as exc: raise HTTPException(400,str(exc))
@app.post("/chat/interrupt")
async def interrupt(): await codex.interrupt(); return {"ok":True}
@app.post("/chat/approval")
async def approval(request:Request):
    b=await request.json()
    try:return await codex.approve(b['id'],b.get('decision'),b.get('answers'))
    except ValueError as exc:raise HTTPException(400,str(exc))
@app.post('/chat/approval-policy')
async def approval_policy(request:Request):
    b=await request.json()
    try:return codex.set_approval_policy(b.get('policy'))
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post('/chat/model')
async def chat_model(request:Request):
    b=await request.json()
    try:return codex.set_model(b.get('model'),b.get('reasoning_effort'))
    except ValueError as exc:raise HTTPException(400,str(exc))
