"""
ELO 评分系统 — 球队实力动态评分引擎

基于经典 ELO 算法的足球增强版：
- 基础 ELO 评分（K 因子根据赛事等级调整）
- 主场优势加成
- 进球差修正
- 联赛间转换
- 时间衰减
"""

import math
import logging
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime

import config as cfg

logger = logging.getLogger(__name__)


class EloSystem:
    """ELO 评分系统"""

    def __init__(self, db=None):
        self.db = db
        self.ratings: Dict[str, float] = {}     # team_id -> elo
        self.home_advantages: Dict[str, float] = {}  # team_id -> home_bonus
        self.config = cfg.ELO_CONFIG

    def load_from_db(self):
        """从数据库加载现有 ELO 评分"""
        if not self.db:
            return
        teams = self.db.get_teams()
        for t in teams:
            self.ratings[t["team_id"]] = t.get("elo_rating", self.config["initial_rating"])
            self.home_advantages[t["team_id"]] = t.get("home_advantage", 0.0)
        logger.info(f"加载 {len(self.ratings)} 支球队的 ELO 数据")

    def get_rating(self, team_id: str) -> float:
        """获取球队 ELO"""
        return self.ratings.get(team_id, self.config["initial_rating"])

    def get_home_advantage(self, team_id: str) -> float:
        """获取球队特有主场优势"""
        return self.home_advantages.get(team_id, 0.0)

    def expected_score(self, rating_a: float, rating_b: float,
                       home_advantage: float = 0) -> Tuple[float, float]:
        """
        计算预期得分（胜率）
        返回 (A的预期得分, B的预期得分)
        """
        adjusted_a = rating_a + home_advantage
        exp_a = 1.0 / (1.0 + 10 ** ((rating_b - adjusted_a) / 400.0))
        return exp_a, 1.0 - exp_a

    def win_probability(self, home_team_id: str, away_team_id: str) -> Tuple[float, float, float]:
        """
        计算胜平负概率
        返回 (主胜概率, 平局概率, 客胜概率)
        """
        home_elo = self.get_rating(home_team_id)
        away_elo = self.get_rating(away_team_id)
        home_adv = self.config["home_advantage"] + self.get_home_advantage(home_team_id)

        # 计算预期胜率
        exp_home, exp_away = self.expected_score(home_elo, away_elo, home_adv)

        # 平局概率模型（基于 ELO 差距）
        elo_diff = abs(home_elo + home_adv - away_elo)
        draw_base = 0.27  # 基础平局率
        draw_factor = max(0.08, draw_base - elo_diff * 0.0002)  # 差距越大平局越少

        # 标准化概率
        home_prob = exp_home * (1 - draw_factor)
        away_prob = exp_away * (1 - draw_factor)
        draw_prob = draw_factor

        # 确保总和为 1
        total = home_prob + draw_prob + away_prob
        return home_prob / total, draw_prob / total, away_prob / total

    def update_rating(self, team_id: str, opponent_id: str,
                      result: str,  # 'win', 'draw', 'loss'
                      goal_diff: int = 0,
                      is_home: bool = True,
                      match_id: str = "") -> Tuple[float, float]:
        """
        更新 ELO 评分
        返回 (新评分, 变化量)
        """
        old_rating = self.get_rating(team_id)
        opp_rating = self.get_rating(opponent_id)

        # 主场优势
        if is_home:
            adj_rating = old_rating + self.config["home_advantage"]
        else:
            adj_rating = old_rating

        # 预期得分
        exp_score = 1.0 / (1.0 + 10 ** ((opp_rating - adj_rating) / 400.0))

        # 实际得分
        if result == "win":
            actual_score = 1.0
        elif result == "draw":
            actual_score = 0.5
        else:
            actual_score = 0.0

        # K 因子 — 进球差修正
        k = self.config["k_factor"]
        if result in ("win", "loss"):
            # 大胜/大败时 K 值增加
            k *= min(2.0, 1.0 + abs(goal_diff) * self.config["goal_diff_factor"] / 4)

        # 更新
        change = k * (actual_score - exp_score)
        new_rating = old_rating + change

        # 持久化
        self.ratings[team_id] = new_rating
        if self.db and match_id:
            self.db.update_elo(team_id, new_rating)
            self.db.insert_elo_history(team_id, match_id, old_rating, new_rating)

        return new_rating, change

    def update_match(self, match: Dict) -> Dict[str, Tuple[float, float]]:
        """根据比赛结果双向更新 ELO"""
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        home_score = match.get("home_score")
        away_score = match.get("away_score")

        if home_score is None or away_score is None:
            return {}

        goal_diff = home_score - away_score
        if goal_diff > 0:
            home_result, away_result = "win", "loss"
        elif goal_diff < 0:
            home_result, away_result = "loss", "win"
        else:
            home_result, away_result = "draw", "draw"

        home_new, home_change = self.update_rating(
            home_id, away_id, home_result, abs(goal_diff), is_home=True,
            match_id=match.get("match_id", "")
        )
        away_new, away_change = self.update_rating(
            away_id, home_id, away_result, abs(goal_diff), is_home=False,
            match_id=match.get("match_id", "")
        )

        return {
            home_id: (home_new, home_change),
            away_id: (away_new, away_change),
        }

    def process_history(self, league_id: Optional[str] = None):
        """处理历史比赛，计算全量 ELO"""
        if not self.db:
            return

        matches = self.db.get_matches(league_id=league_id, status="finished", limit=10000)
        matches.sort(key=lambda m: m["match_date"])  # 按时间顺序

        logger.info(f"处理 {len(matches)} 场历史比赛...")
        for match in matches:
            self.update_match(match)

        logger.info(f"ELO 处理完成，{len(self.ratings)} 支球队已评分")

    def get_ratings_table(self, league_id: Optional[str] = None,
                           limit: int = 20) -> List[Dict]:
        """获取 ELO 排名表"""
        teams = self.db.get_teams(league_id=league_id) if self.db else []
        result = []
        for t in teams:
            tid = t["team_id"]
            rating = self.ratings.get(tid, t.get("elo_rating", 1500))
            result.append({
                "team_id": tid,
                "name": t["name"],
                "elo": round(rating, 1),
                "league": t.get("league_id", ""),
            })

        result.sort(key=lambda x: x["elo"], reverse=True)
        return result[:limit]
