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
            "onde fica o hospital mais próximo": ("mapa", "mapa"),
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

        def resposta_cortada(pergunta, avisar=None, parar=None):
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


if __name__ == "__main__":
    unittest.main(verbosity=1)
