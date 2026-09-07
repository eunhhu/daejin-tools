"""Repository boundaries for independently evolving campus tools."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RepositoryLayoutTests(unittest.TestCase):
    def test_sugang_sources_and_resources_share_one_application_directory(self):
        files = (
            "atomic_swapper.py", "browser_sniper.py", "gui_qt.py",
            "latency_sync.py", "packet_sniper.py", "push_manager.py",
            "query_courses.py", "sugang.py", "vacancy_hunter.py",
            "web_observer.py", "config.example.json", "manifest.json",
            "sw.js", "targets.json", "requirements.txt",
        )
        for name in files:
            with self.subTest(file=name):
                self.assertTrue((ROOT / "apps" / "sugang" / name).is_file(), name)
                self.assertFalse((ROOT / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
