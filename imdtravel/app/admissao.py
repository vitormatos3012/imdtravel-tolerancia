import threading
from app.config import CONFIG

# Padrões (artigo HANMER): Queue for Resources / recusa antecipada: a admissão acontece
# antes de gastar qualquer recurso (thread, chamadas externas) e nunca bloqueia nem espera.
# A recusa acontece ANTES de qualquer venda, então responder 503 "not-sold" é verdade.


class Admissao:
    """Limite de requisições simultâneas, sem fila e sem espera."""

    def __init__(self, limite: int) -> None:
        self._limite = limite
        self._em_andamento = 0
        self._lock = threading.Lock()

    def tentar_entrar(self) -> bool:
        with self._lock:
            if self._em_andamento < self._limite:
                self._em_andamento += 1
                return True
            return False

    def sair(self) -> None:
        with self._lock:
            if self._em_andamento > 0:
                self._em_andamento -= 1

    def em_andamento(self) -> int:
        with self._lock:
            return self._em_andamento


ADMISSAO = Admissao(CONFIG.max_inflight)
