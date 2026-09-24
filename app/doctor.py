"""환경 점검 스크립트 (STEP 1 검증 도구).

실행:
    python -m app.doctor

Spotify에 실제로 접속하기 전에 아래를 확인한다.
  1. Python 버전
  2. 필수 패키지 설치 여부
  3. .env 존재 및 Client ID 입력 여부
  4. Redirect URI가 Spotify 2025 정책에 맞는지
  5. 콜백 포트가 비어 있는지
  6. 인터넷으로 Spotify API에 도달 가능한지
  7. 저장된 토큰이 있는지 (로그인 완료 여부)

각 항목은 통과/경고/실패로 표시되며, 실패 시 해결 방법을 함께 알려준다.
"""

from __future__ import annotations

import importlib
import socket
import sys
import time
from pathlib import Path

from app.core.console import enable_utf8_console

enable_utf8_console()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"

_failures = 0
_warnings = 0


def _report(status: str, label: str, detail: str = "") -> None:
    global _failures, _warnings
    if status == FAIL:
        _failures += 1
    elif status == WARN:
        _warnings += 1
    line = f"  {status}  {label}"
    print(line)
    if detail:
        for sub in detail.splitlines():
            print(f"         {sub}")


def check_python() -> None:
    print("\n[1] Python 버전")
    v = sys.version_info
    version = f"{v.major}.{v.minor}.{v.micro}"
    if v < (3, 10):
        _report(FAIL, f"Python {version}", "Python 3.10 이상이 필요합니다. 3.11을 권장합니다.")
    elif v >= (3, 14):
        _report(WARN, f"Python {version}", "테스트되지 않은 버전입니다. 3.11 사용을 권장합니다.")
    else:
        _report(OK, f"Python {version}")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    if in_venv:
        _report(OK, "가상환경(venv) 활성화됨", sys.prefix)
    else:
        _report(
            WARN,
            "가상환경이 아닌 전역 Python에서 실행 중",
            ".\.venv\Scripts\Activate.ps1 로 가상환경을 켜는 것을 권장합니다.",
        )


def check_packages() -> None:
    print("\n[2] 필수 패키지")
    required = {
        "PySide6": "UI 프레임워크",
        "requests": "Spotify API 호출",
        "dotenv": ".env 로딩 (python-dotenv)",
        "keyring": "토큰 안전 저장",
    }
    for module, purpose in required.items():
        try:
            mod = importlib.import_module(module)
        except ImportError:
            _report(FAIL, f"{module} 없음 ({purpose})", "pip install -r requirements.txt")
            continue
        version = getattr(mod, "__version__", "")
        if module == "PySide6":
            try:
                from PySide6 import __version__ as pyside_version

                version = pyside_version
            except Exception:
                pass
        _report(OK, f"{module} {version}".strip(), purpose)


def check_env_file() -> "object | None":
    print("\n[3] .env 설정")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        _report(
            FAIL,
            ".env 파일 없음",
            "프로젝트 폴더에서 실행하세요:  copy .env.example .env\n"
            "그 다음 Client ID를 채워 넣으세요.",
        )
        return None

    _report(OK, ".env 파일 존재", str(env_path))

    from app.config.settings import load_settings
    from app.core.errors import DeckError

    try:
        settings = load_settings()
    except DeckError as exc:
        _report(FAIL, exc.user_message, exc.hint or "")
        return None

    _report(OK, f"Client ID 확인됨: {settings.masked_client_id()}")
    _report(OK, f"Redirect URI 형식 정상: {settings.redirect_uri}")

    flow = "PKCE (Client Secret 불필요)" if settings.uses_pkce else "Authorization Code + Secret"
    _report(OK, f"인증 방식: {flow}")
    _report(OK, f"갱신 주기: {settings.poll_interval_ms}ms")
    return settings


def check_port(settings) -> None:
    print("\n[4] OAuth 콜백 포트")
    if settings is None:
        _report(WARN, "건너뜀 (.env 설정 필요)")
        return

    host, port = settings.callback_host, settings.callback_port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.bind((host, port))
        _report(OK, f"{host}:{port} 사용 가능")
    except OSError as exc:
        _report(
            FAIL,
            f"{host}:{port} 를 열 수 없습니다",
            f"다른 프로그램이 포트를 쓰고 있습니다. ({exc})\n"
            ".env 와 Dashboard의 포트를 8889 등으로 함께 바꿔 보세요.",
        )
    finally:
        sock.close()


def check_network() -> None:
    print("\n[5] 네트워크")
    try:
        import requests
    except ImportError:
        _report(WARN, "건너뜀 (requests 미설치)")
        return

    # 인증 없이 호출하면 401이 정상. 응답이 오기만 하면 연결은 성공.
    #
    # 프로세스를 새로 띄운 직후 첫 요청이 DNS 지연으로 한 번 실패하는 경우가 있다.
    # 그것만으로 "인터넷 연결을 확인하세요"라고 하면 잘못된 안내이므로
    # 짧게 쉬었다가 두 번 더 시도한 뒤에 판정한다.
    attempts = 3
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get("https://api.spotify.com/v1/me", timeout=8)
        except requests.exceptions.SSLError as exc:
            _report(
                FAIL,
                "SSL 인증서 검증 실패",
                "회사/학교 방화벽이나 백신의 SSL 검사 설정을 확인하세요.",
            )
            return
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1.0)
            continue
        except Exception as exc:  # noqa: BLE001
            _report(WARN, "네트워크 확인 중 예기치 못한 문제", str(exc))
            return

        suffix = "" if attempt == 1 else f" (재시도 {attempt}회)"
        if resp.status_code == 401:
            _report(OK, f"api.spotify.com 도달 가능 (401 = 정상, 토큰 없음){suffix}")
        else:
            _report(OK, f"api.spotify.com 도달 가능 (HTTP {resp.status_code}){suffix}")
        return

    if isinstance(last_error, requests.exceptions.Timeout):
        _report(WARN, f"응답 시간 초과 ({attempts}회 시도)", "네트워크가 느립니다. 다시 시도해 보세요.")
    else:
        _report(
            FAIL,
            f"api.spotify.com 에 연결할 수 없습니다 ({attempts}회 시도)",
            "인터넷 연결을 확인해 주세요.",
        )


def check_tokens(settings) -> None:
    print("\n[6] 저장된 로그인 정보")
    if settings is None:
        _report(WARN, "건너뜀 (.env 설정 필요)")
        return
    try:
        from app.spotify.tokens import create_token_store
    except ImportError:
        _report(WARN, "건너뜀 (아직 STEP 3 미구현)")
        return

    store = create_token_store(settings.token_store)
    _report(OK, f"토큰 저장소: {store.describe()}")
    if store.load() is None:
        _report(
            WARN,
            "저장된 로그인 정보 없음",
            "앱을 처음 실행하면 브라우저에서 Spotify 로그인이 진행됩니다.",
        )
    else:
        _report(OK, "저장된 로그인 정보 있음 (재로그인 불필요)")


def main() -> int:
    print("=" * 62)
    print("  Spotify Deck - 환경 점검")
    print("=" * 62)

    check_python()
    check_packages()
    settings = check_env_file()
    check_port(settings)
    check_network()
    check_tokens(settings)

    print("\n" + "=" * 62)
    if _failures:
        print(f"  실패 {_failures}건, 경고 {_warnings}건 - 위 [FAIL] 항목을 먼저 해결해 주세요.")
        print("=" * 62)
        return 1
    if _warnings:
        print(f"  통과 (경고 {_warnings}건) - 실행 가능합니다.")
    else:
        print("  모든 항목 통과. 실행 준비 완료!")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
