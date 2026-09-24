"""앨범 아트 위젯.

요구사항:
  * 이미지를 네트워크에서 받아오되 **UI가 멈추면 안 된다** -> 워커 스레드
  * 같은 곡을 다시 받지 않는다 -> URL 캐시
  * 곡이 바뀔 때 뚝 끊기지 않게 페이드 전환
  * 3.5인치 LCD로 줄여도 뭉개지지 않게 고품질 스케일링
"""

from __future__ import annotations

import logging
from collections import OrderedDict

import requests
from PySide6.QtCore import (
    QObject,
    QRectF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.icons import Icon, draw_icon
from app.ui.palette import AccentPalette, extract_accent
from app.ui.theme import Colors

logger = logging.getLogger(__name__)

#: 메모리에 유지할 앨범 아트 개수. 곡을 앞뒤로 넘길 때 재다운로드를 막는다.
CACHE_SIZE = 24


class _ImageSignals(QObject):
    finished = Signal(str, QPixmap)  # (url, pixmap)
    failed = Signal(str)


class _ImageLoader(QRunnable):
    """앨범 아트 한 장을 받아오는 작업.

    QThreadPool에서 실행되므로 UI 스레드를 막지 않는다.
    """

    def __init__(self, url: str) -> None:
        super().__init__()
        self.url = url
        self.signals = _ImageSignals()

    def run(self) -> None:
        try:
            resp = requests.get(self.url, timeout=(5, 10))
            resp.raise_for_status()
            pixmap = QPixmap()
            if not pixmap.loadFromData(resp.content):
                raise ValueError("이미지 형식을 해석할 수 없습니다")
        except Exception as exc:  # noqa: BLE001 - 앨범 아트 실패는 치명적이지 않다
            logger.debug("앨범 아트 로딩 실패 (%s): %s", self.url, exc)
            self._emit(self.signals.failed, self.url)
            return
        self._emit(self.signals.finished, self.url, pixmap)

    @staticmethod
    def _emit(signal, *args) -> None:
        """시그널을 안전하게 발행한다.

        다운로드가 진행 중일 때 창이 닫히면 C++ 쪽 수신자가 먼저 파괴되어
        emit이 RuntimeError를 던진다. 앱 종료 시마다 traceback이 쏟아지므로
        여기서 조용히 흡수한다. (이미 창이 없으니 전달할 곳도 없다)
        """
        try:
            signal.emit(*args)
        except RuntimeError:
            logger.debug("수신자가 이미 파괴되어 앨범 아트 결과를 버립니다.")


class AlbumArtWidget(QWidget):
    """둥근 모서리 앨범 아트.

    이미지가 없으면 음표 대신 은은한 플레이스홀더를 그린다.

    Signals:
        accent_changed(AccentPalette): 새 앨범 아트에서 뽑아낸 강조색.
            곡이 바뀔 때만 발생하므로 UI가 이걸 받아 테마를 갈아입는다.
    """

    accent_changed = Signal(object)

    def __init__(self, *, radius: int = 12, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._pixmap: QPixmap | None = None
        self._previous: QPixmap | None = None
        self._current_url: str | None = None
        self._pending_url: str | None = None

        # LRU 캐시
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._pool = QThreadPool.globalInstance()

        # 실행 중인 로더의 강한 참조.
        # QThreadPool은 C++ 객체만 소유하므로, 여기서 붙잡아 두지 않으면
        # 파이썬 쪽 _ImageSignals가 GC되어 emit 시점에
        # "Signal source has been deleted"로 죽는다.
        self._inflight: set[_ImageLoader] = set()

        #: 현재 앨범에서 뽑아낸 강조색. 같은 색이면 다시 알리지 않는다.
        self._accent = AccentPalette.default()

        # 페이드 전환
        self._fade = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(16)  # 약 60fps
        self._fade_timer.timeout.connect(self._step_fade)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(120, 120)

    # -- 공개 API ------------------------------------------------------------

    def set_url(self, url: str | None) -> None:
        """표시할 앨범 아트 URL을 설정한다. 같은 URL이면 아무 일도 하지 않는다."""
        if url == self._current_url:
            return

        self._current_url = url

        if not url:
            self._begin_transition(None)
            return

        cached = self._cache.get(url)
        if cached is not None:
            self._cache.move_to_end(url)
            self._begin_transition(cached)
            self._emit_accent(cached)
            return

        # 같은 이미지를 두 번 요청하지 않는다.
        if self._pending_url == url:
            return

        self._pending_url = url
        loader = _ImageLoader(url)
        self._inflight.add(loader)
        loader.signals.finished.connect(self._on_loaded)
        loader.signals.failed.connect(self._on_failed)
        # 성공/실패 어느 쪽이든 참조를 놓아 준다.
        loader.signals.finished.connect(lambda *_: self._inflight.discard(loader))
        loader.signals.failed.connect(lambda *_: self._inflight.discard(loader))
        self._pool.start(loader)

    def clear(self) -> None:
        self._current_url = None
        self._begin_transition(None)
        self._emit_accent(None)

    # -- 로딩 결과 -----------------------------------------------------------

    def _on_loaded(self, url: str, pixmap: QPixmap) -> None:
        self._cache[url] = pixmap
        self._cache.move_to_end(url)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)

        if url == self._pending_url:
            self._pending_url = None
        # 이미 다른 곡으로 넘어갔다면 캐시에만 넣고 화면은 바꾸지 않는다.
        if url == self._current_url:
            self._begin_transition(pixmap)
            self._emit_accent(pixmap)

    def _on_failed(self, url: str) -> None:
        if url == self._pending_url:
            self._pending_url = None

    def _emit_accent(self, pixmap: QPixmap | None) -> None:
        """앨범 색을 뽑아 알린다. 같은 색이면 알리지 않는다.

        색 추출은 약 5ms로, 곡이 바뀔 때만 일어나므로 UI 스레드에서 해도 된다.
        """
        palette = extract_accent(pixmap)
        if palette == self._accent:
            return
        self._accent = palette
        self.accent_changed.emit(palette)

    # -- 페이드 --------------------------------------------------------------

    def _begin_transition(self, pixmap: QPixmap | None) -> None:
        self._previous = self._pixmap
        self._pixmap = pixmap
        self._fade = 0.0
        self._fade_timer.start()
        self.update()

    def _step_fade(self) -> None:
        self._fade = min(1.0, self._fade + 0.12)
        if self._fade >= 1.0:
            self._fade_timer.stop()
            self._previous = None
        self.update()

    # -- 렌더링 --------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # 위젯 영역 안에서 정사각형을 중앙 정렬한다 (앨범 아트는 1:1).
        side = min(self.width(), self.height())
        box = QRectF(0, 0, side, side)
        box.moveCenter(QRectF(self.rect()).center())

        path = QPainterPath()
        path.addRoundedRect(box, self._radius, self._radius)
        painter.setClipPath(path)

        # 바탕
        painter.fillRect(box, QColor(Colors.SURFACE))

        if self._previous is not None and self._fade < 1.0:
            painter.setOpacity(1.0 - self._fade)
            self._draw_pixmap(painter, self._previous, box)
            painter.setOpacity(1.0)

        if self._pixmap is not None:
            painter.setOpacity(self._fade if self._previous is not None else 1.0)
            self._draw_pixmap(painter, self._pixmap, box)
            painter.setOpacity(1.0)
        elif self._fade >= 1.0:
            self._draw_placeholder(painter, box)

        painter.setClipping(False)

        # 미세한 테두리 — 어두운 앨범 아트가 배경에 묻히는 것을 막는다.
        painter.setPen(QColor(255, 255, 255, 18))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        painter.end()

    def _draw_pixmap(self, painter: QPainter, pixmap: QPixmap, box: QRectF) -> None:
        """비율을 유지하며 box를 가득 채운다 (가운데 크롭)."""
        target_size = box.size().toSize()
        scaled = pixmap.scaled(
            target_size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        src = QRectF(
            (scaled.width() - target_size.width()) / 2,
            (scaled.height() - target_size.height()) / 2,
            target_size.width(),
            target_size.height(),
        )
        painter.drawPixmap(box, scaled, src)

    def _draw_placeholder(self, painter: QPainter, box: QRectF) -> None:
        """앨범 아트가 없을 때의 대체 표시."""
        icon_side = box.width() * 0.22
        rect = QRectF(0, 0, icon_side, icon_side)
        rect.moveCenter(box.center())
        draw_icon(painter, Icon.DEVICE, rect, QColor(Colors.TEXT_MUTED), stroke_width=1.6)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, 320)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return width
