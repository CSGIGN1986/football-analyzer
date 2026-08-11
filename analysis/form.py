"""
近期状态分析 — 球队最近表现评估

分析维度：
1. 近期 N 场比赛的场均积分、进球、失球
2. 连胜/连败走势
3. 状态趋势（上升/下降/平稳）
4. 主客场分别统计
"""

import logging
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np

import config as cfg

logger = logging.getLogger(__name__)


class FormAnalyzer:
    """球队状态分析器"""

    def __init__(self, db=None):
        self.db = db
        self.config = cfg.FEATURE_CONFIG
        self._cache: Dict[str, Dict] = {}

    def analyze_team_form(self, team_id: str, window_sizes: List[int] = None) -> Dict:
        """分析一支球队的近期状态"""
        if team_id in self._cache:
            return self._cache[team_id]

        if window_sizes is None:
            window_sizes = self.config["form_window"]

        matches = self.db.get_team_matches(team_id, limit=max(window_sizes) + 1) if self.db else []
        if not matches:
            return self._empty_form()

        form = {
            "team_id": team_id,
            "total_matches": len(matches),
            "recent_results": [],  # 最近结果走势
        }

        for window in window_sizes:
            recent = matches[:window]
            if len(recent) < 3:
                form[f"pts_pg_{window}"] = 0
                form[f"gf_pg_{window}"] = 0
                form[f"ga_pg_{window}"] = 0
                form[f"win_rate_{window}"] = 0
                form[f"clean_sheet_rate_{window}"] = 0
                continue

            wins = draws = losses = 0
            goals_for = goals_conceded = 0
            clean_sheets = 0
            both_scored = 0

            for m in recent:
                is_home = m["home_team_id"] == team_id
                home_score = m.get("home_score", 0) or 0
                away_score = m.get("away_score", 0) or 0

                if is_home:
                    gf, ga = home_score, away_score
                else:
                    gf, ga = away_score, home_score

                goals_for += gf
                goals_conceded += ga

                if gf > ga:
                    wins += 1
                elif gf == ga:
                    draws += 1
                else:
                    losses += 1

                if ga == 0:
                    clean_sheets += 1
                if gf > 0 and ga > 0:
                    both_scored += 1

            n = len(recent)
            form[f"pts_pg_{window}"] = round((wins * 3 + draws) / n, 2)
            form[f"gf_pg_{window}"] = round(goals_for / n, 2)
            form[f"ga_pg_{window}"] = round(goals_conceded / n, 2)
            form[f"win_rate_{window}"] = round(wins / n, 3)
            form[f"clean_sheet_rate_{window}"] = round(clean_sheets / n, 3)
            form[f"btts_rate_{window}"] = round(both_scored / n, 3)

        # 走势分析
        results_sequence = []
        pts_sequence = []
        for m in matches[:max(window_sizes)]:
            is_home = m["home_team_id"] == team_id
            hs = m.get("home_score", 0) or 0
            aws = m.get("away_score", 0) or 0
            if is_home:
                gf, ga = hs, aws
            else:
                gf, ga = aws, hs

            if gf > ga:
                results_sequence.append("W")
                pts_sequence.append(3)
            elif gf == ga:
                results_sequence.append("D")
                pts_sequence.append(1)
            else:
                results_sequence.append("L")
                pts_sequence.append(0)

        form["form_string"] = "".join(results_sequence[:10])  # 最多10场
        form["form_streak"] = self._analyze_streak(results_sequence)
        form["form_momentum"] = self._calc_momentum(pts_sequence)

        # 主客场分开
        home_matches = [m for m in matches if m["home_team_id"] == team_id]
        away_matches = [m for m in matches if m["away_team_id"] == team_id]

        form["home_ppg"] = self._calc_ppg(home_matches, team_id)
        form["away_ppg"] = self._calc_ppg(away_matches, team_id)

        self._cache[team_id] = form
        return form

    def _analyze_streak(self, results: List[str]) -> Dict:
        """分析当前连走势"""
        if not results:
            return {"type": "none", "count": 0}

        current = results[0]
        count = 0
        for r in results:
            if r == current:
                count += 1
            else:
                break

        streak_type = {
            "W": "winning",
            "D": "drawing",
            "L": "losing",
        }.get(current, "none")

        return {"type": streak_type, "count": count, "result": current}

    def _calc_momentum(self, pts_sequence: List[int]) -> float:
        """计算状态趋势（-1 到 1），正值表示上升"""
        if len(pts_sequence) < 4:
            return 0.0

        # 加权平均：最近比赛权重更高
        weights = np.linspace(0.5, 1.0, len(pts_sequence))
        weighted = np.average(pts_sequence, weights=weights)

        # 简单线性趋势
        x = np.arange(len(pts_sequence))
        if len(x) > 1:
            slope = np.polyfit(x, pts_sequence, 1)[0]
            # 归一化到 -1 到 1
            momentum = np.clip(slope / 1.5, -1, 1)
        else:
            momentum = 0.0

        return round(float(momentum), 3)

    def _calc_ppg(self, matches: List[Dict], team_id: str) -> float:
        """计算场均积分"""
        if not matches:
            return 0.0
        pts = 0
        for m in matches[:10]:  # 最近10场
            is_home = m["home_team_id"] == team_id
            hs = m.get("home_score", 0) or 0
            aws = m.get("away_score", 0) or 0
            gf = hs if is_home else aws
            ga = aws if is_home else hs
            if gf > ga:
                pts += 3
            elif gf == ga:
                pts += 1
        return round(pts / min(10, len(matches)), 2)

    def _empty_form(self) -> Dict:
        return {
            "team_id": "",
            "total_matches": 0,
            "form_string": "",
            "form_streak": {"type": "none", "count": 0},
            "form_momentum": 0.0,
            "home_ppg": 0.0,
            "away_ppg": 0.0,
        }

    def clear_cache(self):
        self._cache.clear()
