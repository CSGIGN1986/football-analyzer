"""
数据库层：SQLite 存储、CRUD 操作
"""

import sqlite3
import json
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

import config as cfg


class FootballDB:
    """足球数据库"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = str(db_path or cfg.DATA_DIR / "football.db")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        """初始化数据库表结构"""
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leagues (
                    league_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    country TEXT,
                    tier INTEGER,
                    season TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS teams (
                    team_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    short_name TEXT,
                    country TEXT,
                    league_id TEXT,
                    elo_rating REAL DEFAULT 1500.0,
                    attack_strength REAL DEFAULT 1.0,
                    defense_strength REAL DEFAULT 1.0,
                    home_advantage REAL DEFAULT 0.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (league_id) REFERENCES leagues(league_id)
                );

                CREATE TABLE IF NOT EXISTS players (
                    player_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    team_id TEXT,
                    position TEXT,
                    number INTEGER,
                    is_injured INTEGER DEFAULT 0,
                    is_suspended INTEGER DEFAULT 0,
                    FOREIGN KEY (team_id) REFERENCES teams(team_id)
                );

                CREATE TABLE IF NOT EXISTS matches (
                    match_id TEXT PRIMARY KEY,
                    league_id TEXT,
                    season TEXT,
                    match_date DATE,
                    home_team_id TEXT,
                    away_team_id TEXT,
                    home_team_name TEXT,
                    away_team_name TEXT,
                    home_score INTEGER,
                    away_score INTEGER,
                    home_ht_score INTEGER,
                    away_ht_score INTEGER,
                    status TEXT DEFAULT 'scheduled',
                    round_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (league_id) REFERENCES leagues(league_id),
                    FOREIGN KEY (home_team_id) REFERENCES teams(team_id),
                    FOREIGN KEY (away_team_id) REFERENCES teams(team_id)
                );

                CREATE TABLE IF NOT EXISTS match_stats (
                    match_id TEXT PRIMARY KEY,
                    home_xg REAL, away_xg REAL,
                    home_possession REAL, away_possession REAL,
                    home_shots INTEGER, away_shots INTEGER,
                    home_shots_on_target INTEGER, away_shots_on_target INTEGER,
                    home_passes INTEGER, away_passes INTEGER,
                    home_pass_accuracy REAL, away_pass_accuracy REAL,
                    home_corners INTEGER, away_corners INTEGER,
                    home_yellow_cards INTEGER, away_yellow_cards INTEGER,
                    home_red_cards INTEGER, away_red_cards INTEGER,
                    FOREIGN KEY (match_id) REFERENCES matches(match_id)
                );

                CREATE TABLE IF NOT EXISTS elo_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id TEXT,
                    match_id TEXT,
                    elo_before REAL,
                    elo_after REAL,
                    change REAL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (team_id) REFERENCES teams(team_id),
                    FOREIGN KEY (match_id) REFERENCES matches(match_id)
                );

                CREATE TABLE IF NOT EXISTS predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    match_id TEXT,
                    home_prob REAL,
                    draw_prob REAL,
                    away_prob REAL,
                    predicted_outcome TEXT,
                    confidence REAL,
                    expected_home_goals REAL,
                    expected_away_goals REAL,
                    over_25_prob REAL,
                    over_35_prob REAL,
                    btts_prob REAL,
                    model_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (match_id) REFERENCES matches(match_id)
                );

                CREATE TABLE IF NOT EXISTS odds (
                    match_id TEXT PRIMARY KEY,
                    home_odds REAL,
                    draw_odds REAL,
                    away_odds REAL,
                    over_25_odds REAL,
                    under_25_odds REAL,
                    source TEXT DEFAULT 'generated',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (match_id) REFERENCES matches(match_id)
                );

                CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
                CREATE INDEX IF NOT EXISTS idx_matches_league ON matches(league_id, season);
                CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team_id, away_team_id);
                CREATE INDEX IF NOT EXISTS idx_elo_history_team ON elo_history(team_id);
            """)

    # === 联赛 ===
    def upsert_league(self, league: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO leagues (league_id, name, country, tier, season)
                VALUES (:league_id, :name, :country, :tier, :season)
            """, league)

    def get_leagues(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM leagues ORDER BY tier, country").fetchall()
            return [dict(r) for r in rows]

    # === 球队 ===
    def upsert_team(self, team: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO teams
                    (team_id, name, short_name, country, league_id,
                     elo_rating, attack_strength, defense_strength, home_advantage, updated_at)
                VALUES (:team_id, :name, :short_name, :country, :league_id,
                        :elo_rating, :attack_strength, :defense_strength, :home_advantage, datetime('now'))
            """, team)

    def get_teams(self, league_id: Optional[str] = None) -> List[Dict]:
        with self._connect() as conn:
            if league_id:
                rows = conn.execute(
                    "SELECT * FROM teams WHERE league_id = ? ORDER BY elo_rating DESC", (league_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM teams ORDER BY elo_rating DESC").fetchall()
            return [dict(r) for r in rows]

    def get_team(self, team_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
            return dict(row) if row else None

    def update_elo(self, team_id: str, elo_rating: float):
        with self._connect() as conn:
            conn.execute(
                "UPDATE teams SET elo_rating = ?, updated_at = datetime('now') WHERE team_id = ?",
                (elo_rating, team_id)
            )

    # === 球员 ===
    def upsert_player(self, player: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO players (player_id, name, team_id, position, number, is_injured, is_suspended)
                VALUES (:player_id, :name, :team_id, :position, :number, :is_injured, :is_suspended)
            """, player)

    # === 比赛 ===
    def upsert_match(self, match: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO matches
                    (match_id, league_id, season, match_date, home_team_id, away_team_id,
                     home_team_name, away_team_name, home_score, away_score,
                     home_ht_score, away_ht_score, status, round_name)
                VALUES (:match_id, :league_id, :season, :match_date, :home_team_id, :away_team_id,
                        :home_team_name, :away_team_name, :home_score, :away_score,
                        :home_ht_score, :away_ht_score, :status, :round_name)
            """, match)

    def get_matches(self, league_id: Optional[str] = None,
                    status: Optional[str] = "finished",
                    limit: int = 500) -> List[Dict]:
        with self._connect() as conn:
            conditions = []
            params = []
            if league_id:
                conditions.append("league_id = ?")
                params.append(league_id)
            if status:
                conditions.append("status = ?")
                params.append(status)
            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM matches {where} ORDER BY match_date DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            return [dict(r) for r in rows]

    def get_team_matches(self, team_id: str, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM matches
                WHERE (home_team_id = ? OR away_team_id = ?) AND status = 'finished'
                ORDER BY match_date DESC LIMIT ?
            """, (team_id, team_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_h2h_matches(self, team1_id: str, team2_id: str, limit: int = 10) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM matches
                WHERE ((home_team_id = ? AND away_team_id = ?)
                    OR (home_team_id = ? AND away_team_id = ?))
                    AND status = 'finished'
                ORDER BY match_date DESC LIMIT ?
            """, (team1_id, team2_id, team2_id, team1_id, limit)).fetchall()
            return [dict(r) for r in rows]

    def get_upcoming_matches(self, league_id: Optional[str] = None,
                              limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            if league_id:
                rows = conn.execute("""
                    SELECT * FROM matches
                    WHERE status = 'scheduled' AND league_id = ?
                    ORDER BY match_date ASC LIMIT ?
                """, (league_id, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM matches
                    WHERE status = 'scheduled'
                    ORDER BY match_date ASC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # === 比赛统计 ===
    def upsert_match_stats(self, stats: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO match_stats
                    (match_id, home_xg, away_xg, home_possession, away_possession,
                     home_shots, away_shots, home_shots_on_target, away_shots_on_target,
                     home_passes, away_passes, home_pass_accuracy, away_pass_accuracy,
                     home_corners, away_corners, home_yellow_cards, away_yellow_cards,
                     home_red_cards, away_red_cards)
                VALUES (:match_id, :home_xg, :away_xg, :home_possession, :away_possession,
                        :home_shots, :away_shots, :home_shots_on_target, :away_shots_on_target,
                        :home_passes, :away_passes, :home_pass_accuracy, :away_pass_accuracy,
                        :home_corners, :away_corners, :home_yellow_cards, :away_yellow_cards,
                        :home_red_cards, :away_red_cards)
            """, stats)

    # === 赔率 ===
    def upsert_odds(self, odds: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO odds (match_id, home_odds, draw_odds, away_odds,
                    over_25_odds, under_25_odds, source, updated_at)
                VALUES (:match_id, :home_odds, :draw_odds, :away_odds,
                    :over_25_odds, :under_25_odds, :source, datetime('now'))
            """, odds)

    # === ELO 历史 ===
    def insert_elo_history(self, team_id: str, match_id: str,
                           elo_before: float, elo_after: float):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO elo_history (team_id, match_id, elo_before, elo_after, change)
                VALUES (?, ?, ?, ?, ?)
            """, (team_id, match_id, elo_before, elo_after, elo_after - elo_before))

    def get_elo_history(self, team_id: str, limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM elo_history
                WHERE team_id = ?
                ORDER BY updated_at DESC LIMIT ?
            """, (team_id, limit)).fetchall()
            return [dict(r) for r in rows]

    # === 预测 ===
    def save_prediction(self, pred: Dict[str, Any]):
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO predictions
                    (match_id, home_prob, draw_prob, away_prob, predicted_outcome,
                     confidence, expected_home_goals, expected_away_goals,
                     over_25_prob, over_35_prob, btts_prob, model_name)
                VALUES (:match_id, :home_prob, :draw_prob, :away_prob, :predicted_outcome,
                        :confidence, :expected_home_goals, :expected_away_goals,
                        :over_25_prob, :over_35_prob, :btts_prob, :model_name)
            """, pred)

    def get_predictions(self, limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT p.*, m.home_team_name, m.away_team_name, m.match_date
                FROM predictions p
                JOIN matches m ON p.match_id = m.match_id
                ORDER BY p.created_at DESC LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # === 聚合统计 ===
    def get_league_table(self, league_id: str, season: str) -> List[Dict]:
        """生成联赛积分榜"""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT 
                    t.team_id, t.name,
                    COUNT(CASE WHEN m.status = 'finished' THEN 1 END) as played,
                    SUM(CASE WHEN m.home_team_id = t.team_id AND m.home_score > m.away_score THEN 1
                             WHEN m.away_team_id = t.team_id AND m.away_score > m.home_score THEN 1
                             ELSE 0 END) as wins,
                    SUM(CASE WHEN m.home_score = m.away_score THEN 1 ELSE 0 END) as draws,
                    SUM(CASE WHEN m.home_team_id = t.team_id AND m.home_score < m.away_score THEN 1
                             WHEN m.away_team_id = t.team_id AND m.away_score < m.home_score THEN 1
                             ELSE 0 END) as losses,
                    SUM(CASE WHEN m.home_team_id = t.team_id THEN m.home_score
                             WHEN m.away_team_id = t.team_id THEN m.away_score
                             ELSE 0 END) as goals_for,
                    SUM(CASE WHEN m.home_team_id = t.team_id THEN m.away_score
                             WHEN m.away_team_id = t.team_id THEN m.home_score
                             ELSE 0 END) as goals_against
                FROM teams t
                JOIN matches m ON (m.home_team_id = t.team_id OR m.away_team_id = t.team_id)
                    AND m.league_id = ? AND m.season = ?
                GROUP BY t.team_id
                ORDER BY (wins * 3 + draws) DESC, (goals_for - goals_against) DESC
            """, (league_id, season)).fetchall()
            return [dict(r) for r in rows]
