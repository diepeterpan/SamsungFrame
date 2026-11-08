import pytest
from unittest.mock import MagicMock
from fastapi import Request, HTTPException
from service.main import supervisor
from service.config.settings import DeviceConfig, OIDCConfig
from service.auth import (
    serializer,
    generate_pkce,
    get_current_user,
    check_authorized,
    COOKIE_NAME
)

def test_pkce_generation():
    verifier, challenge = generate_pkce()
    assert len(verifier) >= 43
    assert len(challenge) > 20
    assert "=" not in challenge

def test_session_serialization_and_deserialization():
    token = serializer.dumps({"username": "john.doe", "logged_in_at": 123456})
    req = MagicMock(spec=Request)
    req.cookies = {COOKIE_NAME: token}
    
    user = get_current_user(req)
    assert user is not None
    assert user["username"] == "john.doe"

def test_anonymous_access_when_oidc_disabled():
    supervisor.config.oidc.enabled = False
    req = MagicMock(spec=Request)
    req.cookies = {}
    
    # Should succeed without error when OIDC is disabled
    res = check_authorized(req, supervisor.config)
    assert res["authenticated"] is True

def test_anonymous_access_blocked_when_oidc_enabled():
    supervisor.config.oidc.enabled = True
    req = MagicMock(spec=Request)
    req.cookies = {}
    
    # Should raise 401 when OIDC is enabled and no cookie is present
    with pytest.raises(HTTPException) as exc_info:
        check_authorized(req, supervisor.config)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication required"

def test_authenticated_user_access_when_oidc_enabled():
    supervisor.config.oidc.enabled = True
    token = serializer.dumps({"username": "alice", "logged_in_at": 100000})
    req = MagicMock(spec=Request)
    req.cookies = {COOKIE_NAME: token}
    
    # Authenticated user succeeds
    res = check_authorized(req, supervisor.config)
    assert res["username"] == "alice"
    
    # Reset
    supervisor.config.oidc.enabled = False
