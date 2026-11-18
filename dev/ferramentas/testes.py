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
import urllib.parse  # noqa: E402

import central  # noqa: E402
import sabio  # noqa: E402
import tarefas  # noqa: E402
import tempfile  # noqa: E402

# Os testes nunca leem nem gravam a ficha medica de verdade da familia.
_PASTA_DOS_TESTES = tempfile.TemporaryDirectory()
tarefas.ARQUIVO_FICHA = Path(_PASTA_DOS_TESTES.name) / "ficha-medica.json"


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

    def test_idioma_de_cada_biblioteca_pelo_catalogo(self):
        def entrada(nome, idioma):
            return (f'<entry><language>{idioma}</language><link type="text/html" href="/content/{nome}"/></entry>')
        opds = ('<feed xmlns="http://www.w3.org/2005/Atom">' + entrada("wikipedia_pt", "por") + entrada("wikimed_en", "eng")
                + entrada("lowtech_mul", "eng,fra,deu,nld,por") + entrada("pt.stackoverflow_mul", "eng,por") + "</feed>")
        with mock.patch.object(sabio, "http_texto", return_value=opds):
            self.assertEqual(sabio.livros_kiwix(), [("wikipedia_pt", "pt"), ("wikimed_en", "en"), ("lowtech_mul", "mul"),
                                                    ("pt.stackoverflow_mul", "mul")])

    def test_biblioteca_de_varios_idiomas_busca_sozinha(self):
        # O kiwix-serve responde 400 a um grupo com idiomas diferentes: a Low-tech Magazine derrubava o grupo do ingles.
        livros = [("wikipedia_pt", "pt"), ("wikipedia_en", "en"), ("mdwiki_en", "en"), ("lowtech_mul", "mul")]
        grupos = []

        def falsa(params):
            nomes = [v for k, v in params if k == "books.name"]
            grupos.append(nomes)
            if "lowtech_mul" in nomes and len(nomes) > 1:
                raise RuntimeError("HTTP 400: Two or more books in different lang")
            return [(f"{nomes[0]} artigo", f"/content/{nomes[0]}/A1")]

        with mock.patch.object(sabio, "_itens_busca", side_effect=falsa):
            r = sabio.buscar_kiwix({"pt": "energia solar", "en": "solar power"}, livros, 2, 10)
        self.assertTrue(all("lowtech_mul" not in g or len(g) == 1 for g in grupos))
        self.assertIn("/content/lowtech_mul/A1", [link for _, link in r])
        self.assertIn(["wikipedia_en", "mdwiki_en"], grupos)  # o grupo do ingles continua inteiro numa busca so

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

    def test_laco_no_raciocinio_refaz_sem_raciocinar(self):
        respostas = [{"texto": "", "timings": {}, "interrompido": False, "repetiu": "raciocinio"},
                     {"texto": "Ferva a agua por 1 minuto [1].", "timings": {}, "interrompido": False, "repetiu": None}]
        with mock.patch.object(sabio, "chat_em_fluxo", side_effect=respostas) as falso:
            texto = sabio.responder("como purificar agua?", self.FONTES, "m", threading.Event())
        self.assertEqual(texto, "Ferva a agua por 1 minuto [1].")
        self.assertFalse(falso.call_args_list[1].args[0]["chat_template_kwargs"]["enable_thinking"])

    def test_laco_na_resposta_avisa_que_cortou(self):
        r = {"texto": "Ferva a agua [1].", "timings": {}, "interrompido": False, "repetiu": "texto"}
        with mock.patch.object(sabio, "chat_em_fluxo", return_value=r):
            texto = sabio.responder("como purificar agua?", self.FONTES, "m", threading.Event())
        self.assertTrue(texto.endswith(sabio.AVISO_LACO))


class _LlamaEmLaco(BaseHTTPRequestHandler):
    """Imita um modelo que entra em laco: a mesma frase sem parar, na resposta ou no raciocinio."""
    campo = "content"
    desconectou = threading.Event()

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        frases = ["Para purificar a agua, siga estes passos. "] + ["Ferva a agua por um minuto e deixe esfriar antes de beber. "] * 400
        try:
            for frase in frases:
                self.wfile.write(f'data: {json.dumps({"choices": [{"delta": {self.campo: frase}}]})}\n\n'.encode())
                self.wfile.flush()
                time.sleep(0.002)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            type(self).desconectou.set()


class GuardaContraLaco(unittest.TestCase):
    """Ideia do Survival LLM: um modelo preso repetindo a mesma frase e cortado cedo, sem gastar a placa a toa."""

    def setUp(self):
        _LlamaEmLaco.desconectou.clear()
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), _LlamaEmLaco)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.endereco = mock.patch.object(sabio, "LLM", f"http://127.0.0.1:{self.servidor.server_address[1]}")
        self.endereco.start()

    def tearDown(self):
        self.endereco.stop()
        self.servidor.shutdown()
        self.servidor.server_close()

    def test_laco_na_resposta_e_cortado_e_fica_uma_volta(self):
        _LlamaEmLaco.campo = "content"
        r = sabio.chat_em_fluxo({"model": "x", "messages": []})
        self.assertEqual(r["repetiu"], "texto")
        self.assertTrue(r["texto"].startswith("Para purificar a agua"))
        self.assertLess(r["texto"].count("Ferva a agua"), 4)  # das 400 repeticoes ficou uma volta
        self.assertTrue(_LlamaEmLaco.desconectou.wait(3))     # o servidor percebe a saida e para

    def test_laco_no_raciocinio_e_percebido(self):
        _LlamaEmLaco.campo = "reasoning_content"
        r = sabio.chat_em_fluxo({"model": "x", "messages": []})
        self.assertEqual(r["repetiu"], "raciocinio")
        self.assertEqual(r["texto"], "")

    def test_texto_comprido_sem_repeticao_nao_e_laco(self):
        texto = " ".join(f"Passo {i}: faca a etapa numero {i} com calma e confira o resultado {i * 7}." for i in range(80))
        self.assertIsNone(sabio.em_laco(texto))


class ConferenciaDeCitacoes(unittest.TestCase):
    """Ideia do Survival LLM: a citacao [n] tem de apontar para uma fonte que a IA leu de verdade."""

    def test_normaliza_listas_e_intervalos(self):
        texto, citadas, inventadas = sabio.conferir_citacoes("Ferva [1, 2]. Filtre [2-3].", 3)
        self.assertEqual(texto, "Ferva [1][2]. Filtre [2][3].")
        self.assertEqual((citadas, inventadas), ([1, 2, 3], []))

    def test_tira_a_citacao_de_fonte_que_nao_existe(self):
        texto, citadas, inventadas = sabio.conferir_citacoes("Ferva a agua [1]. Use cloro [7].", 3)
        self.assertEqual(texto, "Ferva a agua [1]. Use cloro.")
        self.assertEqual((citadas, inventadas), ([1], [7]))

    def test_avisa_quando_inventa_ou_nao_cita(self):
        texto, citadas = sabio.conferir_resposta("Use cloro [5].", 2)
        self.assertIn("fonte que não existe ([5])", texto)
        texto, citadas = sabio.conferir_resposta("Ferva a agua por um minuto.", 3)
        self.assertIn("não citou nenhuma", texto)
        self.assertEqual(citadas, [])

    def test_sem_nota_quando_diz_que_as_fontes_nao_respondem(self):
        texto, _ = sabio.conferir_resposta("As fontes fornecidas não respondem a essa pergunta.", 3)
        self.assertNotIn("Conferido", texto)


class RegrasDeSeguranca(unittest.TestCase):
    def test_toda_resposta_do_cofre_leva_as_regras(self):
        r = {"texto": "Ferva a agua [1].", "timings": {}, "interrompido": False, "repetiu": None}
        with mock.patch.object(sabio, "chat_em_fluxo", return_value=r) as falso:
            sabio.responder("pergunta", [("A", "http://x", "t")], "m", threading.Event())
            sabio.responder_direto("pergunta", "m")
        for chamada in falso.call_args_list:
            sistema = chamada.args[0]["messages"][0]["content"]
            for regra in ("192 (SAMU)", "monoxido de carbono", "dose"):
                self.assertIn(regra, sistema)


class SaudeDoCofre(unittest.TestCase):
    """Ideia do N.O.M.A.D. e do kit da localaimaster: o painel diz o que esta atrasado, pelas datas dos registros."""

    def setUp(self):
        import tempfile
        self.pasta = tempfile.TemporaryDirectory()
        logs = Path(self.pasta.name)
        (logs / "integridade-2026-10-29.txt").write_text("ok", encoding="utf-8")
        (logs / "verificacao-2026-08-01.txt").write_text("ok", encoding="utf-8")
        self.trocas = [mock.patch.object(central, "PASTA_LOGS", logs),
                       mock.patch.object(central, "ARQ_SIMULADOS", logs / "simulados.csv"),
                       mock.patch.object(central, "ARQ_KIT", logs / "kit-de-bolso.json")]
        for t in self.trocas:
            t.start()

    def tearDown(self):
        for t in self.trocas:
            t.stop()
        self.pasta.cleanup()

    def test_em_dia_atrasado_e_nunca_feito(self):
        itens = {i["id"]: i for i in central.saude_do_cofre(central.date(2026, 11, 17))["itens"]}
        self.assertTrue(itens["integridade"]["em_dia"])              # 19 dias, a cada 90
        self.assertEqual(itens["integridade"]["dias"], 19)
        self.assertFalse(itens["novidades"]["em_dia"])               # 108 dias, a cada 30
        self.assertIsNone(itens["sincronizar"]["ultima"])            # nunca feito
        self.assertFalse(itens["simulado"]["em_dia"])

    def test_simulado_registrado_fica_em_dia_e_so_guarda_ids(self):
        r = central.registrar_simulado(["socorro", "agua", "<script>x"], 8)
        self.assertEqual((r["feitos"], r["total"]), (3, 8))
        linha = central.ARQ_SIMULADOS.read_text(encoding="utf-8").splitlines()[1]
        self.assertNotIn("<", linha)
        itens = {i["id"]: i for i in central.saude_do_cofre()["itens"]}
        self.assertTrue(itens["simulado"]["em_dia"])
        self.assertEqual(itens["simulado"]["dias"], 0)

    def test_kit_de_bolso_so_conta_pen_drive_que_terminou_bem(self):
        hoje = central.date(2026, 11, 17)
        kit = central.ARQ_KIT

        def item():
            return {i["id"]: i for i in central.saude_do_cofre(hoje)["itens"]}["kit"]
        self.assertIsNone(item()["ultima"])                                   # nunca montado
        kit.write_text('{"montado_em": "2026-11-17T22:10:00", "ok": true, "removivel": false}', encoding="utf-8")
        self.assertIsNone(item()["ultima"])                                   # pasta de teste nao conta
        kit.write_text('{"montado_em": "2026-11-17T22:10:00", "ok": false, "removivel": true}', encoding="utf-8")
        self.assertIsNone(item()["ultima"])                                   # parou no meio
        kit.write_text('{"montado_em": "2026-08-01T10:00:00", "ok": true, "removivel": true}', encoding="utf-8")
        self.assertEqual(item()["dias"], 108)
        self.assertFalse(item()["em_dia"])                                    # a cada 90 dias
        kit.write_text("nao e json", encoding="utf-8")
        self.assertIsNone(item()["ultima"])


class RegistroDeGasto(unittest.TestCase):
    def test_registra_e_soma_o_mes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "gasto-tarefas.csv"
            with mock.patch.object(sabio, "ARQUIVO_GASTOS", arquivo), mock.patch.object(sabio, "tarifa_kwh", return_value=1.25):
                self.assertEqual(sabio.gasto_mes(), {"tarefas": 0, "wh": 0.0})
                sabio.registrar_gasto("perguntar", 90, 170)   # 4,25 Wh
                sabio.registrar_gasto("conselho", 228, 183)   # 11,59 Wh
                with arquivo.open("a", encoding="utf-8") as f:
                    f.write("2020-01-01T10:00:00;velha;60;100;1.000;0.00125\n")  # outro mes: nao entra
                g = sabio.gasto_mes()
                self.assertEqual(g["tarefas"], 2)
                self.assertAlmostEqual(g["wh"], 4.25 + 11.59, places=1)
                self.assertTrue(arquivo.read_text(encoding="utf-8").startswith("data;tarefa;segundos;watts;wh;reais"))


class Energia(unittest.TestCase):
    def test_texto_custo_na_tarifa_de_goias(self):
        with mock.patch.object(sabio, "tarifa_kwh", return_value=1.25):
            self.assertEqual(central.texto_custo(1.4), "~1,4 Wh ≈ R$ 0,002")
            self.assertEqual(central.texto_custo(250), "~250 Wh ≈ R$ 0,31")
            self.assertEqual(central.texto_custo(2400), "~2,40 kWh ≈ R$ 3,00")
            self.assertTrue(central.texto_custo(0.1).endswith("menos de R$ 0,001"))

    def test_consumo_do_pc(self):
        self.assertEqual(central.consumo_pc(10, 0.0), round((10 + 35 + 40) / 0.88))
        self.assertIsNone(central.consumo_pc(None, 0.5))

    def test_gasto_por_tarefa_e_por_mes(self):
        import tempfile
        mes = time.strftime("%Y-%m")
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "gasto-tarefas.csv"
            arquivo.write_text("data;tarefa;segundos;watts;wh;reais\n"
                               f"{mes}-01T10:00:00;perguntar;90;170;4.250;0.005\n"
                               f"{mes}-02T10:00:00;conselho;228;183;11.590;0.014\n"
                               f"{mes}-03T10:00:00;perguntar;90;170;4.250;0.005\n"
                               "2020-01-01T10:00:00;velha;60;100;1.000;0.001\n", encoding="utf-8")
            with mock.patch.object(sabio, "ARQUIVO_GASTOS", arquivo):
                por_tarefa = sabio.gasto_por_tarefa()
                meses = sabio.gasto_meses(3)
        self.assertEqual([t["tarefa"] for t in por_tarefa], ["conselho", "perguntar"])  # do que mais gastou
        self.assertEqual(por_tarefa[1]["vezes"], 2)
        self.assertAlmostEqual(por_tarefa[1]["wh"], 8.5)
        self.assertEqual(len(meses), 3)
        self.assertEqual(meses[-1]["mes"], mes)
        self.assertAlmostEqual(meses[-1]["wh"], 20.09)
        self.assertEqual(meses[0]["wh"], 0)


class Vigia(unittest.TestCase):
    def test_processo_vivo_sem_matar_ninguem(self):
        self.assertTrue(central.processo_vivo(os.getpid()))
        self.assertFalse(central.processo_vivo(0))

    def test_pid_reaproveitado_por_outro_programa_nao_conta(self):
        self.assertTrue(central.processo_vivo(os.getpid(), Path(sys.executable).name))
        self.assertFalse(central.processo_vivo(os.getpid(), "powershell.exe"))

    def test_sem_arquivo_a_vigia_esta_desligada(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            with mock.patch.object(central, "PID_VIGIA", Path(pasta) / "nao-existe.pid"):
                self.assertFalse(central.vigia_ligada())
            arquivo = Path(pasta) / "vigia.pid"
            arquivo.write_text(f"{os.getpid()}\n", encoding="utf-8")
            with mock.patch.object(central, "PID_VIGIA", arquivo):
                # O PID existe, mas e deste Python, nao do PowerShell da vigia: arquivo velho, vigia desligada.
                self.assertFalse(central.vigia_ligada())
                with mock.patch.object(central, "processo_vivo", side_effect=lambda pid, programa=None: pid == os.getpid()):
                    self.assertTrue(central.vigia_ligada())


class QualFerramenta(unittest.TestCase):
    """O roteador escolhe a ferramenta sem ligar IA nenhuma."""

    def tipo_e_acoes(self, texto):
        r = tarefas.sugerir(texto)
        return r["tipo"], [s["acao"] for s in r["sugestoes"]]

    def test_cada_pedido_vai_para_a_ferramenta_certa(self):
        casos = {
            "meu filho cortou o dedo e está sangrando muito": ("emergencia", "buscar"),
            "onde fica o hospital mais próximo": ("lugar", "buscar"),
            "gere uma imagem de um gato astronauta": ("criar", "comfyui"),
            "traduza para o inglês: bom dia": ("traduzir", "chat"),
            "meu script python dá erro de import": ("codigo", "chat"),
            "quanto é 15% de 230": ("contas", "chat"),
            "estou com febre e dor de cabeça": ("saude", "fonte"),
            "devo comprar painel solar ou gerador?": ("decisao", "conselho"),
            "transcreva a gravação da reunião": ("transcrever", "menu"),
            "torniquete": ("termo", "buscar"),
            "Como purificar água da chuva para beber?": ("pergunta", "fonte"),
        }
        for texto, (tipo, primeira) in casos.items():
            with self.subTest(texto=texto):
                t, acoes = self.tipo_e_acoes(texto)
                self.assertEqual(t, tipo)
                self.assertEqual(acoes[0], primeira)
                self.assertLessEqual(len(acoes), 4)
                modos = [a for a in acoes if a in tarefas.MODOS]
                self.assertEqual(len(modos), len(set(modos)))  # nenhum modo repetido

    def test_avisos_de_emergencia_e_saude(self):
        self.assertIn("192", tarefas.sugerir("ele desmaiou e não respira")["aviso"])
        self.assertIn("médico", tarefas.sugerir("qual a dose de dipirona para criança")["aviso"])
        self.assertIsNone(tarefas.sugerir("como fazer pão caseiro")["aviso"])

    def test_casos_que_a_revisao_achou(self):
        casos = {
            "ele não consegue respirar": "emergencia",
            "meu pai está com dor no peito e falta de ar": "emergencia",
            "fui picado por um escorpião": "emergencia",
            "dor de cabeça logo depois de comer, o que pode ser?": "saude",
            "qual a função do fígado?": "saude",
            "bebê com febre de 38-39 graus, o que fazer?": "saude",
            "transcrever o vídeo de uma aula": "transcrever",
            "traduzir a letra da música para o português": "traduzir",
            "crie um logo para minha padaria": "criar",
        }
        for texto, tipo in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(tarefas.sugerir(texto)["tipo"], tipo)

    def test_vazio(self):
        self.assertEqual(tarefas.sugerir("   ")["sugestoes"], [])

    def test_palavras_da_pergunta(self):
        self.assertEqual(sabio.palavras_da_pergunta("Como purificar a água da chuva?"), ["purificar", "água", "chuva"])
        self.assertEqual(sabio.palavras_da_pergunta("o que é"), ["o", "que", "é"])  # so palavras vazias: ficam as originais


class RespostasGuardadas(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.pasta = tempfile.TemporaryDirectory()
        self.h = tarefas.Historico(Path(self.pasta.name) / "perguntas.jsonl")

    def tearDown(self):
        self.pasta.cleanup()

    def test_mesma_pergunta_com_outras_palavras_vazias(self):
        self.assertEqual(tarefas.chave("Como purificar a água da chuva?"), tarefas.chave("purificar agua chuva"))

    def test_perguntas_diferentes_tem_chaves_diferentes(self):
        # Uma resposta guardada nunca pode aparecer para a pergunta errada (ainda mais em saude).
        pares = [("O que é hepatite B?", "O que é hepatite C?"), ("diabetes tipo 1", "diabetes tipo 2"),
                 ("Posso tomar dipirona com álcool?", "Posso tomar dipirona sem álcool?"),
                 ("Quanto é 3+5?", "Quanto é 3*5?"), ("Para que serve a vitamina C?", "Para que serve a vitamina D?")]
        for a, b in pares:
            with self.subTest(a=a, b=b):
                self.assertNotEqual(tarefas.chave(a), tarefas.chave(b))

    def test_resposta_com_fonte_serve_para_rapida_mas_nao_o_contrario(self):
        self.h.guardar("Como purificar a água?", "rapida", "Ferva.")
        self.assertIsNone(self.h.procurar("como purificar agua", "fonte"))
        self.h.guardar("Como purificar a água?", "fonte", "Ferva por 1 minuto [1].", [{"titulo": "Água", "link": "x"}], 5.0)
        self.assertEqual(self.h.procurar("como purificar agua", "rapida")["modo"], "fonte")
        self.assertEqual(self.h.procurar("como purificar agua", "fonte")["fontes"][0]["titulo"], "Água")

    def test_interrompida_nao_conta(self):
        self.h.guardar("capital da bolívia", "rapida", "La Paz (resposta interrompida a pedido)", interrompida=True)
        self.assertIsNone(self.h.procurar("capital da bolívia", "rapida"))
        self.assertEqual(len(self.h.listar()), 1)  # mas aparece no historico

    def test_parecidas_listar_pegar_e_esquecer(self):
        a = self.h.guardar("como tratar queimadura de segundo grau", "fonte", "Água corrente fria por 20 minutos.")
        self.h.guardar("receita de pão caseiro", "rapida", "Farinha, água, sal e fermento.")
        parecidas = self.h.parecidas("tratamento de queimaduras de segundo grau")
        self.assertEqual([p["id"] for p in parecidas], [a["id"]])
        self.assertEqual(len(self.h.listar("corrente fria")), 1)
        self.assertEqual(self.h.listar()[0]["pergunta"], "receita de pão caseiro")  # mais recente primeiro
        self.assertEqual(self.h.pegar(a["id"])["resposta"], "Água corrente fria por 20 minutos.")
        self.assertTrue(self.h.esquecer(a["id"]))
        self.assertFalse(self.h.esquecer(a["id"]))
        self.assertIsNone(self.h.pegar(a["id"]))
        self.assertEqual(len(self.h.listar()), 1)


class SoBuscar(unittest.TestCase):
    """O "So buscar" acha artigos sem IA, tirando palavras ate o indice achar algo."""
    LIVROS = [("wikipedia_pt", "pt"), ("wikipedia_en", "en"), ("maps_en_brazil", "en")]

    def test_tira_palavras_ate_achar_e_completa_em_ingles(self):
        pedidos = []

        def falsa(params):
            termos = dict(params)["pattern"]
            livros = [v for k, v in params if k == "books.name"]
            pedidos.append((termos, livros))
            if livros == ["wikipedia_pt"] and termos == "purificar água":
                return [{"titulo": "Tratamento de água", "link": "/content/wikipedia_pt/A", "trecho": "ferver", "livro": "Wikipédia"}]
            if livros == ["wikipedia_en"] and termos == "purificar":
                return [{"titulo": "Water purification", "link": "/content/wikipedia_en/W", "trecho": "boil", "livro": "Wikipedia"}]
            return []

        with mock.patch.object(sabio, "livros_kiwix", return_value=self.LIVROS), mock.patch.object(sabio, "_itens_busca_detalhes", side_effect=falsa):
            r = sabio.buscar_sem_ia("Como purificar água da chuva?")
        self.assertEqual(r["termos"], "purificar água")
        self.assertEqual([a["titulo"] for a in r["artigos"]], ["Tratamento de água", "Water purification"])
        self.assertTrue(r["artigos"][0]["link"].startswith(sabio.KIWIX + "/content/"))
        self.assertTrue(all("maps_en_brazil" not in livros for _, livros in pedidos))  # mapa fica de fora

    def test_sem_biblioteca_explica(self):
        with mock.patch.object(sabio, "livros_kiwix", return_value=[]):
            with self.assertRaises(RuntimeError):
                sabio.buscar_sem_ia("agua")


class CentralSemModoJogo(unittest.TestCase):
    """Central de verdade (porta livre), com o modo jogo desligado e o modelo trocado por um falso."""

    def setUp(self):
        import tempfile
        self.pasta = tempfile.TemporaryDirectory()
        self.historico = tarefas.Historico(Path(self.pasta.name) / "perguntas.jsonl")
        self.trocas = [mock.patch.object(central, "HISTORICO", self.historico),
                       mock.patch.object(central, "MODO_JOGO", Path(self.pasta.name) / "sem-modo-jogo.txt"),
                       mock.patch.object(central, "garantir_ligados", lambda nomes, avisar: None),
                       mock.patch.object(sabio, "registrar_gasto", lambda *a: None)]
        for t in self.trocas:
            t.start()
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), central.Central)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        for t in self.trocas:
            t.stop()
        self.pasta.cleanup()

    def test_responder_agora_nao_guarda_como_completa(self):
        import urllib.request

        def resposta_cortada(pergunta, avisar=None, parar=None, **_):
            central.PEDIU_AGORA.set()   # a pessoa apertou "Responder agora"...
            parar.clear()               # ...e o sabio.responder() apaga o sinal ao refazer sem raciocinar
            return {"resposta": "Ferva a agua [1].", "termos": {}, "fontes": [{"titulo": "Agua", "link": "x"}]}

        with mock.patch.object(sabio, "perguntar_com_fonte", side_effect=resposta_cortada):
            corpo = json.dumps({"pergunta": "como purificar agua", "modo": "fonte"}).encode()
            req = urllib.request.Request(self.base + "/api/perguntar", corpo, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
        self.assertTrue(self.historico.listar()[0]["interrompida"])
        self.assertIsNone(self.historico.procurar("como purificar agua", "fonte"))  # e por isso nao serve de cache

    def test_pagina_nao_abre_dentro_de_outro_site(self):
        import urllib.request
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            self.assertEqual(r.headers["X-Frame-Options"], "DENY")
            self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])


class AgenteDoCofre(unittest.TestCase):
    """O servidor MCP do cofre conversando pelo protocolo de verdade (stdio), como um agente faria."""

    def conversar(self, mensagens):
        import subprocess
        entrada = "".join(json.dumps(m) + "\n" for m in mensagens)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "cofre_mcp.py")], input=entrada,
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]

    def test_inicia_lista_e_chama_uma_ferramenta(self):
        respostas = self.conversar([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "teste"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qual_ferramenta", "arguments": {"pedido": "falta de ar"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nao_existe", "arguments": {}}},
        ])
        self.assertEqual([r["id"] for r in respostas], [1, 2, 3, 4])  # a notificacao nao tem resposta
        self.assertEqual(respostas[0]["result"]["serverInfo"]["name"], "cofre")
        nomes = {f["name"] for f in respostas[1]["result"]["tools"]}
        self.assertEqual(nomes, {"buscar_bibliotecas", "ler_artigo", "trechos_com_fonte", "respostas_guardadas", "qual_ferramenta",
                                 "ficha_medica"})
        self.assertIn("emergencia", respostas[2]["result"]["content"][0]["text"])
        self.assertIn("error", respostas[3])

    def test_ler_artigo_so_le_a_biblioteca_do_cofre(self):
        import cofre_mcp
        r = cofre_mcp.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                               "params": {"name": "ler_artigo", "arguments": {"link": "https://site-qualquer.example/pagina"}}})
        self.assertTrue(r["result"]["isError"])
        with mock.patch.object(sabio, "http_texto", return_value="<p>Ferva a agua por um minuto inteiro.</p>") as falso:
            r = cofre_mcp.atender({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                   "params": {"name": "ler_artigo", "arguments": {"link": "/content/wikipedia_pt/A/Agua"}}})
        self.assertIn("Ferva a agua", r["result"]["content"][0]["text"])
        self.assertTrue(falso.call_args.args[0].startswith(sabio.KIWIX + "/content/"))


class FichaMedica(unittest.TestCase):
    """Inspirada na Ficha Medica do iPhone: a IA leva em conta a ficha de quem a pergunta cita."""

    def setUp(self):
        import tempfile
        self.pasta = tempfile.TemporaryDirectory()
        self.troca = mock.patch.object(tarefas, "ARQUIVO_FICHA", Path(self.pasta.name) / "ficha-medica.json")
        self.troca.start()
        tarefas.salvar_ficha({"pessoas": [
            {"nome": "Ana Souza", "nascimento": "2015", "sangue": "Z+", "alergias": "dipirona", "extra": "nao guarda"},
            {"nome": "Mãe", "remedios": "losartana 50 mg", "condicoes": "pressão alta"},
            {"nome": ""}],
            "contatos": [{"nome": "Tia Rosa", "telefone": "62 99999-0000", "relacao": "tia"}, {"nome": ""}]})

    def tearDown(self):
        self.troca.stop()
        self.pasta.cleanup()

    def test_guarda_so_o_que_conhece_e_com_limite(self):
        f = tarefas.ler_ficha()
        self.assertEqual([p["nome"] for p in f["pessoas"]], ["Ana Souza", "Mãe"])
        self.assertEqual(f["pessoas"][0]["sangue"], "")            # tipo invalido nao fica
        self.assertNotIn("extra", f["pessoas"][0])
        self.assertEqual(len(f["contatos"]), 1)

    def test_pega_a_ficha_de_quem_a_pergunta_cita(self):
        self.assertIn("alergias: dipirona", tarefas.ficha_para("Posso dar dipirona pra ana?"))
        self.assertIn("losartana", tarefas.ficha_para("minha mae esta com dor de cabeca"))
        self.assertEqual(tarefas.ficha_para("como purificar agua da chuva?"), "")
        self.assertEqual(tarefas.ficha_para("a banana esta madura?"), "")  # "ana" so vale como palavra inteira

    def test_a_ia_recebe_a_ficha_e_o_agente_tambem(self):
        r = {"texto": "Nao de dipirona [1].", "timings": {}, "interrompido": False, "repetiu": None}
        with mock.patch.object(sabio, "chat_em_fluxo", return_value=r) as falso:
            sabio.responder("posso dar dipirona pra ana?", [("A", "http://x", "t")], "m", threading.Event(),
                            tarefas.ficha_para("posso dar dipirona pra ana?"))
        pedido = falso.call_args.args[0]["messages"][1]["content"]
        self.assertIn("alergias: dipirona", pedido)
        self.assertIn("nunca indique algo a que a pessoa seja alergica", pedido)
        import cofre_mcp
        r = cofre_mcp.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ficha_medica", "arguments": {}}})
        self.assertIn("Tia Rosa (tia) 62 99999-0000", r["result"]["content"][0]["text"])


class ConselhoComPergunta(unittest.TestCase):
    def test_pergunta_no_endereco_abre_a_pagina(self):
        import urllib.request
        import conselho
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), conselho.Painel)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{servidor.server_address[1]}/?pergunta=" + urllib.parse.quote("devo comprar um gerador?")
            with urllib.request.urlopen(url, timeout=10) as r:
                self.assertEqual(r.status, 200)
                self.assertTrue(r.headers["Content-Type"].startswith("text/html"))
                self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        finally:
            servidor.shutdown()
            servidor.server_close()


class CentralRespostaGuardada(unittest.TestCase):
    """Pergunta repetida volta guardada, sem ligar nada, mesmo no modo jogo."""

    def setUp(self):
        import tempfile
        self.pasta = tempfile.TemporaryDirectory()
        jogo = Path(self.pasta.name) / "modo-jogo.txt"
        jogo.write_text("ligado", encoding="utf-8")
        historico = tarefas.Historico(Path(self.pasta.name) / "perguntas.jsonl")
        historico.guardar("Como purificar a água?", "fonte", "Ferva por 1 minuto [1].", [{"titulo": "Água", "link": "x"}], 5.0)
        self.trocas = [mock.patch.object(central, "HISTORICO", historico), mock.patch.object(central, "MODO_JOGO", jogo)]
        for t in self.trocas:
            t.start()
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), central.Central)
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.servidor.server_address[1]}"

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        for t in self.trocas:
            t.stop()
        self.pasta.cleanup()

    def perguntar(self, pergunta, modo="fonte"):
        import urllib.request
        corpo = json.dumps({"pergunta": pergunta, "modo": modo}).encode()
        req = urllib.request.Request(self.base + "/api/perguntar", corpo, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return [json.loads(b[6:]) for b in r.read().decode("utf-8").split("\n\n") if b.startswith("data: ")]

    def test_guardada_sai_na_hora_sem_ligar_nada(self):
        with mock.patch.object(central, "garantir_ligados", side_effect=AssertionError("nao devia ligar nada")):
            eventos = self.perguntar("como purificar agua?", "rapida")
        self.assertEqual(eventos[-1]["tipo"], "final")
        self.assertIn("Ferva", eventos[-1]["resposta"])
        self.assertTrue(eventos[-1]["gasto"].startswith("0 Wh"))

    def test_nova_no_modo_jogo_e_recusada(self):
        eventos = self.perguntar("qual a capital do Peru?")
        self.assertEqual(eventos[-1]["tipo"], "falha")
        self.assertIn("Modo jogo", eventos[-1]["texto"])

    def test_sugerir_avisa_da_guardada(self):
        import urllib.request
        with urllib.request.urlopen(self.base + "/api/sugerir?texto=" + urllib.parse.quote("purificar água"), timeout=10) as r:
            dados = json.loads(r.read())
        self.assertIsNotNone(dados["guardada"])
        self.assertEqual(dados["sugestoes"][0]["acao"], "buscar")  # termo solto: o artigo primeiro
        self.assertIn("gasto", dados["sugestoes"][0])


class PapeisDoCofre(unittest.TestCase):
    """Atualizar um modelo e trocar o modelo de um papel: tudo segue o papel na hora, e o anterior fica para voltar."""

    def setUp(self):
        import papeis
        self.papeis = papeis
        self.pasta = tempfile.TemporaryDirectory()
        base = Path(self.pasta.name)
        self.base = base
        papel = lambda i, nome, tipos, motor, modelo, troca="automatica": {  # noqa: E731
            "id": i, "nome": nome, "grupo": "Teste", "tipos": tipos, "motor": motor, "troca": troca, "modelo": modelo, "anterior": "", "trocado_em": ""}
        (base / "papeis.json").write_text(json.dumps({"papeis": [
            papel("rapida", "Resposta rápida", ["llm", "leve"], "llama.cpp", "pequeno-a"),
            papel("busca", "Busca por sentido", ["embeddings"], "llama.cpp", "vetor-a"),
            papel("imagem", "Criar imagens", ["imagem"], "comfyui", "img-a", "manual"),
        ]}, ensure_ascii=False), encoding="utf-8")
        (base / "modelos.json").write_text(json.dumps({"modelos": [
            {"id": "pequeno-a", "nome": "Pequeno A", "tipo": "llm", "motor": "llama.cpp", "tamanho_gb": 7},
            {"id": "pequeno-b", "nome": "Pequeno B", "tipo": "llm", "motor": "llama.cpp", "tamanho_gb": 8},
            {"id": "nao-baixado", "nome": "Ainda não", "tipo": "llm", "motor": "llama.cpp", "tamanho_gb": 9},
            {"id": "enorme", "nome": "Enorme", "tipo": "llm", "motor": "llama.cpp", "tamanho_gb": 300},
            {"id": "vetor-a", "nome": "Vetor A", "tipo": "embeddings", "motor": "llama.cpp", "tamanho_gb": 0.6},
            {"id": "img-a", "nome": "Imagem A", "tipo": "imagem", "motor": "comfyui", "tamanho_gb": 17},
        ], "conselho": {"membros": ["@rapida", "pequeno-b"], "relator": "@rapida"}}), encoding="utf-8")
        (base / "estado.json").write_text(json.dumps({"modelos": {i: {"completo": True} for i in ("pequeno-a", "pequeno-b", "enorme", "vetor-a", "img-a")}}),
                                          encoding="utf-8")
        self.trocas = [mock.patch.object(papeis, "ARQUIVO", base / "papeis.json"), mock.patch.object(papeis, "CATALOGO", base / "modelos.json"),
                       mock.patch.object(papeis, "ESTADO", base / "estado.json"), mock.patch.object(papeis, "REGISTRO", base / "trocas.csv"),
                       mock.patch.object(central, "ARQ_TROCA", base / "troca.json")]
        for t in self.trocas:
            t.start()

    def tearDown(self):
        for t in self.trocas:
            t.stop()
        self.pasta.cleanup()

    def test_troca_vale_na_hora_e_o_anterior_fica_para_voltar(self):
        self.assertEqual(tarefas.MODELO_RAPIDO, "pequeno-a")
        self.papeis.trocar("rapida", "pequeno-b")
        self.assertEqual(tarefas.MODELO_RAPIDO, "pequeno-b")              # o nome antigo segue o papel, sem reiniciar
        self.assertEqual(sabio.MODELO_EMB, "vetor-a")
        p = next(x for x in self.papeis.listar() if x["id"] == "rapida")
        self.assertEqual(p["anterior"]["id"], "pequeno-a")
        self.papeis.voltar("rapida")
        self.assertEqual(self.papeis.modelo("rapida"), "pequeno-a")
        registro = (self.base / "trocas.csv").read_text(encoding="utf-8")
        self.assertIn(";rapida;pequeno-a;pequeno-b;trocou", registro)
        self.assertIn("voltou", registro)

    def test_recusa_o_que_nao_serve_e_nada_muda(self):
        with self.assertRaisesRegex(ValueError, "não serve"):
            self.papeis.trocar("busca", "pequeno-b")                       # modelo de conversa no papel de busca
        with self.assertRaisesRegex(ValueError, "não foi baixado"):
            self.papeis.trocar("rapida", "nao-baixado")
        with self.assertRaisesRegex(ValueError, "catálogo"):
            self.papeis.trocar("rapida", "inventado")
        with self.assertRaisesRegex(ValueError, "manual"):
            self.papeis.trocar("imagem", "img-a")
        with self.assertRaisesRegex(ValueError, "anterior"):
            self.papeis.voltar("rapida")
        self.assertEqual(self.papeis.modelo("rapida"), "pequeno-a")

    def test_candidatos_e_conselho_seguem_os_papeis(self):
        p = next(x for x in self.papeis.listar() if x["id"] == "rapida")
        ids = [c["id"] for c in p["candidatos"]]
        self.assertIn("nao-baixado", ids)
        self.assertNotIn("vetor-a", ids)                                   # busca nao serve para responder
        self.assertLess(ids.index("pequeno-b"), ids.index("nao-baixado"))  # os ja baixados primeiro
        self.assertEqual(self.papeis.resolver(["@rapida", "pequeno-b", {"x": "@busca"}]), ["pequeno-a", "pequeno-b", {"x": "vetor-a"}])
        import conselho
        with mock.patch.object(conselho, "CATALOGO", self.base / "modelos.json"):
            cfg = conselho.ler_config()
        self.assertEqual(cfg["membros"], ["pequeno-a", "pequeno-b"])
        self.assertEqual(cfg["relator"], "pequeno-a")

    def test_manter_diz_se_o_anterior_ficou_sem_uso(self):
        self.papeis.trocar("rapida", "pequeno-b")
        r = self.papeis.manter("rapida")
        self.assertEqual((r["antigo"], r["sem_uso"]), ("pequeno-a", True))
        self.assertIn("Conselho de IAs", self.papeis.usado_por("pequeno-b"))  # citado pelo nome no conselho: nunca "sem uso"

    def test_sem_o_arquivo_vale_o_time_padrao(self):
        with mock.patch.object(self.papeis, "ARQUIVO", self.base / "nao-existe.json"):
            self.assertEqual(self.papeis.modelo("principal"), self.papeis.PADRAO["principal"])
            with self.assertRaises(RuntimeError):
                self.papeis.trocar("rapida", "pequeno-b")

    def test_central_mostra_onde_roda_e_valida_antes_de_trocar(self):
        with mock.patch.object(central, "placa", return_value={"vram_total_gb": 12}), \
             mock.patch.object(central, "memoria", return_value={"ram_total_gb": 64}):
            r = central.papeis_painel()
        p = next(x for x in r["papeis"] if x["id"] == "rapida")
        self.assertEqual(p["modelo"]["cabe"], "placa")                      # 7 GB numa placa de 12
        self.assertEqual([c["id"] for c in p["candidatos"]], ["pequeno-b", "nao-baixado", "enorme"])  # o grande demais por ultimo
        self.assertEqual(central.onde_cabe(11.3, "llama.cpp", {"vram_total_gb": 12}, {"ram_total_gb": 64}), "ram")
        self.assertEqual(central.onde_cabe(300, "llama.cpp", {"vram_total_gb": 12}, {"ram_total_gb": 64}), "grande")
        self.assertEqual(central.onde_cabe(0.1, "python", None, None), "processador")
        with mock.patch.object(central.subprocess, "Popen") as popen:
            self.assertFalse(central.trocar_modelo("rapida", "vetor-a")["ok"])   # nao serve
            self.assertFalse(central.trocar_modelo("imagem", "img-a")["ok"])     # troca manual
            self.assertFalse(central.trocar_modelo("inventado", "pequeno-b")["ok"])
            popen.assert_not_called()                                            # nenhuma janela aberta
        r = central.voltar_modelo("rapida")
        self.assertFalse(r["ok"])
        self.assertIn("anterior", r["texto"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
