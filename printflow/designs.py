"""Persistent design jobs and library import; workers are replaceable services."""
from __future__ import annotations
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import re
import uuid
import zipfile
import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from .common import DATA, ROOT, bridge_token, now, read_json, save_json
from .design_schema import TEMPLATES, U1, validate_request, material_advice

router = APIRouter()
CAD_URL = os.environ.get("PRINTFLOW_DESIGN_URL", "http://127.0.0.1:8843")
IMAGE_URL = os.environ.get("PRINTFLOW_IMAGE3D_URL", "http://127.0.0.1:8844")
records_path = DATA / "designs.json"
records = read_json(records_path, [])
for record in records:
    if record["status"] in {"queued", "running"}:
        record.update(status="interrupted", stage="Interrupted by a service restart", error="Create a new revision to retry")


def portal():
    from . import api
    return api


def selected_printer(printer_id):
    entry = next((p for p in portal().config if p["id"] == printer_id), None)
    if not entry or entry["kind"] != "snapmaker_u1":
        raise ValueError("Select a configured printer with known build dimensions")
    return {"id": entry["id"], "name": entry["name"], **U1}


async def worker_health(url):
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
            response = await client.get(url + "/health")
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return {"ok": False}


@router.get("/api/design/capabilities")
async def capabilities():
    cad, image = await asyncio.gather(worker_health(CAD_URL), worker_health(IMAGE_URL))
    return {"cad": {"available": bool(cad.get("ok")), "engine": "CadQuery", "templates": TEMPLATES, "device": "CPU"},
            "image3d": {"available": bool(image.get("ready")), "engine": "TripoSR", "device": image.get("device"), "gpu_validated": image.get("gpu_validated", False),
                        "note": image.get("note") or "Set up the local image-to-3D worker first. TripoSR uses one object image; it does not create images from text or separate semantic color parts."},
            "printers": [selected_printer(p["id"]) for p in portal().config if p["kind"] == "snapmaker_u1"],
            "limits": {"native_gui_automation": False, "automatic_multicolor_painting": False, "organic_text_to_3d": False,
                       "note": "Parametric revisions are editable. Generated meshes need geometry, size, support and color review before printing."}}


@router.get("/api/designs")
async def list_designs():
    return {"designs": records[-100:][::-1]}


def find_design(identifier):
    record = next((r for r in records if r["id"] == identifier), None)
    if not record:
        raise ValueError("Design not found")
    return record


def update(record, **values):
    record.update(values)
    save_json(records_path, records)
    portal().events.emit("design", record)


def import_archive(data, record):
    """Import only bounded regular artifacts from our authenticated worker."""
    if len(data) > 200 * 1024**2:
        raise ValueError("The worker result exceeds 200 MB")
    destination = ROOT / "models" / "designs" / record["id"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 100 or sum(i.file_size for i in infos) > 400 * 1024**2:
            raise ValueError("The worker result is too large")
        names = [i.filename for i in infos]
        if len(set(names)) != len(names) or "manifest.json" not in names:
            raise ValueError("Invalid worker manifest")
        for info in infos:
            path = Path(info.filename)
            if path.name != info.filename or path.suffix.lower() not in {".stl", ".3mf", ".step", ".py", ".json", ".png", ".glb"} or info.is_dir():
                raise ValueError("The worker returned an unsupported artifact")
        manifest = json.loads(archive.read("manifest.json"))
        parts = manifest.get("parts", [])
        if not parts or any(part.get("file") not in names or not part["file"].endswith(".stl") for part in parts):
            raise ValueError("The worker did not return printable mesh artifacts")
        destination.mkdir(parents=True, exist_ok=False)
        for info in infos:
            (destination / info.filename).write_bytes(archive.read(info))
    module = portal()
    if "Designs" not in module.folders:
        module.folders.append("Designs")
        save_json(DATA / "folders.json", module.folders)
    created = []
    for part in parts:
        path = destination / part["file"]
        item = {"id": uuid.uuid4().hex[:16], "name": record["name"] + " · " + part["name"] + ".stl", "folder": "Designs",
                "path": path.relative_to(ROOT / "models").as_posix(), "extension": ".stl", "size": path.stat().st_size,
                "created_at": now(), "design_id": record["id"], "planned_color": part.get("color"), "quantity": part.get("quantity", 1)}
        module.files.append(item)
        created.append(item["id"])
    save_json(module.store_path, module.files)
    module.events.emit("library", {"design_id": record["id"]})
    return created, manifest


async def run(record, worker_url, payload):
    try:
        update(record, status="running", stage="Generating geometry in the local worker")
        async with httpx.AsyncClient(trust_env=False, timeout=1800) as client:
            response = await client.post(worker_url + "/generate", json=payload, headers={"X-PrintFlow-Token": bridge_token()})
            if not response.is_success:
                try:
                    detail = response.json().get("detail", response.text)
                except ValueError:
                    detail = response.text
                raise ValueError(str(detail)[:1000])
        update(record, stage="Checking generated artifacts and saving to the library")
        created, manifest = import_archive(response.content, record)
        if manifest.get("assembly"):
            update(record,stage="Building the native U1 color assembly")
            module=portal()
            saved=ROOT/"models"/"designs"/record["id"]
            native=await module.native("u1_prepare_assembly",{"manifest":str(saved/"manifest.json"),"filament":"Snapmaker PLA SnapSpeed @U1"})
            response=await module.host("GET","/artifact",params={"path":native["project"]},timeout=90)
            path=saved/"assembly.3mf";path.write_bytes(response.content)
            item={"id":uuid.uuid4().hex[:16],"name":record["name"]+".3mf","folder":"Designs","path":path.relative_to(ROOT/"models").as_posix(),"extension":".3mf","size":path.stat().st_size,"created_at":now(),"design_id":record["id"],"assembly":True}
            module.files.append(item);created.insert(0,item["id"])
            save_json(module.store_path,module.files);module.events.emit("library",{"design_id":record["id"]})
        update(record, status="ready", stage="Saved to Library · review before slicing", files=created, parts=manifest["parts"],
               notes=manifest.get("notes", []), color_note=manifest.get("color_note"), completed_at=now())
        from .colors import publish_model
        publish_model(created[0])
    except Exception as exc:
        update(record, status="error", stage="Generation failed", error=str(exc))


def enqueue(request, engine, worker_url, payload):
    if sum(r["status"] in {"queued", "running"} for r in records) >= 2:
        raise ValueError("Two designs are already being generated")
    parent = request.get("revision_of")
    if parent:
        find_design(parent)
    record = {"id": uuid.uuid4().hex[:16], "name": request["name"], "engine": engine, "status": "queued", "stage": "Queued",
              "request": request, "revision_of": parent, "created_at": now(), "files": [], "parts": [],
              "advice": material_advice(request) if engine == "cadquery" else {"material": "PLA", "reason": "Start with an indoor display prototype; inspect the generated geometry first."}}
    records.append(record)
    update(record)
    task = asyncio.create_task(run(record, worker_url, payload))
    portal().tasks.add(task)
    task.add_done_callback(portal().tasks.discard)
    return record


@router.post("/api/designs")
async def create_design(request: Request):
    body = await request.json()
    validated = validate_request(body, selected_printer(body.get("printer_id")))
    if not (await worker_health(CAD_URL)).get("ok"):
        raise ValueError("The local CAD worker is offline. Start the design service before generating")
    return enqueue(validated, "cadquery", CAD_URL, validated)


@router.post("/api/designs/image")
async def image_design(file: UploadFile = File(), name: str = Form("Image model"), size_mm: float = Form(100), printer_id: str = Form(),quality:str=Form('detail'),background:str=Form('remove')):
    printer = selected_printer(printer_id)
    if not 10 <= size_mm <= min(printer["build_volume"]) - 12:
        raise ValueError("Choose a model size that fits the printer with a 12 mm margin")
    image = await file.read(12 * 1024**2 + 1)
    if len(image) > 12 * 1024**2:
        raise ValueError("Use an image smaller than 12 MB")
    if not (image.startswith(b"\x89PNG\r\n\x1a\n") or image.startswith(b"\xff\xd8\xff")):
        raise ValueError("Use a PNG or JPEG object image")
    if not (await worker_health(IMAGE_URL)).get("ready"):
        raise ValueError("The local image-to-3D worker is not ready. Run the installer and its model check first")
    if quality not in {'draft','balanced','detail'} or background not in {'remove','keep'}:raise ValueError('Choose valid image quality and background options')
    request = {"name": name[:100], "printer_id": printer_id, "size_mm": size_mm, "source_name": Path(file.filename or "image").name, "template": "image", "usage": {},'quality':quality,'background':background}
    payload = request | {"image_base64": base64.b64encode(image).decode("ascii")}
    return enqueue(request, "triposr", IMAGE_URL, payload)

@router.post('/api/designs/{identifier}/refine-image')
async def refine_image(identifier:str,request:Request):
    original=find_design(identifier)
    if original.get('engine')!='triposr' or original.get('status')!='ready':raise ValueError('Choose a completed image reconstruction')
    b=await request.json();quality=b.get('quality','detail');background=b.get('background','remove')
    if quality not in {'draft','balanced','detail'} or background not in {'remove','keep'}:raise ValueError('Choose valid image quality and background options')
    path=ROOT/'models'/'designs'/original['id']/'reference.png'
    if not path.is_file():path=path.with_name('input.png')
    if not path.is_file():raise ValueError('Upload the original reference image again')
    health=await worker_health(IMAGE_URL)
    if not health.get('ready'):raise ValueError('Start the local image-to-3D worker first')
    if health.get('busy'):raise ValueError('The image worker is still generating another model')
    data=dict(original['request'],name=original['name']+' · detail revision',revision_of=identifier,quality=quality,background=background)
    return enqueue(data,'triposr',IMAGE_URL,data|{'image_base64':base64.b64encode(path.read_bytes()).decode('ascii')})


@router.get("/api/designs/{identifier}/source")
async def design_source(identifier: str, kind: str = "parameters"):
    record = find_design(identifier)
    filename = {"parameters": "parameters.json", "step": "model.step", "source": "model.py", "manifest": "manifest.json", "mesh": "model.glb"}.get(kind)
    if not filename:
        raise ValueError("Choose parameters, step, source or manifest")
    path = ROOT / "models" / "designs" / record["id"] / filename
    if not path.is_file():
        raise HTTPException(404, "This artifact is unavailable for this design")
    return FileResponse(path, filename=filename)
