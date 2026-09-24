"""PC ↔ ESP32 공유 계약.

두 플랫폼이 **같은 개념을 같은 이름과 같은 값으로** 쓰게 만드는 단일 출처다.

    Python (PC)                         C++ (ESP32)
    DeckAction.NEXT_TRACK  ==  3  ==  DeckAction::NEXT_TRACK
    PlaybackState.title        ==     PlaybackState.title

왜 필요한가:
    두 코드베이스가 각자 enum을 손으로 정의하면 반드시 어긋난다.
    ESP32에서 버튼 3번이 VOLUME_UP인데 PC에서는 NEXT_TRACK이면
    같은 하드웨어가 다른 동작을 하고, 원인을 찾기 매우 어렵다.

어떻게 막는가:
    이 파일이 유일한 정의이고, `tools/export_contract.py`가
    여기서 C++ 헤더를 생성한다. 손으로 쓴 C++ enum은 존재하지 않는다.
    테스트(tests/test_contract.py)가 생성물이 최신인지 확인하므로
    Python 쪽에 액션을 추가하고 헤더를 다시 만들지 않으면 CI가 막는다.

버전 관리:
    CONTRACT_VERSION은 호환성이 깨지는 변경(액션 삭제, 값 변경, 필드 삭제)에만 올린다.
    끝에 액션을 **추가**하는 것은 기존 값을 바꾸지 않으므로 올리지 않아도 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.actions import DeckAction
from app.spotify.models import RepeatMode

#: 계약 버전. 호환성이 깨지는 변경에만 올린다.
CONTRACT_VERSION = 1


# ---------------------------------------------------------------------------
#  액션 — 고정된 정수값
# ---------------------------------------------------------------------------
#
#  ⚠️ 여기 적힌 숫자는 **절대 바꾸지 않는다.**
#     ESP32 펌웨어에 구워진 값과 어긋나면 버튼이 엉뚱하게 동작한다.
#     새 액션은 반드시 **끝에 추가**한다.
#
ACTION_CODES: dict[DeckAction, int] = {
    DeckAction.PLAY_PAUSE: 0,
    DeckAction.PLAY: 1,
    DeckAction.PAUSE: 2,
    DeckAction.NEXT_TRACK: 3,
    DeckAction.PREVIOUS_TRACK: 4,
    DeckAction.VOLUME_UP: 5,
    DeckAction.VOLUME_DOWN: 6,
    DeckAction.VOLUME_SET: 7,
    DeckAction.SEEK_SET: 8,
    DeckAction.SEEK_FORWARD: 9,
    DeckAction.SEEK_BACKWARD: 10,
    DeckAction.TOGGLE_SHUFFLE: 11,
    DeckAction.TOGGLE_REPEAT: 12,
    DeckAction.TOGGLE_LIKE: 13,
    DeckAction.REFRESH: 14,
    DeckAction.QUIT: 15,
}

#: 반복 모드의 고정 정수값
REPEAT_CODES: dict[RepeatMode, int] = {
    RepeatMode.OFF: 0,
    RepeatMode.CONTEXT: 1,
    RepeatMode.TRACK: 2,
}


def action_code(action: DeckAction) -> int:
    """액션의 고정 정수값. ESP32와 주고받을 때 쓴다."""
    return ACTION_CODES[action]


def action_from_code(code: int) -> DeckAction | None:
    """정수값을 액션으로. 모르는 값이면 None (펌웨어가 더 새로울 수 있다)."""
    for action, value in ACTION_CODES.items():
        if value == code:
            return action
    return None


# ---------------------------------------------------------------------------
#  재생 상태 — 두 플랫폼의 UI가 그리는 데이터
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldSpec:
    """계약 필드 하나의 정의.

    Attributes:
        name:     양쪽에서 쓰는 이름.
        ctype:    C++ 타입.
        max_len:  문자열이면 최대 바이트. ESP32는 동적 할당을 피해야 하므로
                  고정 길이 버퍼를 쓴다.
        note:     의미 설명.
    """

    name: str
    ctype: str
    max_len: int | None = None
    note: str = ""


#: ESP32의 문자열 버퍼 크기.
#: UTF-8 한글은 글자당 3바이트다. 한글 40자 정도면 화면에 다 못 들어가므로
#: 128바이트면 충분하고, 넘치면 UI에서 말줄임 처리한다.
_TEXT = 128
_SHORT_TEXT = 64

PLAYBACK_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("connected", "bool", note="Spotify API 연결 상태"),
    FieldSpec("has_track", "bool", note="재생 중인 콘텐츠가 있는지"),
    FieldSpec("title", "char[]", _TEXT, "곡 제목"),
    FieldSpec("artist", "char[]", _TEXT, "아티스트 (여러 명이면 ', '로 연결)"),
    FieldSpec("album", "char[]", _TEXT, "앨범명"),
    FieldSpec("album_art_url", "char[]", 256, "앨범 아트 URL (이미지 자체가 아님)"),
    FieldSpec("is_playing", "bool", note="재생 중이면 true"),
    FieldSpec("progress_ms", "uint32_t", note="현재 재생 위치 (밀리초)"),
    FieldSpec("duration_ms", "uint32_t", note="곡 전체 길이 (밀리초)"),
    FieldSpec("volume", "uint8_t", note="0~100. 기기가 미지원이면 255"),
    FieldSpec("shuffle", "bool"),
    FieldSpec("repeat", "uint8_t", note="RepeatMode 값 (0=off, 1=context, 2=track)"),
    FieldSpec("liked", "int8_t", note="1=좋아요, 0=아님, -1=확인 안 됨"),
    FieldSpec("device_name", "char[]", _SHORT_TEXT, "재생 중인 기기 이름"),
    FieldSpec("supports_volume", "bool", note="기기가 볼륨 조절을 지원하는지"),
)

#: 볼륨을 읽을 수 없을 때 쓰는 값 (uint8_t에 None이 없으므로)
VOLUME_UNKNOWN = 255

#: 좋아요 여부를 확인하지 못했을 때
LIKED_UNKNOWN = -1


# ---------------------------------------------------------------------------
#  직렬화
# ---------------------------------------------------------------------------


def playback_state_to_contract(state: Any, *, connected: bool = True) -> dict:
    """PlaybackState를 계약 형태의 dict로 바꾼다.

    ESP32로 상태를 보내거나(향후), 디버깅용으로 덤프할 때 쓴다.
    PC UI는 PlaybackState를 직접 쓰므로 이 함수를 거치지 않는다.

    Args:
        state: app.spotify.models.PlaybackState
        connected: Spotify 연결 상태. PlaybackState에는 없고 앱이 판단한다.
    """
    volume = state.device.volume_percent
    liked = state.is_liked

    return {
        "connected": connected,
        "has_track": state.has_track,
        "title": state.title,
        "artist": state.artist_text,
        "album": state.album,
        "album_art_url": state.album_art_url or "",
        "is_playing": state.is_playing,
        "progress_ms": max(0, state.estimated_progress_ms()),
        "duration_ms": max(0, state.duration_ms),
        "volume": VOLUME_UNKNOWN if volume is None else int(volume),
        "shuffle": bool(state.shuffle),
        "repeat": REPEAT_CODES[state.repeat],
        "liked": LIKED_UNKNOWN if liked is None else int(liked),
        "device_name": state.device.name,
        "supports_volume": bool(state.device.supports_volume),
    }


def contract_descriptor() -> dict:
    """계약 전체를 기계가 읽을 수 있는 형태로.

    tools/export_contract.py가 이걸로 C++ 헤더와 JSON을 만든다.
    """
    return {
        "version": CONTRACT_VERSION,
        "actions": [
            {"name": action.name, "code": code, "value": action.value}
            for action, code in sorted(ACTION_CODES.items(), key=lambda kv: kv[1])
        ],
        "repeat_modes": [
            {"name": mode.name, "code": code, "value": mode.value}
            for mode, code in sorted(REPEAT_CODES.items(), key=lambda kv: kv[1])
        ],
        "playback_fields": [
            {
                "name": f.name,
                "ctype": f.ctype,
                "max_len": f.max_len,
                "note": f.note,
            }
            for f in PLAYBACK_FIELDS
        ],
        "constants": {
            "VOLUME_UNKNOWN": VOLUME_UNKNOWN,
            "LIKED_UNKNOWN": LIKED_UNKNOWN,
        },
    }
