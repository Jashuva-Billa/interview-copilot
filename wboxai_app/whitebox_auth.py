"""Whitebox Learning browser authentication helpers.

This module is intentionally UI-free. The desktop app opens the user's browser
and listens on a local callback URL, while this module owns state, PKCE, token
exchange, user mapping, and best-effort profile sync.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://www.whitebox-learning.com"
DEFAULT_SCOPES = "openid profile email"


@dataclass(frozen=True, slots=True)
class WhiteboxAuthSettings:
    base_url: str = DEFAULT_BASE_URL
    auth_mode: str = "auto"
    authorization_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: str = DEFAULT_SCOPES
    callback_port: int = 12180
    require_state: bool = True
    issuer: str = ""
    audience: str = ""
    logout_url: str = ""

    @property
    def resolved_mode(self) -> str:
        if self.auth_mode and self.auth_mode != "auto":
            return self.auth_mode
        if self.authorization_url and self.token_url and self.client_id:
            return "oidc"
        return "legacy_token"


@dataclass(frozen=True, slots=True)
class AuthRequest:
    login_url: str
    callback_url: str
    state: str
    nonce: str
    code_verifier: str
    mode: str


@dataclass(slots=True)
class AuthResult:
    authenticated: bool
    user: dict[str, Any] = field(default_factory=dict)
    auth_provider: str = "whitebox"
    auth_mode: str = ""
    base_url: str = DEFAULT_BASE_URL
    access_token: str = ""
    id_token: str = ""
    error: str = ""
    error_description: str = ""

    def session_payload(self) -> dict[str, Any]:
        user = dict(self.user)
        return {
            "logged_in": self.authenticated,
            "authenticated": self.authenticated,
            "method": "whitebox_learning",
            "auth_provider": self.auth_provider,
            "auth_mode": "WHITEBOX",
            "candidate_mode": "WHITEBOX",
            "base_url": self.base_url,
            "user": user,
            "whitebox_user_id": user.get("whitebox_user_id") or user.get("id") or "",
            "email": user.get("email") or "",
            "name": user.get("name") or "",
            "session_id": secrets.token_urlsafe(24),
            "created_at": int(time.time()),
        }


def load_settings(app_root: Path | None = None) -> WhiteboxAuthSettings:
    values: dict[str, str] = {}
    root = app_root or Path(__file__).resolve().parent
    for env_file in (root / ".env", root.parent / ".env"):
        values.update(_read_env_file(env_file))
    values.update({k: v for k, v in os.environ.items() if k.startswith("WHITEBOX_")})

    base_url = _clean_url(values.get("WHITEBOX_BASE_URL", DEFAULT_BASE_URL))
    return WhiteboxAuthSettings(
        base_url=base_url,
        auth_mode=values.get("WHITEBOX_AUTH_MODE", "auto").strip().lower() or "auto",
        authorization_url=_clean_url(values.get("WHITEBOX_AUTHORIZATION_URL", "")),
        token_url=_clean_url(values.get("WHITEBOX_TOKEN_URL", "")),
        userinfo_url=_clean_url(values.get("WHITEBOX_USERINFO_URL", "")),
        client_id=values.get("WHITEBOX_CLIENT_ID", "").strip(),
        client_secret=values.get("WHITEBOX_CLIENT_SECRET", "").strip(),
        scopes=values.get("WHITEBOX_SCOPES", DEFAULT_SCOPES).strip() or DEFAULT_SCOPES,
        callback_port=int(values.get("WHITEBOX_CALLBACK_PORT", "12180") or "12180"),
        require_state=_env_bool(values.get("WHITEBOX_AUTH_REQUIRE_STATE", "true")),
        issuer=values.get("WHITEBOX_ISSUER", "").strip(),
        audience=values.get("WHITEBOX_AUDIENCE", values.get("WHITEBOX_CLIENT_ID", "")).strip(),
        logout_url=_clean_url(values.get("WHITEBOX_LOGOUT_URL", "")),
    )


def build_auth_request(settings: WhiteboxAuthSettings, callback_url: str) -> AuthRequest:
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = _pkce_verifier()
    mode = settings.resolved_mode

    if mode == "oidc":
        challenge = _pkce_challenge(verifier)
        params = {
            "response_type": "code",
            "client_id": settings.client_id,
            "redirect_uri": callback_url,
            "scope": settings.scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        login_url = f"{settings.authorization_url}?{urllib.parse.urlencode(params)}"
    else:
        params = {
            "redirect_uri": callback_url,
            "callback": callback_url,
            "state": state,
        }
        login_url = f"{settings.base_url.rstrip('/')}/login?{urllib.parse.urlencode(params)}"

    return AuthRequest(
        login_url=login_url,
        callback_url=callback_url,
        state=state,
        nonce=nonce,
        code_verifier=verifier,
        mode=mode,
    )


def complete_browser_callback(
    *,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    settings: WhiteboxAuthSettings,
    request: AuthRequest,
) -> AuthResult:
    params = _callback_params(method, path, headers, body)
    if params.get("error"):
        return AuthResult(
            authenticated=False,
            auth_mode=request.mode,
            base_url=settings.base_url,
            error=params.get("error", "authorization_error"),
            error_description=params.get("error_description", ""),
        )

    returned_state = params.get("state", "")
    if settings.require_state and returned_state != request.state:
        return AuthResult(
            authenticated=False,
            auth_mode=request.mode,
            base_url=settings.base_url,
            error="invalid_state",
            error_description="Authentication state did not match.",
        )

    code = params.get("code", "")
    token = _first_present(params, ("access_token", "token", "jwt", "jwt_token", "auth_token"))

    if code:
        return exchange_authorization_code(code, settings, request)
    if token:
        return authenticate_bearer_token(token, settings, request.mode)

    return AuthResult(
        authenticated=False,
        auth_mode=request.mode,
        base_url=settings.base_url,
        error="missing_auth_result",
        error_description="Callback did not include an authorization code or token.",
    )


def exchange_authorization_code(
    code: str,
    settings: WhiteboxAuthSettings,
    request: AuthRequest,
) -> AuthResult:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": request.callback_url,
        "client_id": settings.client_id,
        "code_verifier": request.code_verifier,
    }
    if settings.client_secret:
        data["client_secret"] = settings.client_secret
    try:
        token_response = _json_request(
            settings.token_url,
            method="POST",
            data=data,
            headers={"Accept": "application/json"},
            timeout=12,
        )
    except Exception as exc:
        return AuthResult(
            authenticated=False,
            auth_mode=request.mode,
            base_url=settings.base_url,
            error="token_exchange_failed",
            error_description=str(exc),
        )

    access_token = str(token_response.get("access_token", "") or "")
    id_token = str(token_response.get("id_token", "") or "")
    claims = decode_jwt_payload(id_token) if id_token else {}
    validation_error = validate_id_token_claims(claims, settings, request) if claims else ""
    if validation_error:
        return AuthResult(
            authenticated=False,
            auth_mode=request.mode,
            base_url=settings.base_url,
            error="invalid_id_token",
            error_description=validation_error,
        )

    userinfo = fetch_userinfo(access_token, settings) if access_token else {}
    user = map_whitebox_user(userinfo or claims)
    if not user.get("whitebox_user_id"):
        return AuthResult(
            authenticated=False,
            auth_mode=request.mode,
            base_url=settings.base_url,
            error="missing_user_identity",
            error_description="Whitebox identity did not include a stable user id.",
        )
    return AuthResult(
        authenticated=True,
        user=user,
        auth_mode=request.mode,
        base_url=settings.base_url,
        access_token=access_token,
        id_token=id_token,
    )


def authenticate_bearer_token(
    token: str,
    settings: WhiteboxAuthSettings,
    mode: str = "legacy_token",
) -> AuthResult:
    userinfo = fetch_userinfo(token, settings)
    claims = decode_jwt_payload(token)
    user = map_whitebox_user(userinfo or claims)
    if not user.get("whitebox_user_id"):
        # Legacy Whitebox redirects may only give a bearer token. Keep the auth
        # successful but mark identity unknown rather than inventing an email id.
        user = {
            "id": "",
            "whitebox_user_id": "",
            "email": "",
            "name": "",
            "roles": [],
            "authenticated": True,
        }
    return AuthResult(
        authenticated=True,
        user=user,
        auth_mode=mode,
        base_url=settings.base_url,
        access_token=token,
    )


def fetch_userinfo(token: str, settings: WhiteboxAuthSettings) -> dict[str, Any]:
    endpoints = []
    if settings.userinfo_url:
        endpoints.append(settings.userinfo_url)
    base = settings.base_url.rstrip("/")
    endpoints.extend(
        [
            f"{base}/api/auth/me",
            f"{base}/api/me",
            f"{base}/api/user",
            f"{base}/api/user/profile",
            f"{base}/api/candidate/profile",
        ]
    )
    for url in endpoints:
        try:
            result = _json_request(
                url,
                method="GET",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=8,
            )
            if isinstance(result, dict) and result:
                return result
        except Exception:
            continue
    return {}


def fetch_profile_sync_data(token: str, base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    endpoints = [
        f"{base}/api/candidate/sync",
        f"{base}/api/wbox-sync",
        f"{base}/api/wboxai/sync",
        f"{base}/api/candidate/profile",
        f"{base}/api/candidate/config",
        f"{base}/api/candidate/resume",
        f"{base}/api/candidate/llm-keys",
        f"{base}/api/candidate/llm",
        f"{base}/api/candidate/keys",
        f"{base}/api/user/resume",
        f"{base}/api/user/profile",
        f"{base}/api/user/llm-keys",
        f"{base}/api/user/keys",
        f"{base}/api/user_dashboard/my-resume",
        f"{base}/api/user_dashboard/resume",
        f"{base}/api/user_dashboard/my-llm-setup",
        f"{base}/api/user_dashboard/llm",
        f"{base}/api/resume",
        f"{base}/api/llm",
        f"{base}/api/llm-keys",
        f"{base}/api/keys",
        f"{base}/api/profile",
        f"{base}/api/me",
        f"{base}/api/auth/me",
        f"{base}/api/user",
    ]
    combined: dict[str, Any] = {}
    for url in endpoints:
        for method in ("GET", "POST"):
            try:
                result = _json_request(
                    url,
                    method=method,
                    data={} if method == "POST" else None,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    timeout=8,
                )
                if isinstance(result, dict):
                    combined.update(result)
                elif isinstance(result, list):
                    combined[url.rstrip("/").split("/")[-1]] = result
            except Exception:
                continue
    return combined


def map_whitebox_user(claims: dict[str, Any]) -> dict[str, Any]:
    data = _unwrap_user(claims)
    whitebox_id = _string_first(data, ("sub", "id", "user_id", "uid", "_id", "whitebox_user_id"))
    email = _string_first(data, ("email", "user_email"))
    name = _string_first(data, ("name", "full_name", "displayName", "display_name"))
    if not name:
        first = _string_first(data, ("given_name", "first_name"))
        last = _string_first(data, ("family_name", "last_name"))
        name = f"{first} {last}".strip()
    roles = data.get("roles") or data.get("role") or []
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list):
        roles = []
    return {
        "id": whitebox_id,
        "whitebox_user_id": whitebox_id,
        "email": email,
        "name": name,
        "roles": roles,
        "authenticated": True,
    }


def validate_id_token_claims(
    claims: dict[str, Any],
    settings: WhiteboxAuthSettings,
    request: AuthRequest,
) -> str:
    if not claims:
        return "missing claims"
    now = int(time.time())
    exp = int(claims.get("exp", 0) or 0)
    if exp and exp < now:
        return "token expired"
    if settings.issuer and claims.get("iss") != settings.issuer:
        return "issuer mismatch"
    audience = settings.audience or settings.client_id
    if audience:
        aud = claims.get("aud")
        if isinstance(aud, list):
            if audience not in aud:
                return "audience mismatch"
        elif aud and aud != audience:
            return "audience mismatch"
    nonce = claims.get("nonce")
    if nonce and nonce != request.nonce:
        return "nonce mismatch"
    return ""


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def success_html() -> bytes:
    return b"""<!DOCTYPE html>
<html><head><title>WboxAI Login Complete</title>
<style>body{background:#121824;color:#e2e8f0;font-family:Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}.card{background:#1e293b;padding:44px 38px;border-radius:16px;border:1px solid #334155;text-align:center;max-width:430px}.icon{font-size:52px;margin-bottom:16px}h1{color:#38bdf8;margin:0 0 12px}p{color:#94a3b8;font-size:15px;margin:0}</style>
</head><body><div class="card"><div class="icon">&#10003;</div><h1>Login Complete</h1><p>You can close this browser tab and return to WboxAI.</p></div></body></html>"""


def error_html(message: str) -> bytes:
    safe = message.replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html><head><title>WboxAI Login Failed</title>
<style>body{{background:#121824;color:#e2e8f0;font-family:Segoe UI,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}.card{{background:#1e293b;padding:44px 38px;border-radius:16px;border:1px solid #7f1d1d;text-align:center;max-width:460px}}h1{{color:#f87171;margin:0 0 12px}}p{{color:#cbd5e1;font-size:15px;margin:0}}</style>
</head><body><div class="card"><h1>Login Failed</h1><p>{safe}</p></div></body></html>""".encode("utf-8")


def _callback_params(method: str, path: str, headers: dict[str, str], body: bytes) -> dict[str, str]:
    parsed = urllib.parse.urlparse(path)
    values: dict[str, str] = {}
    for key, vals in urllib.parse.parse_qs(parsed.query).items():
        if vals:
            values[key] = vals[0]
    if method.upper() == "POST" and body:
        content_type = headers.get("Content-Type", headers.get("content-type", ""))
        if "application/json" in content_type:
            try:
                data = json.loads(body.decode("utf-8"))
                if isinstance(data, dict):
                    values.update({str(k): str(v) for k, v in data.items() if v is not None})
            except Exception:
                pass
        else:
            for key, vals in urllib.parse.parse_qs(body.decode("utf-8")).items():
                if vals:
                    values[key] = vals[0]
    return values


def _json_request(
    url: str,
    *,
    method: str,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
) -> dict[str, Any] | list[Any]:
    if not url:
        raise ValueError("missing URL")
    payload = None
    request_headers = dict(headers or {})
    if data is not None:
        if request_headers.get("Content-Type") == "application/json":
            payload = json.dumps(data).encode("utf-8")
        else:
            payload = urllib.parse.urlencode(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=payload, headers=request_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    except Exception:
        return {}
    return values


def _pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _clean_url(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _env_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _first_present(values: dict[str, str], names: tuple[str, ...]) -> str:
    lowered = {key.lower(): value for key, value in values.items()}
    for name in names:
        value = lowered.get(name.lower(), "")
        if value:
            return value
    for key, value in lowered.items():
        if any(name in key for name in ("token", "jwt", "auth")) and value:
            return value
    return ""


def _unwrap_user(data: dict[str, Any]) -> dict[str, Any]:
    current = data
    for key in ("user", "profile", "data", "candidate"):
        value = current.get(key)
        if isinstance(value, dict):
            current = value
    return current


def _string_first(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text:
                return text
    return ""

