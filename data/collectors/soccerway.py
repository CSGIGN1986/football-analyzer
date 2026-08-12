"""
Soccerway 数据采集器 v2 — 基于 Playwright 浏览器

采集: 积分榜、球队统计
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SoccerwayCollector:
    """Soccerway 数据采集器 (Playwright)"""

    BASE_URL = "https://int.soccerway.com"

    LEAGUES = {
        "eng_premier": ("/national/england/premier-league/2025-2026/r28562/", "英超"),
        "esp_la_liga": ("/national/spain/primera-division/2025-2026/r28645/", "西甲"),
        "ita_serie_a": ("/national/italy/serie-a/2025-2026/r28603/", "意甲"),
        "ger_bundesliga": ("/national/germany/bundesliga/2025-2026/r28582/", "德甲"),
        "fra_ligue_1": ("/national/france/ligue-1/2025-2026/r28551/", "法甲"),
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/soccerway")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._p = None
        self._browser = None

    def _get_browser(self):
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
            args=["--no-sandbox"],
        )
        return self._browser, self._p

    def get_standings(self, league_key: str) -> List[Dict]:
        info = self.LEAGUES.get(league_key)
        if not info:
            return []

        url = f"{self.BASE_URL}{info[0]}"
        browser, _ = self._get_browser()
        page = browser.new_page()

        try:
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(3000)
            html = page.content()
        finally:
            page.close()

        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="leaguetable")
        if not table:
            # Try generic table
            table = soup.find("table")

        if not table:
            logger.warning(f"  未找到 {league_key} 表格")
            return []

        standings = []
        tbody = table.find("tbody")
        if not tbody:
            return standings

        for tr in tbody.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 8:
                continue
            try:
                rank = self._safe_int(cells[0].get_text(strip=True))
                team = cells[1].get_text(strip=True)
                played = self._safe_int(cells[2].get_text(strip=True))
                wins = self._safe_int(cells[3].get_text(strip=True))
                draws = self._safe_int(cells[4].get_text(strip=True))
                losses = self._safe_int(cells[5].get_text(strip=True))
                gf = self._safe_int(cells[6].get_text(strip=True))
                ga = self._safe_int(cells[7].get_text(strip=True))
                pts = self._safe_int(cells[-1].get_text(strip=True)) if len(cells) > 8 else 0

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
                        "source": "soccerway",
                    })
            except Exception:
                continue

        return standings

    def collect_standings(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        logger.info(f"采集 Soccerway 积分榜 ({len(league_keys)} 个联赛)...")
        all_standings = {}

        for key in league_keys:
            try:
                cn = self.LEAGUES.get(key, ("", key))[1]
                standings = self.get_standings(key)
                if standings:
                    all_standings[key] = standings
                    logger.info(f"  {cn}: {len(standings)} 队")
                time.sleep(2)
            except Exception as e:
                logger.error(f"  {cn} 失败: {e}")

        return all_standings

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        standings = self.collect_standings(league_keys)

        if self._browser:
            self._browser.close()
        if self._p:
            self._p.stop()

        result = {
            "source": "soccerway.com",
            "fetchTime": datetime.now().isoformat(),
            "totalLeagues": len(standings),
            "standings": standings,
        }

        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"soccerway_{date_str}.json"
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
