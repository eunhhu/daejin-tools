#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daejin Sugang Observer - Cross-Platform Web Push Notification Manager (RFC 8292 / VAPID)
========================================================================================
Supports: Desktop Chrome, Firefox, Edge, Safari (macOS), Android Chrome, iOS Safari (PWA)
"""

import os
import json
import logging
import threading
from pywebpush import webpush, WebPushException
from py_vapid import Vapid
from py_vapid.utils import b64urlencode
import cryptography.hazmat.primitives.serialization as serial

logger = logging.getLogger("WebPushManager")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VAPID_FILE = os.path.join(BASE_DIR, "vapid_keys.json")
VAPID_PRIVATE_FILE = os.path.join(BASE_DIR, "vapid_private.pem")
SUBS_FILE = os.path.join(BASE_DIR, "push_subs.json")

class WebPushManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.vapid_keys = self._load_or_create_vapid()
        self._sync_private_key_file()
        self.subscriptions = self._load_subscriptions()

    def _sync_private_key_file(self):
        private_pem = self.vapid_keys["private_pem"]
        current = None
        try:
            with open(VAPID_PRIVATE_FILE, "r", encoding="utf-8") as f:
                current = f.read()
        except FileNotFoundError:
            pass
        if current != private_pem:
            temp_path = VAPID_PRIVATE_FILE + ".tmp"
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(private_pem)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, VAPID_PRIVATE_FILE)
        else:
            os.chmod(VAPID_PRIVATE_FILE, 0o600)
        return VAPID_PRIVATE_FILE

    def _load_or_create_vapid(self):
        if os.path.exists(VAPID_FILE):
            try:
                with open(VAPID_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read VAPID file: {e}. Regenerating...")

        v = Vapid()
        v.generate_keys()
        priv_pem = v.private_pem().decode("utf-8")
        raw_pub = v.public_key.public_bytes(
            encoding=serial.Encoding.X962,
            format=serial.PublicFormat.UncompressedPoint
        )
        pub_b64 = b64urlencode(raw_pub)
        data = {
            "private_pem": priv_pem,
            "public_key": pub_b64,
            "claims_sub": "mailto:eunhhuu@gmail.com"
        }
        with open(VAPID_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.info("🔑 Generated and saved new VAPID Web Push keypair.")
        return data

    def _load_subscriptions(self):
        if os.path.exists(SUBS_FILE):
            try:
                with open(SUBS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load subscriptions: {e}")
        return {}

    def _save_subscriptions(self):
        try:
            with open(SUBS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save subscriptions: {e}")

    def get_public_key(self):
        return self.vapid_keys["public_key"]

    def add_subscription(self, sub_data, starred_courses=None, alert_mode="ALL_OPEN"):
        with self.lock:
            endpoint = sub_data.get("endpoint")
            if not endpoint:
                return False
            self.subscriptions[endpoint] = {
                "subscription": sub_data,
                "starred_courses": starred_courses or [],
                "alert_mode": alert_mode,
                "updated_at": os.getenv("TZ", "")
            }
            self._save_subscriptions()
            logger.info(f"✅ Registered new Web Push client (Total: {len(self.subscriptions)})")
            return True

    def remove_subscription(self, endpoint):
        with self.lock:
            if endpoint in self.subscriptions:
                del self.subscriptions[endpoint]
                self._save_subscriptions()
                logger.info(f"🗑️ Unregistered Web Push client (Total: {len(self.subscriptions)})")
                return True
        return False

    def update_preferences(self, endpoint, starred_courses=None, alert_mode=None):
        with self.lock:
            if endpoint in self.subscriptions:
                if starred_courses is not None:
                    self.subscriptions[endpoint]["starred_courses"] = starred_courses
                if alert_mode is not None:
                    self.subscriptions[endpoint]["alert_mode"] = alert_mode
                self._save_subscriptions()
                return True
        return False

    def send_push(self, sub_info, payload):
        try:
            webpush(
                subscription_info=sub_info,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=self._sync_private_key_file(),
                vapid_claims={"sub": self.vapid_keys.get("claims_sub", "mailto:admin@qucord.com")},
                timeout=5
            )
            return True, "OK"
        except WebPushException as ex:
            # 404 or 410 means subscription expired or uninstalled
            status = getattr(ex.response, 'status_code', None)
            if status in (404, 410):
                endpoint = sub_info.get("endpoint")
                if endpoint:
                    self.remove_subscription(endpoint)
                return False, "EXPIRED"
            logger.warning(f"WebPush delivery warning: {ex}")
            return False, str(ex)
        except Exception as e:
            logger.warning(f"WebPush unexpected error: {e}")
            return False, str(e)

    def broadcast_vacancy_event(self, event):
        """
        Dispatches web push alerts to all matching client devices in background.
        """
        course_name = event.get("name", "수강 교과목")
        full_code = event.get("full_code", "")
        code = event.get("code", "")
        bun = event.get("bun", "")
        seats = event.get("new_seats", event.get("seats", 1))
        prof = event.get("prof", "-")
        time_str = event.get("time", "-")

        payload = {
            "title": f"🔥 [빈자리 발생!] {course_name}",
            "body": f"{course_name} ({code}-{bun}) {seats}자리 오픈!\n교수: {prof} | 시간: {time_str}",
            "icon": "https://www.daejin.ac.kr/favicon.ico",
            "badge": "https://www.daejin.ac.kr/favicon.ico",
            "tag": f"vacancy-{full_code}",
            "url": "https://daejin.qucord.com",
            "data": {
                "url": "https://daejin.qucord.com",
                "code": code,
                "bun": bun,
                "full_code": full_code
            }
        }

        with self.lock:
            active_list = list(self.subscriptions.values())

        if not active_list:
            return 0

        sent_count = 0
        for item in active_list:
            sub = item.get("subscription")
            starred = set(item.get("starred_courses", []))
            mode = item.get("alert_mode", "ALL_OPEN")

            if mode == "MUTED":
                continue
            if mode == "STARRED_ONLY" and full_code not in starred:
                continue

            success, msg = self.send_push(sub, payload)
            if success:
                sent_count += 1

        if sent_count > 0:
            logger.info(f"📢 Broadcasted Web Push to {sent_count} background devices for {course_name} ({full_code})")
        return sent_count


push_mgr = WebPushManager()
