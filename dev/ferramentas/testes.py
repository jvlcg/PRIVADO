# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Testes das ferramentas do cofre, sem servidores ligados (as chamadas de rede sao trocadas por respostas prontas).
Roda pelo testar-cofre.ps1 (menu, opcao 18) ou:  uv run --offline --script testes.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import central  # noqa: E402
import sabio  # noqa: E402


class PedidoLocal(unittest.TestCase):
    def test_programa_local_sem_origin_passa(self):
        self.assertTrue(sabio.pedido_local_ok("127.0.0.1:8070", None))
        self.assertTrue(sabio.pedido_local_ok("localhost:8090", None))
        self.assertTrue(sabio.pedido_local_ok("[::1]:8070", None))

    def test_pagina_do_proprio_servidor_passa(self):
        self.assertTrue(sabio.pedido_local_ok("127.0.0.1:8070", "http://127.0.0.1:8070"))
        self.assertTrue(sabio.pedido_local_ok("192.168.0.10:8090", "http://192.168.0.10:8090"))

    def test_outro_site_e_barrado(self):
        self.assertFalse(sabio.pedido_local_ok("127.0.0.1:8070", "https://site-estranho.example"))
        self.assertFalse(sabio.pedido_local_ok("127.0.0.1:8070", "null"))
        self.assertFalse(sabio.pedido_local_ok("127.0.0.1:8070", "http://127.0.0.1:9999"))

    def test_nome_de_dominio_e_barrado(self):
        # DNS rebinding: um dominio do atacante que aponta para 127.0.0.1.
        self.assertFalse(sabio.pedido_local_ok("ataque.example:8070", None))
        self.assertFalse(sabio.pedido_local_ok("", None))


class BuscaNasBibliotecas(unittest.TestCase):
    LIVROS = [("wikipedia_pt", "pt"), ("wiktionary_pt", "pt"), ("wikipedia_en", "en"), ("mdwiki_en", "en"),
              ("stackoverflow.com_en", "en"), ("maps_en_brazil", "en")]

    @staticmethod
    def resultados(livro: str, n: int) -> list[tuple[str, str]]:
        return [(f"{livro} {i}", f"/content/{livro}/A{i}") for i in range(n)]

    def test_uma_busca_por_idioma_sem_mapas_nem_stackoverflow(self):
        pedidos = []

        def falsa(params):
            pedidos.append([v for k, v in params if k == "books.name"])
            return self.resultados("wikipedia_pt", 5) if "wikipedia_pt" in pedidos[-1] else self.resultados("wikipedia_en", 5)

        with mock.patch.object(sabio, "_itens_busca", side_effect=falsa):
            sabio.buscar_kiwix({"pt": "agua", "en": "water"}, self.LIVROS, 3, 12)
        self.assertEqual(len(pedidos), 2)
        self.assertEqual(pedidos[0], ["wikipedia_pt", "wiktionary_pt"])
        self.assertEqual(pedidos[1], ["wikipedia_en", "mdwiki_en"])

    def test_alterna_idiomas_e_limita_por_biblioteca(self):
        def falsa(params):
            nomes = [v for k, v in params if k == "books.name"]
            return self.resultados("wikipedia_pt", 6) if "wikipedia_pt" in nomes else self.resultados("wikipedia_en", 6) + self.resultados("mdwiki_en", 2)

        with mock.patch.object(sabio, "_itens_busca", side_effect=falsa):
            achados = sabio.buscar_kiwix({"pt": "agua", "en": "water"}, self.LIVROS, 3, 12)
        livros = [link.split("/")[2] for _, link in achados]
        self.assertEqual(livros[:2], ["wikipedia_pt", "wikipedia_en"])
        self.assertEqual(livros.count("wikipedia_pt"), 3)
        self.assertEqual(livros.count("wikipedia_en"), 3)
        self.assertEqual(livros.count("mdwiki_en"), 2)

    def test_codigo_inclui_stackoverflow(self):
        nomes_en = []

        def falsa(params):
            nomes = [v for k, v in params if k == "books.name"]
            if "wikipedia_en" in nomes:
                nomes_en.extend(nomes)
            return []

        with mock.patch.object(sabio, "_itens_busca", side_effect=falsa):
            sabio.buscar_kiwix({"pt": "x", "en": "x"}, self.LIVROS, 3, 12, ("maps_",))
        self.assertIn("stackoverflow.com_en", nomes_en)
        self.assertNotIn("maps_en_brazil", nomes_en)

    def test_volta_ao_livro_a_livro_se_a_busca_conjunta_falhar(self):
        def falsa(params):
            nomes = [v for k, v in params if k == "books.name"]
            if len(nomes) > 1:
                raise ValueError("livros de idiomas diferentes")
            return self.resultados(nomes[0], 1)

        with mock.patch.object(sabio, "_itens_busca", side_effect=falsa):
            achados = sabio.buscar_kiwix({"pt": "x", "en": "x"}, self.LIVROS, 3, 12)
        self.assertEqual(sorted(link.split("/")[2] for _, link in achados),
                         ["mdwiki_en", "wikipedia_en", "wikipedia_pt", "wiktionary_pt"])

    def test_ignora_paginas_de_indice_do_stack_exchange(self):
        xml = ("<rss><channel>"
               "<item><title>Highest Voted 'water' Questions</title><link>/content/diy/questions/tagged/water</link></item>"
               "<item><title>How to filter water?</title><link>/content/diy/questions/1/filter</link></item>"
               "</channel></rss>")
        with mock.patch.object(sabio, "http_texto", return_value=xml):
            self.assertEqual(sabio._itens_busca([("pattern", "water")]), [("How to filter water?", "/content/diy/questions/1/filter")])


class Texto(unittest.TestCase):
    def test_html_para_texto_tira_menus_e_scripts(self):
        pagina = ("<nav>Menu</nav><h1>Agua</h1><script>x()</script><p>Ferva por um minuto.</p>"
                  "<table><tr><td>celula-da-tabela</td></tr></table>")
        texto = sabio.html_para_texto(pagina)
        self.assertIn("Ferva por um minuto.", texto)
        for lixo in ("Menu", "x()", "celula-da-tabela"):
            self.assertNotIn(lixo, texto)

    def test_fatiar_respeita_o_tamanho_e_sobrepoe(self):
        paragrafos = "\n\n".join(f"Paragrafo {i} " + "palavra " * 30 for i in range(20))
        trechos = sabio.fatiar(paragrafos, tamanho=600, sobra=100)
        self.assertGreater(len(trechos), 3)
        self.assertTrue(all(len(t) < 900 for t in trechos))


class Chave(unittest.TestCase):
    def test_variavel_de_ambiente_tem_prioridade(self):
        with mock.patch.dict(os.environ, {"SABIO_CHAVE": "chave-de-teste"}):
            self.assertEqual(sabio.chave_api(), "chave-de-teste")

    def test_chave_so_vai_para_o_servidor_de_modelos(self):
        enviados = []

        class Resposta:
            def __init__(self):
                self.dados = b"{}"

            def read(self):
                return self.dados

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def falsa(req, timeout):
            enviados.append(dict(req.header_items()))
            return Resposta()

        with mock.patch.dict(os.environ, {"SABIO_CHAVE": "segredo"}), mock.patch.object(sabio.urllib.request, "urlopen", side_effect=falsa):
            sabio.http_json(f"{sabio.LLM}/v1/models")
            sabio.http_json("http://outro-servidor.example/api")
        self.assertEqual(enviados[0].get("Authorization"), "Bearer segredo")
        self.assertNotIn("Authorization", enviados[1])


class Mapa(unittest.TestCase):
    def setUp(self):
        central._mapa.update(quando=0.0, url=None)

    def test_prefere_o_mapa_do_brasil(self):
        livros = [("maps_en_south-america_2026-08", "en"), ("maps_en_brazil_2026-06", "en"), ("wikipedia_pt", "pt")]
        with mock.patch.object(sabio, "livros_kiwix", return_value=livros):
            self.assertEqual(central.endereco_mapa(), f"{sabio.KIWIX}/content/maps_en_brazil_2026-06")

    def test_sem_mapa(self):
        with mock.patch.object(sabio, "livros_kiwix", return_value=[("wikipedia_pt", "pt")]):
            self.assertIsNone(central.endereco_mapa())


class _LlamaFalso(BaseHTTPRequestHandler):
    """Imita o llama-server em streaming: um pedaco de texto a cada 0,1 s. Anota se o cliente desligou."""
    pedacos = 3
    desconectou = threading.Event()

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for i in range(self.pedacos):
                self.wfile.write(f'data: {json.dumps({"choices": [{"delta": {"content": f"parte{i} "}}]})}\n\n'.encode())
                self.wfile.flush()
                time.sleep(0.1)
            fim = {"choices": [{"delta": {}}], "timings": {"predicted_n": self.pedacos, "predicted_per_second": 10.0}}
            self.wfile.write(f"data: {json.dumps(fim)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except OSError:
            type(self).desconectou.set()


class GeracaoInterrompivel(unittest.TestCase):
    """O "Responder agora" corta a geracao no meio e aproveita o que ja veio."""

    def setUp(self):
        _LlamaFalso.desconectou.clear()
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), _LlamaFalso)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.endereco = mock.patch.object(sabio, "LLM", f"http://127.0.0.1:{self.servidor.server_address[1]}")
        self.endereco.start()

    def tearDown(self):
        self.endereco.stop()
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_geracao_completa(self):
        _LlamaFalso.pedacos = 3
        r = sabio.chat_em_fluxo({"model": "x", "messages": []})
        self.assertFalse(r["interrompido"])
        self.assertEqual(r["texto"], "parte0 parte1 parte2")
        self.assertEqual(r["timings"]["predicted_n"], 3)

    def test_responder_agora_corta_a_conexao_e_guarda_o_texto(self):
        _LlamaFalso.pedacos = 100  # 10 s se ninguem parar
        parar = threading.Event()
        threading.Timer(0.35, parar.set).start()
        inicio = time.time()
        r = sabio.chat_em_fluxo({"model": "x", "messages": []}, parar)
        self.assertTrue(r["interrompido"])
        self.assertLess(time.time() - inicio, 3)
        self.assertTrue(r["texto"].startswith("parte0"))
        # O servidor percebe que o cliente saiu (no llama-server, isso faz ele parar de gerar).
        self.assertTrue(_LlamaFalso.desconectou.wait(3))


class Responder(unittest.TestCase):
    FONTES = [("Agua", "http://x/a", "Ferva por um minuto.")]

    def test_cortada_no_raciocinio_refaz_sem_raciocinar(self):
        respostas = [{"texto": "", "timings": {}, "interrompido": True},
                     {"texto": "Ferva a agua por 1 minuto [1].", "timings": {}, "interrompido": False}]
        with mock.patch.object(sabio, "chat_em_fluxo", side_effect=respostas) as falso:
            texto = sabio.responder("como purificar agua?", self.FONTES, "m", threading.Event())
        self.assertEqual(texto, "Ferva a agua por 1 minuto [1].")
        self.assertFalse(falso.call_args_list[1].args[0]["chat_template_kwargs"]["enable_thinking"])

    def test_cortada_com_texto_util_devolve_o_que_tinha(self):
        parcial = "Ferva a agua por pelo menos um minuto e guarde em recipiente limpo e tampado [1]."
        with mock.patch.object(sabio, "chat_em_fluxo", return_value={"texto": parcial, "timings": {}, "interrompido": True}) as falso:
            texto = sabio.responder("como purificar agua?", self.FONTES, "m", threading.Event())
        self.assertTrue(texto.startswith(parcial))
        self.assertIn("interrompida a pedido", texto)
        self.assertEqual(falso.call_count, 1)

    def test_agora_antes_de_comecar_nem_raciocina(self):
        parar = threading.Event()
        parar.set()
        with mock.patch.object(sabio, "chat_em_fluxo", return_value={"texto": "ok", "timings": {}, "interrompido": False}) as falso:
            sabio.responder("pergunta", self.FONTES, "m", parar)
        corpo = falso.call_args.args[0]
        self.assertFalse(corpo["chat_template_kwargs"]["enable_thinking"])
        self.assertNotIn("thinking_budget_tokens", corpo)


class Energia(unittest.TestCase):
    def test_texto_custo_na_tarifa_de_goias(self):
        with mock.patch.object(central, "energia", return_value={"tarifa_kwh": 1.25}):
            self.assertEqual(central.texto_custo(1.4), "~1,4 Wh ≈ R$ 0,002")
            self.assertEqual(central.texto_custo(250), "~250 Wh ≈ R$ 0,31")
            self.assertEqual(central.texto_custo(2400), "~2,40 kWh ≈ R$ 3,00")
            self.assertTrue(central.texto_custo(0.1).endswith("menos de R$ 0,001"))

    def test_consumo_do_pc(self):
        self.assertEqual(central.consumo_pc(10, 0.0), round((10 + 35 + 40) / 0.88))
        self.assertIsNone(central.consumo_pc(None, 0.5))


if __name__ == "__main__":
    unittest.main(verbosity=1)
