"""키보드 → DeckAction 매핑 테이블.

이 파일은 **키보드 전용 설정**이다.
GPIO/엔코더를 붙일 때는 이 파일을 건드리지 않고
app/config/gpiomap.py 같은 별도 매핑을 추가하면 된다.
두 매핑 모두 최종적으로 같은 DeckAction을 내보내므로
Spotify 로직과 UI는 어떤 입력이 왔는지 알 필요가 없다.

키 이름은 Qt.Key 열거형 이름에서 'Key_' 접두사를 뗀 문자열을 쓴다.
(예: Qt.Key_Space -> "Space", Qt.Key_Left -> "Left", Qt.Key_S -> "S")
"""

from __future__ import annotations

from app.core.actions import DeckAction

#: 기본 키 매핑.  {키 이름: (액션, payload)}
DEFAULT_KEYMAP: dict[str, tuple[DeckAction, dict]] = {
    # --- 요구사항에 명시된 기본 매핑 ---
    "Space": (DeckAction.PLAY_PAUSE, {}),
    "Left": (DeckAction.PREVIOUS_TRACK, {}),
    "Right": (DeckAction.NEXT_TRACK, {}),
    "Up": (DeckAction.VOLUME_UP, {}),
    "Down": (DeckAction.VOLUME_DOWN, {}),
    "S": (DeckAction.TOGGLE_SHUFFLE, {}),
    "R": (DeckAction.TOGGLE_REPEAT, {}),
    "L": (DeckAction.TOGGLE_LIKE, {}),
    # --- 편의 기능 ---
    "Comma": (DeckAction.SEEK_BACKWARD, {"delta_ms": 10_000}),   # ',' 10초 뒤로
    "Period": (DeckAction.SEEK_FORWARD, {"delta_ms": 10_000}),   # '.' 10초 앞으로
    "F5": (DeckAction.REFRESH, {}),
    "Escape": (DeckAction.QUIT, {}),
}

#: 화면의 단축키 안내(Help)에 표시할 순서와 라벨.
KEY_HINTS: tuple[tuple[str, str], ...] = (
    ("Space", "재생 / 일시정지"),
    ("← →", "이전 곡 / 다음 곡"),
    ("↑ ↓", "볼륨 조절"),
    (", .", "10초 뒤로 / 앞으로"),
    ("S", "셔플"),
    ("R", "반복"),
    ("L", "좋아요"),
    ("F5", "새로고침"),
    ("Esc", "종료"),
)
