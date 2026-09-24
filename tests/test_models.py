"""재생 상태 파싱 테스트.

Spotify API 응답 구조가 바뀌거나 필드가 빠져도
UI가 죽지 않는지를 확인하는 것이 핵심이다.
"""

from __future__ import annotations

import pytest

from app.spotify.models import PlaybackState, RepeatMode, format_duration

TRACK_PAYLOAD = {
    "device": {
        "id": "dev1",
        "name": "내 PC",
        "type": "Computer",
        "volume_percent": 65,
        "supports_volume": True,
        "is_active": True,
        "is_restricted": False,
    },
    "repeat_state": "context",
    "shuffle_state": True,
    "progress_ms": 151_000,
    "is_playing": True,
    "currently_playing_type": "track",
    "item": {
        "id": "t1",
        "uri": "spotify:track:t1",
        "type": "track",
        "name": "Song Title",
        "duration_ms": 225_000,
        "artists": [{"name": "Artist A"}, {"name": "Artist B"}],
        "album": {
            "name": "Album Name",
            "images": [
                {"url": "small.jpg", "width": 64, "height": 64},
                {"url": "large.jpg", "width": 640, "height": 640},
                {"url": "medium.jpg", "width": 300, "height": 300},
            ],
        },
    },
    "actions": {"disallows": {"resuming": True}},
}


# ---------------------------------------------------------------------------
#  기본 파싱
# ---------------------------------------------------------------------------


def test_no_content_response_is_empty_not_error():
    """204는 오류가 아니라 '재생 중 아님'이라는 정상 상태다."""
    state = PlaybackState.from_api(None)
    assert state.is_empty
    assert not state.has_track
    assert state.position_text() == "--:-- / --:--"


def test_parses_track_fields():
    s = PlaybackState.from_api(TRACK_PAYLOAD)
    assert s.title == "Song Title"
    assert s.artist_text == "Artist A, Artist B"
    assert s.album == "Album Name"
    assert s.duration_ms == 225_000
    assert s.shuffle is True
    assert s.repeat is RepeatMode.CONTEXT
    assert s.volume == 65


def test_picks_largest_album_image():
    """작은 이미지를 고르면 큰 화면에서 뭉개진다."""
    assert PlaybackState.from_api(TRACK_PAYLOAD).album_art_url == "large.jpg"


def test_image_without_dimensions_does_not_crash():
    payload = {**TRACK_PAYLOAD}
    payload["item"] = {
        **TRACK_PAYLOAD["item"],
        "album": {"name": "A", "images": [{"url": "x.jpg"}, {"url": "y.jpg", "width": None}]},
    }
    assert PlaybackState.from_api(payload).album_art_url in ("x.jpg", "y.jpg")


def test_device_type_is_localized():
    assert PlaybackState.from_api(TRACK_PAYLOAD).device.icon_hint == "컴퓨터"


def test_disallowed_actions_are_parsed():
    s = PlaybackState.from_api(TRACK_PAYLOAD)
    assert not s.can("resuming")
    assert s.can("seeking")


# ---------------------------------------------------------------------------
#  진행률 보간
# ---------------------------------------------------------------------------


def test_progress_interpolates_while_playing():
    """1초 폴링 사이를 메워야 진행 바가 끊기지 않는다."""
    s = PlaybackState.from_api(TRACK_PAYLOAD)
    assert s.estimated_progress_ms(now=s.fetched_at + 0.5) == 151_500


def test_progress_frozen_while_paused():
    s = PlaybackState.from_api({**TRACK_PAYLOAD, "is_playing": False})
    assert s.estimated_progress_ms(now=s.fetched_at + 10) == 151_000


def test_progress_never_exceeds_duration():
    """곡이 끝났는데 폴링이 늦으면 진행 바가 넘칠 수 있다."""
    s = PlaybackState.from_api(TRACK_PAYLOAD)
    assert s.estimated_progress_ms(now=s.fetched_at + 9999) == 225_000
    assert s.progress_ratio(now=s.fetched_at + 9999) == 1.0


def test_position_text_format():
    s = PlaybackState.from_api(TRACK_PAYLOAD)
    assert s.position_text(now=s.fetched_at) == "2:31 / 3:45"


@pytest.mark.parametrize(
    "ms,expected",
    [(0, "0:00"), (5_000, "0:05"), (65_000, "1:05"), (3_600_000, "1:00:00"), (None, "--:--"), (-5, "--:--")],
)
def test_duration_formatting(ms, expected):
    assert format_duration(ms) == expected


# ---------------------------------------------------------------------------
#  팟캐스트 / 광고
# ---------------------------------------------------------------------------


def test_episode_maps_show_into_artist_slot():
    """에피소드는 artists가 없다. UI가 구분 없이 쓰도록 흡수한다."""
    payload = {
        "device": {"name": "폰", "type": "Smartphone", "volume_percent": 40},
        "repeat_state": "off",
        "shuffle_state": False,
        "progress_ms": 1000,
        "is_playing": True,
        "currently_playing_type": "episode",
        "item": {
            "id": "e1",
            "uri": "spotify:episode:e1",
            "type": "episode",
            "name": "1화",
            "duration_ms": 3_600_000,
            "images": [],
            "show": {"name": "어떤 팟캐스트", "images": [{"url": "show.jpg", "width": 640, "height": 640}]},
        },
    }
    s = PlaybackState.from_api(payload)
    assert s.title == "1화"
    assert s.artist_text == "어떤 팟캐스트"
    assert s.album_art_url == "show.jpg", "에피소드 이미지가 없으면 쇼 이미지를 쓴다"


def test_ad_is_not_empty_and_blocks_skip():
    payload = {
        "device": {"name": "PC", "type": "Computer", "volume_percent": 50},
        "is_playing": True,
        "currently_playing_type": "ad",
        "item": None,
        "progress_ms": 5000,
        "shuffle_state": False,
        "repeat_state": "off",
        "actions": {"disallows": {"skipping_next": True, "skipping_prev": True}},
    }
    s = PlaybackState.from_api(payload)
    assert s.is_ad
    assert not s.is_empty, "광고 중에도 기기 정보는 유효하다"
    assert not s.can("skipping_next")
    assert s.device.volume_percent == 50


# ---------------------------------------------------------------------------
#  반복 모드
# ---------------------------------------------------------------------------


def test_repeat_cycles_off_context_track():
    assert RepeatMode.OFF.next_mode() is RepeatMode.CONTEXT
    assert RepeatMode.CONTEXT.next_mode() is RepeatMode.TRACK
    assert RepeatMode.TRACK.next_mode() is RepeatMode.OFF


def test_unknown_repeat_value_defaults_to_off():
    """API가 새 값을 추가해도 죽지 않아야 한다."""
    assert RepeatMode.parse("something_new") is RepeatMode.OFF
    assert RepeatMode.parse(None) is RepeatMode.OFF


# ---------------------------------------------------------------------------
#  결측 필드 내성
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"item": None, "is_playing": False},
        {"item": {"id": "x", "type": "track", "name": "N"}},
        {"item": {"id": "x", "type": "track", "name": "N", "album": {}}},
        {"item": {"id": "x", "type": "track", "name": "N", "artists": []}, "device": None},
        {"progress_ms": None, "item": None},
    ],
)
def test_survives_missing_fields(payload):
    """API가 필드를 빼도 UI가 죽으면 안 된다."""
    s = PlaybackState.from_api(payload)
    s.position_text()
    s.progress_ratio()
    s.artist_text
    s.volume


def test_same_track_detection_avoids_art_reload():
    a = PlaybackState.from_api(TRACK_PAYLOAD)
    b = PlaybackState.from_api(TRACK_PAYLOAD)
    other = PlaybackState.from_api({**TRACK_PAYLOAD, "item": {**TRACK_PAYLOAD["item"], "id": "t2"}})

    assert a.is_same_track(b)
    assert not a.is_same_track(other)
    assert not a.is_same_track(None)
