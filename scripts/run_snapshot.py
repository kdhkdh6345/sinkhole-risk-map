"""
run_snapshot.py — 1회 실행 스냅샷 생성 스크립트.

GitHub Actions cron이 호출하는 진입점.
Phase 3(시뮬), Phase 5(배포), Phase 6(실제 API)에서 단계적으로 구현됩니다.

실행 예시:
    python scripts/run_snapshot.py --mode sim --scenario heavy_rain
    python scripts/run_snapshot.py --mode real
"""

import argparse


def main() -> None:
    """스냅샷 생성 진입점."""
    parser = argparse.ArgumentParser(description="싱크홀 위험도 스냅샷 생성")
    parser.add_argument("--mode", choices=["real", "sim"], default="sim")
    parser.add_argument(
        "--scenario", choices=["calm", "heavy_rain", "extreme"], default="calm"
    )
    args = parser.parse_args()
    print(f"[Phase 0 stub] run_snapshot.py mode={args.mode} scenario={args.scenario}")
    print("Phase 3에서 실제 snapshot.json이 생성됩니다.")


if __name__ == "__main__":
    main()
