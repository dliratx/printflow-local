"""Isolated CPU CAD service. HTTP callers never supply executable Python."""
import asyncio
import io
import os
from pathlib import Path
import secrets
import tempfile
import zipfile
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from .common import bridge_token
from .design_geometry import generate
from .design_schema import TEMPLATES

app = FastAPI(title="PrintFlow CAD", version="0.3.0")
lock = asyncio.Lock()

@app.post('/calibration/{test_id}')
async def calibration_coupon(test_id:str,request:Request):
    if not secrets.compare_digest(request.headers.get('X-PrintFlow-Token',''),bridge_token()):raise HTTPException(401,'Worker authentication required')
    if lock.locked():raise HTTPException(409,'The design worker is busy. Try again when it finishes.')
    from .calibration_geometry import generate_coupon
    def work():
        with tempfile.TemporaryDirectory(prefix='printflow-coupon-') as temp:
            path=Path(temp)/'coupon.stl';generate_coupon(test_id,path);return path.read_bytes()
    async with lock:
        try:return Response(await asyncio.to_thread(work),media_type='model/stl')
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(400,str(exc)) from exc

@app.get("/health")
def health():
    import cadquery
    return {"ok": True, "engine": "CadQuery", "version": cadquery.__version__, "device": "cpu", "busy": lock.locked(), "templates": TEMPLATES}

@app.post("/generate")
async def create(request: Request):
    if not secrets.compare_digest(request.headers.get("X-PrintFlow-Token", ""), bridge_token()):
        raise HTTPException(401, "Worker authentication required")
    if lock.locked():
        raise HTTPException(409, "The design worker is busy. Try again when the current design finishes")
    body = await request.json()
    def work():
        with tempfile.TemporaryDirectory(prefix="printflow-cad-") as temp:
            generate(body, temp)
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
                for file in Path(temp).iterdir():
                    archive.write(file, file.name)
            return data.getvalue()
    async with lock:
        try:
            return Response(await asyncio.to_thread(work), media_type="application/zip")
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

@app.post('/split')
async def split(request:Request):
    if not secrets.compare_digest(request.headers.get('X-PrintFlow-Token',''),bridge_token()):raise HTTPException(401,'Worker authentication required')
    if lock.locked():raise HTTPException(409,'The design worker is busy')
    from .assembly_geometry import split_model
    body=await request.json()
    def work():
        with tempfile.TemporaryDirectory(prefix='printflow-split-') as temp:
            split_model(body,temp);data=io.BytesIO()
            with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
                for file in Path(temp).iterdir():archive.write(file,file.name)
            return data.getvalue()
    async with lock:
        try:return Response(await asyncio.to_thread(work),media_type='application/zip')
        except (ValueError,KeyError,TypeError) as exc:raise HTTPException(400,str(exc)) from exc
