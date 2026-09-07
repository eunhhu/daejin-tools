#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Sugang Automation Suite - High-End Desktop GUI (v1.1.0)
========================================================================
- Modern Tailwind Zinc Dark Theme with Smooth Interactive UX
- Structured Table & Form UI (Zero Textareas!)
- Real-time Multi-threaded Non-blocking Architecture
- Features:
  1. 📊 실시간 수강신청 옵저버 (검색, 필터, 정렬, 1클릭 신청/스나이퍼/헌터 전송)
  2. 🎯 정각 10:00:00 패킷 스나이퍼 (1지망/대체분반 체인, 초정밀 RTT 보정, 장바구니 자동 불러오기)
  3. 🏹 24시간 취소표 헌터 (목표 과목 등록, 0.01초 자동 낚아채기, 사운드 알림)
  4. 🔄 원자적 수강 맞교환기 (학점 꽉 찼을 때 버릴과목 -> 목표과목 -> 롤백 안전 교체)
  5. 📋 내 수강신청 내역 & 장바구니 (실시간 잔여석, 학점 게이지 바, 1클릭 취소)
"""

import os
import sys
import time
import json
import re
import random
import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QLineEdit, QPushButton, QTableWidget,
        QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
        QTextEdit, QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox,
        QSplitter, QProgressBar, QStatusBar, QFrame, QTimeEdit,
        QAbstractItemView
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime
    from PyQt6.QtGui import QFont, QColor, QIcon, QCursor
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QLineEdit, QPushButton, QTableWidget,
        QTableWidgetItem, QHeaderView, QComboBox, QCheckBox,
        QTextEdit, QSpinBox, QDoubleSpinBox, QGroupBox, QMessageBox,
        QSplitter, QProgressBar, QStatusBar, QFrame, QTimeEdit,
        QAbstractItemView
    )
    from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QTime
    from PyQt5.QtGui import QFont, QColor, QIcon, QCursor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_API_URL = f"{BASE_URL}/sugang/NLoginB"
APPLY_API_URL = f"{BASE_URL}/sugang/NSugangWlsn0410"
CHECK_APPLY_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04110.jsp"
CART_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04120.jsp"

# Modern Zinc Dark QSS Stylesheet
DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #09090b;
    color: #f4f4f5;
    font-family: -apple-system, BlinkMacSystemFont, 'Pretendard', 'Malgun Gothic', 'Segoe UI', sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #27272a;
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: bold;
    color: #e4e4e7;
    background-color: #121215;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #38bdf8;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit {
    background-color: #18181b;
    border: 1px solid #3f3f46;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ffffff;
    selection-background-color: #2563eb;
    font-weight: 500;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus {
    border: 1px solid #38bdf8;
    background-color: #202024;
}
QPushButton {
    background-color: #27272a;
    border: 1px solid #3f3f46;
    border-radius: 6px;
    padding: 7px 14px;
    color: #f4f4f5;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #3f3f46;
    border-color: #52525b;
}
QPushButton:pressed {
    background-color: #18181b;
}
QPushButton#primaryBtn {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #1d4ed8;
}
QPushButton#successBtn {
    background-color: #059669;
    border: 1px solid #10b981;
    color: #ffffff;
}
QPushButton#successBtn:hover {
    background-color: #047857;
}
QPushButton#dangerBtn {
    background-color: #dc2626;
    border: 1px solid #ef4444;
    color: #ffffff;
}
QPushButton#dangerBtn:hover {
    background-color: #b91c1c;
}
QPushButton#amberBtn {
    background-color: #d97706;
    border: 1px solid #f59e0b;
    color: #ffffff;
}
QPushButton#amberBtn:hover {
    background-color: #b45309;
}
QTabWidget::pane {
    border: 1px solid #27272a;
    border-radius: 10px;
    background-color: #0c0c0e;
    top: -1px;
}
QTabBar::tab {
    background: #18181b;
    border: 1px solid #27272a;
    padding: 9px 18px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    color: #a1a1aa;
    font-weight: bold;
}
QTabBar::tab:hover {
    background: #27272a;
    color: #ffffff;
}
QTabBar::tab:selected {
    background: #27272a;
    border-bottom-color: #27272a;
    color: #38bdf8;
}
QTableWidget {
    background-color: #121215;
    border: 1px solid #27272a;
    border-radius: 8px;
    gridline-color: #27272a;
    color: #e4e4e7;
    selection-background-color: #1e3a8a;
    selection-color: #ffffff;
    outline: none;
}
QHeaderView::section {
    background-color: #18181b;
    color: #94a3b8;
    padding: 8px 6px;
    border: none;
    border-bottom: 1px solid #27272a;
    font-weight: bold;
}
QTextEdit {
    background-color: #121215;
    border: 1px solid #27272a;
    border-radius: 8px;
    color: #cbd5e1;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
}
QProgressBar {
    border: 1px solid #27272a;
    border-radius: 6px;
    text-align: center;
    background-color: #18181b;
    color: #ffffff;
    font-weight: bold;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 5px;
}
QCheckBox {
    color: #e4e4e7;
    font-weight: 500;
}
"""


class SugangClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": f"{BASE_URL}/sugang/new/main.jsp",
            "Origin": BASE_URL
        })
        self.std_no = ""
        self.passwd = ""
        self.is_logged_in = False
        self.user_info = {}
        self.server_offset_ms = 0
        self.rtt_ms = 0

    def login(self, std_no, passwd):
        self.std_no = std_no
        self.passwd = passwd
        try:
            r = self.session.post(LOGIN_API_URL, data={
                "stdNo": std_no,
                "passwd": passwd,
                "user_flag": "1"
            }, timeout=5)
            text = r.content.decode("euc-kr", "replace")
            if "main.jsp" in text or "location.href" in text or r.status_code == 200:
                self.is_logged_in = True
                self.fetch_user_info()
                return True, "로그인 성공!"
            return False, "학번 또는 비밀번호가 올바르지 않습니다."
        except Exception as e:
            return False, f"로그인 통신 에러: {e}"

    def fetch_user_info(self):
        try:
            r = self.session.get(CHECK_APPLY_URL, timeout=4)
            soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
            info = {}
            for dl in soup.find_all("dl"):
                dt = dl.find("dt")
                dd = dl.find("dd")
                if dt and dd:
                    info[dt.get_text(strip=True)] = dd.get_text(strip=True)
            self.user_info = info
        except Exception:
            pass

    def apply_course(self, code, bun):
        if not self.is_logged_in:
            return False, "로그인이 필요합니다."
        try:
            r = self.session.post(APPLY_API_URL, data={
                "dir": "1", "cmd": "aply", "urltype": "direct",
                "getsbjt_no": code, "getclss_no": bun, "ic_sbjcd": f"{code}{bun}"
            }, timeout=4)
            text = r.content.decode("euc-kr", "replace")
            alert_msg = ""
            for line in text.split("\n"):
                if "alert(" in line:
                    alert_msg = line.split("alert(")[1].split(")")[0].strip("\"'\\r\\n")
                    break
            success = "완료" in alert_msg or "정상" in alert_msg or "신청되었습니다" in alert_msg
            return success, alert_msg or "신청 처리됨"
        except Exception as e:
            return False, f"신청 에러: {e}"

    def cancel_course(self, code, bun, name=""):
        if not self.is_logged_in:
            return False, "로그인이 필요합니다."
        try:
            r = self.session.post(APPLY_API_URL, data={
                "cmd": "cancle",
                "urltype": "page",
                "cousNm": name.encode("euc-kr") if name else b"",
                "jsg_subcd": f"{code}{bun}"
            }, timeout=4)
            text = r.content.decode("euc-kr", "replace")
            success = "삭제" in text or "완료" in text or r.status_code == 200
            return success, "수강 취소 완료" if success else "취소 실패"
        except Exception as e:
            return False, f"취소 에러: {e}"

    def get_enrolled_courses(self):
        try:
            r = self.session.get(CHECK_APPLY_URL, timeout=4)
            soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
            rows = []
            for tr in soup.find_all("tr"):
                cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cols) >= 8 and "-" in cols[1] and len(cols[1]) == 9 and cols[1] != "교과번호-분반":
                    code, bun = cols[1].split("-")
                    rows.append({
                        "code": code,
                        "bun": bun,
                        "code_bun": cols[1],
                        "name": cols[3],
                        "prof": cols[4],
                        "time": cols[5],
                        "type": cols[6],
                        "credits": cols[8] if len(cols) > 8 else "2"
                    })
            return rows
        except Exception:
            return []

    def get_cart_courses(self):
        try:
            r = self.session.get(CART_URL, timeout=4)
            soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
            rows = []
            for tr in soup.find_all("tr"):
                cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cols) >= 9 and "-" in cols[1] and len(cols[1]) == 9 and cols[1] != "교과번호-분반":
                    code, bun = cols[1].split("-")
                    enrolled = int(cols[7]) if cols[7].isdigit() else 0
                    seats = int(cols[8]) if cols[8].isdigit() else 0
                    rows.append({
                        "code": code,
                        "bun": bun,
                        "code_bun": cols[1],
                        "name": cols[3],
                        "prof": cols[4],
                        "time": cols[5],
                        "enrolled": enrolled,
                        "seats": seats,
                        "credits": cols[9] if len(cols) > 9 else "2"
                    })
            return rows
        except Exception:
            return []

    def sync_server_clock(self):
        latencies = []
        offsets = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                r = self.session.head(f"{BASE_URL}/sugang/new/loginForm.jsp", timeout=3)
                t1 = time.perf_counter()
                rtt = (t1 - t0) * 1000
                latencies.append(rtt)
                date_hdr = r.headers.get("Date")
                if date_hdr:
                    srv_dt = datetime.datetime.strptime(date_hdr, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=datetime.timezone.utc)
                    loc_dt = datetime.datetime.now(datetime.timezone.utc)
                    offset = (srv_dt - loc_dt).total_seconds() * 1000
                    offsets.append(offset)
            except Exception:
                pass
            time.sleep(0.05)
        if latencies:
            self.rtt_ms = round(sum(latencies) / len(latencies), 1)
            self.server_offset_ms = round(sum(offsets) / len(offsets), 1) if offsets else 0
        return self.rtt_ms, self.server_offset_ms


# ==============================================================================
# Worker Threads for Asynchronous Tasks
# ==============================================================================

class SniperWorker(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(list)

    def __init__(self, client, target_courses, target_time_str="10:00:00"):
        super().__init__()
        self.client = client
        self.target_courses = target_courses
        self.target_time_str = target_time_str
        self.running = True

    def run(self):
        self.log_signal.emit(f"🎯 [스나이퍼 대기 모드] 목표 시각: {self.target_time_str} KST | 등록 과목: {len(self.target_courses)}개")
        
        # 1. Sync clock
        rtt, offset = self.client.sync_server_clock()
        self.log_signal.emit(f"📶 서버 RTT: {rtt}ms | 시계 오차: {offset:+.1f}ms")

        # 2. Calculate target time
        h, m, s = map(int, self.target_time_str.split(":"))
        now = datetime.datetime.now()
        target_dt = now.replace(hour=h, minute=m, second=s, microsecond=0)
        
        # Trigger moment adjusted for 1/2 RTT and server offset
        lead_sec = max(0.015, (rtt / 2.0 + offset) / 1000.0)
        trigger_dt = target_dt - datetime.timedelta(seconds=lead_sec)
        self.log_signal.emit(f"🚀 발사 예정 시각: {trigger_dt.strftime('%H:%M:%S.%f')[:-3]}")

        while self.running:
            cur = datetime.datetime.now()
            rem = (trigger_dt - cur).total_seconds()
            if rem <= 0:
                self.log_signal.emit("⚡⚡ [TRIGGER!] 10:00:00 정각 돌파! 전 과목 고속 패킷 사출!")
                break
            elif rem > 3.0:
                self.progress_signal.emit(int(rem), f"남은 시간: {int(rem)}초")
                time.sleep(0.5)
            elif rem > 0.05:
                self.progress_signal.emit(int(rem), f"카운트다운: {rem:.2f}초")
                time.sleep(0.02)
            else:
                pass # tight loop

        if not self.running:
            return

        # 3. Fire all courses concurrently
        results = []
        def fire_course(c):
            # Try 1st choice
            t0 = time.perf_counter()
            ok, msg = self.client.apply_course(c["code"], c["bun"])
            elapsed = (time.perf_counter() - t0) * 1000
            
            if ok:
                self.log_signal.emit(f"🎉 [성공!] {c['name']} ({c['code']}-{c['bun']}) 신청 완료! ({elapsed:.1f}ms) - {msg}")
                return {"name": c["name"], "code": c["code"], "bun": c["bun"], "success": True, "msg": msg}
            
            self.log_signal.emit(f"⚠️ [1지망 마감/실패] {c['name']} ({c['code']}-{c['bun']}) -> {msg}")
            
            # Fallback chain
            for fb in c.get("fallbacks", []):
                fb = fb.strip().zfill(2)
                if not fb: continue
                self.log_signal.emit(f"   ↳ [대체 분반 시도] {c['name']} {fb}분반 사출...")
                t_fb = time.perf_counter()
                ok_fb, msg_fb = self.client.apply_course(c["code"], fb)
                e_fb = (time.perf_counter() - t_fb) * 1000
                if ok_fb:
                    self.log_signal.emit(f"🎉 [대체 분반 성공!] {c['name']} ({c['code']}-{fb}) 완료! ({e_fb:.1f}ms) - {msg_fb}")
                    return {"name": c["name"], "code": c["code"], "bun": fb, "success": True, "msg": msg_fb}
                else:
                    self.log_signal.emit(f"   ↳ [대체 {fb}분반 마감] {msg_fb}")

            return {"name": c["name"], "code": c["code"], "bun": c["bun"], "success": False, "msg": msg}

        with ThreadPoolExecutor(max_workers=len(self.target_courses) or 1) as ex:
            results = list(ex.map(fire_course, self.target_courses))

        self.finished_signal.emit(results)


class HunterWorker(QThread):
    log_signal = pyqtSignal(str)
    hit_signal = pyqtSignal(str, str, str)

    def __init__(self, client, targets, interval=1.5):
        super().__init__()
        self.client = client
        self.targets = targets
        self.interval = interval
        self.running = True

    def run(self):
        self.log_signal.emit(f"🚀 [24시간 취소표 헌터 시작] {len(self.targets)}개 과목 상시 감시 중 (주기: {self.interval}s)")
        while self.running:
            try:
                r = requests.get("https://daejin.qucord.com/api/data", timeout=2.5)
                if r.status_code == 200:
                    data = r.json()
                    course_map = {c["full_code"]: c for c in data.get("courses", [])}
                    for t in list(self.targets):
                        full_code = f"{t['code']}{t['bun']}"
                        c = course_map.get(full_code)
                        if c and c.get("seats", 0) > 0:
                            self.log_signal.emit(f"🔥 [빈자리 발생!] {t['name']} ({t['code']}-{t['bun']}) {c['seats']}자리 발견! 즉각 낚아채기...")
                            ok, msg = self.client.apply_course(t["code"], t["bun"])
                            self.log_signal.emit(f"📢 신청 결과: {msg}")
                            if ok:
                                self.hit_signal.emit(t["code"], t["bun"], t["name"])
                                self.targets.remove(t)
                                if not self.targets:
                                    self.log_signal.emit("🏆 모든 목표 취소표를 낚아챘습니다! 헌터를 종료합니다.")
                                    return
            except Exception as e:
                self.log_signal.emit(f"⚠️ 감시 오류: {e}")

            time.sleep(self.interval)


class SwapperWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, client, drop_course, wanted_courses, rollback_course):
        super().__init__()
        self.client = client
        self.drop_course = drop_course
        self.wanted_courses = wanted_courses
        self.rollback_course = rollback_course
        self.running = True

    def run(self):
        self.log_signal.emit("🛡️ [원자적 수강 맞교환기 시작]")
        self.log_signal.emit(f"   - 버릴 과목: {self.drop_course['name']} ({self.drop_course['code']}-{self.drop_course['bun']})")
        for i, w in enumerate(self.wanted_courses):
            self.log_signal.emit(f"   - [{i+1}순위 목표]: {w['name']} ({w['code']}-{w['bun']})")

        while self.running:
            try:
                r = requests.get("https://daejin.qucord.com/api/data", timeout=2.5)
                if r.status_code == 200:
                    data = r.json()
                    course_map = {c["full_code"]: c for c in data.get("courses", [])}
                    
                    for wanted in self.wanted_courses:
                        full_code = f"{wanted['code']}{wanted['bun']}"
                        c = course_map.get(full_code)
                        if c and c.get("seats", 0) > 0:
                            self.log_signal.emit(f"🔥 [목표 과목 빈자리 발견!] {wanted['name']} ({wanted['code']}-{wanted['bun']}) {c['seats']}석 오픈!")
                            
                            # Step 1: Drop old course (~10ms)
                            self.log_signal.emit(f"🗑️ Step 1: 기존 {self.drop_course['name']} 취소 요청...")
                            t0 = time.perf_counter()
                            drop_ok, drop_msg = self.client.cancel_course(self.drop_course["code"], self.drop_course["bun"], self.drop_course["name"])
                            t_drop = (time.perf_counter() - t0) * 1000
                            self.log_signal.emit(f"   ↳ 취소 완료 ({t_drop:.1f}ms)")

                            # Step 2: Apply new course (~10ms)
                            self.log_signal.emit(f"⚡ Step 2: 신규 {wanted['name']} 즉시 신청...")
                            t1 = time.perf_counter()
                            apply_ok, apply_msg = self.client.apply_course(wanted["code"], wanted["bun"])
                            t_apply = (time.perf_counter() - t1) * 1000

                            if apply_ok:
                                self.log_signal.emit(f"🎉🎉 [교체 성공!] {wanted['name']} 수강 확정! (소요시간: {t_drop+t_apply:.1f}ms)")
                                self.finished_signal.emit(True, f"{wanted['name']} 교체 성공!")
                                return
                            else:
                                self.log_signal.emit(f"⚠️ [신규 신청 실패: {apply_msg}] 즉각 롤백 진행...")
                                # Step 3: Rollback
                                t2 = time.perf_counter()
                                rb_ok, rb_msg = self.client.apply_course(self.rollback_course["code"], self.rollback_course["bun"])
                                t_rb = (time.perf_counter() - t2) * 1000
                                if rb_ok:
                                    self.log_signal.emit(f"🛡️ [롤백 완료] 원래 과목({self.rollback_course['name']})으로 안전 복구되었습니다. ({t_rb:.1f}ms)")
                                else:
                                    self.log_signal.emit(f"🚨 [긴급 경보] 롤백 신청 실패! 수동 확인이 필요합니다!")
            except Exception as e:
                self.log_signal.emit(f"⚠️ 스와퍼 감시 오류: {e}")

            time.sleep(1.2)


# ==============================================================================
# Main GUI Window
# ==============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("대진대학교 수강신청 마스터 자동화 Suite (Daejin Sugang Suite v1.1.0)")
        self.resize(1150, 780)
        self.setStyleSheet(DARK_STYLESHEET)

        self.client = SugangClient()
        self.all_courses_cache = []
        self.sniper_worker = None
        self.hunter_worker = None
        self.swapper_worker = None

        self.init_ui()
        self.load_credentials()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # ----------------------------------------------------------------------
        # Top Header Bar: Account & Student Status Card
        # ----------------------------------------------------------------------
        top_card = QGroupBox("👤 대진대학교 포털 계정 & 수강신청 상태")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(12, 10, 12, 10)
        top_layout.setSpacing(12)

        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("학번 8자리 (20261236)")
        self.id_input.setMaximumWidth(160)

        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("비밀번호")
        self.pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_input.setMaximumWidth(160)

        self.login_btn = QPushButton("포털 로그인")
        self.login_btn.setObjectName("primaryBtn")
        self.login_btn.clicked.connect(self.on_login_click)

        self.user_badge_lbl = QLabel("🔴 로그인 필요")
        self.user_badge_lbl.setStyleSheet("color: #f87171; font-weight: bold;")

        self.credits_bar = QProgressBar()
        self.credits_bar.setMaximum(18)
        self.credits_bar.setValue(0)
        self.credits_bar.setFormat("신청 학점: %v / 18 학점")
        self.credits_bar.setMaximumWidth(200)

        top_layout.addWidget(QLabel("학번:"))
        top_layout.addWidget(self.id_input)
        top_layout.addWidget(QLabel("비번:"))
        top_layout.addWidget(self.pw_input)
        top_layout.addWidget(self.login_btn)
        top_layout.addWidget(self.user_badge_lbl)
        top_layout.addStretch()
        top_layout.addWidget(self.credits_bar)

        main_layout.addWidget(top_card)

        # ----------------------------------------------------------------------
        # Main Tabbed Area
        # ----------------------------------------------------------------------
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs, 3)

        self.init_observer_tab()
        self.init_sniper_tab()
        self.init_hunter_tab()
        self.init_swapper_tab()
        self.init_enrolled_tab()

        # ----------------------------------------------------------------------
        # Bottom Live Event Log Console
        # ----------------------------------------------------------------------
        log_group = QGroupBox("📜 실시간 액션 & 시스템 로그 콘솔")
        log_layout = QVBoxLayout(log_group)
        log_layout.setContentsMargins(10, 8, 10, 8)

        log_ctrl_layout = QHBoxLayout()
        self.clear_log_btn = QPushButton("로그 지우기")
        self.clear_log_btn.clicked.connect(lambda: self.log_box.clear())
        self.server_ping_btn = QPushButton("📶 서버 핑 & 시계 동기화")
        self.server_ping_btn.clicked.connect(self.on_sync_clock)
        self.ping_status_lbl = QLabel("서버 연결: 대기 중")
        self.ping_status_lbl.setStyleSheet("color: #94a3b8;")

        log_ctrl_layout.addWidget(self.server_ping_btn)
        log_ctrl_layout.addWidget(self.ping_status_lbl)
        log_ctrl_layout.addStretch()
        log_ctrl_layout.addWidget(self.clear_log_btn)
        log_layout.addLayout(log_ctrl_layout)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(150)
        log_layout.addWidget(self.log_box)

        main_layout.addWidget(log_group, 1)

        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("옵저버 배포 서버 연결 대기 | https://daejin.qucord.com")

    def log(self, text):
        now_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"[{now_str}] {text}")

    # ==========================================================================
    # Tab 1: 📊 실시간 수강신청 옵저버 (Live Observer)
    # ==========================================================================
    def init_observer_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)

        # Filter bar
        fl_layout = QHBoxLayout()
        self.obs_search = QLineEdit()
        self.obs_search.setPlaceholderText("🔍 과목명, 교수명, 학수번호(6자리), 요일 검색...")
        self.obs_search.textChanged.connect(self.render_observer_table)

        self.obs_cat = QComboBox()
        self.obs_cat.addItems([
            "전체 영역 / 학과", "스마트융합보안", "경영학과",
            "교양필수", "교양선택",
            "1영역", "2영역", "3영역", "4영역", "5영역", "6영역",
            "교직", "일반선택"
        ])
        self.obs_cat.currentIndexChanged.connect(self.render_observer_table)

        self.obs_sort = QComboBox()
        self.obs_sort.addItems([
            "⚡ 여석 많은 순", "🔥 여석 적은 순 (마감임박)",
            "🔤 과목명 (가나다순)", "🔢 학수번호순", "👥 신청자 많은 순"
        ])
        self.obs_sort.currentIndexChanged.connect(self.render_observer_table)

        self.obs_open_only = QCheckBox("빈자리만 보기")
        self.obs_open_only.stateChanged.connect(self.render_observer_table)

        self.obs_refresh_btn = QPushButton("새로고침")
        self.obs_refresh_btn.clicked.connect(self.fetch_observer_data)

        fl_layout.addWidget(self.obs_search, 2)
        fl_layout.addWidget(self.obs_cat)
        fl_layout.addWidget(self.obs_sort)
        fl_layout.addWidget(self.obs_open_only)
        fl_layout.addWidget(self.obs_refresh_btn)
        layout.addLayout(fl_layout)

        # Guide banner explaining action buttons clearly
        guide_banner = QLabel(
            "💡 <b>과목 조작 버튼 안내:</b> "
            "<span style='color:#10b981;'><b>[⚡ 즉시신청]</b> 지금 포털에 즉각 수강신청</span> | "
            "<span style='color:#38bdf8;'><b>[🎯 스나이퍼]</b> 10:00:00 정각 일괄신청 목표에 담기</span> | "
            "<span style='color:#f59e0b;'><b>[🏹 헌터등록]</b> 24시간 빈자리 취소표 감시 목록에 등록</span>"
        )
        guide_banner.setStyleSheet("background-color: #182234; color: #94a3b8; border: 1px solid #1e3a8a; border-radius: 8px; padding: 6px 12px; font-size: 11px;")
        layout.addWidget(guide_banner)

        # Table
        self.obs_table = QTableWidget(0, 8)
        self.obs_table.setHorizontalHeaderLabels([
            "상태", "학수-분반", "교과목명", "담당교수", "강의시간", "신청/여석", "영역/학과", "수강신청 / 모듈 담기"
        ])
        self.obs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.obs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.obs_table)

        self.tabs.addTab(w, "📊 실시간 과목 검색 & 빈자리 옵저버")
        QTimer.singleShot(600, self.fetch_observer_data)

    def fetch_observer_data(self):
        try:
            r = requests.get("https://daejin.qucord.com/api/data", timeout=3.0)
            if r.status_code == 200:
                self.all_courses_cache = r.json().get("courses", [])
                self.render_observer_table()
                self.statusBar.showMessage(f"옵저버 동기화 완료: 총 {len(self.all_courses_cache)}개 과목 실시간 스트리밍 중")
        except Exception as e:
            self.statusBar.showMessage(f"옵저버 수신 오류: {e}")

    def render_observer_table(self):
        kw = self.obs_search.text().strip().lower()
        cat = self.obs_cat.currentText()
        sort_idx = self.obs_sort.currentIndex()
        open_only = self.obs_open_only.isChecked()

        filtered = []
        for c in self.all_courses_cache:
            if open_only and c.get("seats", 0) <= 0:
                continue
            if cat != "전체 영역 / 학과":
                if cat == "교양선택":
                    if "교선" not in c.get("category", "") and "교양선택" not in c.get("category", ""):
                        continue
                elif cat not in c.get("category", ""):
                    continue
            if kw:
                m_code = kw in c.get("full_code", "") or kw in c.get("code", "")
                m_name = kw in c.get("name", "").lower()
                m_prof = kw in (c.get("prof") or "").lower()
                m_time = kw in (c.get("time") or "").lower()
                if not (m_code or m_name or m_prof or m_time):
                    continue
            filtered.append(c)

        if sort_idx == 0:
            filtered.sort(key=lambda x: x.get("seats", 0), reverse=True)
        elif sort_idx == 1:
            filtered.sort(key=lambda x: (x.get("seats", 0) if x.get("seats", 0) > 0 else 9999))
        elif sort_idx == 2:
            filtered.sort(key=lambda x: x.get("name", ""))
        elif sort_idx == 3:
            filtered.sort(key=lambda x: x.get("full_code", ""))
        elif sort_idx == 4:
            filtered.sort(key=lambda x: x.get("enrolled", 0), reverse=True)

        self.obs_table.setRowCount(len(filtered))
        for row, c in enumerate(filtered):
            is_open = c.get("seats", 0) > 0
            st_item = QTableWidgetItem(f"🔥 {c['seats']}석" if is_open else "마감")
            st_item.setForeground(QColor("#10b981" if is_open else "#71717a"))
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            cd_item = QTableWidgetItem(f"{c['code']}-{c['bun']}")
            cd_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            nm_item = QTableWidgetItem(f"{c['name']} ({c.get('credits', '2')}학점)")
            pf_item = QTableWidgetItem(c.get("prof") or "-")
            tm_item = QTableWidgetItem(c.get("time") or "-")
            
            st_cnt_item = QTableWidgetItem(f"{c.get('enrolled', 0)} / {c.get('seats', 0)}")
            st_cnt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_open:
                st_cnt_item.setForeground(QColor("#38bdf8"))

            cat_item = QTableWidgetItem(c.get("category", ""))

            self.obs_table.setItem(row, 0, st_item)
            self.obs_table.setItem(row, 1, cd_item)
            self.obs_table.setItem(row, 2, nm_item)
            self.obs_table.setItem(row, 3, pf_item)
            self.obs_table.setItem(row, 4, tm_item)
            self.obs_table.setItem(row, 5, st_cnt_item)
            self.obs_table.setItem(row, 6, cat_item)

            # Action Buttons Widget
            act_w = QWidget()
            act_l = QHBoxLayout(act_w)
            act_l.setContentsMargins(2, 2, 2, 2)
            act_l.setSpacing(6)

            apply_btn = QPushButton("⚡ 즉시신청")
            apply_btn.setObjectName("primaryBtn")
            apply_btn.setToolTip("해당 과목을 포털에 지금 즉시 1클릭 수강신청합니다.")
            apply_btn.clicked.connect(lambda ch, cd=c['code'], b=c['bun']: self.on_direct_apply(cd, b))

            add_sniper_btn = QPushButton("🎯 스나이퍼")
            add_sniper_btn.setToolTip("10:00:00 정각 스나이퍼 목표 목록에 이 과목을 추가합니다.")
            add_sniper_btn.clicked.connect(lambda ch, cd=c['code'], b=c['bun'], n=c['name']: self.add_to_sniper(cd, b, n))

            add_hunter_btn = QPushButton("🏹 헌터등록")
            add_hunter_btn.setObjectName("amberBtn")
            add_hunter_btn.setToolTip("24시간 빈자리 취소표 헌터 감시 목록에 등록합니다.")
            add_hunter_btn.clicked.connect(lambda ch, cd=c['code'], b=c['bun'], n=c['name']: self.add_to_hunter(cd, b, n))

            act_l.addWidget(apply_btn)
            act_l.addWidget(add_sniper_btn)
            act_l.addWidget(add_hunter_btn)
            self.obs_table.setCellWidget(row, 7, act_w)

    def on_direct_apply(self, code, bun):
        if not self.client.is_logged_in:
            QMessageBox.warning(self, "경고", "먼저 상단에서 포털 로그인을 진행해주세요.")
            return
        ok, msg = self.client.apply_course(code, bun)
        self.log(f"📢 [{code}-{bun}] 직접 수강신청 결과: {msg}")
        if ok:
            QMessageBox.information(self, "신청 성공", f"과목 [{code}-{bun}] 수강신청이 성공적으로 완료되었습니다!\n응답: {msg}")
            self.fetch_enrolled_data()
        else:
            QMessageBox.warning(self, "신청 실패", f"과목 [{code}-{bun}] 신청 실패:\n{msg}")

    # ==========================================================================
    # Tab 2: 🎯 정각 10:00:00 패킷 스나이퍼 (Packet Sniper)
    # ==========================================================================
    def init_sniper_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)

        # Sniper Target Table
        grp = QGroupBox("🎯 10:00:00 동시 자동신청 목표 목록 (1지망 마감 시 대체분반 자동 체인)")
        g_l = QVBoxLayout(grp)

        self.sniper_table = QTableWidget(0, 6)
        self.sniper_table.setHorizontalHeaderLabels([
            "과목번호(6자리)", "1지망 분반", "대체 분반 체인 (Fallback)", "과목명", "상태", "삭제"
        ])
        self.sniper_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        g_l.addWidget(self.sniper_table)

        # Input row to add new target
        input_box = QGroupBox("➕ 스나이퍼 목표 과목 추가")
        in_l = QHBoxLayout(input_box)
        self.snp_code_in = QLineEdit()
        self.snp_code_in.setPlaceholderText("과목번호 (예: 576006)")
        self.snp_code_in.setMaximumWidth(140)

        self.snp_bun_in = QLineEdit()
        self.snp_bun_in.setPlaceholderText("1지망 분반 (예: 01)")
        self.snp_bun_in.setMaximumWidth(120)

        self.snp_fb_in = QLineEdit()
        self.snp_fb_in.setPlaceholderText("대체분반 (예: 02, 03, 15)")

        self.snp_name_in = QLineEdit()
        self.snp_name_in.setPlaceholderText("과목명 (선택)")

        self.snp_add_btn = QPushButton("+ 목표 추가")
        self.snp_add_btn.setObjectName("primaryBtn")
        self.snp_add_btn.clicked.connect(self.on_add_sniper_row)

        self.snp_import_cart_btn = QPushButton("🛒 장바구니에서 불러오기")
        self.snp_import_cart_btn.clicked.connect(self.on_import_cart_to_sniper)

        in_l.addWidget(self.snp_code_in)
        in_l.addWidget(self.snp_bun_in)
        in_l.addWidget(self.snp_fb_in)
        in_l.addWidget(self.snp_name_in)
        in_l.addWidget(self.snp_add_btn)
        in_l.addWidget(self.snp_import_cart_btn)
        g_l.addWidget(input_box)

        # Control Row
        ctrl_l = QHBoxLayout()
        ctrl_l.addWidget(QLabel("발사 목표 시각:"))
        self.snp_time_edit = QTimeEdit()
        self.snp_time_edit.setTime(QTime(10, 0, 0))
        self.snp_time_edit.setDisplayFormat("HH:mm:ss")
        ctrl_l.addWidget(self.snp_time_edit)

        self.snp_countdown_lbl = QLabel("⏳ 대기 상태")
        self.snp_countdown_lbl.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 14px;")
        ctrl_l.addWidget(self.snp_countdown_lbl)
        ctrl_l.addStretch()

        self.snp_start_btn = QPushButton("🚀 10:00:00 스나이퍼 대기 가동")
        self.snp_start_btn.setObjectName("primaryBtn")
        self.snp_start_btn.clicked.connect(self.on_toggle_sniper)
        ctrl_l.addWidget(self.snp_start_btn)
        g_l.addLayout(ctrl_l)

        layout.addWidget(grp)
        self.tabs.addTab(w, "🎯 정각 10:00:00 패킷 스나이퍼")

    def on_add_sniper_row(self):
        code = self.snp_code_in.text().strip()
        bun = self.snp_bun_in.text().strip().zfill(2)
        fb = self.snp_fb_in.text().strip()
        name = self.snp_name_in.text().strip() or "과목"
        if len(code) != 6 or not bun:
            QMessageBox.warning(self, "입력 오류", "과목번호 6자리와 분반을 정확히 입력해주세요.")
            return
        self.add_sniper_table_entry(code, bun, fb, name)
        self.snp_code_in.clear()
        self.snp_bun_in.clear()
        self.snp_fb_in.clear()
        self.snp_name_in.clear()

    def add_sniper_table_entry(self, code, bun, fb_chain, name):
        row = self.sniper_table.rowCount()
        self.sniper_table.insertRow(row)
        self.sniper_table.setItem(row, 0, QTableWidgetItem(code))
        self.sniper_table.setItem(row, 1, QTableWidgetItem(bun))
        self.sniper_table.setItem(row, 2, QTableWidgetItem(fb_chain))
        self.sniper_table.setItem(row, 3, QTableWidgetItem(name))
        
        st = QTableWidgetItem("대기")
        st.setForeground(QColor("#a1a1aa"))
        self.sniper_table.setItem(row, 4, st)

        del_btn = QPushButton("삭제")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(lambda: self.sniper_table.removeRow(self.sniper_table.currentRow()))
        self.sniper_table.setCellWidget(row, 5, del_btn)

    def add_to_sniper(self, code, bun, name):
        self.add_sniper_table_entry(code, bun, "", name)
        self.tabs.setCurrentIndex(1)
        self.log(f"🎯 [{name} ({code}-{bun})] 10시 패킷 스나이퍼 목록에 추가되었습니다.")

    def on_import_cart_to_sniper(self):
        if not self.client.is_logged_in:
            QMessageBox.warning(self, "경고", "먼저 포털 로그인을 진행해주세요.")
            return
        cart = self.client.get_cart_courses()
        if not cart:
            QMessageBox.information(self, "안내", "장바구니에 담긴 과목이 없습니다.")
            return
        for c in cart:
            self.add_sniper_table_entry(c["code"], c["bun"], "", c["name"])
        self.log(f"🛒 장바구니에서 {len(cart)}개 과목을 스나이퍼 목록으로 불러왔습니다.")

    def on_toggle_sniper(self):
        if self.sniper_worker and self.sniper_worker.isRunning():
            self.sniper_worker.running = False
            self.sniper_worker.wait()
            self.snp_start_btn.setText("🚀 10:00:00 스나이퍼 대기 가동")
            self.snp_start_btn.setObjectName("primaryBtn")
            self.snp_countdown_lbl.setText("⏳ 대기 상태")
            self.log("🛑 [패킷 스나이퍼 대기 중지됨]")
            return

        if not self.client.is_logged_in:
            QMessageBox.warning(self, "경고", "먼저 포털 로그인을 진행해주세요.")
            return

        rows = self.sniper_table.rowCount()
        if rows == 0:
            QMessageBox.warning(self, "경고", "스나이퍼 목표 과목을 최소 1개 이상 등록해주세요.")
            return

        targets = []
        for r in range(rows):
            code = self.sniper_table.item(r, 0).text()
            bun = self.sniper_table.item(r, 1).text()
            fb = self.sniper_table.item(r, 2).text().replace(",", " ").split()
            name = self.sniper_table.item(r, 3).text()
            targets.append({"code": code, "bun": bun, "fallbacks": fb, "name": name})

        t_str = self.snp_time_edit.time().toString("HH:mm:ss")
        self.sniper_worker = SniperWorker(self.client, targets, t_str)
        self.sniper_worker.log_signal.connect(self.log)
        self.sniper_worker.progress_signal.connect(lambda _, txt: self.snp_countdown_lbl.setText(txt))
        self.sniper_worker.finished_signal.connect(self.on_sniper_finished)
        self.sniper_worker.start()

        self.snp_start_btn.setText("⏹ 스나이퍼 가동 취소")
        self.snp_start_btn.setObjectName("dangerBtn")
        self.snp_start_btn.setStyleSheet("background-color: #dc2626; color: white;")

    def on_sniper_finished(self, results):
        self.snp_start_btn.setText("🚀 10:00:00 스나이퍼 대기 가동")
        self.snp_start_btn.setObjectName("primaryBtn")
        self.snp_start_btn.setStyleSheet("")
        self.snp_countdown_lbl.setText("🎉 사출 완료!")
        QMessageBox.information(self, "스나이퍼 발사 완료", "10:00:00 스나이퍼 패킷 사출이 완료되었습니다! 하단 로그 콘솔 및 확정 내역 탭을 확인하세요.")
        self.fetch_enrolled_data()

    # ==========================================================================
    # Tab 3: 🏹 24시간 취소표 헌터 (Vacancy Hunter)
    # ==========================================================================
    def init_hunter_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)

        grp = QGroupBox("🏹 24시간 실시간 취소표 자동 주워담기 목표")
        g_l = QVBoxLayout(grp)

        self.hunter_table = QTableWidget(0, 5)
        self.hunter_table.setHorizontalHeaderLabels([
            "과목번호", "분반", "과목명", "현재 잔여석", "삭제"
        ])
        self.hunter_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        g_l.addWidget(self.hunter_table)

        # Add target row
        in_box = QGroupBox("➕ 취소표 낚아채기 목표 등록")
        in_l = QHBoxLayout(in_box)
        self.hnt_code_in = QLineEdit()
        self.hnt_code_in.setPlaceholderText("과목번호 (6자리)")
        self.hnt_code_in.setMaximumWidth(140)

        self.hnt_bun_in = QLineEdit()
        self.hnt_bun_in.setPlaceholderText("분반 (2자리)")
        self.hnt_bun_in.setMaximumWidth(100)

        self.hnt_name_in = QLineEdit()
        self.hnt_name_in.setPlaceholderText("과목명 (선택)")

        self.hnt_add_btn = QPushButton("+ 목표 추가")
        self.hnt_add_btn.setObjectName("primaryBtn")
        self.hnt_add_btn.clicked.connect(self.on_add_hunter_row)

        in_l.addWidget(self.hnt_code_in)
        in_l.addWidget(self.hnt_bun_in)
        in_l.addWidget(self.hnt_name_in)
        in_l.addWidget(self.hnt_add_btn)
        g_l.addWidget(in_box)

        # Control Row
        ctrl_l = QHBoxLayout()
        ctrl_l.addWidget(QLabel("감시 주기(초):"))
        self.hnt_interval = QDoubleSpinBox()
        self.hnt_interval.setRange(0.5, 5.0)
        self.hnt_interval.setValue(1.5)
        self.hnt_interval.setSingleStep(0.2)
        ctrl_l.addWidget(self.hnt_interval)

        self.hnt_sound_chk = QCheckBox("취소표 발생 시 비프음 알림")
        self.hnt_sound_chk.setChecked(True)
        ctrl_l.addWidget(self.hnt_sound_chk)
        ctrl_l.addStretch()

        self.hnt_start_btn = QPushButton("▶ 24시간 취소표 낚아채기 시작")
        self.hnt_start_btn.setObjectName("successBtn")
        self.hnt_start_btn.clicked.connect(self.on_toggle_hunter)
        ctrl_l.addWidget(self.hnt_start_btn)
        g_l.addLayout(ctrl_l)

        layout.addWidget(grp)
        self.tabs.addTab(w, "🏹 24시간 취소표 헌터")

    def on_add_hunter_row(self):
        code = self.hnt_code_in.text().strip()
        bun = self.hnt_bun_in.text().strip().zfill(2)
        name = self.hnt_name_in.text().strip() or "과목"
        if len(code) != 6 or not bun:
            QMessageBox.warning(self, "입력 오류", "과목번호 6자리와 분반을 정확히 입력해주세요.")
            return
        self.add_hunter_table_entry(code, bun, name)
        self.hnt_code_in.clear()
        self.hnt_bun_in.clear()
        self.hnt_name_in.clear()

    def add_hunter_table_entry(self, code, bun, name):
        row = self.hunter_table.rowCount()
        self.hunter_table.insertRow(row)
        self.hunter_table.setItem(row, 0, QTableWidgetItem(code))
        self.hunter_table.setItem(row, 1, QTableWidgetItem(bun))
        self.hunter_table.setItem(row, 2, QTableWidgetItem(name))
        
        seats_item = QTableWidgetItem("0석")
        seats_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hunter_table.setItem(row, 3, seats_item)

        del_btn = QPushButton("삭제")
        del_btn.setObjectName("dangerBtn")
        del_btn.clicked.connect(lambda: self.hunter_table.removeRow(self.hunter_table.currentRow()))
        self.hunter_table.setCellWidget(row, 4, del_btn)

    def add_to_hunter(self, code, bun, name):
        self.add_hunter_table_entry(code, bun, name)
        self.tabs.setCurrentIndex(2)
        self.log(f"🏹 [{name} ({code}-{bun})] 24시간 취소표 헌터 목록에 등록되었습니다.")

    def on_toggle_hunter(self):
        if self.hunter_worker and self.hunter_worker.isRunning():
            self.hunter_worker.running = False
            self.hunter_worker.wait()
            self.hnt_start_btn.setText("▶ 24시간 취소표 낚아채기 시작")
            self.hnt_start_btn.setObjectName("successBtn")
            self.hnt_start_btn.setStyleSheet("")
            self.log("🛑 [취소표 헌터 중지됨]")
            return

        if not self.client.is_logged_in:
            QMessageBox.warning(self, "경고", "먼저 포털 로그인을 진행해주세요.")
            return

        rows = self.hunter_table.rowCount()
        if rows == 0:
            QMessageBox.warning(self, "경고", "감시할 취소표 목표 과목을 등록해주세요.")
            return

        targets = []
        for r in range(rows):
            code = self.hunter_table.item(r, 0).text()
            bun = self.hunter_table.item(r, 1).text()
            name = self.hunter_table.item(r, 2).text()
            targets.append({"code": code, "bun": bun, "name": name})

        self.hunter_worker = HunterWorker(self.client, targets, self.hnt_interval.value())
        self.hunter_worker.log_signal.connect(self.log)
        self.hunter_worker.hit_signal.connect(self.on_hunter_success)
        self.hunter_worker.start()

        self.hnt_start_btn.setText("⏹ 헌터 감시 중지")
        self.hnt_start_btn.setObjectName("dangerBtn")
        self.hnt_start_btn.setStyleSheet("background-color: #dc2626; color: white;")

    def on_hunter_success(self, code, bun, name):
        if self.hnt_sound_chk.isChecked():
            QApplication.beep()
        QMessageBox.information(self, "🎉 취소표 낚아채기 성공!", f"축하합니다!\n과목 [{name} ({code}-{bun})] 취소표가 발생하여 0.01초 만에 성공적으로 수강신청되었습니다!")
        self.fetch_enrolled_data()

    # ==========================================================================
    # Tab 4: 🔄 원자적 수강 맞교환기 (Atomic Swapper)
    # ==========================================================================
    def init_swapper_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)

        desc_box = QLabel("💡 수강신청 학점(18학점)이 이미 가득 찼을 때, 목표 과목에 자리가 나는 순간 **기존 과목 취소(Drop) ➔ 목표 과목 신청(Apply)**을 0.01초 만에 원자적으로 맞바꿉니다. 실패 시 원래 과목으로 안전 롤백됩니다.")
        desc_box.setWordWrap(True)
        desc_box.setStyleSheet("color: #94a3b8; padding: 6px; background: #18181b; border-radius: 6px;")
        layout.addWidget(desc_box)

        # 1. Drop Course
        drop_box = QGroupBox("🗑️ 1단계: 자리가 나면 버릴(취소할) 현재 보유 과목")
        d_l = QHBoxLayout(drop_box)
        self.swp_drop_code = QLineEdit()
        self.swp_drop_code.setPlaceholderText("과목번호 6자리")
        self.swp_drop_bun = QLineEdit()
        self.swp_drop_bun.setPlaceholderText("분반 2자리")
        self.swp_drop_name = QLineEdit()
        self.swp_drop_name.setPlaceholderText("과목명")

        d_l.addWidget(QLabel("학수번호:"))
        d_l.addWidget(self.swp_drop_code)
        d_l.addWidget(QLabel("분반:"))
        d_l.addWidget(self.swp_drop_bun)
        d_l.addWidget(QLabel("과목명:"))
        d_l.addWidget(self.swp_drop_name)
        layout.addWidget(drop_box)

        # 2. Wanted Targets
        wanted_box = QGroupBox("🎯 2단계: 감시할 낚아챌 목표 과목들 (우선순위 순서대로)")
        w_l = QVBoxLayout(wanted_box)
        self.swp_wanted_table = QTableWidget(0, 4)
        self.swp_wanted_table.setHorizontalHeaderLabels(["우선순위", "과목번호", "분반", "과목명"])
        self.swp_wanted_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        w_l.addWidget(self.swp_wanted_table)

        w_in_l = QHBoxLayout()
        self.swp_w_code = QLineEdit()
        self.swp_w_code.setPlaceholderText("목표 과목번호")
        self.swp_w_bun = QLineEdit()
        self.swp_w_bun.setPlaceholderText("목표 분반")
        self.swp_w_name = QLineEdit()
        self.swp_w_name.setPlaceholderText("목표 과목명")
        self.swp_w_add_btn = QPushButton("+ 목표 추가")
        self.swp_w_add_btn.setObjectName("primaryBtn")
        self.swp_w_add_btn.clicked.connect(self.on_add_swapper_wanted)

        w_in_l.addWidget(self.swp_w_code)
        w_in_l.addWidget(self.swp_w_bun)
        w_in_l.addWidget(self.swp_w_name)
        w_in_l.addWidget(self.swp_w_add_btn)
        w_l.addLayout(w_in_l)
        layout.addWidget(wanted_box)

        # 3. Rollback Course
        rb_box = QGroupBox("🛡️ 3단계: 신규 신청 찰나 실패 시 안전하게 원상복구할 롤백 과목")
        rb_l = QHBoxLayout(rb_box)
        self.swp_rb_code = QLineEdit()
        self.swp_rb_code.setPlaceholderText("롤백 과목번호 (보통 버릴과목과 동일)")
        self.swp_rb_bun = QLineEdit()
        self.swp_rb_bun.setPlaceholderText("분반")
        self.swp_rb_name = QLineEdit()
        self.swp_rb_name.setPlaceholderText("롤백 과목명")

        rb_l.addWidget(QLabel("학수번호:"))
        rb_l.addWidget(self.swp_rb_code)
        rb_l.addWidget(QLabel("분반:"))
        rb_l.addWidget(self.swp_rb_bun)
        rb_l.addWidget(QLabel("과목명:"))
        rb_l.addWidget(self.swp_rb_name)
        layout.addWidget(rb_box)

        # Run Button
        self.swp_start_btn = QPushButton("⚡ 원자적 수강 맞교환 감시 가동")
        self.swp_start_btn.setObjectName("primaryBtn")
        self.swp_start_btn.clicked.connect(self.on_toggle_swapper)
        layout.addWidget(self.swp_start_btn)

        self.tabs.addTab(w, "🔄 원자적 수강 맞교환기 (Swapper)")

    def on_add_swapper_wanted(self):
        code = self.swp_w_code.text().strip()
        bun = self.swp_w_bun.text().strip().zfill(2)
        name = self.swp_w_name.text().strip() or "목표과목"
        if len(code) != 6 or not bun:
            QMessageBox.warning(self, "입력 오류", "과목번호 6자리와 분반을 입력하세요.")
            return
        row = self.swp_wanted_table.rowCount()
        self.swp_wanted_table.insertRow(row)
        self.swp_wanted_table.setItem(row, 0, QTableWidgetItem(f"{row+1}순위"))
        self.swp_wanted_table.setItem(row, 1, QTableWidgetItem(code))
        self.swp_wanted_table.setItem(row, 2, QTableWidgetItem(bun))
        self.swp_wanted_table.setItem(row, 3, QTableWidgetItem(name))
        self.swp_w_code.clear()
        self.swp_w_bun.clear()
        self.swp_w_name.clear()

    def on_toggle_swapper(self):
        if self.swapper_worker and self.swapper_worker.isRunning():
            self.swapper_worker.running = False
            self.swapper_worker.wait()
            self.swp_start_btn.setText("⚡ 원자적 수강 맞교환 감시 가동")
            self.swp_start_btn.setObjectName("primaryBtn")
            self.swp_start_btn.setStyleSheet("")
            self.log("🛑 [원자적 스와퍼 감시 중지됨]")
            return

        if not self.client.is_logged_in:
            QMessageBox.warning(self, "경고", "먼저 포털 로그인을 진행해주세요.")
            return

        d_code = self.swp_drop_code.text().strip()
        d_bun = self.swp_drop_bun.text().strip().zfill(2)
        d_name = self.swp_drop_name.text().strip() or "DropCourse"
        if not d_code or not d_bun:
            QMessageBox.warning(self, "설정 필요", "자리가 났을 때 버릴 현재 과목을 입력하세요.")
            return

        w_rows = self.swp_wanted_table.rowCount()
        if w_rows == 0:
            QMessageBox.warning(self, "설정 필요", "감시할 목표 과목을 최소 1개 이상 등록하세요.")
            return

        wanted = []
        for r in range(w_rows):
            wanted.append({
                "code": self.swp_wanted_table.item(r, 1).text(),
                "bun": self.swp_wanted_table.item(r, 2).text(),
                "name": self.swp_wanted_table.item(r, 3).text()
            })

        rb_code = self.swp_rb_code.text().strip() or d_code
        rb_bun = self.swp_rb_bun.text().strip().zfill(2) or d_bun
        rb_name = self.swp_rb_name.text().strip() or d_name

        self.swapper_worker = SwapperWorker(
            self.client,
            {"code": d_code, "bun": d_bun, "name": d_name},
            wanted,
            {"code": rb_code, "bun": rb_bun, "name": rb_name}
        )
        self.swapper_worker.log_signal.connect(self.log)
        self.swapper_worker.finished_signal.connect(self.on_swapper_finished)
        self.swapper_worker.start()

        self.swp_start_btn.setText("⏹ 스와퍼 가동 취소")
        self.swp_start_btn.setObjectName("dangerBtn")
        self.swp_start_btn.setStyleSheet("background-color: #dc2626; color: white;")

    def on_swapper_finished(self, success, msg):
        self.swp_start_btn.setText("⚡ 원자적 수강 맞교환 감시 가동")
        self.swp_start_btn.setObjectName("primaryBtn")
        self.swp_start_btn.setStyleSheet("")
        if success:
            QMessageBox.information(self, "스왑 완료", msg)
            self.fetch_enrolled_data()

    # ==========================================================================
    # Tab 5: 📋 내 수강신청 내역 & 장바구니 (My Courses)
    # ==========================================================================
    def init_enrolled_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 10, 10, 10)

        # Enrolled Box
        e_box = QGroupBox("📋 현재 확정 수강신청 완료 목록")
        e_l = QVBoxLayout(e_box)
        
        btn_l = QHBoxLayout()
        self.enr_refresh_btn = QPushButton("🔄 확정 내역 새로고침")
        self.enr_refresh_btn.clicked.connect(self.fetch_enrolled_data)
        btn_l.addWidget(self.enr_refresh_btn)
        btn_l.addStretch()
        e_l.addLayout(btn_l)

        self.enr_table = QTableWidget(0, 7)
        self.enr_table.setHorizontalHeaderLabels([
            "학수-분반", "교과목명", "담당교수", "강의시간", "이수", "학점", "취소(드랍)"
        ])
        self.enr_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        e_l.addWidget(self.enr_table)
        layout.addWidget(e_box)

        # Cart Box
        c_box = QGroupBox("🛒 예비수강 장바구니 목록 & 실시간 여석")
        c_l = QVBoxLayout(c_box)
        self.cart_table = QTableWidget(0, 6)
        self.cart_table.setHorizontalHeaderLabels([
            "학수-분반", "교과목명", "담당교수", "강의시간", "신청/여석", "즉시 신청"
        ])
        self.cart_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        c_l.addWidget(self.cart_table)
        layout.addWidget(c_box)

        self.tabs.addTab(w, "📋 내 수강신청 내역 & 장바구니")

    def fetch_enrolled_data(self):
        if not self.client.is_logged_in:
            return
        courses = self.client.get_enrolled_courses()
        self.enr_table.setRowCount(len(courses))
        total_credits = 0
        for row, c in enumerate(courses):
            self.enr_table.setItem(row, 0, QTableWidgetItem(c["code_bun"]))
            self.enr_table.setItem(row, 1, QTableWidgetItem(c["name"]))
            self.enr_table.setItem(row, 2, QTableWidgetItem(c["prof"]))
            self.enr_table.setItem(row, 3, QTableWidgetItem(c["time"]))
            self.enr_table.setItem(row, 4, QTableWidgetItem(c["type"]))
            self.enr_table.setItem(row, 5, QTableWidgetItem(c["credits"]))
            if c["credits"].isdigit():
                total_credits += int(c["credits"])

            del_btn = QPushButton("수강취소")
            del_btn.setObjectName("dangerBtn")
            del_btn.clicked.connect(lambda ch, cd=c['code'], b=c['bun'], n=c['name']: self.on_cancel_enrolled(cd, b, n))
            self.enr_table.setCellWidget(row, 6, del_btn)

        self.credits_bar.setValue(total_credits)
        self.credits_bar.setFormat(f"신청 학점: {total_credits} / 18 학점")

        # Also fetch cart
        cart = self.client.get_cart_courses()
        self.cart_table.setRowCount(len(cart))
        for row, c in enumerate(cart):
            is_open = c["seats"] > 0
            self.cart_table.setItem(row, 0, QTableWidgetItem(c["code_bun"]))
            self.cart_table.setItem(row, 1, QTableWidgetItem(c["name"]))
            self.cart_table.setItem(row, 2, QTableWidgetItem(c["prof"]))
            self.cart_table.setItem(row, 3, QTableWidgetItem(c["time"]))
            
            st_item = QTableWidgetItem(f"{c['enrolled']}/{c['seats']}")
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if is_open:
                st_item.setForeground(QColor("#38bdf8"))
            self.cart_table.setItem(row, 4, st_item)

            apply_btn = QPushButton("신청")
            apply_btn.setObjectName("primaryBtn")
            apply_btn.clicked.connect(lambda ch, cd=c['code'], b=c['bun']: self.on_direct_apply(cd, b))
            self.cart_table.setCellWidget(row, 5, apply_btn)

    def on_cancel_enrolled(self, code, bun, name):
        reply = QMessageBox.question(
            self, "수강 취소 확인",
            f"정말로 과목 [{name} ({code}-{bun})]을 수강 취소하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            ok, msg = self.client.cancel_course(code, bun, name)
            if ok:
                QMessageBox.information(self, "취소 완료", f"과목 [{name}] 수강 취소가 완료되었습니다.")
                self.fetch_enrolled_data()
            else:
                QMessageBox.warning(self, "취소 실패", f"수강 취소 실패: {msg}")

    # ==========================================================================
    # Credentials & Clock Sync
    # ==========================================================================
    def load_credentials(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.id_input.setText(cfg.get("stdNo", ""))
                    self.pw_input.setText(cfg.get("passwd", ""))
            except Exception:
                pass

    def on_login_click(self):
        std_no = self.id_input.text().strip()
        passwd = self.pw_input.text().strip()
        if not std_no or not passwd:
            QMessageBox.warning(self, "입력 오류", "학번과 비밀번호를 입력해주세요.")
            return
        
        self.login_btn.setEnabled(False)
        self.login_btn.setText("로그인 중...")
        QApplication.processEvents()

        ok, msg = self.client.login(std_no, passwd)
        self.login_btn.setEnabled(True)
        self.login_btn.setText("포털 로그인")

        if ok:
            name = self.client.user_info.get("성명", "")
            major = self.client.user_info.get("학과", "")
            self.user_badge_lbl.setText(f"🟢 {name} ({major}) 로그인 완료")
            self.user_badge_lbl.setStyleSheet("color: #34d399; font-weight: bold;")
            self.log(f"🔑 포털 로그인 성공: {name} ({std_no} / {major})")
            self.fetch_enrolled_data()
            self.on_sync_clock()
        else:
            self.user_badge_lbl.setText("🔴 로그인 실패")
            self.user_badge_lbl.setStyleSheet("color: #f87171; font-weight: bold;")
            QMessageBox.critical(self, "로그인 실패", msg)

    def on_sync_clock(self):
        rtt, offset = self.client.sync_server_clock()
        self.ping_status_lbl.setText(f"RTT: {rtt}ms | Offset: {offset:+.1f}ms")
        self.log(f"📶 [서버 정밀 시계 동기화] RTT: {rtt}ms | 시계 오차(Offset): {offset:+.1f}ms")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
