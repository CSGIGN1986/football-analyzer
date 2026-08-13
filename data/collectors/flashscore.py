"""
FlashScore 数据采集器 v4 — Playwright inner_text 直接提取

使用 Playwright 浏览器直接提取积分榜、比分数据。
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class FlashScoreCollector:
    """FlashScore 数据采集器"""

    BASE_URL = "https://www.flashscore.com"

    LEAGUES = {
        "eng_premier": ("/football/england/premier-league/", "英超"),
        "esp_la_liga": ("/football/spain/laliga/", "西甲"),
        "ita_serie_a": ("/football/italy/serie-a/", "意甲"),
        "ger_bundesliga": ("/football/germany/bundesliga/", "德甲"),
        "fra_ligue_1": ("/football/france/ligue-1/", "法甲"),
        "ned_eredivisie": ("/football/netherlands/eredivisie/", "荷甲"),
        "por_primeira": ("/football/portugal/liga-portugal/", "葡超"),
        "bra_serie_a": ("/football/brazil/serie-a/", "巴甲"),
        "swe_allsvenskan": ("/football/sweden/allsvenskan/", "瑞超"),
        "nor_eliteserien": ("/football/norway/eliteserien/", "挪超"),
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/flashscore")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._p = None
        self._browser = None

    def _get_browser(self):
        """懒加载浏览器"""
        if self._browser:
            return self._browser, self._p

        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        chrome = os.path.expandvars(
            r"%USERPROFILE%\.agent-browser\browsers\chrome-151.0.7922.77\chrome.exe"
        )
        if not os.path.exists(chrome):
            chrome = None
        self._browser = self._p.chromium.launch(
            headless=True, executable_path=chrome,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        return self._browser, self._p

    def get_standings(self, league_key: str) -> List[Dict]:
        """获取联赛积分榜"""
        info = self.LEAGUES.get(league_key)
        if not info:
            return []

        url_path, cn_name = info
        url = f"{self.BASE_URL}{url_path}standings/"
        
        browser, _ = self._get_browser()
        page = browser.new_page()
        
        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(3000)

            rows = page.query_selector_all(".ui-table__row")
            standings = []

            for row in rows:
                try:
                    text = row.inner_text()
                    if not text.strip():
                        continue
                    
                    parts = text.strip().split("\n")
                    # 格式: rank, team, P, W, D, L, GF:GA, Pts, (extra)
                    if len(parts) >= 8:
                        rank = self._safe_int(parts[0].replace(".", ""))
                        team = parts[1]
                        played = self._safe_int(parts[2])
                        wins = self._safe_int(parts[3])
                        draws = self._safe_int(parts[4])
                        losses = self._safe_int(parts[5])
                        goals = parts[6].split(":")
                        gf = self._safe_int(goals[0])
                        ga = self._safe_int(goals[1]) if len(goals) > 1 else 0
                        pts = self._safe_int(parts[7])

                        if team and rank:
                            standings.append({
                                "rank": rank,
                                "teamName": team,
                                "played": played or 0,
                                "wins": wins or 0,
                                "draws": draws or 0,
                                "losses": losses or 0,
                                "goalsFor": gf or 0,
                                "goalsAgainst": ga or 0,
                                "goalDiff": (gf or 0) - (ga or 0),
                                "points": pts or 0,
                                "league": league_key,
                                "source": "flashscore",
                            })
                except Exception as e:
                    logger.debug(f"行解析失败: {e}")

            return standings
        finally:
            page.close()

    def get_results(self, league_key: str) -> List[Dict]:
        """获取联赛近期赛果（含比分）"""
        info = self.LEAGUES.get(league_key)
        if not info:
            return []

        url_path, cn_name = info
        url = f"{self.BASE_URL}{url_path}results/"

        browser, _ = self._get_browser()
        page = browser.new_page()

        try:
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            events = page.query_selector_all(".event__match")
            results = []

            for event in events:
                try:
                    text = event.inner_text()
                    if not text.strip():
                        continue
                    parts = [p for p in text.strip().split("\n") if p.strip()]
                    # 格式: 日期时间 / 主队 / 客队 / 主比分 / 客比分
                    if len(parts) >= 5:
                        results.append({
                            "time": parts[0],
                            "homeTeam": parts[1],
                            "awayTeam": parts[2],
                            "homeScore": self._safe_int(parts[3]),
                            "awayScore": self._safe_int(parts[4]),
                            "league": league_key,
                            "source": "flashscore",
                        })
                except Exception as e:
                    logger.debug(f"  赛果解析失败: {e}")

            return results
        finally:
            page.close()

    def collect_results(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """采集赛果"""
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        logger.info(f"采集 FlashScore 赛果 ({len(league_keys)} 个联赛)...")
        all_results = {}

        for key in league_keys:
            try:
                cn = self.LEAGUES.get(key, ("", key))[1]
                results = self.get_results(key)
                if results:
                    all_results[key] = results
                    logger.info(f"  {cn}: {len(results)} 场赛果")
                time.sleep(2)
            except Exception as e:
                logger.error(f"  {cn} 赛果失败: {e}")

        return all_results

    def collect_standings(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """采集积分榜"""
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        logger.info(f"采集 FlashScore 积分榜 ({len(league_keys)} 个联赛)...")
        all_standings = {}

        for key in league_keys:
            try:
                cn = self.LEAGUES.get(key, ("", key))[1]
                standings = self.get_standings(key)
                if standings:
                    all_standings[key] = standings
                    logger.info(f"  {cn}: {len(standings)} 队 (top: {standings[0]['teamName']})")
                else:
                    logger.warning(f"  {cn}: 无数据")
                time.sleep(2)
            except Exception as e:
                logger.error(f"  {cn} 失败: {e}")

        return all_standings

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        """采集全部数据"""
        standings = self.collect_standings(league_keys)

        if self._browser:
            self._browser.close()
        if self._p:
            self._p.stop()

        result = {
            "source": "flashscore.com",
            "fetchTime": datetime.now().isoformat(),
            "totalLeagues": len(standings),
            "standings": standings,
        }

        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"flashscore_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")

        return result

    @staticmethod
    def _safe_int(val) -> Optional[int]:
        try:
            return int(str(val).strip())
        except (ValueError, TypeError):
            return None
