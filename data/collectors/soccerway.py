"""
Soccerway 数据采集器 v3 — Playwright + .ui-table 结构

Soccerway 与 FlashScore 同属一家，使用相同的 .ui-table 结构。
URL 结构: https://int.soccerway.com/{country}/{league}/ (2026/27 赛季无需季节路径)
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SoccerwayCollector:
    """Soccerway 数据采集器"""

    BASE_URL = "https://int.soccerway.com"

    # 联赛 URL (2026/27 赛季)
    LEAGUES = {
        "eng_premier": ("/england/premier-league/", "英超"),
        "esp_la_liga": ("/spain/primera-division/", "西甲"),
        "ita_serie_a": ("/italy/serie-a/", "意甲"),
        "ger_bundesliga": ("/germany/bundesliga/", "德甲"),
        "fra_ligue_1": ("/france/ligue-1/", "法甲"),
        "ned_eredivisie": ("/netherlands/eredivisie/", "荷甲"),
        "por_primeira": ("/portugal/portuguese-liga-/", "葡超"),
        "bra_serie_a": ("/brazil/serie-a/", "巴甲"),
        "chn_super": ("/china-pr/super-league/", "中超"),
        "jpn_j1": ("/japan/j1-league/", "日职"),
        "kor_k1": ("/korea-republic/k-league-1/", "韩K"),
        "saudi_pro": ("/saudi-arabia/pro-league/", "沙职"),
        "ucl": ("/europe/uefa-champions-league/", "欧冠"),
        "uel": ("/europe/uefa-cup/", "欧罗巴"),
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
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        return self._browser, self._p

    def get_standings(self, league_key: str) -> List[Dict]:
        info = self.LEAGUES.get(league_key)
        if not info:
            return []

        url = f"{self.BASE_URL}{info[0]}standings/"
        browser, _ = self._get_browser()
        page = browser.new_page()

        try:
            page.goto(url, timeout=25000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)

            ui_table = page.query_selector(".ui-table")
            if not ui_table:
                logger.warning(f"  未找到 {league_key} 积分榜")
                return []

            rows = ui_table.query_selector_all(".ui-table__row")
            standings = []

            for row in rows:
                try:
                    text = row.inner_text()
                    if not text.strip():
                        continue
                    parts = text.strip().split("\n")
                    # Soccerway 格式: rank. / team / MP / W / D / L / G(0:0) / GD / PTS / FORM
                    if len(parts) >= 9:
                        rank = self._safe_int(parts[0].replace(".", ""))
                        team = parts[1]
                        played = self._safe_int(parts[2])
                        wins = self._safe_int(parts[3])
                        draws = self._safe_int(parts[4])
                        losses = self._safe_int(parts[5])
                        goals = parts[6].split(":")
                        gf = self._safe_int(goals[0])
                        ga = self._safe_int(goals[1]) if len(goals) > 1 else 0
                        gd = self._safe_int(parts[7])
                        pts = self._safe_int(parts[8])

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
                                "goalDiff": gd or ((gf or 0) - (ga or 0)),
                                "points": pts or 0,
                                "league": league_key,
                                "source": "soccerway",
                            })
                except Exception as e:
                    logger.debug(f"  行解析失败: {e}")

            return standings
        finally:
            page.close()

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
                    logger.info(f"  {cn}: {len(standings)} 队 (top: {standings[0]['teamName']})")
                else:
                    logger.warning(f"  {cn}: 无数据")
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
