import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def pytest_runtest_logreport(report):
    """No GitHub Actions, cada falha vira uma anotação legível pela API."""
    if not os.environ.get("GITHUB_ACTIONS") or not report.failed:
        return
    path, line, _ = report.location
    message = str(report.longrepr).strip().splitlines()
    text = " | ".join(message[-12:]).replace("%", "%25").replace("\r", "").replace("\n", " ")
    print(f"\n::error file={path},line={(line or 0) + 1},title={report.nodeid}::{text[:3000]}", flush=True)
