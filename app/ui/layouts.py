"""레이아웃 프로파일.

화면 크기별 치수를 한곳에 모은다. 위젯 코드에 숫자를 흩뿌리지 않으면
ESP32 UI를 만들 때 "PC에서는 어떤 크기였지?"를 이 파일 하나로 답할 수 있다.

    DESKTOP        기존 PC UI. 지금까지의 모습 그대로 유지한다.
    COMPACT_480    ESP32 목표 해상도(480x320)의 기준 설계.
                   PC에서 `--compact` 로 띄워 실물 없이 확인할 수 있다.

Compact는 "PC UI를 줄인 것"이 아니라 **별도 설계**다.
480x320은 세로가 320px뿐이라 그냥 축소하면 아무것도 안 들어간다.
무엇을 줄이고 무엇을 지킬지 명시적으로 정한다.

────────────────────────────────────────────────────────────────
 480x320 세로 예산 (총 320px)
────────────────────────────────────────────────────────────────
   상단바 (연결 상태 / 기기)          22
   본문 (앨범아트 + 정보 + 컨트롤)   238
   하단 여백/안내                     24
   상하 마진                          36
   ─────────────────────────────────────
                                     320

 본문 238px 안에서 가로로 나눈다:
   왼쪽  앨범 아트 정사각형 238x238
   오른쪽 곡 정보 + 웨이브 + 진행바 + 버튼 2줄

 지킨 것: 앨범아트, 곡정보, 웨이브, 진행바, 시간, 이전/재생/다음,
          셔플/반복/좋아요, 볼륨, 연결상태, 기기명  (전 기능 유지)
 줄인 것: 폰트 크기, 여백, 버튼 지름, 웨이브 높이, 앨범명은 한 줄 말줄임
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutProfile:
    """화면 크기에 따른 치수 모음.

    모든 값은 논리 픽셀이다.
    """

    name: str

    # --- 창 ---
    window_width: int
    window_height: int
    min_width: int
    min_height: int

    # --- 바깥 여백 ---
    margin_h: int
    margin_v: int
    #: 앨범 아트와 정보 패널 사이 간격
    column_gap: int
    #: 상단바 / 본문 / 하단바 사이 간격
    section_gap: int

    # --- 글자 크기 (pt) ---
    title_pt: int
    artist_pt: int
    album_pt: int
    meta_pt: int
    """상단 상태·기기명·시간 같은 보조 텍스트"""

    # --- 컨트롤 ---
    play_button: int
    skip_button: int
    toggle_button: int
    """셔플 / 반복 / 좋아요"""
    volume_icon: int
    volume_width: int

    # --- 진행 바 ---
    seek_height: int
    seek_track: float
    seek_handle: float

    # --- 웨이브 바 ---
    wave_height: int
    wave_fps: int

    # --- 배치 비율 (앨범아트 : 정보패널) ---
    art_stretch: int
    panel_stretch: int

    # --- 동작 ---
    show_album_line: bool
    """앨범명 줄을 표시할지. 세로가 빠듯하면 끈다."""
    show_key_hints: bool
    """하단 단축키 안내. 터치 기기에서는 의미가 없다."""
    touch_targets: bool
    """True면 버튼 히트 영역을 시각 크기보다 넓게 잡는다."""

    # --- 기본값이 있는 필드는 여기부터 (dataclass 규칙) ---

    art_vertical_bias: float = 0.5
    """앨범 아트의 세로 위치. 0.0=위쪽 끝, 0.5=가운데, 1.0=아래쪽 끝.

    아트는 정사각형이라 세로로 긴 영역에서는 남는 공간이 생긴다.
    가운데에 두면 오른쪽 곡 정보보다 아래로 처져 보인다.
    """

    @property
    def aspect(self) -> float:
        return self.window_width / self.window_height


# ---------------------------------------------------------------------------
#  PC (기존 UI) — 지금까지의 모습을 그대로 보존한다
# ---------------------------------------------------------------------------

DESKTOP = LayoutProfile(
    name="desktop",
    window_width=1024,
    window_height=576,        # 16:9
    min_width=420,
    min_height=320,
    margin_h=28,
    margin_v=22,
    column_gap=32,
    section_gap=16,
    title_pt=26,
    artist_pt=14,
    album_pt=12,
    meta_pt=12,
    play_button=62,
    skip_button=44,
    toggle_button=36,
    volume_icon=30,
    volume_width=150,
    seek_height=22,
    seek_track=5.0,
    seek_handle=7.0,
    wave_height=68,
    wave_fps=60,
    art_stretch=5,
    panel_stretch=6,
    show_album_line=True,
    show_key_hints=True,
    touch_targets=False,
)


# ---------------------------------------------------------------------------
#  PC 좁은 창 — 기존 반응형 동작 유지
# ---------------------------------------------------------------------------

DESKTOP_NARROW = LayoutProfile(
    name="desktop_narrow",
    window_width=480,
    window_height=560,
    min_width=420,
    min_height=320,
    margin_h=20,
    margin_v=16,
    column_gap=16,
    section_gap=12,
    title_pt=18,
    artist_pt=12,
    album_pt=11,
    meta_pt=11,
    play_button=56,
    skip_button=40,
    toggle_button=34,
    volume_icon=28,
    volume_width=120,
    seek_height=20,
    seek_track=5.0,
    seek_handle=7.0,
    wave_height=40,
    wave_fps=60,
    art_stretch=4,
    panel_stretch=5,
    # 세로 배치에서도 아트가 아래로 처지지 않게 살짝 위로.
    art_vertical_bias=0.3,
    show_album_line=True,
    show_key_hints=True,
    touch_targets=False,
)


# ---------------------------------------------------------------------------
#  ESP32 목표 — 480x320 가로
# ---------------------------------------------------------------------------
#
#  이 프로파일이 ESP32 UI의 **설계 도면**이다.
#  실물 없이 PC에서 `python main.py --compact` 로 확인할 수 있다.
#
#  결정 근거:
#    * 세로 320px 중 본문에 쓸 수 있는 건 약 238px.
#      앨범 아트를 정사각형으로 두면 238x238이고, 오른쪽 폭은 약 200px 남는다.
#    * 제목 15pt는 200px 폭에서 한글 약 9자. 대부분의 곡 제목이 잘리므로
#      두 줄까지 허용하고 그 이상은 말줄임한다.
#    * 앨범명 줄은 뺀다. 제목·아티스트가 우선이고 세로가 부족하다.
#    * 웨이브는 28px로 줄인다. 존재감은 남기되 공간을 뺏지 않는다.
#    * 버튼은 터치를 고려해 시각 크기보다 히트 영역을 넓힌다.
#      저항막 터치일 가능성이 높아(펜 동봉) 손가락 정확도가 낮다.
#    * 단축키 안내는 끈다. 물리 버튼/터치 기기에는 키보드가 없다.
#    * 웨이브 fps를 30으로 낮춘다. ESP32는 SPI로 화면을 밀어야 해서
#      60fps 전체 갱신이 불가능하다. PC에서도 같은 값으로 보며 설계한다.
#
COMPACT_480 = LayoutProfile(
    name="compact_480x320",
    window_width=480,
    window_height=320,
    min_width=480,
    min_height=320,
    margin_h=14,
    margin_v=10,
    column_gap=14,
    section_gap=8,
    title_pt=15,
    artist_pt=11,
    album_pt=9,
    meta_pt=9,
    play_button=48,
    skip_button=34,
    toggle_button=30,
    volume_icon=24,
    volume_width=92,
    seek_height=16,
    seek_track=4.0,
    seek_handle=6.0,
    wave_height=28,
    wave_fps=30,
    # 2:3 = 앨범 아트 175px / 정보 패널 263px.
    #
    # 1:1(219/219)로 두면 패널이 17px 모자라 볼륨 슬라이더가 잘려 나간다.
    # 보조 컨트롤 줄에 필요한 폭:
    #   토글 30x3 + 볼륨 아이콘 24 + 볼륨 바 92 + 간격 30 = 236px
    # 2:3이면 263px라 27px 여유가 남는다.
    art_stretch=2,
    panel_stretch=3,
    # 아트는 175x175인데 영역 세로는 약 238px이라 63px이 남는다.
    # 가운데(0.5)에 두면 위아래 31px씩 떠서 오른쪽 곡 제목보다
    # 아트가 아래로 처져 보인다. 0.15면 위쪽 여백이 약 9px로 줄어
    # 곡 정보와 눈높이가 맞는다.
    art_vertical_bias=0.15,
    show_album_line=False,
    show_key_hints=False,
    touch_targets=True,
)


#: 이름으로 찾기
PROFILES: dict[str, LayoutProfile] = {
    p.name: p for p in (DESKTOP, DESKTOP_NARROW, COMPACT_480)
}

#: 이 너비 미만이면 데스크톱에서 좁은 배치로 전환한다 (기존 동작 유지).
NARROW_BREAKPOINT = 700


def profile_for_width(width: int, *, locked: LayoutProfile | None = None) -> LayoutProfile:
    """창 너비에 맞는 프로파일을 고른다.

    Args:
        locked: 고정 프로파일. --compact 로 실행하면 창 크기와 무관하게
            항상 이 프로파일을 쓴다 (ESP32 화면을 흉내 내는 것이므로
            사용자가 창을 키워도 레이아웃이 바뀌면 안 된다).
    """
    if locked is not None:
        return locked
    return DESKTOP_NARROW if width < NARROW_BREAKPOINT else DESKTOP
