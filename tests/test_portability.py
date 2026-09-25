"""하드웨어 이식 계층 테스트.

PC와 ESP32가 같은 정의를 쓰는지, 레이아웃이 480x320에 실제로 들어가는지를
실물 없이 검증한다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.core.actions import DeckAction
from app.core.artwork import ArtworkSpec, spec_for_display
from app.core.contract import (
    ACTION_CODES,
    LIKED_UNKNOWN,
    PLAYBACK_FIELDS,
    REPEAT_CODES,
    VOLUME_UNKNOWN,
    action_code,
    action_from_code,
    playback_state_to_contract,
)
from app.spotify.models import PlaybackState, RepeatMode
from app.ui.layouts import COMPACT_480, DESKTOP, PROFILES, profile_for_width

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
#  계약 — PC와 ESP32가 어긋나면 버튼이 엉뚱하게 동작한다
# ---------------------------------------------------------------------------


def test_every_action_has_a_code():
    """액션을 추가하고 코드를 안 주면 ESP32로 보낼 수 없다."""
    missing = [a.name for a in DeckAction if a not in ACTION_CODES]
    assert not missing, f"ACTION_CODES에 빠진 액션: {missing}"


def test_action_codes_are_unique():
    codes = list(ACTION_CODES.values())
    assert len(codes) == len(set(codes)), "액션 코드가 중복되면 버튼이 뒤바뀐다"


def test_action_codes_are_contiguous_from_zero():
    """C++ enum이 빈틈없이 이어져야 배열 인덱스로 쓸 수 있다."""
    assert sorted(ACTION_CODES.values()) == list(range(len(ACTION_CODES)))


def test_action_code_roundtrip():
    for action in DeckAction:
        assert action_from_code(action_code(action)) is action


def test_unknown_code_returns_none():
    """펌웨어가 PC보다 새로울 수 있다. 모르는 코드에 죽으면 안 된다."""
    assert action_from_code(9999) is None


def test_every_repeat_mode_has_a_code():
    missing = [m.name for m in RepeatMode if m not in REPEAT_CODES]
    assert not missing


@pytest.mark.parametrize(
    "spec_action",
    ["PLAY_PAUSE", "PREVIOUS", "NEXT", "VOLUME_UP", "VOLUME_DOWN",
     "SHUFFLE", "REPEAT", "LIKE", "SEEK_FORWARD", "SEEK_BACKWARD"],
)
def test_hardware_spec_actions_exist(spec_action: str):
    """하드웨어 요구사항에 적힌 InputAction이 전부 구현되어 있는지."""
    alias = {
        "PREVIOUS": "PREVIOUS_TRACK",
        "NEXT": "NEXT_TRACK",
        "SHUFFLE": "TOGGLE_SHUFFLE",
        "REPEAT": "TOGGLE_REPEAT",
        "LIKE": "TOGGLE_LIKE",
    }
    name = alias.get(spec_action, spec_action)
    assert hasattr(DeckAction, name), f"{spec_action} -> DeckAction.{name} 없음"


def test_generated_headers_are_up_to_date():
    """계약을 고치고 헤더를 다시 만들지 않으면 여기서 막는다.

    이걸 안 하면 Python 쪽에 액션을 추가해도 ESP32 헤더는 그대로라
    두 플랫폼이 조용히 어긋난다.
    """
    result = subprocess.run(
        [sys.executable, "tools/export_contract.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, (
        "생성물이 오래되었습니다.\n"
        "  python tools/export_contract.py\n"
        f"{result.stdout}{result.stderr}"
    )


# ---------------------------------------------------------------------------
#  상태 직렬화
# ---------------------------------------------------------------------------


def test_contract_covers_required_playback_fields():
    """하드웨어 요구사항에 적힌 PlaybackState 필드가 전부 있는지."""
    names = {f.name for f in PLAYBACK_FIELDS}
    required = {
        "connected", "title", "artist", "album", "album_art_url",
        "is_playing", "progress_ms", "duration_ms", "volume",
        "shuffle", "repeat", "device_name",
    }
    assert required <= names, f"빠진 필드: {required - names}"


def test_string_fields_have_bounded_length():
    """ESP32는 고정 버퍼를 쓴다. 길이가 없으면 C++ 구조체를 만들 수 없다."""
    for field in PLAYBACK_FIELDS:
        if field.ctype == "char[]":
            assert field.max_len and field.max_len > 0, f"{field.name}에 max_len 없음"


def test_serializes_empty_state():
    payload = playback_state_to_contract(PlaybackState.empty(), connected=False)
    assert payload["connected"] is False
    assert payload["has_track"] is False
    assert payload["volume"] == VOLUME_UNKNOWN
    assert payload["liked"] == LIKED_UNKNOWN


def test_serializes_playing_state():
    state = PlaybackState.from_api(
        {
            "device": {"name": "PC", "type": "Computer", "volume_percent": 62,
                       "supports_volume": True},
            "is_playing": True,
            "currently_playing_type": "track",
            "progress_ms": 30_000,
            "shuffle_state": True,
            "repeat_state": "track",
            "item": {
                "id": "t", "uri": "spotify:track:t", "type": "track",
                "name": "곡", "duration_ms": 200_000,
                "artists": [{"name": "A"}, {"name": "B"}],
                "album": {"name": "앨범", "images": [{"url": "x.jpg", "width": 640, "height": 640}]},
            },
        }
    )
    state.is_liked = True
    payload = playback_state_to_contract(state)

    assert payload["title"] == "곡"
    assert payload["artist"] == "A, B"
    assert payload["album_art_url"] == "x.jpg"
    assert payload["volume"] == 62
    assert payload["repeat"] == REPEAT_CODES[RepeatMode.TRACK]
    assert payload["liked"] == 1
    assert payload["duration_ms"] == 200_000


def test_serialized_values_fit_c_types():
    """음수나 None이 uint로 넘어가면 C++ 쪽에서 쓰레기 값이 된다."""
    payload = playback_state_to_contract(PlaybackState.empty())
    assert payload["progress_ms"] >= 0
    assert payload["duration_ms"] >= 0
    assert 0 <= payload["volume"] <= 255
    assert -1 <= payload["liked"] <= 1


# ---------------------------------------------------------------------------
#  레이아웃 — 480x320에 실제로 들어가는가
# ---------------------------------------------------------------------------


def test_compact_matches_target_screen():
    assert (COMPACT_480.window_width, COMPACT_480.window_height) == (480, 320)


def _usable_width(p) -> int:
    return p.window_width - p.margin_h * 2


def test_compact_control_row_fits():
    """컨트롤 6개가 한 줄에 들어가야 한다.

    넘치면 버튼이 잘리거나 겹친다.
    """
    p = COMPACT_480
    usable = _usable_width(p)
    # 균등 배치이므로 버튼 사이에 최소한의 숨 쉴 틈은 있어야 한다.
    minimum_breathing = 6 * 5
    assert usable >= p.control_row_width + minimum_breathing, (
        f"가용 폭 {usable}px < 컨트롤 {p.control_row_width}px + 간격 {minimum_breathing}px"
    )


def test_compact_volume_row_fits():
    """볼륨 아이콘 + 슬라이더가 들어가야 한다.

    이전에 setMaximumWidth만 줘서 슬라이더가 0px로 찌그러진 적이 있다.
    """
    p = COMPACT_480
    needed = p.volume_icon + p.volume_width + 8
    assert _usable_width(p) >= needed, (
        f"가용 폭 {_usable_width(p)}px < 볼륨 {needed}px"
    )


#: 상단바(로고·시계) 높이 추정치
_HEADER_HEIGHT = 20


def test_compact_stack_fits_vertically():
    """세로 스택 전체가 320px 안에 들어가야 한다.

    넘치면 마지막 줄(컨트롤)이 화면 밖으로 밀려 안 보인다.
    앨범 아트를 키울 때 이 검사가 한계를 잡아 준다.

    진행 바는 **미디어 블록 안**(앨범 아트 옆 열)에 있으므로
    별도 줄로 세지 않는다. 블록 높이는 아트 높이가 결정한다.
    """
    p = COMPACT_480
    gap = p.section_gap
    needed = (
        p.margin_v * 2
        + _HEADER_HEIGHT
        + gap
        + p.art_edge          # 미디어 블록 = 아트 높이
        + gap
        + p.play_button       # 컨트롤 줄
    )
    if p.show_volume:
        needed += max(4, gap - 4) + p.seek_height

    assert p.window_height >= needed, (
        f"세로 {p.window_height}px < 필요 {needed}px — 아래 줄이 잘린다. "
        f"art_size를 줄이세요 (현재 {p.art_edge}px)."
    )


def test_compact_info_column_fits_beside_art():
    """곡 정보 + 웨이브 + 진행 바가 앨범 아트 높이 안에 들어가야 한다.

    넘치면 미디어 블록이 아트보다 높아져 컨트롤을 밀어낸다.
    아트를 **줄일 때** 걸리는 검사다 (키울 때는 test_..._fits_vertically).
    """
    p = COMPACT_480
    # 글자 높이는 pt의 약 1.5배로 잡는다 (폰트 어센트·디센트 포함).
    text = int((p.title_pt + p.artist_pt + p.album_pt) * 1.5) + 6
    needed = text + p.wave_height + p.section_gap + p.seek_height + p.meta_pt + 4

    assert p.art_edge >= needed, (
        f"아트 {p.art_edge}px < 오른쪽 열 {needed}px — 블록이 아트보다 높아진다"
    )


def test_compact_info_column_has_room():
    """앨범 아트를 키워도 옆의 곡 정보가 들어갈 폭은 남아야 한다.

    이전에는 '아트가 화면 세로의 45%를 넘지 마라'는 임의의 비율로
    검사했는데, 근거가 없어서 아트를 키울 때마다 걸렸다.
    실제로 중요한 건 "제목이 들어갈 폭이 남는가"다.
    (세로가 모자라는지는 test_compact_stack_fits_vertically 가 본다)
    """
    p = COMPACT_480
    info_width = _usable_width(p) - p.art_edge - p.column_gap

    # 15pt 한글은 글자당 약 20px. 제목 두 줄이면 한 줄에 10자는 들어가야
    # 웬만한 곡 제목이 읽힌다.
    assert info_width >= 200, (
        f"곡 정보 폭 {info_width}px — 아트 {p.art_edge}px가 너무 크다"
    )


def test_compact_keeps_album_line():
    """세로 스택으로 바꾸면서 공간이 생겨 앨범명을 되살렸다."""
    assert COMPACT_480.show_album_line


def test_compact_hides_key_hints():
    """터치 기기에는 키보드가 없다."""
    assert not COMPACT_480.show_key_hints
    assert COMPACT_480.touch_targets


def test_desktop_profile_unchanged():
    """기존 PC UI를 망가뜨리지 않았는지 고정한다."""
    assert (DESKTOP.window_width, DESKTOP.window_height) == (1024, 576)
    assert DESKTOP.title_pt == 26
    assert DESKTOP.play_button == 62
    assert DESKTOP.wave_height == 68
    assert DESKTOP.show_album_line and DESKTOP.show_key_hints


def test_profile_selection_by_width():
    assert profile_for_width(1280) is DESKTOP
    assert profile_for_width(500).name == "desktop_narrow"


def test_locked_profile_ignores_width():
    """--compact 는 창 크기와 무관하게 고정되어야 한다.

    실제 기기는 해상도가 고정이므로, 반응형으로 바뀌면 설계 확인이 안 된다.
    """
    assert profile_for_width(1920, locked=COMPACT_480) is COMPACT_480
    assert profile_for_width(320, locked=COMPACT_480) is COMPACT_480


def test_all_profiles_registered():
    assert set(PROFILES) == {"desktop", "desktop_narrow", "compact_480x320"}


# ---------------------------------------------------------------------------
#  앨범 아트 — ESP32 메모리 예산
# ---------------------------------------------------------------------------


def test_artwork_spec_memory_math():
    spec = ArtworkSpec(175)
    assert spec.rgb565_bytes == 175 * 175 * 2
    assert 0 < spec.scale_from_source < 1


def test_compact_artwork_fits_esp32_heap():
    """Compact 레이아웃의 앨범 아트가 실제로 ESP32 메모리에 들어가는지.

    이 검사가 실패하면 레이아웃 치수를 줄이거나
    스트립 단위 디코딩으로 설계를 바꿔야 한다.
    """
    p = COMPACT_480
    body = p.window_width - p.margin_h * 2 - p.column_gap
    art_edge = body * p.art_stretch // (p.art_stretch + p.panel_stretch)

    spec = spec_for_display(art_edge, oversample=1.0)
    overhead = (4 + 16) * 1024      # JPEG 디코더 작업 + TLS 버퍼
    usable_heap = 180 * 1024

    total = spec.rgb565_bytes + overhead
    assert total < usable_heap, (
        f"앨범 아트 {spec.edge}px = {total // 1024}KB > 가용 {usable_heap // 1024}KB"
    )


def test_artwork_spec_never_exceeds_source():
    """Spotify 원본보다 크게 요청하면 화질만 나빠지고 메모리만 쓴다."""
    assert spec_for_display(2000).edge <= 640


def test_artwork_spec_has_floor():
    assert spec_for_display(1).edge >= 64
