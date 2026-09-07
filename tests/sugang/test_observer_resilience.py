import copy
import json
import unittest
from unittest.mock import patch

import web_observer as observer


class ObserverResilienceTests(unittest.TestCase):
    def setUp(self):
        self.course_db = copy.deepcopy(observer.course_db)
        self.event_history = copy.deepcopy(observer.event_history)
        self.stats = copy.deepcopy(observer.stats)
        self.cached_json_response = observer.cached_json_response
        self.save_state_cache = observer.save_state_cache
        observer.save_state_cache = lambda: None

    def tearDown(self):
        observer.course_db.clear()
        observer.course_db.update(self.course_db)
        observer.event_history[:] = self.event_history
        observer.stats.clear()
        observer.stats.update(self.stats)
        observer.cached_json_response = self.cached_json_response
        observer.save_state_cache = self.save_state_cache

    def test_failed_scrape_preserves_cached_courses_and_last_success(self):
        cached_course = {
            "full_code": "12345601",
            "code": "123456",
            "bun": "01",
            "name": "캐시강좌",
            "enrolled": 39,
            "seats": 1,
            "last_updated": "18:43:59",
        }
        observer.course_db.clear()
        observer.course_db[cached_course["full_code"]] = copy.deepcopy(cached_course)
        observer.event_history[:] = []
        observer.stats.clear()
        observer.stats.update({
            "total_courses": 1,
            "open_courses": 1,
            "events_count": 0,
            "last_scraped_at": "18:43:59",
            "scrape_latency_ms": 125.0,
            "status": "Live Streaming",
        })

        crawler = object.__new__(observer.CourseCrawler)
        crawler.scrape_targets = [{"url": "https://upstream.invalid/courses", "name": "테스트"}]
        crawler.ensure_session = lambda: False
        crawler.reload_targets = lambda: None
        crawler.fetch_url = lambda _url: ""

        result = crawler.scrape_cycle()
        payload = json.loads(observer.cached_json_response.decode("utf-8"))

        self.assertEqual(observer.course_db[cached_course["full_code"]]["seats"], 1)
        self.assertEqual(observer.stats["open_courses"], 1)
        self.assertEqual(observer.stats["last_scraped_at"], "18:43:59")
        self.assertEqual(observer.stats["status"], "Upstream Unavailable · Cached Data")
        self.assertEqual(result["changes"], [])
        self.assertEqual(payload["courses"][0]["name"], "캐시강좌")
        self.assertEqual(payload["stats"]["status"], "Upstream Unavailable · Cached Data")

    def test_failed_login_skips_course_requests(self):
        observer.course_db.clear()
        observer.event_history[:] = []
        observer.stats.clear()
        observer.stats.update({
            "total_courses": 0,
            "open_courses": 0,
            "events_count": 0,
            "last_scraped_at": "-",
            "scrape_latency_ms": 0,
            "status": "Initializing",
        })

        crawler = object.__new__(observer.CourseCrawler)
        crawler.scrape_targets = [{"url": "https://upstream.invalid/courses", "name": "테스트"}]
        crawler.ensure_session = lambda: False
        crawler.reload_targets = lambda: None
        fetch_calls = []

        def record_fetch(url):
            fetch_calls.append(url)
            return ""

        crawler.fetch_url = record_fetch
        crawler.scrape_cycle()

        self.assertEqual(fetch_calls, [])

    def test_session_retry_waits_until_backoff_deadline(self):
        crawler = object.__new__(observer.CourseCrawler)
        crawler.last_login_time = 0
        crawler.next_login_retry_time = 800
        login_calls = []
        crawler.login = lambda: login_calls.append(True) or False

        original_time = observer.time.time
        observer.time.time = lambda: 700
        try:
            ready = crawler.ensure_session()
        finally:
            observer.time.time = original_time

        self.assertFalse(ready)
        self.assertEqual(login_calls, [])

    def test_login_failure_schedules_retry_backoff(self):
        class FailingSession:
            def post(self, *_args, **_kwargs):
                raise observer.requests.ConnectTimeout("upstream timeout")

        crawler = object.__new__(observer.CourseCrawler)
        crawler.session = FailingSession()
        crawler.std_no = "test"
        crawler.passwd = "test"
        crawler.user_flag = "1"
        crawler.last_login_time = 0
        crawler.next_login_retry_time = 0
        crawler.login_failures = 0

        original_time = observer.time.time
        observer.time.time = lambda: 1000
        try:
            ready = crawler.login()
        finally:
            observer.time.time = original_time

        self.assertFalse(ready)
        self.assertEqual(crawler.login_failures, 1)
        self.assertEqual(crawler.next_login_retry_time, 2800)

    def test_failed_scrape_repairs_false_success_timestamp_from_course_cache(self):
        observer.course_db.clear()
        observer.course_db["12345601"] = {
            "full_code": "12345601",
            "code": "123456",
            "bun": "01",
            "name": "캐시강좌",
            "enrolled": 39,
            "seats": 1,
            "last_updated": "18:43:59",
        }
        observer.event_history[:] = []
        observer.stats.clear()
        observer.stats.update({
            "total_courses": 1,
            "open_courses": 0,
            "events_count": 0,
            "last_scraped_at": "19:39:41",
            "scrape_latency_ms": 7000,
            "status": "Live Streaming",
        })

        crawler = object.__new__(observer.CourseCrawler)
        crawler.scrape_targets = []
        crawler.ensure_session = lambda: False
        crawler.reload_targets = lambda: None
        crawler.fetch_url = lambda _url: ""
        crawler.scrape_cycle()

        self.assertEqual(observer.stats["last_scraped_at"], "18:43:59")

    def test_successful_scrape_clears_degraded_failure_state(self):
        observer.course_db.clear()
        observer.event_history[:] = []
        observer.stats.clear()
        observer.stats.update({
            "total_courses": 1,
            "open_courses": 1,
            "events_count": 0,
            "last_scraped_at": "18:43:59",
            "scrape_latency_ms": 7000,
            "status": "Upstream Unavailable · Cached Data",
            "consecutive_failures": 4,
        })
        html = """
        <table><tr>
          <td>1</td><td>123456-01</td><td>-</td><td>복구강좌</td><td>교수</td>
          <td>월10:00</td><td>전선</td><td>39</td><td>1</td><td>3</td><td>강의실</td><td></td>
        </tr></table>
        """
        crawler = object.__new__(observer.CourseCrawler)
        crawler.scrape_targets = [{"url": "https://upstream.invalid/courses", "name": "테스트"}]
        crawler.ensure_session = lambda: True
        crawler.reload_targets = lambda: None
        crawler.fetch_url = lambda url: html

        crawler.scrape_cycle()

        self.assertEqual(observer.stats["status"], "Live Streaming")
        self.assertEqual(observer.stats["consecutive_failures"], 0)

    def test_ui_exposes_upstream_degraded_state(self):
        self.assertIn("원본 서버 장애 · 캐시", observer.HTML_CONTENT)
        self.assertIn("Upstream Unavailable", observer.HTML_CONTENT)

    def test_crawler_applies_configured_proxy_only_to_upstream_session(self):
        proxy_url = "socks5h://127.0.0.1:18088"
        with patch.dict(
            observer.os.environ,
            {
                "DAEJIN_UPSTREAM_PROXY": proxy_url,
                "HTTPS_PROXY": "http://must-not-be-inherited.invalid:9999",
            },
            clear=False,
        ):
            crawler = observer.CourseCrawler()

        self.assertEqual(crawler.session.proxies, {
            "http": proxy_url,
            "https": proxy_url,
        })
        self.assertFalse(crawler.session.trust_env)

    def test_upstream_rate_limits_are_conservative(self):
        self.assertGreaterEqual(observer.SCRAPE_LOOP_INTERVAL_SECONDS, 10)
        self.assertLessEqual(observer.SCRAPE_MAX_WORKERS, 4)
        self.assertGreaterEqual(observer.LOGIN_RETRY_BASE_SECONDS, 1800)
        self.assertGreaterEqual(observer.LOGIN_RETRY_MAX_SECONDS, 3600)

    def test_login_backoff_caps_at_one_hour(self):
        crawler = object.__new__(observer.CourseCrawler)
        crawler.login_failures = 0
        crawler.next_login_retry_time = 0
        original_time = observer.time.time
        observer.time.time = lambda: 1000
        try:
            crawler._schedule_login_retry()
            self.assertEqual(crawler.next_login_retry_time, 2800)
            crawler.login_failures = 10
            crawler._schedule_login_retry()
            self.assertEqual(crawler.next_login_retry_time, 4600)
        finally:
            observer.time.time = original_time


if __name__ == "__main__":
    unittest.main()
