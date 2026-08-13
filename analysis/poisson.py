"""
泊松分布进球模型

使用泊松分布对两队进球数建模：
- P(home_goals=k) = lambda_home^k * e^(-lambda_home) / k!
- P(away_goals=k) = lambda_away^k * e^(-lambda_away) / k!
- 独立假设：P(home=A, away=B) = P(home=A) * P(away=B)

lambda 估计基于：
1. 球队的进攻/防守强度系数
2. 联赛平均进球率
3. 对手防守强度
4. 主场优势
"""

import logging
from typing import Dict, Tuple, Optional
import math

import numpy as np
from scipy.stats import poisson

import config as cfg

logger = logging.getLogger(__name__)


class PoissonModel:
    """泊松分布进球预测模型"""

    def __init__(self, db=None):
        self.db = db
        self.config = cfg.FEATURE_CONFIG
        # 默认联赛平均进球参数（每队每场）
        self.league_avg_goals = {
            "eng_premier": 1.45,
            "esp_la_liga": 1.35,
            "ita_serie_a": 1.35,
            "ger_bundesliga": 1.55,
            "fra_ligue_1": 1.40,
            "ned_eredivisie": 1.50,
            "por_primeira": 1.30,
            "bra_serie_a": 1.25,
            "chn_super": 1.40,
        }

    def estimate_lambdas(self, home_team_id: str, away_team_id: str,
                         league_id: str = "",
                         home_attack: float = 1.0,
                         home_defense: float = 1.0,
                         away_attack: float = 1.0,
                         away_defense: float = 1.0,
                         ) -> Tuple[float, float]:
        """
        估计两队的期望进球数（lambda）
        """
        league_avg = self.league_avg_goals.get(league_id, 1.40)

        # 主场球队 lambda = league_avg * 主场进攻系数 * 客场防守系数 * 主场优势
        home_lambda = league_avg * home_attack * away_defense * 1.15

        # 客场球队 lambda = league_avg * 客场进攻系数 * 主场防守系数
        away_lambda = league_avg * away_attack * home_defense

        # 下限保护
        home_lambda = max(0.2, home_lambda)
        away_lambda = max(0.2, away_lambda)

        # 上限保护（避免极端值）
        home_lambda = min(6.0, home_lambda)
        away_lambda = min(6.0, away_lambda)

        return round(home_lambda, 3), round(away_lambda, 3)

    def predict_match(self, home_lambda: float, away_lambda: float,
                      max_goals: int = 8) -> Dict:
        """
        预测比赛各项概率
        返回：胜平负概率、大小球、双方进球等
        """
        # 计算进球概率矩阵
        home_probs = [poisson.pmf(i, home_lambda) for i in range(max_goals + 1)]
        away_probs = [poisson.pmf(i, away_lambda) for i in range(max_goals + 1)]

        # 胜平负概率
        home_win = sum(
            home_probs[i] * sum(away_probs[:i])
            for i in range(1, max_goals + 1)
        )
        away_win = sum(
            away_probs[i] * sum(home_probs[:i])
            for i in range(1, max_goals + 1)
        )
        draw = sum(
            home_probs[i] * away_probs[i]
            for i in range(max_goals + 1)
        )

        # 正常化
        total = home_win + draw + away_win
        home_win /= total
        draw /= total
        away_win /= total

        # 总进球分布
        total_goals_prob = {}
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                tg = i + j
                if tg not in total_goals_prob:
                    total_goals_prob[tg] = 0
                total_goals_prob[tg] += home_probs[i] * away_probs[j]

        # 大小球
        over_15 = sum(p for g, p in total_goals_prob.items() if g > 1.5)
        over_25 = sum(p for g, p in total_goals_prob.items() if g > 2.5)
        over_35 = sum(p for g, p in total_goals_prob.items() if g > 3.5)

        # 双方进球 (BTTS)
        btts = sum(
            home_probs[i] * away_probs[j]
            for i in range(1, max_goals + 1)
            for j in range(1, max_goals + 1)
        )

        # 最可能比分
        best_score = None
        best_score_prob = 0
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p = home_probs[i] * away_probs[j]
                if p > best_score_prob:
                    best_score_prob = p
                    best_score = f"{i}-{j}"

        return {
            "home_win_prob": round(home_win, 4),
            "draw_prob": round(draw, 4),
            "away_win_prob": round(away_win, 4),
            "expected_home_goals": round(home_lambda, 2),
            "expected_away_goals": round(away_lambda, 2),
            "expected_total_goals": round(home_lambda + away_lambda, 2),
            "over_15_prob": round(over_15, 4),
            "over_25_prob": round(over_25, 4),
            "over_35_prob": round(over_35, 4),
            "btts_prob": round(btts, 4),
            "most_likely_score": best_score,
            "most_likely_score_prob": round(best_score_prob, 4),
        }

    def estimate_team_strengths(self, league_id: str) -> Dict[str, Tuple[float, float]]:
        """从历史数据估算球队进攻/防守强度"""
        if not self.db:
            return {}

        matches = self.db.get_matches(league_id=league_id, status="finished", limit=5000)
        if not matches:
            return {}

        # 计算联赛场均进球
        total_home_goals = total_away_goals = 0
        team_home_for = {}
        team_home_against = {}
        team_away_for = {}
        team_away_against = {}

        for m in matches:
            hs = m.get("home_score") or 0
            aws = m.get("away_score") or 0
            total_home_goals += hs
            total_away_goals += aws

            hid = m["home_team_id"]
            aid = m["away_team_id"]

            team_home_for[hid] = team_home_for.get(hid, 0) + hs
            team_home_against[hid] = team_home_against.get(hid, 0) + aws
            team_away_for[aid] = team_away_for.get(aid, 0) + aws
            team_away_against[aid] = team_away_against.get(aid, 0) + hs

        n = len(matches)
        if n == 0:
            return {}

        avg_home_goal = total_home_goals / n
        avg_away_goal = total_away_goals / n
        league_avg = (total_home_goals + total_away_goals) / (2 * n)

        if league_avg == 0:
            return {}

        # 获取每队比赛场次
        team_matches = {}
        for m in matches:
            hid = m["home_team_id"]
            aid = m["away_team_id"]
            team_matches[hid] = team_matches.get(hid, 0) + 1
            team_matches[aid] = team_matches.get(aid, 0) + 1

        strengths = {}
        all_teams = set(team_matches.keys())
        for tid in all_teams:
            n_t = team_matches.get(tid, 1)
            # 进攻系数 = (主场场均进球/联赛主场场均 + 客场场均进球/联赛客场场均) / 2
            home_f = team_home_for.get(tid, 0) / n if n > 0 else 0
            away_f = team_away_for.get(tid, 0) / n if n > 0 else 0
            attack = ((home_f / avg_home_goal if avg_home_goal > 0 else 1.0) +
                       (away_f / avg_away_goal if avg_away_goal > 0 else 1.0)) / 2

            # 防守系数 = (主场场均失球/联赛客场场均 + 客场场均失球/联赛主场场均) / 2
            home_a = team_home_against.get(tid, 0) / n if n > 0 else 0
            away_a = team_away_against.get(tid, 0) / n if n > 0 else 0
            defense = ((home_a / avg_away_goal if avg_away_goal > 0 else 1.0) +
                        (away_a / avg_home_goal if avg_home_goal > 0 else 1.0)) / 2

            # 防御系数越小越好，但我们需要它作为乘数，用倒数
            # 实际 lambda = league_avg * attack * (1/defense_opponent)
            # 这里返回的是乘数（越小防守越好 -> 对方lambda越小）
            strengths[tid] = (
                round(max(0.3, min(3.0, attack)), 3),
                round(max(0.3, min(3.0, defense)), 3),
            )

        return strengths
