import time
import requests
from app.config import AIRLINESHUB_URL, EXCHANGE_URL, FIDELITY_URL
from app.instrumentacao import log


def buscar_voo(flight: str, day: str, cid: str) -> requests.Response:
    alvo = "airlineshub"
    path = "/flight"
    url = f"{AIRLINESHUB_URL}{path}"
    inicio = time.monotonic()
    try:
        resp = requests.get(
            url,
            params={"flight": flight, "day": day},
            headers={"X-Correlation-Id": cid},
        )
    except Exception as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc))
        raise

    ms = round((time.monotonic() - inicio) * 1000, 2)
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=resp.status_code)
    return resp


def obter_taxa(cid: str) -> requests.Response:
    alvo = "exchange"
    path = "/convert"
    url = f"{EXCHANGE_URL}{path}"
    inicio = time.monotonic()
    try:
        resp = requests.get(
            url,
            headers={"X-Correlation-Id": cid},
        )
    except Exception as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc))
        raise

    ms = round((time.monotonic() - inicio) * 1000, 2)
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=resp.status_code)
    return resp


def vender(flight: str, day: str, cid: str) -> requests.Response:
    alvo = "airlineshub"
    path = "/sell"
    url = f"{AIRLINESHUB_URL}{path}"
    inicio = time.monotonic()
    try:
        resp = requests.post(
            url,
            json={"flight": flight, "day": day},
            headers={"X-Correlation-Id": cid},
        )
    except Exception as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc))
        raise

    ms = round((time.monotonic() - inicio) * 1000, 2)
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=resp.status_code)
    return resp


def creditar_bonus(user: str, bonus: int, cid: str) -> requests.Response:
    alvo = "fidelity"
    path = "/bonus"
    url = f"{FIDELITY_URL}{path}"
    inicio = time.monotonic()
    try:
        resp = requests.post(
            url,
            json={"user": user, "bonus": bonus},
            headers={"X-Correlation-Id": cid},
        )
    except Exception as exc:
        ms = round((time.monotonic() - inicio) * 1000, 2)
        log("dependencia.falha", ms=ms, alvo=alvo, path=path, erro=str(exc))
        raise

    ms = round((time.monotonic() - inicio) * 1000, 2)
    log("dependencia.resposta", ms=ms, alvo=alvo, path=path, status=resp.status_code)
    return resp