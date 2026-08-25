"""
KMA 5km 격자 좌표 ↔ 위경도 변환 유틸리티
기상청 동네예보(단기예보) 격자 기준

격자 사양:
  - 전국 격자: 동서 149 × 남북 253 = 37,697개
  - 격자 간격: 5km
  - 투영법: Lambert Conformal Conic (LCC)
"""

import math
from typing import Tuple


class KMAGrid:
    """기상청 5km 격자 좌표 변환기 (Lambert Conformal Conic)"""

    RE = 6371.00877   # 지구 반경 (km)
    GRID = 5.0        # 격자 간격 (km)
    SLAT1 = 30.0      # 표준 위도 1 (°N)
    SLAT2 = 60.0      # 표준 위도 2 (°N)
    OLON = 126.0      # 기준 경도 (°E)
    OLAT = 38.0       # 기준 위도 (°N)
    XO = 210 / 2      # 기준점 격자 X (= 105)
    YO = 675 / 2      # 기준점 격자 Y (= 337.5)

    def __init__(self):
        DEGRAD = math.pi / 180.0
        re = self.RE / self.GRID
        slat1 = self.SLAT1 * DEGRAD
        slat2 = self.SLAT2 * DEGRAD
        olon  = self.OLON * DEGRAD
        olat  = self.OLAT * DEGRAD

        sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
        sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
        sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
        sf = math.pow(sf, sn) * math.cos(slat1) / sn
        ro = math.tan(math.pi * 0.25 + olat * 0.5)
        ro = re * sf / math.pow(ro, sn)

        self._sn = sn
        self._sf = sf
        self._ro = ro
        self._re = re
        self._olon = olon
        self._olat = olat

    def latlon_to_grid(self, lat: float, lon: float) -> Tuple[int, int]:
        """위경도 → 격자 (nx, ny) 변환 (1-indexed)"""
        DEGRAD = math.pi / 180.0
        re = self._re
        sn = self._sn
        sf = self._sf
        ro = self._ro

        ra = math.tan(math.pi * 0.25 + lat * DEGRAD * 0.5)
        ra = re * sf / math.pow(ra, sn)
        theta = lon * DEGRAD - self._olon
        if theta > math.pi:
            theta -= 2.0 * math.pi
        if theta < -math.pi:
            theta += 2.0 * math.pi
        theta *= sn

        nx = int(ra * math.sin(theta) + self.XO + 1.5)
        ny = int(ro - ra * math.cos(theta) + self.YO + 1.5)
        return nx, ny

    def grid_to_latlon(self, nx: int, ny: int) -> Tuple[float, float]:
        """격자 (nx, ny) → 위경도 변환 (1-indexed)"""
        DEGRAD = math.pi / 180.0
        RADDEG = 180.0 / math.pi
        re = self._re
        sn = self._sn
        sf = self._sf
        ro = self._ro

        xn = nx - 1 - self.XO
        yn = ro - (ny - 1 - self.YO)
        ra = math.sqrt(xn * xn + yn * yn)
        if sn < 0:
            ra = -ra

        alat = math.pow((re * sf / ra), (1.0 / sn))
        alat = 2.0 * math.atan(alat) - math.pi * 0.5

        if abs(xn) <= 0 and abs(yn) <= 0:
            alon = self._olon
        else:
            if abs(yn) <= 0:
                theta = math.pi * 0.5
                if xn < 0:
                    theta = -theta
            else:
                theta = math.atan2(xn, yn)
            alon = theta / sn + self._olon

        lat = alat * RADDEG
        lon = alon * RADDEG
        return lat, lon

    def all_grid_centers(self, nx_max: int = 149, ny_max: int = 253):
        """전체 격자 중심 위경도 목록 반환 (DataFrame용)"""
        records = []
        for ny in range(1, ny_max + 1):
            for nx in range(1, nx_max + 1):
                lat, lon = self.grid_to_latlon(nx, ny)
                records.append({"nx": nx, "ny": ny, "lat": lat, "lon": lon})
        return records


# ── 간단 테스트 ─────────────────────────────────────────────
if __name__ == "__main__":
    g = KMAGrid()

    # 서울 시청 (37.5665, 126.9780) → 격자 확인
    lat, lon = 37.5665, 126.9780
    nx, ny = g.latlon_to_grid(lat, lon)
    print(f"서울 시청 → 격자 ({nx}, {ny})")

    # 역변환
    lat2, lon2 = g.grid_to_latlon(nx, ny)
    print(f"격자 ({nx}, {ny}) → ({lat2:.4f}°N, {lon2:.4f}°E)")
    print(f"오차: {abs(lat-lat2)*111:.1f}km (위도), {abs(lon-lon2)*89:.1f}km (경도)")
