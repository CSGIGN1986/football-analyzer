"""
数据采集层：多源爬虫汇聚

数据源：
1. FlashScore — 赛程、赛果、积分榜（主要来源）
2. FBref — xG 等进阶数据
3. 本地样本数据 — 离线开发和测试

使用 browser-automation-toolbox 的 CloakBrowser 引擎进行反爬采集。
"""

import json
import time
import random
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import asdict

import requests
from bs4 import BeautifulSoup

import config as cfg

logger = logging.getLogger(__name__)


class BaseScraper:
    """爬虫基类"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.SCRAPER_CONFIG["user_agent"],
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.delay = cfg.SCRAPER_CONFIG["request_delay"]
        self.max_retries = cfg.SCRAPER_CONFIG["max_retries"]

    def _get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """带重试的 GET 请求"""
        for attempt in range(self.max_retries):
            try:
                time.sleep(self.delay + random.uniform(0, 1))
                resp = self.session.get(
                    url,
                    timeout=cfg.SCRAPER_CONFIG["timeout"],
                    **kwargs
                )
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.warning(f"请求失败 (尝试 {attempt+1}/{self.max_retries}): {url} — {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        return None

    def _parse_html(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml")


class FlashScoreScraper(BaseScraper):
    """FlashScore 爬虫 — 赛程、赛果、积分榜"""

    BASE_URL = "https://www.flashscore.com"

    # 联赛 ID 映射（FlashScore 内部 ID）
    LEAGUE_IDS = {
        "eng_premier": "dYlOSQOD",
        "esp_la_liga": "j9gSXg10",
        "ita_serie_a": "d5eQsWaK",
        "ger_bundesliga": "G9NqOlOB",
        "fra_ligue_1": "t7YkW9g2",
        "ned_eredivisie": "Q7SPYAqK",
        "por_primeira": "SK1eKxdO",
        "bra_serie_a": "nHc8lqad",
    }

    def get_fixtures(self, league_id: str, season: str) -> List[Dict]:
        """获取联赛赛程 - 使用 FlashScore API"""
        fs_id = self.LEAGUE_IDS.get(league_id)
        if not fs_id:
            logger.warning(f"未找到联赛映射: {league_id}")
            return []

        matches = []
        url = f"{self.BASE_URL}/x/feed/f_1_{fs_id}_en_1"

        resp = self._get(url)
        if not resp:
            return matches

        try:
            # FlashScore 返回特殊格式，需要解析
            data = resp.text
            # 解析 AA÷...¬AA÷ 格式
            rows = data.split("¬~AA÷") if "¬~AA÷" in data else data.split("~AA÷")
            for row in rows:
                if "¬AD÷" in row or "~AD÷" in row:
                    parts = row.replace("¬", "~").split("~")
                    match_data = {}
                    for part in parts:
                        if part.startswith("AD÷"):
                            match_data["match_date"] = part[3:]
                        elif part.startswith("AE÷"):
                            match_data["home_team"] = part[3:]
                        elif part.startswith("AF÷"):
                            match_data["away_team"] = part[3:]
                        elif part.startswith("AG÷"):
                            match_data["home_score"] = int(part[3:]) if part[3:].isdigit() else None
                        elif part.startswith("AH÷"):
                            match_data["away_score"] = int(part[3:]) if part[3:].isdigit() else None
                    if match_data:
                        matches.append(match_data)
        except Exception as e:
            logger.error(f"解析 FlashScore 数据失败: {e}")

        return matches


class FBrefScraper(BaseScraper):
    """FBref 爬虫 — xG 等进阶数据"""

    BASE_URL = "https://fbref.com"

    # 联赛 URL 映射
    LEAGUE_URLS = {
        "eng_premier": "/en/comps/9/Premier-League-Stats",
        "esp_la_liga": "/en/comps/12/La-Liga-Stats",
        "ita_serie_a": "/en/comps/11/Serie-A-Stats",
        "ger_bundesliga": "/en/comps/20/Bundesliga-Stats",
        "fra_ligue_1": "/en/comps/13/Ligue-1-Stats",
    }

    def get_match_stats(self, league_id: str, season: str) -> List[Dict]:
        """获取比赛级别的 xG 数据"""
        league_url = self.LEAGUE_URLS.get(league_id)
        if not league_url:
            return []

        url = f"{self.BASE_URL}{league_url}"
        all_stats = []

        # 先获取球队列表页面
        resp = self._get(url)
        if not resp:
            return all_stats

        soup = self._parse_html(resp.text)

        # 找到 xG 表格
        xg_table = soup.find("table", id="stats_squads_standard_for")
        if not xg_table:
            logger.warning(f"未找到 {league_id} 的 xG 数据")
            return all_stats

        teams_data = []
        tbody = xg_table.find("tbody")
        if tbody:
            for row in tbody.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if len(cells) >= 10:
                    try:
                        team_link = cells[0].find("a")
                        team_name = team_link.text if team_link else cells[0].text.strip()
                        team_url = team_link.get("href") if team_link else None
                        xg = float(cells[9].text.strip()) if cells[9].text.strip() else 0
                        teams_data.append({
                            "team_name": team_name,
                            "team_url": team_url,
                            "xg_for": xg,
                        })
                    except (ValueError, IndexError):
                        continue

        return teams_data


class SampleDataGenerator:
    """样本数据生成器 — 用于离线开发和测试"""

    SAMPLE_TEAMS = {
        "eng_premier": [
            ("mci", "Manchester City", "Man City"),
            ("ars", "Arsenal", "Arsenal"),
            ("liv", "Liverpool", "Liverpool"),
            ("mun", "Manchester United", "Man Utd"),
            ("che", "Chelsea", "Chelsea"),
            ("tot", "Tottenham", "Spurs"),
            ("new", "Newcastle United", "Newcastle"),
            ("avl", "Aston Villa", "Aston Villa"),
            ("bri", "Brighton", "Brighton"),
            ("whu", "West Ham United", "West Ham"),
        ],
        "esp_la_liga": [
            ("rma", "Real Madrid", "Real Madrid"),
            ("bar", "Barcelona", "Barcelona"),
            ("atm", "Atletico Madrid", "Atletico"),
            ("sev", "Sevilla", "Sevilla"),
            ("rso", "Real Sociedad", "Real Sociedad"),
            ("bet", "Real Betis", "Betis"),
            ("vil", "Villarreal", "Villarreal"),
            ("ath", "Athletic Bilbao", "Athletic"),
            ("val", "Valencia", "Valencia"),
            ("osa", "Osasuna", "Osasuna"),
        ],
        "ita_serie_a": [
            ("juv", "Juventus", "Juve"),
            ("int", "Inter Milan", "Inter"),
            ("mil", "AC Milan", "Milan"),
            ("nap", "Napoli", "Napoli"),
            ("rom", "Roma", "Roma"),
            ("laz", "Lazio", "Lazio"),
            ("ata", "Atalanta", "Atalanta"),
            ("fio", "Fiorentina", "Fiorentina"),
            ("tor", "Torino", "Torino"),
            ("bol", "Bologna", "Bologna"),
        ],
        "ger_bundesliga": [
            ("bay", "Bayern Munich", "Bayern"),
            ("bvb", "Borussia Dortmund", "Dortmund"),
            ("rbl", "RB Leipzig", "Leipzig"),
            ("lev", "Bayer Leverkusen", "Leverkusen"),
            ("fra", "Eintracht Frankfurt", "Frankfurt"),
            ("wol", "Wolfsburg", "Wolfsburg"),
            ("mgl", "Borussia Monchengladbach", "Gladbach"),
            ("stu", "Stuttgart", "Stuttgart"),
            ("hof", "Hoffenheim", "Hoffenheim"),
            ("wer", "Werder Bremen", "Bremen"),
        ],
        "fra_ligue_1": [
            ("psg", "Paris Saint-Germain", "PSG"),
            ("mon", "Monaco", "Monaco"),
            ("mar", "Marseille", "Marseille"),
            ("lyo", "Lyon", "Lyon"),
            ("ren", "Rennes", "Rennes"),
            ("lil", "Lille", "Lille"),
            ("nic", "Nice", "Nice"),
            ("len", "Lens", "Lens"),
            ("str", "Strasbourg", "Strasbourg"),
            ("rei", "Reims", "Reims"),
        ],
    }

    @classmethod
    def generate_seed_data(cls, db) -> Dict[str, int]:
        """生成种子数据：联赛、球队、球员、比赛、赔率、未来赛程"""
        import numpy as np
        np.random.seed(cfg.MODEL_CONFIG["random_state"])
        
        counts = {"leagues": 0, "teams": 0, "players": 0, "matches": 0, "odds": 0, "upcoming": 0}

        # 球员位置模板
        positions = {
            "GK": ["Goalkeeper"],
            "DEF": ["Centre-Back", "Left-Back", "Right-Back", "Centre-Back"],
            "MID": ["Central Midfielder", "Defensive Midfielder", "Attacking Midfielder", "Winger"],
            "FWD": ["Striker", "Centre-Forward", "Winger"],
        }
        player_names = [
            "Smith", "Jones", "Williams", "Brown", "Taylor", "Davies", "Evans", "Wilson",
            "Thomas", "Roberts", "Johnson", "Lewis", "Walker", "Robinson", "Wood", "Thompson",
            "White", "Watson", "Jackson", "Clarke", "Harris", "Martin", "Davis", "Edwards",
            "Turner", "Hill", "Moore", "Cooper", "Ward", "Morris", "King", "Baker", "Green",
            "Adams", "Nelson", "Mitchell", "Phillips", "Campbell", "Parker", "Allen",
            "Hugo", "Marco", "Lucas", "Oscar", "Pablo", "Felix", "Sergio", "Diego",
            "Andre", "Bruno", "Carlos", "Cristian", "Daniel", "Enzo", "Felipe", "Gabi",
        ]

        for league_cfg in cfg.SUPPORTED_LEAGUES:
            lid = league_cfg.league_id
            teams = cls.SAMPLE_TEAMS.get(lid)
            if not teams:
                continue

            # 写入联赛
            db.upsert_league({
                "league_id": lid,
                "name": league_cfg.name,
                "country": league_cfg.country,
                "tier": league_cfg.tier,
                "season": "2024-2025",
            })
            counts["leagues"] += 1

            # 写入球队并生成球员
            for team_id, name, short in teams:
                full_tid = f"{lid}_{team_id}"
                db.upsert_team({
                    "team_id": full_tid,
                    "name": name,
                    "short_name": short,
                    "country": league_cfg.country,
                    "league_id": lid,
                    "elo_rating": cfg.ELO_CONFIG["initial_rating"],
                    "attack_strength": 1.0,
                    "defense_strength": 1.0,
                    "home_advantage": 0.0,
                })
                counts["teams"] += 1

                # 每队生成 23 名球员
                squad = []
                squad.append(("GK", 1))        # 门将 x3
                squad.append(("GK", 2))
                squad.append(("GK", 3))
                for _ in range(7): squad.append(("DEF", None))   # 后卫 x7
                for _ in range(7): squad.append(("MID", None))   # 中场 x7
                for _ in range(6): squad.append(("FWD", None))   # 前锋 x6

                used_names = set()
                for i, (pos, num) in enumerate(squad):
                    pname = np.random.choice(player_names)
                    while pname in used_names:
                        pname = np.random.choice(player_names)
                    used_names.add(pname)
                    player_num = num if num else i
                    db.upsert_player({
                        "player_id": f"{full_tid}_p{i+1}",
                        "name": f"{pname}",
                        "team_id": full_tid,
                        "position": pos,
                        "number": player_num,
                        "is_injured": int(np.random.random() < 0.1),
                        "is_suspended": int(np.random.random() < 0.03),
                    })
                    counts["players"] += 1

            # 模拟生成全赛季 38 轮比赛
            import numpy as np
            np.random.seed(cfg.MODEL_CONFIG["random_state"] + hash(lid) % 10000)

            team_ids = [f"{lid}_{tid}" for tid, _, _ in teams]
            team_strengths = np.linspace(1.5, 0.5, len(teams))
            # 打乱以增加随机性
            np.random.shuffle(team_strengths)
            strength_map = dict(zip(team_ids, team_strengths))

            # 创建 team_short -> team_name 映射
            team_name_map = {tid: name for tid, name, _ in teams}

            num_rounds = 38
            finished_rounds = 30  # 前30轮已打完，后8轮待预测
            for round_num in range(1, num_rounds + 1):
                match_date = date(2024, 8, 10) + timedelta(days=round_num * 7)
                # 简单轮转配对
                n = len(team_ids)
                shuffled = team_ids[1:] + [team_ids[0]]
                if round_num % 2 == 1:
                    pairs = list(zip(team_ids[:n//2], team_ids[n//2:]))
                else:
                    pairs = list(zip(shuffled[:n//2], shuffled[n//2:]))

                for home_id, away_id in pairs:
                    # 提取短队名ID: 'eng_premier_tot' -> 'tot'
                    home_tid = home_id.rsplit("_", 1)[-1]
                    away_tid = away_id.rsplit("_", 1)[-1]
                    home_name = team_name_map.get(home_tid, home_id)
                    away_name = team_name_map.get(away_tid, away_id)

                    # 基于强度生成泊松分布的进球数（在下方 is_finished 分支中生成）
                    home_strength = strength_map.get(home_id, 1.0)
                    away_strength = strength_map.get(away_id, 0.8)
                    # 主场优势 +15%
                    home_lambda = home_strength * 1.7 * 1.15
                    away_lambda = away_strength * 1.3

                    match_id = f"{lid}_r{round_num}_{home_tid}_{away_tid}"
                    is_finished = round_num <= finished_rounds

                    if is_finished:
                        # 已完成的比赛：生成比分
                        home_goals = np.random.poisson(home_lambda)
                        away_goals = np.random.poisson(away_lambda)
                        home_xg = home_goals + abs(np.random.normal(0, 0.5))
                        away_xg = away_goals + abs(np.random.normal(0, 0.5))
                        status = "finished"
                    else:
                        # 未来比赛：无比分
                        home_goals = away_goals = None
                        home_xg = away_xg = None
                        status = "scheduled"

                    db.upsert_match({
                        "match_id": match_id,
                        "league_id": lid,
                        "season": "2024-2025",
                        "match_date": match_date.isoformat(),
                        "home_team_id": home_id,
                        "away_team_id": away_id,
                        "home_team_name": home_name,
                        "away_team_name": away_name,
                        "home_score": int(home_goals) if home_goals is not None else None,
                        "away_score": int(away_goals) if away_goals is not None else None,
                        "home_ht_score": int(home_goals * 0.4) if home_goals and home_goals > 0 else None,
                        "away_ht_score": int(away_goals * 0.4) if away_goals and away_goals > 0 else None,
                        "status": status,
                        "round_name": f"Round {round_num}",
                    })
                    if is_finished:
                        counts["matches"] += 1
                    else:
                        counts["upcoming"] += 1

                    # 生成赔率（所有比赛都有）
                    home_odds_val = round(1.0 / max(0.1, home_lambda / (home_lambda + away_lambda)), 2)
                    away_odds_val = round(1.0 / max(0.1, away_lambda / (home_lambda + away_lambda)), 2)
                    draw_odds_val = round(3.0 + abs(home_lambda - away_lambda) * 1.5, 2)
                    home_odds_val = max(1.10, min(15.0, home_odds_val))
                    away_odds_val = max(1.10, min(15.0, away_odds_val))
                    draw_odds_val = max(2.0, min(10.0, draw_odds_val))

                    total_goals_expected = (home_lambda + away_lambda)
                    over_odds = round(1.5 + abs(3 - total_goals_expected) * 0.5, 2)
                    under_odds = round(max(1.2, 3.5 - abs(3 - total_goals_expected) * 0.5), 2)

                    db.upsert_odds({
                        "match_id": match_id,
                        "home_odds": home_odds_val,
                        "draw_odds": draw_odds_val,
                        "away_odds": away_odds_val,
                        "over_25_odds": max(1.10, min(5.0, over_odds)),
                        "under_25_odds": max(1.10, min(5.0, under_odds)),
                        "source": "generated",
                    })
                    counts["odds"] += 1

                    if not is_finished:
                        continue  # 跳过未来比赛的统计和xG数据

                    # 写入进阶数据（仅已完成比赛）
                    db.upsert_match_stats({
                        "match_id": match_id,
                        "home_xg": round(home_xg, 2),
                        "away_xg": round(away_xg, 2),
                        "home_possession": round(50 + np.random.normal(0, 10), 1),
                        "away_possession": None,  # 互补
                        "home_shots": int(home_goals * 4 + np.random.poisson(4)),
                        "away_shots": int(away_goals * 4 + np.random.poisson(3)),
                        "home_shots_on_target": int(home_goals * 2 + np.random.poisson(2)),
                        "away_shots_on_target": int(away_goals * 2 + np.random.poisson(1.5)),
                        "home_passes": int(400 + np.random.normal(0, 50)),
                        "away_passes": int(350 + np.random.normal(0, 50)),
                        "home_pass_accuracy": round(min(95, 75 + np.random.normal(0, 5)), 1),
                        "away_pass_accuracy": round(min(95, 72 + np.random.normal(0, 5)), 1),
                        "home_corners": int(np.random.poisson(5)),
                        "away_corners": int(np.random.poisson(4)),
                        "home_yellow_cards": int(np.random.poisson(1.5)),
                        "away_yellow_cards": int(np.random.poisson(1.8)),
                        "home_red_cards": int(np.random.binomial(1, 0.05)),
                        "away_red_cards": int(np.random.binomial(1, 0.07)),
                    })

        return counts


def collect_all_data(db, use_sample: bool = True) -> Dict[str, int]:
    """统一数据采集入口"""
    counts = {"leagues": 0, "teams": 0, "matches": 0}

    if use_sample:
        logger.info("使用样本数据生成器...")
        counts = SampleDataGenerator.generate_seed_data(db)
    else:
        scraper = FlashScoreScraper()
        fbref = FBrefScraper()

        for league in cfg.SUPPORTED_LEAGUES:
            # FlashScore 赛程
            fixtures = scraper.get_fixtures(league.league_id, "2024-2025")
            logger.info(f"{league.name}: 获取到 {len(fixtures)} 场比赛")

            # FBref xG 数据
            # xg_data = fbref.get_match_stats(league.league_id, "2024-2025")

    return counts
