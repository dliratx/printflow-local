"""Portable PrintFlow installer and maintenance. Never sends printer commands."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import platform
import secrets
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".runtime/deployment.json"
VERSION = "0.3.0"
PROFILES = ("cpu", "amd-linux", "amd-wsl")


def command(args, capture=False, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=capture)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args[:3])}")
    return result


def settings():
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {"gpu": "cpu", "image3d": False}


def compose(*args, extra=None):
    cfg = settings()
    result = ["docker", "compose", "--project-directory", str(ROOT), "-f", str(ROOT / "compose.yaml")]
    if cfg["gpu"] != "cpu": result += ["-f", str(ROOT / f'deploy/compose.{cfg["gpu"]}.yaml')]
    if extra: result += ["-f", str(extra)]
    if cfg.get("image3d"): result += ["--profile", "image3d"]
    return result + list(args)


def docker_required():
    if not shutil.which("docker"):
        raise RuntimeError("Docker Engine with Compose v2 is required. On Windows, use Docker Engine in Ubuntu WSL2; see INSTALL.md")
    command(["docker", "info"], capture=True)
    command(["docker", "compose", "version"], capture=True)


def doctor():
    gpu = []
    if os.name == "nt":
        gpu = command(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"], capture=True, check=False).stdout.strip().splitlines()
    elif shutil.which("lspci"):
        gpu = [line for line in command(["lspci"], capture=True).stdout.splitlines() if any(word in line for word in ("VGA", "Display", "3D controller"))]
    docker = bool(shutil.which("docker"))
    engine = docker and command(["docker", "info"], capture=True, check=False).returncode == 0
    result = {"os": platform.platform(), "python": platform.python_version(), "gpus": gpu, "docker_cli": docker, "docker_engine": engine,
              "wsl": "microsoft" in platform.release().lower(), "devices": {p: Path(p).exists() for p in ("/dev/dxg", "/dev/kfd", "/dev/dri")},
              "deployment": settings(), "gpu_inference_validated": False,
              "note": "Hardware detection is not inference validation. Run check-gpu, then generate a model; successful inference is reported by the worker."}
    print(json.dumps(result, indent=2))
    return result


def init(args):
    cfg = {"gpu": args.gpu, "image3d": bool(args.image3d or args.gpu != "cpu"), "version": VERSION}
    for folder in (".runtime/printflow", "models", "runs", "weights/triposr", "backups"):
        (ROOT / folder).mkdir(parents=True, exist_ok=True)
    token_path = ROOT / ".runtime/bridge-token"
    if not token_path.exists(): token_path.write_text(secrets.token_urlsafe(48))
    env_path = ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    updates = {"PRINTFLOW_BRIDGE_TOKEN": token_path.read_text().strip(), "PRINTFLOW_VERSION": VERSION, "PRINTFLOW_GPU_PROFILE": args.gpu}
    if args.host_url:
        if not args.host_url.startswith(("http://", "https://")) or any(c in args.host_url for c in "\r\n"):
            raise ValueError("Provide an HTTP host bridge URL")
        updates["PRINTFLOW_HOST_URL"] = args.host_url.rstrip("/")
    if args.gpu == "amd-linux":
        import grp
        if not Path("/dev/kfd").exists(): raise ValueError("The AMD Linux profile requires /dev/kfd and a compatible driver")
        updates.update(PRINTFLOW_VIDEO_GID=str(grp.getgrnam("video").gr_gid), PRINTFLOW_RENDER_GID=str(grp.getgrnam("render").gr_gid))
    if args.gpu == "amd-wsl":
        required = ["/dev/dxg", "/usr/lib/wsl/lib/libdxcore.so", "/opt/rocm/lib/librocdxg.so", "/opt/rocm/share/rocdxg/dids.conf"]
        missing = [p for p in required if not Path(p).exists()]
        if missing: raise ValueError("Install the official AMD WSL prerequisites first: " + ", ".join(missing))
    lines = [line for line in lines if line.split("=", 1)[0] not in updates]
    lines += [f"{key}={value}" for key, value in updates.items()]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    CONFIG.write_text(json.dumps(cfg, indent=2))
    # In WSL on /mnt/c, ownership is controlled by the Windows mount settings.
    # Native Linux bind paths must be writable by the fixed container UID.
    if os.name != "nt":
        if os.geteuid() == 0:
            for folder in (".runtime/printflow", "models", "weights"):
                for directory, dirs, files in os.walk(ROOT / folder):
                    os.chown(directory, 10001, 10001)
                    for name in files:
                        path = Path(directory) / name
                        if not path.is_symlink(): os.chown(path, 10001, 10001)
        else:
            print("Ensure .runtime/printflow, models and weights are writable by UID 10001; see INSTALL.md.")
    print("Deployment configured. Secrets stay in .env; do not publish it.")


def ensure_idle_services():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8840/api/state", timeout=4) as response: state = json.load(response)
    except OSError: return
    if state.get("codex", {}).get("busy") or any(j.get("status") in {"queued", "running"} for j in state.get("jobs", [])):
        raise RuntimeError("Wait for active chat and slicing jobs before maintenance")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8840/api/designs", timeout=4) as response: designs = json.load(response)
        if any(j["status"] in {"queued", "running"} for j in designs["designs"]): raise RuntimeError("Wait for active design jobs before maintenance")
    except OSError: pass


def snapshot(image_ids=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = ROOT / "backups" / ("printflow-" + stamp + ".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = [ROOT / name for name in (".env", ".runtime/bridge-token", ".runtime/deployment.json", "printer_preferences.json")]
    for name in (".runtime/printflow", "models", "runs"):
        if (ROOT / name).exists(): files += list((ROOT / name).rglob("*"))
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            if file.is_file() and not file.is_symlink() and file.suffix not in {".tmp", ".partial"}:
                if not file.resolve().is_relative_to(ROOT.resolve()): raise ValueError("A backup source escapes the workspace")
                archive.write(file, file.relative_to(ROOT).as_posix())
        archive.writestr("backup-manifest.json", json.dumps({"version": VERSION, "created_at": stamp, "images": image_ids or {}, "deployment": settings(),
            "note": "Private backup: includes conversations, printer configuration and bridge secrets. Downloadable model weights are excluded."}, indent=2))
    print(f"Private backup saved: {destination}")
    return destination


def running_images():
    services = {}
    for identifier in command(compose("ps", "-q"), capture=True).stdout.split():
        item = json.loads(command(["docker", "inspect", identifier], capture=True).stdout)[0]
        service = item["Config"]["Labels"].get("com.docker.compose.service")
        if service: services[service] = item["Image"]
    return services


def restore(archive_path, destination):
    destination = Path(destination).resolve()
    if destination.exists(): raise ValueError("Restore into a new directory; existing files are never overwritten")
    with zipfile.ZipFile(archive_path) as archive:
        if "backup-manifest.json" not in archive.namelist(): raise ValueError("Not a PrintFlow backup")
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename or ":" in info.filename or stat.S_ISLNK(info.external_attr >> 16): raise ValueError("Unsafe backup member")
            if not (destination / info.filename).resolve().is_relative_to(destination): raise ValueError("Backup member escapes destination")
        destination.mkdir(parents=True)
        for info in archive.infolist():
            if info.is_dir(): continue
            path = destination / info.filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, path.open("xb") as target: shutil.copyfileobj(source, target)
    print(f"Restored without overwriting the current deployment: {destination}")


def maintain(update=False):
    docker_required()
    ensure_idle_services()
    previous = running_images()
    if update:
        command(compose("build", "--pull"))  # Failed builds leave running services untouched.
        ensure_idle_services()
    command(compose("stop"))
    try:
        backup = snapshot(previous)
    except Exception:
        command(compose("start"), check=False)
        raise
    if not update:
        command(compose("start"))
        return
    try:
        command(compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "180"))
    except RuntimeError:
        if previous:
            rollback = ROOT / ".runtime/rollback.compose.json"
            rollback.write_text(json.dumps({"services": {key: {"image": value} for key, value in previous.items()}}))
            command(compose("up", "-d", "--no-build", "--pull", "never", extra=rollback), check=False)
        raise RuntimeError(f"Update health checks failed. Previous images were requested; inspect status. Backup: {backup}")
    print("Updated services passed health checks. Previous image IDs are recorded in the backup.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor")
    initialize = sub.add_parser("init")
    initialize.add_argument("--gpu", choices=PROFILES, default="cpu")
    initialize.add_argument("--image3d", action="store_true")
    initialize.add_argument("--host-url")
    for name in ("up", "stop", "status", "logs", "backup", "update", "models", "check-gpu"): sub.add_parser(name)
    recovery = sub.add_parser("restore")
    recovery.add_argument("archive")
    recovery.add_argument("destination")
    args = parser.parse_args()
    if args.action == "doctor": doctor()
    elif args.action == "init": init(args)
    elif args.action == "restore": restore(args.archive, args.destination)
    elif args.action in {"backup", "update"}: maintain(args.action == "update")
    else:
        docker_required()
        if args.action == "up": command(compose("up", "-d", "--build", "--wait", "--wait-timeout", "180"))
        elif args.action == "stop": command(compose("stop"))
        elif args.action == "status": command(compose("ps"))
        elif args.action == "logs": command(compose("logs", "--tail", "100"))
        elif args.action in {"models", "check-gpu"}:
            if not settings().get("image3d"): raise ValueError("Enable the image worker with init --image3d first")
            if args.action == "models": command(compose("run", "--rm", "--no-deps", "image3d", "python", "bootstrap.py", "weights", "/weights"))
            else: command(compose("exec", "-T", "image3d", "python", "-m", "printflow.image3d_worker"))


if __name__ == "__main__":
    try: main()
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print("PrintFlow: " + str(exc), file=sys.stderr)
        sys.exit(1)
