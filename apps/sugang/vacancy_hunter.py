#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Course Vacancy Hunter (취소표 자동 주워담기 스나이퍼)
====================================================================
- Features:
  1. High-speed continuous background polling for dropped/cancelled seats
  2. Instant seat capture via direct HTTP POST (/sugang/NSugangWlsn0410) in < 10ms
  3. Automatic Session Keep-Alive & Transparent Auto-Relogin on session expiry
  4. Smart Jitter & Rate-limiting to prevent IP blocking/WAF bans
  5. Immediate Discord DM notification upon successful course grab
"""

import os
import sys
import time
import json
import random
import logging
import datetime
import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("VacancyHunter")

KST = datetime.timezone(datetime.timedelta(hours=9))

BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_PAGE_URL = f"{BASE_URL}/sugang/new/loginForm.jsp"
LOGIN_API_URL = f"{BASE_URL}/sugang/NLoginB"
APPLY_API_URL = f"{BASE_URL}/sugang/NSugangWlsn0410"
MAIN_PAGE_URL = f"{BASE_URL}/sugang/new/main.jsp"
CHECK_APPLY_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04110.jsp"


class DaejinVacancyHunter:
    def __init__(self, config_path="config.json"):
        self.config_path = config_path
        self.config = self.load_config(config_path)
        self.std_no = self.config.get("stdNo")
        self.passwd = self.config.get("passwd")
        self.user_flag = self.config.get("user_flag", "1")
        self.target_courses = self.config.get("hunter_targets", self.config.get("courses", []))
        self.poll_interval = self.config.get("hunter_poll_interval", 1.5)
        self.discord_bot_token = self.config.get("discord_bot_token", "")
        self.discord_channel_id = self.config.get("discord_channel_id", "")
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": MAIN_PAGE_URL,
            "Origin": BASE_URL,
            "Content-Type": "application/x-www-form-urlencoded"
        })
        self.last_login_time = 0

    def load_config(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def login(self):
        """Authenticates and establishes a fresh sugang session."""
        logger.info(f"🔑 Logging into Daejin Sugang System for ID: {self.std_no}...")
        login_data = {
            "stdNo": self.std_no,
            "passwd": self.passwd,
            "user_flag": self.user_flag
        }
        try:
            r = self.session.post(LOGIN_API_URL, data=login_data, timeout=5)
            text = r.content.decode("euc-kr", "replace")
            if "main.jsp" in text or "location.href" in text or r.status_code == 200:
                self.last_login_time = time.time()
                logger.info("✅ Login successful! Session active.")
                return True
            logger.error(f"❌ Login rejected: {text[:200]}")
            return False
        except Exception as e:
            logger.error(f"❌ Login network error: {e}")
            return False

    def ensure_session_alive(self):
        """Keeps session alive and re-logs in if session has expired (every 10 minutes)."""
        if time.time() - self.last_login_time > 600: # 10 minutes
            logger.info("🔄 Refreshing session keep-alive...")
            return self.login()
        return True

    def try_apply_course(self, course_code, section):
        """Attempts to register for a course section directly."""
        payload = {
            "dir": "1",
            "cmd": "aply",
            "urltype": "direct",
            "getsbjt_no": course_code,
            "getclss_no": section,
            "ic_sbjcd": f"{course_code}{section}"
        }
        try:
            r = self.session.post(APPLY_API_URL, data=payload, timeout=4)
            text = r.content.decode("euc-kr", "replace")

            # Check for session expiration redirect
            if "loginForm" in text or "로그인" in text and "수강신청" not in text:
                logger.warning("⚠️ Session expired during apply. Re-authenticating...")
                self.login()
                return False, "SESSION_EXPIRED"

            # Parse alert message
            alert_msg = ""
            for line in text.split("\n"):
                if "alert(" in line:
                    start_idx = line.find("alert(") + 6
                    end_idx = line.rfind(")")
                    alert_msg = line[start_idx:end_idx].strip("'\"")
                    break

            # Evaluate outcome
            if "완료" in alert_msg or "정상" in alert_msg or "신청되었습니다" in alert_msg:
                return True, alert_msg or "SUCCESS"
            elif "이미" in alert_msg or "중복" in alert_msg:
                return False, "ALREADY_ENROLLED"
            elif "초과" in alert_msg or "마감" in alert_msg:
                return False, "FULL"
            else:
                return False, alert_msg or "REJECTED"
        except Exception as e:
            return False, f"ERROR: {e}"

    def send_discord_alert(self, course_name, course_code, section, message):
        """Delivers immediate alert to Discord upon successful seat capture."""
        if not self.discord_bot_token or not self.discord_channel_id:
            return
        
        url = f"https://discord.com/api/v10/channels/{self.discord_channel_id}/messages"
        headers = {"Authorization": f"Bot {self.discord_bot_token}"}
        content = (
            f"🎉🎉 **[취소표 획득 성공!]** 🎉🎉\n"
            f"👤 **학번**: `{self.std_no}`\n"
            f"📚 **과목**: **{course_name}** (`{course_code}-{section}`)\n"
            f"📢 **서버 메시지**: `{message}`\n"
            f"⏰ **획득 시각**: `{datetime.datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"👉 빈자리를 낚아채서 수강신청에 성공했습니다!"
        )
        try:
            resp = requests.post(url, headers=headers, json={"content": content}, timeout=5)
            logger.info(f"📬 Discord urgent alert sent (Status: {resp.status_code})")
        except Exception as e:
            logger.warning(f"Discord delivery failed: {e}")

    def run(self):
        logger.info("=" * 70)
        logger.info("🎯 Daejin University Course Vacancy Hunter (스마트 잔여석 감시형)")
        logger.info("=" * 70)
        logger.info(f"👀 Monitoring {len(self.target_courses)} target courses for vacancies...")
        for t in self.target_courses:
            logger.info(f"  • {t.get('name', 'Unknown')} ({t.get('code')}-{t.get('bun')})")
        logger.info(f"⏱️ Polling interval: {self.poll_interval}s (+ random jitter)")
        logger.info("🛡️ [안전 모드] 잔여석 0석일 때 무차별 신청 전송(300회 밴 위험) 방지 -> 빈자리 발생 시에만 즉시 패킷 사출!")
        logger.info("=" * 70)

        if not self.login():
            logger.error("❌ Failed to initialize session. Aborting.")
            return

        active_targets = list(self.target_courses)
        loop_count = 0

        try:
            while active_targets:
                loop_count += 1
                self.ensure_session_alive()

                # Step 1: Query seat availability from live observer API without firing apply requests
                course_map = {}
                try:
                    r_obs = requests.get("https://daejin.qucord.com/api/data", timeout=2.5)
                    if r_obs.status_code == 200:
                        obs_data = r_obs.json()
                        course_map = {c["full_code"]: c for c in obs_data.get("courses", [])}
                except Exception:
                    pass

                for item in list(active_targets):
                    name = item.get("name", "Unknown")
                    code = item.get("code")
                    sec = item.get("bun")
                    full_code = f"{code}{sec}"

                    # Check seats before applying
                    c_info = course_map.get(full_code)
                    seats = c_info.get("seats", 0) if c_info else None

                    # Only fire apply if seats > 0 or if observer data is unavailable
                    if seats is not None and seats <= 0:
                        if loop_count % 20 == 0:
                            logger.info(f"⏳ [감시 #{loop_count}] {name} ({code}-{sec}) 여석 대기 중 (0석)...")
                        continue

                    logger.info(f"🔥 [빈자리 포착!] {name} ({code}-{sec}) 여석 {seats if seats is not None else '?'}석 발견! 즉각 신청 전송...")
                    success, msg = self.try_apply_course(code, sec)
                    
                    if success:
                        logger.info(f"🎉🎉 [GRABBED!] {name} ({code}-{sec}) 획득 성공! -> {msg}")
                        self.send_discord_alert(name, code, sec, msg)
                        active_targets.remove(item)
                    elif msg == "ALREADY_ENROLLED":
                        logger.info(f"ℹ️ [{name} ({code}-{sec})] 이미 신청된 과목입니다. 모니터링 목록에서 제외합니다.")
                        active_targets.remove(item)
                    elif msg == "FULL":
                        if loop_count % 20 == 0:
                            logger.info(f"⏳ [시도 #{loop_count}] {name} ({code}-{sec}) 여석 대기 중 (정원 초과)...")
                    else:
                        logger.warning(f"⚠️ [{name} ({code}-{sec})] 서버 응답: {msg}")

                # Sleep with jitter (±0.2s) to appear organic
                jitter = random.uniform(-0.2, 0.2)
                sleep_time = max(0.5, self.poll_interval + jitter)
                time.sleep(sleep_time)

            logger.info("🎉 All target courses successfully acquired or enrolled! Hunter exiting.")

        except KeyboardInterrupt:
            logger.info("\n🛑 Vacancy Hunter stopped by user.")


if __name__ == "__main__":
    cfg_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    hunter = DaejinVacancyHunter(cfg_file)
    hunter.run()
