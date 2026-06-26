"""YouTube Data API v3 — 공개 통계(조회수) 수집 (API 키, 표준 라이브러리만).

경로 A: 결제 없이 무료 쿼터(10,000 units/일)로 조회수만 읽는다. 자세히는 docs/YOUTUBE_API.md.
키는 .env 의 YOUTUBE_API_KEY 한 곳에만 둔다.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Dict, List

_API = "https://www.googleapis.com/youtube/v3/"
_ID_RE = re.compile(r"(?:shorts/|watch\?v=|v=|youtu\.be/|embed/)([A-Za-z0-9_-]{11})")


def _key() -> str:
    return (os.environ.get("YOUTUBE_API_KEY") or "").strip()


def available() -> bool:
    return bool(_key())


def extract_id(s: str) -> str:
    """URL 또는 11자 영상 ID 문자열에서 videoId 추출."""
    s = (s or "").strip()
    if not s:
        return ""
    m = _ID_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return ""


def _get(endpoint: str, **params) -> dict:
    params["key"] = _key()
    url = _API + endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def fetch_views(video_ids: List[str]) -> Dict[str, int]:
    """영상 ID들의 조회수 {id: viewCount}. 50개씩 묶어 호출(비용 1/호출)."""
    if not available():
        raise RuntimeError("YOUTUBE_API_KEY 미설정 (.env 확인)")
    ids = [i for i in dict.fromkeys(v for v in video_ids if v)]  # 중복 제거·순서 유지
    out: Dict[str, int] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        try:
            d = _get("videos", part="statistics", id=",".join(chunk))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"YouTube API 호출 실패: {e}")
        for v in d.get("items", []):
            out[v["id"]] = int(v.get("statistics", {}).get("viewCount", 0) or 0)
    return out
