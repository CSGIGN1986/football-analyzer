"""
数据模型：球队、球员、比赛、联赛
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List, Dict
from enum import Enum


class MatchResult(Enum):
    """比赛结果"""
    HOME_WIN = "home"
    DRAW = "draw"
    AWAY_WIN = "away"


class PredictionTarget(Enum):
    """预测目标"""
    MATCH_OUTCOME = "outcome"        # 胜平负
    ASIAN_HANDICAP = "asian"          # 亚盘
    OVER_UNDER = "over_under"         # 大小球
    BOTH_TEAMS_SCORE = "btts"        # 双方进球
    CORRECT_SCORE = "correct_score"  # 正确比分


@dataclass
class League:
    """联赛"""
    league_id: str
    name: str
    country: str
    tier: int
    season: str  # 如 "2024-2025"


@dataclass
class Team:
    """球队"""
    team_id: str
    name: str
    short_name: str = ""
    country: str = ""
    league_id: str = ""
    elo_rating: float = 1500.0
    attack_strength: float = 1.0     # 进攻系数（相对联赛平均）
    defense_strength: float = 1.0    # 防守系数
    home_advantage: float = 0.0       # 主场优势加成
    form_points: float = 0.0
    matches_played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0


@dataclass
class Player:
    """球员"""
    player_id: str
    name: str
    team_id: str
    position: str = ""     # GK/DEF/MID/FWD
    number: int = 0
    is_injured: bool = False
    is_suspended: bool = False


@dataclass
class Match:
    """比赛"""
    match_id: str
    league_id: str
    season: str
    match_date: date
    home_team_id: str
    away_team_id: str
    home_team_name: str = ""
    away_team_name: str = ""
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_ht_score: Optional[int] = None   # 半场
    away_ht_score: Optional[int] = None
    status: str = "scheduled"     # scheduled / live / finished / postponed
    round_name: str = ""


@dataclass
class MatchStats:
    """比赛进阶统计数据"""
    match_id: str
    # xG (Expected Goals)
    home_xg: Optional[float] = None
    away_xg: Optional[float] = None
    # 控球率
    home_possession: Optional[float] = None
    away_possession: Optional[float] = None
    # 射门
    home_shots: Optional[int] = None
    away_shots: Optional[int] = None
    home_shots_on_target: Optional[int] = None
    away_shots_on_target: Optional[int] = None
    # 传球
    home_passes: Optional[int] = None
    away_passes: Optional[int] = None
    home_pass_accuracy: Optional[float] = None
    away_pass_accuracy: Optional[float] = None
    # 角球
    home_corners: Optional[int] = None
    away_corners: Optional[int] = None
    # 黄/红牌
    home_yellow_cards: Optional[int] = None
    away_yellow_cards: Optional[int] = None
    home_red_cards: Optional[int] = None
    away_red_cards: Optional[int] = None


@dataclass
class Prediction:
    """预测结果"""
    match_id: str
    home_team: str
    away_team: str
    match_date: date
    # 胜平负概率
    home_prob: float
    draw_prob: float
    away_prob: float
    # 预测结果
    predicted_outcome: MatchResult
    confidence: float                # 置信度 0-1
    # 期望进球
    expected_home_goals: float
    expected_away_goals: float
    # 大小球
    over_25_prob: float = 0.0
    over_35_prob: float = 0.0
    # 双方进球
    btts_prob: float = 0.0
    # 模型信息
    model_name: str = ""
    feature_count: int = 0
    # 凯利值
    kelly_home: float = 0.0
    kelly_draw: float = 0.0
    kelly_away: float = 0.0


@dataclass
class TeamForm:
    """球队近期状态"""
    team_id: str
    matches: List[Dict] = field(default_factory=list)
    points_last_n: Dict[int, float] = field(default_factory=dict)  # {n: ppg}
    goals_scored_last_n: Dict[int, float] = field(default_factory=dict)
    goals_conceded_last_n: Dict[int, float] = field(default_factory=dict)
    win_rate_last_n: Dict[int, float] = field(default_factory=dict)
    form_streak: str = ""  # "WWDLW"
    form_momentum: float = 0.0  # 状态趋势 (-1 到 1)
