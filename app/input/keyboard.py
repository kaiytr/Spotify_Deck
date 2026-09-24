"""키보드 입력 컨트롤러.

Qt의 키 이벤트를 DeckAction으로 번역한다.
매핑 자체는 app/config/keymap.py에 있어 이 파일을 고치지 않고 바꿀 수 있다.

향후 GPIOController로 교체할 때 이 파일은 지우거나 그냥 두면 된다.
(개발 중에는 키보드와 GPIO를 동시에 쓰는 편이 디버깅에 편하다)
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent

from app.config.keymap import DEFAULT_KEYMAP
from app.core.actions import DeckAction
from app.input.base import InputController

logger = logging.getLogger(__name__)


def _build_qt_keymap(keymap: dict[str, tuple[DeckAction, dict]]) -> dict[int, tuple[DeckAction, dict]]:
    """문자열 키 이름을 Qt 키 코드로 변환한다.

    "Space" -> Qt.Key_Space -> 0x20

    설정 파일에 사람이 읽기 좋은 이름을 쓰되
    런타임 조회는 정수 비교로 빠르게 하기 위함이다.
    """
    resolved: dict[int, tuple[DeckAction, dict]] = {}
    for key_name, binding in keymap.items():
        qt_key = getattr(Qt.Key, f"Key_{key_name}", None)
        if qt_key is None:
            logger.warning("알 수 없는 키 이름이라 무시합니다: %r", key_name)
            continue
        resolved[int(qt_key.value)] = binding
    return resolved


class KeyboardController(InputController):
    """Qt 위젯에 이벤트 필터를 달아 키 입력을 감지한다.

    위젯의 keyPressEvent를 오버라이드하지 않고 이벤트 필터를 쓰는 이유:
    UI 코드와 입력 코드를 섞지 않기 위해서다.
    UI(window.py)는 키보드가 붙어 있다는 사실조차 몰라도 된다.
    """

    name = "keyboard"

    def __init__(self, target: QObject, keymap: dict | None = None) -> None:
        """
        Args:
            target: 키 이벤트를 감시할 위젯 (보통 메인 윈도우).
            keymap: 사용할 매핑. None이면 DEFAULT_KEYMAP.
        """
        super().__init__()
        self._target = target
        self._keymap = _build_qt_keymap(keymap or DEFAULT_KEYMAP)
        self._filter: _KeyEventFilter | None = None

    def start(self) -> None:
        self._filter = _KeyEventFilter(self)
        self._target.installEventFilter(self._filter)
        logger.debug("키보드 매핑 %d개 활성화", len(self._keymap))

    def stop(self) -> None:
        if self._filter is not None:
            self._target.removeEventFilter(self._filter)
            self._filter = None

    def handle_key(self, key: int, modifiers: Qt.KeyboardModifier) -> bool:
        """키 하나를 처리한다.

        Returns:
            True면 이 키를 소비했다는 뜻 (Qt가 더 전달하지 않는다).
        """
        # Ctrl/Alt 조합은 창 단축키일 수 있으므로 건드리지 않는다.
        # Shift는 허용한다 (대문자 S/R/L이 그대로 들어온다).
        blocking = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        if modifiers & blocking:
            return False

        binding = self._keymap.get(key)
        if binding is None:
            return False

        action, payload = binding
        self.emit(action, **payload)
        return True


class _KeyEventFilter(QObject):
    """QObject 이벤트 필터.

    InputController가 QObject를 상속하지 않아도 되도록 분리했다.
    (다중 상속은 shiboken 바인딩에서 문제를 일으키기 쉽다)
    """

    def __init__(self, controller: KeyboardController) -> None:
        super().__init__()
        self._controller = controller

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt 규약
        if event.type() != QEvent.Type.KeyPress:
            return False

        assert isinstance(event, QKeyEvent)

        # 키를 누르고 있을 때 발생하는 자동 반복은 무시한다.
        # 반복을 허용하면 Spotify API에 초당 수십 건이 나가 Rate Limit에 걸린다.
        # (볼륨을 길게 누르는 조작은 UI 슬라이더로 제공한다)
        if event.isAutoRepeat():
            return True

        return self._controller.handle_key(event.key(), event.modifiers())
