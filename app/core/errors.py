"""사용자 친화적 예외 정의.

원칙:
    UI는 절대로 traceback이나 HTTP 상태코드를 그대로 보여주지 않는다.
    모든 하위 계층(requests, Spotify API)의 오류는 이 모듈의
    DeckError 계열로 변환되어 올라오고, UI는 `.user_message`만 출력한다.

    [requests / Spotify API]  ─→  SpotifyClient가 변환  ─→  DeckError
                                                              │
                                                    UI는 user_message만 표시
"""

from __future__ import annotations


class DeckError(Exception):
    """Spotify Deck의 모든 예외의 최상위 클래스.

    Attributes:
        user_message: 화면에 그대로 띄워도 되는 한국어 설명.
        hint:         사용자가 취할 수 있는 조치. 없으면 None.
        recoverable:  True면 다음 폴링에서 자동 회복을 시도할 수 있는 일시적 오류.
    """

    default_message = "알 수 없는 오류가 발생했습니다."
    default_hint: str | None = None
    recoverable = False

    def __init__(
        self,
        user_message: str | None = None,
        *,
        hint: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.user_message = user_message or self.default_message
        self.hint = hint if hint is not None else self.default_hint
        #: 로그에만 남기는 기술적 상세. UI에는 노출하지 않는다.
        self.detail = detail
        super().__init__(self.user_message if not detail else f"{self.user_message} | {detail}")

    def display(self) -> str:
        """UI 표시용 문자열 (메시지 + 조치 안내)."""
        if self.hint:
            return f"{self.user_message}\n{self.hint}"
        return self.user_message


# ---------------------------------------------------------------------------
#  설정 오류
# ---------------------------------------------------------------------------


class ConfigError(DeckError):
    """.env 누락, Client ID 미입력 등 실행 전 설정 문제."""

    default_message = "설정이 올바르지 않습니다."
    default_hint = ".env 파일을 확인해 주세요."


class InvalidCredentialsError(ConfigError):
    """Client ID가 틀렸거나 Redirect URI가 Dashboard와 불일치."""

    default_message = "Spotify 앱 정보가 올바르지 않습니다."
    default_hint = (
        "Developer Dashboard의 Client ID와 Redirect URI가\n"
        ".env 파일의 값과 정확히 일치하는지 확인해 주세요."
    )


# ---------------------------------------------------------------------------
#  인증 오류
# ---------------------------------------------------------------------------


class AuthError(DeckError):
    """로그인/토큰 관련 오류의 상위 클래스."""

    default_message = "Spotify 로그인에 실패했습니다."
    default_hint = "다시 로그인해 주세요."


class AuthCancelledError(AuthError):
    """사용자가 브라우저에서 권한 승인을 거부했거나 창을 닫음."""

    default_message = "Spotify 로그인이 취소되었습니다."
    default_hint = "덱을 사용하려면 Spotify 계정 연결이 필요합니다."


class TokenExpiredError(AuthError):
    """액세스 토큰 만료. 보통 자동 갱신되므로 사용자에게 보이지 않는다."""

    default_message = "인증이 만료되었습니다."
    default_hint = "자동으로 다시 연결하는 중입니다..."
    recoverable = True


class TokenRefreshFailedError(AuthError):
    """리프레시 토큰이 만료/폐기되어 재로그인이 필요함.

    Spotify는 2026년부터 리프레시 토큰에 6개월 수명을 적용한다.
    (액세스 토큰을 갱신해도 이 6개월 시계는 초기화되지 않는다.)
    """

    default_message = "Spotify 재연결에 실패했습니다."
    default_hint = "다시 로그인이 필요합니다. 로그인 버튼을 눌러 주세요."


# ---------------------------------------------------------------------------
#  네트워크 / API 오류
# ---------------------------------------------------------------------------


class NetworkError(DeckError):
    """인터넷 끊김, DNS 실패, 타임아웃."""

    default_message = "인터넷에 연결할 수 없습니다."
    default_hint = "네트워크 연결을 확인해 주세요. 연결되면 자동으로 복구됩니다."
    recoverable = True


class RateLimitError(DeckError):
    """429 Too Many Requests.

    Attributes:
        retry_after: Retry-After 헤더 값(초). 없으면 None.
    """

    default_message = "Spotify 요청이 너무 많습니다."
    default_hint = "잠시 후 자동으로 다시 시도합니다."
    recoverable = True

    def __init__(
        self,
        user_message: str | None = None,
        *,
        retry_after: int | None = None,
        hint: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.retry_after = retry_after
        if user_message is None and retry_after:
            user_message = f"Spotify 요청이 너무 많습니다. {retry_after}초 후 재시도합니다."
        super().__init__(user_message, hint=hint, detail=detail)


class QuotaExceededError(RateLimitError):
    """개발 모드 앱의 일일/시간당 할당량 초과.

    2026년 변경으로 429 응답 본문에 {"reason": "QUOTA_EXCEEDED"}가 포함된다.
    """

    default_message = "Spotify API 사용량 한도를 초과했습니다."
    default_hint = (
        "개발 모드 앱의 할당량을 모두 사용했습니다.\n"
        "잠시 후 다시 시도하거나 갱신 주기를 늘려 주세요."
    )


class SpotifyApiError(DeckError):
    """그 밖의 Spotify API 오류 (4xx/5xx)."""

    default_message = "Spotify 서버에서 오류가 발생했습니다."
    default_hint = "잠시 후 다시 시도해 주세요."
    recoverable = True


# ---------------------------------------------------------------------------
#  재생 제어 제약
# ---------------------------------------------------------------------------


class PlaybackError(DeckError):
    """재생 제어가 거부된 경우의 상위 클래스."""

    default_message = "재생을 제어할 수 없습니다."


class PremiumRequiredError(PlaybackError):
    """403 - Spotify Premium 계정이 아님.

    Player API의 쓰기 동작(재생/일시정지/다음/볼륨 등)은 Premium 전용이다.
    무료 계정도 '현재 재생 정보 조회'는 가능하므로 앱은 계속 동작한다.
    """

    default_message = "이 기능은 Spotify Premium 계정에서만 사용할 수 있습니다."
    default_hint = "현재 재생 중인 곡 정보는 계속 표시됩니다."


class NoActiveDeviceError(PlaybackError):
    """404 - 활성 재생 장치 없음.

    Spotify는 '어디서 재생할지' 모르면 제어 명령을 거부한다.
    """

    default_message = "재생 중인 Spotify 기기가 없습니다."
    default_hint = (
        "휴대폰이나 PC의 Spotify 앱에서 아무 곡이나 한 번 재생한 뒤\n"
        "다시 시도해 주세요."
    )


class RestrictedActionError(PlaybackError):
    """현재 컨텍스트에서 허용되지 않는 동작.

    예) 광고 재생 중 스킵, 라디오에서 이전 곡, 볼륨 미지원 기기.
    """

    default_message = "지금은 이 동작을 할 수 없습니다."
    default_hint = "광고 재생 중이거나 현재 기기가 지원하지 않는 기능입니다."


class NothingPlayingError(PlaybackError):
    """204 - 재생 중인 콘텐츠가 없음.

    오류라기보다 정상 상태에 가까우므로 UI는 조용히 빈 화면을 표시한다.
    """

    default_message = "재생 중인 음악이 없습니다."
    default_hint = "Spotify에서 곡을 재생하면 여기에 표시됩니다."
    recoverable = True
