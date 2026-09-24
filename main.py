"""Spotify Deck 진입점.

실행:
    python main.py              일반 실행 (PC UI)
    python main.py --compact    480x320 ESP32 레이아웃 미리보기
    python main.py --logout     저장된 로그인 정보를 지우고 다시 로그인
    python main.py --debug      상세 로그 출력

조립 순서 (의존성 방향: 아래로만 흐른다):

    Settings ──> TokenStore ──> SpotifyAuth ──> SpotifyClient ──> SpotifyPlayer
                                                                        │
                                                    DeckController ─────┘
                                                        ▲        │
                                      InputManager ─────┘        ▼
                                      (Keyboard/GPIO)        DeckWindow
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.core.console import enable_utf8_console

# 콘솔 인코딩은 다른 무엇보다 먼저 잡아야 한다.
# (Windows 한국어 환경의 cp949에서 한글 로그가 깨지거나 예외로 죽는 것을 막는다)
enable_utf8_console()

logger = logging.getLogger("spotify_deck")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s  %(levelname)-7s  %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # 폴링이 1초마다 돌아 urllib3 디버그 로그가 화면을 도배한다.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def show_startup_error(title: str, message: str, hint: str = "") -> None:
    """GUI를 띄우기 전/후 모두에서 쓸 수 있는 오류 안내.

    Qt가 이미 떠 있으면 대화상자로, 아니면 콘솔에 출력한다.
    """
    body = message + (f"\n\n{hint}" if hint else "")

    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is not None:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Spotify Deck")
            box.setText(title)
            box.setInformativeText(body)
            box.exec()
            return
    except Exception:  # noqa: BLE001 - GUI를 못 띄우면 콘솔로 대체
        pass

    print("\n" + "=" * 62)
    print(f"  {title}")
    print("=" * 62)
    for line in body.splitlines():
        print(f"  {line}")
    print("=" * 62 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Spotify Deck")
    parser.add_argument("--logout", action="store_true", help="저장된 로그인 정보를 지운다")
    parser.add_argument("--debug", action="store_true", help="상세 로그를 출력한다")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="480x320 ESP32 화면 레이아웃으로 실행한다 (하드웨어 없이 설계 확인용)",
    )
    args = parser.parse_args()

    # --- 설정 로딩 (GUI보다 먼저: .env 오류를 빨리 알려 준다) ---
    from app.config.settings import load_settings
    from app.core.errors import DeckError

    try:
        settings = load_settings()
    except DeckError as exc:
        setup_logging("INFO")
        show_startup_error("설정을 확인해 주세요", exc.user_message, exc.hint or "")
        return 1

    setup_logging("DEBUG" if args.debug else settings.log_level)
    logger.info("Spotify Deck 시작 (Client ID: %s)", settings.masked_client_id())

    # --- 인증 ---
    from app.spotify.auth import SpotifyAuth
    from app.spotify.tokens import create_token_store

    store = create_token_store(settings.token_store)
    logger.debug("토큰 저장소: %s", store.describe())
    auth = SpotifyAuth(settings, store)

    if args.logout:
        auth.logout()
        print("로그아웃했습니다. 다시 실행하면 로그인 창이 열립니다.")
        return 0

    try:
        if not auth.is_authenticated:
            print("\n브라우저에서 Spotify 로그인을 진행해 주세요...")
            print("(브라우저가 자동으로 열리지 않으면 콘솔의 주소를 복사해 여세요)\n")
        auth.ensure_login()
        logger.info("Spotify 인증 완료")
    except DeckError as exc:
        show_startup_error("Spotify에 연결하지 못했습니다", exc.user_message, exc.hint or "")
        if exc.detail:
            logger.debug("상세: %s", exc.detail)
        return 1

    # --- 계층 조립 ---
    from PySide6.QtWidgets import QApplication

    from app.core.deck_controller import DeckController
    from app.input.base import InputManager
    from app.input.keyboard import KeyboardController
    from app.spotify.client import SpotifyClient
    from app.spotify.player import SpotifyPlayer
    from app.audio.factory import create_wave_source
    from app.ui.layouts import COMPACT_480, DESKTOP
    from app.ui.window import DeckWindow
    from app.ui.worker import PollWorker

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Spotify Deck")

    client = SpotifyClient(auth)
    player = SpotifyPlayer(client)

    poller = PollWorker(player, interval_ms=settings.poll_interval_ms)

    # DeckController는 '최신 상태'가 필요하다.
    # 폴링 결과를 담아 두는 상자를 만들어 넘긴다.
    from app.spotify.models import PlaybackState

    latest: dict[str, PlaybackState] = {"state": PlaybackState.empty()}
    poller.state_ready.connect(lambda s: latest.__setitem__("state", s))

    controller = DeckController(player, lambda: latest["state"])

    # 웨이브 바 소스. 실시간 캡처가 가능하면 쓰고, 아니면 시뮬레이션으로 폴백한다.
    wave_source = create_wave_source(mode=settings.wave_mode)
    if wave_source is not None:
        logger.info("웨이브 바: %s", wave_source.status_text)

    # --compact 는 ESP32 목표 화면(480x320)을 그대로 흉내 낸다.
    # 창 크기를 고정해 실제 기기와 같은 조건에서 레이아웃을 확인할 수 있다.
    profile = COMPACT_480 if args.compact else DESKTOP
    if args.compact:
        logger.info("Compact 레이아웃 (480x320, ESP32 목표 화면)")

    window = DeckWindow(
        controller,
        poller,
        wave_source=wave_source,
        layout=profile,
        lock_layout=args.compact,
    )

    # --- 입력 장치 ---
    # 여기가 하드웨어 확장 지점이다.
    # GPIO를 붙일 때는 아래에 한 줄만 추가하면 된다:
    #     inputs.register(GPIOController(pin_map=BUTTON_PINS))
    inputs = InputManager(on_action=window.handle_action)
    inputs.register(KeyboardController(window))
    inputs.start_all()

    def cleanup() -> None:
        from PySide6.QtCore import QThreadPool

        inputs.stop_all()
        poller.stop()
        poller.wait(2000)
        # 진행 중인 앨범 아트 다운로드/액션이 끝나기를 기다린다.
        # 기다리지 않고 종료하면 워커가 파괴된 객체를 건드려 크래시한다.
        QThreadPool.globalInstance().waitForDone(3000)
        client.close()
        logger.info("종료합니다.")

    qt_app.aboutToQuit.connect(cleanup)

    window.show()
    poller.start()

    return qt_app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n종료합니다.")
        raise SystemExit(130) from None
