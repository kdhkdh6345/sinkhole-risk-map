"""
cli.py — 싱크홀 위험도 지도 진입점.

사용법:
    python -m sinkhole.cli --mode real
    python -m sinkhole.cli --mode sim --scenario heavy_rain
"""

import argparse


def main() -> None:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="서울시 싱크홀 위험도 지도 계산 엔진"
    )
    parser.add_argument(
        "--mode",
        choices=["real", "sim"],
        default="sim",
        help="실행 모드: real(실시간 API) / sim(시뮬레이션)",
    )
    parser.add_argument(
        "--scenario",
        choices=["calm", "heavy_rain", "extreme"],
        default="calm",
        help="시뮬레이션 시나리오 (--mode sim 일 때만 사용)",
    )
    args = parser.parse_args()
    print(f"[Phase 0 stub] mode={args.mode}, scenario={args.scenario}")
    print("아직 구현되지 않았습니다. Phase 3에서 완성됩니다.")


if __name__ == "__main__":
    main()
