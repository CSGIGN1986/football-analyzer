"""
数据采集浏览器工具 — 基于 Playwright 的统一浏览器采集

封装 Playwright 浏览器操作，供各采集器共用。
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class BrowserScraper:
    """基于 Playwright 的浏览器采集基类"""

    def __init__(self):
        self._playwright = None
        self._browser = None

    def _ensure_browser(self):
        """延迟初始化浏览器"""
        if self._browser is not None:
            return
        
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Playwright 未安装。运行: pip install playwright && playwright install chromium")

        self._playwright = sync_playwright().start()

        # Use agent-browser's Chrome if available, otherwise default
        import os
        agent_chrome = os.path.expandvars(
            r"%USERPROFILE%\.agent-browser\browsers\chrome-151.0.7922.77\chrome.exe"
        )
        if os.path.exists(agent_chrome):
            executable_path = agent_chrome
        else:
            executable_path = None

        self._browser = self._playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

    def get_page(self, url: str, wait_selector: str = None,
                 timeout: int = 30000) -> Optional[str]:
        """获取页面 HTML 内容"""
        self._ensure_browser()

        context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        page = context.new_page()

        try:
            page.goto(url, timeout=timeout, wait_until="networkidle")

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout)
                except Exception:
                    pass

            time.sleep(2)  # 等待 JS 渲染
            html = page.content()
            return html
        except Exception as e:
            logger.error(f"浏览器加载失败: {url} - {e}")
            return None
        finally:
            context.close()

    def get_json_from_api(self, url: str, headers: dict = None) -> Optional[dict]:
        """通过浏览器上下文获取 JSON API 数据（绕过反爬）"""
        self._ensure_browser()

        context = self._browser.new_context()
        page = context.new_page()

        try:
            # 先访问主页建立 session
            page.goto("https://www.flashscore.com/", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            # 通过 evaluate 发起 fetch（使用浏览器的 cookie/session）
            result = page.evaluate("""
                async (url) => {
                    const resp = await fetch(url, {
                        headers: {
                            'Accept': '*/*',
                            'X-Requested-With': 'XMLHttpRequest',
                        }
                    });
                    return await resp.text();
                }
            """, url)

            import json
            return json.loads(result)
        except Exception as e:
            logger.error(f"API 请求失败: {url} - {e}")
            return None
        finally:
            context.close()

    def close(self):
        """关闭浏览器"""
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = None
        self._playwright = None

    def __del__(self):
        self.close()


# 全局单例
_browser_instance: Optional[BrowserScraper] = None


def get_browser() -> BrowserScraper:
    """获取浏览器单例"""
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = BrowserScraper()
    return _browser_instance
