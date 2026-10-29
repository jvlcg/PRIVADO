# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Conselho de IAs: varios modelos do acervo respondem a mesma pergunta e um relator junta tudo
numa resposta final, dizendo onde concordaram e onde divergiram. 100% offline.

  1. triagem  -> um modelo rapido identifica o assunto e chama o especialista certo (codigo, medicina...)
  2. fontes   -> (opcional) trechos das bibliotecas Kiwix, como no sabio.py, lidos por todos
  3. imagem   -> (opcional) quem enxerga descreve a foto para os membros que so leem texto
  4. rodada 1 -> cada membro responde sozinho, sem ver os outros
  5. rodada 2 -> (debate) cada membro le as respostas dos outros, aponta erros e revisa a sua
  6. relator  -> compara tudo, confere contas e logica e escreve a resposta final

A placa de video (12 GB) comporta um modelo grande por vez, entao os membros falam em fila: o conselho
descarrega um e carrega o proximo, numa ordem que evita recarregar. O time fica no catalogo
(secao "conselho" de catalogo\\modelos.json). Cada deliberacao vira uma ata em dev\\conselho\\.

Uso (pelo wrapper A:\\scripts\\conselho.ps1, que liga o servidor de modelos se precisar):
  conselho.ps1 "qual a forma mais segura de guardar agua potavel por anos?"
  conselho.ps1 "..." -Debate -Pensar muito
  conselho.ps1 -Servir      # painel http://127.0.0.1:8090 + API compativel com OpenAI (modelo "conselho")
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sabio  # noqa: E402  (HTTP, busca nas bibliotecas Kiwix e reranker)

RAIZ = Path(__file__).resolve().parents[2]
LLM = sabio.LLM
KIWIX = sabio.KIWIX
CATALOGO = RAIZ / "catalogo" / "modelos.json"
ATAS = Path(os.environ.get("CONSELHO_ATAS", RAIZ / "dev" / "conselho"))

# Usado so se o catalogo nao tiver a secao "conselho".
PADRAO = {
    "membros": ["gemma-4-26b-a4b", "gpt-oss-20b", "qwen3.8-27b"],
    "relator": "gemma-4-26b-a4b",
    "relator_profundo": "qwen3.8-27b",
    "triagem": "gemma-4-26b-a4b",
    "max_membros": 3,
    "especialistas": {"codigo": "qwen3-coder-next", "medicina": "medgemma-27b", "traducao": "translategemma-12b"},
}
AREAS = {
    "geral": "conhecimentos gerais e conversa",
    "codigo": "programacao, scripts, computadores",
    "medicina": "saude, sintomas, remedios, primeiros socorros",
    "matematica": "contas, logica, quebra-cabecas",
    "ciencia": "fisica, quimica, biologia, engenharia",
    "traducao": "traduzir textos entre idiomas",
    "sobrevivencia": "agua, comida, abrigo, energia, consertos",
    "direito": "leis, contratos, direitos",
    "criativo": "historias, poemas, ideias",
}
# Orcamento de pensamento (tokens de raciocinio antes da resposta) e o equivalente no gpt-oss.
PENSAR = {"nao": 0, "pouco": 1024, "muito": 4096}
ESFORCO = {"nao": "low", "pouco": "medium", "muito": "high"}

SISTEMA_MEMBRO = (
    "Voce faz parte de um conselho de IAs que roda offline: varias IAs recebem a mesma pergunta e um relator "
    "junta as respostas depois. Responda em portugues do Brasil, de forma correta e direta, com o essencial "
    "em ate umas 350 palavras (o relator escreve a versao completa). "
    "Mostre o raciocinio quando houver conta ou logica, com as contas em texto simples, sem LaTeX "
    "(ex.: 200 W x 4 h = 800 Wh). Se nao tiver certeza de algo, diga claramente em vez "
    "de inventar. Em temas de saude ou seguranca, inclua os sinais de alerta e quando procurar ajuda."
)
PEDIDO_REVISAO = (
    "Os outros membros do conselho responderam a mesma pergunta assim:\n\n{outras}\n\n"
    "Leia com espirito critico. Aponte em poucas linhas os erros que encontrar (seus ou dos outros) e o que "
    "eles trouxeram de util que faltou na sua. Depois escreva sua resposta final revisada, completa."
)
SISTEMA_RELATOR = (
    "Voce e o relator de um conselho de IAs. Varias IAs responderam a mesma pergunta de forma independente. "
    "Escreva a MELHOR resposta final, em portugues do Brasil, direto para quem perguntou.\n"
    "- Leia as respostas com espirito critico: qualquer uma pode estar errada, inclusive todas. Refaca contas "
    "e confira a logica voce mesmo.\n"
    "- Junte o que estiver correto e util em cada uma; descarte erros e repeticoes.\n"
    "- Quando divergirem, fique com a mais bem fundamentada (nao automaticamente com a maioria).\n"
    "- Se houver trechos de enciclopedia, priorize o que eles dizem e cite [1], [2]. Sem trechos, nao use "
    "marcadores de citacao.\n"
    "- No corpo da resposta nao fale em 'Resposta 1' ou 'membros'.\n"
    "- Escreva contas em texto simples, sem LaTeX (ex.: 889 Wh / 0,8 = 1.111 Wh).\n"
    "Termine com uma secao curta '### Como o conselho decidiu': pontos de consenso, divergencias (e o lado "
    "que voce adotou, com o motivo em uma frase) e o grau de confianca (alto, medio ou baixo)."
)


@dataclass
class Opcoes:
    debate: bool = False
    profundo: bool = False  # relator mais forte (e mais lento): relator_profundo do catalogo
    pensar: str = "pouco"
    fontes: str = "auto"
    membros: list[str] | None = None
    relator: str | None = None
    liberar: bool = True


# ---------- Catalogo e servidor de modelos ----------

def ler_config() -> dict:
    cfg = dict(PADRAO)
    try:
        cfg.update(json.loads(CATALOGO.read_text(encoding="utf-8-sig")).get("conselho") or {})
    except Exception as erro:
        print(f"(sem a secao 'conselho' no catalogo: {erro}; usando o time padrao)", file=sys.stderr)
    return cfg


def modelos_servidor() -> dict[str, dict]:
    return {m["id"]: m for m in sabio.http_json(f"{LLM}/models", timeout=15).get("data", [])}


def eh_de_conversa(m: dict) -> bool:
    args = (m.get("status") or {}).get("args") or []
    return not any(a in args for a in ("--embeddings", "--embedding", "--reranking", "--rerank"))


def aceita_imagem(info: dict, modelo: str) -> bool:
    return "image" in (((info.get(modelo) or {}).get("architecture") or {}).get("input_modalities") or [])


def liberar_placa(manter: str) -> None:
    """Descarrega os outros modelos para o proximo ter a placa de video inteira."""
    try:
        carregados = [i for i, m in modelos_servidor().items()
                      if i != manter and (m.get("status") or {}).get("value") == "loaded"]
    except Exception:
        return
    for i in carregados:
        try:
            sabio.http_json(f"{LLM}/models/unload", {"model": i}, timeout=120)
        except Exception as erro:
            print(f"(nao consegui descarregar {i}: {erro})", file=sys.stderr)


def conversar(modelo: str, mensagens: list[dict], pensar: str, resposta_max: int = 3000) -> dict:
    """Uma chamada ao llama-server. O pensamento tem orcamento proprio e nao entra no texto."""
    orcamento = PENSAR[pensar]
    corpo = {
        "model": modelo,
        "messages": mensagens,
        "max_tokens": resposta_max + orcamento,
        "chat_template_kwargs": {"enable_thinking": orcamento > 0, "reasoning_effort": ESFORCO[pensar]},
    }
    if orcamento:
        corpo["thinking_budget_tokens"] = orcamento
    inicio = time.time()
    r = sabio.http_json(f"{LLM}/v1/chat/completions", corpo, timeout=3600)
    texto = (r["choices"][0]["message"].get("content") or "").strip()
    if not texto and orcamento:
        # Pensou ate o limite sem responder: pede de novo, direto.
        r2 = conversar(modelo, mensagens, "nao", resposta_max)
        r2["segundos"] = round(time.time() - inicio, 1)
        return r2
    return {
        "texto": texto,
        "segundos": round(time.time() - inicio, 1),
        "tokens": (r.get("usage") or {}).get("completion_tokens", 0),
        "tok_s": round((r.get("timings") or {}).get("predicted_per_second", 0), 1),
    }


# ---------- Etapas ----------

def triagem(pergunta: str, modelo: str) -> dict:
    lista = "; ".join(f"{k} = {v}" for k, v in AREAS.items())
    pedido = (
        "Classifique a pergunta abaixo para encaminhar a especialistas. Responda SO com JSON:\n"
        '{"area": "...", "objetiva": true, "fontes": false, "pt": "...", "en": "..."}\n'
        f"area: uma destas -> {lista}.\n"
        "objetiva: true se a resposta for curta e verificavel (um numero, um nome, sim/nao, uma conta).\n"
        "fontes: true se consultar uma enciclopedia ajudaria (fatos, historia, saude, ciencia, como fazer algo).\n"
        "pt / en: 3 a 6 palavras de busca em portugues / 3 to 6 search words in English.\n\n"
        f"Pergunta: {pergunta}"
    )
    try:
        r = conversar(modelo, [{"role": "user", "content": pedido}], "nao", 400)
        j = json.loads(re.search(r"\{.*\}", r["texto"], re.S).group(0))
    except Exception as erro:
        print(f"(triagem falhou: {erro}; seguindo como 'geral')", file=sys.stderr)
        j = {}
    return {
        "area": j.get("area") if j.get("area") in AREAS else "geral",
        "objetiva": bool(j.get("objetiva")),
        "fontes": bool(j.get("fontes")),
        "termos": {"pt": j.get("pt") or pergunta, "en": j.get("en") or pergunta},
    }


def montar_time(cfg: dict, area: str, disponiveis: set[str], opcoes: Opcoes) -> tuple[list[str], str]:
    """Especialista da area + membros gerais, sem repetir, ate max_membros. O relator fala por ultimo."""
    if opcoes.membros:
        candidatos, maximo = list(opcoes.membros), len(opcoes.membros)
    else:
        especialista = (cfg.get("especialistas") or {}).get(area)
        candidatos = ([especialista] if especialista else []) + list(cfg["membros"])
        maximo = int(cfg.get("max_membros", 3))
    time_: list[str] = []
    for m in candidatos:
        if m not in disponiveis:
            print(f"({m} nao esta no servidor de modelos; fica de fora)", file=sys.stderr)
        elif m not in time_:
            time_.append(m)
    if not time_:
        raise RuntimeError("Nenhum membro do conselho esta disponivel no servidor de modelos.")
    relator = opcoes.relator or (cfg.get("relator_profundo") if opcoes.profundo else None) or cfg["relator"]
    if relator not in disponiveis:
        relator = time_[-1]
    while len(time_) > maximo:
        time_.remove([m for m in time_ if m != relator][-1])
    # Quem fez a triagem ja esta na placa: fala primeiro. O relator fala por ultimo e emenda a sintese.
    if cfg.get("triagem") in time_:
        time_.remove(cfg["triagem"])
        time_.insert(0, cfg["triagem"])
    if relator in time_:
        time_.remove(relator)
        time_.append(relator)
    return time_, relator


def buscar_fontes(pergunta: str, termos: dict) -> list[tuple[str, str, str]]:
    """Mesma busca do sabio.py: Kiwix por termos, reranker escolhe os 6 melhores trechos."""
    livros = sabio.livros_kiwix()
    if not livros:
        return []
    trechos, origem, vistos = [], [], set()
    for titulo, link in sabio.buscar_kiwix(termos, livros, 3, 10):
        if link in vistos:
            continue
        vistos.add(link)
        try:
            texto = sabio.html_para_texto(sabio.http_texto(KIWIX + link))
        except Exception:
            continue
        for t in sabio.fatiar(texto)[:8]:
            trechos.append(t)
            origem.append((titulo, KIWIX + link))
    if not trechos:
        return []
    return [(origem[i][0], origem[i][1], trechos[i]) for i in sabio.reordenar(pergunta, trechos, 6)]


def ler_imagem(caminho: str) -> str:
    tipo = mimetypes.guess_type(caminho)[0] or "image/png"
    return f"data:{tipo};base64," + base64.b64encode(Path(caminho).read_bytes()).decode()


def descrever_imagem(modelo: str, imagem: str) -> str:
    pedido = ("Descreva esta imagem em detalhes para quem nao pode ve-la: o que aparece, cores, posicoes, "
              "quantidades e TODO texto visivel (transcreva exatamente).")
    msgs = [{"role": "user", "content": [{"type": "text", "text": pedido}, {"type": "image_url", "image_url": {"url": imagem}}]}]
    return conversar(modelo, msgs, "nao", 1500)["texto"]


def bloco_fontes(fontes: list[tuple[str, str, str]]) -> str:
    return "\n\n".join(f"[{i}] {titulo}\n{trecho}" for i, (titulo, _, trecho) in enumerate(fontes, 1))


def conteudo(pergunta: str, fontes, imagem: str | None, descricao: str, ve_imagem: bool):
    texto = pergunta
    if fontes:
        texto = f"Trechos de enciclopedia que podem ajudar (cite [1], [2] quando usar):\n{bloco_fontes(fontes)}\n\nPergunta: {pergunta}"
    if imagem and not ve_imagem and descricao:
        texto += f"\n\n(Voce nao ve imagens. Outro membro do conselho descreveu a imagem enviada assim:)\n{descricao}"
    if imagem and ve_imagem:
        return [{"type": "text", "text": texto}, {"type": "image_url", "image_url": {"url": imagem}}]
    return texto


# ---------- Deliberacao ----------

def deliberar(pergunta: str, opcoes: Opcoes, avisar=None, imagem: str | None = None, historico: list | None = None) -> dict:
    """Roda o conselho inteiro. avisar(evento) recebe o andamento (usado pelo terminal e pelo painel)."""
    avisar = avisar or (lambda e: None)
    inicio = time.time()
    cfg = ler_config()
    info = modelos_servidor()
    disponiveis = {i for i, m in info.items() if eh_de_conversa(m)}
    historico = historico or []

    quem_tria = cfg.get("triagem") if cfg.get("triagem") in disponiveis else next((m for m in cfg["membros"] if m in disponiveis), None)
    tri = {"area": "geral", "objetiva": False, "fontes": False, "termos": {"pt": pergunta, "en": pergunta}}
    if quem_tria:
        avisar({"tipo": "etapa", "texto": f"Triagem com {quem_tria}"})
        if opcoes.liberar:
            liberar_placa(quem_tria)
        tri = triagem(pergunta, quem_tria)
    membros, relator = montar_time(cfg, tri["area"], disponiveis, opcoes)
    avisar({"tipo": "time", "area": tri["area"], "objetiva": tri["objetiva"], "membros": membros, "relator": relator})

    fontes: list[tuple[str, str, str]] = []
    if opcoes.fontes == "sim" or (opcoes.fontes == "auto" and tri["fontes"]):
        if sabio.servidor_ok(KIWIX):
            avisar({"tipo": "etapa", "texto": "Buscando trechos nas bibliotecas offline"})
            try:
                fontes = buscar_fontes(pergunta, tri["termos"])
            except Exception as erro:
                avisar({"tipo": "aviso", "texto": f"Busca nas bibliotecas falhou: {erro}"})
            avisar({"tipo": "fontes", "fontes": [{"titulo": t, "link": l} for t, l, _ in fontes]})
        elif opcoes.fontes == "sim":
            avisar({"tipo": "aviso", "texto": "Biblioteca offline desligada (iniciar-biblioteca.ps1); seguindo sem fontes."})

    descricao = ""
    if imagem and any(not aceita_imagem(info, m) for m in membros + [relator]):
        quem_ve = next((m for m in membros if aceita_imagem(info, m)), None) or next((m for m in sorted(disponiveis) if aceita_imagem(info, m)), None)
        if quem_ve:
            avisar({"tipo": "etapa", "texto": f"{quem_ve} descreve a imagem para quem so le texto"})
            if opcoes.liberar:
                liberar_placa(quem_ve)
            descricao = descrever_imagem(quem_ve, imagem)
            avisar({"tipo": "imagem", "modelo": quem_ve, "texto": descricao})

    def falar(rodada, n: int, total: int, modelo: str, msgs: list[dict], pensar: str, resposta_max: int = 3000) -> dict | None:
        avisar({"tipo": "inicio", "rodada": rodada, "modelo": modelo, "n": n, "total": total})
        if opcoes.liberar:
            liberar_placa(modelo)
        try:
            r = conversar(modelo, msgs, pensar, resposta_max)
        except Exception as erro:
            avisar({"tipo": "erro", "rodada": rodada, "modelo": modelo, "texto": str(erro)})
            return None
        avisar({"tipo": "resposta", "rodada": rodada, "modelo": modelo, **r})
        return {"msgs": msgs, **r}

    respostas: dict[str, dict] = {}
    for n, m in enumerate(membros, 1):
        msgs = [{"role": "system", "content": SISTEMA_MEMBRO}] + historico + [
            {"role": "user", "content": conteudo(pergunta, fontes, imagem, descricao, aceita_imagem(info, m))}]
        r = falar(1, n, len(membros), m, msgs, opcoes.pensar, 1500)
        if r:
            respostas[m] = r
    if not respostas:
        raise RuntimeError("Nenhum membro conseguiu responder (veja a janela do servidor de modelos).")
    rodadas = [{m: r for m, r in respostas.items()}]

    if opcoes.debate and len(respostas) > 1:
        # Ordem invertida: quem falou por ultimo ainda esta na placa e comeca a revisao.
        ordem = [m for m in reversed(membros) if m in respostas]
        revisadas = {}
        for n, m in enumerate(ordem, 1):
            outras = "\n\n".join(f"--- Outro membro ---\n{respostas[o]['texto']}" for o in ordem if o != m)
            msgs = respostas[m]["msgs"] + [{"role": "assistant", "content": respostas[m]["texto"]},
                                           {"role": "user", "content": PEDIDO_REVISAO.format(outras=outras)}]
            revisadas[m] = falar(2, n, len(ordem), m, msgs, opcoes.pensar, 1500) or respostas[m]
        respostas = {m: revisadas[m] for m in membros if m in revisadas}
        rodadas.append(respostas)

    if len(respostas) == 1:
        relator, final = next(iter(respostas.items()))
        final = final["texto"]
    else:
        partes = []
        if fontes:
            partes.append("Trechos de enciclopedia:\n" + bloco_fontes(fontes))
        partes.append(f"Pergunta: {pergunta}")
        if descricao and not aceita_imagem(info, relator):
            partes.append(f"Descricao da imagem enviada (feita por um membro): {descricao}")
        if tri["objetiva"]:
            partes.append("(A pergunta tem resposta objetiva: comece com a resposta direta em uma linha.)")
        partes += [f"=== Resposta {i} ===\n{r['texto']}" for i, r in enumerate(respostas.values(), 1)]
        texto = "\n\n".join(partes)
        pedido = [{"type": "text", "text": texto}, {"type": "image_url", "image_url": {"url": imagem}}] if imagem and aceita_imagem(info, relator) else texto
        msgs = [{"role": "system", "content": SISTEMA_RELATOR}] + historico + [{"role": "user", "content": pedido}]
        r = falar("relator", 1, 1, relator, msgs, opcoes.pensar, 4000)
        if not r:
            raise RuntimeError(f"O relator {relator} falhou.")
        final = r["texto"]

    resultado = {
        "pergunta": pergunta, "area": tri["area"], "objetiva": tri["objetiva"], "membros": membros,
        "relator": relator, "opcoes": opcoes, "fontes": fontes, "descricao": descricao,
        "rodadas": rodadas, "final": final, "segundos": round(time.time() - inicio),
    }
    try:
        resultado["ata"] = str(salvar_ata(resultado))
    except Exception as erro:
        resultado["ata"] = ""
        avisar({"tipo": "aviso", "texto": f"Nao consegui salvar a ata: {erro}"})
    avisar({"tipo": "final", "texto": final, "ata": resultado["ata"], "segundos": resultado["segundos"], "relator": relator})
    return resultado


def duracao(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    return f"{m} min {s} s" if m else f"{s} s"


def salvar_ata(r: dict) -> Path:
    ATAS.mkdir(parents=True, exist_ok=True)
    slug = unicodedata.normalize("NFKD", r["pergunta"].lower()).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:50] or "pergunta"
    arquivo = ATAS / f"{datetime.now():%Y-%m-%d_%H%M%S}_{slug}.md"
    o = r["opcoes"]
    linhas = [
        f"# Ata do conselho - {datetime.now():%d/%m/%Y %H:%M}", "",
        f"**Pergunta:** {r['pergunta']}", "",
        f"**Assunto:** {r['area']} | **Modo:** {'profundo' if o.profundo else 'debate' if o.debate else 'rodada unica'} | "
        f"**Pensamento:** {o.pensar} | **Tempo total:** {duracao(r['segundos'])}", "",
        f"**Membros:** {', '.join(r['membros'])} | **Relator:** {r['relator']}", "",
        "## Resposta final", "", r["final"], "",
    ]
    if r["fontes"]:
        linhas += ["## Fontes", ""] + [f"[{i}] {t} - {l}" for i, (t, l, _) in enumerate(r["fontes"], 1)] + [""]
    if r["descricao"]:
        linhas += ["## Descricao da imagem", "", r["descricao"], ""]
    for n, rodada in enumerate(r["rodadas"], 1):
        linhas += [f"## Rodada {n} - " + ("respostas independentes" if n == 1 else "revisoes depois do debate"), ""]
        for m, x in rodada.items():
            linhas += [f"### {m} ({duracao(x['segundos'])}, {x['tok_s']} tokens/s)", "", x["texto"], ""]
    arquivo.write_text("\n".join(linhas), encoding="utf-8")
    return arquivo


def descrever(e: dict) -> str:
    """Uma linha de andamento para o terminal e para clientes da API."""
    rotulo = "Relator" if e.get("rodada") == "relator" else f"Rodada {e.get('rodada')}"
    t = e["tipo"]
    if t in ("etapa", "aviso"):
        return e["texto"]
    if t == "time":
        return f"Assunto: {e['area']}. Conselho: {', '.join(e['membros'])}. Relator: {e['relator']}."
    if t == "fontes":
        return f"{len(e['fontes'])} trecho(s) das bibliotecas: " + "; ".join(sorted({f['titulo'] for f in e['fontes']}))
    if t == "imagem":
        return f"{e['modelo']} descreveu a imagem para os outros."
    if t == "inicio":
        return f"{rotulo} ({e['n']}/{e['total']}): {e['modelo']} pensando..." if e["rodada"] != "relator" else f"Relator: {e['modelo']} escrevendo a resposta final..."
    if t == "resposta":
        return f"{rotulo}: {e['modelo']} terminou em {duracao(e['segundos'])} ({e['tok_s']} tokens/s)."
    if t == "erro":
        return f"{rotulo}: {e['modelo']} falhou: {e['texto']}"
    return ""


# ---------- Terminal ----------

def cmd_perguntar(args) -> None:
    if not sabio.servidor_ok(f"{LLM}/health"):
        sys.exit(f"O servidor de modelos nao esta respondendo em {LLM} (rode iniciar-servidor.ps1).")
    opcoes = Opcoes(debate=args.debate or args.profundo, profundo=args.profundo, pensar=args.pensar,
                    fontes=args.fontes, relator=args.relator,
                    membros=[m.strip() for m in args.membros.split(",")] if args.membros else None)

    def avisar(e):
        linha = descrever(e)
        if linha:
            print("> " + linha, file=sys.stderr, flush=True)
        if args.detalhes and e["tipo"] == "resposta" and e["rodada"] != "relator":
            print(f"\n----- {e['modelo']} (rodada {e['rodada']}) -----\n{e['texto']}\n", file=sys.stderr, flush=True)

    r = deliberar(args.pergunta, opcoes, avisar, ler_imagem(args.imagem) if args.imagem else None)
    print("\n" + r["final"] + "\n")
    if r["fontes"]:
        print("Fontes:")
        for i, (titulo, link, _) in enumerate(r["fontes"], 1):
            print(f"  [{i}] {titulo} - {link}")
    print(f"\nConselho: {', '.join(r['membros'])} | relator: {r['relator']} | {duracao(r['segundos'])}", file=sys.stderr)
    if r["ata"]:
        print(f"Ata completa (o que cada IA disse): {r['ata']}", file=sys.stderr)


# ---------- Painel e API ----------

TRAVA = threading.Lock()  # uma deliberacao por vez: a placa de video e uma so
MODELOS_API = {
    "conselho": "Cada IA responde sozinha e o relator junta as respostas",
    "conselho-debate": "Como o conselho, com uma rodada em que cada IA revisa a sua lendo as outras",
    "conselho-profundo": "Debate, mais raciocinio e o relator mais forte (bem mais lento)",
}


def opcoes_do_modelo(nome: str) -> Opcoes:
    profundo = "profundo" in nome
    return Opcoes(debate=profundo or "debate" in nome, profundo=profundo, pensar="muito" if profundo else "pouco")


def separar_conteudo(c) -> tuple[str, str | None]:
    """Conteudo no formato OpenAI (texto ou lista de partes) -> (texto, imagem em data URL)."""
    if isinstance(c, str):
        return c, None
    texto, imagem = [], None
    for p in c or []:
        if p.get("type") == "text":
            texto.append(p.get("text", ""))
        elif p.get("type") == "image_url" and not imagem:
            imagem = (p.get("image_url") or {}).get("url")
    return "\n".join(texto), imagem


def config_painel() -> dict:
    cfg = ler_config()
    try:
        info = modelos_servidor()
        disponiveis = sorted(i for i, m in info.items() if eh_de_conversa(m))
    except Exception:
        disponiveis = []
    return {"membros": cfg["membros"], "relator": cfg["relator"], "especialistas": cfg.get("especialistas", {}),
            "disponiveis": disponiveis, "servidor": bool(disponiveis)}


class Painel(BaseHTTPRequestHandler):
    server_version = "Conselho/1"

    def log_message(self, formato, *args):
        pass

    def _enviar(self, codigo: int, tipo: str, dados: bytes) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, codigo: int, obj) -> None:
        self._enviar(codigo, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _corpo(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _origem_ok(self) -> bool:
        return sabio.pedido_local_ok(self.headers.get("Host"), self.headers.get("Origin"))

    def _abrir_fluxo(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _evento(self, obj) -> bool:
        dados = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
        try:
            self.wfile.write(f"data: {dados}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except OSError:
            return False  # o navegador fechou; a deliberacao continua e a ata e salva

    def do_GET(self):
        if not self._origem_ok():
            return self._json(403, {"erro": "pedido de outro site bloqueado"})
        if self.path in ("/", "/index.html"):
            self._enviar(200, "text/html; charset=utf-8", PAGINA.encode("utf-8"))
        elif self.path in ("/v1/models", "/models"):
            self._json(200, {"object": "list", "data": [
                {"id": k, "object": "model", "owned_by": "conselho-local", "description": v} for k, v in MODELOS_API.items()]})
        elif self.path == "/api/config":
            self._json(200, config_painel())
        elif self.path == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"erro": "nao encontrado"})

    def do_POST(self):
        if not self._origem_ok():
            return self._json(403, {"erro": "pedido de outro site bloqueado"})
        try:
            corpo = self._corpo()
        except Exception:
            return self._json(400, {"erro": "JSON invalido"})
        if self.path == "/api/deliberar":
            self._painel(corpo)
        elif self.path in ("/v1/chat/completions", "/chat/completions"):
            self._openai(corpo)
        else:
            self._json(404, {"erro": "nao encontrado"})

    def _painel(self, corpo: dict) -> None:
        pergunta = (corpo.get("pergunta") or "").strip()
        if not pergunta:
            return self._json(400, {"erro": "pergunta vazia"})
        opcoes = Opcoes(debate=bool(corpo.get("debate") or corpo.get("profundo")), profundo=bool(corpo.get("profundo")),
                        pensar=corpo.get("pensar") if corpo.get("pensar") in PENSAR else "pouco",
                        fontes=corpo.get("fontes") if corpo.get("fontes") in ("auto", "sim", "nao") else "auto",
                        membros=corpo.get("membros") or None, relator=corpo.get("relator") or None)
        self._abrir_fluxo()
        vivo = [True]

        def avisar(e):
            if vivo[0]:
                vivo[0] = self._evento(e)

        if not TRAVA.acquire(blocking=False):
            avisar({"tipo": "etapa", "texto": "Outra pergunta esta em deliberacao; aguardando a vez..."})
            TRAVA.acquire()
        try:
            deliberar(pergunta, opcoes, avisar, corpo.get("imagem") or None)
        except Exception as erro:
            avisar({"tipo": "falha", "texto": str(erro)})
        finally:
            TRAVA.release()

    def _openai(self, corpo: dict) -> None:
        nome = corpo.get("model") or "conselho"
        msgs = [m for m in corpo.get("messages") or [] if m.get("role") in ("user", "assistant")]
        if not msgs or msgs[-1]["role"] != "user":
            return self._json(400, {"error": {"message": "a ultima mensagem precisa ser do usuario"}})
        pergunta, imagem = separar_conteudo(msgs[-1].get("content"))
        historico = []
        for m in msgs[:-1][-6:]:
            t, _ = separar_conteudo(m.get("content"))
            if t:
                historico.append({"role": m["role"], "content": t})
        opcoes = opcoes_do_modelo(nome)
        ident, criado = f"chatcmpl-conselho-{int(time.time() * 1000)}", int(time.time())

        def pedaco(delta: dict, fim=None) -> dict:
            return {"id": ident, "object": "chat.completion.chunk", "created": criado, "model": nome,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": fim}]}

        if not corpo.get("stream"):
            with TRAVA:
                try:
                    final = deliberar(pergunta, opcoes, None, imagem, historico)["final"]
                except Exception as erro:
                    return self._json(500, {"error": {"message": str(erro)}})
            return self._json(200, {"id": ident, "object": "chat.completion", "created": criado, "model": nome,
                                    "choices": [{"index": 0, "message": {"role": "assistant", "content": final}, "finish_reason": "stop"}],
                                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})

        # Em streaming, o andamento vai como "raciocinio" (clientes como o Open WebUI mostram recolhido)
        # e a resposta final como conteudo.
        self._abrir_fluxo()
        vivo = [self._evento(pedaco({"role": "assistant", "content": ""}))]

        def avisar(e):
            linha = descrever(e)
            if linha and vivo[0]:
                vivo[0] = self._evento(pedaco({"reasoning_content": linha + "\n"}))

        with TRAVA:
            try:
                final = deliberar(pergunta, opcoes, avisar, imagem, historico)["final"]
            except Exception as erro:
                final = f"O conselho nao conseguiu responder: {erro}"
        if vivo[0]:
            self._evento(pedaco({"content": final}))
            self._evento(pedaco({}, "stop"))
            self._evento("[DONE]")


def cmd_servir(args) -> None:
    if not sabio.servidor_ok(f"{LLM}/health"):
        print(f"Aviso: o servidor de modelos ainda nao responde em {LLM}.", file=sys.stderr)
    ip = "0.0.0.0" if args.rede else "127.0.0.1"
    servidor = ThreadingHTTPServer((ip, args.porta), Painel)
    print(f"Painel do conselho:  http://127.0.0.1:{args.porta}")
    print(f"API (OpenAI):        http://127.0.0.1:{args.porta}/v1   modelos: {', '.join(MODELOS_API)}")
    print("Para parar: Ctrl+C nesta janela.", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


PAGINA = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conselho de IAs</title>
<style>
:root{--fundo:#f6f5f2;--cartao:#fff;--texto:#1d1d1b;--suave:#6b6a66;--borda:#e2e0da;--destaque:#2f5d50;--destaque-fundo:#e6efe9;--erro:#a3352b;--codigo:#f0eee9}
@media (prefers-color-scheme:dark){:root{--fundo:#161716;--cartao:#1f211f;--texto:#ecebe7;--suave:#a19f99;--borda:#333632;--destaque:#8cc5ad;--destaque-fundo:#223029;--erro:#f08a7e;--codigo:#2a2c29}}
*{box-sizing:border-box}
body{margin:0;background:var(--fundo);color:var(--texto);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:880px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;margin:0}
.sub{color:var(--suave);margin:4px 0 20px}
form,.cartao{background:var(--cartao);border:1px solid var(--borda);border-radius:12px;padding:16px}
textarea{width:100%;min-height:96px;resize:vertical;font:inherit;color:inherit;background:transparent;border:1px solid var(--borda);border-radius:8px;padding:10px}
.linha{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin-top:12px}
label{font-size:.85rem;color:var(--suave);display:flex;flex-direction:column;gap:4px}
select,input[type=file]{font:inherit;color:inherit;background:var(--cartao);border:1px solid var(--borda);border-radius:8px;padding:6px 8px;max-width:100%}
button{font:inherit;font-weight:600;background:var(--destaque);color:var(--cartao);border:0;border-radius:8px;padding:10px 18px;cursor:pointer;margin-left:auto}
button:disabled{opacity:.5;cursor:wait}
details.escolha{margin-top:12px}
details.escolha summary{cursor:pointer;color:var(--suave);font-size:.9rem}
#membros{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0}
#membros label{flex-direction:row;align-items:center;color:var(--texto);font-size:.9rem}
#previa{max-height:120px;border-radius:8px;margin-top:10px}
#andamento{margin:20px 0 8px;color:var(--suave);font-size:.9rem;padding-left:18px}
#relogio{font-variant-numeric:tabular-nums;color:var(--suave);font-size:.9rem}
.final{border-color:var(--destaque);background:var(--destaque-fundo);margin:12px 0}
.final>h2{margin:0 0 8px;font-size:1rem;color:var(--destaque)}
.cartao{margin:10px 0}
.cartao summary{cursor:pointer;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.nome{font-weight:600}
.estado{color:var(--suave);font-size:.85rem}
.erro{color:var(--erro)}
.md h2,.md h3,.md h4,.md h5{margin:1em 0 .4em;line-height:1.3}
.md p{margin:.5em 0}
.md pre{background:var(--codigo);padding:10px;border-radius:8px;overflow-x:auto}
.md code{background:var(--codigo);padding:1px 4px;border-radius:4px;font-size:.9em}
.md pre code{padding:0;background:none}
.tabela{overflow-x:auto}
.md table{border-collapse:collapse;margin:.6em 0}
.md th,.md td{border:1px solid var(--borda);padding:4px 8px;text-align:left;vertical-align:top}
.fontes a{color:var(--destaque)}
footer{margin-top:28px;color:var(--suave);font-size:.85rem}
footer code{background:var(--codigo);padding:1px 4px;border-radius:4px}
</style>
</head>
<body>
<main>
<h1>Conselho de IAs</h1>
<p class="sub">Várias IAs do seu acervo respondem à mesma pergunta; um relator compara e escreve a resposta final. Tudo offline.</p>
<form id="form">
  <textarea id="pergunta" placeholder="Sua pergunta para o conselho..." required></textarea>
  <div class="linha">
    <label>Modo<select id="modo"><option value="rapido">Rodada única (3 a 6 min)</option><option value="debate">Debate: revisam umas às outras (cerca do dobro)</option><option value="profundo">Profundo: debate + relator mais forte (15 a 25 min)</option></select></label>
    <label>Raciocínio<select id="pensar"><option value="pouco">Pouco</option><option value="nao">Nenhum (mais rápido)</option><option value="muito">Muito (mais lento)</option></select></label>
    <label>Fontes<select id="fontes"><option value="auto">Automático</option><option value="sim">Sempre consultar a biblioteca</option><option value="nao">Não consultar</option></select></label>
    <label>Imagem (opcional)<input type="file" id="foto" accept="image/*"></label>
    <button id="enviar">Perguntar ao conselho</button>
  </div>
  <img id="previa" hidden alt="">
  <details class="escolha" id="manual">
    <summary>Escolher os membros (sem isso a triagem escolhe sozinha)</summary>
    <div id="membros"></div>
    <label>Relator<select id="relator"></select></label>
  </details>
</form>
<ul id="andamento"></ul>
<div id="relogio"></div>
<div id="final"></div>
<div id="cartoes"></div>
<footer>Em outros programas (Open WebUI, Continue, scripts): base URL <code>http://127.0.0.1:PORTA/v1</code>, modelo <code>conselho</code>, <code>conselho-debate</code> ou <code>conselho-profundo</code>. As atas ficam em <code>A:\dev\conselho</code>.</footer>
</main>
<script>
const $ = s => document.querySelector(s);
$('footer').innerHTML = $('footer').innerHTML.replace('PORTA', location.port || '80');
let imagem = null, inicio = 0, tique = null;

function esc(s){return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
// Contas em LaTeX ($...$) viram texto simples: o painel e offline e nao carrega bibliotecas de formulas.
const SIMBOLOS = {times: '×', div: '÷', approx: '≈', cdot: '·', pm: '±', le: '≤', ge: '≥', neq: '≠', to: '→', rightarrow: '→', quad: ' ', '%': '%'};
function semLatex(s){
  return s.replace(/\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)/g, (m, a, b, c, d) => {
    let t = a || b || c || d;
    if (b && !/[\\^_]/.test(b)) return m;  // "R$ 5 e R$ 3" e dinheiro, nao formula
    for (let i = 0; i < 3; i++) t = t.replace(/\\(?:text|mathbf|mathrm|textbf|operatorname)\{([^{}]*)\}/g, '$1');
    t = t.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '($1)/($2)').replace(/\\sqrt\{([^{}]*)\}/g, '√($1)');
    t = t.replace(/\\([a-zA-Z]+|%)/g, (x, n) => SIMBOLOS[n] ?? n).replace(/[{}]/g, '').replace(/\^2/g, '²').replace(/\^3/g, '³');
    return t.trim();
  });
}
function inline(s){
  return s.replace(/`([^`]+)`/g, '<code>$1</code>')
          .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
          .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
          .replace(/\[(\d+)\]/g, '<sup>[$1]</sup>');
}
const ITEM = /^\s*([-*+]|\d+[.)])\s+/;
function md(src){
  const L = esc(semLatex(src || '')).split('\n'); let h = '', i = 0;
  while (i < L.length) {
    const l = L[i];
    if (/^\s*```/.test(l)) { const b = []; i++; while (i < L.length && !/^\s*```/.test(L[i])) b.push(L[i++]); i++; h += `<pre><code>${b.join('\n')}</code></pre>`; continue; }
    const t = l.match(/^(#{1,4})\s+(.*)/);
    if (t) { const n = Math.min(t[1].length + 1, 5); h += `<h${n}>${inline(t[2])}</h${n}>`; i++; continue; }
    if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < L.length && /^\s*\|[\s:|-]+\|\s*$/.test(L[i + 1])) {
      const cel = x => x.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      let tb = '<div class="tabela"><table><thead><tr>' + cel(l).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>'; i += 2;
      while (i < L.length && /^\s*\|.*\|\s*$/.test(L[i])) { tb += '<tr>' + cel(L[i]).map(c => `<td>${c}</td>`).join('') + '</tr>'; i++; }
      h += tb + '</tbody></table></div>'; continue;
    }
    if (ITEM.test(l)) {
      const ord = /^\s*\d/.test(l), it = [];
      while (i < L.length && ITEM.test(L[i])) it.push(inline(L[i++].replace(ITEM, '')));
      h += (ord ? '<ol>' : '<ul>') + it.map(x => `<li>${x}</li>`).join('') + (ord ? '</ol>' : '</ul>'); continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { h += '<hr>'; i++; continue; }
    if (!l.trim()) { i++; continue; }
    const p = [];
    while (i < L.length && L[i].trim() && !/^(\s*```|#{1,4}\s|\s*\|)/.test(L[i]) && !ITEM.test(L[i])) p.push(L[i++]);
    if (!p.length) p.push(L[i++]);
    h += `<p>${inline(p.join('<br>'))}</p>`;
  }
  return h;
}

function passo(texto, classe){ const li = document.createElement('li'); li.textContent = texto; if (classe) li.className = classe; $('#andamento').appendChild(li); }
function duracao(s){ s = Math.round(s); return s >= 60 ? `${Math.floor(s/60)} min ${s%60} s` : `${s} s`; }
function cartao(e){
  const id = `c-${e.rodada}-${e.modelo}`.replace(/[^\w-]/g, '_');
  let c = document.getElementById(id);
  if (!c) {
    c = document.createElement('details'); c.id = id; c.className = 'cartao';
    const rot = e.rodada === 'relator' ? 'Relator' : `Rodada ${e.rodada}`;
    c.innerHTML = `<summary><span class="nome"></span><span class="estado"></span></summary><div class="md"></div>`;
    c.querySelector('.nome').textContent = `${rot} · ${e.modelo}`;
    $('#cartoes').prepend(c);
  }
  return c;
}
function tratar(e){
  switch (e.tipo) {
    case 'etapa': case 'aviso': passo(e.texto); break;
    case 'time': passo(`Assunto: ${e.area}. Conselho: ${e.membros.join(', ')}. Relator: ${e.relator}.`); break;
    case 'fontes': {
      passo(`${e.fontes.length} trecho(s) das bibliotecas offline`);
      if (e.fontes.length) { const d = document.createElement('div'); d.className = 'cartao fontes'; d.innerHTML = '<strong>Fontes</strong><ol></ol>';
        e.fontes.forEach(f => { const li = document.createElement('li'); const a = document.createElement('a'); a.href = f.link; a.target = '_blank'; a.textContent = f.titulo; li.appendChild(a); d.querySelector('ol').appendChild(li); });
        $('#cartoes').prepend(d); }
      break;
    }
    case 'imagem': { passo(`${e.modelo} descreveu a imagem para os outros`); const c = cartao({rodada: 'imagem', modelo: e.modelo}); c.querySelector('.nome').textContent = `Descrição da imagem · ${e.modelo}`; c.querySelector('.md').innerHTML = md(e.texto); break; }
    case 'inicio': { const c = cartao(e); c.querySelector('.estado').textContent = e.rodada === 'relator' ? 'escrevendo a resposta final…' : 'pensando…'; break; }
    case 'resposta': {
      const c = cartao(e); c.querySelector('.estado').textContent = `${duracao(e.segundos)} · ${e.tok_s} tokens/s`;
      if (e.rodada !== 'relator') c.querySelector('.md').innerHTML = md(e.texto); else c.remove();
      break;
    }
    case 'erro': { const c = cartao(e); c.querySelector('.estado').textContent = 'falhou'; c.querySelector('.md').innerHTML = `<p class="erro">${esc(e.texto)}</p>`; break; }
    case 'final': {
      const f = $('#final'); f.className = 'cartao final';
      f.innerHTML = `<h2>Resposta do conselho (relator: ${esc(e.relator)})</h2><div class="md">${md(e.texto)}</div><p class="estado">Tempo total ${duracao(e.segundos)}${e.ata ? ' · ata salva em ' + esc(e.ata) : ''}</p>`;
      passo('Pronto. Abra os cartões abaixo para ver o que cada IA disse.');
      break;
    }
    case 'falha': passo('Falhou: ' + e.texto, 'erro'); break;
  }
}

$('#foto').onchange = ev => {
  const f = ev.target.files[0];
  if (!f) { imagem = null; $('#previa').hidden = true; return; }
  const r = new FileReader(); r.onload = () => { imagem = r.result; $('#previa').src = imagem; $('#previa').hidden = false; }; r.readAsDataURL(f);
};

async function carregarConfig(){
  try {
    const c = await (await fetch('/api/config')).json();
    if (!c.servidor) passo('O servidor de modelos (porta 8080) não respondeu. Abra-o pelo menu (opção 1) e recarregue a página.', 'erro');
    $('#membros').innerHTML = '';
    c.disponiveis.forEach(m => {
      const l = document.createElement('label'); const x = document.createElement('input');
      x.type = 'checkbox'; x.value = m; x.checked = c.membros.includes(m); l.append(x, ' ' + m); $('#membros').appendChild(l);
      const o = document.createElement('option'); o.value = o.textContent = m; if (m === c.relator) o.selected = true; $('#relator').appendChild(o);
    });
  } catch (err) { passo('Não consegui ler a configuração: ' + err, 'erro'); }
}

$('#form').onsubmit = async ev => {
  ev.preventDefault();
  const pergunta = $('#pergunta').value.trim(); if (!pergunta) return;
  const corpo = {pergunta, debate: $('#modo').value !== 'rapido', profundo: $('#modo').value === 'profundo', pensar: $('#pensar').value, fontes: $('#fontes').value, imagem};
  if ($('#manual').open) { corpo.membros = [...document.querySelectorAll('#membros input:checked')].map(x => x.value); corpo.relator = $('#relator').value; }
  $('#andamento').innerHTML = ''; $('#cartoes').innerHTML = ''; $('#final').innerHTML = ''; $('#final').className = '';
  $('#enviar').disabled = true; inicio = Date.now();
  tique = setInterval(() => { $('#relogio').textContent = 'Deliberando há ' + duracao((Date.now() - inicio) / 1000); }, 1000);
  try {
    const resp = await fetch('/api/deliberar', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(corpo)});
    const leitor = resp.body.getReader(), dec = new TextDecoder(); let buf = '';
    for (;;) {
      const {value, done} = await leitor.read(); if (done) break;
      buf += dec.decode(value, {stream: true}); let k;
      while ((k = buf.indexOf('\n\n')) >= 0) { const bloco = buf.slice(0, k); buf = buf.slice(k + 2); if (bloco.startsWith('data: ')) tratar(JSON.parse(bloco.slice(6))); }
    }
  } catch (err) { passo('Conexão perdida: ' + err, 'erro'); }
  clearInterval(tique); $('#relogio').textContent = ''; $('#enviar').disabled = false;
};
carregarConfig();
</script>
</body>
</html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description="Conselho de IAs locais.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("perguntar")
    a.add_argument("pergunta")
    a.add_argument("--debate", action="store_true", help="rodada extra em que cada IA revisa a sua lendo as outras")
    a.add_argument("--profundo", action="store_true", help="debate + relator mais forte (bem mais lento)")
    a.add_argument("--pensar", choices=list(PENSAR), default="pouco")
    a.add_argument("--fontes", choices=["auto", "sim", "nao"], default="auto")
    a.add_argument("--membros", help="ids separados por virgula (sem isso, a triagem escolhe)")
    a.add_argument("--relator")
    a.add_argument("--imagem", help="foto ou print para o conselho analisar")
    a.add_argument("--detalhes", action="store_true", help="mostra a resposta de cada IA no terminal")
    a.set_defaults(f=cmd_perguntar)
    s = sub.add_parser("servir")
    s.add_argument("--porta", type=int, default=8090)
    s.add_argument("--rede", action="store_true", help="libera para outros aparelhos da rede")
    s.set_defaults(f=cmd_servir)
    args = p.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
