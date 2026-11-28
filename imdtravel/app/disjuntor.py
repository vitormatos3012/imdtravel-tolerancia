from collections.abc import Callable
import threading
import time
from app.clientes import Resultado
from app.config import CONFIG
from app.instrumentacao import log

# Padrões (artigo HANMER):
# - Fail Fast-like / circuit breaker: depois de falhas repetidas, para de chamar a dependência
#   por um tempo e deixa o chamador seguir pelo caminho degradado que já existe.
# - Error Containment Barrier (13): a falha de uma dependência fica contida no seu disjuntor
#   e não consome o prazo das compras seguintes.
# - Limit Retries (35): enquanto aberto, não há nenhuma tentativa; no meio-aberto passa UMA sonda.
# - Acknowledgement (17), junto com os padrões de detecção e recuperação: o resultado da sonda
#   confirma se a dependência voltou (fecha) ou não (reabre).
#
# Por que balde furado: falhas esporádicas e espaçadas vazam antes de somar o limiar e não abrem
# o disjuntor; uma rajada de falhas em pouco tempo enche o balde e abre.

FECHADO = "fechado"
ABERTO = "aberto"
MEIO_ABERTO = "meio-aberto"
MOTIVO_DISJUNTOR_ABERTO = "disjuntor_aberto"

_NOMES = ("flight", "convert", "sell", "bonus")


class Disjuntor:
    """Disjuntor com balde furado e uma única sonda no estado meio-aberto."""

    def __init__(
        self,
        nome: str,
        limiar: float,
        vazamento_por_s: float,
        aberto_s: float,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._nome = nome
        self._limiar = limiar
        self._vazamento_por_s = vazamento_por_s
        self._aberto_s = aberto_s
        self._relogio = relogio
        self._lock = threading.Lock()
        self._estado = FECHADO
        self._nivel = 0.0
        self._ultimo_instante = relogio()
        self._aberto_em = 0.0
        self._sonda_desde = 0.0

    def _vazar(self, agora: float) -> None:
        decorrido = agora - self._ultimo_instante
        self._nivel = max(0.0, self._nivel - self._vazamento_por_s * decorrido)
        self._ultimo_instante = agora

    def _abrir(self, agora: float) -> None:
        self._estado = ABERTO
        self._aberto_em = agora
        log("disjuntor.abriu", alvo=self._nome, nivel=self._nivel)

    def registrar(self, sucesso: bool) -> None:
        with self._lock:
            if self._estado == ABERTO:
                # Resultado atrasado de uma chamada iniciada antes de abrir: ignorar.
                return
            agora = self._relogio()
            self._vazar(agora)
            if self._estado == FECHADO:
                if sucesso:
                    return
                self._nivel += 1.0
                if self._nivel >= self._limiar:
                    self._abrir(agora)
                return
            # Meio-aberto: o resultado é o da sonda.
            if sucesso:
                self._estado = FECHADO
                self._nivel = 0.0
                log("disjuntor.fechou", alvo=self._nome)
            else:
                self._abrir(agora)

    def permite(self) -> bool:
        with self._lock:
            agora = self._relogio()
            self._vazar(agora)
            if self._estado == FECHADO:
                return True
            if self._estado == ABERTO:
                if agora - self._aberto_em < self._aberto_s:
                    return False
                self._estado = MEIO_ABERTO
                self._sonda_desde = agora
                log("disjuntor.meio_aberto", alvo=self._nome)
                return True
            # Meio-aberto: só uma sonda por vez; se ela nunca reportou, libera outra.
            if agora - self._sonda_desde >= self._aberto_s:
                self._sonda_desde = agora
                return True
            return False

    def esta_aberto(self) -> bool:
        """Só leitura: nunca muda de estado nem consome a sonda."""
        with self._lock:
            agora = self._relogio()
            return self._estado == ABERTO and agora - self._aberto_em < self._aberto_s

    def estado(self) -> str:
        with self._lock:
            return self._estado


def _criar(nome: str, relogio: Callable[[], float]) -> Disjuntor:
    return Disjuntor(
        nome,
        CONFIG.breaker_threshold,
        CONFIG.breaker_leak_per_s,
        CONFIG.breaker_open_s,
        relogio,
    )


DISJUNTORES: dict[str, Disjuntor] = {nome: _criar(nome, time.monotonic) for nome in _NOMES}


def reiniciar_todos(relogio: Callable[[], float] | None = None) -> None:
    """Recria os quatro disjuntores dentro do mesmo dict (usado pelos testes)."""
    relogio_usado = relogio if relogio is not None else time.monotonic
    for nome in _NOMES:
        DISJUNTORES[nome] = _criar(nome, relogio_usado)


def executar(alvo: str, chamada: Callable[[], Resultado]) -> Resultado:
    """Chama a dependência através do disjuntor do alvo.

    Se a chamada levantar exceção, ela propaga sem registro; uma sonda pendente
    é tratada pelo prazo da sonda em permite().
    """
    disjuntor = DISJUNTORES[alvo]
    if not disjuntor.permite():
        log("disjuntor.recusou", alvo=alvo)
        return Resultado(
            tipo="falha_segura",
            status=None,
            dados=None,
            motivo=MOTIVO_DISJUNTOR_ABERTO,
            ms=0.0,
        )
    res = chamada()
    # A dependência respondeu de forma coerente (ok ou definitivo) = sucesso.
    disjuntor.registrar(res.tipo in ("ok", "definitivo"))
    return res
