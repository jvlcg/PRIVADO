# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Testes das ferramentas do cofre, sem servidores ligados (as chamadas de rede sao trocadas por respostas prontas).
Roda pelo testar-cofre.ps1 (menu, opcao 17) ou:  uv run --offline --script testes.py
"""
from __future__ import annotations

import os
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
