# 분석 알고리즘 정리

대시보드 **📊 분석 탭**에 남아 있는 5개 위젯 + **🧠 리포트 탭**(LLM 심층 리포트)이 각각 어떤
알고리즘으로 결과를 만드는지 정리한 문서다.
(2026-07-15 기준. 날짜별/시간대별/요일별/말머리/감성/연관어/TF-IDF 특징어는 제거되었고,
LLM 심층 분석은 분석 탭 카드에서 독립된 리포트 탭으로 옮겨지며 키워드 직접 입력 →
자연어 질문 기반 에이전트로 바뀌었다.)

- 코드 위치: `analysis/` 패키지, API는 `webapp/api.py`
- 각 분석은 **공통 필터**(갤러리·기간·키워드 포함)를 SQL 단계에서 적용한다. 필터가 없으면 DB 전체가 대상.

## 목차
1. [공통 요소](#공통-요소)
2. [개요 카드](#1-개요-카드-overview)
3. [🧠 심층 리포트 (deep_report)](#2-심층-리포트-deep_report)
4. [이슈 버스트 (급상승 / 신규 등장)](#3-이슈-버스트-daily_bursts)
5. [요일 × 시간 히트맵](#4-요일--시간-히트맵-heatmap)
6. [워드클라우드](#5-워드클라우드-word_frequency)
7. [인기글 랭킹](#6-인기글-랭킹-top_posts)

---

## 공통 요소

### 공통 필터 (`webapp/api.py:_filters`)
모든 분석 API가 받는 파라미터. `analysis/db.py`의 `_where`가 SQL `WHERE`로 변환한다.

| 파라미터 | 의미 |
|---|---|
| `gallery_id` | 특정 갤러리로 한정 |
| `date_from` / `date_to` | 작성일 범위(YYYY-MM-DD, 포함) |
| `q` | 제목·본문에 이 키워드가 포함된 글만 (`,`·`\|`·`or`로 여러 개 → OR 매칭) |

필터를 아무것도 안 주면 조건절 자체가 없어 **수집된 전체 데이터**를 집계한다.

### 한국어 토크나이저 (`analysis/keywords.py:extract_nouns`)
**워드클라우드**와 **이슈 버스트**가 공유하는 명사 추출기.

1. `_clean_markup()`으로 전처리: URL 제거 → 인라인 HTML 태그(`<div ...>`) 제거 → HTML 엔티티(`&nbsp;`) 제거 → 잔여 CSS 선언(`property: value;`) 제거
   - AI 채팅 갤러리 이용자가 본문에 붙여넣는 HTML 상태창 템플릿 노이즈(div/px/font/color…)를 걸러내기 위함. 원본 `body_text`는 건드리지 않고 분석 시점에만 정리한다.
2. `kiwipiepy`로 형태소 분석 후, 태그가 **NNG(일반명사)·NNP(고유명사)·SL(외국어/영문)** 인 토큰만 채택
3. 길이 **2자 이상**, `analysis/data/stopwords_ko.txt`의 불용어(조사·CSS 단위 px/rem/div 등 포함)가 아닌 것만 남김. 영문(SL)은 소문자화.

> 즉 두 분석 모두 "의미 있는 명사만" 세며, 마크업/불용어는 배제된다.

---

## 1. 개요 카드 (`overview`)
`analysis/stats.py:overview` · `GET /api/stats/overview`

**목적**: 현재 필터 범위의 요약 지표.

**알고리즘**: 필터된 글/댓글을 로드해 단순 집계.
- 글 수, 댓글 수, 고유 작성자 수(`writer.nunique()`)
- 작성일 범위(min/max), 성인글 수
- 평균 댓글 수, 평균 조회 수

계산은 전부 pandas 집계 한 번. 별도 가중치·모델 없음.

---

## 2. 심층 리포트 (`deep_report`)
`analysis/llm_agent.py:deep_report` · `POST /api/analysis/ask`

**목적**: 사용자가 **자연어 질문**을 던지면, 관련 글·댓글을 LLM으로 읽어 **무슨 얘기·평가·쟁점**이
오갔는지 정리하고, 각 항목에 **근거 글 번호**를 붙인다. (빈도 분석이 "어떤 단어"를 알려준다면 이건
"무슨 내용") 키워드를 사람이 직접 골라 넣던 구버전(`llm_report.keyword_report` 단독 호출)과 달리,
**검색어 발굴 단계가 앞에 붙은 2단계 에이전틱 파이프라인**이다.

**알고리즘**:
1. **검색어 발굴** (`discover_keywords`): `llm.run_tools`로 최대 6턴짜리 tool-calling 루프를 돌려,
   `search_posts`(키워드 검색 + 댓글 미리보기)·`get_post`(특정 글 전체 조회) 툴을 LLM이 스스로 호출하게
   한다. 질문의 표준어로 시작해 검색 결과(특히 댓글)에 등장하는 **커뮤니티 은어·동의어·표기변형**을
   찾아 재검색하며 검색어 후보를 넓힌다. 최종적으로 검색어 배열(JSON, 5~8개)을 반환하며, 파싱
   실패·빈 배열이면 질문 자체의 단어로 폴백한다.
2. **전수 구조화 리포트** (`llm_report.keyword_report`, map-reduce — 검색어 발굴 이전부터 있던
   엔진을 그대로 재사용):
   - **문서 수집** (`_build_docs`): 발굴된 검색어를 하나라도 포함(OR)하는 비성인 글을 로드 →
     **추천순 정렬** → 상위 `max_posts`(기본 60)개만 채택. 잘리면 `truncated=true`.
   - **문서 블록화**: 글마다 `[글 #번호] 제목(추천n) / 본문(최대 800자) / 댓글(최대 15개, 각 180자)` 형태로 구성.
   - **배치**: 문자 예산(14,000자) 기준으로 블록을 묶음.
     - 묶음 1개 → **단일 호출**(`_SINGLE_SYS`)
     - 여러 개 → **map**(각 묶음 요약) 후 **reduce**(부분 결과 JSON들을 하나로 종합, 근거 글번호는 합집합 보존)
   - **출력 JSON**: `overview`(요약), `mood`(분위기), `themes`(주요 주제), `positives`/`negatives`(긍·부정 평가), `issues`(쟁점), `quotes`(대표 인용). 각 항목의 `post_nos` → 원본 글 링크로 변환.
   - **캐시**: `(검색어, 모델, source, 필터, 대상 글번호들)`의 SHA1 해시를 키로 DB(`llm_reports`)에 저장. 같은 검색어 조합은 즉시 반환, `refresh=true`로 무시. **검색어 발굴 단계 자체는 캐시되지 않는다** — 매 질문마다 재실행.
3. **로깅**: 질문·개요·근거·발굴 검색어·모델·매칭 글 수를 `qa_log`에 적재. `GET /api/analysis/ask_history`(목록)·`/ask_history/{id}`(상세, 원본 문서 컨텍스트 포함)·`DELETE .../ask_history/{id}`로 다룰 수 있다.

**한계**: 전체가 아니라 **추천순 상위 60글**만 실제 분석 대상. `post_count`(매칭 전체) vs `analyzed_posts`(분석된 수)로 표시. 검색어 발굴은 키워드 LIKE 매칭 기반이라 임베딩 없이는 완전한 동의어 커버리지를 보장하지 않는다.

---

## 3. 이슈 버스트 (`daily_bursts`)
`analysis/trends.py:daily_bursts` · `GET /api/analysis/bursts`

**목적**: "오늘 갑자기 튀어나온 단어"를 찾는다. TF-IDF가 아니라 **시간축 비중 비교(share ratio)** 방식.

**알고리즘**:
1. **날짜별 단어 집계** (`_daily_terms`): 각 글 제목+본문에서 `extract_nouns`로 명사 추출 → `YYYY-MM-DD` → Counter.
   - ⚠️ **댓글은 제외**. 댓글 타임스탬프에 연도가 없어 날짜 버킷팅이 부정확하기 때문.
2. **대상일/기준일 분리**: `target`(지정 날짜 또는 최신일) vs `baseline`(target 이전 전체 날짜를 합친 Counter).
3. **단어별 버스트 점수** — 대상일에 `min_count`회(기본 2) 이상 나온 단어만:
   ```
   today_share = c / today_total                         # 오늘 이 단어의 비중
   base_share  = (base[term] + 1) / (base_total + vocab) # 과거 비중 (라플라스 스무딩)
   burst       = today_share / base_share
   ```
   - `vocab` = 오늘·과거 어휘의 합집합 크기. `+1`/`+vocab` 스무딩으로 **과거에 없던 신규 단어가 무한대로 튀는 것을 방지**(유한한 점수 부여).
   - `is_new` = 과거 baseline에 아예 없던 단어인지.
4. **두 목록으로 분리**:
   - **🔥 급상승 (bursts)**: 전체 후보를 **burst 내림차순**(동점이면 count)으로 정렬 → 상위 N.
   - **✨ 신규 등장 (new_keywords)**: 그중 `is_new=true`인 것만 뽑아 **raw count 내림차순**으로 정렬 → 상위 N.

   즉 신규 등장은 급상승의 부분집합이되 **정렬 기준이 다르다** (급상승=비율, 신규=빈도).

**호출값**(프론트 `loadBursts`): `top_n=12`, `min_count=2`, 날짜는 선택기 값(없으면 최신일).

**한계/주의**:
- 유일한 문턱이 `min_count=2` → **긴 썰 글 하나가 어떤 단어를 2번만 언급해도 후보**가 된다(예: 한 롤플레이 글의 "캘리포니아").
- **언급 횟수 기반이며 "몇 개의 서로 다른 글에서 나왔는지"는 보지 않는다** → 한 글에 몰린 단어에 취약. (개선 여지: 글 단위 document frequency를 추가로 세어 "서로 다른 글 2개 이상"을 조건화)
- 첫날은 baseline이 없어 모든 단어가 `is_new`, 점수 의미가 약함(`baseline_days=0`으로 표시).

---

## 4. 요일 × 시간 히트맵 (`heatmap`)
`analysis/timeseries.py:heatmap` · `GET /api/analysis/heatmap`

**목적**: 커뮤니티가 언제 활발한지 한눈에.

**알고리즘**: 필터된 글의 `posted_at`을 파싱해 **(요일, 시)** 로 그룹핑 후 글 수 카운트 → **7×24 행렬**(`matrix[요일][시]`) 반환. 프론트는 값이 클수록 진한 파랑으로 셀을 칠한다.

과거의 "시간대별/요일별 막대" 두 위젯을 2D로 포괄한 형태.

---

## 5. 워드클라우드 (`word_frequency`)
`analysis/keywords.py:word_frequency` · `GET /api/analysis/keywords`

**목적**: 자주 나온 단어를 크기로 시각화.

**알고리즘**:
1. 대상 문서 수집(`source`: 제목/본문/댓글/전체)
2. 각 문서를 [공통 토크나이저](#한국어-토크나이저-analysiskeywordsextract_nouns)로 명사 추출
3. 전체 빈도 Counter → `most_common(top_n)` (기본 상위 120개를 프론트에 전달)
4. 단어 크기 ∝ 빈도

TF-IDF 같은 가중치 없이 **순수 빈도**다. (과거 "키워드 카드"의 TF-IDF/특징어 방식은 이 위젯으로 대체하며 제거됨.)

단어를 클릭하면 그 단어가 LLM 심층분석 입력창에 채워진다.

---

## 6. 인기글 랭킹 (`top_posts`)
`analysis/stats.py:top_posts` · `GET /api/stats/top`

**목적**: 지표 기준 상위 글.

**알고리즘**: 필터된 글을 선택 지표(`recommend`·`view_count`·`comment_cnt`)로 **내림차순 정렬 후 상위 N**. 단순 정렬이며, 글목록 탭의 정렬 기능과 동일한 성격(요약 뷰).

---

## 참고
- 위젯 정리 배경과 유지/제거 결정: 커밋 `refactor(analysis): 분석 탭 위젯 14→6개로 정리`
- CSS/HTML 노이즈 제거: 커밋 `fix(analysis): 키워드/버스트에서 인라인 HTML·CSS 노이즈 제거`
- 전체 구조는 [`docs/architecture.md`](./architecture.md) 참고.
