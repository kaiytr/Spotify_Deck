"""백그라운드 작업 스레드.

UI 스레드에서 네트워크 요청을 하면 창이 멈춘다(응답 없음).
그래서 두 가지를 워커로 분리한다.

    PollWorker    일정 주기로 재생 정보를 가져와 UI에 전달   (요구사항 #12)
    ActionRunner  버튼/키 입력 한 건을 처리                 (블로킹 API 호출)

둘 다 Qt 시그널로 결과를 UI 스레드에 넘기므로 스레드 안전하다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from app.core.actions import ActionEvent
from app.core.deck_controller import ActionResult, DeckController
from app.core.errors import DeckError, NetworkError, RateLimitError
from app.spotify.models import PlaybackState
from app.spotify.player import SpotifyPlayer

logger = logging.getLogger(__name__)

#: 연속 실패 시 폴링 간격을 늘리는 배수와 상한(ms).
#: 인터넷이 끊겼을 때 1초마다 재시도하며 로그를 도배하는 것을 막는다.
BACKOFF_FACTOR = 2
MAX_BACKOFF_MS = 30_000

#: 좋아요 상태는 매번 확인할 필요가 없다 (곡이 바뀔 때만).
#: API 호출을 절반으로 줄여 Rate Limit 여유를 확보한다.


class PollWorker(QThread):
    """재생 정보를 주기적으로 가져오는 스레드.

    Signals:
        state_ready(PlaybackState): 새 재생 상태.
        error(DeckError):           조회 실패 (일시적일 수 있음).
        recovered():                실패 후 다시 성공했을 때.
    """

    state_ready = Signal(object)
    error = Signal(object)
    recovered = Signal()

    def __init__(self, player: SpotifyPlayer, interval_ms: int = 1000) -> None:
        super().__init__()
        self._player = player
        self._base_interval = interval_ms
        self._interval = interval_ms
        self._running = True
        self._failing = False
        #: 좋아요를 다시 확인해야 하는 곡 ID 추적
        self._last_track_id: str | None = None
        self._last_liked: bool | None = None
        #: 다음 순회에서 즉시 갱신하도록 하는 플래그
        self._force_now = False

    # -- 제어 ---------------------------------------------------------------

    def stop(self) -> None:
        """스레드를 정지시킨다. 호출 후 wait()로 종료를 기다린다."""
        self._running = False

    def request_immediate(self) -> None:
        """다음 대기를 건너뛰고 지금 바로 갱신한다.

        버튼을 누른 직후 호출하면 화면이 즉시 반응한다.
        """
        self._force_now = True

    def invalidate_like(self) -> None:
        """좋아요 캐시를 버린다. 좋아요를 토글한 직후 호출한다."""
        self._last_liked = None

    # -- 실행 ---------------------------------------------------------------

    def run(self) -> None:  # noqa: C901 - 폴링 루프는 분기가 많은 게 자연스럽다
        logger.debug("폴링 시작 (주기 %dms)", self._base_interval)

        while self._running:
            try:
                state = self._fetch()
            except DeckError as exc:
                self._on_failure(exc)
            except Exception as exc:  # noqa: BLE001 - 스레드가 죽으면 앱이 멎는다
                logger.exception("폴링 중 예기치 못한 오류")
                self._on_failure(
                    DeckError(
                        "재생 정보를 가져오지 못했습니다.",
                        hint="잠시 후 자동으로 다시 시도합니다.",
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
            else:
                if self._failing:
                    self._failing = False
                    self._interval = self._base_interval
                    self.recovered.emit()
                self.state_ready.emit(state)

            self._sleep_interval()

        logger.debug("폴링 종료")

    def _fetch(self) -> PlaybackState:
        """재생 상태를 가져온다. 좋아요는 곡이 바뀐 경우에만 조회한다."""
        state = self._player.get_state(with_like=False)

        if state.has_track and state.content_type == "track":
            if state.track_id != self._last_track_id or self._last_liked is None:
                self._last_liked = self._player.is_saved(state.track_id)
                self._last_track_id = state.track_id
            state.is_liked = self._last_liked
        else:
            self._last_track_id = None
            self._last_liked = None

        return state

    def _on_failure(self, exc: DeckError) -> None:
        """실패 시 백오프를 적용하고 UI에 알린다."""
        self._failing = True

        # Rate Limit은 서버가 알려준 대기 시간을 그대로 따른다.
        if isinstance(exc, RateLimitError) and exc.retry_after:
            self._interval = max(self._base_interval, exc.retry_after * 1000)
        elif isinstance(exc, NetworkError):
            self._interval = min(self._interval * BACKOFF_FACTOR, MAX_BACKOFF_MS)
        else:
            self._interval = min(self._interval * BACKOFF_FACTOR, MAX_BACKOFF_MS)

        logger.debug("폴링 실패 - 다음 시도까지 %dms: %s", self._interval, exc.user_message)
        self.error.emit(exc)

    def _sleep_interval(self) -> None:
        """중단 요청과 즉시 갱신 요청에 빠르게 반응하도록 잘게 나눠 잔다."""
        slept = 0
        step = 50
        while slept < self._interval and self._running:
            if self._force_now:
                self._force_now = False
                return
            QThread.msleep(step)
            slept += step


class _ActionSignals(QObject):
    finished = Signal(object)  # ActionResult


class ActionRunner(QRunnable):
    """액션 한 건을 워커 스레드에서 처리한다.

    QThreadPool에 넣어 실행하며, 결과는 finished 시그널로 UI에 돌아온다.
    """

    def __init__(self, controller: DeckController, event: ActionEvent) -> None:
        super().__init__()
        self._controller = controller
        self._event = event
        self.signals = _ActionSignals()

    def run(self) -> None:
        result = self._controller.handle(self._event)
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            # 액션 처리 도중 창이 닫힌 경우. 결과를 받을 곳이 없으니 조용히 버린다.
            logger.debug("수신자가 이미 파괴되어 액션 결과를 버립니다.")


__all__ = ["PollWorker", "ActionRunner", "ActionResult"]
