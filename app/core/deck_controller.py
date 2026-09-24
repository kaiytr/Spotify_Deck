"""액션 디스패처 — 입력 계층과 Spotify 계층을 잇는 유일한 지점.

    [모든 입력 장치] ──ActionEvent──> DeckController ──> SpotifyPlayer

입력 장치(키보드/GPIO/엔코더/UI 버튼)는 여기까지만 알면 된다.
Spotify API를 직접 호출하는 입력 장치는 존재하지 않는다.

덕분에 GPIO 컨트롤러를 추가할 때 작성할 코드는
"버튼 3번이 눌리면 DeckAction.NEXT_TRACK을 emit한다" 뿐이다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from app.core.actions import (
    DEFAULT_SEEK_DELTA_MS,
    DEFAULT_VOLUME_STEP,
    ActionEvent,
    DeckAction,
)
from app.core.errors import DeckError, NoActiveDeviceError
from app.spotify.models import PlaybackState
from app.spotify.player import SpotifyPlayer

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """액션 처리 결과.

    Attributes:
        ok:       성공 여부.
        message:  사용자에게 보여줄 짧은 피드백. 예) "셔플 켜짐"
        error:    실패한 경우의 예외. UI는 error.display()를 보여준다.
        should_refresh: True면 즉시 재생 정보를 다시 읽어야 한다.
    """

    ok: bool
    message: str = ""
    error: DeckError | None = None
    should_refresh: bool = True

    @classmethod
    def success(cls, message: str = "", *, refresh: bool = True) -> "ActionResult":
        return cls(ok=True, message=message, should_refresh=refresh)

    @classmethod
    def failure(cls, error: DeckError) -> "ActionResult":
        return cls(ok=False, error=error, message=error.user_message, should_refresh=False)


#: 현재 재생 상태를 돌려주는 함수. UI의 폴링 결과를 읽어온다.
StateProvider = Callable[[], PlaybackState]


class DeckController:
    """DeckAction을 받아 SpotifyPlayer를 호출한다.

    모든 메서드는 예외를 던지지 않고 ActionResult로 결과를 알린다.
    입력 장치가 예외 처리를 신경 쓰지 않아도 되게 하기 위함이다.
    """

    def __init__(
        self,
        player: SpotifyPlayer,
        state_provider: StateProvider,
        *,
        volume_step: int = DEFAULT_VOLUME_STEP,
        seek_delta_ms: int = DEFAULT_SEEK_DELTA_MS,
        auto_activate_device: bool = True,
    ) -> None:
        """
        Args:
            player: Spotify 제어 객체.
            state_provider: 최신 PlaybackState를 반환하는 함수.
            volume_step: VOLUME_UP/DOWN의 기본 증감폭.
            seek_delta_ms: SEEK_FORWARD/BACKWARD의 기본 이동폭.
            auto_activate_device: True면 '활성 기기 없음' 오류 시
                사용 가능한 기기를 자동으로 깨워 한 번 재시도한다.
        """
        self._player = player
        self._state = state_provider
        self._volume_step = volume_step
        self._seek_delta_ms = seek_delta_ms
        self._auto_activate = auto_activate_device

        # 액션 -> 처리 함수. 새 액션을 추가하려면 여기에 한 줄 등록하면 된다.
        self._handlers: dict[DeckAction, Callable[[ActionEvent, PlaybackState], ActionResult]] = {
            DeckAction.PLAY_PAUSE: self._play_pause,
            DeckAction.PLAY: self._play,
            DeckAction.PAUSE: self._pause,
            DeckAction.NEXT_TRACK: self._next,
            DeckAction.PREVIOUS_TRACK: self._previous,
            DeckAction.VOLUME_UP: self._volume_up,
            DeckAction.VOLUME_DOWN: self._volume_down,
            DeckAction.VOLUME_SET: self._volume_set,
            DeckAction.SEEK_SET: self._seek_set,
            DeckAction.SEEK_FORWARD: self._seek_forward,
            DeckAction.SEEK_BACKWARD: self._seek_backward,
            DeckAction.TOGGLE_SHUFFLE: self._toggle_shuffle,
            DeckAction.TOGGLE_REPEAT: self._toggle_repeat,
            DeckAction.TOGGLE_LIKE: self._toggle_like,
            DeckAction.REFRESH: self._refresh,
        }

    # -- 진입점 -------------------------------------------------------------

    def handle(self, event: ActionEvent) -> ActionResult:
        """액션 하나를 처리한다. 예외를 던지지 않는다.

        블로킹 호출이므로 UI 스레드가 아닌 워커 스레드에서 실행해야 한다.
        """
        handler = self._handlers.get(event.action)
        if handler is None:
            # QUIT 등은 UI가 직접 처리하므로 여기 오면 안 된다.
            logger.debug("처리기가 없는 액션: %s", event.action)
            return ActionResult(ok=True, should_refresh=False)

        state = self._state()
        logger.debug("액션 처리: %s", event)

        try:
            return handler(event, state)
        except NoActiveDeviceError as exc:
            return self._retry_with_device(handler, event, exc)
        except DeckError as exc:
            logger.info("액션 실패 [%s]: %s", event.action.value, exc.detail or exc.user_message)
            return ActionResult.failure(exc)
        except Exception as exc:  # noqa: BLE001 - 예상 못 한 오류도 UI를 죽이면 안 된다
            logger.exception("액션 처리 중 예기치 못한 오류: %s", event.action)
            return ActionResult.failure(
                DeckError(
                    "예기치 못한 오류가 발생했습니다.",
                    hint="잠시 후 다시 시도해 주세요.",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )

    def _retry_with_device(
        self, handler, event: ActionEvent, original: NoActiveDeviceError
    ) -> ActionResult:
        """'활성 기기 없음'일 때 기기를 깨우고 한 번만 재시도한다.

        Spotify 앱이 켜져 있지만 유휴 상태면 API가 기기를 '비활성'으로 본다.
        이때 사용자가 직접 폰에서 곡을 재생해야 하는 번거로움을 줄여 준다.
        """
        if not self._auto_activate:
            return ActionResult.failure(original)

        try:
            device = self._player.activate_any_device()
        except DeckError:
            return ActionResult.failure(original)

        if device is None:
            # 켜져 있는 Spotify 앱이 아예 없다. 원래 안내가 정확하다.
            return ActionResult.failure(original)

        logger.info("'%s' 기기를 활성화하고 재시도합니다.", device.name)
        try:
            # 기기가 바뀌었으니 상태를 다시 읽어 온다.
            state = self._player.get_state(with_like=False)
            return handler(event, state)
        except DeckError as exc:
            return ActionResult.failure(exc)

    # -- 재생 제어 -----------------------------------------------------------

    def _play_pause(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        self._player.toggle_play_pause(state)
        return ActionResult.success("일시정지" if state.is_playing else "재생")

    def _play(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        self._player.play()
        return ActionResult.success("재생")

    def _pause(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        self._player.pause()
        return ActionResult.success("일시정지")

    def _next(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        self._player.next_track(state)
        return ActionResult.success("다음 곡")

    def _previous(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        self._player.previous_track(state)
        return ActionResult.success("이전 곡")

    # -- 볼륨 ---------------------------------------------------------------

    def _volume_up(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        step = int(event.get("step", self._volume_step))
        new_volume = self._player.adjust_volume(step, state)
        return ActionResult.success(f"볼륨 {new_volume}%")

    def _volume_down(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        step = int(event.get("step", self._volume_step))
        new_volume = self._player.adjust_volume(-step, state)
        return ActionResult.success(f"볼륨 {new_volume}%")

    def _volume_set(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        value = int(event.get("value", 0))
        new_volume = self._player.set_volume(value, state)
        return ActionResult.success(f"볼륨 {new_volume}%")

    # -- 위치 이동 -----------------------------------------------------------

    def _seek_set(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        position = int(event.get("position_ms", 0))
        self._player.seek(position, state)
        return ActionResult.success()

    def _seek_forward(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        delta = int(event.get("delta_ms", self._seek_delta_ms))
        self._player.seek_relative(delta, state)
        return ActionResult.success(f"{delta // 1000}초 앞으로")

    def _seek_backward(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        delta = int(event.get("delta_ms", self._seek_delta_ms))
        self._player.seek_relative(-delta, state)
        return ActionResult.success(f"{delta // 1000}초 뒤로")

    # -- 모드 ---------------------------------------------------------------

    def _toggle_shuffle(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        enabled = self._player.toggle_shuffle(state)
        return ActionResult.success("셔플 켜짐" if enabled else "셔플 꺼짐")

    def _toggle_repeat(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        mode = self._player.toggle_repeat(state)
        return ActionResult.success(mode.label)

    def _toggle_like(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        liked = self._player.toggle_like(state)
        return ActionResult.success("보관함에 추가" if liked else "보관함에서 제거")

    # -- 기타 ---------------------------------------------------------------

    def _refresh(self, event: ActionEvent, state: PlaybackState) -> ActionResult:
        return ActionResult.success(refresh=True)
