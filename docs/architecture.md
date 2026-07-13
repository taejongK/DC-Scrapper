# 프로젝트 구조 문서 (Architecture)

DCInside 커뮤니티 수집·분석 도구의 내부 구조를 정리한 개발자용 문서.
사용법은 [README](../README.md), 분석 기능 개선 이력은
[analysis-improvement-proposal](./analysis-improvement-proposal.md) 참고.

---

## 1. 큰 그림

**수집 → 저장 → 분석 → 표현**의 4단계 단방향 파이프라인.

```
 DCInside 갤러리                                                    브라우저
      │ (HTTP)                                                        ▲
      ▼                                                               │
┌───────────┐   upsert   ┌──────────┐   read    ┌──────────┐  REST  ┌─────────┐
│ dc_scraper│ ─────────▶ │  SQLite  │ ────────▶ │ analysis │ ◀────▶ │ webapp  │
│  (수집기) │            │dcinside.db│           │(분석엔진)│        │(FastAPI)│
└───────────┘            └──────────┘           └──────────┘        └─────────┘
     CLI                    4 tables            stats/keywords/         static/
  python -m dc_scraper                          trends/sentiment/     (대시보드)
                                                timeseries/llm
```

- **의존 방향은 한쪽으로만** 흐른다: `webapp → analysis → (analysis.db) → SQLite`, `dc_scraper → SQLite`.
  분석/웹 레이어는 스크래퍼를 import하지 않고(수집 트리거 제외), 스크래퍼는 분석을 모른다.
- 각 레이어는 독립 실행 가능: 수집만 CLI로, 분석만 파이썬에서, 대시보드는 웹으로.

---

## 2. 디렉터리 구조

```
dc_scraper/            [레이어 1] 수집기 (requests + BeautifulSoup)
  __main__.py            CLI 진입점 (argparse: --date, --date-from/to, --gallery …)
  config.py              갤러리 ID·셀렉터·엔드포인트 등 사이트 의존 상수 총집합
  fetch.py               Fetcher — 세션·UA·랜덤딜레이·재시도·차단(403/429) 처리
  parse_list.py          목록 페이지 파싱 (공지 제외, 글번호·날짜 추출)
  parse_view.py          본문 파싱 (성인글 감지 → is_adult, 추천/조회/e_s_n_o)
  parse_comment.py       댓글 AJAX(JSON) 파싱 (대댓글 계층, 광고행 제외)
  scraper.py             collect() — 페이지 순회·날짜범위·글별 처리 오케스트레이션
  db.py                  Database — 스키마 생성·마이그레이션·멱등 upsert (쓰기 담당)

analysis/              [레이어 3] 분석 엔진 (pandas + kiwipiepy + LLM)
  db.py                  읽기 전용 로더 (load_posts/load_comments, q=str|list OR 필터)
  stats.py               개요 통계·인기글 랭킹·말머리 분포
  timeseries.py          날짜/시간/요일, 요일×시간 히트맵, 참여도·감성 추이
  keywords.py            형태소 추출, 빈도, 특징어(TF-IDF)+bigram, 연관어(PMI)
  trends.py              일자별 키워드 버스트·신규 등장어 탐지
  sentiment.py           사전 기반 감성(슬랭·강조·이모티콘·부정), 연속점수+신뢰도
  llm.py                 LLM 클라이언트 래퍼 (OpenRouter/Anthropic 자동 감지)
  llm_report.py          키워드 심층 리포트 (문서화 → map-reduce → 근거링크 → 캐시)
  data/
    sentiment_ko.json    감성 사전(긍/부/부정어/강조어/이모티콘)
    stopwords_ko.txt     한국어 불용어

webapp/                [레이어 4] 웹 대시보드 (FastAPI + 순수 JS)
  main.py                FastAPI 앱, static 마운트, index.html 서빙
  api.py                 REST 라우트 (/api/*) — 수집제어·글조회·분석·LLM
  jobs.py                JobManager — collect()를 백그라운드 스레드로 실행
  static/
    index.html           탭 3개(수집/글목록/분석) + 공통 필터바(목록·분석 탭에서만 표시)
    app.js               바닐라 JS — fetch·차트(Chart.js)·워드클라우드·LLM 렌더
    style.css            다크 테마

docs/                  설계·구조 문서 (본 문서 포함)
tests/                 분석·웹·LLM 테스트 (dc_scraper/tests/ 는 수집기 테스트)
run.sh / stop.sh       대시보드 실행/종료 (.env 자동 로드)
pyproject.toml         패키지·의존성(extras: web/analysis/llm/dev)
.env / .env.example    LLM API 키 등 로컬 환경변수 (.env는 커밋 제외)
dcinside.db            수집 데이터 (SQLite, 커밋 제외)
```

---

## 3. 데이터 저장 (SQLite)

`dcinside.db`, 단일 파일. 스키마는 `dc_scraper/db.py`가 소유·생성하며,
컬럼 추가는 `ALTER TABLE`(additive) 방식으로 마이그레이션한다.

| 테이블 | 역할 | 핵심 키 |
|---|---|---|
| **posts** | 글 1건 = 1행 | `post_no` (PK). title, writer, posted_at, view_count, recommend, dislike, comment_cnt, category, body_text, body_html, url, **is_adult**, scraped_at |
| **comments** | 댓글/대댓글 | `UNIQUE(post_no, comment_no)`. parent_no(대댓글), content, is_reply |
| **scrape_runs** | 수집 실행 이력 | gallery_id, target_date, posts_found/saved, comments_saved, status, error |
| **llm_reports** | LLM 리포트 캐시 | `cache_key` (PK, 내용 해시). keyword, model, source, post_count, created_at, report_json |

- **멱등성**: posts는 `post_no`, comments는 `(post_no, comment_no)`로 `ON CONFLICT` upsert → 재수집해도 중복 없음.
- `posts`/`comments`/`scrape_runs`는 수집기가 씀. `llm_reports`는 분석 레이어(`llm_report.py`)가 씀(캐시).

---

## 4. 수집 파이프라인 (`dc_scraper.collect`)

```
_resolve_range(date | date_from~date_to)
  → _crawl_list: 목록 페이지를 최신순으로 순회(50건/페이지)
      · parse_list로 행 추출, 공지(말머리=="공지") 제외
      · 대상 날짜 범위 밖 + 더 과거 글만 남으면 순회 중단
  → _process_post(글별):
      · parse_view로 본문·추천·e_s_n_o, 성인글이면 is_adult=1(본문 스킵)
      · fetch_comments(AJAX POST /board/comment/)로 댓글 JSON
      · db.upsert_post / upsert_comment
  → scrape_runs에 실행 결과 기록
```

- 매너 수집: 요청 간 랜덤 딜레이(기본 1.0~2.5초)·백오프, 개별 글 실패가 전체를 멈추지 않음.
- 사이트 구조 변경 시 손볼 곳은 사실상 `config.py`(셀렉터·파라미터)뿐.

---

## 5. 분석 엔진 (`analysis/`)

모든 분석 함수는 `db.load_posts` / `load_comments`(pandas DataFrame)로 데이터를 읽고,
동일한 **필터 딕셔너리**(`gallery_id, date_from, date_to, exclude_adult, q`)를 공유한다.
`q`는 문자열(단일) 또는 리스트(다중 키워드 OR)를 받는다.

| 모듈 | 대표 함수 | 산출 |
|---|---|---|
| stats | overview / top_posts / category_distribution | 카운트·랭킹·분포 |
| timeseries | by_date/by_hour/by_weekday / heatmap / engagement_by_date / sentiment_by_date | 시계열·히트맵 |
| keywords | word_frequency / salient_words / related_words | 빈도·특징어(TF-IDF)·연관어(PMI) |
| trends | daily_bursts | 버스트·신규 키워드 |
| sentiment | score_text / sentiment_distribution | 감성 라벨·연속점수 |
| llm_report | keyword_report | LLM 서술형 리포트(근거 링크) |

- 형태소 분석은 `kiwipiepy`(Java 불필요) 싱글턴(`_kiwi()`, lru_cache).
- 감성은 사전 기반 baseline이며 `score_text`만 교체하면 모델/LLM 스코어러로 승격 가능(집계 API 불변).

---

## 6. LLM 심층 분석 플로우

키워드가 든 글·댓글을 LLM이 읽고 **내용·평가·쟁점**을 서술로 정리하고, 각 항목에 **근거 글 링크**를 붙인다.

```
[UI] 🧠 카드 (키워드 · 범위 · refresh)
  │  POST /api/analysis/llm_report
  ▼
api.py: 검증 → keyword_report(keyword, source, refresh, max_posts=60, **filters)
  ▼
llm_report.keyword_report:
  1. _parse_keywords         "에덴 or 오브, 젬" → ["에덴","오브","젬"]  (or/,/| 구분)
  2. _build_docs             load_posts(q=리스트, OR·성인제외) → 추천순 상위 60글
                             + 댓글(상위 15) → "[글 #no] 제목/본문/댓글" 블록 + meta(no→url)
  3. 캐시 조회               sha1(키워드+모델+범위+필터+글번호셋) → llm_reports 히트 시 즉시 반환
  4. llm.available() 체크     불가 시 에러+상태 반환(크래시 없음)
  5. _batch (14000자/묶음)
       · 1묶음 → _SINGLE_SYS 단일 호출
       · N묶음 → 묶음별 _MAP_SYS → _REDUCE_SYS 종합
  6. _normalize              각 항목 post_nos → sources(글번호+url+제목) 부착
  7. 캐시 저장 → 반환
  ▼
llm.py (백엔드 자동 감지):
  OPENROUTER_API_KEY → OpenRouter(requests) │ ANTHROPIC_API_KEY → anthropic(SDK)
  complete_json: JSON 규칙 지시 → 파싱 실패 시 1회 자동 복구
  ▼
[UI] renderLLM: 개요·분위기·주제·긍정/부정·쟁점·대표반응 + #글번호 근거 링크
```

- **캐시**(`llm_reports`): 같은 요청은 무료·즉시, `새로 분석` 체크 시 재생성.
- **키 주입**: `OPENROUTER_API_KEY`(권장) 또는 `ANTHROPIC_API_KEY`, 모델은 `DC_LLM_MODEL`.
  키는 환경변수로만 읽고 파일/로그에 저장하지 않으며, `.env`는 `run.sh`가 자동 로드.

---

## 7. 웹 API 표면 (`/api/*`)

| 메서드·경로 | 설명 |
|---|---|
| POST `/collect` · GET `/collect/status` | 수집 잡 시작 / 진행·이력 조회 |
| GET `/posts` · `/posts/{post_no}` | 글 목록(검색·정렬·페이지) / 상세(본문+댓글) |
| GET `/stats/overview` · `/stats/top` · `/stats/categories` | 통계·랭킹·분포 |
| GET `/analysis/timeseries?kind=date\|hour\|weekday\|sentiment\|engagement` | 시계열 |
| GET `/analysis/heatmap` · `/analysis/bursts` | 요일×시간 히트맵 / 이슈 버스트 |
| GET `/analysis/keywords?method=count\|salient` · `/analysis/related` | 키워드·특징어 / 연관어 |
| GET `/analysis/sentiment` | 감성 분포 |
| GET `/analysis/llm_status` · POST `/analysis/llm_report` | LLM 사용 가능 여부 / 심층 리포트 |
| GET `/meta/galleries` | 필터 UI용 갤러리·날짜 범위 |

- 분석 엔드포인트는 공통 필터(`gallery_id, date_from, date_to, q`)를 쿼리로 받는다.
- DB 경로는 환경변수 `DC_DB_PATH`(기본 `dcinside.db`)로 결정.

---

## 8. 설정 · 환경변수

| 변수 | 용도 | 기본값 |
|---|---|---|
| `DC_DB_PATH` | 대시보드가 읽을 DB 경로 | `dcinside.db` |
| `OPENROUTER_API_KEY` | LLM 백엔드(OpenRouter) | — |
| `ANTHROPIC_API_KEY` | LLM 백엔드(Anthropic 직접) | — |
| `DC_LLM_MODEL` | LLM 모델 | `anthropic/claude-sonnet-5` (OR) |

`run.sh`가 시작 시 `.env`를 자동 로드한다. 수집 갤러리·딜레이 등은 CLI 옵션 또는 `dc_scraper/config.py`.

---

## 9. 테스트

| 위치 | 대상 | 방식 |
|---|---|---|
| `dc_scraper/tests/` | 파서·DB·수집 오케스트레이션 | 실제 HTML/JSON 픽스처(오프라인) |
| `tests/test_analysis.py` | 분석 함수 전반 | 임시 SQLite 픽스처(`sample_db`) |
| `tests/test_webapp.py` | FastAPI 엔드포인트 | TestClient |
| `tests/test_llm.py` | LLM 래퍼·리포트·API | `llm.set_override`로 네트워크 없이 모킹 |

`pytest`로 전체 실행(테스트=pytest, 린트=`ruff check`). LLM 테스트는 실제 API를 호출하지 않는다.

---

## 10. 확장 포인트

- **다른 갤러리/사이트**: `config.py`의 `GALLERY_KIND`/`GALLTYPE`/셀렉터 조정.
- **감성 고도화**: `sentiment.score_text`를 모델/LLM 스코어러로 교체(집계 API 불변).
- **LLM 백엔드 교체**: `llm.py`의 `complete()` 분기만 확장(현재 OpenRouter/Anthropic).
- **새 분석 축**: `analysis/`에 모듈 추가 → `api.py`에 라우트 → 대시보드 카드.
- **성능**: 분석 결과 캐시 테이블 패턴(`llm_reports`)을 다른 무거운 분석에도 적용 가능.
