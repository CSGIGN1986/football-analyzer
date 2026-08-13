"""
sporttery.cn 数据采集器 — 竞彩足球赛程 + 赔率

API 端点:
  - 赛程列表: /gateway/uniform/football/getMatchListV1.qry?clientCode=3001
  - 详细赔率: /gateway/jc/football/getMatchCalculatorV1.qry
"""

import json
import ssl
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

import urllib.request

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sporttery.cn/jc/zqszsc/",
    "Accept": "application/json, text/plain, */*",
}

POOL_NAMES = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球数",
    "HAFU": "半全场胜平负",
}

SELL_STATUS = {
    "1": "已开售",
    "0": "待开售",
    "2": "暂停销售",
}


class SportteryCollector:
    """竞彩官网数据采集器"""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/sporttery")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ctx = ssl.create_default_context()

    def _fetch(self, url: str, timeout: int = 30) -> dict:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_schedule(self) -> dict:
        """获取赛程列表（含基础赔率）"""
        url = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
        return self._fetch(url)

    def get_calculator(self) -> dict:
        """获取详细赔率计算器数据"""
        url = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?pageSize=100"
        return self._fetch(url)

    def parse_odds(self, odds_list: list) -> dict:
        result = {}
        for item in odds_list:
            pool = item.get("poolCode", "")
            if not pool:
                continue
            result[pool] = {
                "h": item.get("h", ""),
                "d": item.get("d", ""),
                "a": item.get("a", ""),
                "goalLine": item.get("goalLine", ""),
                "updateTime": item.get("updateTime", ""),
            }
        return result

    def parse_pool_status(self, pool_list: list) -> dict:
        result = {}
        for item in pool_list:
            pool = item.get("poolCode", "")
            if not pool:
                continue
            result[pool] = {
                "status": item.get("poolStatus", ""),
                "single": item.get("cbtSingle", 0),
                "allUp": item.get("cbtAllUp", 0),
            }
        return result

    def collect_schedule_matches(self) -> List[Dict]:
        """采集赛程比赛列表"""
        raw = self.get_schedule()
        value = raw.get("value", {})
        match_info_list = value.get("matchInfoList", [])

        matches = []
        for day_data in match_info_list:
            weekday = day_data.get("weekday", "")
            business_date = day_data.get("businessDate", "")
            for m in day_data.get("subMatchList", []):
                match = {
                    "matchNumStr": m.get("matchNumStr", ""),
                    "matchNum": m.get("matchNum", 0),
                    "league": m.get("leagueAbbName", ""),
                    "leagueFull": m.get("leagueAllName", ""),
                    "leagueId": m.get("leagueId", ""),
                    "homeTeam": m.get("homeTeamAllName", "") or m.get("homeTeamAbbName", ""),
                    "awayTeam": m.get("awayTeamAllName", "") or m.get("awayTeamAbbName", ""),
                    "homeTeamId": m.get("homeTeamId", 0),
                    "awayTeamId": m.get("awayTeamId", 0),
                    "matchDate": m.get("matchDate", ""),
                    "matchTime": m.get("matchTime", ""),
                    "matchDatetime": f"{m.get('matchDate', '')} {m.get('matchTime', '')}",
                    "matchId": m.get("matchId", 0),
                    "weekday": weekday,
                    "businessDate": business_date,
                    "sellStatus": SELL_STATUS.get(m.get("sellStatus", ""), m.get("sellStatus", "")),
                    "odds": self.parse_odds(m.get("oddsList", [])),
                    "poolStatus": self.parse_pool_status(m.get("poolList", [])),
                    "remark": m.get("remark", ""),
                    "source": "sporttery",
                }
                matches.append(match)

        return matches

    def collect_detailed_odds(self) -> dict:
        """采集详细赔率数据"""
        raw = self.get_calculator()
        value = raw.get("value", {})
        match_info_list = value.get("matchInfoList", [])

        detailed = {}
        for day_data in match_info_list:
            for m in day_data.get("subMatchList", []):
                match_num = m.get("matchNumStr", "")
                if not match_num:
                    continue

                odds_detail = {}
                for pool_code in ["HAD", "HHAD", "CRS", "TTG", "HAFU"]:
                    pool_key = pool_code.lower()
                    if pool_code == "HHAD":
                        pool_key = "hhad"
                    pool_data = m.get(pool_key, {})
                    if pool_data and any(pool_data.values()):
                        odds_detail[pool_code] = pool_data

                detailed[match_num] = {
                    "homeTeam": m.get("homeTeamAbbName", ""),
                    "awayTeam": m.get("awayTeamAbbName", ""),
                    "homeRank": m.get("homeRank", ""),
                    "awayRank": m.get("awayRank", ""),
                    "oddsDetail": odds_detail,
                }

        return detailed

    def collect_all(self) -> dict:
        """采集全部数据"""
        logger.info("正在采集竞彩官网数据...")
        matches = self.collect_schedule_matches()
        logger.info(f"  赛程: {len(matches)} 场比赛")

        detailed = self.collect_detailed_odds()
        logger.info(f"  详细赔率: {len(detailed)} 场比赛")

        # 合并
        for m in matches:
            key = m["matchNumStr"]
            if key in detailed:
                m["homeRank"] = detailed[key].get("homeRank", "")
                m["awayRank"] = detailed[key].get("awayRank", "")
                m["oddsDetail"] = detailed[key].get("oddsDetail", {})

        result = {
            "source": "sporttery.cn",
            "fetchTime": datetime.now().isoformat(),
            "totalMatches": len(matches),
            "matches": matches,
        }

        # 保存
        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"sporttery_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"  已保存: {json_path}")

        return result
