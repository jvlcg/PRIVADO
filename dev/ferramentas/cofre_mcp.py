# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Agente do Cofre: servidor MCP (Model Context Protocol) que da a qualquer IA ferramentas para pesquisar no
acervo offline. Funciona com o proprio llama-server (--mcp-servers-config, ligado pelo iniciar-servidor.ps1),
com agentes como opencode, Qwen Code, Goose e Hermes, e com o Claude.

Ferramentas (todas sem o modelo de chat: quem pensa e a IA que chamou):
  buscar_bibliotecas   artigos com as palavras, com o trecho onde aparecem (so o Kiwix, gasto quase zero)
  ler_artigo           o texto de um artigo da biblioteca (os agentes locais tendem a buscar e nao ler)
  trechos_com_fonte    os melhores trechos para uma pergunta, ja reordenados e numerados para citar
  respostas_guardadas  perguntas ja respondidas no cofre (Historico): 0 Wh
  qual_ferramenta      o jeito mais barato de resolver um pedido, com o gasto estimado

Protocolo: JSON-RPC 2.0, uma mensagem por linha no stdin/stdout (transporte stdio do MCP). So a biblioteca
padrao do Python, para rodar offline. Uso: uv run --offline --script cofre_mcp.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sabio  # noqa: E402
import tarefas  # noqa: E402

VERSAO_PROTOCOLO = "2025-06-18"
INSTRUCOES = (
    "Ferramentas do Cofre de IAs: bibliotecas offline (Wikipedia, WikiMed, iFixit, manuais e outras 40). "
    "Para responder com fonte: chame trechos_com_fonte (ou buscar_bibliotecas e depois ler_artigo) e cite os "
    "artigos pelo numero [1], [2]. Se a busca so trouxer titulos, LEIA o artigo com ler_artigo antes de responder. "
    "Antes de pesquisar, veja em respostas_guardadas se a pergunta ja foi respondida."
)


def _texto(obj) -> str:
    return obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1)


def buscar_bibliotecas(consulta: str, maximo: int = 8) -> str:
    r = sabio.buscar_sem_ia(consulta, maximo=max(1, min(int(maximo), 20)))
    if not r["artigos"]:
        return f"Nada encontrado com \"{r['termos']}\". Tente outras palavras (a busca e por termos, como num indice)."
    linhas = [f"Artigos com \"{r['termos']}\":"]
    for i, a in enumerate(r["artigos"], 1):
        linhas.append(f"[{i}] {a['titulo']} ({a['livro']})\n    link: {a['link']}\n    trecho: {a['trecho'][:300]}")
    linhas.append("Para o texto completo de um artigo, chame ler_artigo com o link.")
    return "\n".join(linhas)


def ler_artigo(link: str, maximo_caracteres: int = 6000) -> str:
    # So artigos da biblioteca deste PC: nunca um endereco qualquer (a ferramenta nao e um navegador).
    if link.startswith("/content/"):
        link = sabio.KIWIX + link
    if not link.startswith(sabio.KIWIX + "/content/"):
        raise ValueError(f"So leio artigos da biblioteca do cofre ({sabio.KIWIX}/content/...). Use o link que buscar_bibliotecas devolveu.")
    texto = sabio.html_para_texto(sabio.http_texto(link))
    limite = max(500, min(int(maximo_caracteres), 40000))
    return texto[:limite] + ("\n\n(...cortado; peca mais caracteres se precisar)" if len(texto) > limite else "")


def trechos_com_fonte(pergunta: str, quantos: int = 6) -> str:
    """O "perguntar com fonte" sem a resposta da IA: busca pelas palavras da pergunta, le os artigos e deixa o
    reordenador escolher os melhores trechos. Usa so o reordenador pequeno, nao o modelo de chat."""
    livros = sabio.livros_kiwix()
    if not livros:
        raise RuntimeError("A biblioteca nao esta respondendo. Ligue a biblioteca (menu, opcao 3, ou a Central).")
    palavras = " ".join(sabio.palavras_da_pergunta(pergunta))
    achados = sabio.buscar_kiwix({"pt": palavras, "en": palavras}, livros, 3, 10)
    trechos, origem = [], []
    for titulo, link in achados:
        try:
            texto = sabio.html_para_texto(sabio.http_texto(sabio.KIWIX + link))
        except Exception:
            continue
        for t in sabio.fatiar(texto)[:6]:
            trechos.append(t)
            origem.append((titulo, sabio.KIWIX + link))
    if not trechos:
        return "Nada encontrado nas bibliotecas para essa pergunta. Tente buscar_bibliotecas com outras palavras."
    n = max(1, min(int(quantos), 12))
    try:
        melhores = sabio.reordenar(pergunta, [f"{origem[i][0]}\n{t}" for i, t in enumerate(trechos)], n)
    except Exception:
        melhores = list(range(min(n, len(trechos))))  # sem o reordenador (servidor de modelos fechado): os primeiros
    return "\n\n".join(f"[{k}] {origem[i][0]} - {origem[i][1]}\n{trechos[i]}" for k, i in enumerate(melhores, 1))


def respostas_guardadas(busca: str = "", quantas: int = 5) -> str:
    h = tarefas.Historico()
    itens = h.listar(busca, max(1, min(int(quantas), 20)))
    if not itens:
        return "Nenhuma resposta guardada com essas palavras."
    saida = []
    for i in itens:
        completo = h.pegar(i["id"]) or {}
        saida.append(f"Pergunta ({tarefas.quando_br(i['quando'])}, {i['modo']}): {i['pergunta']}\n{completo.get('resposta', i['trecho'])}")
    return "\n\n---\n\n".join(saida)


def qual_ferramenta(pedido: str) -> str:
    return _texto(tarefas.sugerir(pedido))


FERRAMENTAS = {
    "buscar_bibliotecas": (buscar_bibliotecas, "Busca artigos nas bibliotecas offline do cofre (Wikipedia, WikiMed, iFixit, manuais) pelas palavras da consulta. Devolve titulo, link e o trecho onde aparecem. Nao usa IA.",
                           {"consulta": {"type": "string", "description": "palavras ou pergunta, em portugues ou ingles"},
                            "maximo": {"type": "integer", "description": "quantos artigos (1 a 20)", "default": 8}}, ["consulta"]),
    "ler_artigo": (ler_artigo, "Le o texto de um artigo da biblioteca do cofre. Use o link que buscar_bibliotecas devolveu. Leia antes de responder: o trecho da busca e curto demais para citar.",
                   {"link": {"type": "string", "description": "link do artigo (http://127.0.0.1:8081/content/...)"},
                    "maximo_caracteres": {"type": "integer", "description": "tamanho maximo do texto (500 a 40000)", "default": 6000}}, ["link"]),
    "trechos_com_fonte": (trechos_com_fonte, "Os melhores trechos das bibliotecas para responder uma pergunta, ja lidos, reordenados e numerados [1], [2] para citar. E a forma mais rapida de responder com fonte.",
                          {"pergunta": {"type": "string"}, "quantos": {"type": "integer", "description": "1 a 12", "default": 6}}, ["pergunta"]),
    "respostas_guardadas": (respostas_guardadas, "Perguntas que o cofre ja respondeu, com a resposta inteira. Consultar nao gasta energia.",
                            {"busca": {"type": "string", "description": "palavras para filtrar (vazio = as mais recentes)", "default": ""},
                             "quantas": {"type": "integer", "default": 5}}, []),
    "qual_ferramenta": (qual_ferramenta, "Diz o jeito mais barato de resolver um pedido no cofre (so buscar, resposta rapida, com fonte, conselho, chat com um modelo especifico, ComfyUI), com o gasto estimado e avisos de emergencia ou saude.",
                        {"pedido": {"type": "string"}}, ["pedido"]),
}


def lista_ferramentas() -> list[dict]:
    return [{"name": nome, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": obrig}}
            for nome, (_, desc, props, obrig) in FERRAMENTAS.items()]


def atender(msg: dict) -> dict | None:
    """Uma mensagem JSON-RPC -> a resposta (None para notificacoes, que nao tem resposta)."""
    metodo, ident = msg.get("method"), msg.get("id")
    if ident is None:
        return None  # notificacao (ex.: notifications/initialized)
    try:
        if metodo == "initialize":
            pedido = (msg.get("params") or {}).get("protocolVersion") or VERSAO_PROTOCOLO
            resultado = {"protocolVersion": pedido, "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "cofre", "version": "1.0"}, "instructions": INSTRUCOES}
        elif metodo == "ping":
            resultado = {}
        elif metodo == "tools/list":
            resultado = {"tools": lista_ferramentas()}
        elif metodo == "tools/call":
            params = msg.get("params") or {}
            nome, argumentos = params.get("name"), params.get("arguments") or {}
            if nome not in FERRAMENTAS:
                return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32602, "message": f"ferramenta desconhecida: {nome}"}}
            funcao, _, props, _ = FERRAMENTAS[nome]
            try:
                texto = funcao(**{k: v for k, v in argumentos.items() if k in props})
                resultado = {"content": [{"type": "text", "text": _texto(texto)}], "isError": False}
            except Exception as erro:  # erro da ferramenta vai para a IA ler e corrigir, nao derruba o servidor
                resultado = {"content": [{"type": "text", "text": f"Erro: {erro}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32601, "message": f"metodo desconhecido: {metodo}"}}
    except Exception as erro:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": -32603, "message": str(erro)}}
    return {"jsonrpc": "2.0", "id": ident, "result": resultado}


def main() -> None:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    for linha in sys.stdin:
        if not linha.strip():
            continue
        try:
            msg = json.loads(linha)
        except ValueError:
            resposta = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalido"}}
        else:
            resposta = atender(msg)
        if resposta is not None:
            sys.stdout.write(json.dumps(resposta, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
