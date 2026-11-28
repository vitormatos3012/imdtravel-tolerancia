import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.admissao import Admissao
from app.config import CONFIG
from app.rotas import app

_PEDIDO = {"flight": "LA3001", "day": "2026-12-01", "user": "joao"}
_CABECALHO = {"X-Correlation-Id": "cid-rota"}


class TestBuyTicketAdmissao(unittest.TestCase):
    def setUp(self) -> None:
        self.cliente = app.test_client()

    def test_a_admissao_cheia_recusa_503_overloaded_sem_chamar_comprar(self) -> None:
        adm = Admissao(1)
        self.assertTrue(adm.tentar_entrar())
        with patch("app.rotas.ADMISSAO", adm), patch("app.rotas.comprar") as m_comprar:
            resp = self.cliente.post("/buyTicket", json=_PEDIDO, headers=_CABECALHO)

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(
            resp.get_json(),
            {
                "error": "overloaded",
                "outcome": "not-sold",
                "correlationId": "cid-rota",
            },
        )
        self.assertEqual(resp.headers.get("Retry-After"), str(CONFIG.retry_after_s))
        m_comprar.assert_not_called()
        self.assertEqual(adm.em_andamento(), 1)

    def test_b_com_vaga_chama_comprar_e_devolve_a_vaga(self) -> None:
        adm = Admissao(1)
        with (
            patch("app.rotas.ADMISSAO", adm),
            patch("app.rotas.comprar", return_value=(409, {"error": "sold-out"})) as m_comprar,
        ):
            resp = self.cliente.post("/buyTicket", json=_PEDIDO, headers=_CABECALHO)

        self.assertEqual(resp.status_code, 409)
        m_comprar.assert_called_once()
        self.assertEqual(adm.em_andamento(), 0)

    def test_c_excecao_em_comprar_devolve_500_e_a_vaga(self) -> None:
        adm = Admissao(1)
        with (
            patch("app.rotas.ADMISSAO", adm),
            patch("app.rotas.comprar", side_effect=RuntimeError("boom")),
        ):
            resp = self.cliente.post("/buyTicket", json=_PEDIDO, headers=_CABECALHO)

        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json(), {"error": "internal-error"})
        self.assertEqual(adm.em_andamento(), 0)


class TestHealthWorker(unittest.TestCase):
    def setUp(self) -> None:
        self.cliente = app.test_client()
        p_dir = patch("app.rotas._check_sales_dir", return_value=(True, ""))
        p_dir.start()
        self.addCleanup(p_dir.stop)

    def test_d_worker_vivo_devolve_200_com_corpo_de_sempre(self) -> None:
        with patch("app.rotas.WORKER") as m_worker:
            m_worker.esta_vivo.return_value = True
            resp = self.cliente.get("/health")

        self.assertEqual(resp.status_code, 200)
        corpo = resp.get_json()
        self.assertEqual(corpo["status"], "ok")
        self.assertIn("uptimeS", corpo)
        self.assertEqual(set(corpo.keys()), {"status", "uptimeS"})
        m_worker.iniciar.assert_not_called()

    def test_e_worker_morto_que_revive_devolve_200_e_chama_iniciar_uma_vez(self) -> None:
        with patch("app.rotas.WORKER") as m_worker:
            m_worker.esta_vivo.side_effect = [False, True]
            resp = self.cliente.get("/health")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "ok")
        m_worker.iniciar.assert_called_once_with()

    def test_f_worker_morto_que_continua_morto_devolve_503(self) -> None:
        with patch("app.rotas.WORKER") as m_worker:
            m_worker.esta_vivo.return_value = False
            resp = self.cliente.get("/health")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(
            resp.get_json(),
            {"status": "down", "reason": "bonus_worker_dead"},
        )
        m_worker.iniciar.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
