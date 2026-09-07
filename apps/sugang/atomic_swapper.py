#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Credit-Aware Safe Atomic Swapper (학점 한도 초과 방지 원자적 수강 교체기)
========================================================================================
- Use Case:
  - 수강신청 최대 가능 학점(예: 18학점)이 이미 꽉 차 있어서 그냥 신청하면 서버에서 학점 초과로 튕길 때 사용.
- Protocol:
  1. Passive Watchdog: 희망 목표 과목의 잔여석을 실시간 모니터링 (자리가 없으면 기존 과목을 절대 건드리지 않음).
  2. The Instant Seats > 0:
     - Step 1: 기존 보유 과목 삭제(Drop) 요청 전송 (~10ms) -> 학점 확보
     - Step 2: 목표 과목 즉시 수강신청(Apply) 전송 (~10ms) -> 교체 완료
     - Step 3 (안전 롤백): 만약 그 사이에 다른 사람이 낚아채서 실패할 경우, 즉시 원래 과목(또는 대안 과목)으로 재신청 롤백.
"""

import os
import sys
import time
import json
import re
import random
import logging
import datetime
import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("AtomicSwapper")

KST = datetime.timezone(datetime.timedelta(hours=9))

BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_API_URL = f"{BASE_URL}/sugang/NLoginB"
APPLY_API_URL = f"{BASE_URL}/sugang/NSugangWlsn0410"
CONFIRMED_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04110.jsp"


class DaejinAtomicSwapper:
    def __init__(self, config_path="config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.std_no = self.config.get("stdNo")
        self.passwd = self.config.get("passwd")
        self.user_flag = self.config.get("user_flag", "1")
        self.discord_bot_token = self.config.get("discord_bot_token", "")
        self.discord_channel_id = self.config.get("discord_channel_id", "")

        # Swap Targets Configuration
        swap_cfg = self.config.get("swap_targets", {})
        
        # 1. Course to Drop
        drop_raw = swap_cfg.get("drop_course", {
            "name": "AI시대의콘텐츠크리에이션(01분반)",
            "code": "922616",
            "bun": "01"
        })
        self.drop_course_info = {
            "name": drop_raw.get("name", "DropCourse"),
            "code": str(drop_raw["code"]),
            "bun": str(drop_raw["bun"]).zfill(2),
            "full_code": f"{str(drop_raw['code'])}{str(drop_raw['bun']).zfill(2)}"
        }
        self.currently_held = dict(self.drop_course_info)

        # 2. Wanted Courses (in priority order)
        wanted_raw = swap_cfg.get("wanted_courses", [
            {"name": "AI기반프로그래밍입문(01분반)", "code": "922605", "bun": "01"},
            {"name": "AI시대의콘텐츠크리에이션(02분반)", "code": "922616", "bun": "02"}
        ])
        self.wanted_courses = []
        for w in wanted_raw:
            self.wanted_courses.append({
                "name": w.get("name", "WantedCourse"),
                "code": str(w["code"]),
                "bun": str(w["bun"]).zfill(2),
                "full_code": f"{str(w['code'])}{str(w['bun']).zfill(2)}"
            })

        # 3. Rollback Course (default to drop_course if not set)
        rb_raw = swap_cfg.get("rollback_course", self.drop_course_info)
        self.rollback_course_info = {
            "name": rb_raw.get("name", self.drop_course_info["name"]),
            "code": str(rb_raw["code"]),
            "bun": str(rb_raw["bun"]).zfill(2),
            "full_code": f"{str(rb_raw['code'])}{str(rb_raw['bun']).zfill(2)}"
        }

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": f"{BASE_URL}/sugang/new/main.jsp",
            "Origin": BASE_URL
        })
        self.last_login_time = 0

    def login(self):
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
                logger.info(f"✅ Login successful for ID: {self.std_no}")
                return True
            logger.error(f"❌ Login failed: {text[:200]}")
            return False
        except Exception as e:
            logger.error(f"❌ Login error: {e}")
            return False

    def sync_actual_held(self):
        try:
            r = self.session.get(CONFIRMED_URL, timeout=4)
            html = r.content.decode("euc-kr", "replace")
            for w in self.wanted_courses:
                if f"{w['code']}-{w['bun']}" in html or w['full_code'] in html:
                    self.currently_held = w
                    break
            logger.info(f"📋 Currently holding: {self.currently_held['name']} ({self.currently_held['full_code']})")
        except Exception as e:
            logger.warning(f"Sync error: {e}")

    def ensure_session(self):
        if time.time() - self.last_login_time > 600:
            logger.info("🔄 Refreshing session token...")
            self.login()

    def check_seat_for_course(self, course_info):
        """Checks real-time remaining seats from observer API or university portal."""
        # Try fast local observer endpoint first if available
        try:
            r = requests.get("http://127.0.0.1:8888/api/data", timeout=1.0)
            if r.status_code == 200:
                data = r.json()
                for c in data.get("courses", []):
                    if c["full_code"] == course_info["full_code"]:
                        return c.get("seats", 0)
        except Exception:
            pass

        # Fallback to direct query on university portal
        try:
            url = f"{BASE_URL}/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42006&ppage=1"
            r = self.session.get(url, timeout=3)
            html = r.content.decode("euc-kr", "replace")
            soup = BeautifulSoup(html, "html.parser")
            for tr in soup.find_all("tr"):
                cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cols) >= 9 and cols[1] == f"{course_info['code']}-{course_info['bun']}":
                    return int(cols[8]) if cols[8].isdigit() else 0
        except Exception as e:
            logger.debug(f"Seat query error: {e}")
        return 0

    def drop_course(self, course_info):
        payload = {
            "cmd": "cancle",
            "urltype": "page",
            "cousNm": course_info["name"].encode("euc-kr"),
            "jsg_subcd": course_info["full_code"]
        }
        try:
            r = self.session.post(APPLY_API_URL, data=payload, timeout=3)
            text = r.content.decode("euc-kr", "replace")
            logger.info(f"🗑️ [Drop Request Sent] {course_info['name']} ({course_info['full_code']})")
            return "삭제" in text or "완료" in text or r.status_code == 200
        except Exception as e:
            logger.error(f"Drop error: {e}")
            return False

    def apply_course(self, course_info):
        payload = {
            "dir": "1",
            "cmd": "aply",
            "urltype": "direct",
            "getsbjt_no": course_info["code"],
            "getclss_no": course_info["bun"],
            "ic_sbjcd": course_info["full_code"]
        }
        try:
            r = self.session.post(APPLY_API_URL, data=payload, timeout=3)
            text = r.content.decode("euc-kr", "replace")
            alert_msg = ""
            for line in text.split("\n"):
                if "alert(" in line:
                    start_idx = line.find("alert(") + 6
                    end_idx = line.rfind(")")
                    alert_msg = line[start_idx:end_idx].strip("'\"")
                    break
            
            success = "완료" in alert_msg or "정상" in alert_msg or "신청되었습니다" in alert_msg
            return success, alert_msg
        except Exception as e:
            return False, f"Apply error: {e}"

    def send_discord_alert(self, msg):
        if not self.discord_bot_token or not self.discord_channel_id:
            return
        url = f"https://discord.com/api/v10/channels/{self.discord_channel_id}/messages"
        headers = {"Authorization": f"Bot {self.discord_bot_token}"}
        try:
            requests.post(url, headers=headers, json={"content": msg}, timeout=5)
        except Exception:
            pass

    def perform_atomic_swap(self, target_course):
        old = self.currently_held
        logger.info(f"🚨 [ATOMIC SWAP TRIGGERED] Dropping {old['name']} -> Sniping {target_course['name']}...")
        
        # Step 1: Drop old course
        t0 = time.perf_counter()
        dropped = self.drop_course(old)
        t_drop = (time.perf_counter() - t0) * 1000
        logger.info(f"   ↳ Step 1 (Drop Old): {t_drop:.1f}ms | Success={dropped}")

        # Step 2: Apply new course
        t1 = time.perf_counter()
        applied, alert = self.apply_course(target_course)
        t_apply = (time.perf_counter() - t1) * 1000
        logger.info(f"   ↳ Step 2 (Apply New): {t_apply:.1f}ms | Success={applied} | Alert='{alert}'")

        if applied:
            logger.info(f"🎉🎉 [SWAP SUCCESSFUL] Successfully enrolled into {target_course['name']}!")
            self.currently_held = target_course
            self.send_discord_alert(
                f"🎉🎉 **[수강신청 원자적 교체 성공]** 🎉🎉\n"
                f"👤 **학번**: `{self.std_no}`\n"
                f"✅ **신규 확정**: **{target_course['name']} ({target_course['code']}-{target_course['bun']})**\n"
                f"🗑️ **기존 취소**: **{old['name']}**\n"
                f"⚡ **스왑 소요 시간**: `{t_drop + t_apply:.1f}ms`"
            )
            return True

        else:
            logger.warning(f"⚠️ [APPLY FAILED] Reason: {alert}. Initiating instant rollback...")
            # Step 3: Rollback to original/backup course
            t2 = time.perf_counter()
            rb_success, rb_alert = self.apply_course(self.rollback_course_info)
            t_rb = (time.perf_counter() - t2) * 1000
            logger.info(f"   ↳ Step 3 (Rollback): {t_rb:.1f}ms | Success={rb_success} | Alert='{rb_alert}'")

            if rb_success:
                logger.info(f"🛡️ [ROLLBACK COMPLETE] {self.rollback_course_info['name']} 안전하게 원상복구 완료.")
            else:
                logger.error("🚨 [CRITICAL ALERT] Rollback failed! Manual action required.")
                self.send_discord_alert(
                    f"🚨🚨 **[긴급 수동 확인 요망]** 스왑 및 롤백 실패 경보 발생! 즉시 수강신청 확인/취소 메뉴를 확인해주세요!"
                )
            return False

    def run(self):
        logger.info("=" * 70)
        logger.info("🛡️ Daejin University Credit-Aware Safe Atomic Swapper")
        logger.info(f"   - Drop Target: {self.drop_course_info['name']} ({self.drop_course_info['full_code']})")
        logger.info(f"   - Wanted Targets ({len(self.wanted_courses)}):")
        for i, w in enumerate(self.wanted_courses):
            logger.info(f"     [{i+1}순위] {w['name']} ({w['full_code']})")
        logger.info("=" * 70)

        if not self.login():
            return

        self.sync_actual_held()

        loop = 0
        while True:
            loop += 1
            self.ensure_session()

            for target in self.wanted_courses:
                if target["full_code"] == self.currently_held["full_code"]:
                    continue
                seats = self.check_seat_for_course(target)
                if loop % 25 == 0:
                    logger.info(f"⏳ [감시 #{loop}] {target['name']} 여석: {seats}석 | 현재보유: {self.currently_held['name']}")
                
                if seats > 0:
                    logger.info(f"🔥 [빈자리 발견!] {target['name']} 여석 {seats}석 오픈! 즉각 교체 진행...")
                    swapped = self.perform_atomic_swap(target)
                    if swapped:
                        # If reached first priority, we are done
                        if target == self.wanted_courses[0]:
                            logger.info("🏆 1순위 최우선 과목 교체 완료! 모니터링을 종료합니다.")
                            return
                    time.sleep(1.0)
                    break

            jitter = random.uniform(-0.15, 0.15)
            time.sleep(max(0.6, 1.2 + jitter))


if __name__ == "__main__":
    cfg_file = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    swapper = DaejinAtomicSwapper(cfg_file)
    swapper.run()
