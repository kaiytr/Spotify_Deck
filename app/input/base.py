"""입력 장치 추상 인터페이스.

    InputController (이 파일)
    ├── KeyboardController   (구현됨) app/input/keyboard.py
    ├── GPIOController       (향후)   물리 버튼 - RPi.GPIO / periphery
    ├── EncoderController    (향후)   로터리 엔코더 - 볼륨/위치 이동
    └── TouchController      (향후)   터치 LCD

새 하드웨어를 붙이는 방법:

    class GPIOController(InputController):
        name = "gpio"

        def start(self):
            for pin, action in PIN_MAP.items():
                gpio.on_falling_edge(pin, lambda a=action: self.emit(a))

        def stop(self):
            gpio.cleanup()

`emit()`만 호출하면 나머지(디스패치, 오류 처리, UI 갱신)는 기존 코드가 처리한다.
Spotify 로직과 UI는 전혀 수정할 필요가 없다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.core.actions import ActionEvent, DeckAction

logger = logging.getLogger(__name__)

#: 입력 장치가 액션을 내보낼 때 호출하는 콜백
ActionSink = Callable[[ActionEvent], None]


class InputController(ABC):
    """모든 입력 장치의 공통 부모.

    구현체는 `start()`/`stop()`과 `name`만 채우면 된다.
    액션을 내보낼 때는 `self.emit(...)`을 호출한다.
    """

    #: 로그와 ActionEvent.source에 쓰이는 식별자
    name: str = "input"

    def __init__(self) -> None:
        self._sink: ActionSink | None = None
        self._enabled = True

    # -- 수명 주기 ----------------------------------------------------------

    def bind(self, sink: ActionSink) -> None:
        """액션을 받을 대상을 연결한다. InputManager가 호출한다."""
        self._sink = sink

    @abstractmethod
    def start(self) -> None:
        """입력 감지를 시작한다 (핀 설정, 이벤트 후킹 등)."""

    @abstractmethod
    def stop(self) -> None:
        """자원을 정리한다 (GPIO cleanup, 스레드 종료 등)."""

    # -- 액션 발행 ----------------------------------------------------------

    def emit(self, action: DeckAction, **payload: Any) -> None:
        """액션을 내보낸다.

        예:
            self.emit(DeckAction.NEXT_TRACK)
            self.emit(DeckAction.VOLUME_SET, value=70)
        """
        if not self._enabled:
            return
        if self._sink is None:
            logger.warning("[%s] sink가 연결되지 않아 액션을 버립니다: %s", self.name, action)
            return
        self._sink(ActionEvent(action=action, payload=payload, source=self.name))

    # -- 활성/비활성 --------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """일시적으로 입력을 무시한다 (예: 설정 화면이 떠 있는 동안)."""
        self._enabled = value


class InputManager:
    """여러 입력 장치를 동시에 관리한다.

    키보드와 GPIO를 함께 쓰는 상황(개발 중 디버깅)을 자연스럽게 지원한다.

        manager = InputManager(on_action=controller.handle)
        manager.register(KeyboardController(window))
        manager.register(GPIOController())     # 나중에 한 줄 추가
        manager.start_all()
    """

    def __init__(self, on_action: ActionSink) -> None:
        self._on_action = on_action
        self._controllers: list[InputController] = []

    def register(self, controller: InputController) -> InputController:
        """입력 장치를 추가한다. 이미 start_all() 했다면 즉시 시작한다."""
        controller.bind(self._on_action)
        self._controllers.append(controller)
        logger.debug("입력 장치 등록: %s", controller.name)
        return controller

    def start_all(self) -> None:
        for controller in self._controllers:
            try:
                controller.start()
                logger.info("입력 장치 시작: %s", controller.name)
            except Exception:  # noqa: BLE001 - 한 장치 실패가 전체를 막으면 안 된다
                logger.exception("입력 장치 시작 실패: %s", controller.name)

    def stop_all(self) -> None:
        for controller in self._controllers:
            try:
                controller.stop()
            except Exception:  # noqa: BLE001
                logger.exception("입력 장치 종료 실패: %s", controller.name)

    def set_enabled(self, value: bool) -> None:
        for controller in self._controllers:
            controller.set_enabled(value)

    @property
    def controllers(self) -> tuple[InputController, ...]:
        return tuple(self._controllers)
