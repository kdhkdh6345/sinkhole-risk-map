"""
clock.py — 시각 추상화 모듈.

규칙 (AGENTS.md 2절 2항):
  "time.time()을 로직 안에서 직접 호출하지 않는다.
   반드시 주입된 Clock 객체를 통해 현재 시각을 얻는다."

이 모듈이 저장소 내에서 time.time()을 호출하는 유일한 위치다.
다른 모듈에서 time.time()을 직접 호출하는 것은 절대 금지한다.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """시각 획득 인터페이스.

    모든 계산 로직은 이 프로토콜을 통해 현재 시각을 얻는다.
    실시간 모드에는 RealClock, 시뮬레이션·시연에는 AcceleratedClock을 주입한다.
    """

    def now(self) -> float:
        """현재 시각을 Unix 타임스탬프(초) 단위로 반환한다."""
        ...


class RealClock:
    """실제 시스템 시계를 사용하는 Clock 구현.

    실시간 모드(GitHub Actions cron, 실제 API 연동)에서 사용한다.
    """

    def now(self) -> float:
        """현재 Unix 타임스탬프(초)를 반환한다.

        저장소 내에서 time.time()이 직접 등장하는 유일한 위치.
        """
        return time.time()


class AcceleratedClock:
    """speed배 빠른 가상 시계.

    시뮬레이션 시연 및 감쇠 테스트에 사용한다.
    실제 경과 시간에 speed를 곱해 기준 시각(epoch)에 더한 값을 반환한다.

    예시:
        clock = AcceleratedClock(speed=3600)
        # 실시간 1초 경과 → now()가 약 3600초 증가
        # 실시간 1분 경과 → now()가 약 216,000초(60h) 증가

    Args:
        speed:  시간 배속. 1.0 = 실시간. 3600 = 1초가 1시간.
        start:  가상 시계의 기준 시각 (Unix 타임스탬프).
                None이면 AcceleratedClock 생성 시점의 실제 시각을 사용.
    """

    def __init__(self, speed: float, start: float | None = None) -> None:
        if speed <= 0:
            raise ValueError(f"speed는 양수여야 합니다. 입력값: {speed}")
        self._speed = speed
        # 가상 시계 기준 시각 (이 시점부터 가상 시간이 흐른다)
        self._virtual_start: float = start if start is not None else time.time()
        # 실제 시계 기준 시각 (경과 시간 계산에 사용)
        self._real_start: float = time.time()

    def now(self) -> float:
        """가속된 현재 시각을 Unix 타임스탬프(초) 단위로 반환한다.

        계산식:
            virtual_now = virtual_start + (real_elapsed * speed)
            real_elapsed = time.time() - real_start
        """
        real_elapsed = time.time() - self._real_start
        return self._virtual_start + real_elapsed * self._speed

    @property
    def speed(self) -> float:
        """현재 배속을 반환한다."""
        return self._speed

    def reset(self, start: float | None = None) -> None:
        """가상 시계를 리셋한다.

        Args:
            start: 새 기준 시각. None이면 현재 실제 시각을 사용.
        """
        self._real_start = time.time()
        self._virtual_start = start if start is not None else time.time()

    def set_virtual_time(self, virtual_now: float) -> None:
        """가상 현재 시각을 지정한 값으로 강제 설정한다.

        테스트 전용: 감쇠 곡선 검증 등 특정 가상 시각에서 상태를 확인할 때 사용.
        실제 운영 코드에서는 호출하지 않는다.

        Args:
            virtual_now: 설정할 가상 타임스탬프 (초)
        """
        self._real_start = time.time()
        self._virtual_start = virtual_now

