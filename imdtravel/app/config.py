from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import os


def _obter_url_obrigatoria(env: Mapping[str, str], nome: str) -> str:
    valor = env.get(nome, "").strip()
    if not valor:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente ou vazia: {nome}")
    return valor.rstrip("/")


def _ler_str(env: Mapping[str, str], nome: str, padrao: str) -> str:
    valor = env.get(nome, "").strip()
    return valor if valor else padrao


def _ler_int(
    env: Mapping[str, str],
    nome: str,
    padrao: int,
    minimo: int,
    descricao: str,
) -> int:
    bruto = env.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = int(bruto)
    except ValueError as exc:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        ) from exc
    if valor < minimo:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        )
    return valor


def _ler_float(
    env: Mapping[str, str],
    nome: str,
    padrao: float,
    minimo: float,
    inclusivo: bool,
    descricao: str,
) -> float:
    bruto = env.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = float(bruto)
    except ValueError as exc:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        ) from exc
    if not math.isfinite(valor):
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        )
    invalido = valor < minimo if inclusivo else valor <= minimo
    if invalido:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        )
    return valor


def _ler_decimal(
    env: Mapping[str, str],
    nome: str,
    padrao: Decimal,
    descricao: str,
) -> Decimal:
    bruto = env.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        valor = Decimal(bruto)
    except InvalidOperation as exc:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        ) from exc
    if not valor.is_finite() or valor <= 0:
        raise RuntimeError(
            f"Variável de ambiente inválida: {nome}='{bruto}' (esperado: {descricao})"
        )
    return valor


@dataclass(frozen=True)
class Config:
    airlineshub_url: str
    exchange_url: str
    fidelity_url: str
    port: int
    sales_dir: str
    db_path: str
    deadline_ms: int
    deadline_margin_ms: int
    flight_timeout_ms: int
    price_cache_max_age_s: float
    convert_timeout_ms: int
    convert_max_attempts: int
    retry_backoff_ms: int
    retry_jitter_ms: int
    rate_min: Decimal
    rate_max: Decimal
    rate_cache_max_age_s: float
    sell_timeout_ms: int
    sell_min_start_ms: int
    bonus_inline_timeout_ms: int
    bonus_queue_max: int
    bonus_backoff_initial_ms: int
    bonus_backoff_max_ms: int
    bonus_worker_timeout_ms: int
    breaker_threshold: float
    breaker_leak_per_s: float
    breaker_open_s: float
    max_inflight: int
    retry_after_s: int


def carregar(env: Mapping[str, str]) -> Config:
    airlineshub_url = _obter_url_obrigatoria(env, "AIRLINESHUB_URL")
    exchange_url = _obter_url_obrigatoria(env, "EXCHANGE_URL")
    fidelity_url = _obter_url_obrigatoria(env, "FIDELITY_URL")

    port = _ler_int(env, "PORT", 8080, 1, "inteiro >= 1")
    sales_dir = _ler_str(env, "SALES_DIR", "/data")
    db_path = _ler_str(env, "DB_PATH", "/data/imdtravel.db")
    deadline_ms = _ler_int(env, "DEADLINE_MS", 5000, 1, "inteiro >= 1")
    deadline_margin_ms = _ler_int(env, "DEADLINE_MARGIN_MS", 500, 0, "inteiro >= 0")
    flight_timeout_ms = _ler_int(env, "FLIGHT_TIMEOUT_MS", 1000, 1, "inteiro >= 1")
    price_cache_max_age_s = _ler_float(
        env, "PRICE_CACHE_MAX_AGE_S", 3600.0, 0.0, False, "número > 0"
    )
    convert_timeout_ms = _ler_int(env, "CONVERT_TIMEOUT_MS", 500, 1, "inteiro >= 1")
    convert_max_attempts = _ler_int(env, "CONVERT_MAX_ATTEMPTS", 2, 1, "inteiro >= 1")
    retry_backoff_ms = _ler_int(env, "RETRY_BACKOFF_MS", 100, 0, "inteiro >= 0")
    retry_jitter_ms = _ler_int(env, "RETRY_JITTER_MS", 50, 0, "inteiro >= 0")
    rate_min = _ler_decimal(env, "RATE_MIN", Decimal("5.0"), "decimal > 0")
    rate_max = _ler_decimal(env, "RATE_MAX", Decimal("6.0"), "decimal > 0")
    rate_cache_max_age_s = _ler_float(
        env, "RATE_CACHE_MAX_AGE_S", 60.0, 0.0, False, "número > 0"
    )
    sell_timeout_ms = _ler_int(env, "SELL_TIMEOUT_MS", 1500, 1, "inteiro >= 1")
    sell_min_start_ms = _ler_int(env, "SELL_MIN_START_MS", 1000, 1, "inteiro >= 1")
    bonus_inline_timeout_ms = _ler_int(
        env, "BONUS_INLINE_TIMEOUT_MS", 800, 1, "inteiro >= 1"
    )
    bonus_queue_max = _ler_int(env, "BONUS_QUEUE_MAX", 1000, 1, "inteiro >= 1")
    bonus_backoff_initial_ms = _ler_int(
        env, "BONUS_BACKOFF_INITIAL_MS", 500, 1, "inteiro >= 1"
    )
    bonus_backoff_max_ms = _ler_int(
        env, "BONUS_BACKOFF_MAX_MS", 10000, 1, "inteiro >= 1"
    )
    bonus_worker_timeout_ms = _ler_int(
        env, "BONUS_WORKER_TIMEOUT_MS", 2000, 1, "inteiro >= 1"
    )
    breaker_threshold = _ler_float(
        env, "BREAKER_THRESHOLD", 3.0, 0.0, False, "número > 0"
    )
    breaker_leak_per_s = _ler_float(
        env, "BREAKER_LEAK_PER_S", 0.1, 0.0, True, "número >= 0"
    )
    breaker_open_s = _ler_float(env, "BREAKER_OPEN_S", 10.0, 0.0, False, "número > 0")
    max_inflight = _ler_int(env, "MAX_INFLIGHT", 50, 1, "inteiro >= 1")
    retry_after_s = _ler_int(env, "RETRY_AFTER_S", 1, 1, "inteiro >= 1")

    if deadline_ms <= deadline_margin_ms:
        raise RuntimeError(
            "Configuração inválida: DEADLINE_MS deve ser maior que DEADLINE_MARGIN_MS"
        )
    if rate_min >= rate_max:
        raise RuntimeError(
            "Configuração inválida: RATE_MIN deve ser menor que RATE_MAX"
        )
    if bonus_backoff_initial_ms > bonus_backoff_max_ms:
        raise RuntimeError(
            "Configuração inválida: BONUS_BACKOFF_INITIAL_MS deve ser menor ou igual a BONUS_BACKOFF_MAX_MS"
        )
    if sell_min_start_ms > sell_timeout_ms:
        raise RuntimeError(
            "Configuração inválida: SELL_MIN_START_MS deve ser menor ou igual a SELL_TIMEOUT_MS"
        )

    return Config(
        airlineshub_url=airlineshub_url,
        exchange_url=exchange_url,
        fidelity_url=fidelity_url,
        port=port,
        sales_dir=sales_dir,
        db_path=db_path,
        deadline_ms=deadline_ms,
        deadline_margin_ms=deadline_margin_ms,
        flight_timeout_ms=flight_timeout_ms,
        price_cache_max_age_s=price_cache_max_age_s,
        convert_timeout_ms=convert_timeout_ms,
        convert_max_attempts=convert_max_attempts,
        retry_backoff_ms=retry_backoff_ms,
        retry_jitter_ms=retry_jitter_ms,
        rate_min=rate_min,
        rate_max=rate_max,
        rate_cache_max_age_s=rate_cache_max_age_s,
        sell_timeout_ms=sell_timeout_ms,
        sell_min_start_ms=sell_min_start_ms,
        bonus_inline_timeout_ms=bonus_inline_timeout_ms,
        bonus_queue_max=bonus_queue_max,
        bonus_backoff_initial_ms=bonus_backoff_initial_ms,
        bonus_backoff_max_ms=bonus_backoff_max_ms,
        bonus_worker_timeout_ms=bonus_worker_timeout_ms,
        breaker_threshold=breaker_threshold,
        breaker_leak_per_s=breaker_leak_per_s,
        breaker_open_s=breaker_open_s,
        max_inflight=max_inflight,
        retry_after_s=retry_after_s,
    )


CONFIG: Config = carregar(os.environ)

PORT: int = CONFIG.port
SALES_DIR: str = CONFIG.sales_dir
AIRLINESHUB_URL: str = CONFIG.airlineshub_url
EXCHANGE_URL: str = CONFIG.exchange_url
FIDELITY_URL: str = CONFIG.fidelity_url
