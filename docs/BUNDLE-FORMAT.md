# 번들 형식 (입력)

쇼츠공방의 입력은 **번들 폴더** `chNN_bundle` 입니다(예: `ch22_bundle`).
보통 영상공방(VOD Studio)이 생성하지만, 같은 형식이면 직접 만들어도 됩니다.

## 폴더 구조
```
chNN_bundle/
  script/      chNN_script.json     (필수) 장면 목록 마스터
  images/      chNN_XX_*.png|jpeg    (필수) 장면당 이미지 1장
  audio/       chNN_XX_narration.wav (선택) 장면 음성. 있으면 사용
  subtitles/   chNN_XX_narration.srt (선택) 장면 자막
               chNN.srt              (선택) 통합 자막
  draft/       chNN_final_nosub.mp4  (선택) 자막 없는 롱폼 → 영상 배경으로 사용
               render_report.json    (선택) 씬별 타임라인(영상 구간 잘라쓰기용)
```
- `NN` = 2자리 챕터 번호. 파일 접두사는 `chNN_` 또는 `NN_` 둘 다 인식.
- 이미지 매칭: JSON의 `image_filename` → 같은 stem 다른 확장자 → `chNN_XX*`/`NN_XX*` 프리픽스 순.

## script JSON 스키마 (핵심 필드)
```json
{
  "version": "1.0",
  "chapter": 22,
  "title": "고대 서아시아와 지중해 세계의 형성",
  "aspect_ratio": "16:9",
  "scenes": [
    {
      "scene": 1,
      "scene_type": "opening_title",   // opening_title | body | climax | closing | next_preview ...
      "title": "타이틀 — ...",
      "narration_text": "약 2500년 전, ...",   // 자막/대본·검증의 사실 근거
      "narration_seconds": 29,                  // 힌트(실제 길이는 오디오로 측정)
      "image_filename": "22_01_ancient_world_dawn.png",
      "scene_meta": { "subtitle": "고대 서아시아와 지중해 세계의 형성" }  // 후크 초안에 사용
    }
  ]
}
```

## 쇼츠공방이 쓰는 방식
- **씬 선별**: `opening_title`·`climax`·`closing` 우선 + 본문 균등 샘플(`next_preview`는 제외).
- **후크 초안**: `scene_meta.subtitle` 또는 `title`.
- **음성 대본(자막) 초안**: `narration_text` 첫 문장(또는 AI 생성).
- **사실 검증 근거**: `narration_text`(원본) ↔ 편집된 자막 대조.
- **오디오**: 오프닝 장면의 `audio/` WAV(없으면 무음). TTS 재생성 시 새 음성으로 대체.
- **영상 배경**: `draft/chNN_final_nosub.mp4` 가 있을 때만(자막 박힌 `_final.mp4`는 사용 안 함).

## 번들 검색 위치
`.env` 의 `SHORTS_BUNDLE_ROOTS`(세미콜론 구분) 폴더들을 재귀 검색해 `*_bundle`을 찾습니다.
또는 화면에서 경로를 직접 입력할 수 있습니다.
