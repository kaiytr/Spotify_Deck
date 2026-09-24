"""HTTP 계층 테스트 — 오류 번역과 URI 인코딩.

이 계층의 유일한 책임은 저수준 오류를 사용자 언어의 DeckError로 바꾸는 것이다.
같은 403이라도 원인이 셋(Premium 아님 / 허용 목록 미등록 / 금지된 동작)이라
구분해야 사용자가 조치할 수 있다.
"""

from __future__ import annotations

import pytest

from app.core.errors import (
    AuthError,
    NoActiveDeviceError,
    PremiumRequiredError,
    QuotaExceededError,
    RateLimitError,
    RestrictedActionError,
)
from app.spotify.client import SpotifyClient, _is_safe_to_retry, join_uris, track_uri


class _Resp:
    def __init__(self, status: int, payload=None, text: str = "", headers: dict | None = None):
        self.status_code = status
        self._payload = payload
        self.text = text or (str(payload) if payload else "")
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def client():
    return SpotifyClient(auth=None)  # 오류 해석만 쓰므로 인증 객체가 필요 없다


# ---------------------------------------------------------------------------
#  403 원인 구분
# ---------------------------------------------------------------------------


def test_403_premium_required(client):
    resp = _Resp(403, {"error": {"status": 403, "message": "Player command failed: Premium required"}})
    err = client._interpret_403(resp)
    assert isinstance(err, PremiumRequiredError)
    assert "Premium" in err.user_message


def test_403_user_not_allowlisted(client):
    """Development Mode에서 가장 헷갈리는 오류. 조치 방법이 달라진다."""
    resp = _Resp(403, {"error": {"status": 403, "message": "User not registered in the Developer Dashboard"}})
    err = client._interpret_403(resp)
    assert isinstance(err, AuthError)
    assert "User Management" in (err.hint or "")


def test_403_restriction_violated(client):
    """이미 멈춘 것을 또 멈출 때 등. 광고 중 스킵도 여기에 해당한다."""
    resp = _Resp(403, {"error": {"status": 403, "message": "Player command failed: Restriction violated"}})
    assert isinstance(client._interpret_403(resp), RestrictedActionError)


def test_403_unknown_cause_does_not_assert_premium(client):
    """원인이 불분명하면 단정하지 말고 확인할 곳을 알려 줘야 한다."""
    err = client._interpret_403(_Resp(403, {"error": {"status": 403}}))
    assert "Premium" in (err.hint or "") and "허용 목록" in (err.hint or "")


def test_404_means_no_active_device(client):
    resp = _Resp(404, {"error": {"status": 404, "message": "Device not found"}})
    err = client._interpret_404(resp)
    assert isinstance(err, NoActiveDeviceError)
    assert "Spotify 앱" in (err.hint or "")


def test_malformed_error_body_does_not_crash(client):
    """오류 응답이 JSON이 아니어도 죽으면 안 된다."""
    client._interpret_403(_Resp(403, None, text="<html>Gateway</html>"))
    client._interpret_404(_Resp(404, None, text=""))


# ---------------------------------------------------------------------------
#  429 / 할당량
# ---------------------------------------------------------------------------


def test_quota_exceeded_is_distinct_from_rate_limit(client):
    """2026년부터 할당량 초과는 본문에 reason이 담긴다.

    기다리면 풀리는 Rate Limit과 달리 안내 문구가 달라야 한다.
    """
    resp = _Resp(429, {"reason": "QUOTA_EXCEEDED"}, headers={"Retry-After": "30"})
    with pytest.raises(QuotaExceededError) as exc:
        client._handle_rate_limit(resp, "GET", "/me/player", None, None, True, 0)
    assert "한도" in exc.value.user_message


def test_long_rate_limit_is_reported_not_slept(client):
    """오래 기다려야 하면 조용히 자지 말고 사용자에게 알린다."""
    resp = _Resp(429, {}, headers={"Retry-After": "120"})
    with pytest.raises(RateLimitError) as exc:
        client._handle_rate_limit(resp, "GET", "/me/player", None, None, True, 0)
    assert exc.value.retry_after == 120


# ---------------------------------------------------------------------------
#  재시도 안전성 (멱등성)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "HEAD"])
def test_idempotent_methods_are_retryable(method):
    assert _is_safe_to_retry(method)


def test_post_is_never_retried():
    """POST /me/player/next 가 두 번 나가면 곡을 두 개 건너뛴다."""
    assert not _is_safe_to_retry("POST")


# ---------------------------------------------------------------------------
#  라이브러리 URI (2026-02 신규 엔드포인트)
# ---------------------------------------------------------------------------


def test_track_id_becomes_uri():
    assert track_uri("7a3LWj5xSFhFRYmztS8wgK") == "spotify:track:7a3LWj5xSFhFRYmztS8wgK"


def test_existing_uri_is_left_alone():
    assert track_uri("spotify:track:abc") == "spotify:track:abc"


def test_uris_are_not_pre_encoded():
    """직접 URL 인코딩하면 requests가 '%'를 '%25'로 또 인코딩해 실패한다.

    실제로 이 버그를 겪었다:
        보낸 값   spotify%3Atrack%3Aabc
        실제 전송 uris=spotify%253Atrack%253Aabc
        서버 응답 400 Invalid Spotify URI: spotify%3Atrack%3Aabc
    """
    joined = join_uris(["spotify:track:abc", "spotify:album:xyz"])
    assert joined == "spotify:track:abc,spotify:album:xyz"
    assert "%3A" not in joined
    assert "%" not in joined


def test_single_uri_join():
    assert join_uris(["spotify:track:abc"]) == "spotify:track:abc"
