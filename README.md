# 서울시 싱크홀(지반침하) 위험도 실시간 지도

> **🗺️ 배포 URL**: https://kdhkdh6345.github.io/sinkhole-risk-map/

서울시 전역 500m 격자 단위로 싱크홀(지반침하) 위험도를 실시간 표시하는 지도입니다.  
강수량·지하수위·교통·지반 데이터를 종합해 **1·2·3단계**로 위험도를 산정합니다.

![위험도 지도 스크린샷](docs/screenshot.png)

---

## 위험도 단계

| 단계 | 색상 | 조건 |
|------|------|------|
| 1단계 (초록) | 🟢 | 기저점수 B ≥ 10 |
| 2단계 (노랑) | 🟡 | 1단계 + 강수 R ≥ 15 |
| 3단계 (빨강) | 🔴 | 2단계 + 지하수위 G ≥ 10 |

## 점수 체계

- **B (기저점수, 0~60)**: 하수관 노후도 · 시추공 N값 · 과거 침하 이력 · 액상화 위험등급
- **R (강수, 0~25)**: 1h/3h/12h 누적 강수량 → 기상청 특보 기준 구간 매핑
- **G (지하수위, 0~10)**: σ 이상도 급락 (강수 조건 + 연속 2회 유지)
- **T (교통, 0~5)**: 도로 등급·버스노선 밀도 기반 정적 프록시

감쇠 함수: 이벤트 후 0~24h 유지 → 24~72h 지수감쇠 (72h에 5% 잔존) → 72h+ 소멸

---

## 로컬 실행

```bash
# 1. 의존성 설치
pip install -r requirements.txt

# 2. 격자 생성 (최초 1회)
python scripts/build_grid.py

# 3. 기저점수 계산 (최초 1회)
python scripts/build_baseline.py

# 4. 스냅샷 생성
python scripts/run_snapshot.py --mode sim --scenario extreme

# 5. 웹서버 실행 (http://localhost:8765)
cd web && python -m http.server 8765
```

## 테스트 실행

```bash
python -m pytest -v
```

---

## 프로젝트 구조

```
sinkhole-risk-map/
├── config/
│   ├── grid.yaml          # bbox, 격자 크기, 감쇠 파라미터
│   └── weights.yaml       # 배점·임계값 (코드 하드코딩 금지)
├── data/
│   ├── grid.parquet       # 서울시 500m 격자 2430개
│   ├── baseline.npy       # 정적 기저점수 B
│   └── raw/               # 원본 데이터
├── src/sinkhole/
│   ├── core/              # Clock, GridRiskField, Store
│   ├── fusion/            # 감쇠·점수화·단계판정
│   ├── sources/           # 어댑터 (시뮬·실시간)
│   └── static_layers/     # 기저점수 레이어
├── web/
│   ├── index.html         # 메인 지도
│   ├── js/sim.js          # 브라우저 시뮬 엔진 (Python 동일 로직)
│   ├── js/render.js       # Leaflet 렌더링
│   └── data/              # grid.json, snapshot.json
├── scripts/               # build_grid, build_baseline, run_snapshot
└── tests/                 # pytest (25개 테스트)
```

## 데이터 출처

| 데이터 | 출처 | 비고 |
|--------|------|------|
| 서울시 행정경계 | southkorea/seoul-maps (GitHub) | 25개 자치구 |
| 하수관 노후도 | 2025년 국회 제출 서울시 자료 | 9개 구 실측, 16개 구 추정 |
| 지반 탐사 | 국토교통부 지반정보 (2024.08) | 전기비저항탐사 |
| 강수 기준 | 기상청 호우특보 발령 기준 | 기상법 시행령 |

---

## Phase 진행 현황

- [x] Phase 0 — 저장소 골격, Clock 추상화
- [x] Phase 1 — 서울시 500m 격자 생성 (2430개)
- [x] Phase 2 — 정적 기저점수 B (하수관 노후도)
- [x] Phase 3 — 시뮬레이션 엔진 (감쇠·점수화·단계판정)
- [x] Phase 4 — 웹 지도 (Leaflet, 다크 모드, 시뮬 패널)
- [x] Phase 5 — GitHub Pages 배포 + 자동 갱신
- [ ] Phase 6 — 실제 API 연동 (기상청·GIMS)
- [ ] Phase 7 — 불확실성 정량화

---

*서버 없이 동작하는 정적 지도. Leaflet CDN과 지도 타일 외 외부 의존 없음.*
