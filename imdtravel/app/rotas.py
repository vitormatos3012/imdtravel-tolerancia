import os
import tempfile
import time
from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException
from app.admissao import ADMISSAO
from app.bonus_worker import WORKER
from app.compra import comprar
from app.config import CONFIG, SALES_DIR
from app.instrumentacao import log, registrar_instrumentacao
from app.resposta import json_exato, recusa_503
from app.vendas import listar

app = Flask(__name__)
app.json.sort_keys = False
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


def _resposta_503(corpo: dict[str, object]):
    resp = jsonify(corpo)
    resp.headers["Retry-After"] = str(CONFIG.retry_after_s)
    return resp, 503


@app.get("/health")
def health():
    ok, reason = _check_sales_dir()
    if not ok:
        return jsonify({"status": "down", "reason": reason}), 503

    # Vigilância do worker (Watchdog 18 e Restart 31): o healthcheck do compose chama
    # este endpoint periodicamente e faz o papel de vigia.
    if not WORKER.esta_vivo():
        WORKER.iniciar()
        log("bonus.worker.reiniciado")
        if not WORKER.esta_vivo():
            return jsonify({"status": "down", "reason": "bonus_worker_dead"}), 503

    uptime_s = int(time.monotonic() - _START_TIME)
    return jsonify({"status": "ok", "uptimeS": uptime_s}), 200


@app.get("/sales")
def sales():
    return jsonify(listar()), 200


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

    if not ADMISSAO.tentar_entrar():
        log("admissao.recusou", em_andamento=ADMISSAO.em_andamento())
        return _resposta_503(recusa_503("overloaded", g.cid))

    try:
        status, resposta = comprar(
            corpo["flight"].strip(),
            corpo["day"].strip(),
            corpo["user"].strip(),
            g.cid,
        )
    finally:
        ADMISSAO.sair()

    if status == 201:
        return Response(
            json_exato(resposta),
            status=201,
            mimetype="application/json",
        )
    if status == 503:
        return _resposta_503(resposta)
    return jsonify(resposta), status


@app.errorhandler(Exception)
def tratar_excecao_global(exc: Exception):
    if isinstance(exc, HTTPException):
        return exc

    log("erro.nao_tratado", error=str(exc))
    return jsonify({"error": "internal-error"}), 500
