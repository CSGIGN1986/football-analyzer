"""
FBref 数据采集器 v2 — 基于 Playwright 浏览器

采集: xG、射门等进阶统计数据
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


class FBrefCollector:
    """FBref 进阶数据采集器 (Playwright)"""

    BASE_URL = "https://fbref.com"

    LEAGUES = {
        "eng_premier": ("/en/comps/9/Premier-League-Stats", "英超"),
        "esp_la_liga": ("/en/comps/12/La-Liga-Stats", "西甲"),
        "ita_serie_a": ("/en/comps/11/Serie-A-Stats", "意甲"),
        "ger_bundesliga": ("/en/comps/20/Bundesliga-Stats", "德甲"),
        "fra_ligue_1": ("/en/comps/13/Ligue-1-Stats", "法甲"),
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/fbref")
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
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        return self._browser, self._p

    def get_team_stats(self, league_key: str) -> List[Dict]:
        """获取球队统计数据（含xG）"""
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
        table = soup.find("table", id="stats_squads_standard_for")
        if not table:
            logger.warning(f"  未找到 {league_key} xG 表格")
            return []

        stats = []
        tbody = table.find("tbody")
        if not tbody:
            return stats

        for tr in tbody.find_all("tr"):
            if "class" in tr.attrs and "thead" in tr.attrs.get("class", []):
                continue
            cells = tr.find_all(["th", "td"])
            if len(cells) < 10:
                continue
            try:
                squad = cells[0].get_text(strip=True)
                xg = self._safe_float(cells[9].get_text(strip=True))
                stats.append({
                    "squad": squad,
                    "xg": xg,
                    "league": league_key,
                    "source": "fbref",
                })
            except Exception as e:
                logger.debug(f"  行解析失败: {e}")

        return stats

    def collect_xg_data(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        logger.info(f"采集 FBref xG 数据 ({len(league_keys)} 个联赛)...")
        all_stats = {}

        for key in league_keys:
            try:
                cn = self.LEAGUES.get(key, ("", key))[1]
                stats = self.get_team_stats(key)
                if stats:
                    all_stats[key] = stats
                    logger.info(f"  {cn}: {len(stats)} 队")
                time.sleep(3)
            except Exception as e:
                logger.error(f"  {cn} 失败: {e}")

        return all_stats

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        xg_data = self.collect_xg_data(league_keys)

        if self._browser:
            self._browser.close()
        if self._p:
            self._p.stop()

        result = {
            "source": "fbref.com",
            "fetchTime": datetime.now().isoformat(),
            "totalLeagues": len(xg_data),
            "xgData": xg_data,
        }

        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"fbref_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")
        return result

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return None
