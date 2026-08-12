"""
500.com 数据采集器 — 竞彩历史赛果、赔率、开奖

500.com 是最完整的竞彩数据源，包含:
  - 历史赛果 (完场赛果)
  - 赔率变化 (SPF/RQSPF 即时赔率)
  - 开奖信息
  - 进球/半场数据

使用 Playwright 浏览器自动化进行数据采集。
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class FiveHundredCollector:
    """500.com 竞彩数据采集器"""

    BASE_URL = "https://trade.500.com/jczq/"
    LIVE_URL = "https://live.500.com/"
    ODDS_URL = "https://odds.500.com/fenxi/"

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = Path(output_dir) if output_dir else Path("data/five_hundred")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _get_page_with_playwright(self, url: str, wait_selector: str = None,
                                   timeout: int = 30000) -> Optional[str]:
        """使用 Playwright 获取页面内容"""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright 未安装，请运行: pip install playwright && playwright install chromium")
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1920, "height": 1080},
                locale="zh-CN",
            )
            page = context.new_page()

            try:
                page.goto(url, timeout=timeout, wait_until="networkidle")

                if wait_selector:
                    page.wait_for_selector(wait_selector, timeout=timeout)

                # 等待 JS 渲染完成
                time.sleep(2)

                html = page.content()
                return html
            except Exception as e:
                logger.error(f"Playwright 页面加载失败: {url} - {e}")
                return None
            finally:
                browser.close()

    def _get_api_data(self, url: str) -> Optional[dict]:
        """通过 API 获取数据（如果可用）"""
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://trade.500.com/jczq/",
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"API 请求失败: {url} - {e}")
            return None

    def collect_today_matches(self) -> List[Dict]:
        """采集今日竞彩足球比赛（从 500.com）"""
        logger.info("正在从 500.com 采集今日比赛...")

        # 500.com 的 API 获取当日赛程
        # 格式: https://trade.500.com/jczq/?date=2026-08-09
        today = datetime.now().strftime("%Y-%m-%d")

        # 尝试通过网页抓取
        html = self._get_page_with_playwright(
            f"https://trade.500.com/jczq/?date={today}",
            wait_selector=".bet-tb",
        )

        if not html:
            logger.warning("500.com 页面获取失败，尝试备用方案")
            return self._collect_via_odds_page(today)

        return self._parse_match_list(html)

    def _parse_match_list(self, html: str) -> List[Dict]:
        """解析比赛列表 HTML"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        matches = []

        # 500.com 的比赛表格结构
        rows = soup.select(".bet-tb tr")
        current_date = ""
        current_league = ""

        for row in rows:
            # 日期行
            date_cell = row.select_one(".date-bg")
            if date_cell:
                current_date = date_cell.text.strip()
                continue

            # 联赛行
            league_cell = row.select_one(".league-bg td")
            if league_cell:
                current_league = league_cell.text.strip()
                continue

            # 比赛行
            match_cells = row.select("td")
            if len(match_cells) < 8:
                continue

            try:
                match_num = match_cells[0].text.strip() if len(match_cells) > 0 else ""
                match_time = match_cells[2].text.strip() if len(match_cells) > 2 else ""
                home_team = match_cells[3].text.strip() if len(match_cells) > 3 else ""
                away_team = match_cells[5].text.strip() if len(match_cells) > 5 else ""
                handicap = match_cells[4].text.strip() if len(match_cells) > 4 else ""

                # 提取赔率
                odds_spf = []
                odds_rqspf = []
                for i in range(6, min(len(match_cells), 12)):
                    text = match_cells[i].text.strip()
                    if text and text != "-":
                        if i < 9:
                            odds_spf.append(text)
                        else:
                            odds_rqspf.append(text)

                if match_num and home_team:
                    matches.append({
                        "matchNum": match_num,
                        "date": current_date,
                        "league": current_league,
                        "time": match_time,
                        "homeTeam": home_team,
                        "awayTeam": away_team,
                        "handicap": handicap,
                        "spfOdds": odds_spf,
                        "rqspfOdds": odds_rqspf,
                        "source": "500.com",
                    })
            except Exception as e:
                logger.debug(f"解析比赛行失败: {e}")
                continue

        return matches

    def _collect_via_odds_page(self, date_str: str) -> List[Dict]:
        """备用方案: 通过赔率分析页获取数据"""
        html = self._get_page_with_playwright(
            f"https://odds.500.com/fenxi/shuju-{date_str.replace('-', '')}.shtml",
            wait_selector=".odds-table",
        )
        if not html:
            return []

        matches = []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 解析赔率页面的比赛数据
        rows = soup.select(".odds-table tr")
        for row in rows[1:]:  # 跳过表头
            cells = row.select("td")
            if len(cells) < 5:
                continue
            try:
                match = {
                    "matchNum": cells[0].text.strip(),
                    "league": cells[1].text.strip() if len(cells) > 1 else "",
                    "homeTeam": cells[2].text.strip() if len(cells) > 2 else "",
                    "score": cells[3].text.strip() if len(cells) > 3 else "",
                    "awayTeam": cells[4].text.strip() if len(cells) > 4 else "",
                    "source": "500.com",
                }
                matches.append(match)
            except Exception:
                continue

        return matches

    def collect_results(self, days_back: int = 30) -> List[Dict]:
        """采集历史赛果"""
        logger.info(f"正在采集近 {days_back} 天的赛果...")
        all_results = []

        for i in range(days_back):
            date = (datetime.now() - timedelta(days=i+1)).strftime("%Y-%m-%d")
            try:
                html = self._get_page_with_playwright(
                    f"https://trade.500.com/jczq/?date={date}",
                    wait_selector=".bet-tb",
                )
                if html:
                    results = self._parse_match_list(html)
                    # 标记为历史赛果
                    for r in results:
                        r["matchDate"] = date
                        r["type"] = "result"
                    all_results.extend(results)
                    logger.info(f"  {date}: {len(results)} 场比赛")
                time.sleep(2)  # 避免请求过快
            except Exception as e:
                logger.warning(f"  {date} 失败: {e}")

        return all_results

    def collect_odds_history(self, match_id: str) -> Optional[Dict]:
        """采集单场比赛的赔率变化历史"""
        html = self._get_page_with_playwright(
            f"https://odds.500.com/fenxi/ouzhi-{match_id}.shtml",
            wait_selector=".table-container",
        )
        if not html:
            return None

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        odds_data = {"matchId": match_id, "oddsHistory": []}

        # 解析赔率变化表
        rows = soup.select(".table-container table tr")
        for row in rows[1:]:
            cells = row.select("td")
            if len(cells) >= 6:
                try:
                    odds_data["oddsHistory"].append({
                        "time": cells[0].text.strip(),
                        "home": cells[1].text.strip(),
                        "draw": cells[2].text.strip(),
                        "away": cells[3].text.strip(),
                        "company": cells[4].text.strip() if len(cells) > 4 else "",
                    })
                except Exception:
                    continue

        return odds_data

    def collect_all(self) -> dict:
        """采集全部 500.com 数据"""
        logger.info("正在采集 500.com 数据...")

        today_matches = self.collect_today_matches()
        logger.info(f"  今日比赛: {len(today_matches)} 场")

        result = {
            "source": "500.com",
            "fetchTime": datetime.now().isoformat(),
            "todayMatches": today_matches,
        }

        # 保存
        date_str = datetime.now().strftime("%Y%m%d")
        json_path = self.output_dir / f"five_hundred_{date_str}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"  已保存: {json_path}")

        return result
