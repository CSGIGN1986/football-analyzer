"""
Football-Data.co.uk 数据采集器 — 历史赛果 + 完整统计数据 + 博彩赔率

免费 CSV 数据源，包含:
  - 全场/半场比分
  - 射门、射正、犯规、角球、黄牌、红牌
  - 多家博彩公司欧赔 (B365/BW/PS/WH/VC/LB 等)
  - 大小球赔率 (>2.5 / <2.5)
  - 亚盘让球赔率 (Asian Handicap)
  - 收盘赔率 (Closing odds)

这是训练足球预测模型的黄金数据源。
"""

import csv
import io
import logging
import ssl
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 联赛代码映射 (football-data.co.uk 标准代码)
LEAGUES = {
    # 欧洲五大联赛
    "eng_premier": ("E0", "英超", "england"),
    "eng_championship": ("E1", "英冠", "england"),
    "ger_bundesliga": ("D1", "德甲", "germany"),
    "ger_bundesliga2": ("D2", "德乙", "germany"),
    "ita_serie_a": ("I1", "意甲", "italy"),
    "ita_serie_b": ("I2", "意乙", "italy"),
    "esp_la_liga": ("SP1", "西甲", "spain"),
    "esp_la_liga2": ("SP2", "西乙", "spain"),
    "fra_ligue_1": ("F1", "法甲", "france"),
    "fra_ligue_2": ("F2", "法乙", "france"),
    # 其他欧洲联赛
    "ned_eredivisie": ("N1", "荷甲", "netherlands"),
    "por_primeira": ("P1", "葡超", "portugal"),
    "bel_pro_league": ("B1", "比甲", "belgium"),
    "tur_super_lig": ("T1", "土超", "turkey"),
    "gre_super_league": ("G1", "希腊超", "greece"),
    "sco_premiership": ("SC0", "苏超", "scotland"),
    # 北欧
    "swe_allsvenskan": ("SWE", "瑞超", "sweden"),
    "nor_eliteserien": ("NOR", "挪超", "norway"),
    "den_superliga": ("DEN", "丹超", "denmark"),
    "fin_veikkausliiga": ("FIN", "芬超", "finland"),
    # 其他
    "pol_ekstraklasa": ("POL", "波甲", "poland"),
    "cze_first_league": ("CZE", "捷甲", "czech"),
    "aut_bundesliga": ("AUT", "奥甲", "austria"),
    "sui_super_league": ("SUI", "瑞士超", "switzerland"),
    "rus_premier": ("RUS", "俄超", "russia"),
    "usa_mls": ("USA", "美职联", "usa"),
    "mex_liga_mx": ("MEX", "墨超", "mexico"),
    "arg_primera": ("ARG", "阿甲", "argentina"),
    "bra_serie_a": ("BRA", "巴甲", "brazil"),
    "chn_super": ("CHN", "中超", "china"),
    "jpn_j1": ("JPN", "日职", "japan"),
}

# 关键字段映射 (CSV列 -> 内部字段)
FIELD_MAP = {
    "Div": "div",
    "Date": "date",
    "Time": "time",
    "HomeTeam": "homeTeam",
    "AwayTeam": "awayTeam",
    "FTHG": "fullTimeHomeGoals",
    "FTAG": "fullTimeAwayGoals",
    "FTR": "fullTimeResult",
    "HTHG": "halfTimeHomeGoals",
    "HTAG": "halfTimeAwayGoals",
    "HTR": "halfTimeResult",
    "HS": "homeShots",
    "AS": "awayShots",
    "HST": "homeShotsOnTarget",
    "AST": "awayShotsOnTarget",
    "HF": "homeFouls",
    "AF": "awayFouls",
    "HC": "homeCorners",
    "AC": "awayCorners",
    "HY": "homeYellow",
    "AY": "awayYellow",
    "HR": "homeRed",
    "AR": "awayRed",
    # 平均欧赔
    "AvgH": "avgHomeOdds",
    "AvgD": "avgDrawOdds",
    "AvgA": "avgAwayOdds",
    # 平均大小球
    "Avg>2.5": "avgOver25",
    "Avg<2.5": "avgUnder25",
    # 平均亚盘
    "AvgAHH": "avgAsianHandicapHome",
    "AvgAHA": "avgAsianHandicapAway",
    "AHh": "asianHandicapLine",
    # 收盘赔率
    "AvgCH": "avgCloseHome",
    "AvgCD": "avgCloseDraw",
    "AvgCA": "avgCloseAway",
    "AvgC>2.5": "avgCloseOver25",
    "AvgC<2.5": "avgCloseUnder25",
}


class FootballDataCollector:
    """Football-Data.co.uk 历史数据采集器"""

    BASE_URL = "https://www.football-data.co.uk/mmz4281"

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/football_data")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = False

    def _fetch_csv(self, league_code: str, season: str) -> Optional[List[Dict]]:
        """获取指定联赛、赛季的 CSV 数据"""
        url = f"{self.BASE_URL}/{season}/{league_code}.csv"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=self.ctx, timeout=20) as r:
                data = r.read().decode("utf-8-sig", errors="replace")

            reader = csv.DictReader(io.StringIO(data))
            rows = []
            for row in reader:
                # 只保留有比分的比赛（已完成的）
                if row.get("FTHG") and row.get("FTAG"):
                    rows.append(row)
            return rows
        except Exception as e:
            logger.warning(f"  获取失败 {league_code}/{season}: {e}")
            return None

    def _parse_row(self, row: Dict, league_key: str, league_cn: str, season: str) -> Dict:
        """解析一行 CSV 数据"""
        match = {"league": league_key, "leagueCn": league_cn, "season": season}

        for csv_field, internal_field in FIELD_MAP.items():
            if csv_field in row:
                val = row[csv_field].strip() if row[csv_field] else ""
                match[internal_field] = val

        # 数值字段转换
        for field in ["fullTimeHomeGoals", "fullTimeAwayGoals", "halfTimeHomeGoals",
                      "halfTimeAwayGoals", "homeShots", "awayShots", "homeShotsOnTarget",
                      "awayShotsOnTarget", "homeFouls", "awayFouls", "homeCorners",
                      "awayCorners", "homeYellow", "awayYellow", "homeRed", "awayRed"]:
            if field in match:
                match[field] = self._safe_int(match[field])

        for field in ["avgHomeOdds", "avgDrawOdds", "avgAwayOdds", "avgOver25",
                      "avgUnder25", "avgAsianHandicapHome", "avgAsianHandicapAway",
                      "avgCloseHome", "avgCloseDraw", "avgCloseAway",
                      "avgCloseOver25", "avgCloseUnder25"]:
            if field in match:
                match[field] = self._safe_float(match[field])

        # 统一日期格式 DD/MM/YYYY -> YYYY-MM-DD
        if match.get("date"):
            try:
                d = match["date"].split("/")
                if len(d) == 3:
                    match["date"] = f"{d[2]}-{d[1]}-{d[0]}"
            except Exception:
                pass

        match["source"] = "football-data.co.uk"
        return match

    def collect_league(self, league_key: str, seasons: List[str]) -> List[Dict]:
        """采集指定联赛多个赛季的数据"""
        code, cn, _ = LEAGUES.get(league_key, (None, league_key, ""))
        if not code:
            logger.warning(f"  未找到联赛代码: {league_key}")
            return []

        all_matches = []
        for season in seasons:
            rows = self._fetch_csv(code, season)
            if rows:
                parsed = [self._parse_row(r, league_key, cn, season) for r in rows]
                all_matches.extend(parsed)
                logger.info(f"  {cn} {season}: {len(parsed)} 场")

        return all_matches

    def collect_all(self, league_keys: Optional[List[str]] = None,
                    seasons: Optional[List[str]] = None) -> dict:
        """采集全部历史数据"""
        if league_keys is None:
            # 默认采集竞彩覆盖的核心联赛
            league_keys = [
                "eng_premier", "ger_bundesliga", "ita_serie_a",
                "esp_la_liga", "fra_ligue_1", "ned_eredivisie",
                "por_primeira", "swe_allsvenskan", "nor_eliteserien",
                "fin_veikkausliiga", "bra_serie_a",
            ]
        if seasons is None:
            # 默认采集最近 3 个赛季
            seasons = ["2324", "2425", "2526"]

        logger.info(f"采集 football-data.co.uk 历史数据 ({len(league_keys)} 联赛 x {len(seasons)} 赛季)...")

        all_data = {}
        total = 0
        for key in league_keys:
            cn = LEAGUES.get(key, ("", key, ""))[1]
            matches = self.collect_league(key, seasons)
            if matches:
                all_data[key] = matches
                total += len(matches)
                logger.info(f"  {cn}: 共 {len(matches)} 场")

        result = {
            "source": "football-data.co.uk",
            "fetchTime": datetime.now().isoformat(),
            "totalMatches": total,
            "totalLeagues": len(all_data),
            "seasons": seasons,
            "matches": all_data,
        }

        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"football_data_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            import json
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path} ({total} 场比赛)")

        return result

    @staticmethod
    def _safe_int(val) -> Optional[int]:
        try:
            return int(str(val).strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        try:
            return float(str(val).strip())
        except (ValueError, TypeError):
            return None
