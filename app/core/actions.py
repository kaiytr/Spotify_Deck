"""덱 액션(Deck Action) 정의.

이 모듈이 **입력 장치 계층과 Spotify 제어 계층 사이의 유일한 계약**이다.

    [KeyboardController]  ─┐
    [GPIOController]      ─┼─→  DeckAction  ─→  [DeckController]  ─→  [SpotifyPlayer]
    [EncoderController]   ─┘     (이 파일)

입력 장치는 "어떤 키가 눌렸는지" 가 아니라 "무슨 동작을 원하는지"만 전달한다.
따라서 키보드를 물리 버튼/로터리 엔코더로 교체해도
Spotify 로직과 UI는 한 줄도 바뀌지 않는다.

액션을 추가할 때는:
    1. 아래 DeckAction에 멤버를 추가하고
    2. app/core/deck_controller.py 의 핸들러 맵에 처리기를 등록하면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DeckAction(str, Enum):
    """사용자가 요청할 수 있는 모든 동작.

    str을 상속하므로 로그/설정 파일에서 그대로 문자열로 다룰 수 있다.
    """

    # --- 재생 제어 ---
    PLAY_PAUSE = "play_pause"
    """재생 중이면 일시정지, 일시정지 중이면 재생 (토글)."""

    PLAY = "play"
    """명시적 재생. 물리 버튼이 2개로 분리된 하드웨어를 위해 준비."""

    PAUSE = "pause"
    """명시적 일시정지."""

    NEXT_TRACK = "next_track"
    PREVIOUS_TRACK = "previous_track"

    # --- 볼륨 ---
    VOLUME_UP = "volume_up"
    """상대 증가. payload['step']으로 증감폭 지정 가능 (기본 5)."""

    VOLUME_DOWN = "volume_down"
    """상대 감소. payload['step']으로 증감폭 지정 가능 (기본 5)."""

    VOLUME_SET = "volume_set"
    """절대값 설정. payload['value'] = 0~100. 슬라이더/엔코더용."""

    # --- 재생 위치 ---
    SEEK_SET = "seek_set"
    """절대 위치로 이동. payload['position_ms'] = 밀리초."""

    SEEK_FORWARD = "seek_forward"
    """상대 이동(앞으로). payload['delta_ms'] (기본 10000)."""

    SEEK_BACKWARD = "seek_backward"
    """상대 이동(뒤로). payload['delta_ms'] (기본 10000)."""

    # --- 모드 토글 ---
    TOGGLE_SHUFFLE = "toggle_shuffle"
    TOGGLE_REPEAT = "toggle_repeat"
    """repeat 상태를 off → context → track → off 순으로 순환."""

    TOGGLE_LIKE = "toggle_like"
    """현재 곡 좋아요 추가/해제."""

    # --- 시스템 ---
    REFRESH = "refresh"
    """즉시 재생 정보 갱신 요청."""

    QUIT = "quit"
    """앱 종료."""


#: 볼륨 상대 조절의 기본 증감폭(%)
DEFAULT_VOLUME_STEP = 5

#: 재생 위치 상대 이동의 기본 폭(ms)
DEFAULT_SEEK_DELTA_MS = 10_000


@dataclass(frozen=True)
class ActionEvent:
    """입력 장치가 발생시키는 단일 이벤트.

    Attributes:
        action:  요청된 동작.
        payload: 동작에 필요한 부가 값.
                 예) VOLUME_SET -> {"value": 42}
                     SEEK_SET   -> {"position_ms": 91000}
        source:  이벤트를 만든 입력 장치 이름. 로깅/디버깅용.
                 예) "keyboard", "gpio", "encoder", "ui"
    """

    action: DeckAction
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "unknown"

    def get(self, key: str, default: Any = None) -> Any:
        """payload 값을 안전하게 꺼낸다."""
        return self.payload.get(key, default)

    def __str__(self) -> str:  # pragma: no cover - 로깅 편의용
        if self.payload:
            return f"{self.action.value}({self.payload}) from {self.source}"
        return f"{self.action.value} from {self.source}"
