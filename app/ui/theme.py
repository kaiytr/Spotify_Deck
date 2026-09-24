"""다크 테마 색상과 스타일시트.

색상을 한곳에 모아 두면 나중에 LCD 패널에 맞춰 대비를 조정할 때
이 파일만 고치면 된다. (저가 TN 패널은 명암비가 낮아 회색 단계를 넓혀야 한다)
"""

from __future__ import annotations


class Colors:
    """Spotify 느낌의 다크 팔레트."""

    # 배경 단계 (뒤 -> 앞)
    BG = "#0A0A0A"            # 창 배경. 순검정보다 살짝 밝게 해 눈부심을 줄인다.
    SURFACE = "#161616"       # 카드/패널
    SURFACE_HI = "#1F1F1F"    # 호버 상태
    BORDER = "#282828"

    # 텍스트
    TEXT = "#FFFFFF"
    TEXT_DIM = "#B3B3B3"      # 보조 정보 (아티스트, 시간)
    TEXT_MUTED = "#6A6A6A"    # 비활성

    # 포인트
    ACCENT = "#1DB954"        # Spotify 그린
    ACCENT_HI = "#1ED760"     # 호버
    ACCENT_DIM = "#14833B"

    # 상태
    DANGER = "#E22134"
    WARNING = "#E8A33D"
    LIKE = "#1ED760"

    # 진행 바
    TRACK_BG = "#404040"
    TRACK_FILL = "#FFFFFF"    # 평소엔 흰색, 호버 시 그린으로 바뀐다


#: 기본 폰트 스택. Windows/Linux(RK3399) 양쪽에서 한글이 깨지지 않는 순서.
FONT_STACK = '"Segoe UI", "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR", sans-serif'


def build_stylesheet() -> str:
    """앱 전역 QSS.

    위젯별 세부 스타일은 각 위젯이 직접 그리므로 여기서는
    기본 색/폰트와 단순 위젯(툴팁, 스크롤바)만 다룬다.
    """
    c = Colors
    return f"""
    QWidget {{
        background-color: {c.BG};
        color: {c.TEXT};
        font-family: {FONT_STACK};
    }}

    QLabel {{
        background: transparent;
    }}

    QToolTip {{
        background-color: {c.SURFACE_HI};
        color: {c.TEXT};
        border: 1px solid {c.BORDER};
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 12px;
    }}

    /* 상태 배너 (오류/안내) */
    QFrame#StatusBanner {{
        background-color: {c.SURFACE};
        border: 1px solid {c.BORDER};
        border-radius: 10px;
    }}

    QPushButton#TextButton {{
        background-color: {c.ACCENT};
        color: #000000;
        border: none;
        border-radius: 18px;
        padding: 9px 22px;
        font-size: 13px;
        font-weight: 600;
    }}
    QPushButton#TextButton:hover {{
        background-color: {c.ACCENT_HI};
    }}
    QPushButton#TextButton:pressed {{
        background-color: {c.ACCENT_DIM};
    }}

    QPushButton#GhostButton {{
        background-color: transparent;
        color: {c.TEXT_DIM};
        border: 1px solid {c.BORDER};
        border-radius: 16px;
        padding: 7px 16px;
        font-size: 12px;
    }}
    QPushButton#GhostButton:hover {{
        color: {c.TEXT};
        border-color: {c.TEXT_MUTED};
    }}
    """
