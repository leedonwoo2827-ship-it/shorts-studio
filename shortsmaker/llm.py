"""쇼츠 앱 LLM 헬퍼 — 재사용 키트(llm_kit) 위에 쇼츠 전용 프롬프트만 얹은 얇은 래퍼.

브리지/계정관리(상태·공급자전환·로그인·로그아웃)는 전부 `llm_kit` 가 담당한다.
키트는 OAuth 백엔드(영상공방 services.llm_backend, codex/agy)를 그 venv 로 호출한다.
이 앱에선 SHORTS_VODSTUDIO_DIR 로 백엔드 경로를 지정 → 키트의 LLM_BRIDGE_DIR 로 매핑.
"""
from __future__ import annotations

import os
import re

# 이 앱의 설정 이름(SHORTS_VODSTUDIO_DIR)을 키트 표준(LLM_BRIDGE_DIR)으로 매핑
_vod = os.environ.get("SHORTS_VODSTUDIO_DIR")
if _vod and not os.environ.get("LLM_BRIDGE_DIR"):
    os.environ["LLM_BRIDGE_DIR"] = _vod

from .llm_kit import (  # noqa: E402  (재노출)
    LLMUnavailable, available, complete, launch_login, login_cmd, logout,
    set_provider, status,
)

__all__ = ["LLMUnavailable", "available", "complete", "launch_login", "login_cmd",
           "logout", "set_provider", "status", "suggest_hook", "suggest_caption",
           "shorts_meta"]


# ----- 쇼츠 전용 프롬프트 -----

def suggest_hook(narration: str, current: str = "") -> str:
    return complete(
        "다음 장면 내레이션으로 세로 쇼츠 상단 후크를 만들어 주세요.\n"
        "2줄로: 1줄은 호기심·도발 질문형(16자 이내), 2줄은 '봐야 한다/보고 싶다' 류(16자 이내).\n"
        "두 줄을 줄바꿈으로 구분하고, 따옴표·설명 없이 문구만 출력.\n\n"
        + (f"[현재 문구]\n{current}\n\n" if current.strip() else "")
        + f"[내레이션]\n{narration[:600]}",
        max_tokens=80,
    )


def suggest_caption(narration: str, current: str = "") -> str:
    return complete(
        "다음 장면을 세로 쇼츠에서 '말하듯' 들려줄 구어체 나레이션 한 문장으로 만들어 주세요.\n"
        "신문 제목·명사 끝맺음 금지(예: '~크리스트교' X). 사람이 말하듯 완결된 구어체 문장으로, "
        "어미는 '~했어요/~거든요/~인데요/~답니다/질문형/감탄형' 등에서 자연스럽게 골라 22~40자.\n"
        "따옴표·설명 없이 문구만 출력.\n\n"
        + (f"[현재 문구]\n{current}\n\n" if current.strip() else "")
        + f"[내레이션]\n{narration[:600]}",
        max_tokens=90,
    )


def _parse_fill(text: str) -> dict:
    out = {"hook1": "", "hook2": "", "hashtags": "", "captions": {}}
    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r"^후크1\s*[:：]\s*(.+)$", line)
        if m:
            out["hook1"] = m.group(1).strip(); continue
        m = re.match(r"^후크2\s*[:：]\s*(.+)$", line)
        if m:
            out["hook2"] = m.group(1).strip(); continue
        m = re.match(r"^해시?태그\s*[:：]\s*(.+)$", line)
        if m:
            out["hashtags"] = m.group(1).strip(); continue
        m = re.match(r"^씬\s*(\d+)\s*[:：]\s*(.+)$", line)
        if m:
            out["captions"][int(m.group(1))] = m.group(2).strip()
    return out


def gen_fill(title: str, scenes: list, review_of: dict | None = None,
             only: str | None = None) -> dict:
    """쇼츠 후크·해시태그·씬별 음성자막 생성. only='hook'|'captions'|None(전체).

    only='hook' → 후크/해시태그만, only='captions' → 씬 자막만 생성(포커스·빠름).
    """
    want_hook = only in (None, "hook")
    want_caps = only in (None, "captions")
    briefs = "\n".join(f"씬{s['scene_index']}: {(s.get('narration') or s.get('subtitle') or '')[:160]}"
                       for s in scenes)
    review = ""
    if review_of:
        cur = []
        if want_hook:
            cur += [f"후크1: {review_of.get('hook1','')}", f"후크2: {review_of.get('hook2','')}",
                    f"해시태그: {review_of.get('hashtags','')}"]
        if want_caps:
            for k, v in (review_of.get("captions") or {}).items():
                cur.append(f"씬{k}: {v}")
        if cur:
            review = ("\n\n## 아래는 1차 초안입니다. 더 강하고 입에 붙게, 중복 제거하고 최종 다듬으세요.\n"
                      + "\n".join(cur))

    fmt = ""
    if want_hook:
        fmt += ("후크1: (검정으로 나갈 1줄, 호기심·도발 질문형, 16자 이내)\n"
                "후크2: (주황으로 나갈 1줄, '보고 싶다/봐야 한다' 류, 16자 이내)\n"
                "해시태그: 콘텐츠 키워드 위주 7~8개. '#쇼츠'처럼 일반·플랫폼 태그는 넣지 말 것 (하단 2줄 분량)\n")
    if want_caps:
        last_idx = scenes[-1]["scene_index"] if scenes else 0
        for s in scenes:
            if s["scene_index"] == last_idx and len(scenes) > 1:
                fmt += (f"씬{s['scene_index']}: (마지막 — 시청자에게 '전체 영상은 설명란에서 "
                        "만나보세요' 류의 CTA를 말하듯 한 문장, 구어체)\n")
            else:
                fmt += (f"씬{s['scene_index']}: (이 씬을 말하듯 들려주는 구어체 나레이션 한 문장. "
                        "제목·명사 나열 금지, 완결된 문장, 22~40자)\n")

    prompt = (
        "당신은 유튜브 쇼츠 '내레이션 대본' 작가입니다. 아래 씬들로 세로 쇼츠용 문구를 만드세요.\n"
        "후크는 끝까지 보게 만드는 강한 한 방(짧게). 씬 자막은 **음성으로 읽히는 구어체 나레이션**이라 "
        "신문 제목처럼 명사로 끝내지 말고, 사람이 말하듯 완결된 문장으로 쓰세요.\n"
        "★ 중요: 문장 끝맺음(어미)을 줄마다 다르게 섞으세요. '~했죠/~했습니다'만 반복하지 말고 "
        "'~했어요 / ~거든요 / ~인데요 / ~답니다 / ~게 됩니다 / 질문형(?) / 감탄형(!)' 등을 번갈아 쓰고, "
        "같은 어미가 연속으로 나오지 않게 하세요.\n\n"
        "## 반드시 이 형식 그대로(다른 말 금지)\n"
        + fmt
        + f"\n## 제목\n{title}\n\n## 씬 내용\n{briefs}"
        + review
    )
    return _parse_fill(complete(prompt, max_tokens=1000))


def verify_captions(scenes: list) -> dict:
    """각 씬의 [원본 내레이션] 대비 [현재 자막]의 사실 정확성 점검 + 대안 제시.

    scenes: [{scene_index, narration, caption}].
    반환: {idx: {ok: bool, reason: 짧은평가, alts: [사실에 맞는 대안문장,...]}}.
    """
    items = "\n\n".join(
        f"[씬{s['scene_index']}]\n원본: {(s.get('narration') or '')[:220]}\n자막: {s.get('caption') or ''}"
        for s in scenes)
    prompt = (
        "당신은 역사 콘텐츠 '사실 검증 편집자'입니다. 각 씬의 [원본]과 [자막]을 대조해 사실 정확성을 판단하세요.\n"
        "- 자막이 원본 사실을 왜곡하거나 오해를 줄 소지가 있으면 NG, 정확하면 OK.\n"
        "- 평가/이유는 아주 짧게(한 구절, 설명 길게 X).\n"
        "- 그리고 원본에 충실하고 사실에 맞는 구어체 대안 문장을 2~3개 제시(NG면 고친 문장, OK면 더 나은 표현).\n\n"
        "## 출력 형식 (씬마다 정확히 한 줄, 다른 말 없이)\n"
        "씬N | OK 또는 NG | 짧은 평가나 이유 | 대안1 ;; 대안2 ;; 대안3\n\n"
        + items
    )
    raw = complete(prompt, max_tokens=1300)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^씬\s*(\d+)\s*[|｜](.+)$", line.strip())
        if not m:
            continue
        idx = int(m.group(1))
        parts = [p.strip() for p in m.group(2).split("|")]
        status = (parts[0] if parts else "").upper()
        reason = parts[1] if len(parts) > 1 else ""
        alts_str = parts[2] if len(parts) > 2 else ""
        alts = [a.strip() for a in re.split(r";;|；；", alts_str) if a.strip()]
        out[idx] = {"ok": status.startswith("OK"), "reason": reason, "alts": alts}
    return out


def shorts_meta(script_or_beats: str, original_url: str = "", title_hint: str = "") -> str:
    link = (original_url or "").strip() or "(원본 영상 링크)"
    return complete(
        "당신은 유튜브 쇼츠 카피라이터입니다. 아래 내용으로 30초 세로 쇼츠 업로드 메타데이터를 "
        "한국어로 작성하세요.\n\n## 출력 형식\n"
        "제목: (40자 이내, 강한 후크 + #shorts)\n"
        f"설명: (3~4줄. 첫 줄 후크, 그 다음 줄에 '▶ 전체 영상 보기: {link}', 마지막 줄 해시태그 3~5개)\n"
        "태그: (쉼표로 10~12개)\n"
        "고정댓글: (원본 영상 유도 한 줄, 위 링크 포함)\n\n"
        + (f"## 제목 힌트\n{title_hint}\n\n" if title_hint.strip() else "")
        + f"## 내용\n{script_or_beats[:6000]}",
        max_tokens=700,
    )
