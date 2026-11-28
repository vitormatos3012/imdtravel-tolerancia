import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.bonus_worker import BonusWorker, calcular_espera_ms
from app.clientes import Resultado
from app.config import CONFIG
from app.estado import Estado


class _RelogioFalso:
    def __init__(self, agora: float = 1000.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def _pontos_ok(cids: frozenset[str] = frozenset()) -> Resultado:
    return Resultado(
        tipo="ok",
        status=200,
        dados={"cids": cids},
        motivo="ok",
        ms=5.0,
    )


def _pontos_falha(motivo: str = "conexao") -> Resultado:
    return Resultado(
        tipo="falha_segura",
        status=None,
        dados=None,
        motivo=motivo,
        ms=5.0,
    )


def _bonus_ok() -> Resultado:
    return Resultado(
        tipo="ok",
        status=200,
        dados=None,
        motivo="ok",
        ms=5.0,
    )


def _bonus_falha(
    tipo: str = "falha_segura",
    status: int | None = None,
    motivo: str = "conexao_recusada",
) -> Resultado:
    return Resultado(
        tipo=tipo,  # type: ignore[arg-type]
        status=status,
        dados=None,
        motivo=motivo,
        ms=5.0,
    )


class TestBonusWorker(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.relogio = _RelogioFalso(1000.0)
        self.estado = Estado(
            os.path.join(self.tmp_dir.name, "compras.db"),
            relogio=self.relogio,
            bonus_lease_s=0.0,
        )
        self.worker = BonusWorker(
            self.estado,
            relogio=self.relogio,
            aleatorio_ms=lambda _m: 0.0,
        )

    def _inserir_pendente(
        self,
        cid: str = "cid-1",
        flight: str = "LA3001",
        day: str = "2026-12-01",
        user: str = "joao",
        bonus: int = 200,
    ) -> None:
        self.estado.iniciar_compra(cid, flight, day, user)
        self.estado.concluir_vendida(
            cid,
            flight,
            day,
            user,
            f"tx-{cid}",
            bonus,
            201,
            '{"transactionId":"tx"}',
        )

    def test_a_pontos_sem_cid_e_creditar_ok_marca_creditado(self) -> None:
        self._inserir_pendente("cid-a")

        with (
            patch("app.bonus_worker.consultar_pontos", return_value=_pontos_ok()) as m_pts,
            patch("app.bonus_worker.creditar_bonus", return_value=_bonus_ok()) as m_cred,
        ):
            processou = self.worker.rodada()

        self.assertTrue(processou)
        m_pts.assert_called_once_with("joao", "cid-a", CONFIG.bonus_worker_timeout_ms)
        m_cred.assert_called_once_with("joao", 200, "cid-a", CONFIG.bonus_worker_timeout_ms)
        linha = self.estado.buscar("cid-a", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "CREDITADO")

    def test_b_pontos_com_cid_reconcilia_sem_reenviar_bonus(self) -> None:
        self._inserir_pendente("cid-b")

        with (
            patch(
                "app.bonus_worker.consultar_pontos",
                return_value=_pontos_ok(frozenset({"cid-b"})),
            ) as m_pts,
            patch("app.bonus_worker.creditar_bonus", return_value=_bonus_ok()) as m_cred,
        ):
            processou = self.worker.rodada()

        self.assertTrue(processou)
        m_pts.assert_called_once()
        m_cred.assert_not_called()
        linha = self.estado.buscar("cid-b", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "CREDITADO")

    def test_c_consultar_pontos_falha_reagenda_sem_creditar(self) -> None:
        self._inserir_pendente("cid-c")

        with (
            patch(
                "app.bonus_worker.consultar_pontos",
                return_value=_pontos_falha("timeout"),
            ),
            patch("app.bonus_worker.creditar_bonus") as m_cred,
        ):
            processou = self.worker.rodada()

        self.assertTrue(processou)
        m_cred.assert_not_called()
        linha = self.estado.buscar("cid-c", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "PENDENTE")
        self.assertEqual(linha.bonus_tentativas, 1)

        espera_ms = calcular_espera_ms(
            1,
            CONFIG.bonus_backoff_initial_ms,
            CONFIG.bonus_backoff_max_ms,
            0.0,
        )
        self.assertIsNone(self.estado.proximo_bonus_vencido(self.relogio()))
        self.relogio.avancar(espera_ms / 1000.0)
        self.assertIsNotNone(self.estado.proximo_bonus_vencido(self.relogio()))

    def test_d_pontos_ok_mas_creditar_falha_reagenda_como_pendente(self) -> None:
        self._inserir_pendente("cid-d")

        with (
            patch("app.bonus_worker.consultar_pontos", return_value=_pontos_ok()),
            patch("app.bonus_worker.creditar_bonus", return_value=_bonus_falha()),
        ):
            processou = self.worker.rodada()

        self.assertTrue(processou)
        linha = self.estado.buscar("cid-d", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "PENDENTE")
        self.assertEqual(linha.bonus_tentativas, 1)

    def test_e_creditar_definitivo_400_continua_pendente_e_reagenda(self) -> None:
        self._inserir_pendente("cid-e")

        with (
            patch("app.bonus_worker.consultar_pontos", return_value=_pontos_ok()),
            patch(
                "app.bonus_worker.creditar_bonus",
                return_value=_bonus_falha("definitivo", 400, "status_400"),
            ),
        ):
            processou = self.worker.rodada()

        self.assertTrue(processou)
        linha = self.estado.buscar("cid-e", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "PENDENTE")
        self.assertEqual(linha.bonus_tentativas, 1)

    def test_f_nada_vencido_devolve_false_sem_chamar_dependencias(self) -> None:
        with (
            patch("app.bonus_worker.consultar_pontos") as m_pts,
            patch("app.bonus_worker.creditar_bonus") as m_cred,
        ):
            processou = self.worker.rodada()

        self.assertFalse(processou)
        m_pts.assert_not_called()
        m_cred.assert_not_called()

    def test_g_recuo_exponencial_e_teto(self) -> None:
        inicial = CONFIG.bonus_backoff_initial_ms
        maximo = CONFIG.bonus_backoff_max_ms
        self.assertEqual(calcular_espera_ms(0, inicial, maximo, 0.0), 500.0)
        self.assertEqual(calcular_espera_ms(1, inicial, maximo, 0.0), 1000.0)
        self.assertEqual(calcular_espera_ms(2, inicial, maximo, 0.0), 2000.0)
        self.assertEqual(calcular_espera_ms(3, inicial, maximo, 0.0), 4000.0)
        self.assertEqual(calcular_espera_ms(4, inicial, maximo, 0.0), 8000.0)
        self.assertEqual(calcular_espera_ms(5, inicial, maximo, 0.0), float(maximo))
        self.assertEqual(calcular_espera_ms(10, inicial, maximo, 25.0), float(maximo) + 25.0)

    def test_h_falha_seguida_de_sucesso_credita_exatamente_uma_vez(self) -> None:
        self._inserir_pendente("cid-h")

        with (
            patch(
                "app.bonus_worker.consultar_pontos",
                side_effect=[_pontos_falha("conexao"), _pontos_ok()],
            ),
            patch("app.bonus_worker.creditar_bonus", return_value=_bonus_ok()) as m_cred,
        ):
            # Rodada 1: falha na consulta de pontos -> reagenda sem creditar
            self.assertTrue(self.worker.rodada())
            self.assertEqual(m_cred.call_count, 0)

            # Avança o relógio até o próximo vencimento
            espera_s = (
                calcular_espera_ms(
                    1,
                    CONFIG.bonus_backoff_initial_ms,
                    CONFIG.bonus_backoff_max_ms,
                    0.0,
                )
                / 1000.0
            )
            self.relogio.avancar(espera_s)

            # Rodada 2: consulta ok sem cid -> credita uma única vez
            self.assertTrue(self.worker.rodada())
            self.assertEqual(m_cred.call_count, 1)

            # Rodada 3: fila vazia
            self.assertFalse(self.worker.rodada())
            self.assertEqual(m_cred.call_count, 1)

        linha = self.estado.buscar("cid-h", "LA3001", "2026-12-01", "joao")
        assert linha is not None
        self.assertEqual(linha.bonus_estado, "CREDITADO")

    def test_i_iniciar_e_parar_com_thread_real(self) -> None:
        estado_real = Estado(
            os.path.join(self.tmp_dir.name, "worker_real.db"),
            bonus_lease_s=0.0,
        )
        estado_real.iniciar_compra("cid-thread", "LA3001", "2026-12-01", "joao")
        estado_real.concluir_vendida(
            "cid-thread",
            "LA3001",
            "2026-12-01",
            "joao",
            "tx-thread",
            200,
            201,
            '{"transactionId":"tx-thread"}',
        )

        worker_real = BonusWorker(estado_real, aleatorio_ms=lambda _m: 0.0)
        self.addCleanup(worker_real.parar)

        with (
            patch("app.bonus_worker.consultar_pontos", return_value=_pontos_ok()),
            patch("app.bonus_worker.creditar_bonus", return_value=_bonus_ok()) as m_cred,
        ):
            worker_real.iniciar()
            self.assertTrue(worker_real.esta_vivo())

            prazo_limite = time.monotonic() + 3.0
            while time.monotonic() < prazo_limite:
                linha = estado_real.buscar("cid-thread", "LA3001", "2026-12-01", "joao")
                if linha is not None and linha.bonus_estado == "CREDITADO":
                    break
                time.sleep(0.02)

            worker_real.parar()
            self.assertFalse(worker_real.esta_vivo())
            self.assertEqual(m_cred.call_count, 1)

        linha_final = estado_real.buscar("cid-thread", "LA3001", "2026-12-01", "joao")
        assert linha_final is not None
        self.assertEqual(linha_final.bonus_estado, "CREDITADO")

    def test_j_iniciar_duas_vezes_nao_cria_duas_threads(self) -> None:
        worker = BonusWorker(self.estado, relogio=self.relogio, aleatorio_ms=lambda _m: 0.0)
        self.addCleanup(worker.parar)

        worker.iniciar()
        primeira = worker._thread
        self.assertIsNotNone(primeira)
        worker.iniciar()

        self.assertIs(worker._thread, primeira)
        self.assertTrue(worker.esta_vivo())

        worker.parar()
        self.assertFalse(worker.esta_vivo())

    def test_k_depois_de_parar_iniciar_cria_thread_nova(self) -> None:
        worker = BonusWorker(self.estado, relogio=self.relogio, aleatorio_ms=lambda _m: 0.0)
        self.addCleanup(worker.parar)

        worker.iniciar()
        primeira = worker._thread
        worker.parar()
        self.assertFalse(worker.esta_vivo())

        worker.iniciar()
        self.assertTrue(worker.esta_vivo())
        self.assertIsNot(worker._thread, primeira)

        worker.parar()
        self.assertFalse(worker.esta_vivo())


if __name__ == "__main__":
    unittest.main()
