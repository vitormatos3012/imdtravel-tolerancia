import math
import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.clientes import Resultado
from app.config import CONFIG
from app.disjuntor import DISJUNTORES, Disjuntor, executar, reiniciar_todos


class _RelogioFalso:
    def __init__(self, agora: float = 1000.0) -> None:
        self.agora = agora

    def __call__(self) -> float:
        return self.agora

    def avancar(self, segundos: float) -> None:
        self.agora += segundos


def _resultado(tipo: str) -> Resultado:
    return Resultado(
        tipo=tipo,  # type: ignore[arg-type]
        status=None,
        dados=None,
        motivo="teste",
        ms=1.0,
    )


class TestDisjuntor(unittest.TestCase):
    def setUp(self) -> None:
        self.relogio = _RelogioFalso()
        self.d = Disjuntor("teste", 3.0, 0.1, 10.0, self.relogio)

    def _abrir(self) -> None:
        for _ in range(3):
            self.d.registrar(False)
        self.assertEqual(self.d.estado(), "aberto")

    def test_01_abaixo_do_limiar_continua_fechado(self) -> None:
        self.d.registrar(False)
        self.d.registrar(False)
        self.assertEqual(self.d.estado(), "fechado")
        self.assertTrue(self.d.permite())

    def test_02_tres_falhas_seguidas_abrem(self) -> None:
        self._abrir()

    def test_03_falhas_espacadas_nao_abrem(self) -> None:
        for _ in range(10):
            self.d.registrar(False)
            self.assertEqual(self.d.estado(), "fechado")
            self.relogio.avancar(20.0)

    def test_04_aberto_nao_permite_antes_de_aberto_s(self) -> None:
        self._abrir()
        self.relogio.avancar(9.9)
        self.assertFalse(self.d.permite())
        self.assertEqual(self.d.estado(), "aberto")

    def test_05_depois_de_aberto_s_so_uma_sonda(self) -> None:
        self._abrir()
        self.relogio.avancar(10.0)
        self.assertTrue(self.d.permite())
        self.assertEqual(self.d.estado(), "meio-aberto")
        self.assertFalse(self.d.permite())

    def test_06_sonda_com_sucesso_fecha_e_zera_nivel(self) -> None:
        self._abrir()
        self.relogio.avancar(10.0)
        self.assertTrue(self.d.permite())
        self.d.registrar(True)
        self.assertEqual(self.d.estado(), "fechado")
        # Nível zerado: duas falhas não bastam para abrir de novo.
        self.d.registrar(False)
        self.d.registrar(False)
        self.assertEqual(self.d.estado(), "fechado")
        self.d.registrar(False)
        self.assertEqual(self.d.estado(), "aberto")

    def test_07_sonda_com_falha_reabre_e_reinicia_contagem(self) -> None:
        self._abrir()
        self.relogio.avancar(10.0)
        self.assertTrue(self.d.permite())
        self.relogio.avancar(5.0)
        self.d.registrar(False)
        self.assertEqual(self.d.estado(), "aberto")
        self.relogio.avancar(9.0)
        self.assertFalse(self.d.permite())
        self.relogio.avancar(1.0)
        self.assertTrue(self.d.permite())

    def test_08_registrar_enquanto_aberto_e_ignorado(self) -> None:
        self._abrir()
        self.relogio.avancar(5.0)
        self.d.registrar(True)
        self.d.registrar(False)
        self.assertEqual(self.d.estado(), "aberto")
        # aberto_em não foi reiniciado: 10 s depois da abertura original a sonda passa.
        self.relogio.avancar(5.0)
        self.assertTrue(self.d.permite())

    def test_09_sonda_que_nunca_reporta_libera_nova_sonda(self) -> None:
        self._abrir()
        self.relogio.avancar(10.0)
        self.assertTrue(self.d.permite())
        self.relogio.avancar(5.0)
        self.assertFalse(self.d.permite())
        self.relogio.avancar(5.0)
        self.assertTrue(self.d.permite())
        self.assertEqual(self.d.estado(), "meio-aberto")

    def test_10_esta_aberto_nao_consome_a_sonda(self) -> None:
        self._abrir()
        self.assertTrue(self.d.esta_aberto())
        self.relogio.avancar(10.0)
        for _ in range(3):
            self.assertFalse(self.d.esta_aberto())
        self.assertEqual(self.d.estado(), "aberto")
        self.assertTrue(self.d.permite())
        self.assertEqual(self.d.estado(), "meio-aberto")


class TestExecutar(unittest.TestCase):
    def setUp(self) -> None:
        self.relogio = _RelogioFalso()
        reiniciar_todos(self.relogio)
        self.addCleanup(reiniciar_todos)
        self.falhas_para_abrir = math.ceil(CONFIG.breaker_threshold)

    def _abrir(self, alvo: str) -> None:
        for _ in range(self.falhas_para_abrir):
            DISJUNTORES[alvo].registrar(False)
        self.assertEqual(DISJUNTORES[alvo].estado(), "aberto")

    def test_11a_fechado_chama_e_registra(self) -> None:
        res_ok = _resultado("ok")
        chamada = MagicMock(return_value=res_ok)
        self.assertIs(executar("flight", chamada), res_ok)
        chamada.assert_called_once()

        chamada_falha = MagicMock(return_value=_resultado("falha_segura"))
        for _ in range(self.falhas_para_abrir):
            executar("flight", chamada_falha)
        self.assertEqual(DISJUNTORES["flight"].estado(), "aberto")

    def test_11b_aberto_nao_chama_e_devolve_disjuntor_aberto(self) -> None:
        self._abrir("flight")
        chamada = MagicMock(return_value=_resultado("ok"))
        res = executar("flight", chamada)
        chamada.assert_not_called()
        self.assertEqual(res.tipo, "falha_segura")
        self.assertEqual(res.motivo, "disjuntor_aberto")
        self.assertIsNone(res.status)
        self.assertIsNone(res.dados)
        self.assertEqual(res.ms, 0.0)

    def test_11c_definitivo_conta_como_sucesso(self) -> None:
        self._abrir("convert")
        self.relogio.avancar(CONFIG.breaker_open_s)
        executar("convert", lambda: _resultado("definitivo"))
        self.assertEqual(DISJUNTORES["convert"].estado(), "fechado")

    def test_11d_incerto_e_falha_segura_contam_como_falha(self) -> None:
        for alvo, tipo in (("sell", "incerto"), ("bonus", "falha_segura")):
            with self.subTest(alvo=alvo, tipo=tipo):
                for _ in range(self.falhas_para_abrir):
                    executar(alvo, lambda: _resultado(tipo))
                self.assertEqual(DISJUNTORES[alvo].estado(), "aberto")

    def test_11e_excecao_da_chamada_propaga(self) -> None:
        chamada = MagicMock(side_effect=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            executar("flight", chamada)

    def test_12_reiniciar_todos_volta_tudo_para_fechado(self) -> None:
        for alvo in ("flight", "convert", "sell", "bonus"):
            self._abrir(alvo)
        dicionario = DISJUNTORES
        reiniciar_todos(self.relogio)
        self.assertIs(DISJUNTORES, dicionario)
        for alvo in ("flight", "convert", "sell", "bonus"):
            self.assertEqual(DISJUNTORES[alvo].estado(), "fechado")


if __name__ == "__main__":
    unittest.main()
