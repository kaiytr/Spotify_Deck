"""레이아웃 프로파일.

화면 크기별 치수를 한곳에 모은다. 위젯 코드에 숫자를 흩뿌리지 않으면
ESP32 UI를 만들 때 "PC에서는 어떤 크기였지?"를 이 파일 하나로 답할 수 있다.

    DESKTOP        기존 PC UI. 지금까지의 모습 그대로 유지한다.
    COMPACT_480    ESP32 목표 해상도(480x320)의 기준 설계.
                   PC에서 `--compact` 로 띄워 실물 없이 확인할 수 있다.

두 프로파일은 **같은 세로 스택 구조**를 쓰고 치수만 다르다.
구조가 하나면 ESP32로 옮길 때 "PC는 이렇게 생겼는데 기기는 왜 다르지?"가 없다.

────────────────────────────────────────────────────────────────
 화면 구조 (Spotify Deck 기준 디자인)
────────────────────────────────────────────────────────────────

  ┌──────────────────────────────────────────────┐
  │ ● 연결됨                    기기명 · 컴퓨터   │  상단바
  │                                              │
  │ ┌────────┐  Sunset Lover                     │
  │ │        │  Petit Biscuit                    │  미디어 블록
  │ │  ART   │  SUNSET LOVER                     │  (아트 + 정보 + 웨이브)
  │ │        │  ▁▃▅▇▅▃▁▂▄▆▄▂                    │
  │ └────────┘                                   │
  │                                              │
  │ ━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━━━━━━━━   │  진행 바 (전체 폭)
  │ 1:42                                    3:58 │  시간
  │                                              │
  │    ♡    ⤨    ◀    ( ▶ )    ▶▶    ⟲        │  컨트롤 한 줄
  │              🔊 ━━━━━━━━━                    │  볼륨
  └──────────────────────────────────────────────┘

 핵심 결정:
   * 앨범 아트를 **작게** 두고 곡 정보 옆에 붙인다.
     크게 두면 480x320에서 화면의 절반을 먹어 나머지가 눌린다.
   * 진행 바는 **전체 폭**을 쓴다. 터치로 잡기 쉽고 시각적 기준선이 된다.
   * 컨트롤 6개를 **한 줄에 균등 배치**한다.
     두 줄로 나누면 세로를 더 먹고 시선이 흩어진다.
   * 볼륨은 별도 줄. 기준 디자인은 '⋯' 메뉴 뒤에 숨기지만
     이 앱에는 메뉴가 없고 볼륨이 필수 기능이므로 드러낸다.
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

    art_size: int = 0
    """앨범 아트 한 변 (논리 픽셀). 0이면 열 비율에서 계산한다(구형 2열 배치)."""

    show_volume: bool = True
    """볼륨 아이콘과 슬라이더를 화면에 표시할지.

    기기 버전에서는 끈다. 로터리 엔코더가 볼륨을 담당하므로 화면에
    슬라이더를 둘 이유가 없고, 그만큼 앨범 아트를 키울 수 있다.
    PC에는 엔코더가 없어 마우스로 조절할 수단이 필요하므로 켠다.
    (어느 쪽이든 위/아래 방향키는 항상 동작한다)
    """

    toggles_under_art: bool = False
    """셔플·반복·좋아요를 앨범 아트 **아래**에 놓을지.

    좁은 화면에서는 오른쪽 패널의 마지막 줄에 토글 3개와 볼륨을 함께 넣으면
    토글이 왼쪽 끝, 볼륨이 오른쪽 끝으로 밀려 시선이 멀어진다.
    아트가 정사각형이라 아래에 남는 공간이 생기므로 거기로 옮기면
    빈 공간도 쓰고 버튼도 화면 가운데 가까이 온다.
    """

    @property
    def art_edge(self) -> int:
        """앨범 아트 한 변의 길이 (논리 픽셀). 아트는 정사각형이다."""
        if self.art_size:
            return self.art_size
        # 구형 2열 배치용 폴백 (열 비율에서 계산)
        body = self.window_width - self.margin_h * 2 - self.column_gap
        return body * self.art_stretch // (self.art_stretch + self.panel_stretch)

    @property
    def control_row_width(self) -> int:
        """컨트롤 줄 7개가 차지하는 폭.

        좋아요 · 셔플 · 이전 · 재생 · 다음 · 반복 · 더보기
        """
        return (
            self.toggle_button * 4      # 좋아요, 셔플, 반복, 더보기
            + self.skip_button * 2      # 이전, 다음
            + self.play_button          # 재생
        )

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
    volume_width=260,
    seek_height=22,
    seek_track=5.0,
    seek_handle=7.0,
    wave_height=68,
    wave_fps=60,
    art_stretch=5,
    panel_stretch=6,
    art_size=260,
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
    volume_width=200,
    seek_height=20,
    seek_track=5.0,
    seek_handle=7.0,
    wave_height=40,
    wave_fps=60,
    art_stretch=4,
    panel_stretch=5,
    art_size=150,
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
    # 재생 버튼만 48px를 유지하고 나머지는 키웠다.
    # 4인치 실물 기준 터치 크기:
    #   재생 48px = 8.5mm, 이전/다음 42px = 7.4mm (권장 7~9mm 충족)
    #   토글 38px = 6.7mm — 아직 살짝 작지만 간격 41px로 오조작은 적다
    title_pt=17,
    artist_pt=13,
    album_pt=11,
    meta_pt=11,
    play_button=48,
    skip_button=42,
    toggle_button=38,
    volume_icon=28,
    volume_width=170,
    seek_height=20,
    seek_track=6.0,
    seek_handle=8.0,
    wave_height=34,
    wave_fps=30,
    # 2:3 = 앨범 아트 175px / 정보 패널 263px.
    #
    # 1:1(219/219)로 두면 패널이 17px 모자라 볼륨 슬라이더가 잘려 나간다.
    # 보조 컨트롤 줄에 필요한 폭:
    #   토글 30x3 + 볼륨 아이콘 24 + 볼륨 바 92 + 간격 30 = 236px
    # 2:3이면 263px라 27px 여유가 남는다.
    art_stretch=2,
    panel_stretch=3,
    # 진행 바가 미디어 블록 안(오른쪽 열)으로 들어가면서 세로 예산이 바뀌었다.
    #   마진20 + 상단바20 + 간격8 + 아트 + 간격8 + 컨트롤48 = 104 + 아트
    #   320 - 104 = 216 까지 가능하다.
    # 160으로 두면 블록 아래에 62px이 비어 컨트롤과 크게 벌어진다.
    # 200으로 키워 그 공간을 아트와 오른쪽 열이 쓰게 한다.
    art_size=200,
    # 기기에는 로터리 엔코더가 있으므로 화면 볼륨 슬라이더를 뺀다.
    show_volume=False,
    show_album_line=True,
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
