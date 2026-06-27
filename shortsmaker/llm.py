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


# ── 쇼츠 전용 프롬프트 ────────────────────────────────────────────────────────

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
        f"{_INDEP}\n"
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
        f"★ 독립성: {_INDEP}\n"
        "★ 중요: 문장 끝맺음(어미)을 줄마다 다르게 섞으세요. '~했죠/~했습니다'만 반복하지 말고 "
        "'~했어요 / ~거든요 / ~인데요 / ~답니다 / ~게 됩니다 / 질문형(?) / 감탄형(!)' 등을 번갈아 쓰고, "
        "같은 어미가 연속으로 나오지 않게 하세요.\n\n"
        "## 반드시 이 형식 그대로(다른 말 금지)\n"
        + fmt
        + f"\n## 제목\n{title}\n\n## 씬 내용\n{briefs}"
        + review
    )
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
    prompt = (
        "당신은 유튜브 쇼츠 후크 카피라이터입니다. 아래 한 장(章)의 내용으로 **MBTI 16유형 각각을 겨냥한** "
        "세로 쇼츠 상단 후크를 만드세요. 같은 장이지만 유형마다 *끌리는 포인트*가 달라야 합니다.\n"
        + mood_rule +
        "- 2줄 형식: 1줄=호기심·도발 질문형(16자 이내), 2줄='끝까지/봐야 한다·보고 싶다'류(16자 이내).\n"
        f"- {_INDEP}\n"
        f"- {_GROUND}\n"
        "- 16개 후크의 표현·소재가 서로 겹치지 않게 하세요.\n\n"
        "## 출력 형식 (유형마다 정확히 한 줄, 다른 말 없이)\n"
        "ENTJ | 1줄 ;; 2줄\n"
        "(16유형: " + ", ".join(_MBTI16) + " 모두)\n\n"
        f"## 제목\n{title}\n\n## 장 내용\n{briefs}"
    )
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
    prompt = (
        f"당신은 유튜브 쇼츠 후크 카피라이터입니다. 아래 한 장(章)의 내용으로 **{mbti.upper()} 유형을 겨냥한** "
        "세로 쇼츠 상단 후크 1개를 새로 제안하세요.\n"
        + (f"- 무드(페르소나): {mood}\n" if mood else "")
        + "- 2줄: 1줄=호기심·도발 질문형(16자 이내), 2줄='끝까지/봐야 한다·보고 싶다'류(16자 이내).\n"
        f"- {_INDEP}\n"
        f"- {_GROUND}\n"
        "- 이전 제안과 다른 새로운 각도·표현으로(다양하게).\n"
        "- 따옴표·설명 없이 아래 형식 한 줄만.\n\n"
        "## 출력 형식 (정확히 한 줄)\n1줄 ;; 2줄\n\n"
        f"## 제목\n{title}\n\n## 장 내용\n{briefs}"
    )
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
    prompt = (
        f"당신은 유튜브 쇼츠 '내레이션 대본' 작가입니다. 아래 장을 **{mbti.upper()} 유형**이 좋아할 톤으로 "
        "씬별 음성 자막(말로 읽힘)을 다시 쓰세요.\n"
        + (f"- 무드(톤): {mood}\n" if mood else "")
        + "- 음성으로 읽히는 구어체 한 문장. 신문 제목·명사 끝맺음 금지. 22~40자.\n"
        f"- {_INDEP}\n"
        "- ★ 사실은 각 씬 원본 내용에 충실 — 없는 사실 추가·왜곡 금지. 무드는 어조·표현에만.\n"
        "- 핵심 소재·고유명사는 원본 단어로(어려우면 쉬운 일반어로 풀되, 원본에 없는 새 소재어는 만들지 말 것).\n"
        "- 어미를 줄마다 다양하게(~했어요/~거든요/~인데요/~답니다/질문형/감탄형).\n"
        f"- 마지막 씬({last_idx})은 '전체 영상은 설명란에서' 류 CTA를 그 톤으로.\n\n"
        "## 출력 형식 (씬마다 정확히 한 줄, 다른 말 없이)\n씬N: 자막\n\n"
        f"## 제목\n{title}\n\n## 씬 내용\n{items}"
    )
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
    prompt = (
        "당신은 역사 콘텐츠 '사실 검증 편집자'입니다. 각 씬의 [원본]과 [자막]을 대조해 사실 정확성을 판단하세요.\n"
        "- 자막이 원본 사실을 왜곡하거나 오해를 줄 소지가 있으면 NG, 정확하면 OK.\n"
        "- 평가/이유는 아주 짧게(한 구절, 설명 길게 X).\n"
        "- 그리고 원본에 충실하고 사실에 맞는 구어체 대안 문장을 2~3개 제시(NG면 고친 문장, OK면 더 나은 표현).\n"
        f"- {_INDEP}\n\n"
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
    prompt = (
        "아래 세로 쇼츠의 씬별 음성 자막을 전체적으로 다듬어 다시 쓰세요.\n"
        f"1) {_INDEP}\n"
        "2) 전체 흐름·중복을 정리하되 씬 순서는 그대로 둡니다. 비약 없이 자연스럽게.\n"
        "3) ★ 사실은 각 씬의 [원본]에 충실하게 — 원본에 없는 사실·관계를 추가하거나 바꾸지 마세요(왜곡 금지).\n"
        "4) 구어체, 한 문장, 22~40자. 어미는 줄마다 다양하게.\n\n"
        "## 출력 형식 (씬마다 정확히 한 줄, 다른 말 없이)\n"
        "씬N: 다시 쓴 자막\n\n"
        + items
    )
    raw = complete(prompt, max_tokens=1500)
    out: dict = {}
    for line in (raw or "").splitlines():
        m = re.match(r"^씬\s*(\d+)\s*[:：]\s*(.+)$", line.strip())
        if m:
            out[int(m.group(1))] = m.group(2).strip()
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
