"""
FBref 数据采集器 — xG、射门、控球等进阶统计数据

FBref (fbref.com) 是足球进阶数据最权威的免费来源，包含:
  - xG (预期进球)
  - xGA (预期失球)
  - 射门/射正
  - 控球率
  - 传球数据

使用 requests + BeautifulSoup 即可，无需浏览器。
"""

import json
import logging
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class FBrefCollector:
    """FBref 进阶数据采集器"""

    BASE_URL = "https://fbref.com"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # League URL mappings
    LEAGUES = {
        "eng_premier": "/en/comps/9/Premier-League-Stats",
        "esp_la_liga": "/en/comps/12/La-Liga-Stats",
        "ita_serie_a": "/en/comps/11/Serie-A-Stats",
        "ger_bundesliga": "/en/comps/20/Bundesliga-Stats",
        "fra_ligue_1": "/en/comps/13/Ligue-1-Stats",
        "ned_eredivisie": "/en/comps/23/Eredivisie-Stats",
        "por_primeira": "/en/comps/32/Primeira-Liga-Stats",
        "bra_serie_a": "/en/comps/24/Serie-A-Stats",
        "usa_mls": "/en/comps/22/Major-League-Soccer-Stats",
        "sco_premiership": "/en/comps/40/Scottish-Premiership-Stats",
        "bel_pro_league": "/en/comps/37/Belgian-Pro-League-Stats",
        "aut_bundesliga": "/en/comps/56/Austrian-Bundesliga-Stats",
        "sui_super_league": "/en/comps/58/Swiss-Super-League-Stats",
        "tur_super_lig": "/en/comps/26/Super-Lig-Stats",
        "gre_super_league": "/en/comps/27/Super-League-Greece-Stats",
        "pol_ekstraklasa": "/en/comps/36/Ekstraklasa-Stats",
        "cze_first_league": "/en/comps/55/Czech-First-League-Stats",
        "den_superliga": "/en/comps/50/Danish-Superliga-Stats",
        "nor_eliteserien": "/en/comps/28/Eliteserien-Stats",
        "swe_allsvenskan": "/en/comps/29/Allsvenskan-Stats",
        "rus_premier": "/en/comps/30/Russian-Premier-League-Stats",
        "arg_primera": "/en/comps/21/Primera-Division-Stats",
        "mex_liga_mx": "/en/comps/31/Liga-MX-Stats",
        "jpn_j1": "/en/comps/25/J1-League-Stats",
        "kor_k1": "/en/comps/55/K-League-1-Stats",
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/fbref")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _request(self, url: str) -> Optional[str]:
        """发送请求"""
        for attempt in range(3):
            try:
                time.sleep(random.uniform(3, 6))  # FBref 有频率限制
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 429:
                    wait = 30 * (attempt + 1)
                    logger.warning(f"FBref 限流，等待 {wait}s...")
                    time.sleep(wait)
                else:
                    logger.warning(f"请求失败 [{resp.status_code}]: {url}")
            except Exception as e:
                logger.warning(f"请求异常: {url} - {e}")
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        return None

    def _parse_table(self, soup: BeautifulSoup, table_id: str) -> List[Dict]:
        """解析 FBref 标准表格"""
        table = soup.find("table", id=table_id)
        if not table:
            return []

        rows = []
        tbody = table.find("tbody")
        if not tbody:
            return []

        # 获取表头
        headers = []
        thead = table.find("thead")
        if thead:
            for th in thead.find_all("tr")[-1].find_all("th"):
                headers.append(th.get("data-stat", th.text.strip()))

        for tr in tbody.find_all("tr"):
            if "class" in tr.attrs and "thead" in tr.attrs.get("class", []):
                continue

            cells = tr.find_all(["th", "td"])
            if len(cells) < 5:
                continue

            row_data = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                val = cell.text.strip()
                # 尝试转数字
                try:
                    val = float(val)
                except ValueError:
                    pass
                row_data[key] = val

            if row_data.get("player") or row_data.get("squad"):
                rows.append(row_data)

        return rows

    def get_team_stats(self, league_key: str) -> List[Dict]:
        """获取球队统计数据（xG, 射门, 控球等）"""
        league_url = self.LEAGUES.get(league_key)
        if not league_url:
            logger.warning(f"未找到联赛映射: {league_key}")
            return []

        url = f"{self.BASE_URL}{league_url}"
        html = self._request(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")

        # 获取球队标准数据表 (含 xG)
        stats = self._parse_table(soup, "stats_squads_standard_for")
        for s in stats:
            s["league"] = league_key
            s["source"] = "fbref"
            s["type"] = "team_stats"

        return stats

    def get_match_shooting(self, league_key: str) -> List[Dict]:
        """获取球队射门数据"""
        league_url = self.LEAGUES.get(league_key)
        if not league_url:
            return []

        url = f"{self.BASE_URL}{league_url}"
        html = self._request(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        shooting = self._parse_table(soup, "stats_squads_shooting_for")
        for s in shooting:
            s["league"] = league_key
            s["source"] = "fbref"
            s["type"] = "shooting"

        return shooting

    def get_scores_and_fixtures(self, league_key: str) -> List[Dict]:
        """获取比分和赛程（含xG）"""
        league_url = self.LEAGUES.get(league_key)
        if not league_url:
            return []

        # 获取 scores & fixtures 页面
        url = f"{self.BASE_URL}{league_url.replace('-Stats', '-Scores-and-Fixtures')}"
        html = self._request(url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        matches = []

        # 查找比赛表格
        for table in soup.find_all("table"):
            tbody = table.find("tbody")
            if not tbody:
                continue

            for row in tbody.find_all("tr"):
                if "class" in row.attrs and "thead" in row.attrs.get("class", []):
                    continue

                cells = row.find_all(["th", "td"])
                if len(cells) < 8:
                    continue

                try:
                    match = {
                        "date": cells[0].text.strip(),
                        "homeTeam": cells[3].text.strip() if len(cells) > 3 else "",
                        "score": cells[4].text.strip() if len(cells) > 4 else "",
                        "awayTeam": cells[5].text.strip() if len(cells) > 5 else "",
                        "homeXG": cells[6].text.strip() if len(cells) > 6 else "",
                        "awayXG": cells[7].text.strip() if len(cells) > 7 else "",
                        "league": league_key,
                        "source": "fbref",
                    }
                    matches.append(match)
                except Exception:
                    continue

        return matches

    def collect_xg_data(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """采集 xG 数据"""
        if league_keys is None:
            league_keys = ["eng_premier", "esp_la_liga", "ita_serie_a",
                          "ger_bundesliga", "fra_ligue_1"]

        logger.info(f"正在采集 FBref xG 数据 ({len(league_keys)} 个联赛)...")

        all_stats = {}
        for key in league_keys:
            try:
                stats = self.get_team_stats(key)
                if stats:
                    all_stats[key] = stats
                    logger.info(f"  {key}: {len(stats)} 支球队")
                time.sleep(random.uniform(3, 5))  # 尊重 rate limit
            except Exception as e:
                logger.error(f"  {key} 失败: {e}")

        return all_stats

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        """采集全部 FBref 数据"""
        xg_data = self.collect_xg_data(league_keys)

        result = {
            "source": "fbref.com",
            "fetchTime": datetime.now().isoformat(),
            "totalLeagues": len(xg_data),
            "xgData": xg_data,
        }

        # 保存
        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"fbref_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")

        return result
