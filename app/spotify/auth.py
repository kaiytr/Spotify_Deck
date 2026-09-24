"""Spotify OAuth 2.0 — Authorization Code with PKCE.

Implicit Grant는 사용하지 않는다. Spotify가 공식적으로 권장을 철회했고
리프레시 토큰을 받을 수 없어 매번 재로그인해야 하기 때문이다.

PKCE 플로우 개요:

    1. code_verifier  : 암호학적 난수 문자열 (43~128자)
    2. code_challenge : BASE64URL(SHA256(code_verifier))   ← 인증 요청에 실어 보냄
    3. 사용자가 브라우저에서 로그인/권한 승인
    4. Spotify가 127.0.0.1:8888/callback 으로 authorization code 전달
    5. code + code_verifier(원본)를 토큰 엔드포인트에 제출 → 토큰 수령

중간에서 code를 가로채도 code_verifier가 없으면 토큰으로 바꿀 수 없다.
따라서 Client Secret 없이도 안전하며, 데스크톱 앱에 적합하다.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from app.config.settings import Settings
from app.core.errors import (
    AuthCancelledError,
    AuthError,
    ConfigError,
    InvalidCredentialsError,
    NetworkError,
    TokenRefreshFailedError,
)
from app.spotify.tokens import TokenBundle, TokenStore

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

#: 브라우저 로그인 대기 제한 시간(초)
LOGIN_TIMEOUT_SECONDS = 300


# ---------------------------------------------------------------------------
#  PKCE 유틸
# ---------------------------------------------------------------------------


def generate_code_verifier(length: int = 96) -> str:
    """RFC 7636의 code_verifier 생성.

    허용 문자는 unreserved = [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~" 이고
    길이는 43~128자여야 한다. token_urlsafe는 '-'와 '_'만 쓰므로 규격에 맞는다.
    """
    if not 43 <= length <= 128:
        raise ValueError("code_verifier 길이는 43~128자여야 합니다.")
    # token_urlsafe(n)은 약 1.33*n 글자를 만든다. 넉넉히 만든 뒤 잘라 쓴다.
    verifier = secrets.token_urlsafe(length)[:length]
    return verifier


def generate_code_challenge(verifier: str) -> str:
    """BASE64URL-ENCODE(SHA256(ASCII(code_verifier))), 패딩('=') 제거."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


# ---------------------------------------------------------------------------
#  로컬 콜백 서버
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>Spotify Deck</title>
<style>
  body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       background:#121212;color:#fff;font-family:'Segoe UI',system-ui,sans-serif}}
  .card{{text-align:center;padding:48px 64px}}
  .dot{{width:64px;height:64px;border-radius:50%;background:#1DB954;margin:0 auto 24px;
        display:flex;align-items:center;justify-content:center;font-size:32px}}
  h1{{font-size:24px;margin:0 0 12px;font-weight:600}}
  p{{color:#b3b3b3;margin:0;font-size:15px;line-height:1.6}}
</style></head>
<body><div class="card">
  <div class="dot">&#10004;</div>
  <h1>연결되었습니다</h1>
  <p>{message}<br>이 창을 닫아도 됩니다.</p>
</div></body></html>"""

_FAILURE_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><title>Spotify Deck</title>
<style>
  body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       background:#121212;color:#fff;font-family:'Segoe UI',system-ui,sans-serif}}
  .card{{text-align:center;padding:48px 64px}}
  .dot{{width:64px;height:64px;border-radius:50%;background:#E22134;margin:0 auto 24px;
        display:flex;align-items:center;justify-content:center;font-size:32px}}
  h1{{font-size:24px;margin:0 0 12px;font-weight:600}}
  p{{color:#b3b3b3;margin:0;font-size:15px;line-height:1.6}}
</style></head>
<body><div class="card">
  <div class="dot">&#10006;</div>
  <h1>연결하지 못했습니다</h1>
  <p>{message}</p>
</div></body></html>"""


class _CallbackResult:
    """콜백 서버가 채우는 결과 상자."""

    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None
        self.received = threading.Event()


def _make_handler(result: _CallbackResult, expected_path: str):
    """콜백 요청을 한 번 받아 결과를 기록하는 핸들러를 만든다."""

    class Handler(BaseHTTPRequestHandler):
        # 기본 구현은 stderr에 접속 로그를 찍는다. 콘솔을 더럽히므로 끈다.
        def log_message(self, fmt: str, *args) -> None:  # noqa: ARG002
            # 요청 줄에는 authorization code가 들어 있다.
            # 일회용이지만 로그 파일이나 화면 캡처로 새어 나갈 수 있으므로
            # 쿼리 문자열은 통째로 가린다.
            try:
                message = fmt % args
            except (TypeError, ValueError):
                message = fmt
            if "?" in message:
                head, _, tail = message.partition("?")
                # 경로만 남기고 값은 버린다. HTTP 버전 등 뒷부분은 유지한다.
                suffix = tail.split(" ", 1)[1] if " " in tail else ""
                message = f"{head}?<생략> {suffix}".rstrip()
            logger.debug("callback %s", message)

        def _respond(self, status: int, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 규약
            parsed = urllib.parse.urlparse(self.path)

            # 브라우저가 자동 요청하는 /favicon.ico 등은 무시한다.
            if parsed.path != expected_path:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            params = urllib.parse.parse_qs(parsed.query)
            result.code = params.get("code", [None])[0]
            result.state = params.get("state", [None])[0]
            result.error = params.get("error", [None])[0]

            if result.error:
                reason = {
                    "access_denied": "Spotify 계정 연결을 거부하셨습니다.",
                }.get(result.error, f"Spotify가 오류를 반환했습니다: {result.error}")
                self._respond(400, _FAILURE_HTML.format(message=reason))
            elif result.code:
                self._respond(
                    200,
                    _SUCCESS_HTML.format(message="Spotify Deck으로 돌아가 주세요."),
                )
            else:
                self._respond(
                    400,
                    _FAILURE_HTML.format(message="인증 코드를 받지 못했습니다."),
                )

            result.received.set()

    return Handler


# ---------------------------------------------------------------------------
#  인증기
# ---------------------------------------------------------------------------


class SpotifyAuth:
    """PKCE 로그인과 토큰 갱신을 담당한다.

    사용:
        auth = SpotifyAuth(settings, store)
        token = auth.get_access_token()   # 필요하면 자동 로그인/갱신
    """

    def __init__(self, settings: Settings, store: TokenStore) -> None:
        self._settings = settings
        self._store = store
        self._tokens: TokenBundle | None = store.load()
        # 여러 스레드(UI 폴링 + 사용자 조작)가 동시에 갱신하지 않도록 보호한다.
        self._lock = threading.RLock()

    # --- 상태 조회 ---

    @property
    def is_authenticated(self) -> bool:
        """유효한 리프레시 토큰을 갖고 있는지 (= 재로그인 없이 쓸 수 있는지)."""
        return self._tokens is not None and bool(self._tokens.refresh_token)

    @property
    def tokens(self) -> TokenBundle | None:
        return self._tokens

    def logout(self) -> None:
        """저장된 토큰을 지운다."""
        with self._lock:
            self._tokens = None
            self._store.clear()
            logger.info("로그아웃했습니다.")

    # --- 토큰 획득 ---

    def get_access_token(self, *, allow_interactive: bool = True) -> str:
        """유효한 액세스 토큰을 반환한다.

        필요에 따라 자동으로 갱신하거나, 토큰이 아예 없으면 브라우저 로그인을 띄운다.

        Args:
            allow_interactive: False면 로그인이 필요할 때 브라우저를 열지 않고
                AuthError를 던진다. (백그라운드 폴링 스레드에서 사용)
        """
        with self._lock:
            if self._tokens is None:
                if not allow_interactive:
                    raise AuthError("Spotify에 로그인되어 있지 않습니다.")
                self.login()
                assert self._tokens is not None
                return self._tokens.access_token

            if self._tokens.is_expired:
                logger.debug("액세스 토큰 만료 - 갱신합니다.")
                self.refresh()

            return self._tokens.access_token

    # --- 로그인 ---

    def build_authorize_url(self, code_challenge: str, state: str) -> str:
        """브라우저로 열 인증 URL을 만든다."""
        params = {
            "client_id": self._settings.client_id,
            "response_type": "code",
            "redirect_uri": self._settings.redirect_uri,
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
            "state": state,
            "scope": self._settings.scope_string,
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def login(self, *, open_browser: bool = True) -> TokenBundle:
        """브라우저를 열어 사용자 승인을 받고 토큰을 저장한다.

        Raises:
            AuthCancelledError: 사용자가 승인을 거부하거나 제한 시간 초과.
            InvalidCredentialsError: Client ID 또는 Redirect URI 불일치.
            NetworkError: 네트워크 문제.
        """
        verifier = generate_code_verifier()
        challenge = generate_code_challenge(verifier)
        state = secrets.token_urlsafe(24)

        host = self._settings.callback_host
        port = self._settings.callback_port
        result = _CallbackResult()

        try:
            server = HTTPServer((host, port), _make_handler(result, self._settings.callback_path))
        except OSError as exc:
            raise ConfigError(
                f"콜백 서버를 {host}:{port} 에서 시작할 수 없습니다.",
                hint=(
                    "다른 프로그램이 포트를 사용 중입니다.\n"
                    ".env의 SPOTIFY_REDIRECT_URI와 Spotify Dashboard의 값을\n"
                    "8889 등 다른 포트로 함께 바꿔 주세요."
                ),
                detail=str(exc),
            ) from exc

        # 응답을 보낸 뒤 소켓을 바로 정리할 수 있게 타임아웃을 짧게 둔다.
        server.timeout = 1.0

        url = self.build_authorize_url(challenge, state)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                                  daemon=True, name="oauth-callback")
        thread.start()

        try:
            logger.info("브라우저에서 Spotify 로그인을 진행해 주세요.")
            if open_browser:
                opened = webbrowser.open(url)
                if not opened:
                    logger.warning("브라우저를 자동으로 열지 못했습니다. 아래 주소를 직접 여세요:\n%s", url)
            else:
                logger.info("아래 주소를 브라우저에서 여세요:\n%s", url)

            if not result.received.wait(timeout=LOGIN_TIMEOUT_SECONDS):
                raise AuthCancelledError(
                    "로그인 대기 시간이 초과되었습니다.",
                    hint="다시 시도해 주세요.",
                )
        finally:
            server.shutdown()
            server.server_close()

        # --- 결과 검증 ---
        if result.error == "access_denied":
            raise AuthCancelledError()
        if result.error:
            raise AuthError(
                "Spotify 로그인 중 오류가 발생했습니다.",
                hint="잠시 후 다시 시도해 주세요.",
                detail=f"error={result.error}",
            )
        if not result.code:
            raise AuthError("Spotify에서 인증 코드를 받지 못했습니다.")

        # CSRF 방지: 내가 보낸 state가 그대로 돌아왔는지 확인한다.
        if not secrets.compare_digest(result.state or "", state):
            raise AuthError(
                "보안 검증에 실패했습니다.",
                hint="다시 로그인해 주세요.",
                detail="state 값 불일치 (CSRF 가능성)",
            )

        tokens = self._exchange_code(result.code, verifier)

        with self._lock:
            self._tokens = tokens
            self._store.save(tokens)

        logger.info("Spotify 로그인에 성공했습니다.")
        return tokens

    # --- 토큰 엔드포인트 호출 ---

    def _post_token(self, data: dict) -> dict:
        """토큰 엔드포인트 POST 공통 처리."""
        try:
            resp = requests.post(
                TOKEN_URL,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
        except requests.exceptions.SSLError as exc:
            raise NetworkError(
                "보안 연결에 실패했습니다.",
                hint="백신이나 방화벽의 SSL 검사 설정을 확인해 주세요.",
                detail=str(exc),
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(detail=str(exc)) from exc
        except requests.exceptions.Timeout as exc:
            raise NetworkError(
                "Spotify 응답이 너무 늦습니다.",
                hint="네트워크 상태를 확인하고 다시 시도해 주세요.",
                detail=str(exc),
            ) from exc

        if resp.status_code == 200:
            return resp.json()

        # 오류 응답을 사용자 언어로 번역한다.
        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        error = payload.get("error", "")
        description = payload.get("error_description", resp.text[:200])
        detail = f"HTTP {resp.status_code} {error}: {description}"

        if error == "invalid_client":
            raise InvalidCredentialsError(
                "Client ID가 올바르지 않습니다.",
                hint=(
                    "Spotify Dashboard의 Client ID와\n"
                    ".env의 SPOTIFY_CLIENT_ID가 같은지 확인해 주세요."
                ),
                detail=detail,
            )

        if error == "invalid_grant":
            # 인증 코드 재사용/만료, 또는 리프레시 토큰 폐기.
            raise TokenRefreshFailedError(detail=detail)

        if "redirect_uri" in description.lower():
            raise InvalidCredentialsError(
                "Redirect URI가 일치하지 않습니다.",
                hint=(
                    "Spotify Dashboard에 등록한 값과 .env의 값이\n"
                    "글자 하나까지 같아야 합니다:\n"
                    f"  {self._settings.redirect_uri}\n"
                    "Dashboard에서 Add 버튼을 눌러 저장했는지도 확인해 주세요."
                ),
                detail=detail,
            )

        raise AuthError(
            "Spotify 인증에 실패했습니다.",
            hint="잠시 후 다시 시도해 주세요.",
            detail=detail,
        )

    def _exchange_code(self, code: str, verifier: str) -> TokenBundle:
        """authorization code를 토큰으로 교환한다 (PKCE)."""
        payload = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._settings.redirect_uri,
                "client_id": self._settings.client_id,
                "code_verifier": verifier,
            }
        )
        return TokenBundle.from_response(payload)

    def refresh(self) -> TokenBundle:
        """리프레시 토큰으로 액세스 토큰을 갱신한다.

        Raises:
            TokenRefreshFailedError: 리프레시 토큰이 만료/폐기되어 재로그인이 필요.
        """
        with self._lock:
            current = self._tokens
            if current is None or not current.refresh_token:
                raise TokenRefreshFailedError("저장된 로그인 정보가 없습니다.")

            payload = self._post_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": current.refresh_token,
                    "client_id": self._settings.client_id,
                }
            )

            # Spotify는 리프레시 토큰을 회전시킬 수 있다.
            # 응답에 새 값이 있으면 그것을, 없으면 기존 값을 유지한다.
            tokens = TokenBundle.from_response(payload, previous=current)
            self._tokens = tokens
            self._store.save(tokens)
            logger.debug("액세스 토큰을 갱신했습니다. (%d초 유효)", tokens.seconds_remaining)
            return tokens

    def ensure_login(self) -> TokenBundle:
        """토큰이 없으면 로그인, 있으면 유효성만 확인한다.

        앱 시작 시 한 번 호출한다.
        """
        with self._lock:
            if self._tokens is None:
                return self.login()

            try:
                if self._tokens.is_expired:
                    return self.refresh()
                return self._tokens
            except TokenRefreshFailedError:
                # 리프레시 토큰이 6개월 수명을 넘겼거나 사용자가 권한을 취소했다.
                logger.info("저장된 로그인이 만료되어 다시 로그인합니다.")
                self._store.clear()
                self._tokens = None
                return self.login()


# ---------------------------------------------------------------------------
#  STEP 3 단독 테스트용 CLI
# ---------------------------------------------------------------------------


def _main() -> int:
    """`python -m app.spotify.auth` 로 로그인만 따로 테스트한다."""
    import argparse

    from app.core.console import enable_utf8_console

    enable_utf8_console()

    parser = argparse.ArgumentParser(description="Spotify 로그인 테스트 (STEP 3)")
    parser.add_argument("--logout", action="store_true", help="저장된 로그인 정보를 지운다")
    parser.add_argument("--force", action="store_true", help="저장된 토큰을 무시하고 다시 로그인")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

    from app.config.settings import load_settings
    from app.core.errors import DeckError
    from app.spotify.tokens import create_token_store

    try:
        settings = load_settings()
        store = create_token_store(settings.token_store)
        auth = SpotifyAuth(settings, store)

        print(f"토큰 저장소: {store.describe()}")

        if args.logout:
            auth.logout()
            print("로그아웃했습니다.")
            return 0

        if args.force:
            auth.logout()

        if auth.is_authenticated:
            print("저장된 로그인 정보가 있습니다. 토큰을 확인합니다...")
        else:
            print("브라우저가 열립니다. Spotify 계정으로 로그인하고 권한을 허용해 주세요.")

        tokens = auth.ensure_login()

        print("\n" + "=" * 58)
        print("  로그인 성공")
        print("=" * 58)
        print(f"  액세스 토큰   : {tokens.access_token[:24]}... ({len(tokens.access_token)}자)")
        print(f"  만료까지      : {tokens.seconds_remaining}초")
        print(f"  리프레시 토큰 : {'있음' if tokens.refresh_token else '없음'}")
        print(f"  승인된 권한   :")
        for scope in sorted(tokens.scope.split()):
            print(f"      - {scope}")

        # 실제 API를 한 번 호출해 토큰이 진짜 동작하는지 확인한다.
        print("\n  /v1/me 호출로 토큰 검증 중...")
        resp = requests.get(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {tokens.access_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            me = resp.json()
            print(f"  계정          : {me.get('display_name')}")

            # product 필드는 user-read-private 권한이 있어야 내려온다.
            # 이 앱은 최소 권한만 요청하므로 보통 None이며, 그것은 정상이다.
            # (None을 'Premium 아님'으로 단정하면 Premium 사용자에게 거짓 경고가 뜬다)
            product = me.get("product")
            if product is None:
                print("  요금제        : 확인 안 함")
                print("                  (요금제 조회에는 user-read-private 권한이 필요한데,")
                print("                   덱 기능에 쓰이지 않아 요청하지 않습니다)")
            elif product == "premium":
                print("  요금제        : premium")
            else:
                print(f"  요금제        : {product}")
                print("\n  [경고] Premium이 아닙니다. 재생 제어(재생/일시정지/다음 등)는")
                print("         403으로 거부됩니다. 재생 정보 표시는 정상 동작합니다.")
        elif resp.status_code == 403:
            print("  [실패] 403 Forbidden")
            print("         Development Mode 허용 목록에 계정이 등록되지 않았습니다.")
            print("         Dashboard > Settings > User Management 에서")
            print("         본인 이메일을 추가해 주세요.")
            return 1
        else:
            print(f"  [실패] HTTP {resp.status_code}: {resp.text[:200]}")
            return 1

        print("=" * 58)
        print("\nSTEP 3 완료. 이제 저장된 토큰으로 재로그인 없이 실행됩니다.")
        return 0

    except DeckError as exc:
        print(f"\n[오류] {exc.user_message}")
        if exc.hint:
            print(exc.hint)
        if exc.detail:
            logger.debug("상세: %s", exc.detail)
        return 1
    except KeyboardInterrupt:
        print("\n취소되었습니다.")
        return 130


if __name__ == "__main__":
    raise SystemExit(_main())
