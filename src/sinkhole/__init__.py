"""
sinkhole — 서울시 싱크홀 위험도 지도 계산 엔진.

패키지 구조:
  core/          상태 관리, Clock, 스냅샷 저장
  grid/          격자 생성, 좌표→격자 매핑
  static_layers/ 정적 기저점수 B 계산
  sources/       데이터 소스 어댑터 (실시간 / 시뮬레이션)
  fusion/        감쇠, 융합, 이상탐지, 점수화
"""
