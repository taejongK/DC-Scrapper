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
     CLI                   5 tables             stats/keywords/         static/
  python -m dc_scraper                         trends/timeseries/     (대시보드)
                                              llm/llm_report/llm_agent
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
  timeseries.py          요일×시간 히트맵(heatmap)
  keywords.py            형태소 추출(extract_nouns) + 순수 빈도(word_frequency, 워드클라우드용)
  trends.py              일자별 키워드 버스트·신규 등장어 탐지(daily_bursts)
  llm.py                 LLM 클라이언트 래퍼 (OpenRouter/Anthropic 자동 감지, complete/complete_json/run_tools)
  llm_report.py          키워드 심층 리포트 엔진 (문서화 → map-reduce → 근거링크 → 캐시, keyword_report)
  llm_agent.py           자연어 질문 → 에이전틱 검색어 발굴(tool-calling) → keyword_report 실행 → qa_log 기록 (deep_report)
  data/
    stopwords_ko.txt     한국어 불용어
    sentiment_ko.json    (레거시) 감성 사전 — 현재 어떤 코드에서도 참조되지 않음, sentiment.py는 제거됨

webapp/                [레이어 4] 웹 대시보드 (FastAPI + 순수 JS)
  main.py                FastAPI 앱, static 마운트, index.html 서빙
  api.py                 REST 라우트 (/api/*) — 수집제어·글조회·분석·LLM
  jobs.py                JobManager — collect()를 백그라운드 스레드로 실행
  static/
    index.html           탭 4개(수집/글목록/분석/🧠 리포트) + 공통 필터바(글목록·분석·리포트 탭에서 표시)
    app.js               바닐라 JS — fetch·차트(Chart.js)·워드클라우드·심층 리포트 렌더
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
| **posts** | 글 1건 = 1행 | `post_no` (PK). title, writer, posted_at, view_count, recommend, dislike, comment_cnt, category, body_text, body_html, url, **is_adult**, scraped_at, **is_deleted**, **deleted_at** |
| **comments** | 댓글/대댓글 | `UNIQUE(post_no, comment_no)`. parent_no(대댓글), content, is_reply, **is_deleted**, **deleted_at** |
| **scrape_runs** | 수집 실행 이력 | gallery_id, target_date, posts_found/saved, comments_saved, status, error |
| **llm_reports** | 키워드 심층 리포트 캐시 | `cache_key` (PK, 내용 해시). keyword, model, source, post_count, created_at, report_json |
| **qa_log** | 🧠 심층 리포트 질문·답변 이력 | `id` (PK). created_at, question, answer(overview), citations(JSON), filters(JSON), model, used_posts, context(원본 문서 블록), report(구조화 답변 JSON) |

- **멱등성**: posts는 `post_no`, comments는 `(post_no, comment_no)`로 `ON CONFLICT` upsert → 재수집해도 중복 없음.
- **삭제 감지**: 재수집 시 (목록을 끝까지 순회했고 실행이 성공한 경우) 이전엔 있었지만 이번엔 목록에
  없는 글/댓글은 삭제하지 않고 `is_deleted=1`/`deleted_at`로 표시만 한다(아카이브 보존 목적).
- `posts`/`comments`/`scrape_runs`는 수집기가 씀. `llm_reports`/`qa_log`는 분석 레이어(`llm_report.py`/`llm_agent.py`)가 씀(둘 다 `CREATE TABLE IF NOT EXISTS` + additive 마이그레이션으로 최초 사용 시 생성/갱신).

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
  → 삭제 스윕(목록 순회가 완결 + 실행 성공일 때만): 저장된 글 중 이번 목록에 없는
    post_no를 is_deleted=1로 표시(comments도 동반 표시). 목록이 max_pages로 잘렸거나
    실행이 partial이면 스킵(오탐 방지).
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
| timeseries | heatmap | 요일×시간 활동 행렬 |
| keywords | extract_nouns / word_frequency | 명사 추출 · 순수 빈도(워드클라우드) |
| trends | daily_bursts | 버스트·신규 키워드 |
| llm_report | keyword_report | 키워드 매칭 글·댓글 → map-reduce 구조화 리포트(근거 링크), DB 캐시 |
| llm_agent | discover_keywords / deep_report | 자연어 질문 → 검색어(은어 포함) 발굴 → keyword_report 실행 → qa_log 기록 |

- 형태소 분석은 `kiwipiepy`(Java 불필요) 싱글턴(`_kiwi()`, lru_cache).
- 사전 기반 감성 분석(`sentiment.py`)·TF-IDF 특징어·PMI 연관어·다축 시계열은 신뢰도·중복 문제로
  제거되었다. 배경과 대체 방향(LLM 심층 리포트)은
  [analysis-improvement-proposal.md §7~§8](./analysis-improvement-proposal.md) 참고.

---

## 6. LLM 심층 분석 플로우

사용자가 **자유 질문**을 던지면, 에이전트가 먼저 코퍼스에서 **검색어(커뮤니티 은어·동의어 포함)를
발굴**하고, 그 검색어로 관련 글·댓글을 전수 읽어 **내용·평가·쟁점**을 서술로 정리하며, 각 항목에
**근거 글 링크**를 붙인다. (구 버전은 사용자가 키워드를 직접 넣는 1단계 방식이었으나, 현재는
검색어 발굴이 앞단에 추가된 2단계 에이전틱 파이프라인이다.)

```
[UI] 🧠 리포트 탭 (질문 입력 · 상단 필터바의 갤러리/기간)
  │  POST /api/analysis/ask {question, gallery_id?, date_from?, date_to?}
  ▼
api.py: 검증 → llm_agent.deep_report(question, max_turns=6, max_posts=60, **filters)
  ▼
llm_agent.deep_report:
  1. discover_keywords        에이전트 tool-calling 루프(llm.run_tools, 최대 6턴):
                                 · search_posts 툴 — 키워드로 글 검색, 댓글 미리보기 포함(은어가 담김)
                                 · get_post 툴 — 특정 글 본문·댓글 전체 조회
                               표준어로 시작 → 검색 결과(특히 댓글)에서 실제 은어·동의어·표기변형을
                               찾아 재검색 → 최종 검색어 배열(JSON, 5~8개) 반환
                               (파싱 실패/빈 결과 시 질문 자체의 단어로 폴백)
  2. llm_report.keyword_report  발굴된 검색어(" or "로 결합)로 기존 map-reduce 엔진 실행:
       a. _build_docs           load_posts(q=검색어 리스트, OR·성인제외) → 추천순 상위 max_posts(60)글
                                 + 댓글(상위 15) → "[글 #no] 제목/본문/댓글" 블록 + meta(no→url)
       b. 캐시 조회             sha1(검색어+모델+범위+필터+글번호셋) → llm_reports 히트 시 즉시 반환
       c. _batch (14000자/묶음)
            · 1묶음 → 단일 호출 │ N묶음 → 묶음별 map → reduce로 종합
       d. _normalize            각 항목 post_nos → sources(글번호+url+제목) 부착, 캐시 저장
  3. _log_qa                  질문·overview·근거·검색어·모델·매칭 글 수를 qa_log 테이블에 기록
  ▼
llm.py (백엔드 자동 감지, discover/keyword_report 두 단계 모두 사용):
  OPENROUTER_API_KEY → OpenRouter(requests, tool-calling 포함) │ ANTHROPIC_API_KEY → anthropic(SDK)
  complete_json: JSON 규칙 지시 → 파싱 실패 시 1회 자동 복구
  run_tools: 백엔드별 tool-use 프로토콜을 감싸 request→tool→result 루프 실행
  ▼
[UI] renderReport: 발굴 검색어 배지 · 개요·분위기·주제·긍정/부정·쟁점·대표반응 + #글번호 근거 링크
```

- **캐시**(`llm_reports`): 검색어 조합이 같으면 map-reduce 단계는 즉시 반환(무료), `새로 분석` 체크 시 재생성.
  단, 검색어 발굴(`discover_keywords`) 자체는 매 요청 재실행된다(캐시 없음).
- **이력**(`qa_log`): 모든 질문·리포트(원본 문서 컨텍스트 포함)가 로깅되며 `GET /api/analysis/ask_history`(목록)·
  `GET /api/analysis/ask_history/{id}`(상세)·`DELETE /api/analysis/ask_history/{id}`(삭제)로 다룰 수 있다.
  로깅 실패는 리포트 응답에 영향을 주지 않는다(best-effort).
- **키 주입**: `OPENROUTER_API_KEY`(권장) 또는 `ANTHROPIC_API_KEY`, 모델은 `DC_LLM_MODEL`.
  키는 환경변수로만 읽고 파일/로그에 저장하지 않으며, `.env`는 `run.sh`가 자동 로드.
- 옛 단일 키워드 리포트 엔진(`llm_report.keyword_report`)은 여전히 내부에 남아 `deep_report`가
  두 번째 단계로 재사용한다 — 직접 노출하는 `POST /api/analysis/llm_report` 라우트는 제거되었다.

---

## 7. 웹 API 표면 (`/api/*`)

| 메서드·경로 | 설명 |
|---|---|
| POST `/collect` · GET `/collect/status` | 수집 잡 시작 / 진행·이력 조회 |
| GET `/posts` · `/posts/{post_no}` | 글 목록(검색·정렬·페이지) / 상세(본문+댓글) |
| GET `/stats/overview` · `/stats/top` · `/stats/categories` | 통계·랭킹·말머리 분포 |
| GET `/analysis/heatmap` | 요일×시간 히트맵 |
| GET `/analysis/bursts` | 이슈 버스트(급상승·신규 키워드) |
| GET `/analysis/keywords` | 키워드 빈도(워드클라우드) |
| GET `/analysis/llm_status` | LLM 사용 가능 여부(백엔드·모델·키 상태) |
| POST `/analysis/ask` | 🧠 심층 리포트 — 자연어 질문 → 검색어 발굴 → 구조화 리포트 |
| GET `/analysis/ask_history` | 심층 리포트 질문 이력 목록(요약, `qa_log`) |
| GET `/analysis/ask_history/{log_id}` | 이력 1건 상세(질문+원본 문서 컨텍스트+구조화 답변) |
| DELETE `/analysis/ask_history/{log_id}` | 이력 1건 삭제 |
| GET `/meta/galleries` | 필터 UI용 갤러리·날짜 범위 |

- 대부분의 분석 엔드포인트는 공통 필터(`gallery_id, date_from, date_to, q`)를 쿼리로 받는다.
  `/analysis/bursts`는 `q`(키워드) 필터를 받지 않는다.
- `POST /analysis/ask`는 필터를 쿼리가 아닌 JSON 바디(`gallery_id, date_from, date_to`)로 받는다.
- DB 경로는 환경변수 `DC_DB_PATH`(기본 `dcinside.db`)로 결정.
- 제거된 과거 엔드포인트: `/analysis/timeseries`, `/analysis/related`, `/analysis/sentiment`,
  `POST /analysis/llm_report` (배경은 §6, [analysis-improvement-proposal.md](./analysis-improvement-proposal.md) 참고).

---

## 8. 설정 · 환경변수

| 변수 | 용도 | 기본값 |
|---|---|---|
| `DC_DB_PATH` | 대시보드가 읽을 DB 경로 | `dcinside.db` |
| `OPENROUTER_API_KEY` | LLM 백엔드(OpenRouter) | — |
| `ANTHROPIC_API_KEY` | LLM 백엔드(Anthropic 직접) | — |
| `DC_LLM_MODEL` | LLM 모델 | OpenRouter: `anthropic/claude-sonnet-5` · Anthropic: `claude-sonnet-5` |

`run.sh`가 시작 시 `.env`를 자동 로드한다. 수집 갤러리·딜레이 등은 CLI 옵션 또는 `dc_scraper/config.py`.

---

## 9. 테스트

| 위치 | 대상 | 방식 |
|---|---|---|
| `dc_scraper/tests/` | 파서·DB·수집 오케스트레이션 | 실제 HTML/JSON 픽스처(오프라인) |
| `tests/test_analysis.py` | 분석 함수 전반 | 임시 SQLite 픽스처(`sample_db`) |
| `tests/test_webapp.py` | FastAPI 엔드포인트 | TestClient |
| `tests/test_llm.py` | LLM 래퍼·keyword_report·`/analysis/llm_status` API | `llm.set_override`로 네트워크 없이 모킹 |
| `tests/test_agent.py` | `llm_agent.discover_keywords`/`deep_report`·`/analysis/ask`·`ask_history` API | `llm.set_override`/`set_tool_loop_override`로 네트워크 없이 모킹 |

`pytest`로 전체 실행(테스트=pytest, 린트=`ruff check`). LLM 테스트는 실제 API를 호출하지 않는다.

---

## 10. 확장 포인트

- **다른 갤러리/사이트**: `config.py`의 `GALLERY_KIND`/`GALLTYPE`/셀렉터 조정.
- **LLM 백엔드 교체**: `llm.py`의 `complete()`/`run_tools()` 분기만 확장(현재 OpenRouter/Anthropic).
- **검색 고도화**: 현재 `discover_keywords`는 키워드 LIKE 매칭 기반. 임베딩 시맨틱 검색(v3)으로
  동의어·표현 다양성 한계를 보완하는 안이 [analysis-improvement-proposal.md §8-4](./analysis-improvement-proposal.md)에 후보로 남아있다.
- **새 분석 축**: `analysis/`에 모듈 추가 → `api.py`에 라우트 → 대시보드 카드. (감성 분석 등은
  과거 사전 기반으로 시도했다가 신뢰도 문제로 제거된 이력이 있음 — 재도입 시 LLM 기반을 우선 검토.)
- **성능**: 분석 결과 캐시 테이블 패턴(`llm_reports`)을 다른 무거운 분석에도 적용 가능.
