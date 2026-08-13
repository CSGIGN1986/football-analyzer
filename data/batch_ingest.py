#!/usr/bin/env python3
"""批量入库脚本 — 高性能版本

使用单个数据库连接批量写入 football-data 历史数据，
避免逐条 upsert 的连接开关开销。
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("batch_ingest")

import hashlib
import sqlite3
import config as cfg


def team_code(team_name, league_id):
    return hashlib.md5(f"{league_id}_{team_name}".encode()).hexdigest()[:12]


def main():
    json_path = Path("data/football_data/football_data_20260813.json")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    matches_by_league = data.get("matches", {})
    total = data.get("totalMatches", 0)
    logger.info(f"读取 {total} 场比赛，{len(matches_by_league)} 个联赛")

    db_path = str(cfg.DATA_DIR / "football.db")
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=OFF")

    count = 0
    for league_key, matches in matches_by_league.items():
        for m in matches:
            home_team = m.get("homeTeam", "")
            away_team = m.get("awayTeam", "")
            if not home_team or not away_team:
                continue

            league_cn = m.get("leagueCn", league_key)
            season = m.get("season", "")
            home_tid = team_code(home_team, league_key)
            away_tid = team_code(away_team, league_key)
            date_str = (m.get("date", "") or "").replace("-", "")
            match_id = f"{league_key}_{date_str}_{home_tid}_{away_tid}"

            try:
                # 联赛
                conn.execute(
                    "INSERT OR REPLACE INTO leagues (league_id, name, country, tier, season) VALUES (?,?,?,?,?)",
                    (league_key, league_cn, "", 1, season),
                )
                # 球队
                for tid, tname in [(home_tid, home_team), (away_tid, away_team)]:
                    conn.execute(
                        "INSERT OR REPLACE INTO teams (team_id, name, short_name, country, league_id, elo_rating, attack_strength, defense_strength, home_advantage, updated_at) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))",
                        (tid, tname, tname, "", league_key, 1500.0, 1.0, 1.0, 0.0),
                    )
                # 比赛
                conn.execute(
                    "INSERT OR REPLACE INTO matches (match_id, league_id, season, match_date, home_team_id, away_team_id, home_team_name, away_team_name, home_score, away_score, home_ht_score, away_ht_score, status, round_name) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (match_id, league_key, season, m.get("date", ""), home_tid, away_tid,
                     home_team, away_team,
                     m.get("fullTimeHomeGoals"), m.get("fullTimeAwayGoals"),
                     m.get("halfTimeHomeGoals"), m.get("halfTimeAwayGoals"),
                     "finished", ""),
                )
                # 统计
                conn.execute(
                    "INSERT OR REPLACE INTO match_stats (match_id, home_shots, away_shots, home_shots_on_target, away_shots_on_target, home_corners, away_corners, home_yellow_cards, away_yellow_cards, home_red_cards, away_red_cards) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (match_id,
                     m.get("homeShots"), m.get("awayShots"),
                     m.get("homeShotsOnTarget"), m.get("awayShotsOnTarget"),
                     m.get("homeCorners"), m.get("awayCorners"),
                     m.get("homeYellow"), m.get("awayYellow"),
                     m.get("homeRed"), m.get("awayRed")),
                )
                # 赔率
                conn.execute(
                    "INSERT OR REPLACE INTO odds (match_id, home_odds, draw_odds, away_odds, over_25_odds, under_25_odds, source, updated_at) VALUES (?,?,?,?,?,?,?,datetime('now'))",
                    (match_id,
                     m.get("avgHomeOdds"), m.get("avgDrawOdds"), m.get("avgAwayOdds"),
                     m.get("avgOver25"), m.get("avgUnder25"),
                     "football-data.co.uk"),
                )
                count += 1
            except Exception as e:
                logger.warning(f"  失败 {match_id}: {e}")

            if count % 1000 == 0:
                conn.commit()
                logger.info(f"  进度: {count}/{total}")

    conn.commit()
    conn.close()

    # 验证
    conn = sqlite3.connect(db_path)
    finished = conn.execute("SELECT COUNT(*) FROM matches WHERE status='finished'").fetchone()[0]
    teams = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    leagues = conn.execute("SELECT COUNT(*) FROM leagues").fetchone()[0]
    conn.close()

    logger.info(f"入库完成: {count} 场")
    logger.info(f"数据库状态: {leagues} 联赛, {teams} 球队, {finished} 已完成比赛")
    print(f"DONE|{count}|{leagues}|{teams}|{finished}")


if __name__ == "__main__":
    main()
