"""REST API + SSE + MJPEG stream cho dashboard."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger("ppe.api")


# --------------------------------------------------------------------------- #
# Event bus cho SSE
# --------------------------------------------------------------------------- #
class EventBus:
    def __init__(self) -> None:
        self._queues: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: str, data: dict) -> None:
        if self._loop is None:
            return
        payload = (event, data)

        def _dispatch() -> None:
            with self._lock:
                targets = list(self._queues)
            for q in targets:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

        self._loop.call_soon_threadsafe(_dispatch)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._queues.discard(q)


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
class CameraIn(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    name: str = Field(min_length=1, max_length=120)
    source: str = Field(min_length=1)
    zone: str = "default"
    enabled: bool = True
    polygon: list[list[float]] | None = None


class CameraPatch(BaseModel):
    name: str | None = None
    source: str | None = None
    zone: str | None = None
    enabled: bool | None = None
    polygon: list[list[float]] | None = None


class AckIn(BaseModel):
    by: str = "operator"
    resolution: str = "confirmed"   # confirmed | false_positive
    note: str | None = None


class BulkAckIn(BaseModel):
    ids: list[int] = Field(default_factory=list)
    by: str = "operator"
    resolution: str = "confirmed"
    note: str | None = None


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #
def create_app(state: dict[str, Any]) -> FastAPI:
    """state: db, detector, rules, workers, bus, cfg, evidence_dir, started_at"""
    db = state["db"]
    bus: EventBus = state["bus"]
    cfg = state["cfg"]
    workers: dict[str, Any] = state["workers"]

    app = FastAPI(title="PPE Monitor", version="1.0.0", docs_url="/api/docs")

    static_dir = Path(state["static_dir"])
    evidence_dir = Path(state["evidence_dir"])

    from app import auth as auth_mod

    auth = state.get("auth") or auth_mod.Auth({})

    # ---------------- middleware xac thuc ----------------
    @app.middleware("http")
    async def _auth_gate(request: Request, call_next):
        path = request.url.path
        if not auth.enabled or path in ("/", "/api/health", "/api/docs", "/openapi.json",
                                        "/api/auth/login"):
            return await call_next(request)
        if path.startswith(("/static", "/evidence")):
            # Tep bang chung: cho phep khi da dang nhap hoac localhost
            sess = auth.resolve(request)
            if sess is None and not path.startswith("/static"):
                return JSONResponse({"detail": "Chua dang nhap"}, status_code=401)
            return await call_next(request)

        sess = auth.resolve(request)
        if sess is None:
            return JSONResponse({"detail": "Chua dang nhap"}, status_code=401)
        need = auth_mod.required_role(request.method, path)
        if not auth_mod.has_role(sess["role"], need):
            return JSONResponse(
                {"detail": f"Can quyen {need}, ban co {sess['role']}"}, status_code=403
            )
        request.state.user = sess
        return await call_next(request)

    @app.on_event("startup")
    async def _startup() -> None:
        bus.bind(asyncio.get_running_loop())

    # ---------------- trang chu ----------------
    @app.get("/", include_in_schema=False)
    def index():
        p = static_dir / "index.html"
        if not p.exists():
            return JSONResponse({"error": "static/index.html khong ton tai"}, status_code=500)
        return FileResponse(p)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/evidence", StaticFiles(directory=str(evidence_dir)), name="evidence")

    # ---------------- he thong ----------------
    @app.get("/api/health")
    def health():
        det = state.get("detector")
        return {
            "ok": True,
            "uptime_sec": round(time.time() - state["started_at"], 1),
            "cameras": len(workers),
            "model": det.info() if det else None,
            "alerts": state["alert_mgr"].stats() if state.get("alert_mgr") else None,
        }

    @app.get("/api/config")
    def get_config():
        return {
            "zones": cfg.get("rules.zones", {}),
            "app": {"data_dir": str(cfg.path_of("app.data_dir", "data"))},
        }

    # ---------------- xac thuc ----------------
    @app.post("/api/auth/login")
    def login(body: dict = Body(...)):
        from fastapi import Response

        user = str(body.get("user", "")).strip()
        pwd = str(body.get("password", ""))
        token = auth.login(user, pwd)
        if not token:
            db.log_event("warn", None, f"Dang nhap that bai: {user}")
            raise HTTPException(401, "Sai ten dang nhap hoac mat khau")
        db.log_event("info", None, f"Dang nhap: {user}")
        resp = JSONResponse({"ok": True, "user": user, "role": auth.users[user]["role"]})
        resp.set_cookie(
            "ppe_session", token,
            max_age=int(auth.session_hours * 3600),
            httponly=True, samesite="lax",
        )
        return resp

    @app.post("/api/auth/logout")
    def logout(request: Request):
        token = request.cookies.get("ppe_session")
        if token:
            auth.logout(token)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("ppe_session")
        return resp

    @app.get("/api/auth/me")
    def whoami(request: Request):
        if not auth.enabled:
            return {"enabled": False, "user": "anonymous", "role": "admin"}
        sess = auth.resolve(request)
        if not sess:
            raise HTTPException(401, "Chua dang nhap")
        return {"enabled": True, **sess}

    @app.post("/api/auth/password")
    def change_password(request: Request, body: dict = Body(...)):
        """Doi mat khau cua chinh minh. Ghi vao config.yaml."""
        sess = auth.resolve(request)
        if not sess:
            raise HTTPException(401, "Chua dang nhap")
        old = str(body.get("old", ""))
        new = str(body.get("new", ""))
        if len(new) < 8:
            raise HTTPException(400, "Mat khau moi phai tu 8 ky tu")
        user = sess["user"]
        rec = auth.users.get(user)
        if not rec or not auth_mod.verify_password(old, rec["hash"]):
            raise HTTPException(403, "Sai mat khau cu")
        cfg.set(f"auth.users.{user}", auth_mod.hash_password(new))
        cfg.save()
        return {"ok": True, "note": "Khoi dong lai server de ap dung"}

    # ---------------- do phu nhan dien ----------------
    @app.get("/api/coverage")
    def get_coverage():
        from app.coverage import coverage

        return coverage(state.get("detector"), cfg.get("rules.zones", {}))

    # ---------------- luu tru ----------------
    @app.get("/api/retention")
    def get_retention():
        ret = state.get("retention")
        info = ret.info() if ret else {"enabled": False}
        info["db_size_mb"] = round(db.db_size() / 1024 ** 2, 2)
        info["violations"] = db.count_violations()
        return info

    @app.post("/api/retention/run")
    def run_retention():
        ret = state.get("retention")
        if not ret:
            raise HTTPException(503, "Khong co module don dep")
        return ret.run_once()

    # ---------------- camera ----------------
    @app.get("/api/cameras")
    def list_cameras():
        rows = {c["id"]: c for c in db.list_cameras()}
        for cid, w in workers.items():
            if cid in rows:
                rows[cid].update(w.status())
        status = {s["cam_id"]: s for s in db.camera_status()}
        for cid, s in status.items():
            if cid in rows:
                rows[cid]["fps"] = s["fps"]
                rows[cid]["persons"] = s["persons"]
                rows[cid]["online"] = s["online"]
        return list(rows.values())

    @app.post("/api/cameras", status_code=201)
    def add_camera(cam: CameraIn):
        if cam.id in workers:
            raise HTTPException(409, "Camera da ton tai")
        payload = cam.model_dump()
        db.upsert_camera(payload)
        state["spawn_worker"](payload)
        db.log_event("info", cam.id, f"Them camera {cam.name}")
        return {"ok": True, "id": cam.id}

    @app.patch("/api/cameras/{cam_id}")
    def patch_camera(cam_id: str, patch: CameraPatch):
        rows = {c["id"]: c for c in db.list_cameras()}
        if cam_id not in rows:
            raise HTTPException(404, "Khong tim thay camera")
        merged = {**rows[cam_id], **{k: v for k, v in patch.model_dump().items() if v is not None}}
        db.upsert_camera(merged)
        state["restart_worker"](merged)
        return {"ok": True}

    @app.delete("/api/cameras/{cam_id}")
    def delete_camera(cam_id: str):
        state["stop_worker"](cam_id)
        db.delete_camera(cam_id)
        db.log_event("info", cam_id, "Xoa camera")
        return {"ok": True}

    # ---------------- vi pham ----------------
    @app.get("/api/violations")
    def list_violations(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        cam: str | None = None,
        hours: float | None = None,
        unack: bool = False,
    ):
        since = time.time() - hours * 3600 if hours else None
        return db.list_violations(limit=limit, offset=offset, cam_id=cam,
                                  since=since, unack_only=unack)

    @app.post("/api/violations/{vid}/ack")
    def ack_violation(vid: int, body: AckIn = Body(default=AckIn())):
        res = body.resolution if body.resolution in ("confirmed", "false_positive") else "confirmed"
        note = (body.note or "").strip() or None
        db.acknowledge(vid, body.by, resolution=res, note=note)
        bus.publish("ack", {"id": vid, "by": body.by, "resolution": res})
        return {"ok": True}

    @app.post("/api/violations/bulk-ack")
    def bulk_ack_violations(body: BulkAckIn = Body(...)):
        res = body.resolution if body.resolution in ("confirmed", "false_positive") else "confirmed"
        note = (body.note or "").strip() or None
        count = db.acknowledge_many(body.ids, body.by, resolution=res, note=note)
        bus.publish("ack", {"ids": body.ids, "by": body.by, "resolution": res})
        return {"ok": True, "updated": count}

    @app.get("/api/stats")
    def stats(hours: float = Query(24.0, ge=0.5, le=24 * 90)):
        since = time.time() - hours * 3600
        rows = db.violation_counts(since)
        summary = db.summary(since)
        by_item: dict[str, int] = {}
        by_zone: dict[str, int] = {}
        by_cam: dict[str, int] = {}
        for r in rows:
            for item in json.loads(r["missing"]):
                by_item[item] = by_item.get(item, 0) + r["n"]
            by_zone[r["zone"]] = by_zone.get(r["zone"], 0) + r["n"]
            by_cam[r["cam_id"]] = by_cam.get(r["cam_id"], 0) + r["n"]
        return {
            "hours": hours,
            "summary": summary,
            "by_item": by_item,
            "by_zone": by_zone,
            "by_cam": by_cam,
            "hourly": db.hourly_series(since),
            "cameras": db.camera_status(),
        }

    @app.get("/api/events")
    def events(limit: int = Query(100, ge=1, le=500)):
        return db.list_events(limit)

    # ---------------- bao cao ----------------
    @app.get("/api/reports/violations.csv")
    def report_csv(days: float = Query(7.0, ge=0.5, le=365), cam: str | None = None):
        from fastapi import Response
        from app.reports import violations_csv

        body = violations_csv(db, days=days, cam_id=cam)
        name = f"ppe_violations_{time.strftime('%Y%m%d')}.csv"
        return Response(
            content=body.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/reports/summary.xlsx")
    def report_xlsx(days: float = Query(7.0, ge=0.5, le=365)):
        from fastapi import Response
        from app.reports import summary_xlsx

        try:
            body = summary_xlsx(db, days=days)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        name = f"ppe_report_{time.strftime('%Y%m%d')}.xlsx"
        return Response(
            content=body,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/api/reports/report.html")
    def report_page(days: float = Query(7.0, ge=0.5, le=365)):
        from fastapi.responses import HTMLResponse
        from app.reports import report_html

        return HTMLResponse(report_html(db, days=days))

    # ---------------- vung ve tay ----------------
    @app.put("/api/cameras/{cam_id}/polygon")
    def set_polygon(cam_id: str, body: dict = Body(...)):
        rows = {c["id"]: c for c in db.list_cameras()}
        if cam_id not in rows:
            raise HTTPException(404, "Khong tim thay camera")
        points = body.get("polygon")
        if points is not None:
            if not isinstance(points, list) or len(points) < 3:
                raise HTTPException(400, "Can it nhat 3 diem")
            for p in points:
                if not (isinstance(p, list) and len(p) == 2):
                    raise HTTPException(400, "Moi diem phai la [x, y]")
        merged = {**rows[cam_id], "polygon": points}
        db.upsert_camera(merged)
        state["restart_worker"](merged)
        db.log_event("info", cam_id, "Cap nhat vung giam sat")
        return {"ok": True, "points": len(points or [])}

    @app.get("/api/frame/{cam_id}")
    def raw_frame(cam_id: str):
        """Khung hinh hien tai (da ve overlay), dung de lam anh nen khi can."""
        w = workers.get(cam_id)
        if not w:
            raise HTTPException(404, "Khong co camera")
        jpeg, _ = w.latest()
        if not jpeg:
            raise HTTPException(503, "Chua co khung hinh")
        from fastapi import Response
        return Response(content=jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    # ---------------- stream ----------------
    @app.get("/api/snapshot/{cam_id}")
    def snapshot(cam_id: str):
        w = workers.get(cam_id)
        if not w:
            raise HTTPException(404, "Khong co camera")
        jpeg, _ = w.latest()
        if not jpeg:
            raise HTTPException(503, "Chua co khung hinh")
        from fastapi import Response
        return Response(content=jpeg, media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/stream/{cam_id}")
    def stream(cam_id: str):
        w = workers.get(cam_id)
        if not w:
            raise HTTPException(404, "Khong co camera")

        async def gen():
            boundary = b"--frame\r\n"
            while True:
                jpeg, _ = w.latest()
                if jpeg:
                    yield boundary + b"Content-Type: image/jpeg\r\nContent-Length: " \
                        + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
                await asyncio.sleep(0.06)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/events/stream")
    async def sse(request: Request):
        q = bus.subscribe()

        async def gen():
            try:
                yield "event: ready\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event, data = await asyncio.wait_for(q.get(), timeout=20)
                        yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                bus.unsubscribe(q)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no",
                                          "Connection": "keep-alive"})

    return app
