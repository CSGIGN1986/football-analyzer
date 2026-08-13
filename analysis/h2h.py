"""
交锋历史分析 (Head-to-Head)
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class H2HAnalyzer:
    """交锋历史分析器"""

    def __init__(self, db=None):
        self.db = db
        self._cache: Dict[str, Dict] = {}

    def _cache_key(self, team1: str, team2: str) -> str:
        return "|".join(sorted([team1, team2]))

    def analyze(self, team1_id: str, team2_id: str) -> Dict:
        """分析两队交锋历史"""
        key = self._cache_key(team1_id, team2_id)
        if key in self._cache:
            return self._cache[key]

        history = self.db.get_h2h_matches(team1_id, team2_id, limit=10) if self.db else []

        if not history:
            result = self._empty_h2h(team1_id, team2_id)
            self._cache[key] = result
            return result

        # 从 team1 视角统计
        t1_wins = t1_draws = t1_losses = 0
        t1_goals_for = t1_goals_against = 0
        over_25_count = 0
        btts_count = 0

        for m in history:
            home_id = m["home_team_id"]
            hs = m.get("home_score", 0) or 0
            aws = m.get("away_score", 0) or 0

            if (home_id == team1_id and hs > aws) or (home_id == team2_id and aws > hs):
                t1_wins += 1
            elif hs == aws:
                t1_draws += 1
            else:
                t1_losses += 1

            if home_id == team1_id:
                t1_goals_for += hs
                t1_goals_against += aws
            else:
                t1_goals_for += aws
                t1_goals_against += hs

            if hs + aws > 2.5:
                over_25_count += 1
            if hs > 0 and aws > 0:
                btts_count += 1

        n = len(history)
        result = {
            "team1_id": team1_id,
            "team2_id": team2_id,
            "total_matches": n,
            "team1_wins": t1_wins,
            "team1_draws": t1_draws,
            "team1_losses": t1_losses,
            "team1_win_rate": round(t1_wins / n, 3),
            "team1_draw_rate": round(t1_draws / n, 3),
            "team1_goals_for": t1_goals_for,
            "team1_goals_against": t1_goals_against,
            "avg_goals_per_match": round((t1_goals_for + t1_goals_against) / n, 2),
            "over_25_rate": round(over_25_count / n, 3),
            "btts_rate": round(btts_count / n, 3),
            "recent_matches": [
                {
                    "date": m["match_date"],
                    "home": m["home_team_name"],
                    "away": m["away_team_name"],
                    "score": f"{m.get('home_score', '-')}-{m.get('away_score', '-')}",
                }
                for m in history[:5]
            ],
        }

        self._cache[key] = result
        return result

    def _empty_h2h(self, team1: str, team2: str) -> Dict:
        return {
            "team1_id": team1,
            "team2_id": team2,
            "total_matches": 0,
            "team1_wins": 0,
            "team1_draws": 0,
            "team1_losses": 0,
            "team1_win_rate": 0,
            "team1_draw_rate": 0,
            "team1_goals_for": 0,
            "team1_goals_against": 0,
            "avg_goals_per_match": 0,
            "over_25_rate": 0,
            "btts_rate": 0,
            "recent_matches": [],
        }

    def clear_cache(self):
        self._cache.clear()
