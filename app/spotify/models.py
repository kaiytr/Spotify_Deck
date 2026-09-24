"""재생 상태 도메인 모델.

Spotify API의 원시 JSON을 UI가 쓰기 좋은 형태로 정규화한다.
UI는 이 데이터클래스만 알면 되고, API 응답 구조가 바뀌어도
`PlaybackState.from_api()` 한 곳만 고치면 된다.

트랙(track)과 팟캐스트 에피소드(episode)의 JSON 구조가 다르지만
여기서 같은 모양으로 흡수하므로 UI는 구분할 필요가 없다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class RepeatMode(str, Enum):
    """Spotify의 repeat_state 값."""

    OFF = "off"
    CONTEXT = "context"  # 앨범/플레이리스트 전체 반복
    TRACK = "track"      # 현재 곡 한 곡 반복

    @property
    def label(self) -> str:
        return {"off": "반복 꺼짐", "context": "전체 반복", "track": "한 곡 반복"}[self.value]

    def next_mode(self) -> "RepeatMode":
        """토글 순환: off -> context -> track -> off"""
        order = [RepeatMode.OFF, RepeatMode.CONTEXT, RepeatMode.TRACK]
        return order[(order.index(self) + 1) % len(order)]

    @classmethod
    def parse(cls, value: str | None) -> "RepeatMode":
        try:
            return cls(value or "off")
        except ValueError:
            return cls.OFF


def format_duration(ms: int | None) -> str:
    """밀리초를 M:SS 또는 H:MM:SS 로 포맷한다."""
    if ms is None or ms < 0:
        return "--:--"
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@dataclass
class DeviceInfo:
    """재생 중인 Spotify Connect 기기."""

    id: str | None = None
    name: str = ""
    type: str = ""
    volume_percent: int | None = None
    supports_volume: bool = True
    is_active: bool = False
    #: True면 이 기기는 Web API 명령을 받지 않는다.
    is_restricted: bool = False

    @classmethod
    def from_api(cls, data: dict | None) -> "DeviceInfo":
        if not data:
            return cls()
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            type=data.get("type", ""),
            volume_percent=data.get("volume_percent"),
            # 필드가 없으면 지원한다고 가정한다 (구형 응답 호환).
            supports_volume=data.get("supports_volume", True),
            is_active=data.get("is_active", False),
            is_restricted=data.get("is_restricted", False),
        )

    @property
    def icon_hint(self) -> str:
        """기기 종류를 한국어로."""
        return {
            "computer": "컴퓨터",
            "smartphone": "휴대폰",
            "speaker": "스피커",
            "tv": "TV",
            "tablet": "태블릿",
            "game_console": "게임 콘솔",
            "cast_video": "크롬캐스트",
            "cast_audio": "크롬캐스트",
            "automobile": "자동차",
        }.get(self.type.lower(), self.type or "기기")


@dataclass
class PlaybackState:
    """현재 재생 상태 전체 스냅샷.

    `is_empty=True` 면 재생 중인 콘텐츠가 없다는 뜻이며 오류가 아니다.
    """

    # --- 콘텐츠 ---
    track_id: str | None = None
    track_uri: str | None = None
    title: str = ""
    artists: tuple[str, ...] = ()
    album: str = ""
    album_art_url: str | None = None
    duration_ms: int = 0
    #: "track" | "episode" | "ad" | "unknown"
    content_type: str = "unknown"

    # --- 진행 상태 ---
    progress_ms: int = 0
    is_playing: bool = False

    # --- 모드 ---
    shuffle: bool = False
    repeat: RepeatMode = RepeatMode.OFF
    is_liked: bool | None = None  # None = 아직 확인 안 됨

    # --- 기기 ---
    device: DeviceInfo = field(default_factory=DeviceInfo)

    # --- 허용된 동작 (actions.disallows 역발상) ---
    #: 이 집합에 든 동작은 현재 불가능하다. 예) 광고 중에는 "skipping_next"
    disallowed: frozenset[str] = frozenset()

    # --- 메타 ---
    is_empty: bool = False
    #: 이 스냅샷을 받은 시각 (monotonic). 진행률 보간에 사용.
    fetched_at: float = field(default_factory=time.monotonic)

    # -- 생성 ---------------------------------------------------------------

    @classmethod
    def empty(cls) -> "PlaybackState":
        """재생 중인 콘텐츠가 없을 때."""
        return cls(is_empty=True)

    @classmethod
    def from_api(cls, data: dict | None) -> "PlaybackState":
        """GET /me/player 응답을 파싱한다.

        204(본문 없음)면 data가 None으로 들어오며 빈 상태를 반환한다.
        """
        if not data:
            return cls.empty()

        item = data.get("item")
        device = DeviceInfo.from_api(data.get("device"))
        content_type = data.get("currently_playing_type", "unknown")

        # 광고 구간에는 item이 null이다. 기기 정보는 살아 있으므로 유지한다.
        if not item:
            return cls(
                is_empty=content_type != "ad",
                content_type=content_type,
                title="광고 재생 중" if content_type == "ad" else "",
                is_playing=data.get("is_playing", False),
                progress_ms=data.get("progress_ms") or 0,
                shuffle=data.get("shuffle_state", False),
                repeat=RepeatMode.parse(data.get("repeat_state")),
                device=device,
                disallowed=_parse_disallows(data.get("actions")),
            )

        if item.get("type") == "episode":
            title, artists, album, art = _parse_episode(item)
        else:
            title, artists, album, art = _parse_track(item)

        return cls(
            track_id=item.get("id"),
            track_uri=item.get("uri"),
            title=title,
            artists=artists,
            album=album,
            album_art_url=art,
            duration_ms=item.get("duration_ms") or 0,
            content_type=content_type if content_type != "unknown" else item.get("type", "track"),
            progress_ms=data.get("progress_ms") or 0,
            is_playing=data.get("is_playing", False),
            shuffle=data.get("shuffle_state", False),
            repeat=RepeatMode.parse(data.get("repeat_state")),
            device=device,
            disallowed=_parse_disallows(data.get("actions")),
        )

    # -- 파생 값 -------------------------------------------------------------

    @property
    def artist_text(self) -> str:
        """여러 아티스트를 ', ' 로 연결."""
        return ", ".join(self.artists)

    @property
    def has_track(self) -> bool:
        return bool(self.track_id) and not self.is_empty

    @property
    def is_ad(self) -> bool:
        return self.content_type == "ad"

    @property
    def volume(self) -> int:
        return self.device.volume_percent if self.device.volume_percent is not None else 0

    def estimated_progress_ms(self, *, now: float | None = None) -> int:
        """폴링 사이를 보간한 현재 재생 위치.

        1초마다 폴링하면 진행 바가 1초씩 뚝뚝 끊긴다.
        재생 중일 때는 마지막 응답 이후 흐른 실제 시간을 더해
        60fps로 부드럽게 움직이게 한다.
        """
        if not self.is_playing or self.duration_ms <= 0:
            return self.progress_ms
        elapsed = ((now or time.monotonic()) - self.fetched_at) * 1000
        return min(int(self.progress_ms + elapsed), self.duration_ms)

    def progress_ratio(self, *, now: float | None = None) -> float:
        """0.0 ~ 1.0 진행률."""
        if self.duration_ms <= 0:
            return 0.0
        return min(self.estimated_progress_ms(now=now) / self.duration_ms, 1.0)

    def position_text(self, *, now: float | None = None) -> str:
        """'2:31 / 3:45' 형식.

        재생 중인 콘텐츠가 없으면 '0:00 / 0:00' 대신 '--:-- / --:--' 를 보여 준다.
        0:00은 '곡의 맨 앞'처럼 읽혀서 '재생 없음'과 헷갈리기 때문이다.
        """
        if self.duration_ms <= 0:
            return "--:-- / --:--"
        return (
            f"{format_duration(self.estimated_progress_ms(now=now))}"
            f" / {format_duration(self.duration_ms)}"
        )

    def can(self, action: str) -> bool:
        """해당 동작이 현재 허용되는지.

        Args:
            action: Spotify actions 키. 예) "skipping_next", "seeking"
        """
        return action not in self.disallowed

    def is_same_track(self, other: "PlaybackState | None") -> bool:
        """같은 곡인지. 앨범 아트 재다운로드를 피하는 데 쓴다."""
        if other is None:
            return False
        return self.track_id == other.track_id and self.track_id is not None


# ---------------------------------------------------------------------------
#  파싱 보조
# ---------------------------------------------------------------------------


def _parse_track(item: dict) -> tuple[str, tuple[str, ...], str, str | None]:
    """TrackObject → (제목, 아티스트들, 앨범명, 앨범아트 URL)"""
    album = item.get("album") or {}
    artists = tuple(a.get("name", "") for a in item.get("artists") or [] if a.get("name"))
    return (
        item.get("name", ""),
        artists,
        album.get("name", ""),
        _largest_image(album.get("images")),
    )


def _parse_episode(item: dict) -> tuple[str, tuple[str, ...], str, str | None]:
    """EpisodeObject → 트랙과 같은 모양으로 변환.

    에피소드는 artists가 없으므로 쇼(프로그램) 이름을 아티스트 자리에 넣는다.
    """
    show = item.get("show") or {}
    publisher = show.get("name", "")
    # 에피소드 자체 이미지가 없으면 쇼 이미지를 쓴다.
    art = _largest_image(item.get("images")) or _largest_image(show.get("images"))
    return (
        item.get("name", ""),
        (publisher,) if publisher else (),
        show.get("name", ""),
        art,
    )


def _largest_image(images: list[dict] | None) -> str | None:
    """이미지 목록에서 가장 큰 것의 URL.

    Spotify는 보통 큰 것부터 주지만 순서를 보장하지 않으므로 직접 고른다.
    width가 null인 경우가 있어 0으로 취급한다.
    """
    if not images:
        return None
    best = max(images, key=lambda img: (img.get("width") or 0) * (img.get("height") or 0))
    return best.get("url")


def _parse_disallows(actions: dict | None) -> frozenset[str]:
    """actions.disallows에서 금지된 동작 집합을 뽑는다.

    Spotify는 `{"disallows": {"resuming": true}}` 형태로 준다.
    값이 true인 키만 '금지'다.
    """
    if not actions:
        return frozenset()
    disallows = actions.get("disallows") or {}
    return frozenset(key for key, value in disallows.items() if value)
