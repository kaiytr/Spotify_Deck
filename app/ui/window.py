"""메인 윈도우.

Spotify Deck 기준 디자인의 **세로 스택** 구조를 따른다.
PC와 480x320 기기가 같은 구조를 쓰고 치수만 달라진다.

    ┌──────────────────────────────────────────────┐
    │ ● 연결됨                    기기명 · 컴퓨터   │  상단바
    │ ┌────────┐  Song Title                       │
    │ │  ART   │  Artist                           │  미디어 블록
    │ │        │  ALBUM                            │
    │ └────────┘  ▁▃▅▇▅▃▁▂▄▆                      │
    │ ━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │  진행 바 (전체 폭)
    │ 1:42                                    3:58 │
    │    ♡    ⤨    ◀    ( ▶ )    ▶▶    ⟲        │  컨트롤 한 줄
    │              🔊 ━━━━━━━━━                    │  볼륨
    └──────────────────────────────────────────────┘

2열로 나누지 않는 이유: 앨범 아트를 한쪽 열에 세로로 꽉 채우면
480x320에서 화면 절반을 먹고 나머지가 눌린다. 아트를 작게 두고
위에서 아래로 쌓으면 진행 바와 컨트롤이 전체 폭을 쓸 수 있다.

치수는 모두 app/ui/layouts.py 의 LayoutProfile 에서 나온다.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QFont, QPainter, QResizeEvent
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
from app.ui.layouts import DESKTOP, LayoutProfile, profile_for_width
from app.ui.palette import AccentPalette
from app.ui.theme import Colors, build_stylesheet
from app.ui.widgets.album_art import AlbumArtWidget
from app.ui.widgets.buttons import IconButton, IconLabel, PlayButton
from app.ui.widgets.marquee import MarqueeLabel
from app.ui.widgets.slider import ProgressSlider
from app.ui.widgets.wave_bar import WaveBarWidget
from app.ui.worker import ActionRunner, PollWorker

logger = logging.getLogger(__name__)

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
        layout: LayoutProfile | None = None,
        lock_layout: bool = False,
        true_size_scale: float | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """
        Args:
            layout: 시작 레이아웃 프로파일. None이면 DESKTOP(기존 PC UI).
            lock_layout: True면 창 크기가 바뀌어도 프로파일을 바꾸지 않는다.
                ESP32 화면(480x320)을 흉내 낼 때 쓴다 — 실제 기기는
                해상도가 고정이므로 반응형으로 바뀌면 설계 확인이 안 된다.
        """
        super().__init__(parent)
        self._controller = controller
        self._poller = poller
        self._pool = QThreadPool.globalInstance()

        #: 현재 레이아웃 프로파일. 모든 치수가 여기서 나온다.
        self._layout = layout or DESKTOP
        self._locked_layout = self._layout if lock_layout else None

        # 웨이브 바. wave_source가 None이면(DECK_WAVE_MODE=off) 표시하지 않는다.
        self._wave = (
            WaveBarWidget(wave_source, height=self._layout.wave_height,
                          fps=self._layout.wave_fps)
            if wave_source is not None
            else None
        )

        self._state = PlaybackState.empty()
        self._connected = False
        #: 실행 중인 ActionRunner의 강한 참조 (GC로 시그널이 끊기는 것을 막는다)
        self._running_actions: set[ActionRunner] = set()
        #: 현재 앨범에서 뽑은 강조색
        self._accent = AccentPalette.default()
        #: --compact 일 때 기기 화면 크기로 고정된 프레임 (없으면 None)
        self._device_frame: QWidget | None = None
        #: 실물 크기 보정 배율 (--true-size). None이면 보정 없음.
        self._true_size_scale = true_size_scale
        #: 시계에 마지막으로 그린 문자열 (분이 바뀔 때만 다시 그린다)
        self._clock_text = ""

        profile = self._layout
        self.setWindowTitle("Spotify Deck")

        if lock_layout:
            # 창은 화면에 그려질 기기 크기에 맞춘다.
            #
            # --true-size 면 내용물이 축소되므로 창도 그만큼 작아야 한다.
            # 창을 480x320으로 두면 축소된 355x237 내용 주위에 검은 여백이
            # 생겨서 "어디까지가 실제 4인치인지" 헷갈린다.
            #
            # 창 자체를 setFixedSize로 묶지는 않는다. --fullscreen이
            # 강제로 창을 늘릴 때 충돌하기 때문이다. 대신 내부 프레임을
            # 고정해 두었으므로 전체화면에서는 검은 배경 가운데에
            # 기기 화면이 실제 크기로 놓인다.
            width, height = self.rendered_device_size()
            self.setMinimumSize(width, height)
            self.resize(width, height)
        else:
            self.setMinimumSize(profile.min_width, profile.min_height)
            self.resize(profile.window_width, profile.window_height)

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
        """세로 스택 구조로 화면을 만든다.

            상단바
            미디어 블록 (앨범아트 | 제목·아티스트·앨범·웨이브)
            진행 바 (전체 폭)
            시간 (좌: 경과 / 우: 전체)
            컨트롤 한 줄 (♡ ⤨ ◀ ▶ ▶▶ ⟲)
            볼륨
            [단축키 안내 - 데스크톱만]

        2열로 나누지 않는 이유: 앨범 아트를 한쪽 열에 세로로 꽉 채우면
        480x320에서 화면 절반을 먹고 나머지가 눌린다. 아트를 작게 두고
        위에서 아래로 쌓으면 진행 바와 컨트롤이 전체 폭을 쓸 수 있다.
        """
        central = QWidget()
        self.setCentralWidget(central)

        profile = self._layout
        host = self._make_device_frame(central, profile)

        root = QVBoxLayout(host)
        root.setContentsMargins(
            profile.margin_h, profile.margin_v, profile.margin_h, profile.margin_v
        )
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addSpacing(profile.section_gap)

        # 미디어 블록에 진행 바까지 포함한다.
        # 기준 디자인은 진행 바가 화면 전체 폭이 아니라 **곡 정보와 같은
        # 왼쪽 끝**에서 시작한다. 앨범 아트 아래를 비우고 오른쪽 열에 맞춘다.
        root.addWidget(self._build_media_block(profile), 0)

        # 남는 세로는 여기로 몰아 컨트롤을 아래쪽에 붙인다.
        root.addStretch(1)

        root.addWidget(self._build_controls(profile))

        # 볼륨 줄. 기기 버전에서는 로터리 엔코더가 담당하므로 화면에서 뺀다.
        # 위젯 자체는 만들어 둔다 — 상태 반영 코드가 참조하고,
        # 방향키로 볼륨을 바꿀 때 값이 갱신되어야 하기 때문이다.
        self._volume_row = self._build_volume(profile)
        if profile.show_volume:
            root.addSpacing(max(4, profile.section_gap - 4))
            root.addWidget(self._volume_row)
        else:
            self._volume_row.hide()

        self._footer = self._build_footer()
        if profile.show_key_hints:
            root.addSpacing(profile.section_gap)
            root.addWidget(self._footer)
        self._footer.setVisible(profile.show_key_hints)

    # -- 구성 요소 -----------------------------------------------------------

    def _build_media_block(self, profile: LayoutProfile) -> QWidget:
        """앨범 아트 + (곡 정보 · 웨이브 · 진행 바).

        기준 디자인처럼 오른쪽 열이 하나의 덩어리다.
        진행 바도 곡 정보와 같은 왼쪽 끝에서 시작한다.

        곡 정보는 모두 **높이가 고정된 한 줄 마키 라벨**이다.
        줄바꿈을 쓰면 긴 제목이 두 줄이 되면서 웨이브와 진행 바를 밀어내
        곡이 바뀔 때마다 화면이 들썩인다.
        """
        block = QWidget()
        row = QHBoxLayout(block)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(profile.column_gap)

        edge = profile.art_edge
        self._album_art = AlbumArtWidget(radius=10 if edge < 200 else 14)
        self._album_art.setFixedSize(edge, edge)
        row.addWidget(self._album_art, 0, Qt.AlignmentFlag.AlignTop)

        info = QWidget()
        col = QVBoxLayout(info)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        title_font = QFont()
        title_font.setPointSize(profile.title_pt)
        title_font.setWeight(QFont.Weight.Bold)
        self._title_label = MarqueeLabel(
            "재생 중인 음악이 없습니다", font=title_font, color=Colors.TEXT
        )

        artist_font = QFont()
        artist_font.setPointSize(profile.artist_pt)
        self._artist_label = MarqueeLabel("", font=artist_font, color=Colors.TEXT_DIM)

        album_font = QFont()
        album_font.setPointSize(profile.album_pt)
        self._album_label = MarqueeLabel("", font=album_font, color=Colors.TEXT_MUTED)
        self._album_label.setVisible(profile.show_album_line)

        col.addWidget(self._title_label)
        col.addSpacing(2)
        col.addWidget(self._artist_label)
        if profile.show_album_line:
            col.addSpacing(1)
            col.addWidget(self._album_label)

        # 남는 세로는 곡 정보 **바로 아래**에 몰아, 웨이브와 진행 바를
        # 블록 아래쪽으로 내린다.
        #
        # 기준 디자인도 시간 라벨이 앨범 아트 바닥과 나란하다.
        # 중간에 stretch를 또 넣으면 웨이브와 진행 바 사이가 벌어져
        # 아트 옆이 휑해 보인다.
        col.addStretch(1)

        if self._wave is not None:
            col.addWidget(self._wave)
            col.addSpacing(profile.section_gap)

        col.addWidget(self._build_progress(profile))

        row.addWidget(info, 1)
        return block

    def _build_progress(self, profile: LayoutProfile) -> QWidget:
        """진행 바 + 시간. 전체 폭을 쓴다."""
        wrapper = QWidget()
        col = QVBoxLayout(wrapper)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._seek = ProgressSlider(
            height=profile.seek_height,
            track_height=profile.seek_track,
            handle_radius=profile.seek_handle,
            # 터치 기기는 호버가 없어 핸들이 숨으면 잡을 수가 없다.
            always_show_handle=profile.touch_targets,
        )
        col.addWidget(self._seek)

        times = QHBoxLayout()
        times.setContentsMargins(0, 0, 0, 0)
        self._elapsed_label = QLabel("--:--")
        self._duration_label = QLabel("--:--")
        for label in (self._elapsed_label, self._duration_label):
            label.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: {profile.meta_pt + 1}px;"
            )
        times.addWidget(self._elapsed_label)
        times.addStretch(1)
        times.addWidget(self._duration_label)
        col.addLayout(times)

        return wrapper

    def _build_controls(self, profile: LayoutProfile) -> QWidget:
        """컨트롤 한 줄: 좋아요 · 셔플 · 이전 · 재생 · 다음 · 반복.

        기준 디자인처럼 전체 폭에 균등 배치한다.
        두 줄로 나누면 세로를 더 먹고 시선이 흩어진다.
        """
        self._like_btn = IconButton(
            Icon.HEART, size=profile.toggle_button,
            active_color=Colors.LIKE, tooltip="좋아요  (L)",
        )
        self._shuffle_btn = IconButton(
            Icon.SHUFFLE, size=profile.toggle_button, tooltip="셔플  (S)"
        )
        self._prev_btn = IconButton(
            Icon.PREVIOUS, size=profile.skip_button, tooltip="이전 곡  (←)"
        )
        self._play_btn = PlayButton(size=profile.play_button)
        self._next_btn = IconButton(
            Icon.NEXT, size=profile.skip_button, tooltip="다음 곡  (→)"
        )
        self._repeat_btn = IconButton(
            Icon.REPEAT, size=profile.toggle_button, tooltip="반복  (R)"
        )

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        # 기준 디자인의 순서: 좋아요 · 이전 · [재생] · 다음 · 셔플 · 반복
        #
        # **재생 버튼을 화면 정중앙에 고정**한다.
        # 버튼 묶음 전체를 가운데 정렬하면 재생이 3번째라 중앙에서 밀린다.
        # 좌우를 같은 stretch를 가진 상자로 나누고 그 사이에 재생을 두면
        # 양쪽 개수가 달라도(2 : 3) 재생은 항상 정중앙에 온다.
        gap = profile.column_gap + 6

        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(gap)
        left.addStretch(1)
        left.addWidget(self._like_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        left.addWidget(self._prev_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(gap)
        right.addWidget(self._next_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self._shuffle_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(self._repeat_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addStretch(1)

        row.addLayout(left, 1)
        row.addSpacing(gap)
        row.addWidget(self._play_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(gap)
        row.addLayout(right, 1)

        return bar

    def _build_volume(self, profile: LayoutProfile) -> QWidget:
        """볼륨 줄.

        기준 디자인은 볼륨을 '⋯' 메뉴 뒤에 숨기지만 이 앱에는 메뉴가 없고
        볼륨은 필수 기능이라 별도 줄로 드러낸다.
        """
        self._volume_icon = IconButton(
            Icon.VOLUME, size=profile.volume_icon, icon_ratio=0.62,
            tooltip="음소거 / 해제",
        )
        self._volume = ProgressSlider(
            height=max(14, profile.seek_height - 2),
            track_height=profile.seek_track - 1,
            handle_radius=profile.seek_handle - 1,
            always_show_handle=profile.touch_targets,
        )
        self._volume.set_range(100)
        # 고정 폭으로 둔다. setMaximumWidth만 주면 같은 줄의 스트레치가
        # 남는 공간을 전부 가져가 슬라이더가 0px로 찌그러진다.
        self._volume.setFixedWidth(profile.volume_width)

        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(self._volume_icon)
        row.addWidget(self._volume)
        row.addStretch(1)
        return bar

    def rendered_device_size(self) -> tuple[int, int]:
        """기기 화면이 실제로 그려지는 크기 (논리 픽셀).

        --true-size 배율이 걸리면 축소된 크기를, 아니면 프로파일 크기를
        돌려준다. 창 크기를 여기에 맞춰야 검은 여백 없이
        "창 = 기기 화면"이 되어 실물 크기를 자로 잴 수 있다.
        """
        profile = self._layout
        scale = self._true_size_scale

        if scale is None or abs(scale - 1.0) <= 0.01:
            return profile.window_width, profile.window_height

        # +1은 QGraphicsView가 경계에서 1px을 잘라먹지 않게 하는 여유다.
        return (
            round(profile.window_width * scale) + 1,
            round(profile.window_height * scale) + 1,
        )

    def _make_device_frame(self, central: QWidget, profile: LayoutProfile) -> QWidget:
        """실제 UI를 담을 위젯을 돌려준다.

        고정 레이아웃(--compact)이면 기기 화면 크기로 고정한 프레임을
        가운데에 놓고 그 안에 UI를 만든다. 그러면 창이 커져도
        (전체화면 포함) 기기 화면은 480x320 실제 크기를 유지한다.

        실물 크기 배율(--true-size)이 있으면 그 프레임을 QGraphicsView에
        넣어 축소한다. **레이아웃은 480x320 그대로 두고 그려진 결과만
        줄이는 것**이 핵심이다. 창을 354x236으로 줄이면 폰트와 버튼이
        다시 배치되어 실제 기기와 다른 화면이 되어 버린다.

        일반 PC 모드에서는 그냥 central을 쓴다 — 기존 동작 그대로다.
        """
        if self._locked_layout is None:
            return central

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        frame = QWidget()
        frame.setFixedSize(profile.window_width, profile.window_height)
        # 그래픽 씬에 들어가면 부모 스타일시트를 못 물려받아 배경이 비어 보인다.
        frame.setAutoFillBackground(True)
        frame.setStyleSheet(f"background-color: {Colors.BG};")

        centered: QWidget = frame
        scale = self._true_size_scale

        if scale is not None and abs(scale - 1.0) > 0.01:
            centered = self._wrap_in_scaled_view(frame, profile, scale)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(centered)
        row.addStretch(1)

        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self._device_frame = frame
        return frame

    def _wrap_in_scaled_view(
        self, frame: QWidget, profile: LayoutProfile, scale: float
    ) -> QWidget:
        """프레임을 QGraphicsView에 넣어 배율을 적용한다.

        QGraphicsProxyWidget은 마우스·키보드 이벤트의 좌표를 역변환해
        전달하므로, 축소해도 버튼 클릭과 슬라이더 드래그가 정상 동작한다.
        """
        from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView

        scene = QGraphicsScene(self)
        scene.setBackgroundBrush(QColor(Colors.BG))
        scene.addWidget(frame)

        view = QGraphicsView(scene)
        view.setTransform(view.transform().scale(scale, scale))
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        view.setStyleSheet("border: none;")
        # 뷰 크기를 축소된 크기에 정확히 맞춰 여백이나 스크롤이 생기지 않게 한다.
        view.setFixedSize(*self.rendered_device_size())
        view.setSceneRect(0, 0, profile.window_width, profile.window_height)

        logger.debug("실물 크기 뷰: 배율 %.3f", scale)
        return view

    def _build_header(self) -> QWidget:
        """상단: 연결 상태 + 기기 이름.

        글자 크기는 프로파일을 따른다. 고정값으로 박아 두면
        다른 요소를 키울 때 상단바만 작게 남아 어색해진다.
        """
        size = self._layout.meta_pt + 2

        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Spotify 마크가 연결 상태를 겸한다.
        #   연결됨   -> 앨범 강조색 (곡이 바뀌면 함께 물든다)
        #   끊김     -> 빨강
        # 평소에는 글자 없이 마크만 두고, 문제가 생겼을 때만 설명을 띄운다.
        self._logo = IconLabel(
            Icon.SPOTIFY, size=self._layout.meta_pt + 12, color=Colors.TEXT_MUTED
        )

        self._status_label = QLabel("연결 중...")
        self._status_label.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {size}px;"
        )

        # 기기 이름은 화면에 두지 않고 더보기(...) 메뉴로 옮겼다.
        # 오른쪽 위는 기준 디자인처럼 WiFi + 시계가 차지한다.
        # 라벨 자체는 남겨 둔다 — 상태 반영 코드가 기기 이름을 여기 보관하고
        # 메뉴를 열 때 그 값을 읽는다.
        self._device_label = QLabel("")
        self._device_label.hide()

        self._wifi = IconLabel(
            Icon.WIFI, size=self._layout.meta_pt + 8, color=Colors.TEXT_DIM
        )

        self._clock_label = QLabel("--:--")
        self._clock_label.setStyleSheet(
            f"color: {Colors.TEXT_DIM}; font-size: {size + 1}px;"
        )

        # 더보기(...)는 컨트롤 줄이 아니라 여기 둔다.
        #
        # 컨트롤 줄에 넣으면 재생 버튼 오른쪽이 4개(다음·셔플·반복·더보기),
        # 왼쪽이 2개(좋아요·이전)가 되어 오른쪽 묶음이 절반 폭을 넘고
        # 재생 버튼이 화면 중앙에서 밀려난다.
        # 설정 성격의 메뉴라 상단바가 제자리이기도 하다.
        self._more_btn = IconButton(
            Icon.MORE, size=self._layout.meta_pt + 12, tooltip="더보기"
        )

        layout.addWidget(self._logo)
        layout.addWidget(self._status_label)
        layout.addStretch(1)
        layout.addWidget(self._wifi)
        layout.addSpacing(2)
        layout.addWidget(self._clock_label)
        layout.addSpacing(6)
        layout.addWidget(self._more_btn)

        self._update_clock()
        return header

    def _update_clock(self) -> None:
        """시계를 현재 시각으로 갱신한다.

        1초마다 문자열을 다시 만들 필요는 없으므로 분이 바뀔 때만 갱신한다.
        (진행률 타이머가 100ms마다 호출하므로 비교를 넣지 않으면 낭비가 크다)
        """
        from datetime import datetime

        now = datetime.now().strftime("%H:%M")
        if now != self._clock_text:
            self._clock_text = now
            self._clock_label.setText(now)

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
        self._more_btn.clicked.connect(self._show_more_menu)

        self._seek.seek_requested.connect(
            lambda ms: self._dispatch(DeckAction.SEEK_SET, position_ms=ms)
        )
        self._seek.value_preview.connect(
            lambda ms: self._elapsed_label.setText(format_duration(ms))
        )
        self._volume.seek_requested.connect(
            lambda v: self._dispatch(DeckAction.VOLUME_SET, value=v)
        )

        # 앨범 아트에서 뽑은 색을 UI 전체에 전파한다.
        self._album_art.accent_changed.connect(self._apply_accent)

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

    def _show_more_menu(self) -> None:
        """더보기 메뉴.

        기기 버전에서는 볼륨 슬라이더를 화면에서 뺐으므로
        음소거를 여기서 할 수 있게 한다.
        """
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(
            f"""
            QMenu {{
                background-color: {Colors.SURFACE};
                color: {Colors.TEXT};
                border: 1px solid {Colors.BORDER};
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{ padding: 7px 18px; border-radius: 5px; }}
            QMenu::item:selected {{ background-color: {Colors.SURFACE_HI}; }}
            """
        )

        # 현재 재생 기기를 메뉴 맨 위에 보여 준다 (상단바에서 뺀 정보).
        device = self._state.device
        if device.name:
            header = menu.addAction(f"{device.name} · {device.icon_hint}")
            header.setEnabled(False)
            menu.addSeparator()

        # 볼륨 올리기/내리기는 넣지 않는다.
        # 메뉴를 열고 항목을 고르는 동작을 반복하는 건 볼륨 조절 방식으로
        # 번거롭다. 위/아래 방향키가 즉시 동작하고, 실물 기기에서는
        # 로터리 엔코더가 그 역할을 한다.
        muted = self._state.volume == 0
        menu.addAction("음소거 해제" if muted else "음소거", self._toggle_mute)
        menu.addSeparator()
        menu.addAction("새로고침", lambda: self._dispatch(DeckAction.REFRESH))
        menu.addSeparator()
        menu.addAction("종료", self.close)

        # 버튼 위쪽에 띄운다. 아래는 화면 끝이라 잘린다.
        corner = self._more_btn.mapToGlobal(self._more_btn.rect().topLeft())
        menu.exec(corner - QPoint(menu.sizeHint().width() - self._more_btn.width(),
                                  menu.sizeHint().height() + 6))

    def _toggle_mute(self) -> None:
        """볼륨 0 <-> 이전 값 토글."""
        current = self._state.volume
        if current > 0:
            self._muted_volume = current
            self._dispatch(DeckAction.VOLUME_SET, value=0)
        else:
            self._dispatch(DeckAction.VOLUME_SET, value=getattr(self, "_muted_volume", 50))

    # -- 강조색 --------------------------------------------------------------

    def _apply_accent(self, palette: AccentPalette) -> None:
        """앨범 색을 화면 전체에 입힌다.

        곡이 바뀔 때만 호출되므로 비용은 무시할 만하다.
        버튼은 자체 애니메이션이 있어 색이 부드럽게 전환된다.
        """
        self._accent = palette

        self._wave and self._wave.set_accent(palette)
        self._seek.set_accent(palette)
        self._volume.set_accent(palette)
        self._play_btn.set_accent(palette.base, palette.bright)

        for button in (self._shuffle_btn, self._repeat_btn):
            button.set_accent(palette.base)

        # 좋아요는 하트라서 초록보다 앨범색이 더 자연스럽다.
        self._like_btn.set_accent(palette.bright)

        self._more_btn.set_accent(palette.base)

        # Spotify 마크도 함께 물들여 화면이 하나로 보이게 한다.
        if self._connected:
            self._logo.set_color(palette.base)

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
        self._update_clock()

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
        size = self._layout.meta_pt + 2

        if connected:
            # 정상일 때는 마크만 두고 글자를 지운다.
            # "연결됨"은 굳이 읽을 필요가 없고, 작은 화면에서 자리만 차지한다.
            self._logo.set_color(self._accent.base)
            self._wifi.set_icon(Icon.WIFI)
            self._wifi.set_color(QColor(Colors.TEXT_DIM))
            self._status_label.setText("")
            self._status_label.hide()
        else:
            self._logo.set_color(QColor(Colors.DANGER))
            self._wifi.set_icon(Icon.WIFI_OFF)
            self._wifi.set_color(QColor(Colors.DANGER))
            self._status_label.setText("연결 끊김")
            self._status_label.setStyleSheet(
                f"color: {Colors.DANGER}; font-size: {size}px;"
            )
            self._status_label.show()

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
        """창 너비에 맞는 프로파일로 전환한다.

        --compact 로 실행하면 프로파일이 고정되어 아무것도 하지 않는다
        (ESP32는 해상도가 고정이므로 반응형으로 바뀌면 설계 확인이 안 된다).
        """
        profile = profile_for_width(self.width(), locked=self._locked_layout)
        if profile is self._layout:
            return

        self._layout = profile
        self._apply_profile(profile)

    def _apply_profile(self, profile: LayoutProfile) -> None:
        """프로파일의 치수를 이미 만들어진 위젯들에 반영한다.

        위젯을 다시 만들지 않고 크기·폰트만 바꾼다.
        재생성하면 앨범 아트 캐시와 웨이브 상태가 날아간다.
        """
        host = self._device_frame or self.centralWidget()
        if host is not None and host.layout() is not None:
            host.layout().setContentsMargins(
                profile.margin_h, profile.margin_v, profile.margin_h, profile.margin_v
            )

        # --- 앨범 아트 ---
        edge = profile.art_edge
        self._album_art.setFixedSize(edge, edge)

        # --- 글자 ---
        title_font = self._title_label.font()
        title_font.setPointSize(profile.title_pt)
        self._title_label.setFont(title_font)

        artist_font = self._artist_label.font()
        artist_font.setPointSize(profile.artist_pt)
        self._artist_label.setFont(artist_font)

        self._album_label.setVisible(profile.show_album_line)

        for label in (self._elapsed_label, self._duration_label):
            label.setStyleSheet(
                f"color: {Colors.TEXT_DIM}; font-size: {profile.meta_pt + 1}px;"
            )

        # --- 컨트롤 ---
        self._play_btn.setFixedSize(profile.play_button, profile.play_button)
        for button in (self._prev_btn, self._next_btn):
            button.setFixedSize(profile.skip_button, profile.skip_button)
        for button in (self._shuffle_btn, self._repeat_btn, self._like_btn):
            button.setFixedSize(profile.toggle_button, profile.toggle_button)
        self._volume_icon.setFixedSize(profile.volume_icon, profile.volume_icon)
        self._volume.setFixedWidth(profile.volume_width)

        # --- 웨이브 ---
        if self._wave is not None:
            self._wave.setFixedHeight(profile.wave_height)

        # --- 하단 안내 ---
        self._footer.setVisible(profile.show_key_hints)

        logger.debug("레이아웃 전환: %s", profile.name)

    # -- 종료 ----------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        logger.debug("창을 닫습니다.")
        self._tick.stop()
        if self._wave is not None:
            self._wave.stop()
        self._poller.stop()
        self._poller.wait(2000)
        super().closeEvent(event)
