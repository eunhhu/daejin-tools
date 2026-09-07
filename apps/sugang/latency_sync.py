#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin University Server Latency & Time Synchronizer
====================================================
Measures precise network round-trip time (RTT) and calculates microsecond server clock offset.
"""

import time
import datetime
import requests

LOGIN_PAGE_URL = "https://dreams2.daejin.ac.kr/sugang/new/loginForm.jsp"


def measure_server_metrics(samples=10):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    latencies = []
    offsets = []

    print(f"📡 Pinging {LOGIN_PAGE_URL} ({samples} samples)...")
    for i in range(samples):
        t0 = time.perf_counter()
        try:
            r = session.head(LOGIN_PAGE_URL, headers=headers, timeout=3)
            t1 = time.perf_counter()
            rtt_ms = (t1 - t0) * 1000
            latencies.append(rtt_ms)

            server_date = r.headers.get("Date")
            if server_date:
                server_dt = datetime.datetime.strptime(server_date, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=datetime.timezone.utc)
                local_dt = datetime.datetime.now(datetime.timezone.utc)
                offset = (server_dt - local_dt).total_seconds() + (rtt_ms / 2000.0)
                offsets.append(offset)
                print(f"  Sample #{i+1:02d}: RTT = {rtt_ms:5.1f}ms | Server Date = {server_date} | Offset = {offset:+.3f}s")
            else:
                print(f"  Sample #{i+1:02d}: RTT = {rtt_ms:5.1f}ms")
        except Exception as e:
            print(f"  Sample #{i+1:02d}: Failed ({e})")
        time.sleep(0.1)

    if latencies:
        min_rtt = min(latencies)
        avg_rtt = sum(latencies) / len(latencies)
        max_rtt = max(latencies)
        avg_offset = sum(offsets) / len(offsets) if offsets else 0.0
        
        print("\n" + "=" * 50)
        print(f"📊 [결과 요약]")
        print(f"• 최소 RTT (Min): {min_rtt:.1f}ms (편도: {min_rtt/2:.1f}ms)")
        print(f"• 평균 RTT (Avg): {avg_rtt:.1f}ms (편도: {avg_rtt/2:.1f}ms)")
        print(f"• 최대 RTT (Max): {max_rtt:.1f}ms")
        print(f"• 서버 시계 오차 (Offset): {avg_offset:+.3f}초")
        print("=" * 50)


if __name__ == "__main__":
    measure_server_metrics()
