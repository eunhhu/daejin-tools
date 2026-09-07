#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Course Registration CLI Master Tool (대진대학교 수강신청 통합 자동화 도구)
======================================================================================
Usage:
  python3 sugang.py status                  : 현재 확정 수강신청 목록 및 취득/신청학점 조회
  python3 sugang.py cart                    : 예비수강 장바구니 목록 및 실시간 여석 조회
  python3 sugang.py search <keyword>        : 전공/교양 전체 과목 실시간 검색 (과목명, 교수명, 학수번호)
  python3 sugang.py open [category]         : 현재 빈자리(여석 > 0) 있는 과목 목록 필터링
  python3 sugang.py dept <학과명/코드>     : 특정 학과 전공과목 실시간 조회 (예: 경영학과, 컴공, 보안)
  python3 sugang.py apply <과목번호> <분반> : 단일 과목 즉시 초고속 수강신청 (패킷 직전송)
  python3 sugang.py cancel <과목번호> <분반>: 수강신청 확정 과목 즉시 취소
  python3 sugang.py hunt <과목번호> <분반>  : 취소표 발생 시 0.01초 즉시 주워담기 (Vacancy Hunter)
  python3 sugang.py swap <버릴과목> <잡을과목>: 원자적 수강 교환 (목표과목 빈자리 감지 시 즉시 교체)
  python3 sugang.py sync                    : 대진대 서버 정밀 시계 오차(ms) 및 왕복 지연시간(RTT) 측정
  python3 sugang.py snipe                   : 10:00:00 정각 밀리초 단위 초고속 일괄 자동신청 (Sniper)
"""

import os
import sys
import time
import json
import re
import argparse
import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
BASE_URL = "https://dreams2.daejin.ac.kr"
LOGIN_API_URL = f"{BASE_URL}/sugang/NLoginB"
APPLY_API_URL = f"{BASE_URL}/sugang/NSugangWlsn0410"
CHECK_APPLY_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04110.jsp"
CART_URL = f"{BASE_URL}/sugang/new/sugang_wlsn04120.jsp"
GE_QUERY_URL = f"{BASE_URL}/sugang/new/sugang_wlsn0417_2.jsp"
MAJOR_QUERY_URL = f"{BASE_URL}/sugang/new/sugang_wlsn0417_3.jsp"
OTHER_MAJOR_URL = f"{BASE_URL}/sugang/new/sugang_wlsn0417_1.jsp"

# Department Code Mapping
DEPT_MAP = {
    "경영학과": "AA0242", "경영": "AA0242",
    "컴퓨터공학전공": "AA0194", "컴퓨터공학과": "AA0194", "컴공": "AA0194",
    "AI빅데이터전공": "AA0816", "AI빅데이터": "AA0816", "인공지능": "AA0816",
    "스마트융합보안학과": "AA0829", "보안학과": "AA0829", "보안": "AA0829",
    "미디어커뮤니케이션학과": "AA0245", "미컴": "AA0245",
    "글로벌경제학과": "AA0241", "경제학과": "AA0241",
    "국제통상학과": "AA0243", "국통": "AA0243",
    "공공인재법학과": "AA0239", "법학과": "AA0239",
    "행정정보학과": "AA0240", "행정": "AA0240",
    "사회복지학과": "AA0244", "사복": "AA0244",
    "전자공학과": "AA0726", "전자": "AA0726",
    "전기공학과": "AA0049", "전기": "AA0049",
    "화학공학과": "AA0058", "화공": "AA0058",
    "간호학과": "AA0469", "간호": "AA0469",
    "식품영양학과": "AA0315", "식영": "AA0315",
    "스포츠건강과학과": "AA0364", "스건": "AA0364",
    "시각디자인학과": "AA0293", "시디": "AA0293",
    "산업디자인학과": "AA0294", "산디": "AA0294",
    "영화영상학과": "AA0317", "영화": "AA0317",
    "연기예술학과": "AA0318", "연기": "AA0318",
    "실용음악학과": "AA0813", "실음": "AA0813",
    "영어영문학과": "AA0101", "영문": "AA0101",
    "한국어문학과": "AA0131", "국문": "AA0131"
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"❌ 설정 파일({CONFIG_PATH})이 없습니다. config.example.json을 복사해 생성하세요.")
        sys.exit(1)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_session():
    cfg = load_config()
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": f"{BASE_URL}/sugang/new/main.jsp",
        "Origin": BASE_URL
    })
    r = s.post(LOGIN_API_URL, data={
        "stdNo": cfg["stdNo"],
        "passwd": cfg["passwd"],
        "user_flag": cfg.get("user_flag", "1")
    }, timeout=5)
    text = r.content.decode("euc-kr", "replace")
    if "main.jsp" in text or "location.href" in text or r.status_code == 200:
        return s, cfg
    raise RuntimeError("❌ 대진대 포털 로그인 실패! 학번과 비밀번호를 확인하세요.")


def parse_course_table(html, category=""):
    courses = []
    soup = BeautifulSoup(html, "html.parser")
    for tr in soup.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) >= 10 and "-" in cols[1] and len(cols[1]) == 9 and cols[1] != "교과번호-분반":
            code_parts = cols[1].split("-")
            enrolled = int(cols[7]) if cols[7].isdigit() else 0
            seats = int(cols[8]) if cols[8].isdigit() else 0
            courses.append({
                "code": code_parts[0],
                "bun": code_parts[1],
                "full_code": f"{code_parts[0]}{code_parts[1]}",
                "name": cols[3],
                "prof": cols[4],
                "time": cols[5],
                "type": cols[6] if len(cols) > 6 else "",
                "enrolled": enrolled,
                "seats": seats,
                "credits": cols[9] if len(cols) > 9 else "2",
                "room": cols[10] if len(cols) > 10 else "",
                "remarks": cols[11] if len(cols) > 11 else "",
                "category": category
            })
    return courses


# ==============================================================================
# Command: status (현재 확정 수강신청 내역)
# ==============================================================================
def cmd_status(args):
    s, cfg = get_session()
    print(f"\n📋 [대진대학교 2026-2학기 확정 수강신청 목록] (학번: {cfg['stdNo']})")
    print("=" * 85)
    r = s.get(CHECK_APPLY_URL)
    soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
    
    # Check student info
    info_dls = soup.find_all("dl")
    info_dict = {}
    for dl in info_dls:
        dt = dl.find("dt")
        dd = dl.find("dd")
        if dt and dd:
            info_dict[dt.get_text(strip=True)] = dd.get_text(strip=True)
    if info_dict:
        print(f"👤 {info_dict.get('성명', '')} ({info_dict.get('학과', '')} / {info_dict.get('학년', '')}학년) | 신청학점: {info_dict.get('취득학점', '')} / 가능: {info_dict.get('신청가능학점', '')}")
        print("-" * 85)

    rows = []
    for tr in soup.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) >= 8 and "-" in cols[1] and len(cols[1]) == 9:
            rows.append(cols)

    if not rows:
        print("  * 현재 확정 신청된 과목이 없습니다.")
    else:
        print(f"{'학수-분반':<12} {'교과목명':<25} {'담당교수':<10} {'강의시간':<20} {'이수':<6} {'학점':<4}")
        print("-" * 85)
        for row in rows:
            print(f"{row[1]:<12} {row[3]:<25} {row[4]:<10} {row[5]:<20} {row[6]:<6} {row[8]:<4}")
    print("=" * 85 + "\n")


# ==============================================================================
# Command: cart (예비수강 장바구니 조회)
# ==============================================================================
def cmd_cart(args):
    s, cfg = get_session()
    print(f"\n🛒 [예비수강 장바구니 목록 및 실시간 여석] (학번: {cfg['stdNo']})")
    print("=" * 90)
    r = s.get(CART_URL)
    soup = BeautifulSoup(r.content.decode("euc-kr", "replace"), "html.parser")
    
    rows = []
    for tr in soup.find_all("tr"):
        cols = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cols) >= 9 and "-" in cols[1] and len(cols[1]) == 9:
            rows.append(cols)

    if not rows:
        print("  * 장바구니에 담긴 과목이 없습니다.")
    else:
        print(f"{'학수-분반':<12} {'교과목명':<25} {'담당교수':<10} {'강의시간':<20} {'신청/여석':<10} {'상태':<8}")
        print("-" * 90)
        for row in rows:
            seats = row[8] if len(row) > 8 else "0"
            enrolled = row[7] if len(row) > 7 else "0"
            is_open = int(seats) > 0 if seats.isdigit() else False
            status = "🔥 OPEN" if is_open else "⏳ 마감"
            print(f"{row[1]:<12} {row[3]:<25} {row[4]:<10} {row[5]:<20} {enrolled}/{seats:<8} {status:<8}")
    print("=" * 90 + "\n")


# ==============================================================================
# Command: search & open (실시간 강좌 검색 & 빈자리 필터)
# ==============================================================================
def fetch_all_active_courses(session):
    targets = [
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_3.jsp", "스마트융합보안 전공"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_1.jsp?ic_kwa=B41005&ic_kwa_1=AA0242", "경영학과 전공"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41001&ppage=1", "교양필수"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42001&ppage=1", "교선 1영역(인간과소통)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42002&ppage=1", "교선 2영역(사회와경제)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42003&ppage=1", "교선 3영역(과학과기술)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42004&ppage=1", "교선 4영역(예술과문화)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42005&ppage=1", "교선 5영역(융합과혁신)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41002&ic_kwa_1=B42006&ppage=1", "교선 6영역(AI·디지털)"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_4.jsp", "교직"),
        ("https://dreams2.daejin.ac.kr/sugang/new/sugang_wlsn0417_2.jsp?ic_kwa=B41020&ppage=1", "일반선택"),
    ]
    all_courses = []
    
    def fetch_target(t):
        url, cat = t
        try:
            r = session.get(url, timeout=4)
            html = r.content.decode("euc-kr", "replace")
            c_list = parse_course_table(html, cat)
            
            # Check pagination
            soup = BeautifulSoup(html, "html.parser")
            pag = soup.find("div", class_="pagination")
            if pag:
                pages = re.findall(r"setPage\(\x27(\d+)\x27\)", str(pag))
                if pages:
                    max_p = max(int(p) for p in pages)
                    for p in range(2, max_p + 1):
                        p_url = re.sub(r"ppage=\d+", f"ppage={p}", url)
                        if "ppage=" not in p_url:
                            p_url += f"?ppage={p}" if "?" not in p_url else f"&ppage={p}"
                        pr = session.get(p_url, timeout=4)
                        c_list.extend(parse_course_table(pr.content.decode("euc-kr", "replace"), cat))
            return c_list
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=12) as ex:
        results = ex.map(fetch_target, targets)
        for r in results:
            all_courses.extend(r)
    return {c["full_code"]: c for c in all_courses}.values()


def cmd_search(args):
    kw = args.keyword.strip().lower()
    s, _ = get_session()
    print(f"\n🔍 [실시간 과목 검색: '{kw}']")
    courses = list(fetch_all_active_courses(s))
    
    matched = [c for c in courses if kw in c["name"].lower() or kw in c["prof"].lower() or kw in c["full_code"] or kw in c["category"].lower() or kw in c["time"].lower()]
    matched.sort(key=lambda x: x["seats"], reverse=True)

    print(f"총 {len(matched)}개 강좌 발견\n" + "=" * 95)
    print(f"{'상태':<8} {'학수-분반':<12} {'교과목명':<25} {'담당교수':<10} {'강의시간':<20} {'신청/여석':<10} {'영역/학과':<15}")
    print("-" * 95)
    for c in matched:
        status = f"🔥 {c['seats']}석" if c['seats'] > 0 else "마감"
        print(f"{status:<8} {c['code']}-{c['bun']:<10} {c['name']:<25} {c['prof']:<10} {c['time']:<20} {c['enrolled']}/{c['seats']:<8} {c['category']:<15}")
    print("=" * 95 + "\n")


def cmd_open(args):
    s, _ = get_session()
    print("\n🔥 [실시간 신청 가능(여석 > 0) 빈자리 강좌 목록]")
    courses = list(fetch_all_active_courses(s))
    open_courses = [c for c in courses if c["seats"] > 0]
    if args.category:
        cat_kw = args.category.strip().lower()
        open_courses = [c for c in open_courses if cat_kw in c["category"].lower()]

    open_courses.sort(key=lambda x: x["seats"], reverse=True)
    print(f"총 {len(open_courses)}개 잔여석 강좌 발견\n" + "=" * 95)
    print(f"{'여석':<8} {'학수-분반':<12} {'교과목명':<25} {'담당교수':<10} {'강의시간':<20} {'신청/여석':<10} {'영역/학과':<15}")
    print("-" * 95)
    for c in open_courses:
        print(f"🔥 {c['seats']:<5} {c['code']}-{c['bun']:<10} {c['name']:<25} {c['prof']:<10} {c['time']:<20} {c['enrolled']}/{c['seats']:<8} {c['category']:<15}")
    print("=" * 95 + "\n")


# ==============================================================================
# Command: dept (특정 학과 전공 실시간 조회)
# ==============================================================================
def cmd_dept(args):
    dept_name = args.dept_name.strip()
    org_cd = DEPT_MAP.get(dept_name, dept_name if dept_name.startswith("AA") else None)
    
    s, _ = get_session()
    if not org_cd:
        # Search dynamically from other major page
        r = s.get(OTHER_MAJOR_URL)
        m2 = re.search(r"let selectList2\s*=\s*\[(.*?)\];", r.content.decode("euc-kr", "replace"), re.DOTALL)
        if m2:
            items = re.findall(r"\{\x27int_cd1\x27:\x27(.*?)\x27,\x27cd_nm\x27:\x27(.*?)\x27,\x27org_cd\x27:\x27(.*?)\x27\}", m2.group(1))
            for int_cd, nm, cd in items:
                if dept_name in nm:
                    dept_name = nm
                    org_cd = cd
                    break

    if not org_cd:
        print(f"❌ 학과명 '{dept_name}'을 찾을 수 없습니다. (예: 경영학과, 컴공, 보안, 전자, 간호 등)")
        return

    url = f"{OTHER_MAJOR_URL}?ic_kwa=B41005&ic_kwa_1={org_cd}&ppage=1"
    r = s.get(url)
    courses = parse_course_table(r.content.decode("euc-kr", "replace"), f"{dept_name} 전공")
    courses.sort(key=lambda x: x["seats"], reverse=True)

    print(f"\n📚 [{dept_name} 개설 전공강좌 및 실시간 잔여석] (총 {len(courses)}개)")
    print("=" * 95)
    print(f"{'상태':<8} {'학수-분반':<12} {'교과목명':<25} {'담당교수':<10} {'강의시간':<20} {'신청/여석':<10} {'학점':<4}")
    print("-" * 95)
    for c in courses:
        status = f"🔥 {c['seats']}석" if c['seats'] > 0 else "마감"
        print(f"{status:<8} {c['code']}-{c['bun']:<10} {c['name']:<25} {c['prof']:<10} {c['time']:<20} {c['enrolled']}/{c['seats']:<8} {c['credits']:<4}")
    print("=" * 95 + "\n")


# ==============================================================================
# Command: apply (단일 과목 즉각 고속 신청)
# ==============================================================================
def cmd_apply(args):
    code = args.code.strip()
    bun = args.bun.strip().zfill(2)
    s, cfg = get_session()
    print(f"⚡ 과목 [{code}-{bun}] 고속 수강신청 전송 중...")
    t0 = time.perf_counter()
    r = s.post(APPLY_API_URL, data={
        "dir": "1", "cmd": "aply", "urltype": "direct",
        "getsbjt_no": code, "getclss_no": bun, "ic_sbjcd": f"{code}{bun}"
    }, timeout=4)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text = r.content.decode("euc-kr", "replace")
    
    alert_msg = ""
    for line in text.split("\n"):
        if "alert(" in line:
            alert_msg = line.split("alert(")[1].split(")")[0].strip("\"'\\r\\n")
            break
    print(f"⏱ 응답 시간: {elapsed_ms:.1f}ms")
    print(f"📢 서버 응답: {alert_msg or '정상 처리'}")


# ==============================================================================
# Command: sync (서버 타임 및 레이턴시 정밀 측정)
# ==============================================================================
def cmd_sync(args):
    s, _ = get_session()
    print("🕒 대진대 수강신청 서버 정밀 시계 동기화 측정 중...")
    rtts = []
    offsets = []
    for i in range(5):
        t0 = time.perf_counter()
        r = s.head(f"{BASE_URL}/sugang/new/loginForm.jsp", timeout=3)
        t1 = time.perf_counter()
        rtt_ms = (t1 - t0) * 1000
        rtts.append(rtt_ms)
        date_hdr = r.headers.get("Date")
        if date_hdr:
            srv_dt = datetime.datetime.strptime(date_hdr, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=datetime.timezone.utc)
            loc_dt = datetime.datetime.now(datetime.timezone.utc)
            offset = (srv_dt - loc_dt).total_seconds()
            offsets.append(offset)
            print(f"  [시도 {i+1}] RTT: {rtt_ms:.1f}ms | 서버 Offset: {offset:+.3f}s")
        time.sleep(0.1)

    avg_rtt = sum(rtts) / len(rtts)
    avg_offset = sum(offsets) / len(offsets) if offsets else 0.0
    print("-" * 50)
    print(f"📶 평균 RTT: {avg_rtt:.1f}ms (편도 지연시간: {avg_rtt/2:.1f}ms)")
    print(f"⏱ 평균 시계 오차: {avg_offset:+.3f}초")
    print("=" * 50)


# ==============================================================================
# Main CLI Router
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="대진대학교 수강신청 마스터 자동화 CLI")
    subparsers = parser.add_subparsers(dest="command", help="실행할 명령")

    subparsers.add_parser("status", help="확정 수강신청 목록 및 학점 확인")
    subparsers.add_parser("cart", help="예비수강 장바구니 목록 및 실시간 잔여석")
    
    search_p = subparsers.add_parser("search", help="실시간 과목 검색")
    search_p.add_argument("keyword", help="검색 키워드 (과목명, 교수명, 학수번호)")

    open_p = subparsers.add_parser("open", help="실시간 빈자리 강좌만 조회")
    open_p.add_argument("category", nargs="?", default="", help="영역/학과 필터 (선택사항)")

    dept_p = subparsers.add_parser("dept", help="특정 학과 개설 전공강좌 실시간 조회")
    dept_p.add_argument("dept_name", help="학과명 (예: 경영학과, 컴공, 보안, 전자, 간호)")

    apply_p = subparsers.add_parser("apply", help="과목 즉시 수강신청")
    apply_p.add_argument("code", help="과목번호 6자리")
    apply_p.add_argument("bun", help="분반 2자리")

    subparsers.add_parser("sync", help="서버 타임 동기화 및 네트워크 레이턴시 측정")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    if args.command == "status":
        cmd_status(args)
    elif args.command == "cart":
        cmd_cart(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "open":
        cmd_open(args)
    elif args.command == "dept":
        cmd_dept(args)
    elif args.command == "apply":
        cmd_apply(args)
    elif args.command == "sync":
        cmd_sync(args)


if __name__ == "__main__":
    main()
