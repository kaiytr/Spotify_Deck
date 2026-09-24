"""토큰 저장소.

액세스 토큰과 리프레시 토큰을 안전하게 보관해 매번 로그인하지 않아도 되게 한다.

두 가지 백엔드를 제공하며, 이 역시 하드웨어 이식을 염두에 둔 설계다.

    TokenStore (추상)
    ├── KeyringTokenStore   Windows 자격 증명 관리자 / macOS 키체인 / Linux SecretService
    └── FileTokenStore      헤드리스 환경(RK3399 등) 폴백. 홈 디렉터리에 0600 권한 저장

`create_token_store("auto")` 는 keyring을 시도하고 실패하면 파일로 자동 폴백한다.
RK3399를 데스크톱 환경 없이 부팅하면 SecretService(dbus)가 없어 keyring이 실패하는데,
그때 코드 수정 없이 파일 저장으로 넘어간다.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: keyring 서비스 이름
SERVICE_NAME = "spotify-deck"

#: 파일 폴백 저장 위치 (프로젝트 폴더 밖 → 실수로 커밋될 위험 없음)
FILE_STORE_PATH = Path.home() / ".spotify_deck" / "tokens.json"

#: 만료 판정 여유 시간(초). 만료 직전에 요청이 나가는 경쟁 상태를 막는다.
EXPIRY_MARGIN_SECONDS = 60


@dataclass
class TokenBundle:
    """Spotify가 발급한 토큰 묶음.

    Attributes:
        access_token:  API 호출용 토큰. 보통 1시간 유효.
        refresh_token: 액세스 토큰 재발급용.
                       2026년부터 최초 인증 시점으로부터 6개월 수명이며,
                       액세스 토큰을 갱신해도 이 시계는 초기화되지 않는다.
        expires_at:    액세스 토큰 만료 시각 (Unix epoch 초).
        scope:         실제로 승인된 스코프 (요청한 것과 다를 수 있다).
        token_type:    항상 "Bearer".
    """

    access_token: str
    refresh_token: str
    expires_at: float
    scope: str = ""
    token_type: str = "Bearer"

    @classmethod
    def from_response(cls, data: dict, *, previous: "TokenBundle | None" = None) -> "TokenBundle":
        """토큰 엔드포인트 응답(JSON)에서 만든다.

        갱신(refresh) 응답에는 refresh_token이 없을 수도 있고,
        새 값으로 회전(rotate)되어 올 수도 있다. 둘 다 처리한다.
        """
        refresh = data.get("refresh_token") or (previous.refresh_token if previous else "")
        expires_in = float(data.get("expires_in", 3600))
        return cls(
            access_token=data["access_token"],
            refresh_token=refresh,
            expires_at=time.time() + expires_in,
            scope=data.get("scope", previous.scope if previous else ""),
            token_type=data.get("token_type", "Bearer"),
        )

    @property
    def is_expired(self) -> bool:
        """여유 시간을 감안해 만료되었는지."""
        return time.time() >= (self.expires_at - EXPIRY_MARGIN_SECONDS)

    @property
    def seconds_remaining(self) -> int:
        """액세스 토큰 잔여 시간(초). 음수면 이미 만료."""
        return int(self.expires_at - time.time())

    def has_scope(self, scope: str) -> bool:
        """해당 권한이 실제로 승인되었는지 확인."""
        return scope in self.scope.split()

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "TokenBundle":
        return cls(**json.loads(raw))


# ---------------------------------------------------------------------------
#  저장소 구현
# ---------------------------------------------------------------------------


class TokenStore(ABC):
    """토큰 영속화 인터페이스."""

    @abstractmethod
    def save(self, tokens: TokenBundle) -> None: ...

    @abstractmethod
    def load(self) -> TokenBundle | None:
        """저장된 토큰. 없거나 읽기 실패면 None."""

    @abstractmethod
    def clear(self) -> None:
        """저장된 토큰 삭제 (로그아웃)."""

    @abstractmethod
    def describe(self) -> str:
        """사용자/로그에 보여줄 저장 위치 설명."""


class KeyringTokenStore(TokenStore):
    """OS 자격 증명 저장소 기반.

    Windows에서는 자격 증명 관리자에 저장되어 다른 사용자 계정이 읽을 수 없다.
    """

    def __init__(self, account: str = "default") -> None:
        import keyring  # 지연 임포트: 백엔드 없는 환경에서 모듈 로딩 실패를 피한다

        self._keyring = keyring
        self._account = account

    def save(self, tokens: TokenBundle) -> None:
        self._keyring.set_password(SERVICE_NAME, self._account, tokens.to_json())
        logger.debug("토큰을 자격 증명 저장소에 보관했습니다.")

    def load(self) -> TokenBundle | None:
        try:
            raw = self._keyring.get_password(SERVICE_NAME, self._account)
        except Exception as exc:  # noqa: BLE001 - 백엔드 오류는 '토큰 없음'으로 처리
            logger.warning("자격 증명 저장소 읽기 실패: %s", exc)
            return None
        if not raw:
            return None
        try:
            return TokenBundle.from_json(raw)
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("저장된 토큰 형식이 올바르지 않아 무시합니다: %s", exc)
            return None

    def clear(self) -> None:
        try:
            self._keyring.delete_password(SERVICE_NAME, self._account)
        except Exception:  # noqa: BLE001 - 이미 없으면 그만
            pass

    def describe(self) -> str:
        backend = type(self._keyring.get_keyring()).__name__
        return f"OS 자격 증명 저장소 ({backend})"


class FileTokenStore(TokenStore):
    """파일 기반 폴백.

    keyring 백엔드가 없는 헤드리스 환경(RK3399 콘솔 부팅 등)에서 사용한다.
    POSIX에서는 0600(소유자만 읽기/쓰기) 권한을 적용한다.
    Windows는 사용자 홈 디렉터리의 ACL이 이미 타 계정 접근을 막는다.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or FILE_STORE_PATH

    def save(self, tokens: TokenBundle) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # 임시 파일에 쓴 뒤 교체 → 쓰기 도중 정전되어도 기존 토큰이 깨지지 않는다.
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(tokens.to_json(), encoding="utf-8")
        if os.name == "posix":
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        tmp.replace(self._path)
        logger.debug("토큰을 파일에 보관했습니다: %s", self._path)

    def load(self) -> TokenBundle | None:
        if not self._path.exists():
            return None
        try:
            return TokenBundle.from_json(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError, KeyError, OSError) as exc:
            logger.warning("토큰 파일을 읽을 수 없어 무시합니다: %s", exc)
            return None

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)

    def describe(self) -> str:
        return f"파일 ({self._path})"


class NullTokenStore(TokenStore):
    """저장하지 않는 구현. 테스트/일회성 실행용."""

    def save(self, tokens: TokenBundle) -> None:  # noqa: ARG002
        pass

    def load(self) -> TokenBundle | None:
        return None

    def clear(self) -> None:
        pass

    def describe(self) -> str:
        return "저장 안 함 (메모리 전용)"


def create_token_store(mode: str = "auto") -> TokenStore:
    """설정값(DECK_TOKEN_STORE)에 맞는 저장소를 만든다.

    Args:
        mode: "auto" | "keyring" | "file" | "none"

    "auto"는 keyring을 실제로 써 보고(쓰기 테스트 포함) 실패하면 파일로 폴백한다.
    단순히 import만 확인하면 백엔드가 없는 환경에서 런타임에 터지기 때문에
    여기서 한 번 실제 동작을 확인한다.
    """
    mode = (mode or "auto").lower()

    if mode == "none":
        return NullTokenStore()

    if mode == "file":
        return FileTokenStore()

    if mode in ("auto", "keyring"):
        try:
            import keyring
            from keyring.backends.fail import Keyring as FailKeyring

            backend = keyring.get_keyring()
            if isinstance(backend, FailKeyring):
                raise RuntimeError("사용 가능한 keyring 백엔드가 없습니다")

            # 실제 쓰기/읽기/삭제가 되는지 확인한다.
            keyring.set_password(SERVICE_NAME, "__probe__", "ok")
            if keyring.get_password(SERVICE_NAME, "__probe__") != "ok":
                raise RuntimeError("keyring 검증 실패")
            keyring.delete_password(SERVICE_NAME, "__probe__")

            return KeyringTokenStore()
        except Exception as exc:  # noqa: BLE001
            if mode == "keyring":
                logger.warning("keyring을 사용할 수 없어 파일 저장으로 전환합니다: %s", exc)
            else:
                logger.info("keyring을 사용할 수 없어 파일 저장을 사용합니다: %s", exc)
            return FileTokenStore()

    logger.warning("알 수 없는 토큰 저장 방식 %r - 파일 저장을 사용합니다.", mode)
    return FileTokenStore()
