#!/usr/bin/env python3
"""
竞彩足球信息采集脚本
从 sporttery.cn 采集足球竞猜赛程、赔率数据
数据来源: https://www.sporttery.cn/jc/zqszsc/

API:
  赛程列表: webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001
  详细赔率: webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry

输出: JSON 文件保存到 data/ 目录
"""

import json
import os
import ssl
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import urllib.request

BASE_DIR = Path(__file__).parent / "data" / "sporttery"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.sporttery.cn/jc/zqszsc/",
    "Accept": "application/json, text/plain, */*",
}

# 玩法代码映射
POOL_NAMES = {
    "HAD": "胜平负",
    "HHAD": "让球胜平负",
    "CRS": "比分",
    "TTG": "总进球数",
    "HAFU": "半全场胜平负",
}

# 开售状态映射
SELL_STATUS = {
    "1": "已开售",
    "0": "待开售",
    "2": "暂停销售",
    "Selling": "已开售",
    "NoSelling": "待开售",
    "StopSelling": "暂停销售",
}


def fetch_json(url: str, timeout: int = 30) -> dict:
    """获取 JSON 数据"""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_odds(odds_list: list) -> dict:
    """解析赔率列表，返回按玩法组织的赔率数据"""
    result = {}
    for item in odds_list:
        pool = item.get("poolCode", "")
        if not pool:
            continue
        odds_data = {
            "h": item.get("h", ""),  # 主胜
            "d": item.get("d", ""),  # 平局
            "a": item.get("a", ""),  # 客胜
            "goalLine": item.get("goalLine", ""),
        }
        result[pool] = odds_data
    return result


def parse_pool_status(pool_list: list) -> dict:
    """解析各玩法开售状态"""
    result = {}
    for item in pool_list:
        pool = item.get("poolCode", "")
        if not pool:
            continue
        result[pool] = {
            "status": item.get("poolStatus", ""),
            "single": item.get("cbtSingle", 0),  # 是否开单关
            "allUp": item.get("cbtAllUp", 0),  # 是否开过关
        }
    return result


def fetch_schedule() -> dict:
    """获取赛程列表数据 (包含基础赔率)"""
    url = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"
    return fetch_json(url)


def fetch_calculator() -> dict:
    """获取详细赔率计算器数据"""
    url = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry?pageSize=100"
    return fetch_json(url)


def process_schedule(raw: dict) -> list[dict]:
    """处理赛程数据，提取比赛列表"""
    value = raw.get("value", {})
    match_info_list = value.get("matchInfoList", [])
    last_update = value.get("lastUpdateTime", "")

    matches = []
    for day_data in match_info_list:
        weekday = day_data.get("weekday", "")
        business_date = day_data.get("businessDate", "")
        for m in day_data.get("subMatchList", []):
            match = {
                "matchNumStr": m.get("matchNumStr", ""),  # 如 "周日016"
                "matchNum": m.get("matchNum", 0),  # 数字编号如 7016
                "league": m.get("leagueAbbName", ""),
                "leagueFull": m.get("leagueAllName", ""),
                "homeTeam": m.get("homeTeamAllName", "") or m.get("homeTeamAbbName", ""),
                "awayTeam": m.get("awayTeamAllName", "") or m.get("awayTeamAbbName", ""),
                "matchDate": m.get("matchDate", ""),
                "matchTime": m.get("matchTime", ""),
                "matchDatetime": f"{m.get('matchDate', '')} {m.get('matchTime', '')}",
                "matchId": m.get("matchId", 0),
                "weekday": weekday,
                "businessDate": business_date,
                "sellStatus": SELL_STATUS.get(m.get("sellStatus", ""), m.get("sellStatus", "")),
                "matchStatus": m.get("matchStatus", ""),
                "odds": parse_odds(m.get("oddsList", [])),
                "poolStatus": parse_pool_status(m.get("poolList", [])),
                "remark": m.get("remark", ""),
            }
            matches.append(match)

    return matches, last_update


def process_calculator(raw: dict) -> dict:
    """处理计算器数据，提取详细赔率"""
    value = raw.get("value", {})
    match_info_list = value.get("matchInfoList", [])
    last_update = value.get("lastUpdateTime", "")

    detailed = {}
    for day_data in match_info_list:
        for m in day_data.get("subMatchList", []):
            match_num = m.get("matchNumStr", "")
            if not match_num:
                continue

            # 提取各玩法详细赔率
            odds_detail = {}
            for pool_code in ["HAD", "HHAD", "CRS", "TTG", "HAFU"]:
                pool_data = m.get(pool_code.lower(), {})
                if pool_data:
                    odds_detail[pool_code] = pool_data

            detailed[match_num] = {
                "homeTeam": m.get("homeTeamAbbName", ""),
                "awayTeam": m.get("awayTeamAbbName", ""),
                "homeRank": m.get("homeRank", ""),
                "awayRank": m.get("awayRank", ""),
                "matchDatetime": f"{m.get('businessDate', '')} {m.get('matchTime', '')}",
                "oddsDetail": odds_detail,
            }

    return detailed, last_update


def merge_data(schedule_matches: list, calc_detail: dict) -> list[dict]:
    """合并赛程数据和详细赔率"""
    for match in schedule_matches:
        key = match["matchNumStr"]
        if key in calc_detail:
            detail = calc_detail[key]
            match["homeRank"] = detail.get("homeRank", "")
            match["awayRank"] = detail.get("awayRank", "")
            match["oddsDetail"] = detail.get("oddsDetail", {})
        else:
            match["homeRank"] = ""
            match["awayRank"] = ""
            match["oddsDetail"] = {}
    return schedule_matches


def generate_summary(matches: list[dict], last_update: str) -> str:
    """生成可读的文本摘要"""
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"═══════════════════════════════════════",
        f"  竞彩足球赛程 & 赔率报告",
        f"  采集时间: {today}",
        f"  数据更新: {last_update}",
        f"  比赛总数: {len(matches)} 场",
        f"═══════════════════════════════════════",
        "",
    ]

    current_day = ""
    for m in matches:
        day = m["weekday"] + " " + m["businessDate"]
        if day != current_day:
            current_day = day
            lines.append(f"\n{'='*50}")
            lines.append(f"  {day}")
            lines.append(f"{'='*50}")

        odds_had = m["odds"].get("HAD", {})
        odds_hhad = m["odds"].get("HHAD", {})
        had_str = f"{odds_had.get('h','-')}/{odds_had.get('d','-')}/{odds_had.get('a','-')}"
        hhad_str = f"{odds_hhad.get('h','-')}/{odds_hhad.get('d','-')}/{odds_hhad.get('a','-')}"

        handicap = odds_hhad.get("goalLine", "")
        handicap_str = f"({handicap})" if handicap else ""

        lines.append(
            f"  {m['matchNumStr']:8s} | {m['league']:8s} | "
            f"{m['homeTeam']} vs {m['awayTeam']} | "
            f"{m.get('matchDatetime', '')}"
        )
        lines.append(
            f"           SPF: {had_str:20s} | "
            f"RQSPF{handicap_str}: {hhad_str:20s} | "
            f"状态: {m.get('sellStatus', '?')}"
        )

    return "\n".join(lines)


def save_output(matches: list[dict], metadata: dict, suffix: str = "") -> Path:
    """保存数据到 JSON 文件"""
    BASE_DIR.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y%m%d")
    if suffix:
        json_path = BASE_DIR / f"sporttery_{date_str}_{suffix}.json"
    else:
        json_path = BASE_DIR / f"sporttery_{date_str}.json"

    output = {
        "metadata": metadata,
        "matches": matches,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return json_path


def main():
    """主采集流程"""
    print("=" * 60)
    print("竞彩足球信息采集")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. 获取赛程列表
    print("\n[1/3] 获取赛程列表...")
    try:
        schedule_raw = fetch_schedule()
        schedule_matches, schedule_update = process_schedule(schedule_raw)
        print(f"  ✓ 获取到 {len(schedule_matches)} 场比赛 (更新: {schedule_update})")
    except Exception as e:
        print(f"  ✗ 赛程获取失败: {e}")
        # 即使赛程失败，也尝试获取计算器数据
        schedule_matches = []
        schedule_update = ""

    # 2. 获取详细赔率
    print("\n[2/3] 获取详细赔率...")
    try:
        calc_raw = fetch_calculator()
        calc_detail, calc_update = process_calculator(calc_raw)
        print(f"  ✓ 获取到 {len(calc_detail)} 场比赛详情 (更新: {calc_update})")
    except Exception as e:
        print(f"  ✗ 详细赔率获取失败: {e}")
        calc_detail = {}
        calc_update = ""

    # 3. 合并数据并保存
    print("\n[3/3] 合并并保存数据...")
    matches = merge_data(schedule_matches, calc_detail)

    last_update = schedule_update or calc_update
    metadata = {
        "source": "sporttery.cn",
        "url": "https://www.sporttery.cn/jc/zqszsc/",
        "fetch_time": datetime.now().isoformat(),
        "last_update": last_update,
        "total_matches": len(matches),
    }

    # 保存 JSON
    json_path = save_output(matches, metadata)
    print(f"  ✓ JSON 保存到: {json_path}")

    # 生成并保存文本摘要
    summary = generate_summary(matches, last_update)
    txt_path = json_path.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"  ✓ 文本摘要保存到: {txt_path}")

    # 按玩法统计
    had_count = sum(1 for m in matches if m["odds"].get("HAD", {}).get("h"))
    hhad_count = sum(1 for m in matches if m["odds"].get("HHAD", {}).get("h"))
    sold_count = sum(1 for m in matches if m.get("sellStatus") == "已开售")

    print(f"\n{'='*60}")
    print(f"采集完成!")
    print(f"  总场次: {len(matches)}")
    print(f"  已开售: {sold_count}")
    print(f"  有SPF赔率: {had_count}")
    print(f"  有RQSPF赔率: {hhad_count}")
    print(f"  数据文件: {json_path}")
    print(f"{'='*60}")

    # 打印摘要预览
    print("\n" + summary[:2000])

    return matches, metadata


if __name__ == "__main__":
    main()
