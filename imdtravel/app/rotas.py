import os
import tempfile
import time
from flask import Flask, jsonify
from app.config import SALES_DIR

app = Flask(__name__)
_START_TIME = time.monotonic()


def _check_sales_dir() -> tuple[bool, str]:
    if not os.path.exists(SALES_DIR):
        return False, "sales_dir_missing"
    if not os.path.isdir(SALES_DIR):
        return False, "sales_dir_not_directory"
    try:
        with tempfile.NamedTemporaryFile(dir=SALES_DIR, prefix=".health_", delete=True):
            pass
    except OSError:
        return False, "sales_dir_not_writable"
    return True, ""


@app.get("/health")
def health():
    ok, reason = _check_sales_dir()
    if not ok:
        return jsonify({"status": "down", "reason": reason}), 503

    uptime_s = int(time.monotonic() - _START_TIME)
    return jsonify({"status": "ok", "uptimeS": uptime_s}), 200
