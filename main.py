"""
足球分析预测系统 — 主入口

用法：
    python main.py setup        — 初始化数据库和种子数据
    python main.py train        — 训练预测模型
    python main.py predict      — 预测下一轮比赛
    python main.py evaluate     — 模型评估和交叉验证
    python main.py report       — 生成分析报告
    python main.py dashboard    — 查看系统概况
"""

import sys
import logging
from pathlib import Path
from datetime import date, datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "system.log",
                            encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def cmd_setup():
    """初始化系统：建表、生成种子数据、计算 ELO"""
    from data.database import FootballDB
    from data.scraper import collect_all_data
    from analysis.elo import EloSystem

    db = FootballDB()
    db.init_schema()
    logger.info("数据库表结构已创建")

    counts = collect_all_data(db, use_sample=True)
    logger.info(f"数据导入完成: {counts}")

    # 计算全量 ELO
    elo = EloSystem(db)
    elo.load_from_db()
    elo.process_history()
    logger.info("ELO 评分计算完成")

    # 打印排名
    rankings = elo.get_ratings_table(limit=20)
    print("\n=== ELO 排名 TOP 20 ===")
    print(f"{'排名':<6}{'球队':<25}{'ELO':<10}{'联赛'}")
    print("-" * 55)
    for i, r in enumerate(rankings, 1):
        league_name = r.get("league", "")
        print(f"{i:<6}{r['name']:<25}{r['elo']:<10.1f}{league_name}")

    print(f"\n✅ 初始化完成！共 {counts['matches']} 场比赛数据。")

    return db, elo


def cmd_train():
    """训练预测模型"""
    from data.database import FootballDB
    from analysis.elo import EloSystem
    from analysis.form import FormAnalyzer
    from analysis.h2h import H2HAnalyzer
    from features.builder import FeatureBuilder
    from models.predictor import FootballPredictor

    db = FootballDB()
    logger.info("数据库连接已建立")

    # 初始化分析器
    elo = EloSystem(db)
    elo.load_from_db()
    elo.process_history()

    form_analyzer = FormAnalyzer(db)
    h2h_analyzer = H2HAnalyzer(db)

    # 构建特征
    fb = FeatureBuilder(db, elo, form_analyzer, h2h_analyzer)
    df = fb.build_dataset(limit=10000)
    logger.info(f"数据集: {len(df)} 条记录")

    if len(df) < 100:
        logger.warning("数据量不足，请先运行 setup 生成样本数据")
        return

    # 训练模型
    predictor = FootballPredictor()
    results = predictor.train(df)

    print("\n=== 模型训练结果 ===")
    for k, v in results.items():
        if isinstance(v, float):
            print(f"{k}: {v:.4f}")
        else:
            print(f"{k}: {v}")

    # 交叉验证
    cv_results = predictor.cross_validate(df)
    print("\n=== 交叉验证 ===")
    for s in cv_results["scores"]:
        print(f"{s['model']}: {s['mean_accuracy']:.4f} ± {s['std_accuracy']:.4f}")

    # 特征重要性
    importance = predictor.feature_importance()
    print(f"\n=== 特征重要性 TOP 15 ===")
    for i, row in importance.head(15).iterrows():
        bar = "█" * int(row["importance"] * 100)
        print(f"{row['feature']:<35} {row['importance']:.4f} {bar}")

    # 保存模型
    predictor.save()
    logger.info("模型已保存")

    # 模型评估
    eval_results = predictor.evaluate(df)
    print(f"\n=== 模型命中率 ===")
    print(f"准确率: {eval_results['accuracy']:.2%}")
    print(f"Log Loss: {eval_results['log_loss']:.4f}")
    if "classification_report" in eval_results:
        cr = eval_results["classification_report"]
        for cls, metrics in cr.items():
            if cls in ("accuracy", "macro avg", "weighted avg"):
                continue
            if isinstance(metrics, dict):
                print(f"  {cls}: Prec={metrics['precision']:.3f}, "
                      f"Rec={metrics['recall']:.3f}, F1={metrics['f1-score']:.3f}")

    return predictor, df


def cmd_predict(league_id: str = None):
    """预测比赛"""
    from data.database import FootballDB
    from analysis.elo import EloSystem
    from analysis.form import FormAnalyzer
    from analysis.h2h import H2HAnalyzer
    from analysis.poisson import PoissonModel
    from features.builder import FeatureBuilder
    from models.predictor import FootballPredictor

    db = FootballDB()

    # 加载分析器和模型
    elo = EloSystem(db)
    elo.load_from_db()

    form_analyzer = FormAnalyzer(db)
    h2h_analyzer = H2HAnalyzer(db)
    fb = FeatureBuilder(db, elo, form_analyzer, h2h_analyzer)

    # 加载/训练模型
    predictor = FootballPredictor()
    if not predictor.load():
        logger.info("模型不存在，先训练...")
        predictor = cmd_train()

    # 获取待预测比赛
    matches = db.get_upcoming_matches(league_id=league_id, limit=100)
    if not matches:
        logger.info("无待预测比赛。生成当前比赛的预测...")
        # 取最近已完成的比赛做验证预测
        matches = db.get_matches(status="finished", limit=20)

    print(f"\n{'='*90}")
    print(f"{'足球预测系统 — 比赛预测':^90}")
    print(f"{'='*90}")

    predictions = []
    for match in matches:
        feats = fb.build_match_features(match)
        if not feats:
            continue

        ml_pred = predictor.predict(feats)

        # 泊松模型预测
        pm = PoissonModel(db)
        strengths = pm.estimate_team_strengths(match.get("league_id", ""))
        ha, hd = strengths.get(match["home_team_id"], (1.0, 1.0))
        aa, ad = strengths.get(match["away_team_id"], (1.0, 1.0))
        hl, al = pm.estimate_lambdas(
            match["home_team_id"], match["away_team_id"],
            match.get("league_id", ""), ha, hd, aa, ad
        )
        poisson_pred = pm.predict_match(hl, al)

        # 综合预测
        home_prob = (ml_pred["home_prob"] + poisson_pred["home_win_prob"]) / 2
        draw_prob = (ml_pred["draw_prob"] + poisson_pred["draw_prob"]) / 2
        away_prob = (ml_pred["away_prob"] + poisson_pred["away_win_prob"]) / 2

        total = home_prob + draw_prob + away_prob
        home_prob /= total
        draw_prob /= total
        away_prob /= total

        best_prob = max(home_prob, draw_prob, away_prob)
        if best_prob == home_prob:
            outcome = "主胜"
        elif best_prob == draw_prob:
            outcome = "平局"
        else:
            outcome = "客胜"

        # 显示预测
        home_name = match.get("home_team_name", match["home_team_id"])
        away_name = match.get("away_team_name", match["away_team_id"])
        match_date = match.get("match_date", "?")

        print(f"\n📅 {match_date}")
        print(f"   {home_name} vs {away_name}")
        print(f"   {'─'*50}")
        print(f"   主胜: {home_prob:.1%}  │  平局: {draw_prob:.1%}  │  客胜: {away_prob:.1%}")
        print(f"   预测: {outcome}  (置信度: {best_prob:.1%})")
        print(f"   期望进球: {hl:.2f} - {al:.2f}")
        print(f"   大2.5: {poisson_pred['over_25_prob']:.1%}  |  BTTS: {poisson_pred['btts_prob']:.1%}")

        # 保存预测
        db.save_prediction({
            "match_id": match["match_id"],
            "home_prob": home_prob,
            "draw_prob": draw_prob,
            "away_prob": away_prob,
            "predicted_outcome": ml_pred["predicted_outcome"],
            "confidence": best_prob,
            "expected_home_goals": hl,
            "expected_away_goals": al,
            "over_25_prob": poisson_pred["over_25_prob"],
            "over_35_prob": poisson_pred["over_35_prob"],
            "btts_prob": poisson_pred["btts_prob"],
            "model_name": "ensemble+poisson",
        })

        predictions.append({
            "match": f"{home_name} vs {away_name}",
            "outcome": outcome,
            "confidence": best_prob,
        })

    print(f"\n{'='*90}")
    print(f"共预测 {len(predictions)} 场比赛")
    return predictions


def cmd_evaluate():
    """模型评估"""
    from data.database import FootballDB
    from analysis.elo import EloSystem
    from analysis.form import FormAnalyzer
    from analysis.h2h import H2HAnalyzer
    from features.builder import FeatureBuilder
    from models.predictor import FootballPredictor

    db = FootballDB()
    elo = EloSystem(db)
    elo.load_from_db()
    elo.process_history()

    form_analyzer = FormAnalyzer(db)
    h2h_analyzer = H2HAnalyzer(db)
    fb = FeatureBuilder(db, elo, form_analyzer, h2h_analyzer)

    df = fb.build_dataset(limit=5000)
    logger.info(f"评估数据集: {len(df)} 条记录")

    # 按联赛分别评估
    print(f"\n=== 按联赛评估 ===")
    predictor = FootballPredictor()
    if predictor.load():
        eval_result = predictor.evaluate(df)
        print(f"总体准确率: {eval_result['accuracy']:.2%}")

    # 交叉验证
    predictor = FootballPredictor()
    cv = predictor.cross_validate(df, n_folds=5)
    print(f"\n=== 5折交叉验证 ===")
    for s in cv["scores"]:
        print(f"{s['model']}: {s['mean_accuracy']:.2%} (±{s['std_accuracy']:.2%})")

    # 按联赛评估
    leagues = db.get_leagues()
    for league in leagues:
        lid = league["league_id"]
        ldf = df
        # Note: 实际按league过滤需要从matches表关联
        # 这里简化处理
        print(f"\n  {league['name']}: 数据已加载")


def cmd_report():
    """生成分析报告"""
    from data.database import FootballDB
    from analysis.elo import EloSystem

    db = FootballDB()
    elo = EloSystem(db)
    elo.load_from_db()

    print(f"""
{'='*70}
                   足球分析预测系统 — 分析报告
                   生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
{'='*70}

【数据库概况】
""")

    leagues = db.get_leagues()
    print(f"  联赛数量: {len(leagues)}")
    for league in leagues:
        lid = league["league_id"]
        teams = db.get_teams(league_id=lid)
        print(f"  · {league['name']}: {len(teams)} 支球队")

    matches = db.get_matches(status="finished", limit=1)
    upcoming = db.get_upcoming_matches()
    print(f"\n  已完成比赛: {len(db.get_matches(status='finished', limit=10000))} 场")
    print(f"  待预测比赛: {len(upcoming)} 场")

    print(f"\n【ELO 排名 TOP 10】")
    rankings = elo.get_ratings_table(limit=10)
    for i, r in enumerate(rankings, 1):
        print(f"  {i}. {r['name']:<25} {r['elo']:,.1f}")

    # 近期预测记录
    predictions = db.get_predictions(limit=10)
    if predictions:
        print(f"\n【近期预测记录】")
        for p in predictions[:5]:
            print(f"  {p.get('home_team_name', '?')} vs {p.get('away_team_name', '?')}: "
                  f"{p['predicted_outcome']} ({p['confidence']:.1%})")


def cmd_dashboard():
    """系统概况"""
    from data.database import FootballDB
    import config as cfg

    db = FootballDB()

    # 获取统计信息
    teams = db.get_teams()
    matches = db.get_matches(status="finished", limit=100000)
    upcoming = db.get_upcoming_matches()
    predictions = db.get_predictions(limit=100)

    leagues_count = len(db.get_leagues())

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║            ⚽ 足球分析预测系统 — 系统概况                     ║
╠══════════════════════════════════════════════════════════════╣
║  联赛: {leagues_count:<4}  球队: {len(teams):<4}  比赛: {len(matches):<6}               ║
║  待预测: {len(upcoming):<4}  预测记录: {len(predictions):<4}                         ║
╠══════════════════════════════════════════════════════════════╣
║  数据目录: {str(cfg.DATA_DIR):<40} ║
║  模型目录: {str(cfg.MODELS_DIR):<40} ║
╚══════════════════════════════════════════════════════════════╝
""")

    import config as cfg_ref

    # 模型文件状态
    model_path = cfg_ref.MODELS_DIR / "predictor.pkl"
    if model_path.exists():
        size = model_path.stat().st_size
        print(f"  ✅ 模型文件: predictor.pkl ({size/1024:.1f} KB)")
    else:
        print(f"  ⚠️  模型文件: 未找到 (请运行 python main.py train)")

    print(f"\n  数据文件: football.db")
    db_path = cfg_ref.DATA_DIR / "football.db"
    if db_path.exists():
        print(f"    大小: {db_path.stat().st_size/1024:.1f} KB")


def main():
    """主入口"""
    import config as cfg_ref

    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    league_id = sys.argv[2] if len(sys.argv) > 2 else None

    commands = {
        "setup": cmd_setup,
        "train": cmd_train,
        "predict": lambda: cmd_predict(league_id),
        "evaluate": cmd_evaluate,
        "report": cmd_report,
        "dashboard": cmd_dashboard,
    }

    if cmd in commands:
        logger.info(f"执行命令: {cmd}")
        commands[cmd]()
    else:
        print(f"用法: python main.py [{'|'.join(commands.keys())}]")
        print(f"可用命令: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
