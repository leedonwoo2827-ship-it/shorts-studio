# YouTube 조회수 연동 (Phase 3) — 경로 A / B

캠페인으로 발행한 쇼츠의 **조회수**를 모아 *어떤 MBTI/장/후크 스타일이 잘 맞는지* 인사이트를 얻기 위한
YouTube API 연동 절차. 두 경로가 있고, **목적이 조회수면 경로 A(API 키) 하나로 충분**하다.

| | 경로 A · API 키 | 경로 B · OAuth |
|---|---|---|
| 얻는 것 | **공개 통계**: 조회수·좋아요·댓글수 | + **비공개 분석**: 시청 지속시간·CTR·노출수·시청자 지역/연령 |
| API | YouTube **Data** API v3 | YouTube **Analytics** API (+ Data) |
| 인증 | API 키 1개 (사용자 동의 불필요) | OAuth 2.0 동의 흐름 |
| 난이도 | 쉬움 | 중간(동의 화면·토큰 관리) |
| 권장 | ✅ **여기서 시작** | 심화 분석이 필요할 때만 |

> **경로 A만으로도 인사이트가 나온다.** 영상별 조회수를 (장 × MBTI)에 매핑하면 **MBTI별·장별·후크스타일별
> 평균 조회수**를 집계할 수 있어 "이 책류 숏폼엔 어떤 유형 후크가 잘 먹히나"라는 1차 결론이 나온다.
> 경로 B는 *왜 잘됐나*(지속시간·CTR)를 더해주는 심화일 뿐, 없어도 된다.

---

## 현재 설정 (이 프로젝트)
| 항목 | 값 |
|---|---|
| Google 계정 | `ubionbooktv@gmail.com` |
| 채널 | https://www.youtube.com/@ubionbooktv/shorts |
| GCP 프로젝트 이름 | `short-studio` |
| GCP 프로젝트 ID | `short-studio-500623` |
| 사용 설정 API | **YouTube Data API v3** (경로 A) |
| API 키 | 발급 후 `.env`의 `YOUTUBE_API_KEY=` 에만 보관(레포에 커밋 안 함) |
| 결제 | 불필요(무료 쿼터, 카드 미등록) |

> 진행 체크: ① 프로젝트 생성 ✅ ② YouTube Data API v3 사용 설정 ✅ ③ API 키 발급 ✅ → `.env`에 입력

## 경로 A — API 키 (권장)

### 발급 절차
1. **Google Cloud Console** (console.cloud.google.com) → **프로젝트 생성** (예: `shorts-studio`).
2. **API 및 서비스 → 라이브러리** → "**YouTube Data API v3**" → **사용 설정(Enable)**.
3. **사용자 인증 정보 → 사용자 인증 정보 만들기 → API 키**.
4. (권장) 생성된 키 → **키 제한 → API 제한 → "YouTube Data API v3"만** 선택(유출 대비).
5. `.env`에 `YOUTUBE_API_KEY=...` 추가.

> LLM에 쓰는 agy/Gemini의 Google 로그인과 **YouTube API 키는 별개**다. 위 절차로 키를 따로 만들어야 한다.

### 호출 예시
```
# 영상 ID들의 조회수 (한 번에 최대 50개, 비용 1 unit)
GET https://www.googleapis.com/youtube/v3/videos?part=statistics&id=ID1,ID2&key=KEY
 → items[].statistics.viewCount / likeCount / commentCount

# 채널(@ubionbooktv)의 업로드 목록
GET .../channels?part=contentDetails&forHandle=ubionbooktv&key=KEY
 → items[0].contentDetails.relatedPlaylists.uploads  (업로드 플레이리스트 ID)
GET .../playlistItems?part=contentDetails&playlistId=<uploads>&maxResults=50&key=KEY
 → items[].contentDetails.videoId   (페이지네이션: nextPageToken)
```
- 쇼츠도 일반 영상과 동일하게 잡힌다.
- **쿼터**: 기본 **10,000 units/일**. `videos.list`는 호출당 **1 unit**(50개 묶음) → 조회수 폴링엔 충분.
  ⚠️ `search.list`는 **100 units**라 가급적 쓰지 않는다(업로드 목록은 위 playlistItems 경로 사용).

---

## 경로 B — OAuth (심화, 선택)
시청 지속시간·평균 시청률·노출 클릭률(CTR)·시청자 통계는 **YouTube Analytics API + OAuth 2.0** 필요.
1. 경로 A의 1~2단계(프로젝트 + API 사용 설정)에 더해 **YouTube Analytics API**도 Enable.
2. **OAuth 동의 화면** 구성(내부/본인 채널용) → **OAuth 클라이언트 ID(데스크톱앱)** 발급.
3. 최초 1회 브라우저 동의 → refresh token 저장 → 이후 자동 갱신.
4. `reports.query`로 `estimatedMinutesWatched`, `averageViewPercentage`, `views`, `impressionsCtr` 등 조회.

본인 채널이라 가능하지만 토큰 관리가 늘어난다. **조회수 인사이트가 목적이면 A로 시작**하고, 더 깊게 볼 때 B를 추가.

---

## 앱 연동 (구현됨 ✅)
구현 위치: [shortsmaker/youtube.py](../shortsmaker/youtube.py)(API 키 클라이언트),
[shortsmaker/campaign.py](../shortsmaker/campaign.py)(`set_video`/`refresh_views`/`insights`),
`/api/campaign/{video,views/refresh,insights}`, 캠페인 탭 UI.

**사용 순서**
1. `.env`에 `YOUTUBE_API_KEY=` 입력 → 서버(run.bat) 재시작.
2. [캠페인] 탭 마스터 리스트의 각 행 **YouTube URL/ID 칸**에 발행한 쇼츠 주소를 붙여넣기
   (예: `https://www.youtube.com/shorts/XXXXXXXXXXX` 또는 11자 ID) → 자동으로 (장,MBTI) 셀에 연결.
3. **[📊 조회수 갱신]** → 연결된 모든 영상의 조회수를 한 번에 가져와 `view_stat`에 일자별 적재
   (행 옆에 `▶ 조회수` 표시). 매일/주기적으로 누르면 추세가 쌓임.
4. **[💡 인사이트]** → 각 셀 '최신 조회수' 기준 **MBTI별·장별 평균 조회수** 표 → 어떤 유형/장이 잘 먹히는지.

> 경로 B(OAuth) 연동 시 `view_stat`에 지속시간·CTR 컬럼을 더해 같은 표를 확장하면 된다(미구현).

---

## 나중에 키를 다시 보는 곳 / 관리
발급받은 키 값을 잊었거나 다시 확인·교체할 때:

1. https://console.cloud.google.com 접속 (계정 `ubionbooktv@gmail.com`)
2. 상단 프로젝트가 **`short-studio`** 인지 확인 (다르면 클릭해서 전환)
3. 왼쪽 메뉴 **API 및 서비스 → 사용자 인증 정보(Credentials)**
4. **API 키** 목록에서 해당 키 클릭
   - **"키 표시(Show key)"** → 전체 키 값 확인·복사
   - 같은 화면에서 **키 제한 변경**(API 제한 = YouTube Data API v3) / **키 재생성(회전)** / **삭제** 가능
5. 키를 바꿨으면 `.env`의 `YOUTUBE_API_KEY=` 값을 새 키로 교체 후 서버(run.bat) 재시작

**보관 위치**: 이 앱에서는 `.env`의 `YOUTUBE_API_KEY=` 한 곳에만 둔다. `.env`는 `.gitignore`라 깃에 안 올라감.
키가 유출되면 위 4단계에서 **재생성**하면 옛 키는 즉시 무효화된다.

관련: [SERIES.md](SERIES.md) · [ARCHITECTURE.md](ARCHITECTURE.md)
