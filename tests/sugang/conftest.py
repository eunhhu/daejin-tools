"""Import unchanged legacy modules from a disposable, credential-free copy."""

import shutil
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "sugang"


def pytest_configure(config):
    sandbox = tempfile.TemporaryDirectory(prefix="daejin-sugang-tests-")
    config._sugang_test_sandbox = sandbox
    directory = Path(sandbox.name)
    for name in ("web_observer.py", "push_manager.py"):
        shutil.copy2(APP_DIR / name, directory / name)
    # Empty test-only inputs: never read real credentials or monitoring targets.
    (directory / "config.json").write_text("{}", encoding="utf-8")
    (directory / "targets.json").write_text("[]", encoding="utf-8")
    sys.path.insert(0, sandbox.name)


def pytest_unconfigure(config):
    sandbox = getattr(config, "_sugang_test_sandbox", None)
    if sandbox is None:
        return
    for name in ("web_observer", "push_manager"):
        module = sys.modules.get(name)
        if module is not None and Path(module.__file__ or "").parent == Path(sandbox.name):
            del sys.modules[name]
    if sandbox.name in sys.path:
        sys.path.remove(sandbox.name)
    sandbox.cleanup()
