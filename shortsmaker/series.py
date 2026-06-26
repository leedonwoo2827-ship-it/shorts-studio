"""시리즈 경로/활성 시리즈 관리 (표준 라이브러리만).

한 루트(`SHORTS_SERIES_ROOT`) 아래 시리즈명별 `input/output` 폴더로 자산을 분리한다.
    <SERIES_ROOT>/<series>/input/   chNN_bundle ...
    <SERIES_ROOT>/<series>/output/  렌더 결과
활성 시리즈는 `<project>/data/active_series.txt` 한 값으로 기록한다(캠페인 카드에서 전환).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Optional

_PROJECT = Path(__file__).resolve().parent.parent
_DATA = _PROJECT / "data"
_ACTIVE_FILE = _DATA / "active_series.txt"


def series_root() -> Optional[Path]:
    raw = (os.environ.get("SHORTS_SERIES_ROOT") or "").strip()
    return Path(raw) if raw else None


def slugify(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_-]+", "-", (name or "").strip()).strip("-_")
    return s or "series"


def list_series() -> List[str]:
    """input 폴더를 가진 시리즈명 목록."""
    root = series_root()
    if not root or not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if d.is_dir() and (d / "input").is_dir())


def active_series() -> str:
    """활성 시리즈명. 파일이 없으면 첫 시리즈로 폴백(없으면 '')."""
    try:
        if _ACTIVE_FILE.exists():
            val = _ACTIVE_FILE.read_text(encoding="utf-8").strip()
            if val:
                return val
    except Exception:
        pass
    avail = list_series()
    return avail[0] if avail else ""


def set_active(name: str) -> str:
    name = (name or "").strip()
    _DATA.mkdir(exist_ok=True)
    _ACTIVE_FILE.write_text(name, encoding="utf-8")
    return name


def input_dir(series: Optional[str] = None) -> Optional[Path]:
    root = series_root()
    s = (series or active_series()).strip()
    if not root or not s:
        return None
    return root / s / "input"


def output_dir(series: Optional[str] = None) -> Optional[Path]:
    root = series_root()
    s = (series or active_series()).strip()
    if not root or not s:
        return None
    d = root / s / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d
