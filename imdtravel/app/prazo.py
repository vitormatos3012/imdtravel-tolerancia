from collections.abc import Callable
import time


class Prazo:
    def __init__(
        self,
        total_ms: float,
        margem_ms: float = 0,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        if total_ms <= 0:
            raise ValueError("total_ms deve ser maior que zero")
        if margem_ms < 0:
            raise ValueError("margem_ms não pode ser negativo")
        if margem_ms >= total_ms:
            raise ValueError("margem_ms deve ser menor que total_ms")

        self._total_ms = float(total_ms)
        self._margem_ms = float(margem_ms)
        self._relogio = relogio
        self._inicio_s = relogio()

    def decorrido_ms(self) -> float:
        return (self._relogio() - self._inicio_s) * 1000.0

    def restante_ms(self) -> float:
        return max(0.0, self._total_ms - self._margem_ms - self.decorrido_ms())

    def expirou(self) -> bool:
        return self.restante_ms() <= 0

    def cabe(self, minimo_ms: float) -> bool:
        return self.restante_ms() >= minimo_ms

    def timeout_ms(
        self,
        nominal_ms: float,
        reserva_ms: float = 0,
        minimo_ms: float = 1,
    ) -> float | None:
        candidato = min(nominal_ms, self.restante_ms() - reserva_ms)
        if candidato < minimo_ms:
            return None
        return float(candidato)
