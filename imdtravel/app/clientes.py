from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import time
from typing import Literal
import requests
import urllib3.exceptions
from app.config import AIRLINESHUB_URL, CONFIG, EXCHANGE_URL, FIDELITY_URL
from app.instrumentacao import log

TipoResultado = Literal["ok", "definitivo", "falha_segura", "incerto"]


@dataclass(frozen=True)
class Resultado:
    tipo: TipoResultado
    status: int | None
    dados: dict[str, object] | None
    motivo: str
    ms: float


def _eh_2xx(status_code: int) -> bool:
    return 200 <= status_code < 300


def _rejeitar_constante_json(valor: str) -> None:
    raise ValueError(f"Constante JSON não permitida: {valor}")


def interpretar_taxa(
    texto: str,
    rate_min: Decimal,
    rate_max: Decimal,
) -> tuple[Decimal, str] | None:
    try:
        dados = json.loads(
            texto,
            parse_float=Decimal,
            parse_constant=_rejeitar_constante_json,
        )
        if not isinstance(dados, dict):
            return None
        if "rate" not in dados or "asOf" not in dados:
            return None

        rate_bruto = dados["rate"]
        if isinstance(rate_bruto, bool) or not isinstance(rate_bruto, (int, Decimal)):
            return None

        rate = Decimal(rate_bruto) if isinstance(rate_bruto, int) else rate_bruto
        if not rate.is_finite():
            return None
        if rate < rate_min or rate > rate_max:
            return None

        as_of = dados["asOf"]
        if not isinstance(as_of, str) or not as_of.strip():
            return None

        return rate, as_of
    except (ValueError, KeyError, TypeError, ArithmeticError, InvalidOperation):
        return None


def classificar_excecao(
    exc: requests.exceptions.RequestException,
) -> tuple[TipoResultado, str]:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "falha_segura", "connect_timeout"

    if isinstance(exc, requests.exceptions.ConnectionError) and exc.args:
        primeiro = exc.args[0]
        reason = getattr(primeiro, "reason", None)
        if isinstance(reason, urllib3.exceptions.NewConnectionError):
            return "falha_segura", "conexao_recusada"

    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "incerto", "timeout"

    return "incerto", "conexao_interrompida"


def _extrair_preco_voo(texto: str) -> Decimal | None:
    try:
        dados = json.loads(
            texto,
            parse_float=Decimal,
            parse_constant=_rejeitar_constante_json,
        )
        if not isinstance(dados, dict) or "priceUSD" not in dados:
            return None

        preco_bruto = dados["priceUSD"]
        if isinstance(preco_bruto, bool) or not isinstance(preco_bruto, (int, Decimal)):
            return None

        preco = Decimal(preco_bruto) if isinstance(preco_bruto, int) else preco_bruto
        if not preco.is_finite() or preco <= 0:
            return None

        return preco
    except (ValueError, KeyError, TypeError, ArithmeticError, InvalidOperation):
        return None


def _extrair_transaction_id(texto: str) -> str | None:
    try:
        dados = json.loads(
            texto,
            parse_float=Decimal,
            parse_constant=_rejeitar_constante_json,
        )
        if not isinstance(dados, dict) or "transactionId" not in dados:
            return None

        tx_id = dados["transactionId"]
        if not isinstance(tx_id, str) or not tx_id.strip():
            return None

        return tx_id
    except (ValueError, KeyError, TypeError, ArithmeticError, InvalidOperation):
        return None


def _extrair_cids_pontos(texto: str) -> frozenset[str] | None:
    try:
        dados = json.loads(
            texto,
            parse_float=Decimal,
            parse_constant=_rejeitar_constante_json,
        )
        if not isinstance(dados, dict) or "entries" not in dados:
            return None

        entries = dados["entries"]
        if not isinstance(entries, list):
            return None

        cids: set[str] = set()
        for item in entries:
            if not isinstance(item, dict):
                return None
            cid_bruto = item.get("cid")
            if isinstance(cid_bruto, str) and cid_bruto.strip():
                cids.add(cid_bruto)

        return frozenset(cids)
    except (ValueError, KeyError, TypeError, ArithmeticError, InvalidOperation):
        return None


def buscar_voo(
    flight: str,
    day: str,
    cid: str,
    timeout_ms: float,
    base_url: str | None = None,
) -> Resultado:
    alvo = "airlineshub"
    path = "/flight"
    url_base = (base_url if base_url is not None else AIRLINESHUB_URL).rstrip("/")
    url = f"{url_base}{path}"
    inicio = time.monotonic()

    # O timeout do requests vale por fase (conexão e espera de bytes), não como prazo total;
    # para as nossas falhas (nenhum byte chega) isso equivale a um limite total.
    try:
        resp = requests.get(
            url,
            params={"flight": flight, "day": day},
            headers={"X-Correlation-Id": cid},
            timeout=timeout_ms / 1000,
        )
    except requests.exceptions.Timeout as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo: TipoResultado = "falha_segura"
        motivo = "timeout"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)
    except requests.exceptions.RequestException as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo = "falha_segura"
        motivo = "conexao"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)

    ms = round((time.monotonic() - inicio) * 1000, 2)
    status = resp.status_code

    if status == 404:
        tipo = "definitivo"
        motivo = "status_404"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    if status != 200:
        tipo = "falha_segura"
        motivo = f"status_{status}"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    preco = _extrair_preco_voo(resp.text)
    if preco is None:
        tipo = "falha_segura"
        motivo = "resposta_invalida"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    tipo = "ok"
    motivo = "ok"
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
    return Resultado(
        tipo=tipo,
        status=status,
        dados={"priceUSD": preco},
        motivo=motivo,
        ms=ms,
    )


def obter_taxa(
    cid: str,
    timeout_ms: float,
    base_url: str | None = None,
) -> Resultado:
    alvo = "exchange"
    path = "/convert"
    url_base = (base_url if base_url is not None else EXCHANGE_URL).rstrip("/")
    url = f"{url_base}{path}"
    inicio = time.monotonic()

    # O timeout do requests vale por fase (conexão e espera de bytes), não como prazo total;
    # para as nossas falhas (nenhum byte chega) isso equivale a um limite total.
    try:
        resp = requests.get(
            url,
            headers={"X-Correlation-Id": cid},
            timeout=timeout_ms / 1000,
        )
    except requests.exceptions.Timeout as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo: TipoResultado = "falha_segura"
        motivo = "timeout"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)
    except requests.exceptions.RequestException as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo = "falha_segura"
        motivo = "conexao"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)

    ms = round((time.monotonic() - inicio) * 1000, 2)
    status = resp.status_code

    if not _eh_2xx(status):
        tipo = "falha_segura"
        motivo = f"status_{status}"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    try:
        json.loads(
            resp.text,
            parse_float=Decimal,
            parse_constant=_rejeitar_constante_json,
        )
    except ValueError:
        tipo = "falha_segura"
        motivo = "resposta_invalida"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    interpretado = interpretar_taxa(resp.text, CONFIG.rate_min, CONFIG.rate_max)
    if interpretado is None:
        tipo = "falha_segura"
        motivo = "taxa_invalida"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    rate, as_of = interpretado
    tipo = "ok"
    motivo = "ok"
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
    return Resultado(
        tipo=tipo,
        status=status,
        dados={"rate": rate, "asOf": as_of},
        motivo=motivo,
        ms=ms,
    )


def vender(
    flight: str,
    day: str,
    cid: str,
    timeout_ms: float,
    base_url: str | None = None,
) -> Resultado:
    alvo = "airlineshub"
    path = "/sell"
    url_base = (base_url if base_url is not None else AIRLINESHUB_URL).rstrip("/")
    url = f"{url_base}{path}"
    inicio = time.monotonic()

    # O timeout do requests vale por fase (conexão e espera de bytes), não como prazo total;
    # para as nossas falhas (nenhum byte chega) isso equivale a um limite total.
    try:
        resp = requests.post(
            url,
            json={"flight": flight, "day": day},
            headers={"X-Correlation-Id": cid},
            timeout=timeout_ms / 1000,
        )
    except requests.exceptions.RequestException as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo, motivo = classificar_excecao(exc)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)

    ms = round((time.monotonic() - inicio) * 1000, 2)
    status = resp.status_code

    if status == 201:
        tx_id = _extrair_transaction_id(resp.text)
        if tx_id is None:
            tipo = "incerto"
            motivo = "201_sem_transactionId"
            log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
            return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

        tipo = "ok"
        motivo = "ok"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(
            tipo=tipo,
            status=status,
            dados={"transactionId": tx_id},
            motivo=motivo,
            ms=ms,
        )

    if status == 409:
        tipo = "definitivo"
        motivo = "status_409"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    if 400 <= status < 500:
        tipo = "falha_segura"
        motivo = f"status_{status}"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    tipo = "incerto"
    motivo = f"status_{status}"
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
    return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)


def creditar_bonus(
    user: str,
    bonus: int,
    cid: str,
    timeout_ms: float,
    base_url: str | None = None,
) -> Resultado:
    alvo = "fidelity"
    path = "/bonus"
    url_base = (base_url if base_url is not None else FIDELITY_URL).rstrip("/")
    url = f"{url_base}{path}"
    inicio = time.monotonic()

    # O timeout do requests vale por fase (conexão e espera de bytes), não como prazo total;
    # para as nossas falhas (nenhum byte chega) isso equivale a um limite total.
    try:
        resp = requests.post(
            url,
            json={"user": user, "bonus": bonus},
            headers={"X-Correlation-Id": cid},
            timeout=timeout_ms / 1000,
        )
    except requests.exceptions.RequestException as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo, motivo = classificar_excecao(exc)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)

    ms = round((time.monotonic() - inicio) * 1000, 2)
    status = resp.status_code

    if _eh_2xx(status):
        tipo = "ok"
        motivo = "ok"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    if 400 <= status < 500:
        tipo = "definitivo"
        motivo = f"status_{status}"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    tipo = "incerto"
    motivo = f"status_{status}"
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
    return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)


def consultar_pontos(
    user: str,
    cid: str,
    timeout_ms: float,
    base_url: str | None = None,
) -> Resultado:
    alvo = "fidelity"
    path = "/points"
    url_base = (base_url if base_url is not None else FIDELITY_URL).rstrip("/")
    url = f"{url_base}{path}"
    inicio = time.monotonic()

    # O timeout do requests vale por fase (conexão e espera de bytes), não como prazo total;
    # para as nossas falhas (nenhum byte chega) isso equivale a um limite total.
    try:
        resp = requests.get(
            url,
            params={"user": user},
            headers={"X-Correlation-Id": cid},
            timeout=timeout_ms / 1000,
        )
    except requests.exceptions.Timeout as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo: TipoResultado = "falha_segura"
        motivo = "timeout"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)
    except requests.exceptions.RequestException as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        tipo = "falha_segura"
        motivo = "conexao"
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc), tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=None, dados=None, motivo=motivo, ms=ms)

    ms = round((time.monotonic() - inicio) * 1000, 2)
    status = resp.status_code

    if status != 200:
        tipo = "falha_segura"
        motivo = f"status_{status}"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    cids = _extrair_cids_pontos(resp.text)
    if cids is None:
        tipo = "falha_segura"
        motivo = "resposta_invalida"
        log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
        return Resultado(tipo=tipo, status=status, dados=None, motivo=motivo, ms=ms)

    tipo = "ok"
    motivo = "ok"
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=status, tipo=tipo, motivo=motivo)
    return Resultado(
        tipo=tipo,
        status=status,
        dados={"cids": cids},
        motivo=motivo,
        ms=ms,
    )
