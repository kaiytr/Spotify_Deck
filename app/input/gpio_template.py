"""하드웨어 입력 템플릿 (RK3399 이식용).

⚠️ 이 파일은 **현재 실행되지 않는다.** PC 버전에서는 임포트하지 않으며,
   RK3399로 옮길 때 참고할 설계도이자 뼈대다.

여기서 증명하려는 것: **Spotify 로직과 UI를 한 줄도 고치지 않고**
키보드를 물리 버튼/로터리 엔코더로 교체할 수 있다는 점.

아래 클래스들이 하는 일은 `self.emit(DeckAction.XXX)` 호출뿐이다.
나머지(API 호출, 오류 처리, 화면 갱신)는 기존 코드가 그대로 처리한다.

────────────────────────────────────────────────────────────────
 이식 순서
────────────────────────────────────────────────────────────────
 1. RK3399에 Python과 GPIO 라이브러리를 설치한다.
        pip install python-periphery      # 권장: 커널 GPIO 문자 장치 사용
        # 또는 보드 벤더가 제공하는 라이브러리

 2. 아래 PIN_MAP을 실제 배선에 맞게 수정한다.

 3. main.py 의 입력 등록부에 한 줄 추가한다:

        from app.input.gpio_template import GPIOButtonController, RotaryEncoderController

        inputs.register(KeyboardController(window))          # 디버깅용으로 남겨 둬도 된다
        inputs.register(GPIOButtonController(PIN_MAP))       # ← 추가
        inputs.register(RotaryEncoderController(clk=17, dt=18, sw=27))  # ← 추가

 4. 끝. app/spotify/ 와 app/ui/ 는 수정하지 않는다.
────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import threading
import time

from app.core.actions import DeckAction
from app.input.base import InputController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  배선 설정 — 실제 하드웨어에 맞게 수정할 부분
# ---------------------------------------------------------------------------

#: 물리 버튼 핀 번호 -> 액션
#: 키보드 매핑(app/config/keymap.py)과 같은 액션을 쓰므로 동작이 완전히 동일하다.
PIN_MAP: dict[int, DeckAction] = {
    5: DeckAction.PLAY_PAUSE,
    6: DeckAction.PREVIOUS_TRACK,
    13: DeckAction.NEXT_TRACK,
    19: DeckAction.TOGGLE_SHUFFLE,
    26: DeckAction.TOGGLE_REPEAT,
    21: DeckAction.TOGGLE_LIKE,
}

#: 채터링(bounce) 무시 시간(초).
#: 기계식 버튼은 한 번 눌러도 수 ms 동안 수십 번 on/off가 반복된다.
#: 이를 거르지 않으면 "다음 곡"이 한 번에 5번 실행되고 Rate Limit에 걸린다.
DEBOUNCE_SECONDS = 0.18


# ---------------------------------------------------------------------------
#  물리 버튼
# ---------------------------------------------------------------------------


class GPIOButtonController(InputController):
    """물리 버튼 → DeckAction.

    풀업 저항을 쓰는 배선(버튼을 누르면 GND로 떨어짐)을 가정한다.
    """

    name = "gpio"

    def __init__(self, pin_map: dict[int, DeckAction] | None = None) -> None:
        super().__init__()
        self._pin_map = pin_map or PIN_MAP
        self._lines: dict[int, object] = {}
        self._last_fire: dict[int, float] = {}
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        try:
            from periphery import GPIO  # type: ignore[import-not-found]
        except ImportError:
            logger.error(
                "python-periphery가 없어 GPIO 입력을 시작할 수 없습니다. "
                "`pip install python-periphery` 후 다시 시도하세요."
            )
            return

        for pin in self._pin_map:
            # "both" 엣지를 감지하되 눌림(falling)만 처리한다.
            self._lines[pin] = GPIO("/dev/gpiochip0", pin, "in")

        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="gpio-buttons")
        self._thread.start()
        logger.info("GPIO 버튼 %d개 활성화", len(self._lines))

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        for line in self._lines.values():
            try:
                line.close()  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass
        self._lines.clear()

    def _poll_loop(self) -> None:
        """5ms 주기 폴링 + 디바운스.

        인터럽트(epoll) 방식이 더 효율적이지만, 폴링이 이해하기 쉽고
        5ms면 사람 손가락 기준으로 충분히 즉각적이다.
        """
        previous = {pin: True for pin in self._lines}

        while self._running:
            now = time.monotonic()
            for pin, line in self._lines.items():
                try:
                    level = line.read()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    continue

                # True -> False 로 떨어지는 순간이 '눌림'
                if previous[pin] and not level:
                    if now - self._last_fire.get(pin, 0.0) >= DEBOUNCE_SECONDS:
                        self._last_fire[pin] = now
                        self.emit(self._pin_map[pin])
                previous[pin] = level

            time.sleep(0.005)


# ---------------------------------------------------------------------------
#  로터리 엔코더
# ---------------------------------------------------------------------------


class RotaryEncoderController(InputController):
    """로터리 엔코더 → 볼륨 증감 (누르면 음소거 토글).

    엔코더는 CLK/DT 두 신호의 위상차로 회전 방향을 판별한다.

        시계 방향   : CLK가 먼저 떨어짐  -> VOLUME_UP
        반시계 방향 : DT가 먼저 떨어짐   -> VOLUME_DOWN

    ⚠️ 중요 — Rate Limit 보호:
       엔코더를 빠르게 돌리면 초당 수십 스텝이 발생한다.
       그때마다 API를 호출하면 즉시 429에 걸린다.
       그래서 스텝을 모았다가 일정 시간(ACCUMULATE_MS)마다
       **절대값 한 번**으로 보내는 방식을 쓴다.
    """

    name = "encoder"

    #: 스텝을 모아서 보내는 주기(초)
    ACCUMULATE_SECONDS = 0.15

    #: 한 스텝당 볼륨 변화량(%)
    VOLUME_PER_STEP = 3

    def __init__(self, clk: int, dt: int, sw: int | None = None) -> None:
        super().__init__()
        self._clk_pin = clk
        self._dt_pin = dt
        self._sw_pin = sw

        self._pending_steps = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="rotary-encoder")
        self._thread.start()
        logger.info("로터리 엔코더 활성화 (CLK=%d, DT=%d)", self._clk_pin, self._dt_pin)

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def on_rotate(self, direction: int) -> None:
        """엔코더 한 스텝. 인터럽트 핸들러에서 호출한다.

        Args:
            direction: +1(시계) 또는 -1(반시계)
        """
        with self._lock:
            self._pending_steps += direction

    def on_press(self) -> None:
        """엔코더 버튼(축을 누름) → 재생/일시정지."""
        self.emit(DeckAction.PLAY_PAUSE)

    def _loop(self) -> None:
        """모아 둔 스텝을 주기적으로 하나의 액션으로 내보낸다."""
        while self._running:
            time.sleep(self.ACCUMULATE_SECONDS)

            with self._lock:
                steps, self._pending_steps = self._pending_steps, 0

            if steps == 0:
                continue

            # 상대 증감으로 보낸다. DeckController가 현재 볼륨에 더해 준다.
            amount = abs(steps) * self.VOLUME_PER_STEP
            action = DeckAction.VOLUME_UP if steps > 0 else DeckAction.VOLUME_DOWN
            self.emit(action, step=amount)


# ---------------------------------------------------------------------------
#  터치 LCD
# ---------------------------------------------------------------------------
#
# 터치는 별도 컨트롤러가 필요 없다.
# Qt가 터치를 마우스 이벤트로 변환해 주므로 기존 UI 버튼이 그대로 동작한다.
#
# RK3399에서 확인할 점:
#   1. 터치 영역 크기 — 손가락은 최소 44x44px가 필요하다.
#      app/ui/window.py 의 IconButton size 인자를 키우면 된다.
#   2. 전체화면 실행:
#          window.showFullScreen()
#   3. 마우스 커서 숨기기:
#          from PySide6.QtGui import QCursor
#          from PySide6.QtCore import Qt
#          qt_app.setOverrideCursor(QCursor(Qt.CursorShape.BlankCursor))
#   4. X11 없이 직접 프레임버퍼로 띄우려면:
#          QT_QPA_PLATFORM=linuxfb  python main.py
#      또는 eglfs (GPU 가속). RK3399는 Mali GPU라 eglfs가 더 부드럽다.
