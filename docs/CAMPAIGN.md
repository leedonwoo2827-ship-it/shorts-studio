# MBTI 후크 캠페인 — 사용 시나리오 & 스케줄

장(章) × MBTI 16유형으로 쇼츠를 무중복 발행하고, 조회수로 "어떤 유형/장이 잘 맞나"를 본다.
구현: [shortsmaker/campaign.py](../shortsmaker/campaign.py) · [llm.py](../shortsmaker/llm.py) · 캠페인 탭 UI.

## 용어 — 무드 vs 톤·내용
- **무드(mood)** = MBTI 16유형별 *지속 페르소나/분위기*. **미리 1회 정의·저장**하고 모든 장에 재사용.
  (예: ESTP=짜릿한 반전 / INTJ=냉철한 분석 / ENFP=설레는 가능성)
- **톤·내용** = 그날 (장·MBTI) 한 건의 실제 후크 표현·자막. **매일** 그 무드를 따라 다듬어 확정.

## 사용 시나리오
### A. 최초 1회 — 셋업
1. [캠페인] 탭 → 시리즈 선택(상단 드롭다운).
2. **🎭 무드 가이드** → 16유형 무드 확인/수정 → **저장**. (기본값 제공, 언제든 수정 가능)

### B. 장별 1회 — 후크 준비
3. 장 선택 → **✨ 16유형 후크 생성** → 그 장 16행이 채워짐(각 무드 반영, 원본 내레이션 근거).
4. 마스터 리스트에서 후크 인라인 검토·수정(필요 시).

### C. 매일 — 발행 루프
5. **⤵ 다음 미생산으로** → 오늘의 (장·MBTI) 행에서 **[구성]**.
6. [제작] 탭으로 이동 + 상단 **빌드 배너 "N장 · MBTI · 무드"** 표시 → 무드 따라 **톤·내용(자막) 정리**
   → 🔎 검토 → 🎙️ 음성 → 🎬 렌더(완료 시 자동 '생산' 기록, 출력은 `_series/<시리즈>/output`).
7. 유튜브 발행 → 행 **YouTube URL/ID 칸**에 붙여넣기 → **📊 조회수 갱신** → **💡 인사이트**(MBTI/장 평균).

### 행 색 상태 (한눈에)
- **흰색** = 후크 없음(구성 잠금) · **노랑** = 후크 준비됨(구성 활성) · **다크 네이비** = 생산 완료(후크·구성 잠금, YT칸만 열림).

## 무중복 일일 스케줄 (라운드 방식)
- **한 라운드 = 한 MBTI로 장 1→N(=17)을 쭉**(17일). 다음 라운드에 다음 MBTI. 16라운드 = **16×17 = 272일**.
- 공식: `Day d → 장=chapters[(d-1)%N]`, `라운드 r=(d-1)//N`, `MBTI=mbti_order[r%16]`.
- Day1 = 1장·(1번 MBTI), Day17 = 17장·(1번 MBTI), Day18 = 1장·(2번 MBTI) → **Day18 ≠ Day1**(같은 장·다른 MBTI).
- 무중복 보장: 각 (장,MBTI)은 정확히 1회. 진실 원천은 `slot` UNIQUE 제약 + "다음 미생산" 자동 advance.

## MBTI 라운드 진행 순서 (기본값·근거)
앞쪽일수록 **초반 조회수가 잘 나올 가능성**이 높은 유형(도달·소구 우선). 16라운드면 결국 전부 1회씩 나오므로,
순서는 **초반 모멘텀 최적화**일 뿐 — 데이터가 쌓이면 재정렬한다(`campaign.mbti_order`에 저장, 편집 가능).

기본 순서:
```
ESFP → ESFJ → ENFP → ESTP → ISFJ → ISFP → ISTJ → ESTJ
→ ENTP → ENFJ → INFP → INTP → ISTP → INTJ → ENTJ → INFJ
```
근거:
- **인구 비율(잠재 도달)**: 감각(S)형이 ~73%. ISFJ 13.8% · ESFJ ~12% · ISTJ ~11.6% 최다, 직관형(INFJ/ENTJ/INTJ/ENFJ) 합쳐 8% 미만.
- **온라인·쇼츠 참여**: 외향형이 SNS 적극적, 외향·감각·감정형 후크가 즉각 소구·바이럴에 유리. ISTP는 SNS 최저.
  내향직관(INFP/INTP/INFJ/INTJ)은 인구 대비 유튜브 참여는 높으나 절대 도달이 작아 중후반 배치.
- 그래서 앞: **외향·감정·감각의 대중적 유형(ESFP/ESFJ/ENFP/ESTP + ISFJ/ISFP/ISTJ/ESTJ)**, 뒤: **희소·내향직관·SNS 저활동(INTJ/ENTJ/INFJ, ISTP)**.

> 출처: MBTI 인구 통계(crowncounseling, personalitymax), 소셜미디어/유튜브 참여 연구(The Myers-Briggs Co. Social Media Report, Nature 2025 "Predicting MBTI of YouTube users").

관련: [SERIES.md](SERIES.md) · [YOUTUBE_API.md](YOUTUBE_API.md)
