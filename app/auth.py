"""Xac thuc dashboard: token qua header hoac cookie, phan quyen theo vai tro.

Ba che do trong config.yaml:

    auth:
      enabled: false                       # mo, ai trong LAN cung vao
      enabled: true
      users:
        admin: "matkhau-manh"              # toan quyen
        viewer: "matkhau-khac"             # chi xem, khong xoa/sua
      session_hours: 12
      allow_localhost: true                # 127.0.0.1 khong can dang nhap

Mat khau luu duoi dang bam PBKDF2-SHA256, khong luu tho.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any

log = logging.getLogger("ppe.auth")

# Vai tro: viewer chi doc, operator xu ly vi pham, admin sua cau hinh
ROLE_ORDER = {"viewer": 1, "operator": 2, "admin": 3}


def hash_password(password: str, salt: bytes | None = None) -> str:
    """pbkdf2_sha256$iterations$salt_b64$hash_b64"""
    salt = salt or secrets.token_bytes(16)
    iterations = 240_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(iters)
        )
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except Exception:
        return False


class Auth:
    """Quan ly phien dang nhap trong bo nho. Khoi dong lai = dang xuat het."""

    def __init__(self, cfg: dict | None):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled", False))
        self.allow_localhost = bool(self.cfg.get("allow_localhost", True))
        self.session_hours = float(self.cfg.get("session_hours", 12))

        self.users: dict[str, dict[str, str]] = {}
        raw = self.cfg.get("users", {}) or {}
        for name, spec in raw.items():
            if isinstance(spec, str):
                self.users[name] = {"hash": hash_password(spec), "role": "admin"}
            elif isinstance(spec, dict):
                pwd = spec.get("password", "")
                hashed = spec.get("hash") or hash_password(pwd) if pwd else spec.get("hash", "")
                self.users[name] = {
                    "hash": hashed,
                    "role": spec.get("role", "admin"),
                }

        self._sessions: dict[str, dict[str, Any]] = {}

        if self.enabled and not self.users:
            log.warning("auth.enabled=true nhung khong co user nao — tao user mac dinh 'admin'")
            self.users["admin"] = {"hash": hash_password("admin"), "role": "admin"}

    # ---------------- phien ----------------
    def login(self, username: str, password: str) -> str | None:
        user = self.users.get(username)
        if not user:
            return None
        if not verify_password(password, user["hash"]):
            return None
        token = secrets.token_urlsafe(32)
        self._sessions[token] = {
            "user": username,
            "role": user["role"],
            "expires": time.time() + self.session_hours * 3600,
        }
        self._gc()
        return token

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    def session(self, token: str | None) -> dict | None:
        if not token:
            return None
        rec = self._sessions.get(token)
        if not rec:
            return None
        if rec["expires"] < time.time():
            self._sessions.pop(token, None)
            return None
        return rec

    def _gc(self) -> None:
        now = time.time()
        for tok in [k for k, v in self._sessions.items() if v["expires"] < now]:
            self._sessions.pop(tok, None)

    # ---------------- kiem tra quyen ----------------
    def resolve(self, request) -> dict | None:
        """Tra ve {'user','role'} hoac None. None = chua dang nhap."""
        if not self.enabled:
            return {"user": "anonymous", "role": "admin"}

        # Header Authorization: Bearer <token>
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            rec = self.session(auth[7:].strip())
            if rec:
                return rec

        # Header X-API-Key: <user>:<password> — cho script/tich hop
        api_key = request.headers.get("x-api-key") or ""
        if api_key and ":" in api_key:
            user, _, pwd = api_key.partition(":")
            if user in self.users and verify_password(pwd, self.users[user]["hash"]):
                return {"user": user, "role": self.users[user]["role"]}

        # Cookie phien
        rec = self.session(request.cookies.get("ppe_session"))
        if rec:
            return rec

        # localhost mien dang nhap (tien cho van hanh tai may chu)
        if self.allow_localhost:
            host = request.client.host if request.client else ""
            if host in ("127.0.0.1", "::1", "localhost"):
                return {"user": "localhost", "role": "admin"}

        return None


def required_role(method: str, path: str) -> str:
    """Suy ra vai tro toi thieu tu dong yeu cau."""
    if path.startswith("/api/auth/"):
        return "viewer"
    if path.startswith(("/static", "/evidence", "/api/snapshot", "/api/stream",
                        "/api/events/stream")):
        return "viewer"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "viewer"
    if path.startswith("/api/cameras") and method in ("POST", "PATCH", "PUT", "DELETE"):
        return "admin"
    if path.startswith("/api/config"):
        return "admin"
    if path.startswith("/api/violations") and method == "POST":
        return "operator"
    return "operator"


def has_role(role: str, needed: str) -> bool:
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(needed, 99)
