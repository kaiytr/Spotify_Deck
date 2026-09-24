"""메인 윈도우.

레이아웃 전략 — "16:9 데스크톱 최적화 + 3.5~5인치 LCD 축소 대응":

    넓을 때 (16:9 데스크톱, 800x480 LCD)      좁을 때 (세로 화면)
    ┌────────────┬──────────────────┐        ┌──────────────┐
    │            │  Song Title      │        │  [앨범아트]   │
    │  [앨범아트] │  Artist / Album  │        ├──────────────┤
    │            │  ──────●───────  │        │  Song Title  │
    │            │  [◀] [▶] [▶▶]   │        │  ──●───────  │
    │            │  [S] [R] [♥] 🔊  │        │  [◀][▶][▶▶] │
    └────────────┴──────────────────┘        └──────────────┘

창 너비가 임계값을 넘나들 때 자동으로 전환된다.
RK3399에 5인치 800x480 LCD를 붙이면 가로 배치가 그대로 쓰인다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.config.keymap import KEY_HINTS
from app.core.actions import ActionEvent, DeckAction
from app.core.deck_controller import ActionResult, DeckController
from app.core.errors import DeckError, NothingPlayingError
from app.spotify.models import PlaybackState, RepeatMode, format_duration
from app.ui.icons import Icon
from app.ui.theme import Colors, build_stylesheet
from app.ui.widgets.album_art import AlbumArtWidget
from app.ui.widgets.buttons import IconButton, PlayButton
from app.ui.widgets.slider import ProgressSlider
from app.ui.widgets.wave_bar import WaveBarWidget
from app.ui.worker import ActionRunner, PollWorker

logger = logging.getLogger(__name__)

#: 이 너비 미만이면 세로 배치로 전환한다.
NARROW_BREAKPOINT = 700

#: 액션 피드백 메시지 표시 시간(ms)
TOAST_DURATION_MS = 2200


class DeckWindow(QMainWindow):
    """Spotify Deck 메인 화면."""

    action_requested = Signal(object)  # ActionEvent

    def __init__(
        self,
        controller: DeckController,
        poller: PollWorker,
        *,
        wave_source=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._poller = poller
        self._pool = QThreadPool.globalInstance()

        # 웨이브 바. wave_source가 None이면(DECK_WAVE_MODE=off) 표시하지 않는다.
        self._wave = WaveBarWidget(wave_source, height=68) if wave_source is not None else None

        self._state = PlaybackState.empty()
        self._is_narrow = False
        self._connected = False
        #: 실행 중인 ActionRunner의 강한 참조 (GC로 시그널이 끊기는 것을 막는다)
        self._running_actions: set[ActionRunner] = set()

        self.setWindowTitle("Spotify Deck")
        self.setMinimumSize(420, 320)
        self.resize(1024, 576)  # 16:9
        self.setStyleSheet(build_stylesheet())

        self._build_ui()
        self._connect_signals()

        # 진행률을 60fps로 부드럽게 갱신 (서버 폴링과 별개)
        self._tick = QTimer(self)
        self._tick.setInterval(100)
        self._tick.timeout.connect(self._update_progress_display)
        self._tick.start()

        if self._wave is not None:
            self._wave.start()

        self._apply_state(self._state)

    # -- UI 구성 -------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(16)

        root.addWidget(self._build_header())

        # 앨범 아트 + 정보/컨트롤을 담는 가변 영역
        self._body = QHBoxLayout()
        self._body.setSpacing(32)

        self._album_art = AlbumArtWidget(radius=14)
        self._body.addWidget(self._album_art, 5)

        self._panel = self._build_panel()
        self._body.addWidget(self._panel, 6)

        root.addLayout(self._body, 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        """상단: 연결 상태 + 기기 이름."""
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 13px;")

        self._status_label = QLabel("연결 중...")
        self._status_label.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 12px;")

        self._device_label = QLabel("")
        self._device_label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 12px;")

        layout.addWidget(self._status_dot)
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        layout.addWidget(self._device_label)
        return header

    def _build_panel(self) -> QWidget:
        """오른쪽(또는 아래쪽): 곡 정보 + 진행률 + 컨트롤."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addStretch(1)

        # --- 곡 정보 ---
        self._title_label = QLabel("재생 중인 음악이 없습니다")
        title_font = QFont()
        title_font.setPointSize(26)
        title_font.setWeight(QFont.Weight.Bold)
        self._title_label.setFont(title_font)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(f"color: {Colors.TEXT};")

        self._artist_label = QLabel("")
        artist_font = QFont()
        artist_font.setPointSize(14)
        self._artist_label.setFont(artist_font)
        self._artist_label.setWordWrap(True)
        self._artist_label.setStyleSheet(f"color: {Colors.TEXT_DIM};")

        self._album_label = QLabel("")
        self._album_label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 12px;")
        self._album_label.setWordWrap(True)

        layout.addWidget(self._title_label)
        layout.addSpacing(6)
        layout.addWidget(self._artist_label)
        layout.addSpacing(3)
        layout.addWidget(self._album_label)
        layout.addSpacing(18)

        # --- 웨이브 바 (스펙트럼) ---
        # 곡 정보와 진행 바 사이에 둔다. 재생 중임을 한눈에 보여 주는 자리다.
        if self._wave is not None:
            layout.addWidget(self._wave)
            layout.addSpacing(14)
        else:
            layout.addSpacing(8)

        # --- 진행률 ---
        self._seek = ProgressSlider(height=22, track_height=5, handle_radius=7)
        layout.addWidget(self._seek)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 2, 0, 0)
        self._elapsed_label = QLabel("--:--")
        self._duration_label = QLabel("--:--")
        for lbl in (self._elapsed_label, self._duration_label):
            lbl.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 11px;")
        time_row.addWidget(self._elapsed_label)
        time_row.addStretch(1)
        time_row.addWidget(self._duration_label)
        layout.addLayout(time_row)
        layout.addSpacing(18)

        # --- 주 컨트롤 ---
        self._prev_btn = IconButton(Icon.PREVIOUS, size=44, tooltip="이전 곡  (←)")
        self._play_btn = PlayButton(size=62)
        self._next_btn = IconButton(Icon.NEXT, size=44, tooltip="다음 곡  (→)")

        main_row = QHBoxLayout()
        main_row.setSpacing(18)
        main_row.addStretch(1)
        main_row.addWidget(self._prev_btn)
        main_row.addWidget(self._play_btn)
        main_row.addWidget(self._next_btn)
        main_row.addStretch(1)
        layout.addLayout(main_row)
        layout.addSpacing(16)

        # --- 보조 컨트롤 + 볼륨 ---
        self._shuffle_btn = IconButton(Icon.SHUFFLE, size=36, tooltip="셔플  (S)")
        self._repeat_btn = IconButton(Icon.REPEAT, size=36, tooltip="반복  (R)")
        self._like_btn = IconButton(
            Icon.HEART, size=36, active_color=Colors.LIKE, tooltip="좋아요  (L)"
        )
        self._volume_icon = IconButton(
            Icon.VOLUME, size=30, icon_ratio=0.62, tooltip="음소거 / 해제"
        )

        self._volume = ProgressSlider(height=18, track_height=4, handle_radius=6)
        self._volume.set_range(100)
        self._volume.setMaximumWidth(150)
        self._volume.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        sub_row.addWidget(self._shuffle_btn)
        sub_row.addWidget(self._repeat_btn)
        sub_row.addWidget(self._like_btn)
        sub_row.addStretch(1)
        sub_row.addWidget(self._volume_icon)
        sub_row.addWidget(self._volume)
        layout.addLayout(sub_row)

        layout.addStretch(1)
        return panel

    def _build_footer(self) -> QWidget:
        """하단: 상태 배너(오류/안내) + 단축키 힌트."""
        footer = QFrame()
        footer.setObjectName("StatusBanner")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(16, 10, 12, 10)
        layout.setSpacing(12)

        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 12px;")

        self._action_button = QPushButton("")
        self._action_button.setObjectName("TextButton")
        self._action_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_button.hide()

        layout.addWidget(self._message_label, 1)
        layout.addWidget(self._action_button)

        self._footer = footer
        self._set_hint_message()
        return footer

    def _set_hint_message(self) -> None:
        """평소에는 단축키 안내를 보여 준다."""
        hints = "   ".join(f"{key} {label}" for key, label in KEY_HINTS[:5])
        self._message_label.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        self._message_label.setText(hints)
        self._action_button.hide()

    # -- 시그널 연결 ---------------------------------------------------------

    def _connect_signals(self) -> None:
        self._play_btn.clicked.connect(lambda: self._dispatch(DeckAction.PLAY_PAUSE))
        self._prev_btn.clicked.connect(lambda: self._dispatch(DeckAction.PREVIOUS_TRACK))
        self._next_btn.clicked.connect(lambda: self._dispatch(DeckAction.NEXT_TRACK))
        self._shuffle_btn.clicked.connect(lambda: self._dispatch(DeckAction.TOGGLE_SHUFFLE))
        self._repeat_btn.clicked.connect(lambda: self._dispatch(DeckAction.TOGGLE_REPEAT))
        self._like_btn.clicked.connect(lambda: self._dispatch(DeckAction.TOGGLE_LIKE))
        self._volume_icon.clicked.connect(self._toggle_mute)

        self._seek.seek_requested.connect(
            lambda ms: self._dispatch(DeckAction.SEEK_SET, position_ms=ms)
        )
        self._seek.value_preview.connect(
            lambda ms: self._elapsed_label.setText(format_duration(ms))
        )
        self._volume.seek_requested.connect(
            lambda v: self._dispatch(DeckAction.VOLUME_SET, value=v)
        )

        self._poller.state_ready.connect(self._apply_state)
        self._poller.error.connect(self._show_error)
        self._poller.recovered.connect(self._on_recovered)

    # -- 액션 전달 -----------------------------------------------------------

    def _dispatch(self, action: DeckAction, **payload) -> None:
        """UI 버튼에서 발생한 액션을 처리한다."""
        self.handle_action(ActionEvent(action=action, payload=payload, source="ui"))

    def handle_action(self, event: ActionEvent) -> None:
        """입력 장치(키보드/GPIO)와 UI 버튼 모두가 거쳐 가는 단일 진입점.

        블로킹 API 호출을 워커 스레드로 넘겨 UI가 멈추지 않게 한다.
        """
        if event.action is DeckAction.QUIT:
            self.close()
            return

        if event.action is DeckAction.REFRESH:
            self._poller.request_immediate()
            self._show_toast("새로고침")
            return

        # 좋아요는 캐시를 쓰므로 토글 후 강제로 다시 읽게 한다.
        if event.action is DeckAction.TOGGLE_LIKE:
            self._poller.invalidate_like()

        runner = ActionRunner(self._controller, event)
        # 앨범 아트 로더와 같은 이유로 강한 참조를 유지한다 (GC 방지).
        self._running_actions.add(runner)
        runner.signals.finished.connect(self._on_action_done)
        runner.signals.finished.connect(lambda *_: self._running_actions.discard(runner))
        self._pool.start(runner)

    def _on_action_done(self, result: ActionResult) -> None:
        if result.ok:
            if result.message:
                self._show_toast(result.message)
            if result.should_refresh:
                # 서버에 반영될 약간의 시간을 준 뒤 갱신한다.
                QTimer.singleShot(180, self._poller.request_immediate)
        elif result.error is not None:
            self._show_error(result.error)

    def _toggle_mute(self) -> None:
        """볼륨 0 <-> 이전 값 토글."""
        current = self._state.volume
        if current > 0:
            self._muted_volume = current
            self._dispatch(DeckAction.VOLUME_SET, value=0)
        else:
            self._dispatch(DeckAction.VOLUME_SET, value=getattr(self, "_muted_volume", 50))

    # -- 상태 반영 -----------------------------------------------------------

    def _apply_state(self, state: PlaybackState) -> None:
        """폴링 결과를 화면에 반영한다."""
        track_changed = not state.is_same_track(self._state)
        self._state = state

        self._set_connected(True)

        # --- 곡 정보 ---
        if state.is_empty:
            self._title_label.setText("재생 중인 음악이 없습니다")
            self._artist_label.setText("Spotify에서 곡을 재생하면 여기에 표시됩니다")
            self._album_label.setText("")
            self._album_art.clear()
        else:
            self._title_label.setText(state.title or "-")
            self._artist_label.setText(state.artist_text or "-")
            self._album_label.setText(state.album or "")
            self._album_art.set_url(state.album_art_url)

        # --- 진행률 ---
        self._seek.set_range(state.duration_ms)
        if track_changed:
            # 곡이 바뀌면 드래그 중이어도 값을 강제로 맞춘다.
            self._seek.set_value(state.progress_ms, force=True)
        self._duration_label.setText(
            format_duration(state.duration_ms) if state.duration_ms else "--:--"
        )

        # --- 웨이브 바 ---
        if self._wave is not None:
            # 시뮬레이션 모드에서 재생/정지를 반영하는 데 쓰인다.
            # 실시간 캡처 모드는 소리 자체로 판단하므로 영향이 없다.
            self._wave.set_playing(state.is_playing and not state.is_empty)

        # --- 버튼 상태 ---
        self._play_btn.set_playing(state.is_playing)
        self._shuffle_btn.set_active(state.shuffle)
        self._repeat_btn.set_active(state.repeat is not RepeatMode.OFF)
        self._repeat_btn.set_icon(
            Icon.REPEAT_ONE if state.repeat is RepeatMode.TRACK else Icon.REPEAT
        )
        self._repeat_btn.setToolTip(f"{state.repeat.label}  (R)")

        self._like_btn.set_active(bool(state.is_liked))
        self._like_btn.set_icon(Icon.HEART_FILLED if state.is_liked else Icon.HEART)
        self._like_btn.set_interactive(state.has_track and state.content_type == "track")

        # 현재 상황에서 불가능한 동작은 흐리게 표시한다.
        self._next_btn.set_interactive(state.can("skipping_next") and not state.is_empty)
        self._prev_btn.set_interactive(state.can("skipping_prev") and not state.is_empty)
        self._play_btn.set_interactive(not state.is_empty or state.is_ad)
        self._seek.setEnabled(state.can("seeking") and state.duration_ms > 0)

        # --- 볼륨 ---
        if state.device.volume_percent is not None:
            self._volume.set_value(state.device.volume_percent)
            self._volume_icon.set_icon(
                Icon.VOLUME_MUTE if state.device.volume_percent == 0 else Icon.VOLUME
            )
        self._volume.setEnabled(state.device.supports_volume)
        self._volume_icon.set_interactive(state.device.supports_volume)

        # --- 기기 ---
        if state.device.name:
            self._device_label.setText(f"{state.device.name} · {state.device.icon_hint}")
        else:
            self._device_label.setText("")

        self._update_progress_display()

    def _update_progress_display(self) -> None:
        """폴링 사이를 보간해 진행 바를 부드럽게 움직인다."""
        state = self._state
        if state.duration_ms <= 0:
            self._elapsed_label.setText("--:--")
            return
        if self._seek.is_dragging:
            return  # 드래그 중에는 사용자 손을 따라간다
        progress = state.estimated_progress_ms()
        self._seek.set_value(progress)
        self._elapsed_label.setText(format_duration(progress))

    # -- 상태 표시 -----------------------------------------------------------

    def _set_connected(self, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        if connected:
            self._status_dot.setStyleSheet(f"color: {Colors.ACCENT}; font-size: 13px;")
            self._status_label.setText("Spotify 연결됨")
            self._status_label.setStyleSheet(f"color: {Colors.TEXT_DIM}; font-size: 12px;")
        else:
            self._status_dot.setStyleSheet(f"color: {Colors.DANGER}; font-size: 13px;")
            self._status_label.setText("연결 끊김")
            self._status_label.setStyleSheet(f"color: {Colors.DANGER}; font-size: 12px;")

    def _show_toast(self, message: str) -> None:
        """짧은 성공 피드백. 일정 시간 뒤 단축키 안내로 돌아간다."""
        self._message_label.setStyleSheet(f"color: {Colors.TEXT}; font-size: 12px;")
        self._message_label.setText(message)
        self._action_button.hide()
        QTimer.singleShot(TOAST_DURATION_MS, self._restore_message)

    def _show_error(self, error: DeckError) -> None:
        """오류를 사용자 언어로 보여 준다. traceback은 절대 노출하지 않는다."""
        if isinstance(error, NothingPlayingError):
            return  # 오류가 아니라 정상 상태다

        # 네트워크 오류는 연결 표시등도 함께 바꾼다.
        if not error.recoverable or "연결" in error.user_message:
            self._set_connected(False)

        text = error.user_message
        if error.hint:
            text += f"  —  {error.hint.replace(chr(10), ' ')}"

        color = Colors.WARNING if error.recoverable else Colors.DANGER
        self._message_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._message_label.setText(text)

        if error.detail:
            logger.info("오류 상세: %s", error.detail)

        # 복구 가능한 오류는 잠시 뒤 안내로 되돌린다.
        if error.recoverable:
            QTimer.singleShot(TOAST_DURATION_MS * 2, self._restore_message)

    def _restore_message(self) -> None:
        if self._connected:
            self._set_hint_message()

    def _on_recovered(self) -> None:
        self._set_connected(True)
        self._show_toast("다시 연결되었습니다")

    # -- 반응형 --------------------------------------------------------------

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_layout_mode()

    def _update_layout_mode(self) -> None:
        """창 너비에 따라 가로/세로 배치를 전환한다."""
        narrow = self.width() < NARROW_BREAKPOINT
        if narrow == self._is_narrow:
            return
        self._is_narrow = narrow

        self._body.setDirection(
            QHBoxLayout.Direction.TopToBottom if narrow else QHBoxLayout.Direction.LeftToRight
        )
        self._body.setSpacing(16 if narrow else 32)

        # 좁은 화면에서는 글자 크기를 줄여야 제목이 3줄로 넘치지 않는다.
        title_font = self._title_label.font()
        title_font.setPointSize(18 if narrow else 26)
        self._title_label.setFont(title_font)

        artist_font = self._artist_label.font()
        artist_font.setPointSize(12 if narrow else 14)
        self._artist_label.setFont(artist_font)

        # 좁은 화면에서는 웨이브 바도 낮춘다 (3.5인치 LCD 대응).
        if self._wave is not None:
            self._wave.setFixedHeight(40 if narrow else 68)

        # 세로 배치에서는 앨범 아트가 화면을 다 먹지 않도록 비중을 줄인다.
        self._body.setStretch(0, 4 if narrow else 5)
        self._body.setStretch(1, 5 if narrow else 6)

    # -- 종료 ----------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        logger.debug("창을 닫습니다.")
        self._tick.stop()
        if self._wave is not None:
            self._wave.stop()
        self._poller.stop()
        self._poller.wait(2000)
        super().closeEvent(event)
