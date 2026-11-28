from collections.abc import Callable
import random
import sqlite3
import threading
import time
from app.clientes import consultar_pontos, creditar_bonus
from app.config import CONFIG
from app.estado import ESTADO, Estado
from app.instrumentacao import log


def _aleatorio_uniforme_ms(maximo: float) -> float:
    if maximo <= 0:
        return 0.0
    return random.uniform(0.0, maximo)


def calcular_espera_ms(
    tentativas: int,
    inicial_ms: int,
    maximo_ms: int,
    jitter_ms: float,
) -> float:
    """Calcula espera de recuo exponencial com teto e jitter (Limit Retries)."""
    base = min(maximo_ms, inicial_ms * (2**tentativas))
    return float(base) + jitter_ms


class BonusWorker:
    """Worker em segundo plano para crédito assíncrono e reconciliado de bônus.

    Padrões aplicados:
    - Deferrable Work e Queue for Resources: o crédito de bônus não é essencial
      para responder 201 na venda e segue para uma fila persistente.
    - Checkpoint e What to Save: a fila reside na tabela SQLite do volume
      persistente, sobrevivendo a reinícios do container sem perda de bônus.
    - Limit Retries: usa recuo exponencial com teto e jitter para não
      sobrecarregar o Fidelity durante ou logo após uma indisponibilidade.
    """

    def __init__(
        self,
        estado: Estado,
        relogio: Callable[[], float] = time.time,
        aleatorio_ms: Callable[[float], float] = _aleatorio_uniforme_ms,
        dormir_s: Callable[[float], None] | None = None,
    ) -> None:
        self._estado = estado
        self._relogio = relogio
        self._aleatorio_ms = aleatorio_ms
        self._dormir_s = dormir_s
        self._evento_parada = threading.Event()
        self._thread: threading.Thread | None = None
        self._trava_thread = threading.Lock()

    def rodada(self) -> bool:
        agora = self._relogio()
        pendente = self._estado.proximo_bonus_vencido(agora)
        if pendente is None:
            return False

        res_pontos = consultar_pontos(
            pendente.user,
            pendente.cid,
            CONFIG.bonus_worker_timeout_ms,
        )
        if res_pontos.tipo == "ok" and res_pontos.dados is not None:
            cids = res_pontos.dados["cids"]
            assert isinstance(cids, frozenset)
            if pendente.cid in cids:
                self._estado.marcar_bonus_creditado(
                    pendente.cid,
                    pendente.flight,
                    pendente.day,
                    pendente.user,
                )
                log("bonus.reconciliado", cid=pendente.cid)
                return True

            res_bonus = creditar_bonus(
                pendente.user,
                pendente.bonus,
                pendente.cid,
                CONFIG.bonus_worker_timeout_ms,
            )
            if res_bonus.tipo == "ok":
                self._estado.marcar_bonus_creditado(
                    pendente.cid,
                    pendente.flight,
                    pendente.day,
                    pendente.user,
                )
                log(
                    "bonus.creditado",
                    cid=pendente.cid,
                    tentativas=pendente.tentativas + 1,
                )
                return True

            if res_bonus.tipo == "definitivo":
                log("bonus.rejeitado", cid=pendente.cid, motivo=res_bonus.motivo)
            motivo_falha = res_bonus.motivo
        else:
            motivo_falha = res_pontos.motivo

        tentativas = pendente.tentativas + 1
        jitter_ms = self._aleatorio_ms(float(CONFIG.bonus_backoff_initial_ms))
        espera_ms = calcular_espera_ms(
            tentativas,
            CONFIG.bonus_backoff_initial_ms,
            CONFIG.bonus_backoff_max_ms,
            jitter_ms,
        )
        proxima_em = agora + espera_ms / 1000.0
        self._estado.reagendar_bonus(
            pendente.cid,
            pendente.flight,
            pendente.day,
            pendente.user,
            tentativas,
            proxima_em,
        )
        if CONFIG.bonus_backoff_initial_ms * (2**tentativas) >= CONFIG.bonus_backoff_max_ms:
            log("bonus.escalonado", cid=pendente.cid, tentativas=tentativas)
        log(
            "bonus.adiado",
            cid=pendente.cid,
            tentativas=tentativas,
            motivo=motivo_falha,
        )
        return True

    def _esperar(self, segundos: float) -> None:
        if self._dormir_s is not None:
            self._dormir_s(segundos)
        else:
            self._evento_parada.wait(segundos)

    def _executar(self) -> None:
        while not self._evento_parada.is_set():
            try:
                processou = self.rodada()
            except sqlite3.Error as exc:
                log("bonus.worker.erro", erro=str(exc))
                self._esperar(1.0)
                continue

            if not processou:
                self._esperar(0.2)

    def iniciar(self) -> None:
        # Idempotente e protegido por trava: /health pode chamar em paralelo
        # (Flask com threaded=True) e nunca devem nascer duas threads.
        with self._trava_thread:
            if self._thread is not None and self._thread.is_alive():
                return
            self._evento_parada.clear()
            self._thread = threading.Thread(
                target=self._executar,
                name="bonus-worker",
                daemon=True,
            )
            self._thread.start()

    def parar(self) -> None:
        self._evento_parada.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def esta_vivo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


WORKER = BonusWorker(ESTADO)
