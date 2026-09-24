"""Spotify 재생 제어 (고수준 API).

사용하는 엔드포인트는 모두 2026년 현재 공식 문서 기준으로 확인했다.

    상태 조회   GET    /me/player                 (재생 없으면 204)
    기기 목록   GET    /me/player/devices
    재생        PUT    /me/player/play
    일시정지    PUT    /me/player/pause
    다음 곡     POST   /me/player/next
    이전 곡     POST   /me/player/previous
    위치 이동   PUT    /me/player/seek?position_ms=
    볼륨        PUT    /me/player/volume?volume_percent=
    셔플        PUT    /me/player/shuffle?state=
    반복        PUT    /me/player/repeat?state=
    좋아요 확인 GET    /me/library/contains?uris=    (2026-02 신규)
    좋아요 추가 PUT    /me/library?uris=             (2026-02 신규)
    좋아요 해제 DELETE /me/library?uris=             (2026-02 신규)

⚠️ 구버전 튜토리얼이 쓰는 PUT/DELETE /me/tracks, GET /me/tracks/contains 는
   2026년 2월 마이그레이션으로 제거되었다. 여기서는 사용하지 않는다.
"""

from __future__ import annotations

import logging

from app.core.errors import (
    DeckError,
    NoActiveDeviceError,
    RestrictedActionError,
    SpotifyApiError,
)
from app.spotify.client import SpotifyClient, join_uris, track_uri
from app.spotify.models import DeviceInfo, PlaybackState, RepeatMode

logger = logging.getLogger(__name__)


class SpotifyPlayer:
    """재생 상태 조회와 제어를 제공한다.

    모든 메서드는 실패 시 DeckError 계열만 던진다.
    UI는 예외를 잡아 `.display()` 를 보여주기만 하면 된다.
    """

    def __init__(self, client: SpotifyClient) -> None:
        self._client = client

    # -- 조회 ---------------------------------------------------------------

    def get_state(self, *, with_like: bool = True) -> PlaybackState:
        """현재 재생 상태를 가져온다.

        Args:
            with_like: True면 좋아요 여부까지 조회한다 (API 호출 1회 추가).

        Returns:
            PlaybackState. 재생 중이 아니면 `is_empty=True` 인 상태.
        """
        # additional_types=episode 를 붙여야 팟캐스트도 item으로 내려온다.
        # 빠뜨리면 팟캐스트 재생 중에 item이 null이 되어 '재생 없음'으로 보인다.
        data = self._client.get("/me/player", additional_types="track,episode")
        state = PlaybackState.from_api(data)

        if with_like and state.has_track and state.content_type == "track":
            state.is_liked = self.is_saved(state.track_id)

        return state

    def get_devices(self) -> list[DeviceInfo]:
        """사용 가능한 Spotify Connect 기기 목록."""
        data = self._client.get("/me/player/devices") or {}
        return [DeviceInfo.from_api(d) for d in data.get("devices", [])]

    # -- 재생 제어 -----------------------------------------------------------

    def play(self) -> None:
        """재생 시작/재개."""
        self._client.put("/me/player/play")

    def pause(self) -> None:
        """일시정지."""
        self._client.put("/me/player/pause")

    def toggle_play_pause(self, state: PlaybackState | None = None) -> None:
        """재생/일시정지 토글.

        Args:
            state: 이미 알고 있는 상태. 주면 API 호출을 1회 아낀다.

        상태가 낡았을 때의 자동 보정:
            폴링 주기(1초) 안에 버튼을 두 번 누르면 아직 갱신되지 않은 상태를
            보고 판단하게 된다. 이미 멈춘 것을 또 멈추려 하면 Spotify가
            403 "Player command failed: Restriction violated" 로 거부한다.
            사용자 입장에서는 "그냥 토글이 안 되는" 버그로 보이므로,
            거부당하면 반대 명령을 한 번 더 보내 의도대로 동작시킨다.
        """
        if state is None:
            state = self.get_state(with_like=False)

        if state.is_empty and not state.is_ad:
            raise NoActiveDeviceError(
                "재생할 음악이 선택되지 않았습니다.",
                hint=(
                    "Spotify 앱에서 곡을 하나 재생한 뒤 다시 시도해 주세요.\n"
                    "그 뒤부터는 이 덱에서 제어할 수 있습니다."
                ),
            )

        first, second = (self.pause, self.play) if state.is_playing else (self.play, self.pause)

        try:
            first()
        except RestrictedActionError:
            logger.debug("재생 상태가 낡아 거부됨 - 반대 명령으로 재시도합니다.")
            second()

    def next_track(self, state: PlaybackState | None = None) -> None:
        """다음 곡."""
        if state is not None and not state.can("skipping_next"):
            raise RestrictedActionError(
                "지금은 다음 곡으로 넘어갈 수 없습니다.",
                hint="광고 재생 중에는 건너뛸 수 없습니다." if state.is_ad else None,
            )
        self._client.post("/me/player/next")

    def previous_track(self, state: PlaybackState | None = None) -> None:
        """이전 곡.

        Spotify의 동작: 재생 3초 이후에는 '곡 처음으로', 3초 이내면 '이전 곡'.
        이는 Spotify 서버가 결정하므로 여기서 따로 처리하지 않는다.
        """
        if state is not None and not state.can("skipping_prev"):
            raise RestrictedActionError(
                "지금은 이전 곡으로 갈 수 없습니다.",
                hint="광고 재생 중에는 건너뛸 수 없습니다." if state.is_ad else None,
            )
        self._client.post("/me/player/previous")

    # -- 위치 이동 -----------------------------------------------------------

    def seek(self, position_ms: int, state: PlaybackState | None = None) -> None:
        """재생 위치를 절대값으로 이동한다.

        Args:
            position_ms: 이동할 위치(밀리초). 곡 길이를 넘으면 다음 곡으로 넘어간다.
        """
        if state is not None and not state.can("seeking"):
            raise RestrictedActionError("지금은 재생 위치를 바꿀 수 없습니다.")

        position_ms = max(0, int(position_ms))
        self._client.put("/me/player/seek", params={"position_ms": position_ms})

    def seek_relative(self, delta_ms: int, state: PlaybackState) -> None:
        """현재 위치에서 상대 이동한다.

        보간된 위치를 기준으로 계산해야 실제 들리는 지점과 어긋나지 않는다.
        """
        if state.duration_ms <= 0:
            raise RestrictedActionError("재생 중인 곡이 없습니다.")
        target = state.estimated_progress_ms() + delta_ms
        # 끝까지 밀면 의도치 않게 다음 곡으로 넘어가므로 1초 앞에서 멈춘다.
        target = max(0, min(target, state.duration_ms - 1000))
        self.seek(target, state)

    # -- 볼륨 ---------------------------------------------------------------

    def set_volume(self, percent: int, state: PlaybackState | None = None) -> int:
        """볼륨을 절대값으로 설정한다.

        Returns:
            실제로 설정된 값 (0~100으로 보정된 결과).
        """
        percent = max(0, min(100, int(percent)))

        if state is not None and state.device.id and not state.device.supports_volume:
            raise RestrictedActionError(
                f"'{state.device.name}' 기기는 볼륨 조절을 지원하지 않습니다.",
                hint="기기 자체의 볼륨 버튼을 사용해 주세요.",
            )

        self._client.put("/me/player/volume", params={"volume_percent": percent})
        return percent

    def adjust_volume(self, delta: int, state: PlaybackState) -> int:
        """현재 볼륨에서 상대 조절한다.

        Returns:
            새로 설정된 볼륨.
        """
        if state.device.volume_percent is None:
            raise RestrictedActionError(
                "현재 기기의 볼륨을 읽을 수 없습니다.",
                hint="기기 자체의 볼륨 버튼을 사용해 주세요.",
            )
        return self.set_volume(state.device.volume_percent + delta, state)

    # -- 모드 ---------------------------------------------------------------

    def set_shuffle(self, enabled: bool) -> None:
        # Spotify는 쿼리 문자열의 'true'/'false' 소문자를 기대한다.
        self._client.put("/me/player/shuffle", params={"state": str(bool(enabled)).lower()})

    def toggle_shuffle(self, state: PlaybackState) -> bool:
        """셔플 토글.

        Returns:
            새 셔플 상태.
        """
        if not state.can("toggling_shuffle"):
            raise RestrictedActionError("지금은 셔플을 바꿀 수 없습니다.")
        new_value = not state.shuffle
        self.set_shuffle(new_value)
        return new_value

    def set_repeat(self, mode: RepeatMode) -> None:
        self._client.put("/me/player/repeat", params={"state": mode.value})

    def toggle_repeat(self, state: PlaybackState) -> RepeatMode:
        """반복 모드를 off -> context -> track -> off 로 순환한다.

        Returns:
            새 반복 모드.
        """
        new_mode = state.repeat.next_mode()

        # 컨텍스트(플레이리스트/앨범) 없이 단일 곡을 재생 중이면
        # 'context' 반복이 거부될 수 있다. 그럴 땐 track으로 건너뛴다.
        if new_mode is RepeatMode.CONTEXT and not state.can("toggling_repeat_context"):
            new_mode = RepeatMode.TRACK
        if new_mode is RepeatMode.TRACK and not state.can("toggling_repeat_track"):
            new_mode = RepeatMode.OFF

        self.set_repeat(new_mode)
        return new_mode

    # -- 좋아요 (2026-02 신규 /me/library 엔드포인트) -------------------------

    def is_saved(self, track_id: str | None) -> bool | None:
        """현재 곡이 보관함에 저장되어 있는지 확인한다.

        GET /me/library/contains?uris=spotify%3Atrack%3A...
        응답은 boolean 배열: [true]

        Returns:
            True/False. 확인에 실패하면 None (UI는 '알 수 없음'으로 표시).
        """
        if not track_id:
            return None
        try:
            result = self._client.get(
                "/me/library/contains", uris=join_uris([track_uri(track_id)])
            )
        except DeckError as exc:
            # 좋아요 표시는 부가 정보다. 실패해도 재생 정보는 계속 보여야 하므로
            # 예외를 위로 던지지 않는다.
            logger.debug("좋아요 상태 확인 실패: %s", exc)
            return None

        if isinstance(result, list) and result:
            return bool(result[0])
        return None

    def save_track(self, track_id: str) -> None:
        """보관함에 추가한다.  PUT /me/library?uris=..."""
        self._library_write("PUT", track_id)

    def remove_track(self, track_id: str) -> None:
        """보관함에서 제거한다.  DELETE /me/library?uris=..."""
        self._library_write("DELETE", track_id)

    def _library_write(self, method: str, track_id: str) -> None:
        """라이브러리 추가/삭제 공통 처리.

        `uris`는 쿼리 파라미터로 보낸다. 실제 API 응답으로 확인한 방식이다.
        (마이그레이션 가이드에는 JSON 본문 예시도 나오지만,
         공식 레퍼런스와 실제 동작 모두 쿼리 파라미터를 쓴다)

        URI는 인코딩하지 않은 원본을 넘긴다 — join_uris 주석 참고.
        """
        self._client.request(
            method, "/me/library", params={"uris": join_uris([track_uri(track_id)])}
        )

    def toggle_like(self, state: PlaybackState) -> bool:
        """현재 곡의 좋아요를 토글한다.

        Returns:
            새 좋아요 상태 (True = 저장됨).
        """
        if not state.has_track or not state.track_id:
            raise RestrictedActionError(
                "좋아요를 표시할 곡이 없습니다.",
                hint="재생 중인 곡이 있어야 합니다.",
            )

        if state.content_type != "track":
            raise RestrictedActionError(
                "이 콘텐츠는 좋아요를 지원하지 않습니다.",
                hint="팟캐스트 에피소드나 광고는 보관함에 저장할 수 없습니다.",
            )

        # 상태를 모르면 먼저 확인한다.
        currently = state.is_liked
        if currently is None:
            currently = self.is_saved(state.track_id) or False

        if currently:
            self.remove_track(state.track_id)
            return False

        self.save_track(state.track_id)
        return True

    # -- 기기 --------------------------------------------------------------

    def transfer_to(self, device_id: str, *, play: bool = True) -> None:
        """재생을 다른 기기로 넘긴다.

        활성 기기가 없을 때 사용 가능한 기기로 재생을 옮기는 용도.
        """
        self._client.put("/me/player", json={"device_ids": [device_id], "play": play})

    def activate_any_device(self) -> DeviceInfo | None:
        """활성 기기가 없을 때 사용 가능한 기기 하나를 활성화한다.

        '활성 기기 없음' 오류에서 자동 복구를 시도할 때 쓴다.

        Returns:
            활성화한 기기. 쓸 수 있는 기기가 없으면 None.
        """
        devices = self.get_devices()
        if not devices:
            return None

        # 이미 활성인 기기가 있으면 그대로 쓴다.
        for device in devices:
            if device.is_active and not device.is_restricted:
                return device

        for device in devices:
            if device.id and not device.is_restricted:
                # play=False: 사용자가 누르지도 않았는데 음악이 튀어나오지 않게 한다.
                self.transfer_to(device.id, play=False)
                logger.info("'%s' 기기를 활성화했습니다.", device.name)
                return device

        return None
