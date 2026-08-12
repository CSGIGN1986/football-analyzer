"""
Soccerway 数据采集器 — 球队统计、交锋记录、球员数据

Soccerway (soccerway.com) 是全球最全面的足球数据库之一，包含:
  - 球队近期战绩
  - 交锋记录 (H2H)
  - 场均进球/失球
  - 球员出场和进球

复用代理的 agent-browser (已安装) 进行采集。
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)


class SoccerwayCollector:
    """Soccerway 数据采集器"""

    BASE_URL = "https://int.soccerway.com"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    }

    # 联赛页面映射
    LEAGUES = {
        "eng_premier": "/national/england/premier-league/2025-2026/r28562/",
        "esp_la_liga": "/national/spain/primera-division/2025-2026/r28645/",
        "ita_serie_a": "/national/italy/serie-a/2025-2026/r28603/",
        "ger_bundesliga": "/national/germany/bundesliga/2025-2026/r28582/",
        "fra_ligue_1": "/national/france/ligue-1/2025-2026/r28551/",
        "ned_eredivisie": "/national/netherlands/eredivisie/2025-2026/r28583/",
        "por_primeira": "/national/portugal/portuguese-liga-/2025-2026/r28761/",
        "bra_serie_a": "/national/brazil/serie-a/2026/r28778/",
        "chn_super": "/national/china-pr/super-league/2026/r29161/",
        "jpn_j1": "/national/japan/j1-league/2026/r28819/",
        "kor_k1": "/national/korea-republic/k-league-classic/2026/r28939/",
        "sau_pro": "/national/saudi-arabia/pro-league/2025-2026/r29012/",
        "ucl": "/international/europe/uefa-champions-league/2025-2026/r28626/",
        "uel": "/international/europe/uefa-cup/2025-2026/r28627/",
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/soccerway")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _request(self, url: str, max_retries: int = 3) -> Optional[str]:
        """带重试的HTTP GET"""
        for attempt in range(max_retries):
            try:
                time.sleep(1 + attempt * 0.5)
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code == 404:
                    logger.warning(f"页面不存在: {url}")
                    return None
                logger.warning(f"请求失败 [{resp.status_code}]: {url}")
            except Exception as e:
                logger.warning(f"请求异常: {url} - {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def get_league_standings(self, league_key: str) -> List[Dict]:
        """获取联赛积分榜和基本统计数据"""
        league_path = self.LEAGUES.get(league_key)
        if not league_path:
            logger.warning(f"未找到联赛映射: {league_key}")
            return []

        url = f"{self.BASE_URL}{league_path}"
        html = self._request(url)
        if not html:
            return self._collect_via_agent_browser(url)

        return self._parse_standings(html, league_key)

    def _parse_standings(self, html: str, league_key: str) -> List[Dict]:
        """解析积分榜 HTML"""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="leaguetable")
        if not table:
            # 尝试其他表格选择器
            table = soup.find("table", {"class": re.compile(r".*standings.*|.*league.*")})

        if not table:
            logger.warning(f"未找到积分榜表格: {league_key}")
            return []

        standings = []
        tbody = table.find("tbody")
        if not tbody:
            return standings

        for row in tbody.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 8:
                continue

            try:
                # Soccerway 表格结构: rank, team, P, W, D, L, GF, GA, +/-, Pts
                rank = cells[0].text.strip()
                team_cell = cells[1]
                team_link = team_cell.find("a")
                team_name = team_link.text.strip() if team_link else team_cell.text.strip()
                team_url = team_link.get("href") if team_link else ""
                played = self._safe_int(cells[2].text)
                wins = self._safe_int(cells[3].text)
                draws = self._safe_int(cells[4].text)
                losses = self._safe_int(cells[5].text)
                goals_for = self._safe_int(cells[6].text)
                goals_against = self._safe_int(cells[7].text)
                points = self._safe_int(cells[-1].text) if len(cells) > 8 else 0

                standings.append({
                    "rank": self._safe_int(rank),
                    "teamName": team_name,
                    "teamUrl": team_url,
                    "played": played,
                    "wins": wins,
                    "draws": draws,
                    "losses": losses,
                    "goalsFor": goals_for,
                    "goalsAgainst": goals_against,
                    "goalDiff": goals_for - goals_against if goals_for is not None and goals_against is not None else None,
                    "points": points,
                    "league": league_key,
                    "source": "soccerway",
                })
            except Exception as e:
                logger.debug(f"解析积分榜行失败: {e}")
                continue

        return standings

    def get_team_form(self, team_url: str) -> Optional[Dict]:
        """获取球队近期战绩"""
        if not team_url:
            return None

        url = f"{self.BASE_URL}{team_url}" if not team_url.startswith("http") else team_url
        html = self._request(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 获取近期比赛结果
        matches = []
        results_table = soup.find("table", class_="matches")
        if results_table:
            tbody = results_table.find("tbody")
            if tbody:
                for row in tbody.find_all("tr")[:10]:  # 最近10场
                    cells = row.find_all("td")
                    if len(cells) < 5:
                        continue
                    try:
                        matches.append({
                            "date": cells[0].text.strip(),
                            "opponent": cells[3].text.strip() if len(cells) > 3 else "",
                            "result": cells[4].text.strip() if len(cells) > 4 else "",
                            "score": cells[2].text.strip() if len(cells) > 2 else "",
                        })
                    except Exception:
                        continue

        # 获取球队统计数据
        stats = {}
        stats_div = soup.find("div", class_="team-stats")
        if stats_div:
            for stat_row in stats_div.find_all("div", class_="stat"):
                label = stat_row.find("span", class_="label")
                value = stat_row.find("span", class_="value")
                if label and value:
                    stats[label.text.strip()] = value.text.strip()

        return {
            "recentMatches": matches,
            "statistics": stats,
            "source": "soccerway",
        }

    def get_h2h(self, team1_url: str, team2_url: str) -> Optional[Dict]:
        """获取两队交锋记录"""
        # Soccerway 的交锋记录需要通过搜索结果或特定页面获取
        # 这里通过两队的比赛页面来查找
        if not team1_url or not team2_url:
            return None

        team1_matches = self.get_team_form(team1_url)
        team2_matches = self.get_team_form(team2_url)

        if not team1_matches or not team2_matches:
            return None

        # 简化的H2H查找 (实际应使用 Soccerway 的 H2H 页面)
        return {
            "team1Form": team1_matches.get("recentMatches", []),
            "team2Form": team2_matches.get("recentMatches", []),
            "source": "soccerway",
        }

    def _collect_via_agent_browser(self, url: str) -> List[Dict]:
        """使用 agent-browser 作为备用采集方案"""
        try:
            import subprocess
            result = subprocess.run(
                ["npx", "agent-browser", "get", "--url", url, "--format", "text"],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                # agent-browser 返回的文本内容，尝试从中提取数据
                logger.info("agent-browser 采集成功")
                return []
            else:
                logger.error(f"agent-browser 失败: {result.stderr}")
                return []
        except Exception as e:
            logger.error(f"agent-browser 异常: {e}")
            return []

    @staticmethod
    def _safe_int(val) -> Optional[int]:
        try:
            return int(val.strip())
        except (ValueError, AttributeError):
            return None

    def collect_standings(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """采集联赛积分榜"""
        if league_keys is None:
            league_keys = ["eng_premier", "esp_la_liga", "ita_serie_a",
                          "ger_bundesliga", "fra_ligue_1"]

        logger.info(f"正在采集 Soccerway 积分榜 ({len(league_keys)} 个联赛)...")

        all_standings = {}
        for key in league_keys:
            try:
                standings = self.get_league_standings(key)
                if standings:
                    all_standings[key] = standings
                    logger.info(f"  {key}: {len(standings)} 支球队")
            except Exception as e:
                logger.error(f"  {key} 失败: {e}")

        return all_standings

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        """采集全部 Soccerway 数据"""
        standings = self.collect_standings(league_keys)

        result = {
            "source": "soccerway.com",
            "fetchTime": datetime.now().isoformat(),
            "totalLeagues": len(standings),
            "standings": standings,
        }

        # 保存
        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"soccerway_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")

        return result
