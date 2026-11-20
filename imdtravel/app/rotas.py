import os
import tempfile
import time
from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
from app.config import SALES_DIR
from app.instrumentacao import log, registrar_instrumentacao

app = Flask(__name__)
registrar_instrumentacao(app)

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


def _texto_nao_vazio(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


@app.get("/health")
def health():
    ok, reason = _check_sales_dir()
    if not ok:
        return jsonify({"status": "down", "reason": reason}), 503

    uptime_s = int(time.monotonic() - _START_TIME)
    return jsonify({"status": "ok", "uptimeS": uptime_s}), 200


@app.post("/buyTicket")
def buy_ticket():
    corpo = request.get_json(force=True, silent=True)
    if not isinstance(corpo, dict):
        return jsonify({"error": "invalid-request"}), 400

    if not (
        _texto_nao_vazio(corpo.get("flight"))
        and _texto_nao_vazio(corpo.get("day"))
        and _texto_nao_vazio(corpo.get("user"))
    ):
        return jsonify({"error": "invalid-request"}), 400

    return jsonify({"error": "not-implemented"}), 501


@app.errorhandler(Exception)
def tratar_excecao_global(exc: Exception):
    if isinstance(exc, HTTPException):
        return exc

    log("erro.nao_tratado", error=str(exc))
    return jsonify({"error": "internal-error"}), 500