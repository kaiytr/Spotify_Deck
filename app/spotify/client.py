"""Spotify Web API HTTP 클라이언트.

이 계층의 유일한 책임은 **모든 저수준 오류를 DeckError로 번역하는 것**이다.
상위 계층(player, UI)은 requests 예외나 HTTP 상태 코드를 절대 보지 않는다.

    requests 예외 / HTTP 4xx·5xx  ──[이 파일]──>  DeckError  ──> UI가 한국어로 표시

처리하는 상황:
    * 인터넷 끊김 / DNS 실패 / 타임아웃 / SSL 오류  -> NetworkError
    * 401 만료                                      -> 토큰 자동 갱신 후 1회 재시도
    * 403 Premium 아님 / 허용 목록 미등록            -> PremiumRequiredError 등
    * 404 활성 기기 없음                             -> NoActiveDeviceError
    * 429 Rate Limit / 할당량 초과                   -> 자동 대기 재시도, 초과 시 예외
    * 5xx 서버 오류                                  -> 지수 백오프 재시도
    * 204 내용 없음                                  -> None 반환
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

from app.core.errors import (
    AuthError,
    DeckError,
    NetworkError,
    NoActiveDeviceError,
    PremiumRequiredError,
    QuotaExceededError,
    RateLimitError,
    RestrictedActionError,
    SpotifyApiError,
    TokenExpiredError,
)
from app.spotify.auth import SpotifyAuth

logger = logging.getLogger(__name__)

API_BASE = "https://api.spotify.com/v1"

#: 429 응답을 자동으로 기다렸다 재시도할 최대 대기 시간(초).
#: 이보다 길면 사용자에게 알리는 편이 낫다.
MAX_AUTO_RETRY_WAIT = 5

#: 5xx 서버 오류 재시도 횟수
SERVER_ERROR_RETRIES = 2

#: 요청 타임아웃 (연결, 읽기)
TIMEOUT = (5, 10)

#: 일시적 연결 끊김 재시도 횟수
NETWORK_RETRIES = 1


class SpotifyClient:
    """인증과 오류 번역을 담당하는 얇은 HTTP 래퍼.

    Thread-safe: UI 폴링 스레드와 사용자 조작이 동시에 호출해도 안전하다.
    """

    def __init__(self, auth: SpotifyAuth) -> None:
        self._auth = auth
        # Session은 TCP 연결을 재사용해 1초 폴링의 지연을 크게 줄인다.
        self._session = requests.Session()
        self._lock = threading.Lock()
        #: 429를 받았을 때 이 시각 전까지는 요청을 보내지 않는다.
        self._backoff_until = 0.0

    def close(self) -> None:
        self._session.close()

    # -- 공개 메서드 -------------------------------------------------------

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params=params or None)

    def put(self, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        return self.request("PUT", path, params=params, json=json)

    def post(self, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        return self.request("POST", path, params=params, json=json)

    def delete(self, path: str, *, params: dict | None = None, json: Any = None) -> Any:
        return self.request("DELETE", path, params=params, json=json)

    # -- 핵심 요청 처리 ----------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        _retry_auth: bool = True,
        _retry_server: int = SERVER_ERROR_RETRIES,
        _retry_network: int = NETWORK_RETRIES,
    ) -> Any:
        """API를 호출하고 파싱된 JSON을 반환한다.

        Returns:
            파싱된 JSON. 204(No Content)면 None.

        Raises:
            DeckError 계열. 그 밖의 예외는 던지지 않는다.
        """
        # 직전 429의 대기 시간이 남아 있으면 즉시 알린다.
        remaining = self._backoff_until - time.monotonic()
        if remaining > 0:
            raise RateLimitError(retry_after=int(remaining) + 1)

        url = path if path.startswith("http") else f"{API_BASE}{path}"

        # 토큰 획득 (필요 시 자동 갱신). 폴링 스레드에서 브라우저가 열리면 안 되므로
        # allow_interactive=False로 막는다.
        token = self._auth.get_access_token(allow_interactive=False)

        headers = {"Authorization": f"Bearer {token}"}
        if json is not None:
            headers["Content-Type"] = "application/json"

        try:
            with self._lock:
                resp = self._session.request(
                    method, url, headers=headers, params=params, json=json, timeout=TIMEOUT
                )
        except requests.exceptions.SSLError as exc:
            raise NetworkError(
                "보안 연결에 실패했습니다.",
                hint="백신이나 방화벽의 SSL 검사 설정을 확인해 주세요.",
                detail=str(exc),
            ) from exc
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            # 연결이 순간적으로 끊기는 일은 드물지 않다 (Wi-Fi 전환, TLS 핸드셰이크 리셋 등).
            # 한 번 실패했다고 사용자에게 오류를 띄우면 앱이 불안정해 보인다.
            if _retry_network > 0 and _is_safe_to_retry(method):
                logger.debug("연결 실패 - 재시도합니다 (%s %s): %s", method, path, exc)
                time.sleep(0.4)
                return self.request(
                    method, path, params=params, json=json,
                    _retry_auth=_retry_auth, _retry_server=_retry_server,
                    _retry_network=_retry_network - 1,
                )

            if isinstance(exc, requests.exceptions.Timeout):
                raise NetworkError(
                    "Spotify 응답이 없습니다.",
                    hint="네트워크가 불안정합니다. 연결되면 자동으로 복구됩니다.",
                    detail=str(exc),
                ) from exc
            raise NetworkError(detail=str(exc)) from exc
        except requests.exceptions.RequestException as exc:
            raise NetworkError(detail=str(exc)) from exc

        # --- 성공 ---
        if resp.status_code == 204 or not resp.content:
            return None

        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except ValueError:
                # 일부 제어 엔드포인트는 200에 빈 본문을 준다.
                return None

        # --- 401: 토큰 만료 → 갱신 후 1회 재시도 ---
        if resp.status_code == 401:
            if not _retry_auth:
                raise TokenExpiredError(detail=_body_snippet(resp))
            logger.debug("401 수신 - 토큰을 갱신하고 재시도합니다.")
            try:
                self._auth.refresh()
            except DeckError:
                raise  # TokenRefreshFailedError 등을 그대로 전달
            return self.request(
                method, path, params=params, json=json,
                _retry_auth=False, _retry_server=_retry_server,
                _retry_network=_retry_network,
            )

        # --- 429: Rate Limit / 할당량 초과 ---
        if resp.status_code == 429:
            return self._handle_rate_limit(
                resp, method, path, params, json, _retry_auth, _retry_server
            )

        # --- 403 / 404: 재생 제어 제약 ---
        if resp.status_code == 403:
            raise self._interpret_403(resp)

        if resp.status_code == 404:
            raise self._interpret_404(resp)

        # --- 5xx: 서버 오류 → 지수 백오프 재시도 ---
        if resp.status_code >= 500:
            if _retry_server > 0:
                wait = 0.5 * (2 ** (SERVER_ERROR_RETRIES - _retry_server))
                logger.warning("Spotify 서버 오류 %d - %.1f초 후 재시도", resp.status_code, wait)
                time.sleep(wait)
                return self.request(
                    method, path, params=params, json=json,
                    _retry_auth=_retry_auth, _retry_server=_retry_server - 1,
                    _retry_network=_retry_network,
                )
            raise SpotifyApiError(
                "Spotify 서버가 응답하지 않습니다.",
                hint="Spotify 측 문제입니다. 잠시 후 자동으로 다시 시도합니다.",
                detail=_body_snippet(resp),
            )

        # --- 그 밖의 4xx ---
        raise SpotifyApiError(
            "Spotify 요청이 거부되었습니다.",
            hint="잠시 후 다시 시도해 주세요.",
            detail=_body_snippet(resp),
        )

    # -- 상태 코드 해석 ----------------------------------------------------

    def _handle_rate_limit(
        self, resp, method, path, params, json, retry_auth, retry_server
    ) -> Any:
        """429 처리.

        2026년 변경으로 할당량 초과 시 본문에 {"reason": "QUOTA_EXCEEDED"}가 담긴다.
        일시적 Rate Limit과 달리 기다린다고 바로 풀리지 않으므로 구분해서 알린다.
        """
        retry_after = _int_header(resp, "Retry-After", default=1)

        reason = ""
        try:
            payload = resp.json()
            reason = payload.get("reason") or payload.get("error", {}).get("reason", "")
        except (ValueError, AttributeError):
            pass

        if reason == "QUOTA_EXCEEDED":
            self._backoff_until = time.monotonic() + max(retry_after, 60)
            raise QuotaExceededError(retry_after=retry_after, detail=_body_snippet(resp))

        # 짧은 대기면 조용히 기다렸다 한 번 더 시도한다.
        if retry_after <= MAX_AUTO_RETRY_WAIT:
            logger.info("Rate Limit - %d초 대기 후 재시도합니다.", retry_after)
            time.sleep(retry_after)
            return self.request(
                method, path, params=params, json=json,
                _retry_auth=retry_auth, _retry_server=retry_server,
            )

        # 오래 기다려야 하면 그동안 요청을 보내지 않도록 기록하고 알린다.
        self._backoff_until = time.monotonic() + retry_after
        raise RateLimitError(retry_after=retry_after, detail=_body_snippet(resp))

    def _interpret_403(self, resp) -> DeckError:
        """403의 여러 원인을 구분한다.

        같은 403이라도 원인이 셋이라 메시지를 나눠야 사용자가 조치할 수 있다:
          1. Premium이 아님
          2. Development Mode 허용 목록 미등록
          3. 현재 상황에서 금지된 동작 (광고 중 스킵 등)
        """
        message = _error_message(resp).lower()
        detail = _body_snippet(resp)

        if "premium" in message:
            return PremiumRequiredError(detail=detail)

        # 허용 목록 미등록은 보통 "User not registered in the Developer Dashboard"
        if "not registered" in message or "developer dashboard" in message:
            return AuthError(
                "이 계정은 앱 사용이 허용되지 않았습니다.",
                hint=(
                    "Spotify Dashboard > Settings > User Management 에서\n"
                    "본인 이메일을 허용 목록에 추가해 주세요.\n"
                    "(Development Mode 앱은 등록된 계정만 사용할 수 있습니다)"
                ),
                detail=detail,
            )

        if "restrict" in message or "not allowed" in message:
            return RestrictedActionError(detail=detail)

        # 원인 불명 403: Premium이 가장 흔하므로 그쪽으로 안내하되 단정하지 않는다.
        return PremiumRequiredError(
            "이 동작이 허용되지 않았습니다.",
            hint=(
                "Spotify Premium 계정인지, 그리고 Dashboard 허용 목록에\n"
                "계정이 등록되어 있는지 확인해 주세요."
            ),
            detail=detail,
        )

    def _interpret_404(self, resp) -> DeckError:
        """404는 대부분 '활성 기기 없음'이다."""
        message = _error_message(resp).lower()
        detail = _body_snippet(resp)

        if "device" in message or "not found" in message:
            return NoActiveDeviceError(detail=detail)

        return SpotifyApiError(
            "요청한 정보를 찾을 수 없습니다.",
            hint="Spotify 앱에서 재생을 시작한 뒤 다시 시도해 주세요.",
            detail=detail,
        )


# ---------------------------------------------------------------------------
#  보조 함수
# ---------------------------------------------------------------------------


def _is_safe_to_retry(method: str) -> bool:
    """같은 요청을 다시 보내도 안전한지 (멱등성).

    GET/PUT/DELETE는 여러 번 보내도 결과가 같다.
      - PUT /me/player/play    이미 재생 중이면 그대로 재생
      - PUT /me/player/volume  같은 값을 두 번 넣어도 같은 볼륨
      - DELETE /me/library     이미 지웠으면 그대로 없음

    POST는 위험하다.
      - POST /me/player/next   두 번 나가면 곡을 두 개 건너뛴다
    연결이 끊긴 시점이 '요청 도달 전'인지 '처리 후'인지 알 수 없으므로
    POST는 재시도하지 않고 오류로 알린다.
    """
    return method.upper() in ("GET", "PUT", "DELETE", "HEAD")


def _error_message(resp) -> str:
    """Spotify 오류 본문에서 message를 뽑는다. 형식이 달라도 죽지 않는다."""
    try:
        payload = resp.json()
    except ValueError:
        return resp.text or ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message", ""))
    if isinstance(error, str):
        return error
    return str(payload)


def _body_snippet(resp, limit: int = 300) -> str:
    """로그용 응답 본문 요약 (UI에는 노출하지 않는다)."""
    text = (resp.text or "").strip().replace("\n", " ")
    if len(text) > limit:
        text = text[:limit] + "..."
    return f"HTTP {resp.status_code} {text}"


def _int_header(resp, name: str, default: int = 0) -> int:
    try:
        return int(resp.headers.get(name, default))
    except (TypeError, ValueError):
        return default


def track_uri(track_id: str) -> str:
    """트랙 ID를 Spotify URI로 바꾼다.

    2026년 2월부터 라이브러리 엔드포인트가 ID가 아닌 URI를 받는다.
    """
    if track_id.startswith("spotify:"):
        return track_id
    return f"spotify:track:{track_id}"


def join_uris(uris: list[str]) -> str:
    """URI 목록을 라이브러리 엔드포인트용 쿼리 값으로 만든다.

    쉼표로 잇기만 하고 **직접 URL 인코딩하지 않는다.**

    공식 문서에는 `uris=spotify%3Atrack%3A...` 처럼 인코딩된 예시가 나오는데,
    그건 최종 HTTP 요청 줄의 모습을 보여 주는 것이다.
    requests가 쿼리 파라미터를 이미 인코딩하므로 여기서 또 인코딩하면
    `%`가 `%25`로 한 번 더 바뀌어 Spotify가 콜론 대신 '%3A'라는 글자를 받는다:

        보낸 값   spotify%3Atrack%3Aabc
        실제 전송 uris=spotify%253Atrack%253Aabc
        서버 해석 spotify%3Atrack%3Aabc      <- 400 Invalid Spotify URI

    그래서 원본 URI를 그대로 넘기고 인코딩은 requests에 맡긴다.
    """
    return ",".join(uris)
