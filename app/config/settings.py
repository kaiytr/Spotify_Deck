"""환경변수 로딩 및 앱 전역 설정.

.env 파일에서 값을 읽어 검증한 뒤 불변(frozen) Settings 객체로 제공한다.
Client ID/Secret은 이 모듈을 통해서만 접근하며, 코드 어디에도 하드코딩하지 않는다.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from app.core.errors import ConfigError

logger = logging.getLogger(__name__)

#: 프로젝트 루트 (app/config/settings.py -> app/config -> app -> 루트)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: .env 예시 파일에 남아 있는 자리표시자. 이 값이면 미입력으로 간주한다.
_PLACEHOLDER_PATTERN = re.compile(r"여기에|your[_-]?client|paste|xxx+|<.*>", re.IGNORECASE)


# ---------------------------------------------------------------------------
#  OAuth 스코프
# ---------------------------------------------------------------------------
#  "필요한 권한만 요청한다"는 요구사항에 따라 최소 집합만 선언한다.
#  각 스코프가 어느 기능에 쓰이는지 주석으로 남긴다.
SCOPES: tuple[str, ...] = (
    # 현재 재생 상태 + 기기 정보(볼륨/shuffle/repeat) 읽기  -> GET /me/player
    "user-read-playback-state",
    # 재생/일시정지/다음/이전/볼륨/seek/shuffle/repeat 제어  -> PUT,POST /me/player/*
    "user-modify-playback-state",
    # 현재 재생 중인 곡 읽기 (playback-state의 보조)        -> GET /me/player/currently-playing
    "user-read-currently-playing",
    # 좋아요 여부 조회                                       -> GET /me/library/contains
    "user-library-read",
    # 좋아요 추가/삭제                                       -> PUT,DELETE /me/library
    "user-library-modify",
)


@dataclass(frozen=True)
class Settings:
    """검증이 끝난 앱 설정."""

    client_id: str
    redirect_uri: str
    client_secret: str | None = None

    poll_interval_ms: int = 1000
    token_store: str = "auto"
    log_level: str = "INFO"
    wave_mode: str = "auto"

    scopes: tuple[str, ...] = field(default=SCOPES)

    # --- 파생 값 ---

    @property
    def callback_host(self) -> str:
        """OAuth 콜백을 받을 로컬 서버 호스트."""
        return urlparse(self.redirect_uri).hostname or "127.0.0.1"

    @property
    def callback_port(self) -> int:
        """OAuth 콜백을 받을 로컬 서버 포트."""
        return urlparse(self.redirect_uri).port or 8888

    @property
    def callback_path(self) -> str:
        """OAuth 콜백 경로. 예) '/callback'"""
        return urlparse(self.redirect_uri).path or "/"

    @property
    def scope_string(self) -> str:
        """인증 URL에 넣을 공백 구분 스코프 문자열."""
        return " ".join(self.scopes)

    @property
    def uses_pkce(self) -> bool:
        """Client Secret이 없으면 PKCE 플로우를 사용한다."""
        return not self.client_secret

    def masked_client_id(self) -> str:
        """로그 출력용 마스킹된 Client ID."""
        if len(self.client_id) <= 8:
            return "*" * len(self.client_id)
        return f"{self.client_id[:4]}{'*' * (len(self.client_id) - 8)}{self.client_id[-4:]}"


# ---------------------------------------------------------------------------
#  로딩 & 검증
# ---------------------------------------------------------------------------


def _is_blank(value: str | None) -> bool:
    """미입력이거나 .env.example의 자리표시자가 그대로 남아 있는지."""
    if value is None:
        return True
    value = value.strip()
    if not value:
        return True
    return bool(_PLACEHOLDER_PATTERN.search(value))


def _validate_redirect_uri(uri: str) -> None:
    """Spotify의 2025년 Redirect URI 규칙을 사전 검증한다.

    Dashboard에 등록하기 전에 여기서 걸러 주면
    브라우저에서 INVALID_CLIENT 에러를 보는 것보다 훨씬 친절하다.

    규칙:
      * loopback이 아니면 HTTPS여야 한다.
      * loopback은 반드시 명시적 IP(127.0.0.1 / [::1])여야 한다.
      * 'localhost'는 금지.
    """
    parsed = urlparse(uri)

    if parsed.scheme not in ("http", "https"):
        raise ConfigError(
            f"SPOTIFY_REDIRECT_URI의 형식이 잘못되었습니다: {uri}",
            hint="예시: http://127.0.0.1:8888/callback",
        )

    host = parsed.hostname or ""

    if host == "localhost":
        raise ConfigError(
            "Redirect URI에 'localhost'는 사용할 수 없습니다.",
            hint=(
                "Spotify 정책에 따라 명시적 IP를 써야 합니다.\n"
                "  .env 와 Dashboard 양쪽을 다음으로 바꿔 주세요:\n"
                "  http://127.0.0.1:8888/callback"
            ),
            detail=f"redirect_uri={uri}",
        )

    is_loopback = host in ("127.0.0.1", "::1")

    if parsed.scheme == "http" and not is_loopback:
        raise ConfigError(
            "Redirect URI가 http이면 루프백 주소여야 합니다.",
            hint="http://127.0.0.1:8888/callback 을 사용하거나 https를 쓰세요.",
            detail=f"redirect_uri={uri}",
        )

    if is_loopback and parsed.port is None:
        raise ConfigError(
            "Redirect URI에 포트 번호가 없습니다.",
            hint="예시: http://127.0.0.1:8888/callback",
            detail=f"redirect_uri={uri}",
        )


def load_settings(env_file: Path | None = None, *, require_client_id: bool = True) -> Settings:
    """.env를 읽어 Settings를 만든다.

    Args:
        env_file: 사용할 .env 경로. None이면 프로젝트 루트의 .env.
        require_client_id: False면 Client ID가 없어도 예외를 던지지 않는다.
            (환경 점검 스크립트에서 사용)

    Raises:
        ConfigError: .env가 없거나 필수 값이 비어 있을 때.
    """
    env_path = env_file or (PROJECT_ROOT / ".env")

    if env_path.exists():
        load_dotenv(env_path, override=False)
        logger.debug("환경변수 로드: %s", env_path)
    elif require_client_id:
        raise ConfigError(
            ".env 파일을 찾을 수 없습니다.",
            hint=(
                "프로젝트 폴더에서 아래 명령을 실행한 뒤 Client ID를 채워 주세요:\n"
                "  copy .env.example .env"
            ),
            detail=f"기대 경로: {env_path}",
        )

    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()

    if require_client_id and _is_blank(client_id):
        raise ConfigError(
            "SPOTIFY_CLIENT_ID가 설정되지 않았습니다.",
            hint=(
                "https://developer.spotify.com/dashboard 에서 앱을 만들고\n"
                "Client ID를 .env 파일에 붙여넣어 주세요."
            ),
        )

    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback").strip()
    _validate_redirect_uri(redirect_uri)

    secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    client_secret = None if _is_blank(secret) else secret

    # --- 폴링 주기 ---
    raw_interval = os.getenv("DECK_POLL_INTERVAL_MS", "1000").strip()
    try:
        poll_interval_ms = int(raw_interval)
    except ValueError:
        logger.warning("DECK_POLL_INTERVAL_MS 값이 잘못되어 기본값 1000을 사용합니다: %r", raw_interval)
        poll_interval_ms = 1000

    # Rate Limit 보호: 500ms 미만은 허용하지 않는다.
    if poll_interval_ms < 500:
        logger.warning("폴링 주기가 너무 짧아 500ms로 올립니다 (요청값 %dms).", poll_interval_ms)
        poll_interval_ms = 500

    token_store = os.getenv("DECK_TOKEN_STORE", "auto").strip().lower()
    if token_store not in ("auto", "keyring", "file"):
        logger.warning("DECK_TOKEN_STORE 값이 잘못되어 'auto'를 사용합니다: %r", token_store)
        token_store = "auto"

    wave_mode = os.getenv("DECK_WAVE_MODE", "auto").strip().lower()
    if wave_mode not in ("auto", "live", "simulated", "off"):
        logger.warning("DECK_WAVE_MODE 값이 잘못되어 'auto'를 사용합니다: %r", wave_mode)
        wave_mode = "auto"

    log_level = os.getenv("DECK_LOG_LEVEL", "INFO").strip().upper()
    if log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        log_level = "INFO"

    return Settings(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        poll_interval_ms=poll_interval_ms,
        token_store=token_store,
        wave_mode=wave_mode,
        log_level=log_level,
    )
