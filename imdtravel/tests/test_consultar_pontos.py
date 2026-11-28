from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import threading
import unittest
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("AIRLINESHUB_URL", "http://airlineshub.test")
os.environ.setdefault("EXCHANGE_URL", "http://exchange.test")
os.environ.setdefault("FIDELITY_URL", "http://fidelity.test")

from app.clientes import consultar_pontos

RespostaHandler = Callable[[str, dict[str, list[str]]], tuple[int, str]]


class _ServidorHttpLocal:
    def __init__(self, handler_fn: RespostaHandler) -> None:
        self._handler_fn = handler_fn

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self_req) -> None:
                parsed = urlparse(self_req.path)
                params = parse_qs(parsed.query)
                status, corpo = handler_fn(parsed.path, params)
                dados = corpo.encode("utf-8")
                self_req.send_response(status)
                self_req.send_header("Content-Type", "application/json")
                self_req.send_header("Content-Length", str(len(dados)))
                self_req.end_headers()
                self_req.wfile.write(dados)

            def log_message(self_req, format: str, *args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        porta = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{porta}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def iniciar(self) -> None:
        self._thread.start()

    def fechar(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


class _ServidorSilencioso:
    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(5)
        self._sock.settimeout(0.1)
        porta = self._sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{porta}"
        self._parar = threading.Event()
        self._conexoes: list[socket.socket] = []
        self._thread = threading.Thread(target=self._aceitar, daemon=True)

    def _aceitar(self) -> None:
        while not self._parar.is_set():
            try:
                conn, _ = self._sock.accept()
                self._conexoes.append(conn)
            except TimeoutError:
                continue
            except OSError:
                break

    def iniciar(self) -> None:
        self._thread.start()

    def fechar(self) -> None:
        self._parar.set()
        self._sock.close()
        for conn in self._conexoes:
            conn.close()
        self._thread.join(timeout=2.0)


def _porta_livre_recusada() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    return f"http://127.0.0.1:{porta}"


class TestConsultarPontos(unittest.TestCase):
    def _subir_servidor(self, fn: RespostaHandler) -> _ServidorHttpLocal:
        srv = _ServidorHttpLocal(fn)
        srv.iniciar()
        self.addCleanup(srv.fechar)
        return srv

    def test_200_com_entries_devolve_cids_e_envia_user_na_query(self) -> None:
        chamadas: list[tuple[str, dict[str, list[str]]]] = []

        def handler(path: str, params: dict[str, list[str]]) -> tuple[int, str]:
            chamadas.append((path, params))
            corpo = (
                '{"user":"joao","totalPoints":350,'
                '"entries":[{"bonus":200,"cid":"cid-a","ts":"2026-11-27T10:00:00Z"},'
                '{"bonus":150,"cid":"cid-b","ts":"2026-11-27T10:01:00Z"}]}'
            )
            return 200, corpo

        srv = self._subir_servidor(handler)
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "ok")
        self.assertEqual(res.status, 200)
        self.assertIsNotNone(res.dados)
        assert res.dados is not None
        self.assertEqual(res.dados["cids"], frozenset({"cid-a", "cid-b"}))
        self.assertEqual(chamadas, [("/points", {"user": ["joao"]})])

    def test_200_com_entries_vazia_devolve_frozenset_vazio(self) -> None:
        srv = self._subir_servidor(
            lambda _p, _q: (200, '{"user":"joao","totalPoints":0,"entries":[]}')
        )
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "ok")
        assert res.dados is not None
        self.assertEqual(res.dados["cids"], frozenset())

    def test_200_ignora_objetos_sem_cid_texto(self) -> None:
        corpo = (
            '{"user":"joao","totalPoints":300,"entries":['
            '{"bonus":100},'
            '{"bonus":100,"cid":null},'
            '{"bonus":100,"cid":123},'
            '{"bonus":100,"cid":""},'
            '{"bonus":100,"cid":"cid-valido"}]}'
        )
        srv = self._subir_servidor(lambda _p, _q: (200, corpo))
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "ok")
        assert res.dados is not None
        self.assertEqual(res.dados["cids"], frozenset({"cid-valido"}))

    def test_200_com_elemento_nao_objeto_em_entries_devolve_resposta_invalida(self) -> None:
        corpo = '{"user":"joao","totalPoints":100,"entries":[{"cid":"cid-1"}, 5]}'
        srv = self._subir_servidor(lambda _p, _q: (200, corpo))
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertEqual(res.status, 200)
        self.assertEqual(res.motivo, "resposta_invalida")

    def test_200_corpo_nao_json_devolve_resposta_invalida(self) -> None:
        srv = self._subir_servidor(lambda _p, _q: (200, "nao-eh-json"))
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertEqual(res.status, 200)
        self.assertEqual(res.motivo, "resposta_invalida")

    def test_200_sem_entries_devolve_resposta_invalida(self) -> None:
        srv = self._subir_servidor(lambda _p, _q: (200, '{"user":"joao","totalPoints":0}'))
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertEqual(res.status, 200)
        self.assertEqual(res.motivo, "resposta_invalida")

    def test_500_devolve_falha_segura_status_500(self) -> None:
        srv = self._subir_servidor(lambda _p, _q: (500, '{"error":"boom"}'))
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=srv.url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertEqual(res.status, 500)
        self.assertEqual(res.motivo, "status_500")

    def test_silencio_devolve_falha_segura_timeout(self) -> None:
        srv = _ServidorSilencioso()
        srv.iniciar()
        self.addCleanup(srv.fechar)

        res = consultar_pontos("joao", "cid-req", 50.0, base_url=srv.url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertIsNone(res.status)
        self.assertEqual(res.motivo, "timeout")

    def test_conexao_recusada_devolve_falha_segura_conexao(self) -> None:
        url = _porta_livre_recusada()
        res = consultar_pontos("joao", "cid-req", 500.0, base_url=url)

        self.assertEqual(res.tipo, "falha_segura")
        self.assertIsNone(res.status)
        self.assertEqual(res.motivo, "conexao")


if __name__ == "__main__":
    unittest.main()
