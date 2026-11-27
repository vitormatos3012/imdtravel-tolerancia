from collections.abc import Callable
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import socket
import threading
import time
import unittest
import requests
import urllib3.exceptions
from app.clientes import (
    buscar_voo,
    classificar_excecao,
    creditar_bonus,
    obter_taxa,
    vender,
)


def _iniciar_http_server(
    responder: Callable[[str, str, bytes], tuple[int, str]],
) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def _processar(self) -> None:
            tamanho = int(self.headers.get("Content-Length", "0"))
            corpo = self.rfile.read(tamanho) if tamanho > 0 else b""
            status, payload = responder(self.command, self.path, corpo)
            dados = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self) -> None:
            self._processar()

        def do_POST(self) -> None:
            self._processar()

        def log_message(self, format: str, *args: object) -> None:
            return

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    porta = servidor.server_address[1]
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    return servidor, f"http://127.0.0.1:{porta}"


def _porta_fechada() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _iniciar_socket_silencioso(
    evento_parar: threading.Event,
    contador_conexoes: list[int] | None = None,
) -> tuple[socket.socket, str]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(0.05)
    porta = srv.getsockname()[1]

    def _loop() -> None:
        conexoes: list[socket.socket] = []
        try:
            while not evento_parar.is_set():
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                if contador_conexoes is not None:
                    contador_conexoes[0] += 1
                conexoes.append(conn)
            evento_parar.wait(0.2)
        finally:
            for c in conexoes:
                c.close()
            srv.close()

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{porta}"


def _iniciar_socket_fecha_apos_ler(
    evento_parar: threading.Event,
    contador_conexoes: list[int] | None = None,
) -> tuple[socket.socket, str]:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    srv.settimeout(0.05)
    porta = srv.getsockname()[1]

    def _loop() -> None:
        try:
            while not evento_parar.is_set():
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                if contador_conexoes is not None:
                    contador_conexoes[0] += 1
                conn.settimeout(0.2)
                try:
                    conn.recv(4096)
                except OSError:
                    pass
                finally:
                    conn.close()
        finally:
            srv.close()

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return srv, f"http://127.0.0.1:{porta}"


class TestClientes(unittest.TestCase):
    def _registrar_http(
        self,
        responder: Callable[[str, str, bytes], tuple[int, str]],
    ) -> str:
        srv, url = _iniciar_http_server(responder)
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return url

    def _registrar_silencioso(
        self,
        contador_conexoes: list[int] | None = None,
    ) -> str:
        parar = threading.Event()
        srv, url = _iniciar_socket_silencioso(parar, contador_conexoes)
        self.addCleanup(srv.close)
        self.addCleanup(parar.set)
        return url

    def _registrar_fecha_apos_ler(
        self,
        contador_conexoes: list[int] | None = None,
    ) -> str:
        parar = threading.Event()
        srv, url = _iniciar_socket_fecha_apos_ler(parar, contador_conexoes)
        self.addCleanup(srv.close)
        self.addCleanup(parar.set)
        return url

    def test_vender_classificacoes(self) -> None:
        url_ok = self._registrar_http(
            lambda m, p, c: (201, '{"transactionId": "tx-123"}')
        )
        res_ok = vender("LA3000", "2026-12-01", "cid-1", 500, base_url=url_ok)
        self.assertEqual(res_ok.tipo, "ok")
        self.assertEqual(res_ok.status, 201)
        self.assertEqual(res_ok.dados, {"transactionId": "tx-123"})

        url_sem_tx = self._registrar_http(lambda m, p, c: (201, '{"ok": true}'))
        res_sem_tx = vender("LA3000", "2026-12-01", "cid-2", 500, base_url=url_sem_tx)
        self.assertEqual(res_sem_tx.tipo, "incerto")
        self.assertEqual(res_sem_tx.status, 201)
        self.assertEqual(res_sem_tx.motivo, "201_sem_transactionId")

        url_409 = self._registrar_http(lambda m, p, c: (409, '{"error": "sold-out"}'))
        res_409 = vender("LA3000", "2026-12-01", "cid-3", 500, base_url=url_409)
        self.assertEqual(res_409.tipo, "definitivo")
        self.assertEqual(res_409.status, 409)
        self.assertEqual(res_409.motivo, "status_409")

        url_400 = self._registrar_http(lambda m, p, c: (400, '{"error": "bad"}'))
        res_400 = vender("LA3000", "2026-12-01", "cid-4", 500, base_url=url_400)
        self.assertEqual(res_400.tipo, "falha_segura")
        self.assertEqual(res_400.status, 400)
        self.assertEqual(res_400.motivo, "status_400")

        url_500 = self._registrar_http(lambda m, p, c: (500, '{"error": "boom"}'))
        res_500 = vender("LA3000", "2026-12-01", "cid-5", 500, base_url=url_500)
        self.assertEqual(res_500.tipo, "incerto")
        self.assertEqual(res_500.status, 500)
        self.assertEqual(res_500.motivo, "status_500")

        url_silencio = self._registrar_silencioso()
        res_silencio = vender("LA3000", "2026-12-01", "cid-6", 300, base_url=url_silencio)
        self.assertEqual(res_silencio.tipo, "incerto")
        self.assertEqual(res_silencio.motivo, "timeout")

        url_fecha = self._registrar_fecha_apos_ler()
        res_fecha = vender("LA3000", "2026-12-01", "cid-7", 500, base_url=url_fecha)
        self.assertEqual(res_fecha.tipo, "incerto")
        self.assertEqual(res_fecha.motivo, "conexao_interrompida")

        porta_livre = _porta_fechada()
        res_recusada = vender(
            "LA3000",
            "2026-12-01",
            "cid-8",
            500,
            base_url=f"http://127.0.0.1:{porta_livre}",
        )
        self.assertEqual(res_recusada.tipo, "falha_segura")
        self.assertEqual(res_recusada.motivo, "conexao_recusada")

    def test_vender_nao_retenta(self) -> None:
        conexoes = [0]
        url_fecha = self._registrar_fecha_apos_ler(contador_conexoes=conexoes)
        res = vender("LA3000", "2026-12-01", "cid-retry", 500, base_url=url_fecha)
        time.sleep(0.05)
        self.assertEqual(res.tipo, "incerto")
        self.assertEqual(conexoes[0], 1)

    def test_buscar_voo_classificacoes(self) -> None:
        url_ok = self._registrar_http(
            lambda m, p, c: (200, '{"flight": "LA3000", "priceUSD": 199.90}')
        )
        res_ok = buscar_voo("LA3000", "2026-12-01", "cid-v1", 500, base_url=url_ok)
        self.assertEqual(res_ok.tipo, "ok")
        self.assertEqual(res_ok.status, 200)
        self.assertEqual(res_ok.dados, {"priceUSD": Decimal("199.90")})

        url_404 = self._registrar_http(lambda m, p, c: (404, '{"error": "not-found"}'))
        res_404 = buscar_voo("LA3000", "2026-12-01", "cid-v2", 500, base_url=url_404)
        self.assertEqual(res_404.tipo, "definitivo")
        self.assertEqual(res_404.status, 404)
        self.assertEqual(res_404.motivo, "status_404")

        url_500 = self._registrar_http(lambda m, p, c: (500, "erro"))
        res_500 = buscar_voo("LA3000", "2026-12-01", "cid-v3", 500, base_url=url_500)
        self.assertEqual(res_500.tipo, "falha_segura")
        self.assertEqual(res_500.motivo, "status_500")

        url_invalido = self._registrar_http(lambda m, p, c: (200, "nao-json"))
        res_inv = buscar_voo("LA3000", "2026-12-01", "cid-v4", 500, base_url=url_invalido)
        self.assertEqual(res_inv.tipo, "falha_segura")
        self.assertEqual(res_inv.motivo, "resposta_invalida")

        url_silencio = self._registrar_silencioso()
        res_sil = buscar_voo("LA3000", "2026-12-01", "cid-v5", 250, base_url=url_silencio)
        self.assertEqual(res_sil.tipo, "falha_segura")
        self.assertEqual(res_sil.motivo, "timeout")

    def test_obter_taxa_classificacoes(self) -> None:
        url_ok = self._registrar_http(
            lambda m, p, c: (200, '{"rate": 5.45, "asOf": "2026-11-27T04:59:54Z"}')
        )
        res_ok = obter_taxa("cid-t1", 500, base_url=url_ok)
        self.assertEqual(res_ok.tipo, "ok")
        self.assertEqual(
            res_ok.dados,
            {"rate": Decimal("5.45"), "asOf": "2026-11-27T04:59:54Z"},
        )

        url_virgula = self._registrar_http(
            lambda m, p, c: (200, '{"rate": "5,50", "asOf": "2026-11-27T04:59:54Z"}')
        )
        res_virg = obter_taxa("cid-t2", 500, base_url=url_virgula)
        self.assertEqual(res_virg.tipo, "falha_segura")
        self.assertEqual(res_virg.motivo, "taxa_invalida")

        url_zero = self._registrar_http(
            lambda m, p, c: (200, '{"rate": 0, "asOf": "2026-11-27T04:59:54Z"}')
        )
        res_zero = obter_taxa("cid-t3", 500, base_url=url_zero)
        self.assertEqual(res_zero.tipo, "falha_segura")
        self.assertEqual(res_zero.motivo, "taxa_invalida")

    def test_creditar_bonus_classificacoes(self) -> None:
        url_ok = self._registrar_http(lambda m, p, c: (200, '{"credited": true}'))
        res_ok = creditar_bonus("joao", 100, "cid-b1", 500, base_url=url_ok)
        self.assertEqual(res_ok.tipo, "ok")
        self.assertEqual(res_ok.status, 200)

        url_400 = self._registrar_http(lambda m, p, c: (400, '{"error": "invalid"}'))
        res_400 = creditar_bonus("joao", 100, "cid-b2", 500, base_url=url_400)
        self.assertEqual(res_400.tipo, "definitivo")
        self.assertEqual(res_400.status, 400)
        self.assertEqual(res_400.motivo, "status_400")

        porta_livre = _porta_fechada()
        res_rec = creditar_bonus(
            "joao",
            100,
            "cid-b3",
            500,
            base_url=f"http://127.0.0.1:{porta_livre}",
        )
        self.assertEqual(res_rec.tipo, "falha_segura")
        self.assertEqual(res_rec.motivo, "conexao_recusada")

        url_silencio = self._registrar_silencioso()
        res_sil = creditar_bonus("joao", 100, "cid-b4", 250, base_url=url_silencio)
        self.assertEqual(res_sil.tipo, "incerto")
        self.assertEqual(res_sil.motivo, "timeout")

    def test_classificar_excecao_direto(self) -> None:
        exc_conn_timeout = requests.exceptions.ConnectTimeout("connect timeout")
        self.assertEqual(
            classificar_excecao(exc_conn_timeout),
            ("falha_segura", "connect_timeout"),
        )

        exc_read_timeout = requests.exceptions.ReadTimeout("read timeout")
        self.assertEqual(
            classificar_excecao(exc_read_timeout),
            ("incerto", "timeout"),
        )

        pool = urllib3.connectionpool.HTTPConnectionPool("127.0.0.1", port=1)
        new_conn_err = urllib3.exceptions.NewConnectionError(pool, "recusada")
        max_retry_err = urllib3.exceptions.MaxRetryError(pool, "/sell", reason=new_conn_err)
        exc_recusada = requests.exceptions.ConnectionError(max_retry_err)
        self.assertEqual(
            classificar_excecao(exc_recusada),
            ("falha_segura", "conexao_recusada"),
        )


if __name__ == "__main__":
    unittest.main()
