"""Windows 콘솔 한글 출력 보정.

Windows 기본 콘솔 코드페이지는 한국어 환경에서 cp949다.
cp949는 '—'(em dash) 같은 문자를 인코딩하지 못해
print() 한 줄이 UnicodeEncodeError로 프로그램 전체를 죽인다.

이 모듈은 콘솔 출력 코드페이지를 UTF-8(65001)로 바꾸고
stdout/stderr를 UTF-8로 재설정해 한글이 깨지지 않게 한다.

CLI 진입점(main.py, doctor.py)에서 가장 먼저 호출한다.
GUI(Qt)는 내부적으로 유니코드를 쓰므로 영향을 받지 않는다.
"""

from __future__ import annotations

import sys


def enable_utf8_console() -> None:
    """콘솔을 UTF-8로 전환한다. 실패해도 예외를 던지지 않는다."""
    if sys.platform == "win32":
        try:
            import ctypes

            # 65001 = UTF-8 코드페이지
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - 콘솔이 없는 환경(pythonw)에서는 무시
            pass

    for stream in (sys.stdout, sys.stderr):
        # 파이프로 리다이렉트된 경우 reconfigure가 없을 수 있다.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # errors='replace': 그래도 못 쓰는 문자가 있으면 죽지 말고 '?'로 대체
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
