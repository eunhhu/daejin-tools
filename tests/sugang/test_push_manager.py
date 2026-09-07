import json
import os
import unittest
from pathlib import Path

import push_manager

PROJECT_ROOT = Path(push_manager.BASE_DIR)


class WebPushKeyTests(unittest.TestCase):
    def test_send_push_uses_matching_private_key_file(self):
        manager = object.__new__(push_manager.WebPushManager)
        manager.vapid_keys = json.loads((PROJECT_ROOT / "vapid_keys.json").read_text(encoding="utf-8"))
        captured = {}

        def fake_webpush(**kwargs):
            captured.update(kwargs)

        original_webpush = push_manager.webpush
        push_manager.webpush = fake_webpush
        try:
            success, message = manager.send_push(
                {"endpoint": "https://push.invalid/example", "keys": {"p256dh": "x", "auth": "y"}},
                {"title": "test"},
            )
        finally:
            push_manager.webpush = original_webpush

        self.assertTrue(success)
        self.assertEqual(message, "OK")
        private_key_arg = captured["vapid_private_key"]
        self.assertTrue(os.path.isfile(private_key_arg))
        self.assertEqual(
            Path(private_key_arg).read_text(encoding="utf-8"),
            manager.vapid_keys["private_pem"],
        )


if __name__ == "__main__":
    unittest.main()
