import json
import os
import threading
from app.config import SALES_DIR

_LOCK = threading.Lock()


def _caminho_arquivo() -> str:
    return os.path.join(SALES_DIR, "vendas.jsonl")


def registrar(registro: dict[str, object]) -> None:
    linha = json.dumps(registro, ensure_ascii=False) + "\n"
    with _LOCK:
        with open(_caminho_arquivo(), "a", encoding="utf-8") as arquivo:
            arquivo.write(linha)
            arquivo.flush()


def listar() -> list[dict[str, object]]:
    caminho = _caminho_arquivo()
    with _LOCK:
        if not os.path.exists(caminho):
            return []
        registros: list[dict[str, object]] = []
        with open(caminho, "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                conteudo = linha.strip()
                if conteudo:
                    registros.append(json.loads(conteudo))
        return registros