#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Course Registration - Playwright Browser Sniper (Version 2)
=============================================================================
- Method: Headless / Headful Chromium Browser Automation via Playwright
- Features:
  1. Full DOM Event & JavaScript Environment Emulation
  2. Persistent Credentials Injection Guard (Prevents form clearing on bounce/history.go)
  3. Non-blocking Asynchronous Dialog Interception (page.on("dialog"))
  4. Fallback Multi-section Fast-filling & Cart/Table One-click Scraper
  5. Live Screenshot Capture & Multi-part Discord DM Image Delivery
"""

import os
import sys
import time
import json
import logging
import datetime
import requests
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("BrowserSniper")

KST = datetime.timezone(datetime.timedelta(hours=9))

BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_PAGE_URL = f"{BASE_URL}/sugang/new/loginForm.jsp"


class DaejinBrowserSniper:
    def __init__(self, config_path="config.json"):
        self.config = self.load_config(config_path)
        self.std_no = self.config.get("stdNo")
        self.passwd = self.config.get("passwd")
        self.user_flag = self.config.get("user_flag", "1")
        self.target_courses = self.config.get("courses", [])
        self.target_time_str = self.config.get("target_time", "10:00:00")
        self.headless = self.config.get("headless", True)
        self.discord_bot_token = self.config.get("discord_bot_token", "")
        self.discord_channel_id = self.config.get("discord_channel_id", "")
        self.dialog_logs = []

    def load_config(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def send_discord_alert(self, content, image_path=None):
        if not self.discord_bot_token or not self.discord_channel_id:
            return
        url = f"https://discord.com/api/v10/channels/{self.discord_channel_id}/messages"
        headers = {"Authorization": f"Bot {self.discord_bot_token}"}
        try:
            if image_path and os.path.exists(image_path):
                with open(image_path, "rb") as f:
                    files = {"file": (os.path.basename(image_path), f, "image/png")}
                    requests.post(url, headers=headers, data={"content": content}, files=files, timeout=10)
            else:
                requests.post(url, headers=headers, json={"content": content}, timeout=5)
        except Exception as e:
            logger.warning(f"Discord delivery failed: {e}")

    def run(self):
        logger.info("=" * 70)
        logger.info("🌐 Daejin University Playwright Browser Sniper (Version 2)")
        logger.info("=" * 70)

        os.makedirs("screenshots", exist_ok=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080}
            )

            # Guard against form reset on page reload/bounce
            context.add_init_script(f"""
                const restoreCreds = () => {{
                    const s = document.querySelector('#stdNo');
                    const p = document.querySelector('#passwd');
                    if (s && s.value !== '{self.std_no}') s.value = '{self.std_no}';
                    if (p && p.value !== '{self.passwd}') p.value = '{self.passwd}';
                }};
                window.addEventListener('DOMContentLoaded', restoreCreds);
                setInterval(restoreCreds, 25);
            """)

            page = context.new_page()

            # Non-blocking dialog auto-accept
            def on_dialog(dialog):
                msg = dialog.message
                self.dialog_logs.append({"time": datetime.datetime.now(KST).isoformat(), "msg": msg})
                logger.info(f"📢 [Alert/Dialog] {msg}")
                try:
                    dialog.accept()
                except Exception as e:
                    logger.debug(f"Dialog accept error: {e}")

            page.on("dialog", on_dialog)

            # 1. Open login page & fill credentials
            logger.info(f"📄 Navigating to {LOGIN_PAGE_URL}...")
            page.goto(LOGIN_PAGE_URL, wait_until="networkidle")
            page.fill("#stdNo", self.std_no)
            page.fill("#passwd", self.passwd)

            # 2. Wait until registration moment
            now = datetime.datetime.now(KST)
            h, m, s = map(int, self.target_time_str.split(":"))
            target_dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
            
            while datetime.datetime.now(KST) < target_dt:
                rem = (target_dt - datetime.datetime.now(KST)).total_seconds()
                if rem > 1:
                    time.sleep(0.5)
                else:
                    time.sleep(0.005)

            # 3. Burst login click
            logger.info("🚀 Triggering login...")
            login_success = False
            for attempt in range(1, 50):
                try:
                    page.evaluate(f"""() => {{
                        const s = document.querySelector('#stdNo');
                        const p = document.querySelector('#passwd');
                        if (s) s.value = '{self.std_no}';
                        if (p) p.value = '{self.passwd}';
                        if (typeof login === 'function') login();
                        else if (document.forms[0]) document.forms[0].submit();
                    }}""")
                except Exception:
                    try:
                        page.click(".btn_login")
                    except Exception:
                        pass

                page.wait_for_timeout(80)
                cur_url = page.url
                if "main.jsp" in cur_url or ("sugang" in cur_url and "loginForm" not in cur_url):
                    logger.info(f"🎉 Login Successful on attempt #{attempt}!")
                    login_success = True
                    break

            if not login_success:
                logger.error("❌ Login failed.")
                browser.close()
                return

            page.wait_for_load_state("networkidle")
            main_shot = f"screenshots/main_{datetime.datetime.now().strftime('%H%M%S')}.png"
            page.screenshot(path=main_shot)

            # 4. Fast Apply Loop
            results = []
            for item in self.target_courses:
                name = item.get("name", "Unknown")
                code = item.get("code")
                sec = item.get("bun")
                fallbacks = item.get("fallback_bun", [])
                
                candidate_secs = [sec] + [f for f in fallbacks if f != sec]
                for candidate in candidate_secs:
                    logger.info(f"👉 Applying {name} ({code}-{candidate})...")
                    try:
                        # Direct fill into directForm
                        page.evaluate(f"""() => {{
                            const s = document.querySelector('#getsbjt_no');
                            const c = document.querySelector('#getclss_no');
                            const h = document.querySelector('#ic_sbjcd');
                            const f = document.querySelector('form[name=directForm]');
                            if (s && c && f) {{
                                s.value = '{code}';
                                c.value = '{candidate}';
                                if (h) h.value = '{code}{candidate}';
                                if (typeof quickSugang === 'function') quickSugang();
                                else f.submit();
                            }}
                        }}""")
                        page.wait_for_timeout(100)
                        results.append({"name": name, "code": code, "section": candidate, "status": "SUBMITTED"})
                        break
                    except Exception as e:
                        logger.warning(f"Error submitting {name}: {e}")

            # 5. Final Screenshot & Summary
            page.wait_for_timeout(1500)
            final_shot = f"screenshots/final_{datetime.datetime.now().strftime('%H%M%S')}.png"
            page.screenshot(path=final_shot)
            
            self.send_discord_alert(f"🎯 **[Playwright Browser Sniper 완료]**\n학번: `{self.std_no}`", final_shot)
            browser.close()
            logger.info("🎉 Playwright sniper finished.")


if __name__ == "__main__":
    cfg_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    sniper = DaejinBrowserSniper(cfg_file)
    sniper.run()
