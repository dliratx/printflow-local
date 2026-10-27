"""Fetch explicitly pinned MIT model/source artifacts. No login or gated weights."""
import argparse
import io
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

SOURCE = "107cefdc244c39106fa830359024f6a2f1c78871"
WEIGHTS = "5b521936b01fbe1890f6f9baed0254ab6351c04a"
DINO = "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2"


def fetch(url, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    temporary.replace(path)


def source(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    url = f"https://codeload.github.com/VAST-AI-Research/TripoSR/tar.gz/{SOURCE}"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(40 * 1024**2 + 1)
    if len(data) > 40 * 1024**2:
        raise ValueError("Unexpected upstream source size")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            path = Path(*Path(member.name).parts[1:])
            if member.isfile() and (str(path).replace("\\", "/").startswith("tsr/") or path.name in {"LICENSE", "README.md"}):
                target = (destination / path).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("Invalid upstream archive path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    # No C++/CUDA-only marching-cubes extension, no background-removal dependency.
    (destination / "tsr/models/isosurface.py").write_text("from printflow.image3d_isosurface import MarchingCubeHelper\n", encoding="utf-8")
    utils = destination / "tsr/utils.py"
    value = utils.read_text(encoding="utf-8")
    value = value.replace("import rembg\n", "")
    value = value.replace("        image = rembg.remove", "        import rembg  # Optional; PrintFlow does not call this path.\n        image = rembg.remove")
    utils.write_text(value, encoding="utf-8")
    tokenizer = destination / "tsr/models/tokenizers/image.py"
    value = tokenizer.read_text(encoding="utf-8")
    old = '''hf_hub_download(
                    repo_id=self.cfg.pretrained_model_name_or_path,
                    filename="config.json",
                )'''
    if old not in value:
        raise ValueError("Unexpected upstream tokenizer; review the integration before upgrading")
    value = "import os\n" + value.replace(old, 'os.path.join(os.environ["PRINTFLOW_WEIGHTS_DIR"], "dino-config.json")')
    tokenizer.write_text(value, encoding="utf-8")
    (destination / "printflow-provenance.json").write_text(json.dumps({"source": SOURCE, "license": "MIT", "changes": ["CPU skimage marching cubes", "lazy unused rembg import", "offline pinned DINO configuration"]}, indent=2))


def weights(destination):
    destination = Path(destination)
    for name in ("config.yaml", "model.ckpt"):
        if name == "model.ckpt" and (destination / name).is_file():
            with (destination / name).open("rb") as file:
                existing = hashlib.file_digest(file, "sha256").hexdigest()
            if existing == "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee":
                continue
        fetch(f"https://huggingface.co/stabilityai/TripoSR/resolve/{WEIGHTS}/{name}?download=true", destination / name)
    with (destination / "model.ckpt").open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    if digest != "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee":
        raise ValueError("Model checksum differs from the pinned upstream LFS artifact")
    fetch(f"https://huggingface.co/facebook/dino-vitb16/resolve/{DINO}/config.json", destination / "dino-config.json")
    (destination / "provenance.json").write_text(json.dumps({"model": "stabilityai/TripoSR", "revision": WEIGHTS, "license": "MIT", "dino_config_revision": DINO}, indent=2))
    background(destination)
    print("Pinned model files downloaded. Run the device and inference checks before claiming GPU readiness.")

def background(destination):
    destination=Path(destination);path=destination/'u2net.onnx'
    expected='60024c5c889badc19c04ad937298a77b'
    def digest():
        with path.open('rb') as file:return hashlib.file_digest(file,'md5').hexdigest()
    if not path.is_file() or digest()!=expected:
        fetch('https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx',path)
    if digest()!=expected:raise ValueError('Background model checksum differs from the pinned upstream artifact')
    fetch('https://raw.githubusercontent.com/xuebinqin/U-2-Net/master/LICENSE',destination/'U2NET-LICENSE.txt')
    with path.open('rb') as file:sha=hashlib.file_digest(file,'sha256').hexdigest()
    (destination/'background-provenance.json').write_text(json.dumps({'model':'U2Net','source':'https://github.com/xuebinqin/U-2-Net','distribution':'rembg release v0.0.0','license':'Apache-2.0','md5':expected,'sha256':sha},indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["source", "weights", "background"])
    parser.add_argument("destination")
    args = parser.parse_args()
    globals()[args.action](args.destination)
