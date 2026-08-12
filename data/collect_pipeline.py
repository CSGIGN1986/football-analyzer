#!/usr/bin/env python3
"""
统一数据采集管道 — 足球分析预测系统的数据入口

功能:
  1. 从多源采集足球数据
  2. 数据清洗和标准化
  3. 存入 SQLite 数据库
  4. 支持定时每日更新

用法:
  python -m data.collect_pipeline          # 采集全部数据源
  python -m data.collect_pipeline --source sporttery   # 仅采集竞彩
  python -m data.collect_pipeline --source flashscore  # 仅采集FlashScore
  python -m data.collect_pipeline --source all --db-only  # 仅入库
"""

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

# 设置路径
import os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg
from data.database import FootballDB
from data.collectors.sporttery import SportteryCollector
from data.collectors.flashscore import FlashScoreCollector
from data.collectors.fbref import FBrefCollector
from data.collectors.soccerway import SoccerwayCollector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(cfg.LOGS_DIR / "collect_pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("collect_pipeline")


class DataPipeline:
    """统一数据采集管道"""

    # 竞彩联赛名 -> 数据库 league_id 映射
    JC_LEAGUE_MAP = {
        "英超": "eng_premier", "西甲": "esp_la_liga",
        "意甲": "ita_serie_a", "德甲": "ger_bundesliga",
        "法甲": "fra_ligue_1", "荷甲": "ned_eredivisie",
        "葡超": "por_primeira", "巴甲": "bra_serie_a",
        "瑞超": "swe_allsvenskan", "挪超": "nor_eliteserien",
        "芬超": "fin_veikkausliiga", "日职": "jpn_j1",
        "韩K联": "kor_k1", "美职联": "usa_mls",
        "欧冠": "ucl", "欧罗巴": "uel",
        "亚冠精英": "afc_cl", "欧超杯": "ucl",
        "解放者杯": "bra_serie_a",
    }

    def __init__(self):
        self.db = FootballDB()
        self.db.init_schema()

    def collect_sporttery(self) -> List[Dict]:
        """采集竞彩数据"""
        collector = SportteryCollector()
        result = collector.collect_all()
        return result.get("matches", [])

    def collect_flashscore(self) -> dict:
        """采集 FlashScore 数据"""
        collector = FlashScoreCollector()
        return collector.collect_all()

    def collect_fbref(self) -> dict:
        """采集 FBref xG 数据"""
        collector = FBrefCollector()
        return collector.collect_all()

    def collect_soccerway(self) -> dict:
        """采集 Soccerway 积分榜"""
        collector = SoccerwayCollector()
        return collector.collect_all()

    def collect_500(self) -> dict:
        """采集 500.com 数据"""
        from data.collectors.five_hundred import FiveHundredCollector
        collector = FiveHundredCollector()
        return collector.collect_all()

    def _map_league(self, jc_league_name: str) -> Optional[str]:
        """竞彩联赛名映射到内部 league_id"""
        return self.JC_LEAGUE_MAP.get(jc_league_name)

    def _extract_team_code(self, team_name: str, league_id: str) -> str:
        """从队名生成 team_id"""
        # 简单哈希
        raw = f"{league_id}_{team_name}"
        import hashlib
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def ingest_sporttery(self, matches: List[Dict]) -> int:
        """将竞彩数据写入数据库"""
        count = 0
        today = datetime.now().strftime("%Y-%m-%d")

        for m in matches:
            try:
                league_name = m.get("league", "")
                league_id = self._map_league(league_name)
                if not league_id:
                    # 动态创建联赛记录
                    league_id = f"jc_{league_name.lower().replace(' ', '_')}"
                    self.db.upsert_league({
                        "league_id": league_id,
                        "name": league_name,
                        "country": "",
                        "tier": 1,
                        "season": "2026",
                    })

                home_team = m.get("homeTeam", "")
                away_team = m.get("awayTeam", "")
                home_team_id = self._extract_team_code(home_team, league_id)
                away_team_id = self._extract_team_code(away_team, league_id)

                # 写入球队
                self.db.upsert_team({
                    "team_id": home_team_id,
                    "name": home_team,
                    "short_name": home_team,
                    "country": "",
                    "league_id": league_id,
                    "elo_rating": 1500.0,
                    "attack_strength": 1.0,
                    "defense_strength": 1.0,
                    "home_advantage": 0.0,
                })
                self.db.upsert_team({
                    "team_id": away_team_id,
                    "name": away_team,
                    "short_name": away_team,
                    "country": "",
                    "league_id": league_id,
                    "elo_rating": 1500.0,
                    "attack_strength": 1.0,
                    "defense_strength": 1.0,
                    "home_advantage": 0.0,
                })

                # 生成 match_id
                match_num = m.get("matchNumStr", "")
                match_id = f"jc_{m.get('matchNum', 0)}_{today.replace('-', '')}"

                # 写入比赛
                self.db.upsert_match({
                    "match_id": match_id,
                    "league_id": league_id,
                    "season": "2026",
                    "match_date": m.get("matchDate", today),
                    "home_team_id": home_team_id,
                    "away_team_id": away_team_id,
                    "home_team_name": home_team,
                    "away_team_name": away_team,
                    "home_score": None,
                    "away_score": None,
                    "home_ht_score": None,
                    "away_ht_score": None,
                    "status": "scheduled",
                    "round_name": f"{m.get('weekday', '')} {m.get('matchNumStr', '')}",
                })

                # 写入赔率
                odds = m.get("odds", {})
                had = odds.get("HAD", {})
                self.db.upsert_odds({
                    "match_id": match_id,
                    "home_odds": float(had.get("h", 0)) if had.get("h") else None,
                    "draw_odds": float(had.get("d", 0)) if had.get("d") else None,
                    "away_odds": float(had.get("a", 0)) if had.get("a") else None,
                    "over_25_odds": None,
                    "under_25_odds": None,
                    "source": "sporttery",
                })

                count += 1
            except Exception as e:
                logger.warning(f"写入比赛失败 [{m.get('matchNumStr', '?')}]: {e}")

        return count

    def ingest_flashscore_standings(self, standings: Dict[str, List[Dict]]) -> int:
        """将 FlashScore 积分榜写入数据库"""
        count = 0
        for league_key, teams in standings.items():
            for team in teams:
                try:
                    team_name = team.get("teamName", "")
                    team_id = self._extract_team_code(team_name, league_key)

                    self.db.upsert_team({
                        "team_id": team_id,
                        "name": team_name,
                        "short_name": team_name[:10],
                        "country": "",
                        "league_id": league_key,
                        "elo_rating": 1500.0,
                        "attack_strength": 1.0,
                        "defense_strength": 1.0,
                        "home_advantage": 0.0,
                    })
                    count += 1
                except Exception as e:
                    logger.warning(f"写入球队失败: {e}")

        return count

    def run(self, sources: Optional[List[str]] = None, db_only: bool = False):
        """执行完整采集管道"""
        if sources is None:
            sources = ["sporttery", "flashscore", "fbref", "soccerway"]

        logger.info("=" * 60)
        logger.info(f"数据采集管道启动 - {datetime.now().isoformat()}")
        logger.info(f"数据源: {sources}")
        logger.info("=" * 60)

        results = {}

        # 1. 竞彩数据 (最高优先级，不需要浏览器)
        if "sporttery" in sources:
            try:
                logger.info("\n[1] 采集竞彩数据...")
                matches = self.collect_sporttery()
                results["sporttery"] = {"matches": len(matches)}
                ingest_count = self.ingest_sporttery(matches)
                logger.info(f"  ✓ 采集 {len(matches)} 场，入库 {ingest_count} 场")
            except Exception as e:
                logger.error(f"  竞彩采集失败: {e}")
                results["sporttery"] = {"error": str(e)}

        # 2. FlashScore 数据
        if "flashscore" in sources:
            try:
                logger.info("\n[2] 采集 FlashScore 数据...")
                fs_data = self.collect_flashscore()
                standings = fs_data.get("standings", {})
                results["flashscore"] = {
                    "matches": fs_data.get("totalMatches", 0),
                    "leagues": len(standings),
                }
                ingest_count = self.ingest_flashscore_standings(standings)
                logger.info(f"  ✓ {len(standings)} 个联赛，入库 {ingest_count} 支球队")
            except Exception as e:
                logger.error(f"  FlashScore 失败: {e}")
                results["flashscore"] = {"error": str(e)}

        # 3. FBref xG 数据
        if "fbref" in sources:
            try:
                logger.info("\n[3] 采集 FBref xG 数据...")
                fbref_data = self.collect_fbref()
                results["fbref"] = {"leagues": fbref_data.get("totalLeagues", 0)}
                logger.info(f"  ✓ {fbref_data.get('totalLeagues', 0)} 个联赛")
            except Exception as e:
                logger.error(f"  FBref 失败: {e}")
                results["fbref"] = {"error": str(e)}

        # 4. Soccerway 积分榜
        if "soccerway" in sources:
            try:
                logger.info("\n[4] 采集 Soccerway 积分榜...")
                sw_data = self.collect_soccerway()
                results["soccerway"] = {"leagues": sw_data.get("totalLeagues", 0)}
                logger.info(f"  ✓ {sw_data.get('totalLeagues', 0)} 个联赛")
            except Exception as e:
                logger.error(f"  Soccerway 失败: {e}")
                results["soccerway"] = {"error": str(e)}

        # 汇总
        logger.info("\n" + "=" * 60)
        logger.info("采集完成!")
        for source, result in results.items():
            if "error" in result:
                logger.info(f"  {source}: ❌ {result['error']}")
            else:
                logger.info(f"  {source}: ✓ {result}")
        logger.info("=" * 60)

        # 检查数据库状态
        leagues = self.db.get_leagues()
        teams = self.db.get_teams()
        upcoming = self.db.get_upcoming_matches()
        logger.info(f"\n数据库状态: {len(leagues)} 联赛, {len(teams)} 球队, {len(upcoming)} 待预测比赛")

        return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="足球数据采集管道")
    parser.add_argument("--source", choices=["sporttery", "flashscore", "fbref",
                                              "soccerway", "500", "all"],
                        default="all", help="数据源")
    parser.add_argument("--db-only", action="store_true", help="仅执行数据库入库")
    args = parser.parse_args()

    if args.source == "all":
        sources = ["sporttery", "flashscore", "fbref", "soccerway"]
    else:
        sources = [args.source]

    pipeline = DataPipeline()
    pipeline.run(sources=sources)


if __name__ == "__main__":
    main()
