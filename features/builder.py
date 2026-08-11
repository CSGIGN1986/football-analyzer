"""
特征工程 — 将原始数据转换为模型可用特征矩阵

构建的特征维度（~80个）：
1. ELO 特征：主/客 ELO、ELO差、ELO概率
2. 状态特征：近期场均积分、进球、失球、胜率
3. 交锋特征：H2H胜率、进球数、大小球率
4. 泊松特征：期望进球、总进球
5. 进阶统计：xG、控球、射门
6. 联赛结构：赛事等级、主客场差异
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import date

import numpy as np
import pandas as pd

import config as cfg

logger = logging.getLogger(__name__)


class FeatureBuilder:
    """特征构建器"""

    def __init__(self, db=None, elo_system=None, form_analyzer=None,
                 h2h_analyzer=None):
        self.db = db
        self.elo = elo_system
        self.form = form_analyzer
        self.h2h = h2h_analyzer
        self.config = cfg.FEATURE_CONFIG

    def build_match_features(self, match: Dict) -> Optional[Dict]:
        """为单场比赛构建特征向量"""
        home_id = match["home_team_id"]
        away_id = match["away_team_id"]
        league_id = match.get("league_id", "")

        features = {}

        # === 1. ELO 特征 ===
        if self.elo and self.config["use_elo"]:
            home_elo = self.elo.get_rating(home_id)
            away_elo = self.elo.get_rating(away_id)
            elo_diff = home_elo - away_elo + cfg.ELO_CONFIG["home_advantage"]

            hp, dp, ap = self.elo.win_probability(home_id, away_id)

            features.update({
                "elo_home": home_elo,
                "elo_away": away_elo,
                "elo_diff": round(elo_diff, 1),
                "elo_diff_abs": abs(elo_diff),
                "elo_home_prob": round(hp, 4),
                "elo_draw_prob": round(dp, 4),
                "elo_away_prob": round(ap, 4),
                "elo_home_advantage": cfg.ELO_CONFIG["home_advantage"],
            })

        # === 2. 近期状态特征 ===
        if self.form and self.config["use_form"]:
            home_form = self.form.analyze_team_form(home_id)
            away_form = self.form.analyze_team_form(away_id)

            for window in self.config["form_window"]:
                for prefix, form_dict in [("home", home_form), ("away", away_form)]:
                    for metric in ["pts_pg", "gf_pg", "ga_pg", "win_rate"]:
                        key = f"{prefix}_{metric}_{window}"
                        val = form_dict.get(f"{metric}_{window}", 0)
                        features[key] = val

            # 动量差异
            features["form_momentum_diff"] = round(
                home_form.get("form_momentum", 0) - away_form.get("form_momentum", 0), 3
            )

            # PPG 差异
            features["ppg_diff_5"] = round(
                home_form.get("pts_pg_5", 0) - away_form.get("pts_pg_5", 0), 2
            )

            # 主场PPG vs 客场PPG
            features["home_home_ppg"] = home_form.get("home_ppg", 0)
            features["away_away_ppg"] = away_form.get("away_ppg", 0)
            features["home_away_ppg_diff"] = round(
                home_form.get("home_ppg", 0) - away_form.get("away_ppg", 0), 2
            )

            # 连胜/连败
            home_streak = home_form.get("form_streak", {})
            away_streak = away_form.get("form_streak", {})
            features["home_streak_count"] = home_streak.get("count", 0)
            features["home_streak_type"] = 1 if home_streak.get("type") == "winning" else (-1 if home_streak.get("type") == "losing" else 0)
            features["away_streak_count"] = away_streak.get("count", 0)
            features["away_streak_type"] = 1 if away_streak.get("type") == "winning" else (-1 if away_streak.get("type") == "losing" else 0)

        # === 3. 交锋历史特征 ===
        if self.h2h and self.config["use_h2h"]:
            h2h_data = self.h2h.analyze(home_id, away_id)
            features.update({
                "h2h_total_matches": h2h_data["total_matches"],
                "h2h_home_win_rate": h2h_data["team1_win_rate"],
                "h2h_draw_rate": h2h_data["team1_draw_rate"],
                "h2h_avg_goals": h2h_data["avg_goals_per_match"],
                "h2h_over_25_rate": h2h_data["over_25_rate"],
                "h2h_btts_rate": h2h_data["btts_rate"],
            })

        # === 4. 泊松特征 ===
        if self.config["use_poisson"]:
            # 从历史数据估算进攻/防守强度
            from analysis.poisson import PoissonModel
            pm = PoissonModel(self.db)
            strengths = pm.estimate_team_strengths(league_id)

            home_attack, home_defense = strengths.get(home_id, (1.0, 1.0))
            away_attack, away_defense = strengths.get(away_id, (1.0, 1.0))

            home_lambda, away_lambda = pm.estimate_lambdas(
                home_id, away_id, league_id,
                home_attack, home_defense, away_attack, away_defense
            )

            features.update({
                "home_attack_strength": home_attack,
                "home_defense_strength": home_defense,
                "away_attack_strength": away_attack,
                "away_defense_strength": away_defense,
                "expected_home_goals": home_lambda,
                "expected_away_goals": away_lambda,
                "expected_total_goals": round(home_lambda + away_lambda, 2),
                "expected_goal_diff": round(home_lambda - away_lambda, 2),
            })

        # === 5. 联赛/结构特征 ===
        league_tier = {l.league_id: l.tier for l in cfg.SUPPORTED_LEAGUES}
        features["league_tier"] = league_tier.get(league_id, 1)

        # 赛季进度
        try:
            match_date = date.fromisoformat(match["match_date"]) if isinstance(match.get("match_date"), str) else match.get("match_date")
            if match_date:
                season_start = date(2024, 8, 10)
                season_end = date(2025, 5, 25)
                total_days = (season_end - season_start).days
                elapsed = (match_date - season_start).days
                features["season_progress"] = round(max(0, min(1, elapsed / total_days)), 3)
        except (ValueError, TypeError):
            features["season_progress"] = 0.5

        # === 6. 构建标签 ===
        hs = match.get("home_score")
        aws = match.get("away_score")
        if hs is not None and aws is not None:
            if hs > aws:
                features["label"] = 0  # 主胜
            elif hs == aws:
                features["label"] = 1  # 平局
            else:
                features["label"] = 2  # 客胜

            # 附加标签
            features["total_goals"] = hs + aws
            features["goal_diff"] = hs - aws
            features["over_25"] = 1 if hs + aws > 2.5 else 0
            features["btts"] = 1 if hs > 0 and aws > 0 else 0

        return features

    def build_dataset(self, league_id: Optional[str] = None,
                      limit: int = 5000) -> pd.DataFrame:
        """构建完整特征数据集"""
        if not self.db:
            logger.error("数据库未连接")
            return pd.DataFrame()

        matches = self.db.get_matches(league_id=league_id, status="finished", limit=limit)
        if not matches:
            logger.warning("无比赛数据")
            return pd.DataFrame()

        all_features = []
        for match in matches:
            feats = self.build_match_features(match)
            if feats and "label" in feats:
                all_features.append(feats)

        df = pd.DataFrame(all_features)
        logger.info(f"构建数据集: {len(df)} 条记录, {len(df.columns)} 个特征")

        # 处理缺失值
        df = df.fillna(0)

        return df

    def get_feature_names(self, df: pd.DataFrame) -> List[str]:
        """获取特征名列表（排除标签列）"""
        exclude = ["label", "total_goals", "goal_diff", "over_25", "btts"]
        return [c for c in df.columns if c not in exclude]
