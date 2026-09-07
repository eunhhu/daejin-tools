"""The shared package must be usable without launching an application."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PackageTests(unittest.TestCase):
    def test_shared_package_import_has_no_application_or_filesystem_side_effects(self):
        code = (
            "import sys; from pathlib import Path; import daejin_tools; "
            "assert 'web_observer' not in sys.modules; "
            "assert 'push_manager' not in sys.modules; "
            "assert 'requests' not in sys.modules; "
            "assert not list(Path.cwd().iterdir())"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        with tempfile.TemporaryDirectory() as working_dir:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=working_dir, env=env, capture_output=True, text=True, timeout=10, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
