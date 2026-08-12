"""
FlashScore 数据采集器 — 国际足球赛程、赛果、积分榜

FlashScore 使用特殊的分隔符格式 (AA÷...¬AA÷) 返回数据。
无需浏览器，直接请求其内部 API 即可获取结构化数据。
"""

import json
import logging
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class FlashScoreCollector:
    """FlashScore 数据采集器"""

    BASE_URL = "https://www.flashscore.com"
    API_BASE = "https://www.flashscore.com/x/feed"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Referer": "https://www.flashscore.com/",
        "X-Requested-With": "XMLHttpRequest",
        "x-fsign": "SW9D1eZo",  # FlashScore specific header
    }

    # 联赛 ID 映射
    LEAGUES = {
        "eng_premier": {"id": "dYlOSQOD", "name": "Premier League", "cn": "英超"},
        "esp_la_liga": {"id": "j9gSXg10", "name": "La Liga", "cn": "西甲"},
        "ita_serie_a": {"id": "d5eQsWaK", "name": "Serie A", "cn": "意甲"},
        "ger_bundesliga": {"id": "G9NqOlOB", "name": "Bundesliga", "cn": "德甲"},
        "fra_ligue_1": {"id": "t7YkW9g2", "name": "Ligue 1", "cn": "法甲"},
        "ned_eredivisie": {"id": "Q7SPYAqK", "name": "Eredivisie", "cn": "荷甲"},
        "por_primeira": {"id": "SK1eKxdO", "name": "Primeira Liga", "cn": "葡超"},
        "bra_serie_a": {"id": "nHc8lqad", "name": "Brasileirão", "cn": "巴甲"},
        "jpn_j1": {"id": "nsN1npMu", "name": "J1 League", "cn": "日职"},
        "kor_k1": {"id": "OwsGsYg0", "name": "K League 1", "cn": "韩K"},
        "swe_allsvenskan": {"id": "02nHl3vr", "name": "Allsvenskan", "cn": "瑞超"},
        "nor_eliteserien": {"id": "ljOll8Xt", "name": "Eliteserien", "cn": "挪超"},
        "den_superliga": {"id": "G2oVKKWh", "name": "Superliga", "cn": "丹超"},
        "fin_veikkausliiga": {"id": "0GFj7QXn", "name": "Veikkausliiga", "cn": "芬超"},
        "sco_premiership": {"id": "tXGdCxnN", "name": "Premiership", "cn": "苏超"},
        "bel_pro_league": {"id": "lrLkbje4", "name": "Pro League", "cn": "比甲"},
        "aut_bundesliga": {"id": "W5aUEOJj", "name": "Bundesliga", "cn": "奥甲"},
        "sui_super_league": {"id": "d3cjQQhk", "name": "Super League", "cn": "瑞士超"},
        "pol_ekstraklasa": {"id": "neCCwWGI", "name": "Ekstraklasa", "cn": "波甲"},
        "cze_first_league": {"id": "j0TS5KED", "name": "First League", "cn": "捷甲"},
        "gre_super_league": {"id": "IHbEKnd7", "name": "Super League", "cn": "希腊超"},
        "tur_super_lig": {"id": "Q4Y5KW7t", "name": "Süper Lig", "cn": "土超"},
        "rus_premier": {"id": "lwgCO4Mh", "name": "Premier Liga", "cn": "俄超"},
        "usa_mls": {"id": "jYjouQpS", "name": "MLS", "cn": "美职联"},
        "mex_liga_mx": {"id": "Ob7jo3WF", "name": "Liga MX", "cn": "墨超"},
        "arg_primera": {"id": "Ok0GV0Mb", "name": "Primera División", "cn": "阿甲"},
        "chi_primera": {"id": "GjcmgI6U", "name": "Primera División", "cn": "智甲"},
        "chn_super": {"id": "IFNqJslf", "name": "Super League", "cn": "中超"},
        "aus_a_league": {"id": "nsnkR0ID", "name": "A-League", "cn": "澳超"},
        "ucl": {"id": "jYtyVxRt", "name": "Champions League", "cn": "欧冠"},
        "uel": {"id": "IJkEDxY0", "name": "Europa League", "cn": "欧罗巴"},
        "saudi_pro": {"id": "zNwr3HRB", "name": "Saudi Pro League", "cn": "沙职"},
        "afc_cl": {"id": "lxVM0w2I", "name": "AFC CL", "cn": "亚冠"},
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/flashscore")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def _request(self, url: str, max_retries: int = 3) -> Optional[str]:
        """带重试的请求"""
        for attempt in range(max_retries):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 200:
                    return resp.text
                logger.warning(f"请求失败 [{resp.status_code}]: {url} (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"请求异常: {url} - {e} (attempt {attempt+1})")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def _parse_flashscore_format(self, text: str) -> List[Dict]:
        """解析 FlashScore 特殊分隔符格式"""
        results = []
        if not text:
            return results

        # FlashScore 格式: AA÷值¬AA÷值¬... 或使用 ~ 分隔
        text = text.replace("¬", "~")
        segments = text.split("~AA÷")

        current = {}
        for seg in segments:
            if not seg or seg == "AA÷":
                continue
            # 解析每个属性
            parts = seg.split("~")
            for part in parts:
                for prefix in ["AD÷", "AE÷", "AF÷", "AG÷", "AH÷",
                               "AC÷", "AB÷", "AX÷", "SA÷", "SD÷",
                               "AA÷", "BB÷", "BC÷", "BD÷", "BG÷",
                               "IA÷", "IB÷", "IC÷", "ID÷", "IE÷",
                               "OA÷", "OB÷", "OC÷", "OD÷", "CX÷",
                               "JB÷", "JC÷", "JD÷", "JE÷", "JF÷",
                               "I÷", "J÷", "K÷", "L÷", "FD÷", "FF÷",
                               "SG÷", "SH÷"]:
                    if part.startswith(prefix):
                        value = part[len(prefix):]
                        current[prefix[:-1]] = value
                        break

            if current:
                results.append(current.copy())

        # 合并为比赛记录
        matches = self._build_matches(results)
        return matches

    def _build_matches(self, rows: List[Dict]) -> List[Dict]:
        """将解析的行数据构建为比赛记录"""
        matches = []
        match = {}
        for row in rows:
            if "AD" in row:  # 日期分隔
                if match:
                    matches.append(match)
                match = {"date": row["AD"]}
            elif "AE" in row:  # 主队
                match["homeTeam"] = row["AE"]
            elif "AF" in row:  # 客队
                match["awayTeam"] = row["AF"]
            elif "AG" in row:  # 主队比分
                try:
                    match["homeScore"] = int(row["AG"])
                except (ValueError, TypeError):
                    match["homeScore"] = None
            elif "AH" in row:  # 客队比分
                try:
                    match["awayScore"] = int(row["AH"])
                except (ValueError, TypeError):
                    match["awayScore"] = None
            elif "AX" in row:  # 状态
                match["status"] = row["AX"]
            elif "AC" in row:  # 比赛ID
                match["matchId"] = row["AC"]

        if match:
            matches.append(match)

        return matches

    def get_matches_by_date(self, league_key: str, match_date: str) -> List[Dict]:
        """获取指定联赛、指定日期的比赛"""
        league = self.LEAGUES.get(league_key)
        if not league:
            logger.warning(f"未找到联赛: {league_key}")
            return []

        # FlashScore API: /x/feed/f_1_{leagueId}_en_1
        url = f"{self.API_BASE}/f_1_{league['id']}_en_1"
        text = self._request(url)
        if not text:
            return []

        matches = self._parse_flashscore_format(text)

        # 过滤指定日期
        if match_date:
            matches = [m for m in matches if m.get("date", "").startswith(match_date)]

        # 添加联赛信息
        for m in matches:
            m["league"] = league["name"]
            m["leagueCn"] = league["cn"]
            m["source"] = "flashscore"

        return matches

    def get_standings(self, league_key: str) -> List[Dict]:
        """获取联赛积分榜"""
        league = self.LEAGUES.get(league_key)
        if not league:
            return []

        url = f"{self.API_BASE}/d_h_{league['id']}_en_1"
        text = self._request(url)
        if not text:
            return []

        # 解析积分榜数据
        standings = []
        text = text.replace("¬", "~")
        rows = text.split("~AA÷")

        for row in rows:
            if "AD÷" not in row:
                continue

            team_data = {}
            parts = row.split("~")
            for part in parts:
                # 积分榜字段
                mappings = {
                    "AD÷": "rank", "AE÷": "teamName", "AF÷": "teamId",
                    "JA÷": "played", "JB÷": "wins", "JC÷": "draws",
                    "JD÷": "losses", "JE÷": "goalsFor", "JF÷": "goalsAgainst",
                    "I÷": "points",
                }
                for prefix, field in mappings.items():
                    if part.startswith(prefix):
                        val = part[len(prefix):]
                        try:
                            team_data[field] = int(val)
                        except (ValueError, TypeError):
                            team_data[field] = val
                        break

            if team_data.get("teamName"):
                team_data["league"] = league["name"]
                team_data["source"] = "flashscore"
                standings.append(team_data)

        return standings

    def collect_live_scores(self, league_keys: Optional[List[str]] = None) -> List[Dict]:
        """采集实时比分"""
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        all_matches = []
        today = datetime.now().strftime("%Y-%m-%d")

        for key in league_keys:
            try:
                matches = self.get_matches_by_date(key, today)
                all_matches.extend(matches)
                logger.info(f"  {self.LEAGUES[key]['cn']}: {len(matches)} 场比赛")
            except Exception as e:
                logger.error(f"  {self.LEAGUES.get(key, {}).get('cn', key)} 失败: {e}")

        return all_matches

    def collect_standings(self, league_keys: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """采集所有联赛积分榜"""
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        all_standings = {}
        for key in league_keys:
            try:
                standings = self.get_standings(key)
                if standings:
                    all_standings[key] = standings
                    logger.info(f"  {self.LEAGUES[key]['cn']} 积分榜: {len(standings)} 队")
            except Exception as e:
                logger.error(f"  积分榜 {key} 失败: {e}")

        return all_standings

    def collect_all(self, league_keys: Optional[List[str]] = None) -> dict:
        """采集全部数据"""
        if league_keys is None:
            league_keys = list(self.LEAGUES.keys())

        logger.info(f"正在采集 FlashScore 数据 ({len(league_keys)} 个联赛)...")

        # 今日比分
        matches = self.collect_live_scores(league_keys)

        # 积分榜
        standings = self.collect_standings(league_keys)

        result = {
            "source": "flashscore.com",
            "fetchTime": datetime.now().isoformat(),
            "totalMatches": len(matches),
            "totalLeagues": len(standings),
            "matches": matches,
            "standings": standings,
        }

        # 保存
        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"flashscore_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")

        return result
