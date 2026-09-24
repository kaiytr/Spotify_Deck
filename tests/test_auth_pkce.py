"""PKCE 인증 및 토큰 처리 테스트.

네트워크 없이 순수 계산과 URL 구성만 검증한다.
"""

from __future__ import annotations

import string
import time
import urllib.parse

import pytest

from app.config.settings import Settings
from app.core.errors import NetworkError
from app.spotify import auth as auth_module
from app.spotify.auth import (
    SpotifyAuth,
    generate_code_challenge,
    generate_code_verifier,
)
from app.spotify.tokens import NullTokenStore, TokenBundle

UNRESERVED = set(string.ascii_letters + string.digits + "-._~")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        client_id="test_client_id_0123456789abcdef",
        redirect_uri="http://127.0.0.1:8888/callback",
    )


# ---------------------------------------------------------------------------
#  PKCE 규격 (RFC 7636)
# ---------------------------------------------------------------------------


def test_challenge_matches_rfc7636_test_vector():
    """RFC 7636 Appendix B의 공식 테스트 벡터와 일치해야 한다.

    이게 틀리면 Spotify가 code 교환을 거부한다.
    """
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert generate_code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("length", [43, 64, 96, 128])
def test_verifier_length_and_charset(length: int):
    verifier = generate_code_verifier(length)
    assert len(verifier) == length
    assert set(verifier) <= UNRESERVED


@pytest.mark.parametrize("length", [42, 129, 0])
def test_verifier_rejects_out_of_spec_length(length: int):
    with pytest.raises(ValueError):
        generate_code_verifier(length)


def test_verifier_is_random():
    assert generate_code_verifier() != generate_code_verifier()


def test_challenge_has_no_base64_padding():
    """'=' 패딩이 남으면 URL 파라미터로 전달할 때 깨진다."""
    assert "=" not in generate_code_challenge(generate_code_verifier())


# ---------------------------------------------------------------------------
#  인증 URL
# ---------------------------------------------------------------------------


def test_authorize_url_uses_code_flow_not_implicit(settings):
    """Implicit Grant(response_type=token)는 절대 쓰면 안 된다."""
    auth = SpotifyAuth(settings, NullTokenStore())
    url = auth.build_authorize_url("CHAL", "STATE")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert url.startswith("https://accounts.spotify.com/authorize?")
    assert query["response_type"] == ["code"]
    assert "token" not in query["response_type"]


def test_authorize_url_carries_pkce_and_state(settings):
    auth = SpotifyAuth(settings, NullTokenStore())
    url = auth.build_authorize_url("MY_CHALLENGE", "MY_STATE")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)

    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == ["MY_CHALLENGE"]
    assert query["state"] == ["MY_STATE"]
    assert query["client_id"] == [settings.client_id]
    assert query["redirect_uri"] == ["http://127.0.0.1:8888/callback"]


def test_authorize_url_requests_only_needed_scopes(settings):
    """최소 권한 원칙. 쓰지 않는 스코프가 섞이면 안 된다."""
    auth = SpotifyAuth(settings, NullTokenStore())
    url = auth.build_authorize_url("C", "S")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    scopes = set(query["scope"][0].split())

    assert scopes == {
        "user-read-playback-state",
        "user-modify-playback-state",
        "user-read-currently-playing",
        "user-library-read",
        "user-library-modify",
    }


def test_callback_log_redacts_authorization_code(caplog):
    """인증 코드가 로그에 남으면 로그 공유 시 유출된다."""
    handler_cls = auth_module._make_handler(auth_module._CallbackResult(), "/callback")
    instance = handler_cls.__new__(handler_cls)

    with caplog.at_level("DEBUG", logger="app.spotify.auth"):
        handler_cls.log_message(
            instance,
            '"%s" %s %s',
            "GET /callback?code=SECRET_CODE_VALUE&state=SECRET_STATE HTTP/1.1",
            "200",
            "-",
        )

    logged = caplog.text
    assert "SECRET_CODE_VALUE" not in logged
    assert "SECRET_STATE" not in logged
    assert "/callback" in logged


# ---------------------------------------------------------------------------
#  토큰 요청 재시도
# ---------------------------------------------------------------------------


def test_post_token_retries_transient_connection_error(settings, monkeypatch):
    """DNS 실패는 요청이 나가지도 못한 것이므로 재시도가 안전하다.

    한 번 실패했다고 '다시 로그인하세요'가 뜨면 앱이 불안정해 보인다.
    """
    import requests

    calls = {"n": 0}

    def flaky_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("getaddrinfo failed")
        return _FakeResponse(200, {"access_token": "AT", "expires_in": 3600})

    monkeypatch.setattr(requests, "post", flaky_post)
    monkeypatch.setattr(auth_module.time, "sleep", lambda _s: None)

    auth = SpotifyAuth(settings, NullTokenStore())
    payload = auth._post_token({"grant_type": "refresh_token"})

    assert payload["access_token"] == "AT"
    assert calls["n"] == 3, "두 번 재시도한 뒤 성공해야 한다"


def test_post_token_gives_up_after_retries(settings, monkeypatch):
    import requests

    def always_fail(*args, **kwargs):
        raise requests.exceptions.ConnectionError("network down")

    monkeypatch.setattr(requests, "post", always_fail)
    monkeypatch.setattr(auth_module.time, "sleep", lambda _s: None)

    auth = SpotifyAuth(settings, NullTokenStore())
    with pytest.raises(NetworkError):
        auth._post_token({"grant_type": "refresh_token"})


def test_post_token_does_not_retry_ssl_error(settings, monkeypatch):
    """SSL 오류는 설정 문제라 재시도해도 똑같이 실패한다."""
    import requests

    calls = {"n": 0}

    def ssl_fail(*args, **kwargs):
        calls["n"] += 1
        raise requests.exceptions.SSLError("cert verify failed")

    monkeypatch.setattr(requests, "post", ssl_fail)

    auth = SpotifyAuth(settings, NullTokenStore())
    with pytest.raises(NetworkError):
        auth._post_token({"grant_type": "refresh_token"})
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
#  토큰 묶음
# ---------------------------------------------------------------------------


def test_refresh_keeps_existing_refresh_token():
    """갱신 응답에 refresh_token이 없으면 기존 값을 유지해야 한다."""
    previous = TokenBundle("OLD_AT", "KEEP_ME", time.time() + 3600, scope="a b")
    updated = TokenBundle.from_response({"access_token": "NEW_AT", "expires_in": 3600}, previous=previous)

    assert updated.access_token == "NEW_AT"
    assert updated.refresh_token == "KEEP_ME"
    assert updated.scope == "a b"


def test_refresh_adopts_rotated_refresh_token():
    """Spotify는 리프레시 토큰을 회전시킬 수 있다."""
    previous = TokenBundle("OLD", "OLD_RT", time.time() + 3600)
    updated = TokenBundle.from_response(
        {"access_token": "NEW", "refresh_token": "NEW_RT", "expires_in": 3600},
        previous=previous,
    )
    assert updated.refresh_token == "NEW_RT"


def test_expiry_uses_safety_margin():
    """만료 직전에 요청이 나가는 경쟁 상태를 막아야 한다."""
    almost = TokenBundle("A", "R", time.time() + 30)   # 30초 남음 < 60초 여유
    fresh = TokenBundle("A", "R", time.time() + 3600)

    assert almost.is_expired
    assert not fresh.is_expired


def test_has_scope():
    bundle = TokenBundle("A", "R", time.time() + 3600, scope="user-library-read user-library-modify")
    assert bundle.has_scope("user-library-read")
    assert not bundle.has_scope("playlist-read-private")


class _FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status_code = status
        self._payload = payload
        self.text = str(payload)
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return self._payload
