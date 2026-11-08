import os
import time
import json
import base64
import hashlib
import secrets
import logging
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from pydantic import BaseModel

from service.config.settings import save_config, DeviceConfig, OIDCConfig

logger = logging.getLogger("frame.auth")

SECRET_KEY = os.getenv("FRAME_SESSION_SECRET", "samsungframe-insecure-secret-key-change-me")
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="samsungframe-auth-session")
COOKIE_NAME = "frame_session"
SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days

router = APIRouter()

# Temporary store for PKCE verifiers & states: state -> {code_verifier: str, expires_at: float}
_AUTH_STATES: Dict[str, Dict[str, Any]] = {}

def _clean_expired_states():
    now = time.time()
    expired = [k for k, v in _AUTH_STATES.items() if v.get("expires_at", 0) < now]
    for k in expired:
        _AUTH_STATES.pop(k, None)

def generate_pkce():
    code_verifier = secrets.token_urlsafe(64)
    sha256_digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(sha256_digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge

def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    try:
        data = serializer.loads(cookie, max_age=SESSION_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None

def check_authorized(request: Request, supervisor_config: DeviceConfig):
    """Enforces authorization if OIDC is active. Raises 401 if unauthorized."""
    if not supervisor_config.oidc.enabled:
        return {"authenticated": True, "username": "anonymous"}
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

def _sync_http_request(url: str, method: str = "GET", data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> Dict[str, Any]:
    req = URLRequest(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        logger.error(f"HTTP Error calling {url}: {e.code} - {err_body}")
        raise HTTPException(status_code=502, detail=f"OIDC IdP HTTP {e.code}: {err_body}")
    except URLError as e:
        logger.error(f"URL Error connecting to {url}: {e.reason}")
        raise HTTPException(status_code=502, detail=f"OIDC connection error: {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error calling {url}: {e}")
        raise HTTPException(status_code=502, detail=f"OIDC request failed: {e}")

async def async_http_request(url: str, method: str = "GET", data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None, timeout: int = 15) -> Dict[str, Any]:
    return await asyncio.to_thread(_sync_http_request, url, method, data, headers, timeout)

async def fetch_discovery(discovery_url: str) -> Dict[str, Any]:
    url = discovery_url.rstrip("/")
    if not url.endswith("/.well-known/openid-configuration"):
        url = f"{url}/.well-known/openid-configuration"
    return await async_http_request(url, method="GET")

class OIDCUpdatePayload(BaseModel):
    enabled: bool
    discovery_url: str
    client_id: str
    client_secret: Optional[str] = None
    redirect_uri: str
    scopes: str = "openid profile email groups"
    token_endpoint_auth_method: str = "client_secret_post"
    require_pkce: bool = True

@router.get("/api/auth/status")
async def get_auth_status(request: Request):
    from service.main import supervisor
    oidc_cfg = supervisor.config.oidc
    user = get_current_user(request)
    return {
        "oidc_enabled": oidc_cfg.enabled,
        "authenticated": user is not None if oidc_cfg.enabled else True,
        "username": user.get("username") if user else None,
        "anonymous": user is None and oidc_cfg.enabled
    }

@router.get("/auth/login")
async def auth_login(request: Request):
    from service.main import supervisor
    oidc_cfg = supervisor.config.oidc
    if not oidc_cfg.enabled or not oidc_cfg.discovery_url or not oidc_cfg.client_id:
        raise HTTPException(status_code=400, detail="OIDC is not properly configured")

    _clean_expired_states()
    disco = await fetch_discovery(oidc_cfg.discovery_url)
    auth_endpoint = disco.get("authorization_endpoint")
    if not auth_endpoint:
        raise HTTPException(status_code=502, detail="Discovery document missing authorization_endpoint")

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    code_verifier, code_challenge = generate_pkce()

    _AUTH_STATES[state] = {
        "code_verifier": code_verifier,
        "expires_at": time.time() + 600,
        "token_endpoint": disco.get("token_endpoint"),
        "userinfo_endpoint": disco.get("userinfo_endpoint")
    }

    # Automatically derive redirect_uri if not explicitly set
    redirect_uri = oidc_cfg.redirect_uri
    if not redirect_uri:
        redirect_uri = str(request.url_for("auth_callback"))

    params = {
        "client_id": oidc_cfg.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": oidc_cfg.scopes,
        "state": state,
        "nonce": nonce,
    }
    if oidc_cfg.require_pkce:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"

    redirect_url = f"{auth_endpoint}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url)

@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    from service.main import supervisor
    oidc_cfg = supervisor.config.oidc
    if error:
        logger.error(f"OIDC callback error from IdP: {error}")
        return HTMLResponse(f"<h3>Authentication error: {error}</h3><p><a href='/'>Return to Dashboard</a></p>", status_code=400)

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state in callback")

    state_data = _AUTH_STATES.pop(state, None)
    if not state_data or state_data.get("expires_at", 0) < time.time():
        raise HTTPException(status_code=400, detail="Invalid or expired authentication state")

    token_endpoint = state_data.get("token_endpoint")
    userinfo_endpoint = state_data.get("userinfo_endpoint")

    if not token_endpoint or not userinfo_endpoint:
        disco = await fetch_discovery(oidc_cfg.discovery_url)
        token_endpoint = disco.get("token_endpoint")
        userinfo_endpoint = disco.get("userinfo_endpoint")

    redirect_uri = oidc_cfg.redirect_uri or str(request.url_for("auth_callback"))

    # Exchange authorization code for tokens
    token_params = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }

    if oidc_cfg.require_pkce:
        token_params["code_verifier"] = state_data["code_verifier"]

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    auth_method = oidc_cfg.token_endpoint_auth_method or "client_secret_post"
    if auth_method == "client_secret_basic":
        creds = base64.b64encode(f"{oidc_cfg.client_id}:{oidc_cfg.client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"
    else:  # client_secret_post
        token_params["client_id"] = oidc_cfg.client_id
        if oidc_cfg.client_secret:
            token_params["client_secret"] = oidc_cfg.client_secret

    token_body = urlencode(token_params).encode("utf-8")
    token_data = await async_http_request(token_endpoint, method="POST", data=token_body, headers=headers, timeout=15)

    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="Token response missing access_token")

    # Query userinfo endpoint to retrieve username
    userinfo_headers = {"Authorization": f"Bearer {access_token}"}
    userinfo = await async_http_request(userinfo_endpoint, method="GET", headers=userinfo_headers, timeout=10)

    # Extract display username
    username = (
        userinfo.get("preferred_username")
        or userinfo.get("name")
        or userinfo.get("email")
        or userinfo.get("sub")
        or "Authenticated User"
    )

    supervisor.add_log(f"User '{username}' logged in via OIDC.", "SUCCESS")

    session_cookie_val = serializer.dumps({"username": username, "logged_in_at": time.time()})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=COOKIE_NAME,
        value=session_cookie_val,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https"
    )
    return response

@router.get("/auth/logout")
async def auth_logout(request: Request):
    from service.main import supervisor
    user = get_current_user(request)
    if user:
        supervisor.add_log(f"User '{user.get('username')}' logged out.", "INFO")
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response

@router.get("/api/oidc/config")
async def get_oidc_config(request: Request):
    from service.main import supervisor
    if supervisor.config.oidc.enabled:
        check_authorized(request, supervisor.config)
    
    cfg = supervisor.config.oidc.model_dump()
    if cfg.get("client_secret"):
        cfg["client_secret_set"] = True
        cfg["client_secret"] = "********"
    else:
        cfg["client_secret_set"] = False
    return cfg

@router.post("/api/oidc/config")
async def update_oidc_config(request: Request, payload: OIDCUpdatePayload):
    from service.main import supervisor
    if supervisor.config.oidc.enabled:
        check_authorized(request, supervisor.config)

    current_secret = supervisor.config.oidc.client_secret
    secret_to_use = payload.client_secret
    if not secret_to_use or secret_to_use.startswith("****"):
        secret_to_use = current_secret

    new_oidc = OIDCConfig(
        enabled=payload.enabled,
        discovery_url=payload.discovery_url.strip(),
        client_id=payload.client_id.strip(),
        client_secret=secret_to_use,
        redirect_uri=payload.redirect_uri.strip(),
        scopes=payload.scopes.strip(),
        token_endpoint_auth_method=payload.token_endpoint_auth_method,
        require_pkce=payload.require_pkce
    )

    supervisor.config.oidc = new_oidc
    save_config(supervisor.config)
    supervisor.add_log(f"OIDC configuration updated (enabled={new_oidc.enabled}).", "INFO")
    return {"status": "ok", "enabled": new_oidc.enabled}
