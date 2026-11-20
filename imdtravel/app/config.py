import os


def _get_required_url(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Variável de ambiente obrigatória ausente ou vazia: {name}")
    return value.rstrip("/")


PORT: int = int(os.environ.get("PORT", "8080"))
SALES_DIR: str = os.environ.get("SALES_DIR", "/data")
AIRLINESHUB_URL: str = _get_required_url("AIRLINESHUB_URL")
EXCHANGE_URL: str = _get_required_url("EXCHANGE_URL")
FIDELITY_URL: str = _get_required_url("FIDELITY_URL")
