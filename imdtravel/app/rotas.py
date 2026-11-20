import json
import os
import tempfile
import time
from decimal import Decimal
from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException
from app.compra import comprar
from app.config import SALES_DIR
from app.instrumentacao import log, registrar_instrumentacao

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


def _json_com_numeros_exatos(corpo: dict[str, object]) -> str:
    # O testes.sh compara o texto dos números (350.50 não é igual a 350.5),
    # então os Decimal são escritos exatamente como foram recebidos.
    partes = []
    for chave, valor in corpo.items():
        if isinstance(valor, Decimal):
            texto = format(valor, "f")
        else:
            texto = json.dumps(valor, ensure_ascii=False)
        partes.append(f"{json.dumps(chave)}:{texto}")
    return "{" + ",".join(partes) + "}"


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

    status, resposta = comprar(
        corpo["flight"].strip(),
        corpo["day"].strip(),
        corpo["user"].strip(),
        g.cid,
    )
    if status == 201:
        return Response(
            _json_com_numeros_exatos(resposta),
            status=201,
            mimetype="application/json",
        )
    return jsonify(resposta), status


@app.errorhandler(Exception)
def tratar_excecao_global(exc: Exception):
    if isinstance(exc, HTTPException):
        return exc

    log("erro.nao_tratado", error=str(exc))
    return jsonify({"error": "internal-error"}), 500