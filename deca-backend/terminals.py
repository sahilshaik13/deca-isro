"""REST + WebSocket routes for dashboard terminals."""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from terminal_manager import ALLOWED_TARGETS, manager

router = APIRouter(prefix="/api/v1", tags=["terminals"])


class TerminalCreateBody(BaseModel):
    target: str = Field(..., description="brain | station1 | station2 | station3")


def _peer_host(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host or ""


def _require_localhost(request: Request) -> None:
    peer = _peer_host(request)
    if peer not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="localhost_only")


def _ws_localhost(websocket: WebSocket) -> bool:
    client = websocket.client
    if client is None:
        return False
    return client.host in ("127.0.0.1", "::1")


@router.get("/terminals")
def list_terminals(request: Request):
    _require_localhost(request)
    return {"terminals": manager.list_sessions()}


@router.post("/pipeline/ensure")
def ensure_pipeline(request: Request):
    """Idempotent: pipeline monitor sessions already start with the manager."""
    _require_localhost(request)
    try:
        import pipeline_feed

        pipeline_feed.start()
        tabs = pipeline_feed.ensure_sessions_meta()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    sessions = manager.list_sessions()
    by_id = {s["id"]: s for s in sessions}
    out = []
    for tab in tabs:
        meta = by_id.get(tab["id"])
        out.append({**tab, "session": meta, "ok": meta is not None})
    return {"ok": all(t["ok"] for t in out), "tabs": out}


@router.post("/terminals")
def create_terminal(body: TerminalCreateBody, request: Request):
    _require_localhost(request)
    try:
        session = manager.create_interactive(body.target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"ok": True, "terminal": session.meta()}


@router.delete("/terminals/{session_id}")
def delete_terminal(session_id: str, request: Request):
    _require_localhost(request)
    try:
        ok = manager.delete_interactive(session_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="terminal not found")
    return {"ok": True}


@router.websocket("/terminals/{session_id}/ws")
async def terminal_ws(websocket: WebSocket, session_id: str):
    if not _ws_localhost(websocket):
        await websocket.close(code=4403, reason="localhost_only")
        return

    session = manager.get(session_id)
    if session is None:
        await websocket.close(code=4404, reason="not_found")
        return

    await websocket.accept()

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=256)

    def on_data(data: bytes) -> None:
        try:
            loop.call_soon_threadsafe(_enqueue, queue, data)
        except RuntimeError:
            pass

    def _enqueue(q: asyncio.Queue, data: bytes) -> None:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    session.subscribe(on_data)

    async def pump_out() -> None:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            await websocket.send_bytes(chunk)

    out_task = asyncio.create_task(pump_out())

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if "bytes" in message and message["bytes"] is not None:
                data = message["bytes"]
                if not session.readonly:
                    await asyncio.to_thread(session.write_input, data)
                continue
            if "text" in message and message["text"] is not None:
                text = message["text"]
                if text.startswith("{") and '"type"' in text:
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict) and payload.get("type") == "resize":
                        rows = int(payload.get("rows") or 24)
                        cols = int(payload.get("cols") or 80)
                        await asyncio.to_thread(session.resize, rows, cols)
                        continue
                if not session.readonly:
                    await asyncio.to_thread(session.write_input, text.encode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    finally:
        session.unsubscribe(on_data)
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        out_task.cancel()
        try:
            await out_task
        except asyncio.CancelledError:
            pass
        # Close interactive shells when the last viewer disconnects
        if session.mode == "interactive" and not session._subscribers:
            try:
                manager.delete_interactive(session.id)
            except Exception:  # noqa: BLE001
                pass


# Re-export for docs / tests
__all__ = ["router", "ALLOWED_TARGETS"]
