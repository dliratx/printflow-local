"""Optional local TripoSR worker: genuine image inference, no placeholder meshes."""
import asyncio
import base64
import io
import json
import math
import os
from pathlib import Path
import secrets
import tempfile
import time
import zipfile
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from .common import bridge_token
from .image3d_input import prepare_input, QUALITY

app = FastAPI(title="PrintFlow image to 3D", version="0.3.0")
lock = asyncio.Lock()
weights = Path(os.environ.get("PRINTFLOW_WEIGHTS_DIR", "/weights"))
model = None
device = "unverified"
gpu_validated = False
last_inference = None
last_error = None


def device_check():
    import torch
    preferred = os.environ.get("PRINTFLOW_DEVICE", "cpu")
    if preferred not in {"cpu", "cuda"}:
        raise ValueError("PRINTFLOW_DEVICE must be cpu or cuda (including ROCm)")
    if preferred == "cuda":
        if not torch.cuda.is_available():
            raise ValueError("The selected GPU is unavailable inside this worker")
        value = torch.ones((256, 256), device="cuda")
        result = (value @ value).mean().item()
        torch.cuda.synchronize()
        if result != 256:
            raise ValueError("GPU tensor check failed")
        return {"device": "cuda", "name": torch.cuda.get_device_name(0), "backend": "rocm" if torch.version.hip else "cuda", "tensor_check": True, "inference_validated": gpu_validated}
    return {"device": "cpu", "name": "CPU", "tensor_check": True, "inference_validated": last_inference is not None}


@app.get("/health")
def health():
    present = all((weights / file).is_file() for file in ("model.ckpt", "config.yaml", "dino-config.json", "provenance.json"))
    return {"ok": True, "ready": present, "engine": "TripoSR", "device": device, "gpu_validated": gpu_validated,
            "busy": lock.locked(), "last_inference": last_inference, "last_error": last_error,
            "background_removal":(weights/'u2net.onnx').is_file(), "quality_modes":QUALITY,
            "note": "Use a single isolated object on a neutral background or a transparent PNG. Geometry needs review; texture colors are not separate printable parts." if present else "Download the pinned MIT weights with the installer models command. No weights are downloaded by a generation request."}


@app.get("/device")
def check():
    try:
        return device_check()
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc


def infer(body):
    global model, device, gpu_validated, last_inference
    import numpy as np
    import torch
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 16_000_000
    from tsr.system import TSR
    from omegaconf import OmegaConf
    size = float(body.get("size_mm", 100))
    if not math.isfinite(size) or not 10 <= size <= 1000:
        raise ValueError("Invalid target size")
    started = time.monotonic()
    probe = device_check()
    device = probe["device"]
    if model is None:
        cfg = OmegaConf.load(weights / "config.yaml")
        OmegaConf.resolve(cfg)
        candidate = TSR(cfg)
        candidate.load_state_dict(torch.load(weights / "model.ckpt", map_location="cpu", weights_only=True))
        candidate.renderer.set_chunk_size(4096)
        candidate.eval().to(device)
        model = candidate
    raw = base64.b64decode(body["image_base64"], validate=True)
    if len(raw) > 12 * 1024**2:
        raise ValueError("Image exceeds 12 MB")
    source = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGBA")
    quality=body.get('quality','detail')
    if quality not in QUALITY:raise ValueError('Choose draft, balanced or detail quality')
    image,preprocessing=prepare_input(source,weights,body.get('background','remove'))
    resolution = QUALITY[quality]
    if resolution not in {64, 128, 192, 256}:
        raise ValueError("Mesh resolution must be 64, 128, 192 or 256")
    with torch.inference_mode():
        scene = model([image], device=device)
        mesh = model.extract_mesh(scene, has_vertex_color=True, resolution=resolution)[0]
    if len(mesh.faces) == 0 or not np.isfinite(mesh.vertices).all() or max(mesh.extents) <= 0:
        raise ValueError("The model did not produce usable geometry")
    mesh.fix_normals()
    # TripoSR camera coordinates are Z-up (tsr/utils.py); preserve that axis.
    mesh.apply_scale(size / max(mesh.extents))
    mesh.apply_translation(-mesh.bounds[0])
    manifest = {"parts": [{"name": "image_model", "file": "image_model.stl", "quantity": 1, "dimensions": mesh.extents.tolist()}],
                "notes": ["AI-generated geometry: inspect thin features, disconnected regions, orientation and supports before printing.",
                          "The GLB preserves vertex colors for reference. STL has no color assignments; four-tool separation is not automatic."],
                "mesh": {"faces": len(mesh.faces), "watertight": bool(mesh.is_watertight), "volume_mm3": float(abs(mesh.volume))},
                "engine": "TripoSR", "device": probe,"quality":quality,"mesh_resolution":resolution,"preprocessing":preprocessing,
                "elapsed_seconds": round(time.monotonic()-started, 2)}
    with tempfile.TemporaryDirectory(prefix="printflow-image-") as folder:
        folder = Path(folder)
        mesh.export(folder / "image_model.stl")
        mesh.export(folder / "model.glb")
        image.save(folder / "input.png")
        source.save(folder / "reference.png")
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (folder / "parameters.json").write_text(json.dumps({k: v for k, v in body.items() if k != "image_base64"}, indent=2))
        archive_data = io.BytesIO()
        with zipfile.ZipFile(archive_data, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in folder.iterdir():
                archive.write(file, file.name)
    gpu_validated = device == "cuda"
    last_inference = {"seconds": manifest["elapsed_seconds"], "device": device, "faces": len(mesh.faces)}
    return archive_data.getvalue()


@app.post("/generate")
async def generate(request: Request):
    global last_error
    if not secrets.compare_digest(request.headers.get("X-PrintFlow-Token", ""), bridge_token()):
        raise HTTPException(401, "Worker authentication required")
    if not health()["ready"]:
        raise HTTPException(503, "Install the pinned model weights first")
    if lock.locked():
        raise HTTPException(409, "The image worker is already generating a model")
    body = await request.json()
    async with lock:
        try:
            result = await asyncio.to_thread(infer, body)
            last_error = None
            return Response(result, media_type="application/zip")
        except Exception as exc:
            last_error = str(exc)
            raise HTTPException(400, last_error) from exc


if __name__ == "__main__":
    print(json.dumps(device_check(), indent=2))
