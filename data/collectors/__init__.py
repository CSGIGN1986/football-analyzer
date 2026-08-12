"""
数据采集器模块 — 多源足球数据采集

数据源:
  1. sporttery.cn  — 竞彩赛程 + 赔率 (API)
  2. 500.com       — 竞彩历史赛果、赔率变化
  3. FlashScore    — 国际比赛赛程/赛果/积分榜 (API + 网页)
  4. FBref         — xG 等进阶数据 (网页)
  5. Soccerway     — 球队统计、交锋记录 (网页)
  6. Transfermarkt — 球队身价、伤停 (网页)
"""

from .sporttery import SportteryCollector
from .five_hundred import FiveHundredCollector
from .flashscore import FlashScoreCollector
from .fbref import FBrefCollector
from .soccerway import SoccerwayCollector

__all__ = [
    "SportteryCollector",
    "FiveHundredCollector",
    "FlashScoreCollector",
    "FBrefCollector",
    "SoccerwayCollector",
]
