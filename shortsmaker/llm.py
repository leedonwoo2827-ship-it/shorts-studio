"""쇼츠 앱 LLM 헬퍼 — 백엔드 자동 분기 + 쇼츠 전용 프롬프트.

- 영상공방 백엔드(LLM_BRIDGE_DIR/venv + services)가 있으면 → 그쪽 OAuth LLM/TTS 를 브리지(llm_kit).
- 없으면 → **내장 codex/agy 직접 호출**(cli_llm)로 폴백. (그 그룹은 codex/agy CLI 설치+로그인만 하면 됨)
둘 다 없으면 available()=False → AI 기능은 조용히 비활성, 렌더는 정상.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# SHORTS_VODSTUDIO_DIR → 키트 표준 LLM_BRIDGE_DIR 매핑
_vod = os.environ.get("SHORTS_VODSTUDIO_DIR")
if _vod and not os.environ.get("LLM_BRIDGE_DIR"):
    os.environ["LLM_BRIDGE_DIR"] = _vod

from . import cli_llm  # noqa: E402  내장 폴백
from . import llm_kit  # noqa: E402  영상공방 브리지

LLMUnavailable = llm_kit.LLMUnavailable

# 모든 자막 생성 공통: 독립 완결 문장 원칙(씬 간 의존 제거 → 흐름 수렴)
_INDEP = ("각 자막은 그 자체로 완결된 독립 문장입니다. 주어와 서술어를 갖추고, 앞/뒤 씬을 가리키는 "
          "접속어·지시어('이에 맞서·뒤이어·그래서·결국·그·이·저·이런·이렇게' 등)에 의존하지 마세요. "
          "어떤 순서로 읽어도 그 문장 하나만으로 이해돼야 합니다.")
# 단어 그라운딩(RAG처럼): 무드를 입히되 소재·고유명사는 원본에서만. '파티' 류 환각 방지.
_GROUND = ("★ 단어는 원본 근거(RAG처럼): 핵심 소재·고유명사·사실 단어는 원본 내레이션에 실제로 나온 것만 쓰세요. "
           "어려운 용어는 일반적이고 쉬운 말로 풀어 써도 되지만(뜻은 유지), 원본에 없는 새 소재·고유명사"
           "(예: '파티·축제·콘서트' 등)를 지어내지 마세요. 무드는 어조·에너지(어미·문형)로만 표현하세요.")
__all__ = ["LLMUnavailable", "available", "status", "complete", "set_provider", "logout",
           "login_cmd", "launch_login", "list_models", "get_model", "set_model",
           "suggest_hook", "suggest_caption", "gen_fill", "verify_captions", "tidy_all",
           "gen_mbti_hooks", "gen_one_mbti_hook", "gen_mbti_captions", "shorts_meta"]


def _use_bridge() -> bool:
    return llm_kit.backend_available()


# ── 상태/계정 (자동 분기) ─────────────────────────────────────────────────────
def status(use_cache: bool = True) -> dict:
    if _use_bridge():
        s = llm_kit.status(use_cache)
        if s.get("ready") or s.get("provider"):
            return s
    return cli_llm.status()


def available() -> bool:
    return bool(status(False).get("ready"))


def set_provider(name: str) -> dict:
    if _use_bridge():
        return llm_kit.set_provider(name)
    os.environ["LLM_PROVIDER"] = name      # 내장: 런타임 공급자 변경(.env 로 기본값 지정)
    return {"ok": True, "status": cli_llm.status()}


def logout(provider: str | None = None) -> dict:
    if _use_bridge():
        return llm_kit.logout(provider)
    # 내장: codex 는 logout, agy 는 미지원
    prov = provider or cli_llm.status().get("provider")
    if prov == "codex":
        try:
            subprocess.run([(cli_llm._codex_path() or "codex"), "logout"],
                           capture_output=True, timeout=20)
        except Exception:
            pass
    return {"ok": True, "provider": prov}


def login_cmd(provider: str | None = None) -> dict:
    if _use_bridge():
        return llm_kit.login_cmd(provider)
    cmd = cli_llm.login_cmd(provider)
    return {"provider": provider or cli_llm.status().get("provider"), "cmd": cmd}


def launch_login(provider: str | None = None) -> dict:
    if _use_bridge():
        return llm_kit.launch_login(provider)
    cmd = cli_llm.login_cmd(provider)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", *cmd])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Terminal", cmd[0]])
        else:
            subprocess.Popen(cmd)
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"로그인 터미널 실행 실패: {e}")
    return {"ok": True, "provider": provider, "cmd": cmd}


def list_models() -> list:
    return llm_kit.list_models() if _use_bridge() else cli_llm.list_models()


def get_model() -> str:
    return llm_kit.get_model() if _use_bridge() else cli_llm.get_model()


def set_model(name: str) -> dict:
    return llm_kit.set_model(name) if _use_bridge() else cli_llm.set_model(name)


def complete(prompt: str, *, max_tokens: int = 800) -> str:
    if _use_bridge():
        return llm_kit.complete(prompt, max_tokens=max_tokens)
    try:
        return cli_llm.complete(prompt, max_tokens=max_tokens)
    except LLMUnavailable:
        raise
    except Exception as e:  # noqa: BLE001
        raise LLMUnavailable(f"LLM 호출 실패: {e}")


# ── 쇼츠 전용 프롬프트 (템플릿은 prompts/ 폴더, _prompt 로 로드) ──────────────
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


def _prompt(name: str, **vars) -> str:
    """prompts/<name>.md 를 읽어 {토큰}을 치환. 공통 규칙({indep},{ground})은 자동 주입."""
    text = (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    vars.setdefault("indep", _INDEP)
    vars.setdefault("ground", _GROUND)
    for k, v in vars.items():
        text = text.replace("{" + k + "}", "" if v is None else str(v))
    return text


def suggest_hook(narration: str, current: str = "") -> str:
    cur = f"[현재 문구]\n{current}\n\n" if current.strip() else ""
    return complete(_prompt("hook", current=cur, narration=narration[:600]), max_tokens=80)


def suggest_caption(narration: str, current: str = "") -> str:
    cur = f"[현재 문구]\n{current}\n\n" if current.strip() else ""
    return complete(_prompt("caption", current=cur, narration=narration[:600]), max_tokens=90)


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
    prompt = _prompt("fill", fmt=fmt, title=title, briefs=briefs, review=review)
    return _parse_fill(complete(prompt, max_tokens=1000))


_MBTI16 = ["ISTJ", "ISFJ", "INFJ", "INTJ", "ISTP", "ISFP", "INFP", "INTP",
           "ESTP", "ESFP", "ENFP", "ENTP", "ESTJ", "ESFJ", "ENFJ", "ENTJ"]


def gen_mbti_hooks(title: str, scenes: list, moods: dict | None = None) -> dict:
    """한 장(章)의 내레이션을 근거로 MBTI 16유형을 각각 겨냥한 쇼츠 후크를 1회 호출로 생성.

    scenes: [{scene_index, narration|subtitle}]. moods: {MBTI: '무드 한 줄'} (미리 정의한 페르소나).
    반환: {"ENTJ": {"line1":..., "line2":...}, ...}.
    각 후크 2줄(1줄=검정 질문/도발형, 2줄=주황 '봐야 한다'형, 각 16자 이내), 유형 간 표현 중복 금지.
    """
    briefs = "\n".join(f"씬{s.get('scene_index')}: {(s.get('narration') or s.get('subtitle') or '')[:160]}"
                       for s in scenes)
    if moods:
        mood_block = "\n".join(f"- {m}: {moods.get(m, '')}" for m in _MBTI16 if moods.get(m))
        mood_rule = ("- 각 유형의 후크는 아래 **무드(페르소나)**에 맞춰 1번 후크의 '미끼'와 어조를 다르게 잡으세요:\n"
                     + mood_block + "\n")
    else:
        mood_rule = ("- 각 유형의 동기/관심사에 맞춰 1번 후크의 '미끼'를 다르게: 예) 분석형(NT)=원리·왜, "
                     "이상형(NF)=의미·사람, 관리형(SJ)=순서·교훈, 모험형(SP)=장면·반전.\n")
    prompt = _prompt("mbti_hooks", mood_rule=mood_rule, mbti_list=", ".join(_MBTI16),
                     title=title, briefs=briefs)
    raw = complete(prompt, max_tokens=1400)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^\s*([IEie][NSns][TFtf][JPjp])\s*[|｜](.+)$", line.strip())
        if not m:
            continue
        mbti = m.group(1).upper()
        parts = [p.strip() for p in re.split(r";;|；；", m.group(2)) if p.strip()]
        if not parts:
            continue
        out[mbti] = {"line1": parts[0], "line2": (parts[1] if len(parts) > 1 else "")}
    return out


def gen_one_mbti_hook(title: str, scenes: list, mbti: str, mood: str = "") -> dict:
    """한 장 + 한 MBTI(무드)로 후크 1개를 새로 제안. 반복 호출 시 다른 각도로. 반환 {line1, line2}."""
    briefs = "\n".join(f"씬{s.get('scene_index')}: {(s.get('narration') or s.get('subtitle') or '')[:160]}"
                       for s in scenes)
    mood_line = f"- 무드(페르소나): {mood}\n" if mood else ""
    prompt = _prompt("mbti_hook_one", mbti=mbti.upper(), mood_line=mood_line, title=title, briefs=briefs)
    raw = complete(prompt, max_tokens=120)
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in re.split(r";;|；；", line.strip()) if p.strip()]
        if parts:
            return {"line1": parts[0], "line2": (parts[1] if len(parts) > 1 else "")}
    return {"line1": (raw or "").strip().split("\n")[0][:16], "line2": ""}


def gen_mbti_captions(title: str, scenes: list, mbti: str, mood: str = "") -> dict:
    """한 장 + MBTI 무드로 씬별 음성 자막(구어체 대본)을 재생성. scenes:[{scene_index,narration}].
    반환 {idx: caption}. 무드 톤을 입히되 원본 내레이션에 충실(사실 변경 금지), 독립 완결 문장."""
    last_idx = scenes[-1]["scene_index"] if scenes else 0
    items = "\n".join(
        f"씬{s.get('scene_index')}: {(s.get('narration') or s.get('subtitle') or '')[:200]}"
        for s in scenes)
    mood_line = f"- 무드(톤): {mood}\n" if mood else ""
    prompt = _prompt("mbti_captions", mbti=mbti.upper(), mood_line=mood_line,
                     last_idx=last_idx, title=title, items=items)
    raw = complete(prompt, max_tokens=1100)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^씬\s*(\d+)\s*[:：]\s*(.+)$", line.strip())
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def verify_captions(scenes: list) -> dict:
    items = "\n\n".join(
        f"[씬{s['scene_index']}]\n원본: {(s.get('narration') or '')[:220]}\n자막: {s.get('caption') or ''}"
        for s in scenes)
    raw = complete(_prompt("verify", items=items), max_tokens=1300)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^씬\s*(\d+)\s*[|｜](.+)$", line.strip())
        if not m:
            continue
        idx = int(m.group(1))
        parts = [p.strip() for p in m.group(2).split("|")]
        status_ = (parts[0] if parts else "").upper()
        reason = parts[1] if len(parts) > 1 else ""
        alts_str = parts[2] if len(parts) > 2 else ""
        alts = [a.strip() for a in re.split(r";;|；；", alts_str) if a.strip()]
        out[idx] = {"ok": status_.startswith("OK"), "reason": reason, "alts": alts}
    return out


def tidy_all(title: str, scenes: list) -> dict:
    """모든 자막을 원본 근거로 1회 재작성 — 독립 완결 문장 + 흐름·중복 정리, 사실 변경 금지.

    scenes: [{scene_index, narration, caption}]. 반환: {idx: 새 자막}.
    개별 패치(접속어 의존) 루프 대신 전체를 한 번에 일관 재작성 → 흐름이 수렴한다.
    """
    items = "\n\n".join(
        f"[씬{s['scene_index']}]\n원본: {(s.get('narration') or '')[:240]}\n현재: {s.get('caption') or ''}"
        for s in scenes)
    raw = complete(_prompt("tidy", items=items), max_tokens=1500)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^씬\s*(\d+)\s*[:：]\s*(.+)$", line.strip())
        if m:
            out[int(m.group(1))] = m.group(2).strip()
    return out


def shorts_meta(script_or_beats: str, original_url: str = "", title_hint: str = "") -> str:
    link = (original_url or "").strip() or "(원본 영상 링크)"
    title_hint_block = f"## 제목 힌트\n{title_hint}\n\n" if title_hint.strip() else ""
    return complete(_prompt("meta", link=link, title_hint_block=title_hint_block,
                            content=script_or_beats[:6000]), max_tokens=700)
