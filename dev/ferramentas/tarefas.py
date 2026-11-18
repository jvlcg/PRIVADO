# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Estrategia do cofre: o caminho mais barato para cada pedido, decidido sem ligar nenhuma IA.

  sugerir(texto)   -> que ferramenta usar, da recomendada para as alternativas, com a tarefa do catalogo
                      (a Central e o menu poem o gasto estimado de cada uma)
  Historico        -> perguntas ja respondidas, em dev\\historico (fora do git: o repositorio e publico).
                      Repetir uma pergunta mostra a resposta guardada: 0 Wh e nenhum servidor ligado.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sabio import palavras_da_pergunta, sem_acento  # noqa: E402
import papeis  # noqa: E402  (o modelo de cada papel, em catalogo\papeis.json)

ARQUIVO_HISTORICO = Path(__file__).resolve().parents[1] / "historico" / "perguntas.jsonl"

# Modos de responder, do mais barato ao mais caro, e a tarefa do catalogo (secao energia) de cada um.
MODOS = {
    "buscar": {"titulo": "Só buscar na biblioteca", "tarefa": "buscar", "nivel": 0},
    "rapida": {"titulo": "Resposta rápida, sem fontes", "tarefa": "rapida", "nivel": 1},
    "fonte": {"titulo": "Perguntar com fonte", "tarefa": "perguntar", "nivel": 2},
    "conselho": {"titulo": "Conselho de IAs", "tarefa": "conselho", "nivel": 3},
}
# O modelo da resposta rapida e o do papel "rapida" (catalogo\papeis.json); de fora, tarefas.MODELO_RAPIDO
# continua valendo (veja o __getattr__ no fim). As sugestoes de chat tambem seguem os papeis.

# ---------- Que ferramenta usar ----------

AVISO_SAUDE = "Não substitui um médico: se piorar ou houver sinal de alerta, procure atendimento."
AVISO_EMERGENCIA = "Emergência: se houver telefone, ligue 192 (SAMU) ou 193 (Bombeiros). Abaixo, o que fazer até a ajuda chegar."


def _s(acao: str, titulo: str, porque: str, tarefa: str, **extra) -> dict:
    return {"acao": acao, "titulo": titulo, "porque": porque, "tarefa": tarefa, **extra}


def _escada(pergunta_curta: bool) -> list[dict]:
    """O padrao: do mais barato ao mais caro. Termo solto (sem pergunta) quer o artigo; pergunta quer explicacao."""
    buscar = _s("buscar", MODOS["buscar"]["titulo"], "Lista os artigos que falam disso, sem ligar IA.", "buscar")
    rapida = _s("rapida", MODOS["rapida"]["titulo"], "Uma IA pequena responde em segundos, sem consultar a biblioteca.", "rapida")
    fonte = _s("fonte", MODOS["fonte"]["titulo"], "A IA lê a Wikipédia e as outras bibliotecas e cita de onde tirou.", "perguntar")
    conselho = _s("conselho", MODOS["conselho"]["titulo"], "Várias IAs respondem e um relator decide: para o que é difícil.", "conselho")
    return [buscar, fonte, rapida, conselho] if pergunta_curta else [fonte, buscar, rapida, conselho]


# Cada regra: tipo, expressao (sobre o texto sem acento, em minusculas) e as sugestoes, da recomendada em diante.
# A primeira regra que casar vale; nenhuma casando, vale a escada padrao.
_REGRAS: list[tuple[str, str, list[dict], str | None]] = [
    ("emergencia",
     r"\b(sangr\w*|hemorrag\w*|queimad\w*|engasg\w*|desmai\w*|convuls\w*|infarto|avc|parada cardiaca"
     r"|nao (esta |consegue |consigo )?respira\w*|falta de ar|sem ar|dor (forte |muito forte )?no peito"
     r"|afog\w*|envenen\w*|intoxica\w*|picad\w* (de|por)|picou|mordid\w* (de|por)|fratur\w*|choque eletrico|engoliu"
     r"|bebeu (agua sanitaria|veneno|soda|querosene|gasolina)|overdose|inconscient\w*|corte (fundo|profundo)|reanima\w*"
     r"|primeiros socorros)\b",
     [_s("buscar", "Abrir primeiros socorros na biblioteca", "O artigo na hora, sem esperar IA nenhuma.", "buscar"),
      _s("fonte", "Perguntar com fonte (WikiMed)", "A IA explica o passo a passo citando a WikiMed.", "perguntar")],
     AVISO_EMERGENCIA),
    # Saude logo depois da emergencia: "funcao do figado" ou "febre de 38-39" nao podem cair em codigo ou contas.
    ("saude",
     r"\b(dor(es)?|febre|remedio\w*|medicament\w*|dose|dosagem|sintoma\w*|doenca\w*|infec\w*|ferid\w*|gravid\w*|bebe|diarreia|vomit\w*"
     r"|tosse|alergi\w*|pressao (alta|baixa)|diabet\w*|antibiotic\w*|machucad\w*|inflama\w*|virus|bacteria|hepatite|figado|rim|rins"
     r"|renal|exame|vacina\w*|paciente|ferimento|curativo|pomada)\b",
     [_s("fonte", "Perguntar com fonte (WikiMed)", "A IA responde citando a WikiMed e a Wikipédia.", "perguntar"),
      _s("buscar", "Ler direto na biblioteca", "Os artigos da Wikipédia e das outras bibliotecas sobre o assunto, sem IA.", "buscar"),
      _s("chat", "Chat com o {modelo}", "Modelo de saúde, para conversar sobre o caso.", "chat", papel="medicina")],
     AVISO_SAUDE),
    ("lugar",
     r"\b(mapa|onde fica|como chego|como chegar|endereco|bairro|rota|caminho (para|ate)|mais proxim\w*|perto daqui|localiza\w*)\b",
     [_s("buscar", "Buscar o lugar na biblioteca", "Wikivoyage e Wikipédia: cidades, rotas, o que há em cada lugar.", "buscar"),
      _s("fonte", MODOS["fonte"]["titulo"], "A IA junta o que as bibliotecas dizem sobre o lugar.", "perguntar")],
     None),
    ("ler",
     r"\b(ler (uma |a |esta |essa )?(foto|imagem|documento)|extrai\w*|digitaliz\w*|ocr|texto d[aeo] (foto|imagem|documento)|escanead\w*|nota fiscal)\b",
     [_s("chat", "Chat com o {modelo}", "Lê fotos e PDFs escaneados, inclusive tabelas: anexe a imagem no chat.", "chat", papel="documentos")],
     None),
    # Transcrever e traduzir antes de criar: "transcrever o video de uma aula" e "traduzir a letra da musica para o
    # portugues" falam de video e musica sem querer criar nada.
    ("transcrever",
     r"\b(transcrev\w*|transcricao|legenda\w*|(o que|oque) (diz|fala) (o|esse|este) (audio|video)|gravacao|audio (para|em) texto)\b",
     [_s("menu", "Transcrever áudio (Whisper)", "Pelo menu do terminal: opção 8, com o caminho do arquivo WAV.", "transcrever", menu=8)],
     None),
    ("falar",
     r"\b(em voz alta|narr(e|ar|acao)|leia para mim|ler para mim|transform\w* em (audio|voz)|virar audio)\b",
     [_s("menu", "Falar em voz alta (Piper)", "Pelo menu do terminal: opção 9. Só usa o processador.", "falar", menu=9)],
     None),
    ("traduzir",
     r"\b(traduz\w*|traducao|translate|(em|para o|para|pro) (ingles|espanhol|frances|alemao|italiano|chines|japones|portugues))\b",
     [_s("chat", "Chat com o {modelo}", "O tradutor do cofre, inclusive texto em fotos.", "chat", papel="traducao"),
      _s("rapida", MODOS["rapida"]["titulo"], "Para uma frase curta, a IA pequena resolve.", "rapida")],
     None),
    # Criar so com verbo de criacao ou nome de obra: "logo" sozinho e o adverbio ("logo depois de comer").
    ("criar",
     r"\b(desenh\w*|ilustra\w*|logotipo|(gera|gere|gerar|cria|crie|criar|faca|faz|fazer|monte|montar|componha|compor)"
     r" (uma |um |o |a )?(imagem|foto|figura|video|musica|cancao|logo|modelo 3d|desenho|animacao|wallpaper|papel de parede)"
     r"|modelo 3d|em 3d)\b",
     [_s("comfyui", "Criar no ComfyUI", "Imagem, vídeo, música e 3D com modelos prontos (Browse Templates).", "comfyui")],
     None),
    ("codigo",
     r"\b(codigo|programa(r|cao)|python|javascript|typescript|java|c\+\+|rust|golang|script|bug|compila\w*|sql|html|css"
     r"|powershell|bash|linux|stack ?trace|exception|regex|api|git|funcao (em|no|do|de) (python|javascript|codigo|programa|excel))\b",
     [_s("chat", "Chat com o {modelo}", "O modelo de código do cofre, feito para programar e usar ferramentas.", "chat", papel="codigo"),
      _s("conselho", MODOS["conselho"]["titulo"], "Para um problema difícil: inclui o Stack Overflow nas fontes.", "conselho")],
     None),
    ("contas",
     r"(\b(calcul\w*|quanto (e|da|fica|custa)|porcentagem|percentual|equacao|juros|converte\w*|conversao|regra de tres|media de|raiz quadrada)\b"
     r"|\d+\s*[+*/x^%]\s*\d+)",  # sem o "-": "38-39 graus" e datas nao sao conta
     [_s("chat", "Chat com o {modelo}", "Raciocínio e contas, passo a passo.", "chat", papel="segunda-opiniao"),
      _s("rapida", MODOS["rapida"]["titulo"], "Para uma conta simples, a IA pequena resolve.", "rapida")],
     None),
    ("decisao",
     r"\b(devo|deveria|vale a pena|qual (e )?(o |a )?melhor|o que e melhor|compar\w*|pros e contras|vantagens e desvantagens"
     r"|decidir|escolher entre|recomenda\w*|ou (nao|melhor))\b",
     [_s("conselho", MODOS["conselho"]["titulo"], "Decisão: várias IAs opinam e um relator pesa os argumentos.", "conselho"),
      _s("fonte", MODOS["fonte"]["titulo"], "Uma IA só, com as fontes da biblioteca: mais barato.", "perguntar")],
     None),
]
_REGRAS_COMPILADAS = [(tipo, re.compile(padrao), sugestoes, aviso) for tipo, padrao, sugestoes, aviso in _REGRAS]
_PERGUNTA = re.compile(r"\?|\b(como|por que|porque|qual|quais|quando|onde|quanto|o que|oque|quem|explique|explica|diferenca)\b")


def sugerir(texto: str) -> dict:
    """{tipo, aviso, sugestoes: [{acao, titulo, porque, tarefa, modelo?, menu?}]}, a recomendada primeiro.
    acao: buscar | rapida | fonte | conselho (os modos de responder), chat (abrir o chat com `modelo`),
    comfyui ou menu (opcao `menu` do terminal)."""
    t = sem_acento(texto.lower()).strip()
    if not t:
        return {"tipo": "vazio", "aviso": None, "sugestoes": []}
    curta = len(palavras_da_pergunta(t)) <= 3 and not _PERGUNTA.search(t)
    for tipo, padrao, sugestoes, aviso in _REGRAS_COMPILADAS:
        if padrao.search(t):
            escolhidas = [dict(s) for s in sugestoes]
            for s in escolhidas:  # o chat sugerido e o do papel agora (uma troca de modelo vale aqui na hora)
                if s.get("papel"):
                    s["modelo"] = papeis.modelo(s["papel"])
                    s["titulo"] = s["titulo"].format(modelo=s["modelo"])
            # Completa com a escada padrao, sem repetir modo, ate 4 opcoes.
            for s in _escada(curta):
                if len(escolhidas) >= 4:
                    break
                if all(s["acao"] != e["acao"] for e in escolhidas if e["acao"] in MODOS):
                    escolhidas.append(s)
            return {"tipo": tipo, "aviso": aviso, "sugestoes": escolhidas[:4]}
    return {"tipo": "termo" if curta else "pergunta", "aviso": None, "sugestoes": _escada(curta)}


# ---------- Historico (respostas guardadas) ----------

# Na chave so saem artigos, preposicoes e palavras de pergunta. Letras, numeros, operadores e palavras que
# mudam o sentido ficam: "hepatite B" e "hepatite C", "com" e "sem alcool", "3+5" e "3*5" sao perguntas diferentes.
_FORA_DA_CHAVE = set("""o a os as um uma uns umas de do da dos das em no na nos nas num numa por pelo pela pelos pelas
para pra pro ao aos que qual quais quem como quando onde e eh ser esta isso isto me voce the of to in how what is""".split())


def chave(pergunta: str) -> str:
    """Mesma pergunta, mesma chave: sem acento, sem pontuacao e sem artigos ou palavras de pergunta ("Como
    purificar a agua?" e "purificar agua" sao a mesma; "hepatite B" e "hepatite C", nao)."""
    pedacos = re.findall(r"[a-z0-9]+|[+*/^%=<>-]", sem_acento(pergunta.lower()))
    return " ".join(p for p in pedacos if p not in _FORA_DA_CHAVE)


def _radical(palavra: str) -> str:
    # Plural e genero simples: "queimaduras" ~ "queimadura", "fervida" ~ "fervido".
    for fim in ("oes", "aes", "es", "s"):
        if palavra.endswith(fim) and len(palavra) > len(fim) + 3:
            palavra = palavra[: -len(fim)]
            break
    return palavra[:-1] if palavra[-1:] in ("a", "o") and len(palavra) > 4 else palavra


def _palavras(pergunta: str) -> set[str]:
    return {_radical(p) for p in chave(pergunta).split()}


class Historico:
    """Perguntas respondidas, uma por linha (JSON). Uma trava protege o arquivo: a Central atende em varias threads."""

    def __init__(self, arquivo: Path = ARQUIVO_HISTORICO):
        self.arquivo = arquivo
        self._trava = threading.Lock()

    def _ler(self) -> list[dict]:
        try:
            linhas = self.arquivo.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        itens = []
        for linha in linhas:
            try:
                itens.append(json.loads(linha))
            except ValueError:
                continue
        return itens

    def guardar(self, pergunta: str, modo: str, resposta: str, fontes: list | None = None, wh: float = 0.0,
                segundos: float = 0.0, modelo: str = "", interrompida: bool = False) -> dict:
        item = {"id": secrets.token_hex(4), "quando": time.strftime("%Y-%m-%dT%H:%M:%S"), "pergunta": pergunta.strip(),
                "chave": chave(pergunta), "modo": modo, "modelo": modelo, "resposta": resposta, "fontes": fontes or [],
                "wh": round(wh, 3), "segundos": round(segundos), "interrompida": interrompida}
        with self._trava:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            with self.arquivo.open("a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def procurar(self, pergunta: str, modo: str) -> dict | None:
        """A resposta guardada mais recente para a mesma pergunta, num modo igual ou melhor (uma resposta com
        fonte serve para quem pediu a rapida; o contrario nao). Respostas interrompidas nao contam."""
        alvo, nivel = chave(pergunta), MODOS.get(modo, MODOS["fonte"])["nivel"]
        with self._trava:
            itens = self._ler()
        for item in reversed(itens):
            if (item.get("chave") == alvo and not item.get("interrompida")
                    and MODOS.get(item.get("modo"), {"nivel": -1})["nivel"] >= nivel):
                return item
        return None

    def parecidas(self, pergunta: str, quantas: int = 3, minimo: float = 0.5) -> list[dict]:
        """Perguntas antigas com quase as mesmas palavras (semelhanca de Jaccard), sem a identica."""
        alvo, base = chave(pergunta), _palavras(pergunta)
        if not base:
            return []
        with self._trava:
            itens = self._ler()
        vistas, achadas = set(), []
        for item in reversed(itens):
            c = item.get("chave", "")
            if c == alvo or c in vistas:
                continue
            vistas.add(c)
            outras = _palavras(item.get("pergunta", ""))
            nota = len(base & outras) / len(base | outras) if outras else 0
            if nota >= minimo:
                achadas.append((nota, item))
        achadas.sort(key=lambda x: -x[0])
        return [resumo(i) for _, i in achadas[:quantas]]

    def listar(self, busca: str = "", limite: int = 100) -> list[dict]:
        """As mais recentes primeiro; `busca` filtra pelas palavras (sem acento) da pergunta e da resposta."""
        termos = sem_acento(busca.lower()).split()
        with self._trava:
            itens = self._ler()
        saida = []
        for item in reversed(itens):
            texto = sem_acento((item.get("pergunta", "") + " " + item.get("resposta", "")).lower())
            if all(t in texto for t in termos):
                saida.append(resumo(item))
                if len(saida) >= limite:
                    break
        return saida

    def pegar(self, ident: str) -> dict | None:
        with self._trava:
            return next((i for i in self._ler() if i.get("id") == ident), None)

    def esquecer(self, ident: str) -> bool:
        with self._trava:
            itens = self._ler()
            restantes = [i for i in itens if i.get("id") != ident]
            if len(restantes) == len(itens):
                return False
            temporario = self.arquivo.with_suffix(".tmp")
            temporario.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in restantes), encoding="utf-8")
            temporario.replace(self.arquivo)
            return True


def resumo(item: dict) -> dict:
    """O que a lista mostra (sem a resposta inteira)."""
    texto = re.sub(r"[_*#\[\]()]", "", item.get("resposta", ""))
    texto = re.sub(r"\s+", " ", texto.replace("Resposta rapida, sem consultar a biblioteca: confira antes de seguir.", "")).strip()
    return {"id": item.get("id"), "quando": item.get("quando"), "pergunta": item.get("pergunta"), "modo": item.get("modo"),
            "wh": item.get("wh", 0), "interrompida": item.get("interrompida", False),
            "trecho": texto[:160] + ("..." if len(texto) > 160 else "")}


def quando_br(iso: str) -> str:
    """'2026-10-28T14:05:00' -> '28/10 às 14:05' (com o ano se nao for o atual)."""
    try:
        t = time.strptime(iso, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return iso or ""
    data = time.strftime("%d/%m" if t.tm_year == time.localtime().tm_year else "%d/%m/%Y", t)
    return f"{data} às {time.strftime('%H:%M', t)}"


# ---------- Ficha medica da familia ----------
# Inspirada na Ficha Medica do iPhone (e nas notas do N.O.M.A.D.): alergias, remedios de uso continuo, tipo
# sanguineo e contatos, para a hora do aperto. Fica so neste PC, junto do historico (fora do GitHub). A IA usa a
# ficha de quem a pergunta cita pelo nome: "posso dar dipirona pra Ana?" leva em conta a alergia da Ana.
ARQUIVO_FICHA = ARQUIVO_HISTORICO.parent / "ficha-medica.json"
CAMPOS_PESSOA = {"nome": 60, "nascimento": 40, "sangue": 10, "alergias": 300, "remedios": 400, "condicoes": 300, "observacoes": 400}
CAMPOS_CONTATO = {"nome": 60, "telefone": 30, "relacao": 40}
TIPOS_SANGUE = ("", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", "não sei")


def _limpo(valor, tamanho: int) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", str(valor or "")).strip()[:tamanho]


def ler_ficha() -> dict:
    try:
        f = json.loads(ARQUIVO_FICHA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        f = {}
    return {"pessoas": f.get("pessoas") or [], "contatos": f.get("contatos") or [],
            "ponto_encontro": f.get("ponto_encontro") or "", "atualizada": f.get("atualizada")}


def salvar_ficha(dados: dict) -> dict:
    """Guarda a ficha so com os campos conhecidos, com tamanho limitado (o que vem do navegador nao e confiavel)."""
    pessoas = [{c: _limpo(p.get(c), n) for c, n in CAMPOS_PESSOA.items()}
               for p in (dados.get("pessoas") or [])[:12] if isinstance(p, dict) and _limpo(p.get("nome"), 60)]
    for p in pessoas:
        if p["sangue"] not in TIPOS_SANGUE:
            p["sangue"] = ""
    contatos = [{c: _limpo(x.get(c), n) for c, n in CAMPOS_CONTATO.items()}
                for x in (dados.get("contatos") or [])[:8]
                if isinstance(x, dict) and (_limpo(x.get("nome"), 60) or _limpo(x.get("telefone"), 30))]
    ficha = {"pessoas": pessoas, "contatos": contatos, "ponto_encontro": _limpo(dados.get("ponto_encontro"), 300),
             "atualizada": time.strftime("%Y-%m-%dT%H:%M:%S")}
    ARQUIVO_FICHA.parent.mkdir(parents=True, exist_ok=True)
    temporario = ARQUIVO_FICHA.with_suffix(".tmp")
    temporario.write_text(json.dumps(ficha, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(ARQUIVO_FICHA)  # troca de uma vez: uma queda de energia no meio nao estraga a ficha
    return ficha


def _linha_pessoa(p: dict) -> str:
    partes = [p["nome"]]
    if p.get("nascimento"):
        partes.append(f"nascimento ou idade: {p['nascimento']}")
    if p.get("sangue"):
        partes.append(f"sangue {p['sangue']}")
    partes.append(f"alergias: {p.get('alergias') or 'nenhuma anotada'}")
    for campo, nome in (("remedios", "remédios de uso contínuo"), ("condicoes", "condições"), ("observacoes", "observações")):
        if p.get(campo):
            partes.append(f"{nome}: {p[campo]}")
    return "; ".join(partes)


def ficha_para(pergunta: str, ficha: dict | None = None) -> str:
    """A ficha de quem a pergunta cita pelo primeiro nome (palavra inteira, sem acento; "Mãe" e "Pai" valem).
    Vazio se a pergunta nao cita ninguem da ficha."""
    ficha = ficha if ficha is not None else ler_ficha()
    texto = f" {sem_acento(pergunta.lower())} "
    linhas = []
    for p in ficha.get("pessoas") or []:
        nome = sem_acento(str(p.get("nome") or "").lower()).split()
        if nome and len(nome[0]) >= 3 and re.search(rf"\b{re.escape(nome[0])}\b", texto):
            linhas.append(_linha_pessoa(p))
    return "\n".join(linhas)


def texto_ficha(ficha: dict | None = None) -> str:
    """A ficha inteira em texto, para os agentes (MCP) e para a resposta da IA."""
    ficha = ficha if ficha is not None else ler_ficha()
    if not ficha.get("pessoas") and not ficha.get("contatos"):
        return "A ficha médica ainda está vazia. Ela é preenchida na Central (Início, botão SOS)."
    partes = [_linha_pessoa(p) for p in ficha.get("pessoas") or []]
    if ficha.get("contatos"):
        partes.append("Contatos de emergência: " + "; ".join(
            " ".join(x for x in (c.get("nome"), c.get("relacao") and f"({c['relacao']})", c.get("telefone")) if x)
            for c in ficha["contatos"]))
    if ficha.get("ponto_encontro"):
        partes.append(f"Ponto de encontro: {ficha['ponto_encontro']}")
    return "\n".join(partes)


def __getattr__(nome: str):
    """tarefas.MODELO_RAPIDO, o nome antigo: o modelo do papel "rapida" agora."""
    if nome == "MODELO_RAPIDO":
        return papeis.modelo("rapida")
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
