"""
足球分析预测系统 — 全局配置
"""

from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional

# === 路径 ===
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models" / "saved"
LOGS_DIR = BASE_DIR / "logs"
REPORTS_DIR = BASE_DIR / "reports"

for d in [DATA_DIR, MODELS_DIR, LOGS_DIR, REPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# === 数据库 ===
DATABASE_URL = f"sqlite:///{DATA_DIR / 'football.db'}"

# === 爬虫配置 ===
SCRAPER_CONFIG = {
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "request_delay": 2.0,          # 请求间隔（秒）
    "max_retries": 3,
    "timeout": 30,
    "headless": True,
}

# === 数据源 ===
DATA_SOURCES = {
    "flashscore": {
        "base_url": "https://www.flashscore.com",
        "enabled": True,
        "leagues_endpoint": "/x/feed/f_1_{league_id}_en_1",
    },
    "soccerway": {
        "base_url": "https://us.soccerway.com",
        "enabled": False,
    },
    "fbref": {
        "base_url": "https://fbref.com",
        "enabled": True,
    },
}

# === ELO 评分系统 ===
ELO_CONFIG = {
    "initial_rating": 1500.0,
    "k_factor": 32.0,              # 基础 K 值
    "home_advantage": 100.0,        # 主场加分
    "goal_diff_factor": 1.5,        # 进失球差系数
    "decay_weeks": 52,              # 衰减周期（周）
    "minimum_matches": 5,           # 最少比赛场次
}

# === 特征工程 ===
FEATURE_CONFIG = {
    "form_window": [5, 10, 15],    # 近期比赛窗口
    "h2h_window": 10,              # 交锋历史窗口
    "use_elo": True,
    "use_poisson": True,
    "use_form": True,
    "use_h2h": True,
    "use_advanced_stats": True,    # xG 等进阶数据
    "poisson_simulations": 10000,   # 泊松模拟次数
}

# === 模型训练 ===
MODEL_CONFIG = {
    "test_size": 0.2,
    "cv_folds": 5,
    "random_state": 42,
    "xgboost_params": {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "objective": "multi:softprob",
        "eval_metric": "mlogloss",
        "early_stopping_rounds": 50,
    },
    "lightgbm_params": {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_samples": 20,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "objective": "multiclass",
        "metric": "multi_logloss",
        "verbose": -1,
    },
}

# === 赛事配置 ===
@dataclass
class LeagueConfig:
    """联赛配置"""
    league_id: str
    name: str
    country: str
    tier: int  # 1=顶级联赛
    teams_count: int
    elo_k_override: Optional[float] = None  # 覆盖基础 K 值

# 支持的联赛
SUPPORTED_LEAGUES: List[LeagueConfig] = [
    LeagueConfig("eng_premier", "英超", "England", 1, 20),
    LeagueConfig("esp_la_liga", "西甲", "Spain", 1, 20),
    LeagueConfig("ita_serie_a", "意甲", "Italy", 1, 20),
    LeagueConfig("ger_bundesliga", "德甲", "Germany", 1, 18),
    LeagueConfig("fra_ligue_1", "法甲", "France", 1, 18),
    LeagueConfig("eng_championship", "英冠", "England", 2, 24),
    LeagueConfig("ned_eredivisie", "荷甲", "Netherlands", 1, 18),
    LeagueConfig("por_primeira", "葡超", "Portugal", 1, 18),
    LeagueConfig("bra_serie_a", "巴甲", "Brazil", 1, 20),
    LeagueConfig("chn_super", "中超", "China", 1, 16),
]

# === 预测输出 ===
PREDICTION_CONFIG = {
    "confidence_threshold": 0.55,   # 置信度阈值
    "output_formats": ["console", "json", "csv"],
    "kelly_fraction": 0.25,         # 凯利分数
    "min_edge": 0.05,               # 最小优势
}
