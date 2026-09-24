"""설정 로딩과 Redirect URI 검증 테스트.

Spotify의 2025년 Redirect URI 규칙을 Dashboard에 등록하기 *전에*
걸러 주는 것이 이 검증의 목적이다.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings, _is_blank, _validate_redirect_uri, load_settings
from app.core.errors import ConfigError


# ---------------------------------------------------------------------------
#  Redirect URI 규칙
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:8888/callback",
        "http://127.0.0.1:9999/callback",
        "http://[::1]:8888/callback",
        "https://example.com/callback",
    ],
)
def test_accepts_valid_redirect_uris(uri: str):
    _validate_redirect_uri(uri)  # 예외가 없으면 통과


def test_rejects_localhost():
    """Spotify가 2025년부터 금지한 형태. 가장 흔한 실수다."""
    with pytest.raises(ConfigError) as exc:
        _validate_redirect_uri("http://localhost:8888/callback")
    assert "localhost" in exc.value.user_message
    assert "127.0.0.1" in (exc.value.hint or "")


def test_rejects_loopback_without_port():
    with pytest.raises(ConfigError) as exc:
        _validate_redirect_uri("http://127.0.0.1/callback")
    assert "포트" in exc.value.user_message


def test_rejects_plain_http_on_public_host():
    """루프백이 아니면 HTTPS여야 한다."""
    with pytest.raises(ConfigError):
        _validate_redirect_uri("http://example.com/callback")


@pytest.mark.parametrize("uri", ["ftp://127.0.0.1:8888/cb", "not-a-url", ""])
def test_rejects_malformed(uri: str):
    with pytest.raises(ConfigError):
        _validate_redirect_uri(uri)


# ---------------------------------------------------------------------------
#  자리표시자 감지
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["", "   ", None, "여기에_본인의_Client_ID를_붙여넣으세요", "your_client_id", "xxxxxxxx", "<client-id>"],
)
def test_detects_unfilled_placeholders(value):
    """.env.example을 복사만 하고 안 채운 경우를 잡아야 한다."""
    assert _is_blank(value)


def test_real_client_id_is_not_blank():
    assert not _is_blank("6d0dfc90b867482ca7843c3fd28e5a3e")


# ---------------------------------------------------------------------------
#  .env 로딩
# ---------------------------------------------------------------------------


def _write_env(tmp_path, body: str):
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_missing_env_file_gives_actionable_error(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_settings(tmp_path / "nope.env")
    assert "copy .env.example .env" in (exc.value.hint or "")


def test_missing_client_id_gives_actionable_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    env = _write_env(tmp_path, "SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback\n")
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    assert "developer.spotify.com" in (exc.value.hint or "")


def test_poll_interval_is_floored_to_protect_rate_limit(tmp_path, monkeypatch):
    """너무 짧은 폴링은 Rate Limit을 유발하므로 500ms로 올린다."""
    for key in ("SPOTIFY_CLIENT_ID", "DECK_POLL_INTERVAL_MS"):
        monkeypatch.delenv(key, raising=False)
    env = _write_env(
        tmp_path,
        "SPOTIFY_CLIENT_ID=abc123def456\nDECK_POLL_INTERVAL_MS=50\n",
    )
    assert load_settings(env).poll_interval_ms == 500


def test_invalid_numeric_setting_falls_back(tmp_path, monkeypatch):
    for key in ("SPOTIFY_CLIENT_ID", "DECK_POLL_INTERVAL_MS"):
        monkeypatch.delenv(key, raising=False)
    env = _write_env(tmp_path, "SPOTIFY_CLIENT_ID=abc123def456\nDECK_POLL_INTERVAL_MS=빠르게\n")
    assert load_settings(env).poll_interval_ms == 1000


@pytest.mark.parametrize("mode,expected", [("live", "live"), ("off", "off"), ("garbage", "auto")])
def test_wave_mode_validation(tmp_path, monkeypatch, mode, expected):
    for key in ("SPOTIFY_CLIENT_ID", "DECK_WAVE_MODE"):
        monkeypatch.delenv(key, raising=False)
    env = _write_env(tmp_path, f"SPOTIFY_CLIENT_ID=abc123def456\nDECK_WAVE_MODE={mode}\n")
    assert load_settings(env).wave_mode == expected


# ---------------------------------------------------------------------------
#  파생 값
# ---------------------------------------------------------------------------


def test_callback_parts_parsed_from_uri():
    s = Settings(client_id="x" * 32, redirect_uri="http://127.0.0.1:9100/cb")
    assert s.callback_host == "127.0.0.1"
    assert s.callback_port == 9100
    assert s.callback_path == "/cb"


def test_pkce_used_when_no_secret():
    assert Settings(client_id="x" * 32, redirect_uri="http://127.0.0.1:8888/cb").uses_pkce


def test_client_id_is_masked_for_logs():
    s = Settings(client_id="6d0dfc90b867482ca7843c3fd28e5a3e", redirect_uri="http://127.0.0.1:8888/cb")
    masked = s.masked_client_id()
    assert masked.startswith("6d0d")
    assert masked.endswith("5a3e")
    assert "fc90b867482ca7843c3fd28e" not in masked
