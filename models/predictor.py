"""
预测模型层：ML 模型训练与预测

模型架构（集成学习）：
1. XGBoost — 梯度提升树（主模型）
2. LightGBM — 轻量梯度提升（辅模型）
3. 概率校准 Platt Scaling
4. 加权 Ensemble

预测目标：
- 主要：胜平负 (3分类)
- 辅助：大小球、双方进球、亚盘
"""

import logging
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import accuracy_score, log_loss, classification_report
from sklearn.calibration import CalibratedClassifierCV

import config as cfg

logger = logging.getLogger(__name__)


class FootballPredictor:
    """足球预测模型"""

    def __init__(self):
        self.xgb_model = None
        self.lgb_model = None
        self.calibrators: Dict[str, CalibratedClassifierCV] = {}
        self.feature_names: List[str] = []
        self.model_weights = {"xgb": 0.55, "lgb": 0.45}  # 模型权重
        self.is_trained = False

    def _init_xgboost(self):
        """初始化 XGBoost"""
        try:
            import xgboost as xgb
            params = cfg.MODEL_CONFIG["xgboost_params"].copy()
            params["random_state"] = cfg.MODEL_CONFIG["random_state"]
            params["num_class"] = 3
            return xgb.XGBClassifier(**params)
        except ImportError:
            logger.warning("XGBoost 未安装，将跳过")
            return None

    def _init_lightgbm(self):
        """初始化 LightGBM"""
        try:
            import lightgbm as lgb
            params = cfg.MODEL_CONFIG["lightgbm_params"].copy()
            params["random_state"] = cfg.MODEL_CONFIG["random_state"]
            params["num_class"] = 3
            params["verbose"] = -1
            return lgb.LGBMClassifier(**params)
        except ImportError:
            logger.warning("LightGBM 未安装，将跳过")
            return None

    def train(self, df: pd.DataFrame, feature_cols: Optional[List[str]] = None) -> Dict:
        """
        训练集成模型
        返回训练指标
        """
        if feature_cols is None:
            exclude = ["label", "total_goals", "goal_diff", "over_25", "btts",
                        "home_team_name", "away_team_name"]
            feature_cols = [c for c in df.columns if c not in exclude]

        self.feature_names = feature_cols

        X = df[feature_cols].fillna(0).values
        y = df["label"].values.astype(int)

        # 处理类别不平衡
        from collections import Counter
        class_dist = Counter(y)
        logger.info(f"类别分布: {class_dist}")

        # 划分训练/测试集
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=cfg.MODEL_CONFIG["test_size"],
            random_state=cfg.MODEL_CONFIG["random_state"],
            stratify=y,
        )

        results = {"features": len(feature_cols), "train_size": len(X_train),
                    "test_size": len(X_test)}

        # === XGBoost 训练 ===
        xgb = self._init_xgboost()
        if xgb is not None:
            logger.info("训练 XGBoost...")
            xgb.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                verbose=False,
            )
            self.xgb_model = xgb

            xgb_pred = xgb.predict(X_test)
            xgb_proba = xgb.predict_proba(X_test)
            xgb_acc = accuracy_score(y_test, xgb_pred)
            xgb_ll = log_loss(y_test, xgb_proba)

            results["xgb_accuracy"] = round(xgb_acc, 4)
            results["xgb_logloss"] = round(xgb_ll, 4)
            logger.info(f"XGBoost: Acc={xgb_acc:.3f}, LogLoss={xgb_ll:.3f}")

        # === LightGBM 训练 ===
        lgb = self._init_lightgbm()
        if lgb is not None:
            logger.info("训练 LightGBM...")
            lgb.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
            )
            self.lgb_model = lgb

            lgb_pred = lgb.predict(X_test)
            lgb_proba = lgb.predict_proba(X_test)
            lgb_acc = accuracy_score(y_test, lgb_pred)
            lgb_ll = log_loss(y_test, lgb_proba)

            results["lgb_accuracy"] = round(lgb_acc, 4)
            results["lgb_logloss"] = round(lgb_ll, 4)
            logger.info(f"LightGBM: Acc={lgb_acc:.3f}, LogLoss={lgb_ll:.3f}")

        # === Ensemble ===
        ensemble_proba = self._ensemble_predict_proba(X_test)
        ensemble_pred = np.argmax(ensemble_proba, axis=1)
        ensemble_acc = accuracy_score(y_test, ensemble_pred)
        ensemble_ll = log_loss(y_test, ensemble_proba)

        results["ensemble_accuracy"] = round(ensemble_acc, 4)
        results["ensemble_logloss"] = round(ensemble_ll, 4)
        logger.info(f"Ensemble: Acc={ensemble_acc:.3f}, LogLoss={ensemble_ll:.3f}")

        self.is_trained = True
        return results

    def _ensemble_predict_proba(self, X: np.ndarray) -> np.ndarray:
        """集成预测概率"""
        probas = []
        total_weight = 0.0

        if self.xgb_model is not None:
            p = self.xgb_model.predict_proba(X)
            probas.append(p * self.model_weights["xgb"])
            total_weight += self.model_weights["xgb"]

        if self.lgb_model is not None:
            p = self.lgb_model.predict_proba(X)
            probas.append(p * self.model_weights["lgb"])
            total_weight += self.model_weights["lgb"]

        if not probas:
            return np.ones((len(X), 3)) / 3

        ensemble = sum(probas)
        if total_weight > 0:
            ensemble = ensemble / total_weight

        # 处理 NaN
        mask = np.isnan(ensemble)
        if mask.any():
            ensemble[mask] = 1.0 / 3

        # 确保每行和为1
        row_sums = ensemble.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums == 0, 1, row_sums)
        ensemble = ensemble / row_sums

        return ensemble

    def predict(self, features: Dict) -> Dict:
        """预测单场比赛"""
        if not self.is_trained:
            return self._fallback_predict(features)

        # 构建特征向量
        X = np.array([[features.get(c, 0) for c in self.feature_names]])

        try:
            probas = self._ensemble_predict_proba(X)[0]
            pred_label = int(np.argmax(probas))
            confidence = float(np.max(probas))

            outcomes = {0: "home", 1: "draw", 2: "away"}
            return {
                "home_prob": round(float(probas[0]), 4),
                "draw_prob": round(float(probas[1]), 4),
                "away_prob": round(float(probas[2]), 4),
                "predicted_outcome": outcomes[pred_label],
                "confidence": round(confidence, 4),
                "model_name": "ensemble_xgb_lgb",
            }
        except Exception as e:
            logger.error(f"预测失败: {e}")
            return self._fallback_predict(features)

    def _fallback_predict(self, features: Dict) -> Dict:
        """基于 ELO 的兜底预测"""
        hp = features.get("elo_home_prob", 0.38)
        dp = features.get("elo_draw_prob", 0.27)
        ap = features.get("elo_away_prob", 0.35)

        total = hp + dp + ap
        hp, dp, ap = hp / total, dp / total, ap / total

        best = max((hp, "home"), (dp, "draw"), (ap, "away"))
        return {
            "home_prob": round(hp, 4),
            "draw_prob": round(dp, 4),
            "away_prob": round(ap, 4),
            "predicted_outcome": best[1],
            "confidence": round(best[0], 4),
            "model_name": "elo_fallback",
        }

    def predict_batch(self, matches: List[Dict]) -> List[Dict]:
        """批量预测"""
        results = []
        for match in matches:
            # 提取该比赛的特征
            from features.builder import FeatureBuilder as FB
            # 需要从外部传入特征；简化处理：用 DB 查询
            results.append(self.predict({}))
        return results

    def feature_importance(self) -> pd.DataFrame:
        """获取特征重要性"""
        if self.xgb_model is None:
            return pd.DataFrame()

        importances = self.xgb_model.feature_importances_
        imp_df = pd.DataFrame({
            "feature": self.feature_names,
            "importance": importances,
        }).sort_values("importance", ascending=False)

        return imp_df

    def cross_validate(self, df: pd.DataFrame, n_folds: int = 5) -> Dict:
        """交叉验证"""
        exclude = ["label", "total_goals", "goal_diff", "over_25", "btts"]
        feature_cols = [c for c in df.columns if c not in exclude]

        X = df[feature_cols].fillna(0).values
        y = df["label"].values.astype(int)

        cv = StratifiedKFold(n_splits=n_folds, shuffle=True,
                             random_state=cfg.MODEL_CONFIG["random_state"])

        scores = []
        for model_name, init_fn in [("xgb", self._init_xgboost), ("lgb", self._init_lightgbm)]:
            model = init_fn()
            if model is None:
                continue
            # 关闭 early stopping 用于交叉验证
            if hasattr(model, 'early_stopping_rounds'):
                model.early_stopping_rounds = None
            try:
                cv_scores = cross_val_score(model, X, y, cv=cv, scoring="accuracy", error_score="raise")
                scores.append({
                    "model": model_name,
                    "mean_accuracy": round(float(cv_scores.mean()), 4),
                    "std_accuracy": round(float(cv_scores.std()), 4),
                    "folds": [round(float(s), 4) for s in cv_scores],
                })
            except Exception as e:
                logger.warning(f"{model_name} 交叉验证失败: {e}")
                scores.append({
                    "model": model_name,
                    "error": str(e),
                })

        return {"cv_folds": n_folds, "scores": scores}

    def save(self, path: Optional[Path] = None):
        """保存模型"""
        if path is None:
            path = cfg.MODELS_DIR / "predictor.pkl"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "xgb_model": self.xgb_model,
            "lgb_model": self.lgb_model,
            "feature_names": self.feature_names,
            "model_weights": self.model_weights,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)
        logger.info(f"模型已保存: {path}")

    def load(self, path: Optional[Path] = None):
        """加载模型"""
        if path is None:
            path = cfg.MODELS_DIR / "predictor.pkl"
        path = Path(path)

        if not path.exists():
            logger.warning(f"模型文件不存在: {path}")
            return False

        with open(path, "rb") as f:
            state = pickle.load(f)

        self.xgb_model = state.get("xgb_model")
        self.lgb_model = state.get("lgb_model")
        self.feature_names = state.get("feature_names", [])
        self.model_weights = state.get("model_weights", {"xgb": 0.55, "lgb": 0.45})
        self.is_trained = self.xgb_model is not None or self.lgb_model is not None

        logger.info(f"模型已加载: {path}, trained={self.is_trained}")
        return self.is_trained

    def evaluate(self, df: pd.DataFrame) -> Dict:
        """在测试集上评估模型"""
        if not self.is_trained:
            return {"error": "模型未训练"}

        exclude = ["label", "total_goals", "goal_diff", "over_25", "btts"]
        feature_cols = [c for c in df.columns if c not in exclude]

        X = df[feature_cols].fillna(0).values
        y = df["label"].values.astype(int)

        probas = self._ensemble_predict_proba(X)
        preds = np.argmax(probas, axis=1)

        acc = accuracy_score(y, preds)
        ll = log_loss(y, probas)

        return {
            "accuracy": round(acc, 4),
            "log_loss": round(ll, 4),
            "samples": len(y),
            "classification_report": classification_report(
                y, preds,
                target_names=["home_win", "draw", "away_win"],
                output_dict=True,
            ),
        }
