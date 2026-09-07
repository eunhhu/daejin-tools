#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Real-time Course Vacancy Observer (High-Performance SSE & Web Push Suite)
===========================================================================================
- Backwards compatible with legacy polling (/api/data)
- High-concurrency Server-Sent Events (SSE) streaming (/api/stream)
- Course Watchlist / Star Subscription System (⭐ 구독 과목만 알림)
- Native Browser Web Push Notification API
- Zero-Downtime State Persistence & Hot-Reload (targets.json)
"""

import os
import sys
import time
import json
import re
import logging
import asyncio
import datetime
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Set, List, Dict

import requests
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
import uvicorn
from push_manager import push_mgr

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DaejinObserver")

KST = datetime.timezone(datetime.timedelta(hours=9))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
TARGETS_PATH = os.path.join(BASE_DIR, "targets.json")
CACHE_PATH = os.path.join(BASE_DIR, "db_cache.json")

BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_API_URL = f"{BASE_URL}/sugang/NLoginB"
SCRAPE_LOOP_INTERVAL_SECONDS = 10.0
SCRAPE_MAX_WORKERS = 4
LOGIN_RETRY_BASE_SECONDS = 1800
LOGIN_RETRY_MAX_SECONDS = 3600

# Global In-Memory State
course_db: Dict[str, dict] = {}
event_history: List[dict] = []
stats = {
    "total_courses": 0,
    "open_courses": 0,
    "events_count": 0,
    "last_scraped_at": "-",
    "scrape_latency_ms": 0,
    "status": "Initializing"
}
cached_json_response = b'{"stats":{},"events":[],"courses":[]}'
subscribers: Set[asyncio.Queue] = set()
crawler_running = True


def load_state_cache():
    global course_db, event_history, stats, cached_json_response
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                course_db = data.get("courses", {})
                event_history = data.get("events", [])
                stats = data.get("stats", stats)
                open_cnt = sum(1 for c in course_db.values() if c.get("seats", 0) > 0)
                stats["total_courses"] = len(course_db)
                stats["open_courses"] = open_cnt
                stats["status"] = "Live Streaming"
                cached_json_response = json.dumps({
                    "stats": stats,
                    "events": event_history[:20],
                    "courses": list(course_db.values())
                }, ensure_ascii=False).encode("utf-8")
                logger.info(f"💾 Restored state cache: {len(course_db)} courses ({open_cnt} open).")
        except Exception as e:
            logger.warning(f"Failed to load state cache: {e}")


def save_state_cache():
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "courses": course_db,
                "events": event_history[:50],
                "stats": stats
            }, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"Failed to save state cache: {e}")


load_state_cache()


class CourseCrawler:
    def __init__(self):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self.config = json.load(f)

        self.std_no = self.config.get("stdNo")
        self.passwd = self.config.get("passwd")
        self.user_flag = self.config.get("user_flag", "1")

        self.session = requests.Session()
        self.session.trust_env = False
        proxy_url = os.environ.get("DAEJIN_UPSTREAM_PROXY", "").strip()
        if proxy_url:
            self.session.proxies.update({"http": proxy_url, "https": proxy_url})
            logger.info("🛡️ Dedicated upstream proxy enabled.")
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
        self.session.mount("https://", adapter)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Referer": f"{BASE_URL}/sugang/new/main.jsp",
            "Origin": BASE_URL
        })
        self.last_login_time = 0
        self.next_login_retry_time = 0
        self.login_failures = 0
        self.targets_mtime = 0
        self.scrape_targets = []
        self.reload_targets()

    def reload_targets(self):
        if os.path.exists(TARGETS_PATH):
            try:
                mtime = os.path.getmtime(TARGETS_PATH)
                if mtime != self.targets_mtime:
                    with open(TARGETS_PATH, "r", encoding="utf-8") as f:
                        self.scrape_targets = json.load(f)
                    self.targets_mtime = mtime
                    logger.info(f"🎯 Loaded {len(self.scrape_targets)} targets from targets.json")
            except Exception as e:
                logger.error(f"Error loading targets: {e}")

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
                self.next_login_retry_time = 0
                self.login_failures = 0
                logger.info("✅ Scraper session authenticated.")
                return True
            self._schedule_login_retry()
            return False
        except Exception as e:
            self._schedule_login_retry()
            logger.error(f"Login error: {e}")
            return False

    def _schedule_login_retry(self):
        self.login_failures += 1
        delay = min(
            LOGIN_RETRY_MAX_SECONDS,
            LOGIN_RETRY_BASE_SECONDS * (2 ** (self.login_failures - 1)),
        )
        self.next_login_retry_time = time.time() + delay

    def ensure_session(self):
        now = time.time()
        if now - self.last_login_time <= 600:
            return True
        if now < self.next_login_retry_time:
            return False
        return self.login()

    def fetch_url(self, url):
        try:
            r = self.session.get(url, timeout=3.5)
            return r.content.decode("euc-kr", "replace")
        except Exception:
            return ""

    def parse_table_html(self, html, category_name):
        courses = []
        if not html:
            return courses

        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            row = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(row) >= 10 and "-" in row[1] and len(row[1]) == 9 and row[1] != "교과번호-분반":
                code_parts = row[1].split("-")
                code = code_parts[0]
                bun = code_parts[1]
                full_code = f"{code}{bun}"

                enrolled = int(row[7]) if row[7].isdigit() else 0
                seats = int(row[8]) if row[8].isdigit() else 0
                credits_val = row[9] if len(row) > 9 else "2"
                room = row[10] if len(row) > 10 else ""
                remarks = row[11] if len(row) > 11 else ""

                courses.append({
                    "full_code": full_code,
                    "code": code,
                    "bun": bun,
                    "name": row[3],
                    "prof": row[4],
                    "time": row[5],
                    "type": row[6] if len(row) > 6 else "",
                    "enrolled": enrolled,
                    "seats": seats,
                    "credits": credits_val,
                    "room": room,
                    "remarks": remarks,
                    "category": category_name,
                    "status": "OPEN" if seats > 0 else "FULL"
                })
        return courses

    def scrape_cycle(self):
        global cached_json_response
        self.reload_targets()
        t0 = time.perf_counter()
        scraped_courses = []

        if self.ensure_session() is False:
            p1_results = []
        else:
            with ThreadPoolExecutor(max_workers=SCRAPE_MAX_WORKERS) as ex:
                p1_results = list(ex.map(lambda t: (t["url"], t["name"], self.fetch_url(t["url"])), self.scrape_targets))

        all_page_jobs = []
        for base_url, cat_name, html in p1_results:
            if not html:
                continue

            scraped_courses.extend(self.parse_table_html(html, cat_name))

            max_page = 1
            soup = BeautifulSoup(html, "html.parser")
            pagination = soup.find("div", class_="pagination")
            if pagination:
                pages = re.findall(r"setPage\(\x27(\d+)\x27\)", str(pagination))
                if pages:
                    max_page = max(int(p) for p in pages)

            if max_page > 1:
                for p in range(2, max_page + 1):
                    p_url = re.sub(r"ppage=\d+", f"ppage={p}", base_url)
                    if "ppage=" not in p_url:
                        p_url += f"?ppage={p}" if "?" not in p_url else f"&ppage={p}"
                    all_page_jobs.append((p_url, cat_name))

        if all_page_jobs:
            with ThreadPoolExecutor(max_workers=SCRAPE_MAX_WORKERS) as ex:
                rem_results = list(ex.map(lambda job: (job[1], self.fetch_url(job[0])), all_page_jobs))
            for cat_name, html in rem_results:
                if html:
                    scraped_courses.extend(self.parse_table_html(html, cat_name))

        elapsed_ms = (time.perf_counter() - t0) * 1000
        now_str = datetime.datetime.now(KST).strftime("%H:%M:%S")

        if not scraped_courses:
            stats["total_courses"] = len(course_db)
            stats["open_courses"] = sum(1 for c in course_db.values() if c.get("seats", 0) > 0)
            stats["events_count"] = len(event_history)
            cached_update_times = [c.get("last_updated") for c in course_db.values() if c.get("last_updated")]
            if cached_update_times:
                stats["last_scraped_at"] = max(cached_update_times)
            stats["last_attempted_at"] = now_str
            stats["scrape_latency_ms"] = round(elapsed_ms, 1)
            stats["status"] = "Upstream Unavailable · Cached Data"
            stats["consecutive_failures"] = stats.get("consecutive_failures", 0) + 1
            cached_json_response = json.dumps({
                "stats": dict(stats),
                "events": list(event_history[:20]),
                "courses": list(course_db.values())
            }, ensure_ascii=False).encode("utf-8")
            save_state_cache()
            return {
                "changes": [],
                "new_events": [],
                "stats": dict(stats)
            }

        changes = []
        new_events = []
        open_count = 0

        for c in scraped_courses:
            key = c["full_code"]
            prev = course_db.get(key)

            if prev:
                if prev["seats"] != c["seats"] or prev["enrolled"] != c["enrolled"]:
                    changes.append(c)
                    if prev["seats"] == 0 and c["seats"] > 0:
                        event_msg = f"🔥 [빈자리 발생!] {c['name']} ({c['code']}-{c['bun']}) {c['seats']}석 오픈! (교수: {c['prof']} / 시간: {c['time']})"
                        ev = {
                            "time": now_str,
                            "type": "VACANCY_OPEN",
                            "code": c["code"],
                            "bun": c["bun"],
                            "full_code": c["full_code"],
                            "name": c["name"],
                            "seats": c["seats"],
                            "prof": c.get("prof", ""),
                            "time_str": c.get("time", ""),
                            "msg": event_msg
                        }
                        new_events.insert(0, ev)
                        event_history.insert(0, ev)
                        logger.info(event_msg)
                    elif prev["seats"] > 0 and c["seats"] == 0:
                        ev = {
                            "time": now_str,
                            "type": "VACANCY_FILLED",
                            "code": c["code"],
                            "bun": c["bun"],
                            "full_code": c["full_code"],
                            "name": c["name"],
                            "seats": 0,
                            "prof": c.get("prof", ""),
                            "time_str": c.get("time", ""),
                            "msg": f"⏳ [마감] {c['name']} ({c['code']}-{c['bun']}) 잔여석 소진 (마감)"
                        }
                        new_events.insert(0, ev)
                        event_history.insert(0, ev)
            else:
                changes.append(c)

            c["last_updated"] = now_str
            course_db[key] = c
            if c["seats"] > 0:
                open_count += 1

        if len(event_history) > 50:
            event_history[:] = event_history[:50]

        stats["total_courses"] = len(course_db)
        stats["open_courses"] = open_count
        stats["events_count"] = len(event_history)
        stats["last_scraped_at"] = now_str
        stats["last_attempted_at"] = now_str
        stats["scrape_latency_ms"] = round(elapsed_ms, 1)
        stats["status"] = "Live Streaming"
        stats["consecutive_failures"] = 0

        cached_json_response = json.dumps({
            "stats": dict(stats),
            "events": list(event_history[:20]),
            "courses": list(course_db.values())
        }, ensure_ascii=False).encode("utf-8")

        save_state_cache()

        return {
            "changes": changes,
            "new_events": new_events,
            "stats": dict(stats)
        }


crawler = CourseCrawler()


async def broadcast_worker():
    global crawler_running
    logger.info("🚀 Background Crawler & SSE Broadcaster Task running.")
    crawler.login()
    while crawler_running:
        try:
            diff = await asyncio.to_thread(crawler.scrape_cycle)
            if diff:
                new_events = diff.get("new_events", [])
                if new_events:
                    for ev in new_events:
                        asyncio.create_task(asyncio.to_thread(push_mgr.broadcast_vacancy_event, ev))

                if subscribers:
                    payload = {
                        "type": "delta",
                        "changes": diff.get("changes", []),
                        "events": new_events,
                        "stats": diff.get("stats", {})
                    }
                    msg = f"event: update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    dead_subs = set()
                    for q in list(subscribers):
                        try:
                            q.put_nowait(msg)
                        except asyncio.QueueFull:
                            dead_subs.add(q)
                    for q in dead_subs:
                        subscribers.discard(q)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Crawler loop exception: {e}")

        try:
            await asyncio.sleep(SCRAPE_LOOP_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def lifespan(app: FastAPI):
    global crawler_running
    crawler_running = True
    task = asyncio.create_task(broadcast_worker())
    yield
    crawler_running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("🛑 Crawler background task cleanly shut down.")


app = FastAPI(title="Daejin Sugang Observer", lifespan=lifespan)


@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(
        os.path.join(BASE_DIR, "manifest.json"),
        media_type="application/manifest+json"
    )


@app.get("/sw.js")
async def get_service_worker():
    return FileResponse(
        os.path.join(BASE_DIR, "sw.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"}
    )


@app.get("/api/push/public_key")
async def get_push_public_key():
    return {"public_key": push_mgr.get_public_key()}


@app.post("/api/push/subscribe")
async def subscribe_push_api(request: Request):
    try:
        data = await request.json()
        sub = data.get("subscription")
        starred = data.get("starred_courses", [])
        mode = data.get("alert_mode", "ALL_OPEN")
        success = push_mgr.add_subscription(sub, starred, mode)
        return {"status": "ok" if success else "error"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/push/unsubscribe")
async def unsubscribe_push_api(request: Request):
    try:
        data = await request.json()
        endpoint = data.get("endpoint")
        if endpoint:
            push_mgr.remove_subscription(endpoint)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/push/test")
async def test_push_api(request: Request):
    try:
        data = await request.json()
        sub = data.get("subscription")
        if not sub:
            return {"status": "error", "message": "No subscription provided"}
        payload = {
            "title": "🔔 [대진대 옵저버] 백그라운드 푸시 연동 완료!",
            "body": "브라우저나 화면을 닫아도 수강신청 빈자리가 생기면 실시간 푸시가 도착합니다.",
            "icon": "https://www.daejin.ac.kr/favicon.ico",
            "badge": "https://www.daejin.ac.kr/favicon.ico",
            "url": "https://daejin.qucord.com"
        }
        success, msg = push_mgr.send_push(sub, payload)
        return {"status": "ok" if success else "error", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.head("/api/data")
@app.get("/api/data")
async def get_data():
    return JSONResponse(
        content=json.loads(cached_json_response.decode("utf-8")),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Content-Type": "application/json; charset=utf-8"
        }
    )


@app.post("/api/reload_targets")
async def reload_targets_api():
    crawler.reload_targets()
    return {"status": "ok", "targets_count": len(crawler.scrape_targets)}


@app.get("/api/stream")
async def sse_stream(request: Request):
    q = asyncio.Queue(maxsize=30)
    subscribers.add(q)

    init_data = json.dumps({
        "type": "init",
        "courses": list(course_db.values()),
        "events": list(event_history[:20]),
        "stats": dict(stats)
    }, ensure_ascii=False)
    await q.put(f"event: init\ndata: {init_data}\n\n")

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield data
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            subscribers.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


HTML_CONTENT = """<!DOCTYPE html>
<html lang="ko" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>대진대 수강신청 실시간 빈자리 옵저버</title>
  <link rel="manifest" href="/manifest.json">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="대진 옵저버">
  <link rel="apple-touch-icon" href="https://www.daejin.ac.kr/site/daejin/images/common/logo.png">
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: '#3b82f6',
            brandDark: '#1e3a8a',
            surface: '#18181b',
            surfaceCard: '#27272a',
            surfaceBorder: '#3f3f46'
          }
        }
      }
    }
  </script>
  <style>
    @keyframes pulse-fast { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
    .live-dot { animation: pulse-fast 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
  </style>
</head>
<body class="bg-zinc-950 text-zinc-100 min-h-screen font-sans antialiased selection:bg-blue-500 selection:text-white">

  <!-- Header -->
  <header class="border-b border-zinc-800 bg-zinc-900/80 backdrop-blur sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 py-3 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-xl bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
          <i class="fa-solid fa-radar text-lg"></i>
        </div>
        <div>
          <h1 class="text-lg font-bold flex items-center gap-2">
            대진대 수강신청 실시간 옵저버
            <span id="connBadge" class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 live-dot"></span> <span id="connLabel">SSE 연결 중</span>
            </span>
          </h1>
          <p class="text-xs text-zinc-400">전공(스마트융합보안, 경영학과) 및 교양 전 영역 실시간 취소표 감지</p>
        </div>
      </div>
      
      <!-- Notification Controls Bar -->
      <div class="flex flex-wrap items-center gap-2 text-xs">
        <!-- Subscribed Filter Quick Button -->
        <button id="starredQuickBtn" onclick="toggleStarredOnly()" 
                class="px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition flex items-center gap-1.5 text-zinc-300">
          <i class="fa-solid fa-star text-amber-400"></i>
          <span id="starredCountLabel">⭐ 구독 0개</span>
        </button>

        <!-- Web Push Notification Request -->
        <button id="pushNotifBtn" onclick="toggleWebPush()" 
                class="px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition flex items-center gap-1.5 text-zinc-300">
          <i id="pushIcon" class="fa-solid fa-bell"></i>
          <span id="pushLabel">백그라운드 푸시 켜기</span>
        </button>

        <!-- Alert Scope Selector -->
        <select id="alertModeSelect" onchange="changeAlertMode()" 
                class="bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-blue-500 font-medium">
          <option value="ALL_OPEN">🔥 전체 빈자리 알림</option>
          <option value="STARRED_ONLY">⭐ 구독 과목만 알림</option>
          <option value="MUTED">🔕 알림 끄기</option>
        </select>

        <div class="flex items-center gap-1">
          <button id="soundToggle" onclick="toggleSound()" class="px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition flex items-center gap-1.5 text-zinc-300">
            <i id="soundIcon" class="fa-solid fa-volume-high text-emerald-400"></i>
            <span id="soundLabel">소리 ON</span>
          </button>
          <button onclick="testSoundBtn()" title="알림음 즉시 테스트 및 iOS 오디오 활성화" class="px-2 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition text-zinc-400 hover:text-emerald-400 text-xs flex items-center gap-1">
            <i class="fa-solid fa-volume-low"></i>
            <span class="hidden sm:inline">테스트</span>
          </button>
        </div>
      </div>
    </div>
  </header>

  <!-- iOS Safari PWA Guide Modal -->
  <div id="iosModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden items-center justify-center p-4">
    <div class="bg-zinc-900 border border-zinc-700 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl">
      <div class="flex items-center justify-between">
        <h3 class="text-base font-bold text-zinc-100 flex items-center gap-2">
          <i class="fa-brands fa-apple text-emerald-400"></i> 아이폰 백그라운드 푸시 설정
        </h3>
        <button onclick="closeIosModal()" class="text-zinc-400 hover:text-zinc-200">
          <i class="fa-solid fa-xmark text-lg"></i>
        </button>
      </div>
      <p class="text-xs text-zinc-300 leading-relaxed">
        iOS 사파리는 보안 정책상 <strong class="text-emerald-400">'홈 화면에 추가(PWA)'</strong>된 상태에서만 브라우저가 꺼져 있을 때 백그라운드 푸시 알림을 수신할 수 있습니다.
      </p>
      <div class="space-y-3 bg-zinc-950/80 p-4 rounded-xl border border-zinc-800 text-xs">
        <div class="flex items-start gap-2.5">
          <span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 font-bold flex items-center justify-center text-[11px] shrink-0">1</span>
          <span>사파리 하단 메뉴바의 <strong>[공유]</strong> 아이콘( <i class="fa-solid fa-arrow-up-from-bracket text-blue-400"></i> )을 누릅니다.</span>
        </div>
        <div class="flex items-start gap-2.5">
          <span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 font-bold flex items-center justify-center text-[11px] shrink-0">2</span>
          <span>아래로 스크롤하여 <strong>[홈 화면에 추가]</strong>( <i class="fa-regular fa-square-plus text-emerald-400"></i> )를 선택합니다.</span>
        </div>
        <div class="flex items-start gap-2.5">
          <span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 font-bold flex items-center justify-center text-[11px] shrink-0">3</span>
          <span>홈 화면에 생성된 <strong>'대진 옵저버'</strong> 앱 아이콘으로 접속한 뒤 <strong>[🔔 백그라운드 푸시 켜기]</strong>를 누르면 완료!</span>
        </div>
      </div>
      <div class="text-[11px] text-zinc-400">
        💡 안드로이드 및 PC 크롬/엣지/파폭/웨일은 홈 화면 추가 없이 즉시 백그라운드 푸시가 수신됩니다.
      </div>
      <button onclick="closeIosModal()" class="w-full py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 font-bold text-xs text-white transition">
        확인했습니다
      </button>
    </div>
  </div>

  <main class="max-w-7xl mx-auto px-4 py-6 space-y-6">

    <!-- KPI Metric Cards -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-zinc-900 border border-zinc-800 p-4 rounded-2xl">
        <div class="text-xs text-zinc-400 font-medium mb-1">총 모니터링 강좌</div>
        <div id="statTotal" class="text-2xl font-bold text-zinc-100 font-mono">0</div>
        <div class="text-[11px] text-zinc-500 mt-1">전공 + 교필 + 교선 전영역</div>
      </div>
      <div class="bg-zinc-900 border border-zinc-800 p-4 rounded-2xl relative overflow-hidden">
        <div class="absolute right-3 top-3 w-8 h-8 rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-400 text-xs font-bold">
          <i class="fa-solid fa-door-open"></i>
        </div>
        <div class="text-xs text-emerald-400 font-medium mb-1">현재 빈자리 강좌</div>
        <div id="statOpen" class="text-2xl font-bold text-emerald-400 font-mono">0</div>
        <div class="text-[11px] text-zinc-500 mt-1">즉시 신청 가능한 강좌</div>
      </div>
      <div class="bg-zinc-900 border border-zinc-800 p-4 rounded-2xl">
        <div class="text-xs text-zinc-400 font-medium mb-1">취소표 감지 피드</div>
        <div id="statEvents" class="text-2xl font-bold text-amber-400 font-mono">0</div>
        <div class="text-[11px] text-zinc-500 mt-1">실시간 감지된 변동 건수</div>
      </div>
      <div class="bg-zinc-900 border border-zinc-800 p-4 rounded-2xl">
        <div class="text-xs text-zinc-400 font-medium mb-1">내 관심 과목</div>
        <div id="statStarred" class="text-2xl font-bold text-amber-400 font-mono">0</div>
        <div class="text-[11px] text-zinc-500 mt-1">⭐ 알림 타겟 구독 과목</div>
      </div>
    </div>

    <!-- Live Vacancy Alert Feed Ticker -->
    <div class="bg-zinc-900/90 border border-zinc-800 rounded-2xl p-4">
      <div class="flex items-center justify-between mb-2">
        <h2 class="text-sm font-bold flex items-center gap-2 text-zinc-200">
          <i class="fa-solid fa-bolt text-amber-400"></i> 실시간 취소표 발생 피드
        </h2>
        <span class="text-[11px] text-zinc-500">실시간 스트림 (최근 20건)</span>
      </div>
      <div id="eventsContainer" class="space-y-1.5 max-h-36 overflow-y-auto pr-1 text-xs font-mono">
        <div class="text-zinc-500 italic py-2 text-center">아직 감지된 취소표 이벤트가 없습니다. 실시간 감시 중...</div>
      </div>
    </div>

    <!-- Filter & Search Controls -->
    <div class="bg-zinc-900 border border-zinc-800 p-4 rounded-2xl space-y-3">
      <div class="flex flex-col md:flex-row gap-3">
        <!-- Search Input -->
        <div class="relative flex-1">
          <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-3 text-zinc-500 text-sm"></i>
          <input id="searchInput" type="text" placeholder="과목명, 교수명, 학수번호(6자리), 요일 검색..." 
                 class="w-full pl-10 pr-4 py-2 bg-zinc-950 border border-zinc-800 rounded-xl text-sm text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-blue-500 transition"
                 oninput="renderCourses()">
        </div>

        <!-- Category Dropdown -->
        <select id="categoryFilter" onchange="renderCourses()"
                class="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500">
          <option value="ALL">전체 영역 / 학과</option>
          <option value="스마트융합보안">스마트융합보안 전공</option>
          <option value="경영학과">경영학과 전공</option>
          <option value="교양필수">교양필수 (사표/영읽토/대순/AI)</option>
          <option value="교양선택">교양선택 전체</option>
          <option value="1영역">교선 1영역 (인간과소통)</option>
          <option value="2영역">교선 2영역 (사회와경제)</option>
          <option value="3영역">교선 3영역 (과학과기술)</option>
          <option value="4영역">교선 4영역 (예술과문화)</option>
          <option value="5영역">교선 5영역 (융합과혁신)</option>
          <option value="6영역">교선 6영역 (AI·디지털리터러시)</option>
          <option value="교직">교직</option>
          <option value="일반선택">일반선택</option>
        </select>

        <!-- Sort Select -->
        <select id="sortSelect" onchange="onSortDropdownChange()"
                class="bg-zinc-950 border border-zinc-800 rounded-xl px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:border-blue-500">
          <option value="SEATS_DESC">⚡ 여석 많은 순 (기본)</option>
          <option value="SEATS_ASC">🔥 여석 적은 순 (마감임박)</option>
          <option value="NAME_ASC">🔤 과목명 (가나다순)</option>
          <option value="NAME_DESC">🔤 과목명 (역순)</option>
          <option value="CODE_ASC">🔢 학수번호순</option>
          <option value="PROF_ASC">👨‍🏫 교수명순</option>
          <option value="ENROLLED_DESC">👥 신청자 많은 순 (인기)</option>
          <option value="ENROLLED_ASC">👥 신청자 적은 순</option>
        </select>

        <!-- Starred Only Toggle -->
        <label class="flex items-center gap-2 cursor-pointer bg-zinc-950 border border-zinc-800 px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-zinc-800/50 transition select-none">
          <input id="starredOnlyToggle" type="checkbox" onchange="renderCourses()" class="w-4 h-4 rounded text-amber-400 focus:ring-0 bg-zinc-900 border-zinc-700">
          <span class="text-amber-400 flex items-center gap-1">
            <i class="fa-solid fa-star"></i> 구독 과목만
          </span>
        </label>

        <!-- Open Only Toggle -->
        <label class="flex items-center gap-2 cursor-pointer bg-zinc-950 border border-zinc-800 px-3.5 py-2 rounded-xl text-sm font-medium hover:bg-zinc-800/50 transition select-none">
          <input id="openOnlyToggle" type="checkbox" onchange="renderCourses()" class="w-4 h-4 rounded text-emerald-500 focus:ring-0 bg-zinc-900 border-zinc-700">
          <span class="text-emerald-400 flex items-center gap-1">
            <i class="fa-solid fa-sparkles"></i> 빈자리만
          </span>
        </label>
      </div>
    </div>

    <!-- Courses Table -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-2xl overflow-hidden">
      <div class="px-4 py-3 border-b border-zinc-800 flex items-center justify-between text-xs text-zinc-400">
        <span id="filteredCount">0개 강좌 표시 중</span>
        <span>⭐ 클릭하여 과목 알림 구독 / 학수번호 클릭하여 복사</span>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="bg-zinc-950/70 text-zinc-400 text-xs uppercase border-b border-zinc-800">
            <tr>
              <th class="py-3 px-3 text-center w-10">⭐</th>
              <th onclick="setSort('seats')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                상태 / 여석 <span id="sort_icon_seats">▼</span>
              </th>
              <th onclick="setSort('code')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                학수-분반 <span id="sort_icon_code"></span>
              </th>
              <th onclick="setSort('name')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                교과목명 <span id="sort_icon_name"></span>
              </th>
              <th onclick="setSort('prof')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                담당교수 <span id="sort_icon_prof"></span>
              </th>
              <th onclick="setSort('time')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                강의시간 <span id="sort_icon_time"></span>
              </th>
              <th onclick="setSort('enrolled')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                신청/여석 <span id="sort_icon_enrolled"></span>
              </th>
              <th onclick="setSort('category')" class="py-3 px-4 cursor-pointer select-none hover:text-white transition">
                영역/학과 <span id="sort_icon_category"></span>
              </th>
              <th class="py-3 px-4 text-right">복사</th>
            </tr>
          </thead>
          <tbody id="courseTableBody" class="divide-y divide-zinc-800/60 font-sans">
            <tr>
              <td colspan="9" class="text-center py-8 text-zinc-500">데이터 스트림에 연결하는 중입니다...</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </main>

  <audio id="alertAudio" src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" preload="auto"></audio>

  <script>
    let courseMap = new Map();
    let eventsList = [];
    let soundEnabled = true;
    let knownOpenKeys = new Set();
    let isInitialized = false;
    let eventSource = null;
    let currentSort = 'SEATS_DESC';

    // Watchlist / Subscriptions
    let starredKeys = new Set(JSON.parse(localStorage.getItem('daejin_starred_courses') || '[]'));
    let alertMode = localStorage.getItem('daejin_alert_mode') || 'ALL_OPEN';

    // Web Audio API Context & iOS Unlock
    let audioCtx = null;

    function getAudioContext() {
      if (!audioCtx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (AudioContextClass) {
          audioCtx = new AudioContextClass();
        }
      }
      return audioCtx;
    }

    function unlockAudio() {
      const ctx = getAudioContext();
      if (ctx && ctx.state === 'suspended') {
        ctx.resume();
      }
      // Play 1-sample silent buffer to unlock iOS Safari Web Audio
      if (ctx) {
        try {
          const buffer = ctx.createBuffer(1, 1, 22050);
          const source = ctx.createBufferSource();
          source.buffer = buffer;
          source.connect(ctx.destination);
          source.start(0);
        } catch (e) {}
      }
      const audio = document.getElementById('alertAudio');
      if (audio) {
        audio.play().then(() => {
          audio.pause();
          audio.currentTime = 0;
        }).catch(() => {});
      }
    }

    // Auto-unlock audio engine on first user interaction anywhere on screen
    ['click', 'touchstart', 'touchend', 'pointerdown'].forEach(evt => {
      document.addEventListener(evt, unlockAudio, { passive: true });
    });

    function playSynthChime() {
      const ctx = getAudioContext();
      if (!ctx) return false;
      try {
        if (ctx.state === 'suspended') {
          ctx.resume();
        }
        const now = ctx.currentTime;
        
        // High-clarity pleasant dual chime: 987Hz (B5) -> 1318Hz (E6) -> 1760Hz (A6)
        const osc1 = ctx.createOscillator();
        const osc2 = ctx.createOscillator();
        const gain = ctx.createGain();

        osc1.type = 'sine';
        osc1.frequency.setValueAtTime(987.77, now);
        osc1.frequency.exponentialRampToValueAtTime(1318.51, now + 0.08);

        osc2.type = 'triangle';
        osc2.frequency.setValueAtTime(1975.53, now);
        osc2.frequency.exponentialRampToValueAtTime(2637.02, now + 0.08);

        gain.gain.setValueAtTime(0.35, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);

        osc1.connect(gain);
        osc2.connect(gain);
        gain.connect(ctx.destination);

        osc1.start(now);
        osc2.start(now);
        osc1.stop(now + 0.65);
        osc2.stop(now + 0.65);
        return true;
      } catch (err) {
        console.warn("Synth chime failed:", err);
        return false;
      }
    }

    // Web Push (VAPID / Service Worker) State
    let isPushSubscribed = false;
    let pushSubscription = null;
    let swRegistration = null;

    function isIos() {
      return /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    }

    function isStandalone() {
      return (window.navigator.standalone === true) || window.matchMedia('(display-mode: standalone)').matches;
    }

    function showIosModal() {
      const m = document.getElementById('iosModal');
      if (m) { m.classList.remove('hidden'); m.classList.add('flex'); }
    }

    function closeIosModal() {
      const m = document.getElementById('iosModal');
      if (m) { m.classList.add('hidden'); m.classList.remove('flex'); }
    }

    function urlB64ToUint8Array(base64String) {
      const padding = '='.repeat((4 - base64String.length % 4) % 4);
      const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
      const rawData = window.atob(base64);
      const outputArray = new Uint8Array(rawData.length);
      for (let i = 0; i < rawData.length; ++i) {
        outputArray[i] = rawData.charCodeAt(i);
      }
      return outputArray;
    }

    async function initServiceWorker() {
      if (!('serviceWorker' in navigator)) return;

      try {
        swRegistration = await navigator.serviceWorker.register('/sw.js');
        if ('PushManager' in window) {
          pushSubscription = await swRegistration.pushManager.getSubscription();
          isPushSubscribed = !!pushSubscription;
          updatePushBtnUI();
        }
      } catch (err) {
        console.warn('Service Worker registration error:', err);
      }
    }

    function updatePushBtnUI() {
      const btn = document.getElementById('pushNotifBtn');
      const icon = document.getElementById('pushIcon');
      const label = document.getElementById('pushLabel');
      if (!btn || !icon || !label) return;

      if (isIos() && !isStandalone() && !('PushManager' in window)) {
        icon.className = "fa-brands fa-apple text-amber-400";
        label.innerText = "아이폰 푸시 설정";
        return;
      }

      if (isPushSubscribed) {
        btn.className = "px-2.5 py-1.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 hover:bg-emerald-500/20 transition flex items-center gap-1.5 text-emerald-300 font-medium";
        icon.className = "fa-solid fa-bell text-emerald-400";
        label.innerText = "백그라운드 푸시 켜짐";
      } else {
        btn.className = "px-2.5 py-1.5 rounded-lg bg-zinc-800 border border-zinc-700 hover:bg-zinc-700 transition flex items-center gap-1.5 text-zinc-300";
        icon.className = "fa-solid fa-bell-slash text-zinc-400";
        label.innerText = "백그라운드 푸시 켜기";
      }
    }

    async function syncPushPreferences() {
      if (!pushSubscription) return;
      try {
        await fetch('/api/push/subscribe', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            subscription: pushSubscription,
            starred_courses: Array.from(starredKeys),
            alert_mode: alertMode
          })
        });
      } catch (e) {
        console.warn("Failed to sync push preferences:", e);
      }
    }

    async function toggleWebPush() {
      if (isIos() && !isStandalone() && !('PushManager' in window)) {
        showIosModal();
        return;
      }

      if (!('PushManager' in window) || !('serviceWorker' in navigator)) {
        if (isIos() && !isStandalone()) {
          showIosModal();
          return;
        }
        alert('이 브라우저는 웹 푸시 API를 지원하지 않습니다.');
        return;
      }

      if (!swRegistration) {
        await initServiceWorker();
      }

      if (isPushSubscribed) {
        // Unsubscribe
        try {
          if (pushSubscription) {
            await fetch('/api/push/unsubscribe', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ endpoint: pushSubscription.endpoint })
            });
            await pushSubscription.unsubscribe();
          }
          pushSubscription = null;
          isPushSubscribed = false;
          updatePushBtnUI();
        } catch (e) {
          console.error('Failed to unsubscribe:', e);
        }
      } else {
        // Subscribe
        try {
          const perm = await Notification.requestPermission();
          if (perm !== 'granted') {
            alert('알림 권한이 허용되지 않았습니다. 브라우저 설정에서 알림 권한을 허용해주세요.');
            return;
          }

          const keyRes = await fetch('/api/push/public_key');
          const { public_key } = await keyRes.json();

          const sub = await swRegistration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlB64ToUint8Array(public_key)
          });

          pushSubscription = sub;
          isPushSubscribed = true;

          // Register on server
          await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              subscription: sub,
              starred_courses: Array.from(starredKeys),
              alert_mode: alertMode
            })
          });

          updatePushBtnUI();

          // Send immediate test verification push
          await fetch('/api/push/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ subscription: sub })
          });
        } catch (err) {
          console.error('Push subscription failed:', err);
          if (isIos() && !isStandalone()) {
            showIosModal();
          } else {
            alert('푸시 알림 등록에 실패했습니다: ' + err.message);
          }
        }
      }
    }

    function initSettings() {
      const modeSelect = document.getElementById('alertModeSelect');
      if (modeSelect) modeSelect.value = alertMode;
      updateStarredCountUI();
      initServiceWorker();

      // Instant 0ms cache hydration
      fetch('/api/data').then(r => r.json()).then(data => {
        if (!isInitialized && data && data.courses) {
          courseMap.clear();
          data.courses.forEach(c => {
            courseMap.set(c.full_code, c);
            if (c.seats > 0) knownOpenKeys.add(c.full_code);
          });
          eventsList = data.events || [];
          updateStatsUI(data.stats);
          renderEvents(eventsList);
          renderCourses();
          isInitialized = true;
        }
      }).catch(() => {});
    }

    function changeAlertMode() {
      alertMode = document.getElementById('alertModeSelect').value;
      localStorage.setItem('daejin_alert_mode', alertMode);
      syncPushPreferences();
    }

    function toggleStarredOnly() {
      const chk = document.getElementById('starredOnlyToggle');
      chk.checked = !chk.checked;
      renderCourses();
    }

    function toggleSubscription(full_code) {
      if (starredKeys.has(full_code)) {
        starredKeys.delete(full_code);
      } else {
        starredKeys.add(full_code);
      }
      localStorage.setItem('daejin_starred_courses', JSON.stringify(Array.from(starredKeys)));
      updateStarredCountUI();
      renderCourses();
      syncPushPreferences();
    }

    function updateStarredCountUI() {
      const cnt = starredKeys.size;
      document.getElementById('statStarred').innerText = cnt;
      document.getElementById('starredCountLabel').innerText = `⭐ 구독 ${cnt}개`;
    }

    function toggleSound() {
      unlockAudio();
      soundEnabled = !soundEnabled;
      document.getElementById('soundIcon').className = soundEnabled ? 'fa-solid fa-volume-high text-emerald-400' : 'fa-solid fa-volume-xmark text-zinc-500';
      document.getElementById('soundLabel').innerText = soundEnabled ? '소리 ON' : '소리 OFF';
      if (soundEnabled) {
        playSynthChime();
      }
    }

    function testSoundBtn() {
      unlockAudio();
      soundEnabled = true;
      document.getElementById('soundIcon').className = 'fa-solid fa-volume-high text-emerald-400';
      document.getElementById('soundLabel').innerText = '소리 ON';
      playSynthChime();
    }

    function playBeep() {
      if (!soundEnabled || alertMode === 'MUTED') return;
      
      // 1. Try synthesized Web Audio (zero network latency & iOS Safari background compatible)
      const played = playSynthChime();
      
      // 2. Fallback to HTML5 audio element
      if (!played) {
        const audio = document.getElementById('alertAudio');
        if (audio) {
          audio.currentTime = 0;
          audio.play().catch(() => {});
        }
      }
    }

    function fireWebPush(c) {
      if (!("Notification" in window) || Notification.permission !== "granted" || alertMode === 'MUTED') return;
      try {
        const notif = new Notification(`🔥 [빈자리 발생!] ${c.name} (${c.code}-${c.bun})`, {
          body: `현재 ${c.seats}자리 발생! 교수: ${c.prof || '-'} | 시간: ${c.time || '-'} (클릭하여 복사)`,
          icon: "https://www.daejin.ac.kr/favicon.ico",
          tag: `vacancy-${c.full_code}`,
          renotify: true
        });
        notif.onclick = function() {
          window.focus();
          navigator.clipboard.writeText(`${c.code}${c.bun}`);
          notif.close();
        };
      } catch (err) {
        console.warn("Notification trigger error:", err);
      }
    }

    function triggerAlertForCourse(c) {
      const isStarred = starredKeys.has(c.full_code);
      const shouldAlert = (alertMode === 'ALL_OPEN') || (alertMode === 'STARRED_ONLY' && isStarred);
      if (shouldAlert) {
        playBeep();
        fireWebPush(c);
      }
    }

    function copyToClipboard(text, btn) {
      navigator.clipboard.writeText(text).then(() => {
        const oldHtml = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check text-emerald-400"></i>';
        setTimeout(() => { btn.innerHTML = oldHtml; }, 1200);
      });
    }

    function updateConnectionHealthUI(s) {
      if (!s) return;
      const badge = document.getElementById('connBadge');
      const label = document.getElementById('connLabel');
      if (!badge || !label) return;
      if ((s.status || '').includes('Upstream Unavailable')) {
        badge.className = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-300 border border-amber-500/30";
        label.innerText = "원본 서버 장애 · 캐시";
        badge.title = `대진대 원본 서버 연결 실패 · 마지막 정상 수집 ${s.last_scraped_at || '-'}`;
      } else if (eventSource && eventSource.readyState === EventSource.OPEN) {
        badge.className = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
        label.innerText = "SSE 라이브";
        badge.title = '';
      }
    }

    function updateStatsUI(s) {
      if (!s) return;
      const setTxt = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.innerText = val;
      };
      setTxt('statTotal', s.total_courses || 0);
      setTxt('statOpen', s.open_courses || 0);
      setTxt('statEvents', s.events_count || 0);
      setTxt('statStatus', s.status || 'Live');
      setTxt('lastUpdated', s.last_scraped_at || '-');
      setTxt('scrapeLatency', (s.scrape_latency_ms || 0) + 'ms');
      updateConnectionHealthUI(s);
    }

    function renderEvents(events) {
      const container = document.getElementById('eventsContainer');
      if (!events || events.length === 0) {
        container.innerHTML = '<div class="text-zinc-500 italic py-2 text-center">아직 감지된 취소표 이벤트가 없습니다. 실시간 감시 중...</div>';
        return;
      }

      container.innerHTML = events.slice(0, 20).map(e => {
        const isOpen = e.type === 'VACANCY_OPEN';
        const isStarred = starredKeys.has(e.full_code || `${e.code}${e.bun}`);
        return `
          <div class="flex items-center justify-between py-1 px-2.5 rounded-lg ${isStarred ? 'bg-amber-500/10 border border-amber-500/30 text-amber-300' : (isOpen ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300' : 'bg-zinc-800/40 text-zinc-400')}">
            <div class="flex items-center gap-2 truncate">
              <span class="text-zinc-500 font-mono text-[10px]">[${e.time}]</span>
              ${isStarred ? '<span class="text-amber-400">⭐</span>' : ''}
              <span class="font-bold ${isOpen ? (isStarred ? 'text-amber-300' : 'text-emerald-400') : 'text-zinc-400'}">${e.name} (${e.code}-${e.bun})</span>
              <span>${isOpen ? '🔥 ' + e.seats + '자리 발생!' : '마감'}</span>
            </div>
            <button onclick="copyToClipboard('${e.code}${e.bun}', this)" class="text-[10px] px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition">
              복사
            </button>
          </div>
        `;
      }).join('');
    }

    function setSort(field) {
      if (field === 'seats') currentSort = currentSort === 'SEATS_DESC' ? 'SEATS_ASC' : 'SEATS_DESC';
      else if (field === 'name') currentSort = currentSort === 'NAME_ASC' ? 'NAME_DESC' : 'NAME_ASC';
      else if (field === 'code') currentSort = currentSort === 'CODE_ASC' ? 'CODE_DESC' : 'CODE_ASC';
      else if (field === 'prof') currentSort = currentSort === 'PROF_ASC' ? 'PROF_DESC' : 'PROF_ASC';
      else if (field === 'enrolled') currentSort = currentSort === 'ENROLLED_DESC' ? 'ENROLLED_ASC' : 'ENROLLED_DESC';
      else if (field === 'time') currentSort = currentSort === 'TIME_ASC' ? 'TIME_DESC' : 'TIME_ASC';
      else if (field === 'category') currentSort = currentSort === 'CAT_ASC' ? 'CAT_DESC' : 'CAT_ASC';

      const selectElem = document.getElementById('sortSelect');
      if (selectElem) selectElem.value = currentSort;
      renderCourses();
    }

    function onSortDropdownChange() {
      currentSort = document.getElementById('sortSelect').value;
      renderCourses();
    }

    function updateSortHeaderIcons() {
      const icons = {
        sort_icon_seats: '', sort_icon_code: '', sort_icon_name: '',
        sort_icon_prof: '', sort_icon_time: '', sort_icon_enrolled: '', sort_icon_category: ''
      };
      if (currentSort === 'SEATS_DESC') icons.sort_icon_seats = '▼';
      else if (currentSort === 'SEATS_ASC') icons.sort_icon_seats = '▲';
      else if (currentSort === 'CODE_ASC') icons.sort_icon_code = '▲';
      else if (currentSort === 'CODE_DESC') icons.sort_icon_code = '▼';
      else if (currentSort === 'NAME_ASC') icons.sort_icon_name = '▲';
      else if (currentSort === 'NAME_DESC') icons.sort_icon_name = '▼';
      else if (currentSort === 'PROF_ASC') icons.sort_icon_prof = '▲';
      else if (currentSort === 'PROF_DESC') icons.sort_icon_prof = '▼';
      else if (currentSort === 'ENROLLED_DESC') icons.sort_icon_enrolled = '▼';
      else if (currentSort === 'ENROLLED_ASC') icons.sort_icon_enrolled = '▲';
      else if (currentSort === 'TIME_ASC') icons.sort_icon_time = '▲';
      else if (currentSort === 'TIME_DESC') icons.sort_icon_time = '▼';
      else if (currentSort === 'CAT_ASC') icons.sort_icon_category = '▲';
      else if (currentSort === 'CAT_DESC') icons.sort_icon_category = '▼';

      for (const [id, arrow] of Object.entries(icons)) {
        const el = document.getElementById(id);
        if (el) el.innerText = arrow;
      }
    }

    function renderCourses() {
      const search = document.getElementById('searchInput').value.trim().toLowerCase();
      const cat = document.getElementById('categoryFilter').value;
      const openOnly = document.getElementById('openOnlyToggle').checked;
      const starredOnly = document.getElementById('starredOnlyToggle').checked;

      const allCourses = Array.from(courseMap.values());

      const filtered = allCourses.filter(c => {
        if (openOnly && c.seats <= 0) return false;
        if (starredOnly && !starredKeys.has(c.full_code)) return false;
        if (cat !== 'ALL') {
          if (cat === '교양선택') {
            if (!c.category.includes('교선') && !c.category.includes('교양선택')) return false;
          } else if (!c.category.includes(cat)) {
            return false;
          }
        }
        if (search) {
          const matchCode = c.full_code.toLowerCase().includes(search) || c.code.toLowerCase().includes(search);
          const matchName = c.name.toLowerCase().includes(search);
          const matchProf = (c.prof || '').toLowerCase().includes(search);
          const matchTime = (c.time || '').toLowerCase().includes(search);
          const matchCat = (c.category || '').toLowerCase().includes(search);
          if (!matchCode && !matchName && !matchProf && !matchTime && !matchCat) return false;
        }
        return true;
      });

      if (currentSort === 'SEATS_DESC') {
        filtered.sort((a, b) => b.seats - a.seats || a.code.localeCompare(b.code));
      } else if (currentSort === 'SEATS_ASC') {
        filtered.sort((a, b) => {
          if (a.seats > 0 && b.seats > 0) return a.seats - b.seats || a.code.localeCompare(b.code);
          if (a.seats > 0) return -1;
          if (b.seats > 0) return 1;
          return a.code.localeCompare(b.code);
        });
      } else if (currentSort === 'NAME_ASC') filtered.sort((a, b) => a.name.localeCompare(b.name, 'ko'));
      else if (currentSort === 'NAME_DESC') filtered.sort((a, b) => b.name.localeCompare(a.name, 'ko'));
      else if (currentSort === 'CODE_ASC') filtered.sort((a, b) => a.full_code.localeCompare(b.full_code));
      else if (currentSort === 'CODE_DESC') filtered.sort((a, b) => b.full_code.localeCompare(a.full_code));
      else if (currentSort === 'PROF_ASC') filtered.sort((a, b) => (a.prof || '').localeCompare(b.prof || '', 'ko'));
      else if (currentSort === 'PROF_DESC') filtered.sort((a, b) => (b.prof || '').localeCompare(a.prof || '', 'ko'));
      else if (currentSort === 'ENROLLED_DESC') filtered.sort((a, b) => b.enrolled - a.enrolled || a.code.localeCompare(b.code));
      else if (currentSort === 'ENROLLED_ASC') filtered.sort((a, b) => a.enrolled - b.enrolled || a.code.localeCompare(b.code));
      else if (currentSort === 'TIME_ASC') filtered.sort((a, b) => (a.time || '').localeCompare(b.time || ''));
      else if (currentSort === 'TIME_DESC') filtered.sort((a, b) => (b.time || '').localeCompare(a.time || ''));
      else if (currentSort === 'CAT_ASC') filtered.sort((a, b) => (a.category || '').localeCompare(b.category || '', 'ko'));
      else if (currentSort === 'CAT_DESC') filtered.sort((a, b) => (b.category || '').localeCompare(a.category || '', 'ko'));

      updateSortHeaderIcons();
      document.getElementById('filteredCount').innerText = `${filtered.length}개 강좌 표시 중`;

      const tbody = document.getElementById('courseTableBody');
      if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center py-8 text-zinc-500">조건에 맞는 강좌가 없습니다.</td></tr>';
        return;
      }

      tbody.innerHTML = filtered.map(c => {
        const isOpen = c.seats > 0;
        const isStarred = starredKeys.has(c.full_code);
        return `
          <tr class="hover:bg-zinc-800/40 transition border-b border-zinc-800/40 ${isStarred ? 'bg-amber-950/20' : (isOpen ? 'bg-emerald-950/20' : '')}">
            <td class="py-3 px-3 text-center">
              <button onclick="toggleSubscription('${c.full_code}')" title="${isStarred ? '구독 해제' : '알림 구독'}" class="text-base transition ${isStarred ? 'text-amber-400 scale-110' : 'text-zinc-600 hover:text-zinc-400'}">
                <i class="fa-solid fa-star"></i>
              </button>
            </td>
            <td class="py-3 px-4 whitespace-nowrap">
              ${isOpen 
                ? `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                     <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 live-dot"></span> ${c.seats}석 오픈!
                   </span>`
                : `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs text-zinc-500 bg-zinc-800/50">마감</span>`
              }
            </td>
            <td class="py-3 px-4 font-mono font-bold text-zinc-200 whitespace-nowrap">
              ${c.code}-${c.bun}
            </td>
            <td class="py-3 px-4 font-medium text-zinc-100">
              ${c.name}
              <span class="text-xs text-zinc-500 block sm:inline">(${c.credits}학점)</span>
            </td>
            <td class="py-3 px-4 text-zinc-300 whitespace-nowrap">${c.prof || '-'}</td>
            <td class="py-3 px-4 text-zinc-400 font-mono text-xs whitespace-nowrap">${c.time || '-'}</td>
            <td class="py-3 px-4 whitespace-nowrap font-mono text-xs">
              <span class="text-zinc-400">${c.enrolled}</span>
              <span class="text-zinc-600">/</span>
              <span class="${isOpen ? 'text-emerald-400 font-bold text-sm' : 'text-zinc-500'}">${c.seats}</span>
            </td>
            <td class="py-3 px-4 text-xs text-zinc-400 truncate max-w-xs">${c.category}</td>
            <td class="py-3 px-4 text-right whitespace-nowrap">
              <button onclick="copyToClipboard('${c.code}${c.bun}', this)" 
                      title="학수번호 ${c.code}${c.bun} 복사"
                      class="px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs text-zinc-300 transition border border-zinc-700/60 flex items-center gap-1 ml-auto">
                <i class="fa-regular fa-copy"></i>
                <span>${c.code}</span>
              </button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function initSSE() {
      if (!!window.EventSource) {
        eventSource = new EventSource('/api/stream');

        eventSource.addEventListener('init', (e) => {
          const data = JSON.parse(e.data);
          courseMap.clear();
          (data.courses || []).forEach(c => {
            courseMap.set(c.full_code, c);
            if (c.seats > 0) knownOpenKeys.add(c.full_code);
          });
          eventsList = data.events || [];
          updateStatsUI(data.stats);
          renderEvents(eventsList);
          renderCourses();
          isInitialized = true;

          updateConnectionHealthUI(data.stats);
        });

        eventSource.addEventListener('update', (e) => {
          const data = JSON.parse(e.data);

          (data.changes || []).forEach(c => {
            courseMap.set(c.full_code, c);

            if (c.seats > 0) {
              if (isInitialized && !knownOpenKeys.has(c.full_code)) {
                triggerAlertForCourse(c);
              }
              knownOpenKeys.add(c.full_code);
            } else {
              knownOpenKeys.delete(c.full_code);
            }
          });

          if (data.events && data.events.length > 0) {
            eventsList = [...data.events, ...eventsList].slice(0, 50);
            renderEvents(eventsList);
          }

          updateStatsUI(data.stats);
          renderCourses();
        });

        eventSource.onerror = (err) => {
          document.getElementById('connBadge').className = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/20";
          document.getElementById('connLabel').innerText = "폴링 백업";
          fallbackPolling();
        };
      } else {
        fallbackPolling();
      }
    }

    let pollingTimer = null;
    async function fallbackPolling() {
      if (pollingTimer) return;
      pollingTimer = setInterval(async () => {
        try {
          const res = await fetch('/api/data');
          const data = await res.json();
          courseMap.clear();
          (data.courses || []).forEach(c => {
            courseMap.set(c.full_code, c);
            if (c.seats > 0) {
              if (isInitialized && !knownOpenKeys.has(c.full_code)) {
                triggerAlertForCourse(c);
              }
              knownOpenKeys.add(c.full_code);
            } else {
              knownOpenKeys.delete(c.full_code);
            }
          });
          updateStatsUI(data.stats);
          renderEvents(data.events);
          renderCourses();
        } catch (e) {
          console.error("Polling error:", e);
        }
      }, 3000);
    }

    async function loadInitialData() {
      try {
        const res = await fetch('/api/data');
        const data = await res.json();
        if (data && data.courses) {
          courseMap.clear();
          data.courses.forEach(c => {
            courseMap.set(c.full_code, c);
            if (c.seats > 0) knownOpenKeys.add(c.full_code);
          });
          eventsList = data.events || [];
          updateStatsUI(data.stats);
          renderEvents(eventsList);
          renderCourses();
          isInitialized = true;
        }
      } catch (e) {
        console.error("Initial load error:", e);
      }
    }

    function init() {
      initSettings();
      loadInitialData();
      initSSE();
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  </script>
</body>
</html>"""

@app.head("/")
@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_CONTENT)


def main():
    port = int(os.environ.get("PORT", 8888))
    logger.info(f"🌐 Daejin Sugang High-Perf SSE Observer starting on http://0.0.0.0:{port}...")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
