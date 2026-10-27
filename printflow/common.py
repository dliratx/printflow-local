from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get("PRINTFLOW_DATA_DIR",ROOT/".runtime/printflow"))
DATA.mkdir(parents=True,exist_ok=True)

def now(): return datetime.now(timezone.utc).isoformat()
def read_json(path,default):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError): return default
def save_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    # Preview and thumbnail requests may compute the same cache concurrently.
    # Each writer needs its own temporary file before the atomic replacement.
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=path.parent,prefix=path.name+".",suffix=".tmp",delete=False) as writer:
        temp=Path(writer.name)
        json.dump(data,writer,indent=2,ensure_ascii=False)
    try:
        for attempt in range(6):
            try:
                temp.replace(path)
                break
            except PermissionError:
                if attempt==5: raise
                time.sleep(.01*(attempt+1))
    finally:
        temp.unlink(missing_ok=True)
def bridge_token():
    value=os.environ.get("PRINTFLOW_BRIDGE_TOKEN")
    if value: return value
    path=ROOT/".runtime/bridge-token"
    if not path.exists():
        path.parent.mkdir(exist_ok=True); path.write_text(secrets.token_urlsafe(48))
    return path.read_text().strip()

class Events:
    def __init__(self): self.subscribers=set(); self.history=[]
    def emit(self,kind,data):
        event={"type":kind,"data":data,"time":now()}
        self.history.append(event); self.history=self.history[-200:]
        for queue in self.subscribers:
            if queue.full():
                try: queue.get_nowait()
                except asyncio.QueueEmpty: pass
            queue.put_nowait(event)
    async def stream(self):
        queue=asyncio.Queue(maxsize=100); self.subscribers.add(queue)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    event=await asyncio.wait_for(queue.get(),15)
                    yield "event: update\ndata: "+json.dumps(event,ensure_ascii=False)+"\n\n"
                except TimeoutError: yield ": heartbeat\n\n"
        finally: self.subscribers.discard(queue)
