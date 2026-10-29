# /// script
# requires-python = ">=3.11"
# dependencies = ["pypdf>=5"]
# ///
"""
Sabio: perguntas respondidas com fonte, 100% offline.

  perguntar  -> busca nas bibliotecas Kiwix (Wikipedia, WikiMed, iFixit...), escolhe os melhores
                trechos com o reranker e pede ao modelo uma resposta citando [1], [2]...
  indexar    -> le uma pasta sua (.txt, .md, .pdf, .html) e guarda os vetores num banco SQLite
  buscar     -> pergunta sobre os seus documentos indexados

Precisa de dois servidores ligados (o menu A:\\IA.cmd abre os dois):
  iniciar-servidor.ps1   (modelos, porta 8080)   e   iniciar-biblioteca.ps1 (Kiwix, porta 8081)

Uso (pelo wrapper A:\\scripts\\perguntar.ps1, que ja configura o Python do SSD):
  perguntar.ps1 "como tratar uma queimadura de segundo grau?"
  perguntar.ps1 -Indexar C:\\meus\\documentos
  perguntar.ps1 -Buscar "qual o prazo do contrato?"
"""
from __future__ import annotations

import argparse
import html
import http.client
import ipaddress
import itertools
import json
import math
import os
import re
import signal
import socket
import sqlite3
import struct
import sys
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

LLM = os.environ.get("SABIO_LLM", "http://127.0.0.1:8080")
KIWIX = os.environ.get("SABIO_KIWIX", "http://127.0.0.1:8081")
MODELO_CHAT = os.environ.get("SABIO_MODELO", "gemma-4-26b-a4b")
MODELO_EMB = "qwen3-embedding-0.6b"
MODELO_RERANK = "qwen3-reranker-0.6b"
BANCO = Path(os.environ.get("SABIO_BANCO", Path(__file__).resolve().parents[1] / "datasets" / "sabio.sqlite"))
INSTRUCAO_BUSCA = "Instruct: Dada uma pergunta, encontre trechos que a respondam\nQuery: "
# Chave de acesso do servidor de modelos (gerada por iniciar-servidor.ps1, fora do git).
ARQUIVO_CHAVE = Path(__file__).resolve().parents[2] / "catalogo" / "chave-api.txt"


# ---------- HTTP ----------

def chave_api() -> str:
    if os.environ.get("SABIO_CHAVE"):
        return os.environ["SABIO_CHAVE"]
    try:
        return ARQUIVO_CHAVE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def http_json(url: str, corpo: dict | None = None, timeout: int = 600) -> dict:
    dados = None if corpo is None else json.dumps(corpo).encode("utf-8")
    cabecalhos = {"Content-Type": "application/json"}
    if url.startswith(LLM) and chave_api():
        cabecalhos["Authorization"] = f"Bearer {chave_api()}"
    req = urllib.request.Request(url, data=dados, headers=cabecalhos)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat_em_fluxo(corpo: dict, parar: threading.Event | None = None) -> dict:
    """Pede ao llama-server em streaming, numa thread. Se `parar` acender ("Responder agora"), derruba a
    conexao (o servidor para de gerar e de gastar a placa) e devolve o texto que ja veio."""
    parar = parar or threading.Event()
    estado = {"texto": [], "timings": {}, "erro": None, "sock": None}
    destino = urllib.parse.urlsplit(LLM)

    def trabalhar() -> None:
        try:
            conexao = http.client.HTTPConnection(destino.hostname, destino.port or 80, timeout=3600)
            cabecalhos = {"Content-Type": "application/json"}
            if chave_api():
                cabecalhos["Authorization"] = f"Bearer {chave_api()}"
            conexao.request("POST", "/v1/chat/completions", body=json.dumps({**corpo, "stream": True}).encode("utf-8"), headers=cabecalhos)
            estado["sock"] = conexao.sock
            resp = conexao.getresponse()
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}: {resp.read()[:300].decode('utf-8', 'replace')}")
            for linha in resp:
                if not linha.startswith(b"data: "):
                    continue
                carga = linha[6:].strip()
                if carga == b"[DONE]":
                    break
                j = json.loads(carga)
                estado["timings"] = j.get("timings") or estado["timings"]
                for escolha in j.get("choices") or []:
                    pedaco = (escolha.get("delta") or {}).get("content")
                    if pedaco:
                        estado["texto"].append(pedaco)
        except Exception as erro:
            if not parar.is_set():
                estado["erro"] = erro

    t = threading.Thread(target=trabalhar, daemon=True)
    t.start()
    interrompido = False
    while t.is_alive():
        t.join(0.5)
        if parar.is_set() and t.is_alive():
            interrompido = True
            if estado["sock"]:
                try:
                    estado["sock"].shutdown(socket.SHUT_RDWR)  # fecha mesmo com a leitura em andamento
                except OSError:
                    pass
            t.join(5)
            break
    if estado["erro"]:
        raise estado["erro"]
    return {"texto": "".join(estado["texto"]).strip(), "timings": estado["timings"], "interrompido": interrompido}


def http_texto(url: str, timeout: int = 60) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def pedido_local_ok(host: str | None, origem: str | None) -> bool:
    """Para os servidores do cofre: recusa pedidos que um site aberto no navegador faca (o navegador
    manda Origin) e nomes de dominio que apontam para este PC (DNS rebinding). Programas locais, como
    o Open WebUI, nao mandam Origin e passam."""
    host = (host or "").strip()
    nome = host[1:host.find("]")] if host.startswith("[") else host.split(":")[0]
    if nome != "localhost":
        try:
            ipaddress.ip_address(nome)
        except ValueError:
            return False
    return origem is None or origem == f"http://{host}"


def servidor_ok(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except Exception:
        return False


# ---------- Texto ----------

class _Extrator(HTMLParser):
    """Tira o texto de uma pagina, ignorando menus, scripts e tabelas de navegacao."""
    IGNORAR = {"script", "style", "nav", "footer", "header", "sup", "table", "figure"}

    def __init__(self):
        super().__init__()
        self.partes: list[str] = []
        self._fundo = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._fundo += 1
        elif tag in ("p", "li", "h1", "h2", "h3", "h4", "br", "div", "dd", "dt"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._fundo:
            self._fundo -= 1

    def handle_data(self, data):
        if not self._fundo:
            self.partes.append(data)


def html_para_texto(conteudo: str) -> str:
    e = _Extrator()
    e.feed(conteudo)
    texto = html.unescape("".join(e.partes))
    texto = re.sub(r"[ \t]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n\n", texto).strip()


def fatiar(texto: str, tamanho: int = 1200, sobra: int = 200) -> list[str]:
    """Corta em trechos de ~tamanho caracteres, respeitando paragrafos, com sobreposicao."""
    paragrafos = [p.strip() for p in texto.split("\n\n") if len(p.strip()) > 40]
    trechos, atual = [], ""
    for p in paragrafos:
        if len(atual) + len(p) > tamanho and atual:
            trechos.append(atual.strip())
            atual = atual[-sobra:]
        atual += "\n" + p
    if atual.strip():
        trechos.append(atual.strip())
    return trechos


# ---------- Modelos (llama-server) ----------

def embeddings(textos: list[str]) -> list[list[float]]:
    r = http_json(f"{LLM}/v1/embeddings", {"model": MODELO_EMB, "input": textos})
    vetores = [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]
    return [normalizar(v) for v in vetores]


def normalizar(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def reordenar(pergunta: str, trechos: list[str], quantos: int) -> list[int]:
    """Usa o reranker; se ele nao estiver disponivel, mantem a ordem da busca."""
    try:
        r = http_json(f"{LLM}/v1/rerank", {"model": MODELO_RERANK, "query": pergunta, "documents": trechos, "top_n": quantos})
        return [x["index"] for x in sorted(r["results"], key=lambda x: -x["relevance_score"])][:quantos]
    except Exception as erro:
        print(f"(reranker indisponivel: {erro}; usando a ordem da busca)", file=sys.stderr)
        return list(range(min(quantos, len(trechos))))


def responder(pergunta: str, fontes: list[tuple[str, str, str]], modelo: str, parar: threading.Event | None = None) -> str:
    contexto = "\n\n".join(f"[{i}] {titulo}\n{trecho}" for i, (titulo, _, trecho) in enumerate(fontes, 1))
    sistema = (
        "Voce responde em portugues do Brasil usando SOMENTE as fontes fornecidas. "
        "Cite as fontes com [1], [2] logo depois de cada afirmacao. "
        "Se as fontes nao responderem a pergunta, diga isso claramente em vez de inventar. "
        "Em temas de saude ou seguranca, inclua os sinais de alerta e quando procurar ajuda."
    )
    corpo = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": sistema},
            {"role": "user", "content": f"Fontes:\n{contexto}\n\nPergunta: {pergunta}"},
        ],
        "max_tokens": 4000,
        # Raciocinio curto: as fontes ja estao na mesa (mais rapido e gasta menos energia).
        "thinking_budget_tokens": 1024,
        "chat_template_kwargs": {"reasoning_effort": "medium"},
    }
    parar = parar or threading.Event()
    direto = {"enable_thinking": False, "reasoning_effort": "low"}
    if parar.is_set():  # "Responder agora" antes de comecar: nem raciocina
        corpo["chat_template_kwargs"] = direto
        corpo.pop("thinking_budget_tokens")
        parar.clear()
    r = chat_em_fluxo(corpo, parar)
    if r["interrompido"] and len(r["texto"]) >= 80:
        return r["texto"] + "\n\n(resposta interrompida a pedido)"
    if not r["texto"] or r["interrompido"]:
        # O raciocinio gastou tudo, ou pediram "Responder agora" enquanto ainda raciocinava: de novo, direto.
        corpo["chat_template_kwargs"] = direto
        corpo.pop("thinking_budget_tokens", None)
        parar.clear()
        r = chat_em_fluxo(corpo, parar)
        if r["interrompido"]:
            r["texto"] += "\n\n(resposta interrompida a pedido)"
    return r["texto"]


# ---------- Kiwix ----------

def palavras_chave(pergunta: str, modelo: str) -> dict[str, str]:
    """A busca do Kiwix e por termos (como um indice): pede ao modelo termos em portugues e em ingles."""
    pedido = (
        "Gere termos de busca para encontrar a resposta numa enciclopedia. "
        'Responda SO com JSON no formato {"pt": "3 a 6 palavras em portugues", "en": "3 to 6 words in English"}.\n'
        f"Pergunta: {pergunta}"
    )
    try:
        # Gerar palavras de busca nao precisa de raciocinio: sem ele sai em segundos.
        r = http_json(f"{LLM}/v1/chat/completions", {"model": modelo, "messages": [{"role": "user", "content": pedido}], "max_tokens": 300,
                                                     "chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "low"}})
        achado = re.search(r"\{.*\}", r["choices"][0]["message"]["content"], re.S)
        termos = json.loads(achado.group(0)) if achado else {}
    except Exception as erro:
        print(f"(sem palavras-chave do modelo: {erro})", file=sys.stderr)
        termos = {}
    return {"pt": termos.get("pt") or pergunta, "en": termos.get("en") or pergunta}


def livros_kiwix() -> list[tuple[str, str]]:
    """Livros servidos pelo kiwix-serve: [(nome usado na busca, idioma de 2 letras)]."""
    try:
        raiz = ET.fromstring(http_texto(f"{KIWIX}/catalog/v2/entries?count=-1"))
    except Exception:
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    livros = []
    for e in raiz.findall("a:entry", ns):
        link = next((l.get("href") for l in e.findall("a:link", ns) if (l.get("href") or "").startswith("/content/")), None)
        if link:
            idioma = (e.findtext("a:language", namespaces=ns) or "eng").split(",")[0]
            livros.append((link.removeprefix("/content/"), "pt" if idioma.startswith("po") else "en"))
    return livros


def _itens_busca(params: list[tuple[str, str]]) -> list[tuple[str, str]]:
    raiz = ET.fromstring(http_texto(f"{KIWIX}/search?{urllib.parse.urlencode(params)}"))
    itens = []
    for i in raiz.iter("item"):
        titulo, link = (i.findtext("title") or "").strip(), (i.findtext("link") or "").strip()
        # Paginas de indice do Stack Exchange ("Highest Voted ... Questions") nao tem texto para citar.
        if link and "/questions/tagged/" not in link and not titulo.startswith("Highest Voted"):
            itens.append((titulo, link))
    return itens


# Fora da busca padrao: mapas (paginas de lugares) e o Stack Overflow, que so traz programacao e
# polui palavras comuns ("burn" vira pergunta de grafico em R). Perguntas de codigo o incluem de volta.
FORA_DA_BUSCA = ("maps_", "stackoverflow.com")


def buscar_kiwix(termos: dict[str, str], livros: list[tuple[str, str]], por_livro: int, maximo: int,
                 excluir: tuple[str, ...] = FORA_DA_BUSCA) -> list[tuple[str, str]]:
    """Uma busca por idioma em todas as bibliotecas daquele idioma, que o Kiwix ordena por relevancia
    (buscar livro a livro e intercalar deixava de fora quem vinha depois na lista). Alterna portugues e
    ingles e pega no maximo `por_livro` artigos de cada biblioteca, para as fontes variarem."""
    por_idioma = []
    for idioma in ("pt", "en"):
        nomes = [n for n, i in livros if i == idioma and not n.startswith(excluir)]
        if not nomes:
            continue
        base = [("pattern", termos[idioma]), ("format", "xml")]
        try:
            itens = _itens_busca(base + [("pageLength", str(maximo * 3))] + [("books.name", n) for n in nomes])
        except Exception:
            # Bibliotecas de idiomas diferentes no mesmo grupo nao buscam juntas: uma por vez, como antes.
            itens = []
            for n in nomes:
                try:
                    itens += _itens_busca(base + [("pageLength", str(por_livro)), ("books.name", n)])
                except Exception:
                    continue
        por_idioma.append(itens)
    escolhidos, conta = [], {}
    for rodada in itertools.zip_longest(*por_idioma):
        for x in rodada:
            if not x:
                continue
            livro = x[1].split("/")[2] if x[1].count("/") >= 2 else ""
            if conta.get(livro, 0) < por_livro:
                conta[livro] = conta.get(livro, 0) + 1
                escolhidos.append(x)
    return escolhidos[:maximo]


def responder_direto(pergunta: str, modelo: str) -> str:
    """Sem fontes e sem raciocinio: para quando pedem "Responder agora" antes de a busca terminar."""
    r = chat_em_fluxo({"model": modelo, "max_tokens": 1500,
                       "chat_template_kwargs": {"enable_thinking": False, "reasoning_effort": "low"},
                       "messages": [{"role": "system", "content": "Responda em portugues do Brasil, de forma curta e pratica. "
                                     "Em temas de saude ou seguranca, inclua sinais de alerta e quando procurar ajuda."},
                                    {"role": "user", "content": pergunta}]})
    return "_(Resposta rapida, sem consultar a biblioteca: confira antes de seguir.)_\n\n" + r["texto"]


def perguntar_com_fonte(pergunta: str, modelo: str = MODELO_CHAT, artigos: int = 3, maximo: int = 12, n_trechos: int = 6,
                        livros_escolhidos: str | None = None, avisar=None, parar: threading.Event | None = None) -> dict:
    """Busca nas bibliotecas, escolhe os melhores trechos e o modelo responde citando [1], [2]...
    `avisar(texto)` recebe o andamento. `parar` acende com "Responder agora": cada etapa para e o modelo
    responde com o que ja foi achado. Problemas que a pessoa pode resolver viram RuntimeError com a explicacao."""
    avisar = avisar or (lambda texto: print(texto, file=sys.stderr))
    parar = parar or threading.Event()
    for nome, url in (("modelos (iniciar-servidor.ps1)", f"{LLM}/health"), ("biblioteca (iniciar-biblioteca.ps1)", KIWIX)):
        if not servidor_ok(url):
            raise RuntimeError(f"O servidor de {nome} nao esta respondendo em {url}.")
    livros = livros_kiwix()
    excluir = FORA_DA_BUSCA
    if livros_escolhidos:
        filtro = [f.strip() for f in livros_escolhidos.split(",")]
        livros = [l for l in livros if any(l[0].startswith(f) for f in filtro)]
        excluir = ("maps_",)  # quem escolheu os livros a mao quer exatamente esses
    if not livros:
        raise RuntimeError("Nenhuma biblioteca disponivel no kiwix-serve.")
    def direto(motivo: str) -> dict:
        avisar(f"Respondendo agora, {motivo}")
        return {"resposta": responder_direto(pergunta, modelo), "termos": {}, "fontes": []}

    avisar("Escolhendo as palavras de busca")
    termos = palavras_chave(pergunta, modelo)
    if parar.is_set():
        return direto("sem esperar a busca")
    avisar(f"Buscando em {len(livros)} biblioteca(s): \"{termos['pt']}\" / \"{termos['en']}\"")
    achados = buscar_kiwix(termos, livros, artigos, maximo, excluir)
    if not achados:
        if parar.is_set():
            return direto("sem fontes")
        raise RuntimeError("Nada encontrado nas bibliotecas. Tente outras palavras (a busca e por termos, como num indice).")
    avisar(f"Lendo {len(achados)} artigos")
    trechos, origem = [], []
    vistos = set()
    for titulo, link in achados:
        if parar.is_set() and trechos:
            break  # "Responder agora": segue com os artigos ja lidos
        if link in vistos:
            continue
        vistos.add(link)
        try:
            texto = html_para_texto(http_texto(KIWIX + link))
        except Exception:
            continue
        for t in fatiar(texto)[:8]:
            trechos.append(t)
            origem.append((titulo, KIWIX + link))
    if not trechos:
        if parar.is_set():
            return direto("sem fontes")
        raise RuntimeError("Os artigos encontrados nao tinham texto aproveitavel.")
    if parar.is_set():
        melhores = list(range(min(n_trechos, len(trechos))))  # sem esperar o reordenador
    else:
        avisar("Escolhendo os melhores trechos")
        melhores = reordenar(pergunta, trechos, n_trechos)
    fontes = [(origem[i][0], origem[i][1], trechos[i]) for i in melhores]
    avisar(f"Escrevendo a resposta com {modelo}" + (" (direto, sem raciocinar)" if parar.is_set() else ""))
    return {"resposta": responder(pergunta, fontes, modelo, parar), "termos": termos,
            "fontes": [{"titulo": t, "link": l} for t, l, _ in fontes]}


def cmd_perguntar(args) -> None:
    # Primeiro Ctrl+C: responde agora com o que ja foi achado. Segundo: sai.
    parar, apertos = threading.Event(), [0]

    def ao_ctrl_c(sinal, quadro):
        apertos[0] += 1
        if apertos[0] > 1:
            raise KeyboardInterrupt
        parar.set()
        print("\n(Respondendo agora com o que ja foi encontrado. Ctrl+C de novo para sair.)", file=sys.stderr, flush=True)

    signal.signal(signal.SIGINT, ao_ctrl_c)
    print("(Dica: Ctrl+C responde agora com o que ja foi encontrado.)", file=sys.stderr, flush=True)
    try:
        r = perguntar_com_fonte(args.pergunta, args.modelo, args.artigos, args.maximo, args.trechos, args.livros, parar=parar)
    except RuntimeError as erro:
        sys.exit(str(erro))
    except KeyboardInterrupt:
        sys.exit("Pergunta cancelada.")
    print("\n" + r["resposta"] + "\n")
    print("Fontes:")
    for i, f in enumerate(r["fontes"], 1):
        print(f"  [{i}] {f['titulo']} - {f['link']}")


# ---------- Seus documentos ----------

def abrir_banco() -> sqlite3.Connection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BANCO)
    con.execute("CREATE TABLE IF NOT EXISTS trechos (id INTEGER PRIMARY KEY, arquivo TEXT, ordem INTEGER, texto TEXT, vetor BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS i_arquivo ON trechos(arquivo)")
    return con


def ler_arquivo(caminho: Path) -> str:
    ext = caminho.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join((p.extract_text() or "") for p in PdfReader(str(caminho)).pages)
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    return html_para_texto(texto) if ext in (".html", ".htm") else texto


def cmd_indexar(args) -> None:
    con = abrir_banco()
    arquivos = [p for p in Path(args.pasta).rglob("*") if p.suffix.lower() in (".txt", ".md", ".pdf", ".html", ".htm")]
    print(f"{len(arquivos)} arquivo(s) em {args.pasta}")
    for arq in arquivos:
        try:
            trechos = fatiar(ler_arquivo(arq))
        except Exception as erro:
            print(f"  pulando {arq.name}: {erro}")
            continue
        con.execute("DELETE FROM trechos WHERE arquivo = ?", (str(arq),))
        for i in range(0, len(trechos), 16):
            lote = trechos[i:i + 16]
            for j, (t, v) in enumerate(zip(lote, embeddings(lote))):
                con.execute("INSERT INTO trechos (arquivo, ordem, texto, vetor) VALUES (?, ?, ?, ?)",
                            (str(arq), i + j, t, struct.pack(f"{len(v)}f", *v)))
        con.commit()
        print(f"  {arq.name}: {len(trechos)} trecho(s)")
    print(f"Banco: {BANCO}")


def cmd_buscar(args) -> None:
    con = abrir_banco()
    q = embeddings([INSTRUCAO_BUSCA + args.pergunta])[0]
    pontuados = []
    for arquivo, texto, blob in con.execute("SELECT arquivo, texto, vetor FROM trechos"):
        v = struct.unpack(f"{len(blob) // 4}f", blob)
        pontuados.append((sum(a * b for a, b in zip(q, v)), arquivo, texto))
    if not pontuados:
        sys.exit("Nenhum documento indexado. Rode primeiro: perguntar.ps1 -Indexar <pasta>")
    pontuados.sort(reverse=True)
    candidatos = pontuados[:30]
    melhores = reordenar(args.pergunta, [t for _, _, t in candidatos], args.trechos)
    fontes = [(Path(candidatos[i][1]).name, candidatos[i][1], candidatos[i][2]) for i in melhores]
    print("\n" + responder(args.pergunta, fontes, args.modelo) + "\n")
    print("Fontes:")
    for i, (nome, caminho, _) in enumerate(fontes, 1):
        print(f"  [{i}] {nome} - {caminho}")


def main() -> None:
    p = argparse.ArgumentParser(description="Perguntas com fonte, offline.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("perguntar")
    a.add_argument("pergunta")
    a.add_argument("--livros", help="comeco do nome dos livros Kiwix, separados por virgula (ex.: wikipedia_pt,mdwiki)")
    a.add_argument("--artigos", type=int, default=3, help="no maximo quantos artigos de cada biblioteca")
    a.add_argument("--maximo", type=int, default=12, help="total de artigos lidos")
    a.add_argument("--trechos", type=int, default=6)
    a.add_argument("--modelo", default=MODELO_CHAT)
    a.set_defaults(f=cmd_perguntar)
    b = sub.add_parser("indexar")
    b.add_argument("pasta")
    b.set_defaults(f=cmd_indexar)
    c = sub.add_parser("buscar")
    c.add_argument("pergunta")
    c.add_argument("--trechos", type=int, default=6)
    c.add_argument("--modelo", default=MODELO_CHAT)
    c.set_defaults(f=cmd_buscar)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
