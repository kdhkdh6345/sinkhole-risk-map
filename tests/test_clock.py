"""
tests/test_clock.py — Clock 모듈 단위 테스트.

수용 기준 2번 검증:
  AcceleratedClock(speed=3600)에서 실시간 1초 경과 시
  now()가 약 3600초 증가한다.
"""

import time

import pytest

from sinkhole.core.clock import AcceleratedClock, RealClock


class TestRealClock:
    """RealClock 기본 동작 검증."""

    def test_now_returns_float(self) -> None:
        """now()가 float을 반환해야 한다."""
        clock = RealClock()
        result = clock.now()
        assert isinstance(result, float)

    def test_now_increases_over_time(self) -> None:
        """두 번 호출 시 두 번째 값이 더 커야 한다."""
        clock = RealClock()
        t0 = clock.now()
        time.sleep(0.01)
        t1 = clock.now()
        assert t1 > t0

    def test_now_close_to_system_time(self) -> None:
        """now()가 실제 시스템 시각(time.time())과 1초 이내 차이여야 한다."""
        clock = RealClock()
        assert abs(clock.now() - time.time()) < 1.0


class TestAcceleratedClock:
    """AcceleratedClock 동작 검증."""

    def test_speed_1_behaves_like_real_clock(self) -> None:
        """speed=1일 때 실제 시계와 거의 동일하게 흘러야 한다."""
        clock = AcceleratedClock(speed=1.0)
        t0 = clock.now()
        time.sleep(0.1)
        t1 = clock.now()
        # 0.1초 실시간 → 약 0.1초 가상 (오차 허용: 50ms)
        assert 0.05 < (t1 - t0) < 0.15

    def test_speed_3600_one_real_second(self) -> None:
        """수용 기준 2번: speed=3600일 때 실시간 1초 → 가상 3600초.

        오차 허용: ±100초 (시스템 스케줄러 지연 고려)
        """
        clock = AcceleratedClock(speed=3600)
        t0 = clock.now()
        time.sleep(1.0)
        t1 = clock.now()
        elapsed_virtual = t1 - t0
        assert 3500 < elapsed_virtual < 3700, (
            f"speed=3600에서 1초 실시간 경과 시 가상 경과가 "
            f"{elapsed_virtual:.1f}초여야 합니다 (기대: 3500~3700)"
        )

    def test_speed_100_proportional(self) -> None:
        """speed=100일 때 실시간 0.1초 → 가상 약 10초."""
        clock = AcceleratedClock(speed=100)
        t0 = clock.now()
        time.sleep(0.1)
        t1 = clock.now()
        elapsed_virtual = t1 - t0
        assert 8 < elapsed_virtual < 12, (
            f"speed=100에서 0.1초 실시간 → {elapsed_virtual:.2f}초 가상 (기대: 8~12)"
        )

    def test_invalid_speed_raises(self) -> None:
        """speed가 0 이하이면 ValueError를 발생시켜야 한다."""
        with pytest.raises(ValueError):
            AcceleratedClock(speed=0)
        with pytest.raises(ValueError):
            AcceleratedClock(speed=-1)

    def test_custom_start_time(self) -> None:
        """start 인자로 기준 시각을 지정할 수 있어야 한다."""
        epoch = 1_000_000.0
        clock = AcceleratedClock(speed=1.0, start=epoch)
        # 생성 직후 now()가 epoch와 가까워야 한다 (오차: 0.1초)
        assert abs(clock.now() - epoch) < 0.1

    def test_speed_property(self) -> None:
        """speed 프로퍼티가 올바른 값을 반환해야 한다."""
        clock = AcceleratedClock(speed=42.0)
        assert clock.speed == 42.0

    def test_reset_restarts_virtual_time(self) -> None:
        """reset() 후 now()가 새 기준 시각 근처에서 시작해야 한다."""
        clock = AcceleratedClock(speed=3600)
        time.sleep(0.05)  # 약 180초 가상 경과
        new_epoch = 500_000.0
        clock.reset(start=new_epoch)
        assert abs(clock.now() - new_epoch) < 1.0
