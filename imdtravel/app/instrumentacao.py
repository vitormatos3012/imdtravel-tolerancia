from datetime import datetime, timezone
import json
import logging
import sys
import time
import uuid
from flask import Flask, g, has_request_context, request


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "svc": "imdtravel",
            "cid": getattr(record, "cid", None),
            "event": getattr(record, "event", record.getMessage()),
            "ms": getattr(record, "ms", 0),
        }
        extras = getattr(record, "extras", None)
        if isinstance(extras, dict):
            for key, value in extras.items():
                # Fora de uma requisição (worker) o "cid" do payload é None: o cid explícito vale.
                if key not in payload or (key == "cid" and payload["cid"] is None):
                    payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


_logger = logging.getLogger("imdtravel")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_JsonFormatter())
    _logger.addHandler(_handler)

logging.getLogger("werkzeug").setLevel(logging.ERROR)


def _obter_cid() -> str | None:
    if has_request_context():
        cid = getattr(g, "cid", None)
        if isinstance(cid, str) and cid:
            return cid
    return None


def log(event: str, ms: int | float = 0, **extras: object) -> None:
    _logger.info(
        event,
        extra={
            "cid": _obter_cid(),
            "event": event,
            "ms": ms,
            "extras": extras,
        },
    )


def registrar_instrumentacao(app: Flask) -> None:
    @app.before_request
    def _antes_da_requisicao() -> None:
        header_cid = request.headers.get("X-Correlation-Id", "").strip()
        g.cid = header_cid if header_cid else str(uuid.uuid4())
        g.inicio_req = time.monotonic()

        if request.path != "/health":
            log(
                "requisicao.recebida",
                ms=0,
                method=request.method,
                path=request.path,
            )

    @app.after_request
    def _depois_da_requisicao(response):
        cid = _obter_cid()
        if not cid:
            header_cid = request.headers.get("X-Correlation-Id", "").strip()
            cid = header_cid if header_cid else str(uuid.uuid4())
            g.cid = cid

        response.headers["X-Correlation-Id"] = cid

        inicio = getattr(g, "inicio_req", None)
        duracao_ms = (
            round((time.monotonic() - inicio) * 1000, 2)
            if inicio is not None
            else 0
        )

        if request.path != "/health" or response.status_code != 200:
            log(
                "resposta.enviada",
                ms=duracao_ms,
                path=request.path,
                status=response.status_code,
            )

        return response