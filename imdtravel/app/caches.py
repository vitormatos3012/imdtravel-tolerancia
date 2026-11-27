from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
import threading
import time


@dataclass(frozen=True)
class Entrada:
    # Marked Data: carrega a idade calculada na leitura para que o chamador
    # saiba o quão antigo é o dado reaproveitado em modo degradado.
    valor: object
    as_of: str | None
    idade_s: float


class _CacheBase:
    def __init__(self, relogio: Callable[[], float] = time.monotonic) -> None:
        self._relogio = relogio
        self._lock = threading.Lock()
        self._entradas: dict[object, tuple[object, str | None, float]] = {}

    def _guardar(self, chave: object, valor: object, as_of: str | None) -> None:
        # Data Reset: o dado em cache é apenas um ponto de partida seguro;
        # qualquer nova leitura válida da dependência substitui o registro.
        with self._lock:
            self._entradas[chave] = (valor, as_of, self._relogio())

    def _obter(self, chave: object, idade_max_s: float) -> Entrada | None:
        with self._lock:
            registro = self._entradas.get(chave)
            if registro is None:
                return None
            valor, as_of, gravado_em_s = registro
            idade_s = max(0.0, self._relogio() - gravado_em_s)
            if idade_s > idade_max_s:
                return None
            return Entrada(valor=valor, as_of=as_of, idade_s=idade_s)


class CachePreco(_CacheBase):
    def guardar(self, flight: str, day: str, preco: Decimal) -> None:
        self._guardar((flight, day), preco, None)

    def obter(self, flight: str, day: str, idade_max_s: float) -> Entrada | None:
        return self._obter((flight, day), idade_max_s)


class CacheTaxa(_CacheBase):
    _CHAVE_UNICA = "taxa_atual"

    def guardar(self, rate: Decimal, as_of: str) -> None:
        self._guardar(self._CHAVE_UNICA, rate, as_of)

    def obter(self, idade_max_s: float) -> Entrada | None:
        return self._obter(self._CHAVE_UNICA, idade_max_s)


CACHE_PRECO = CachePreco()
CACHE_TAXA = CacheTaxa()
