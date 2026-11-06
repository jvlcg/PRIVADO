# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Central do Cofre: painel no navegador (http://127.0.0.1:8070) que mostra o que esta ligado, liga
cada servico com um clique, mostra os modelos na memoria e o consumo da placa de video, fecha tudo
e responde perguntas do jeito mais barato que resolve: so buscar na biblioteca (sem IA), resposta
rapida (IA pequena) ou com fonte (o mesmo do sabio.py). Sugere a ferramenta certa para cada pedido
sem ligar IA (tarefas.py) e guarda as respostas: repetir uma pergunta custa 0 Wh.
So atende este PC (127.0.0.1) e recusa pedidos vindos de outros sites.

Uso (pelo wrapper A:\\scripts\\central.ps1: menu, opcao 1, ou dois cliques em A:\\Painel.cmd):
  central.py [--porta 8070]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sabio  # noqa: E402  (HTTP com a chave de acesso e a checagem de origem)
import tarefas  # noqa: E402  (que ferramenta usar e o historico de respostas)

RAIZ = Path(__file__).resolve().parents[2]
SCRIPTS = RAIZ / "scripts"
PAINEL = RAIZ / "docs" / "painel.html"
CATALOGO = RAIZ / "catalogo" / "modelos.json"
MODO_JOGO = RAIZ / "catalogo" / "modo-jogo.txt"  # existe = modo jogo ligado (scripts\modo-jogo.ps1)

# Cada servico: endereco que responde quando esta ligado e o script que o liga (sem abrir o navegador).
SERVICOS = {
    "chat": {"nome": "o chat", "teste": f"{sabio.LLM}/health", "script": "iniciar-servidor.ps1", "args": ["-SemNavegador"]},
    "biblioteca": {"nome": "a biblioteca", "teste": f"{sabio.KIWIX}/", "script": "iniciar-biblioteca.ps1", "args": ["-SemNavegador"]},
    "conselho": {"nome": "o conselho", "teste": "http://127.0.0.1:8090/health", "script": "conselho.ps1", "args": ["-Servir", "-SemNavegador"]},
    "comfyui": {"nome": "o ComfyUI", "teste": "http://127.0.0.1:8188/", "script": "iniciar-comfyui.ps1", "args": ["-SemNavegador"]},
}
TRAVA_PERGUNTA = threading.Lock()  # uma pergunta por vez: a placa de video e uma so
AGORA = threading.Event()  # "Responder agora": a pergunta em andamento responde com o que ja achou
# Lembra que o botao foi apertado: o sabio.responder() apaga o AGORA quando refaz a resposta sem raciocinar,
# e uma resposta cortada nao pode ficar guardada como completa.
PEDIU_AGORA = threading.Event()
LIGANDO: dict[str, float] = {}  # servico -> quando foi pedido; evita abrir duas janelas do mesmo
ESPERA_LIGAR = 300  # depois disso o painel avisa que o servico nao ligou
_placa = {"quando": 0.0, "dados": None}
HISTORICO = tarefas.Historico()
# Nome de cada tarefa do registro de gasto, para o painel de energia.
NOMES_TAREFA = {
    "perguntar": "Perguntar com fonte", "rapida": "Resposta rápida", "buscar": "Só buscar", "conselho": "Conselho de IAs",
    "chat": "Chat", "comfyui": "ComfyUI", "gerar": "Gerar imagem ou vídeo", "transcrever": "Transcrever áudio",
    "falar": "Falar em voz alta", "medir": "Medir o consumo", "sincronizar": "Sincronizar o cofre",
    "integridade": "Conferir a integridade", "status": "Status do acervo", "verificar": "Verificar novidades",
    "testar": "Testar o projeto", "biblioteca": "Biblioteca", "gigante": "Modelo gigante do HD",
}


def placa() -> dict | None:
    """Consumo e memoria da placa (nvidia-smi), guardados por 10 s para nao abrir um processo a cada consulta."""
    if time.time() - _placa["quando"] < 10:
        return _placa["dados"]
    try:
        saida = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,power.draw", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout
        usada, total, watts = (float(x) for x in saida.splitlines()[0].split(","))
        dados = {"vram_usada_gb": round(usada / 1024, 1), "vram_total_gb": round(total / 1024, 1), "watts": round(watts)}
    except Exception:
        dados = None
    _placa.update(quando=time.time(), dados=dados)
    return dados


class _Memoria(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memoria() -> dict | None:
    m = _Memoria()
    m.dwLength = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return {"ram_livre_gb": round(m.ullAvailPhys / 2**30, 1), "ram_total_gb": round(m.ullTotalPhys / 2**30, 1)}


_energia = {"quando": 0.0, "dados": None}


def energia() -> dict:
    """Tarifa e estimativas da secao "energia" do catalogo (as mesmas do menu), relidas a cada minuto."""
    if time.time() - _energia["quando"] > 60 or _energia["dados"] is None:
        try:
            _energia["dados"] = json.loads(CATALOGO.read_text(encoding="utf-8-sig")).get("energia") or {}
        except Exception:
            _energia["dados"] = _energia["dados"] or {}
        _energia["quando"] = time.time()
    return _energia["dados"]


texto_custo = sabio.texto_custo  # "~1,4 Wh ≈ R$ 0,002" na tarifa do catalogo


def texto_gasto_mes() -> str:
    g = sabio.gasto_mes()
    return f"{g['tarefas']} tarefa(s), {texto_custo(g['wh'])}" if g["tarefas"] else "nenhuma tarefa registrada neste mês"


def estimativa(tarefa: str) -> str:
    t = (energia().get("tarefas") or {}).get(tarefa) or {}
    if t.get("texto"):
        return t["texto"]
    base = t.get("wh") or t.get("watts")
    return f"{texto_custo(base)} {t.get('unidade', '')}".strip() if base else ""


class _Tempo(ctypes.Structure):
    _fields_ = [("baixo", ctypes.c_ulong), ("alto", ctypes.c_ulong)]


_cpu = {"antes": None}


def carga_cpu() -> float | None:
    """Fracao do processador em uso desde a consulta anterior (GetSystemTimes, sem abrir processo)."""
    ocioso, nucleo, usuario = _Tempo(), _Tempo(), _Tempo()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(ocioso), ctypes.byref(nucleo), ctypes.byref(usuario)):
        return None
    valor = lambda t: (t.alto << 32) | t.baixo  # noqa: E731
    agora = (valor(ocioso), valor(nucleo) + valor(usuario))  # o tempo "nucleo" ja inclui o ocioso
    antes, _cpu["antes"] = _cpu["antes"], agora
    if not antes or agora[1] <= antes[1]:
        return None
    return max(0.0, min(1.0, 1 - (agora[0] - antes[0]) / (agora[1] - antes[1])))


def consumo_pc(gpu_w: float | None, cpu: float | None) -> int | None:
    """Mesmo modelo do medir-energia.ps1: placa medida + processador pela carga + placa-mae e discos, /0,88 da fonte."""
    if gpu_w is None or cpu is None:
        return None
    return round((gpu_w + 35 + 160 * cpu + 40) / 0.88)


def modelos_na_memoria() -> list[dict]:
    try:
        dados = sabio.http_json(f"{sabio.LLM}/models", timeout=5).get("data", [])
    except Exception:
        return []
    saida = []
    for m in dados:
        valor = (m.get("status") or {}).get("value")
        if valor and valor != "unloaded":
            saida.append({"id": m["id"], "estado": valor})
    return saida


def estado() -> dict:
    with ThreadPoolExecutor(len(SERVICOS)) as ex:
        ligados = dict(zip(SERVICOS, ex.map(lambda s: sabio.servidor_ok(s["teste"]), SERVICOS.values())))
    agora = time.time()
    for nome in [n for n in LIGANDO if ligados[n]]:
        del LIGANDO[nome]
    p = placa()
    pc_w = consumo_pc(p["watts"] if p else None, carga_cpu())
    e = energia()
    return {
        "servicos": ligados,
        "ligando": sorted(n for n, t in LIGANDO.items() if agora - t < ESPERA_LIGAR),
        "falhou": sorted(n for n, t in LIGANDO.items() if agora - t >= ESPERA_LIGAR),
        "placa": p,
        "memoria": memoria(),
        "modelos": modelos_na_memoria() if ligados["chat"] else [],
        "modo_jogo": MODO_JOGO.exists(),
        "vigia": vigia_ligada(),
        "gasto_mes": texto_gasto_mes(),
        "gasto_mes_wh": round(sabio.gasto_mes()["wh"], 3),
        "pc_w": pc_w,
        "pc_custo_hora": texto_custo(pc_w) + " por hora" if pc_w else None,
        "energia": {"distribuidora": e.get("distribuidora", ""), "tarifa": f"R$ {float(e.get('tarifa_kwh') or 0):.2f}/kWh".replace(".", ","),
                    "tarifa_kwh": float(e.get("tarifa_kwh") or 0),
                    "estimativas": {t: estimativa(t) for t in ("chat", "biblioteca", "perguntar", "conselho", "comfyui", "pc-ligado",
                                                               "buscar", "rapida")},
                    # Gasto de cada modo de responder, em numero: a altura de cada degrau da "escada" do painel.
                    "wh_modos": {m: float(((e.get("tarefas") or {}).get(v["tarefa"]) or {}).get("wh") or 0)
                                 for m, v in tarefas.MODOS.items()}},
    }


def sugestoes(texto: str) -> dict:
    """O que usar para este pedido (sem IA), com o gasto de cada opcao, e se ja ha resposta guardada."""
    r = tarefas.sugerir(texto)
    gastos = energia().get("tarefas") or {}
    for s in r["sugestoes"]:
        s["gasto"] = estimativa(s["tarefa"])
        s["wh"] = float((gastos.get(s["tarefa"]) or {}).get("wh") or 0)
    guardada = HISTORICO.procurar(texto, "rapida") if texto.strip() else None
    r["guardada"] = tarefas.resumo(guardada) | {"quando_br": tarefas.quando_br(guardada["quando"])} if guardada else None
    r["parecidas"] = [p | {"quando_br": tarefas.quando_br(p["quando"])} for p in HISTORICO.parecidas(texto)] if texto.strip() else []
    return r


def pastas_conhecimento() -> list[Path]:
    pastas = [RAIZ / "conhecimento"]
    try:
        raiz_cofre = json.loads(CATALOGO.read_text(encoding="utf-8-sig")).get("cofre", {}).get("raiz")
        if raiz_cofre:
            pastas.append(Path(raiz_cofre) / "conhecimento")
    except Exception:
        pass
    return [p for p in pastas if p.is_dir()]


def acervo() -> dict:
    """Bibliotecas do catalogo: o que cada uma tem, onde esta (SSD ou HD) e o link quando a biblioteca esta ligada."""
    try:
        itens = json.loads(CATALOGO.read_text(encoding="utf-8-sig")).get("conhecimento") or []
    except Exception:
        itens = []
    arquivos = sorted(z.name for pasta in pastas_conhecimento() for z in pasta.glob("*.zim"))
    ligada = sabio.servidor_ok(f"{sabio.KIWIX}/")
    saida = []
    for i in itens:
        padrao = re.compile(re.escape(i.get("prefixo", "")) + r"_\d{4}-\d{2}[a-z]?\.zim$")
        achados = [a for a in arquivos if padrao.match(a)]
        livro = achados[-1][:-4] if achados else None
        saida.append({"id": i.get("id"), "nome": i.get("nome"), "uso": i.get("uso", ""), "tamanho_gb": i.get("tamanho_gb"),
                      "local": i.get("local"), "observar": i.get("status") == "observar", "baixada": bool(livro),
                      "versao": livro.rsplit("_", 1)[-1] if livro else None,
                      "link": f"{sabio.KIWIX}/content/{livro}" if livro and ligada else None})
    return {"ligada": ligada, "bibliotecas": saida}


def painel_energia() -> dict:
    """Gasto do mes por tarefa e dos ultimos 6 meses, para o painel de energia."""
    por_tarefa = [t | {"nome": NOMES_TAREFA.get(t["tarefa"], t["tarefa"]), "custo": texto_custo(t["wh"])} for t in sabio.gasto_por_tarefa()]
    meses = [m | {"custo": texto_custo(m["wh"])} for m in sabio.gasto_meses()]
    e = energia()
    pc_parado = float(e.get("pc_parado_w") or 114)
    return {"por_tarefa": por_tarefa, "meses": meses, "tarifa_detalhe": e.get("tarifa_detalhe", ""),
            "pc_parado_w": pc_parado, "pc_parado_dia": texto_custo(pc_parado * 24), "pc_parado_mes": texto_custo(pc_parado * 24 * 30)}


def ligar(nome: str) -> dict:
    s = SERVICOS[nome]
    if MODO_JOGO.exists():
        return {"ok": False, "texto": "modo jogo ligado: saia dele para ligar as IAs"}
    if sabio.servidor_ok(s["teste"]):
        return {"ok": True, "texto": "ja estava ligado"}
    if time.time() - LIGANDO.get(nome, 0) < ESPERA_LIGAR:
        return {"ok": True, "texto": "ja esta ligando"}
    # Janela propria e minimizada, como no menu: fechar a Central nao derruba o servico.
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 7  # SW_SHOWMINNOACTIVE
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / s["script"]), *s["args"]],
                     cwd=str(SCRIPTS), creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
    LIGANDO[nome] = time.time()
    return {"ok": True, "texto": "ligando"}


def parar_tudo() -> dict:
    # A Central continua aberta (ela e o uv que a iniciou ficam de fora).
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "parar-tudo.ps1"),
                        "-Manter", f"{os.getpid()},{os.getppid()}"],
                       capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    LIGANDO.clear()
    _placa["quando"] = 0.0
    return {"ok": r.returncode == 0, "texto": (r.stdout or r.stderr).strip()[-600:]}


def garantir_ligados(nomes: list[str], avisar) -> None:
    """Liga o que faltar e espera responder (os modelos do HD demoram mais)."""
    for n in nomes:
        if not sabio.servidor_ok(SERVICOS[n]["teste"]):
            avisar(f"Ligando {SERVICOS[n]['nome']}...")
            ligar(n)
    prazo = time.time() + 240
    while not all(sabio.servidor_ok(SERVICOS[n]["teste"]) for n in nomes):
        if time.time() > prazo:
            raise RuntimeError("O chat ou a biblioteca nao ligou em 4 minutos. Use o menu (opcoes 2 e 3) para ver o erro.")
        time.sleep(2)


def modo_jogo(ligar_modo: bool) -> dict:
    """Liga: fecha tudo pelo modo-jogo.ps1 (poupando a Central so ate responder; depois ela fecha tambem).
    Desliga: as IAs voltam a abrir."""
    args = ["-Ligar", "-Manter", f"{os.getpid()},{os.getppid()}"] if ligar_modo else ["-Sair"]
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / "modo-jogo.ps1"), *args],
                       capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
    LIGANDO.clear()
    _placa["quando"] = 0.0
    return {"ok": r.returncode == 0, "ligado": MODO_JOGO.exists(), "texto": (r.stdout or r.stderr).strip()[-600:]}


PID_VIGIA = RAIZ / "logs" / "vigia-desligar.pid"  # escrito pelo desligar-ao-terminar.ps1 enquanto vigia


def processo_vivo(pid: int, programa: str | None = None) -> bool:
    """Pergunta ao Windows se o processo existe (os.kill no Windows mataria o processo em vez de testar) e,
    com `programa`, se ele e esse executavel: um PID velho pode ter sido reaproveitado por outro programa."""
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        codigo = ctypes.c_ulong()
        if not (k.GetExitCodeProcess(h, ctypes.byref(codigo)) and codigo.value == 259):  # STILL_ACTIVE
            return False
        if programa:
            nome = ctypes.create_unicode_buffer(1024)
            tamanho = ctypes.c_ulong(1024)
            if not k.QueryFullProcessImageNameW(h, 0, nome, ctypes.byref(tamanho)):
                return False
            return Path(nome.value).name.lower() == programa.lower()
        return True
    finally:
        k.CloseHandle(h)


def vigia_ligada() -> bool:
    try:
        return processo_vivo(int(PID_VIGIA.read_text(encoding="utf-8-sig").split()[0]), "powershell.exe")
    except (OSError, ValueError, IndexError):
        return False


def vigia(ligar_vigia: bool) -> dict:
    """Liga a vigia de desligar numa janela minimizada (como os servicos) ou para ela."""
    script = str(SCRIPTS / "desligar-ao-terminar.ps1")
    if ligar_vigia:
        if vigia_ligada():
            return {"ok": True, "texto": "a vigia já estava ligada"}
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script],
                         cwd=str(SCRIPTS), creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=info)
        prazo = time.time() + 15
        while not vigia_ligada() and time.time() < prazo:
            time.sleep(0.5)
        return {"ok": vigia_ligada(), "texto": "vigia ligada" if vigia_ligada() else "a vigia não abriu: use o menu, opção 19"}
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Parar"],
                       capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    return {"ok": not vigia_ligada(), "texto": "vigia parada" if not vigia_ligada() else (r.stdout or r.stderr).strip()[-300:]}


def descarregar(modelo: str) -> dict:
    sabio.http_json(f"{sabio.LLM}/models/unload", {"model": modelo}, timeout=120)
    _placa["quando"] = 0.0
    return {"ok": True, "texto": f"{modelo} descarregado"}


class Central(BaseHTTPRequestHandler):
    server_version = "CentralDoCofre/1"

    def log_message(self, formato, *args):
        pass

    def _enviar(self, codigo: int, tipo: str, dados: bytes) -> None:
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        # Nenhum outro site pode abrir a Central dentro de uma moldura e induzir cliques nela.
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, codigo: int, obj) -> None:
        self._enviar(codigo, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _local_ok(self) -> bool:
        return sabio.pedido_local_ok(self.headers.get("Host"), self.headers.get("Origin"))

    def do_GET(self):
        if not self._local_ok():
            return self._json(403, {"erro": "pedido de outro site bloqueado"})
        rota, _, consulta = self.path.partition("?")
        params = {k: v[-1] for k, v in urllib.parse.parse_qs(consulta).items()}
        if rota in ("/", "/index.html"):
            self._enviar(200, "text/html; charset=utf-8", PAINEL.read_bytes())
        elif rota == "/api/estado":
            self._json(200, estado())
        elif rota == "/api/sugerir":
            self._json(200, sugestoes(params.get("texto", "")[:2000]))
        elif rota == "/api/historico":
            if params.get("id"):
                item = HISTORICO.pegar(params["id"])
                if not item:
                    return self._json(404, {"erro": "nao encontrado"})
                return self._json(200, item | {"quando_br": tarefas.quando_br(item["quando"])})
            lista = HISTORICO.listar(params.get("busca", ""), int(params.get("limite") or 100))
            self._json(200, {"itens": [i | {"quando_br": tarefas.quando_br(i["quando"])} for i in lista]})
        elif rota == "/api/acervo":
            self._json(200, acervo())
        elif rota == "/api/energia":
            self._json(200, painel_energia())
        elif rota == "/api/chave":
            # So esta pagina le a resposta: a Central nao libera CORS, barra nomes de dominio (DNS rebinding)
            # e recusa o que o navegador marca como vindo de outro site, mesmo sem Origin.
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self._json(403, {"erro": "pedido de outro site bloqueado"})
            self._json(200, {"chave": sabio.chave_api()})
        elif rota == "/health":
            self._json(200, {"status": "ok"})
        else:
            self._json(404, {"erro": "nao encontrado"})

    def do_POST(self):
        # Acoes so com JSON: um formulario de outro site nao consegue mandar isso sem o navegador perguntar antes.
        if not self._local_ok() or not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(403, {"erro": "pedido de outro site bloqueado"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            corpo = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"erro": "JSON invalido"})
        try:
            if self.path == "/api/ligar" and corpo.get("servico") in SERVICOS:
                self._json(200, ligar(corpo["servico"]))
            elif self.path == "/api/parar-tudo":
                self._json(200, parar_tudo())
            elif self.path == "/api/descarregar" and corpo.get("modelo"):
                self._json(200, descarregar(str(corpo["modelo"])))
            elif self.path == "/api/perguntar" and str(corpo.get("pergunta") or "").strip():
                modo = corpo.get("modo") if corpo.get("modo") in ("buscar", "rapida", "fonte") else "fonte"
                self._perguntar(str(corpo["pergunta"]).strip()[:4000], modo, bool(corpo.get("de_novo")))
            elif self.path == "/api/vigia":
                self._json(200, vigia(bool(corpo.get("ligar"))))
            elif self.path == "/api/esquecer" and corpo.get("id"):
                self._json(200, {"ok": HISTORICO.esquecer(str(corpo["id"]))})
            elif self.path == "/api/agora":
                AGORA.set()
                PEDIU_AGORA.set()
                self._json(200, {"ok": True})
            elif self.path == "/api/modo-jogo":
                r = modo_jogo(bool(corpo.get("ligar")))
                self._json(200, r)
                if r["ligado"]:
                    # Tudo fechado: a Central sai tambem, depois de responder (shutdown precisa de outra thread).
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self._json(404, {"erro": "nao encontrado"})
        except Exception as erro:
            self._json(500, {"erro": str(erro)})

    def _perguntar(self, pergunta: str, modo: str = "fonte", de_novo: bool = False) -> None:
        """Responde do jeito pedido, com o andamento em tempo real (SSE): "buscar" (so a biblioteca, sem IA),
        "rapida" (IA pequena, sem fontes) ou "fonte" (o mesmo do menu, opcao 4). Pergunta repetida mostra a
        resposta guardada, sem ligar nada, a menos que pecam de novo."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        vivo = [True]

        def evento(obj: dict) -> None:
            if not vivo[0]:
                return
            try:
                self.wfile.write(f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except OSError:
                vivo[0] = False  # o navegador fechou; a resposta termina mesmo assim

        def avisar(texto: str) -> None:
            evento({"tipo": "etapa", "texto": texto})

        # A resposta guardada vem antes do modo jogo: mostra-la nao liga nada.
        if modo != "buscar" and not de_novo:
            guardada = HISTORICO.procurar(pergunta, modo)
            if guardada:
                return evento({"tipo": "final", "modo": guardada["modo"], "resposta": guardada["resposta"], "fontes": guardada["fontes"],
                               "id": guardada["id"], "guardada": {"quando_br": tarefas.quando_br(guardada["quando"])},
                               "gasto": "0 Wh: resposta guardada, nada foi ligado"})
        if MODO_JOGO.exists():
            return evento({"tipo": "falha", "texto": "Modo jogo ligado: as IAs e a biblioteca estão desligadas. Saia do modo jogo para perguntar."})
        if modo == "buscar":
            # Sem placa de video: nao precisa esperar a vez de outra pergunta.
            try:
                garantir_ligados(["biblioteca"], avisar)
                avisar("Buscando nas bibliotecas, sem IA")
                evento({"tipo": "final", "modo": "buscar", **sabio.buscar_sem_ia(pergunta), "gasto": estimativa("buscar")})
            except Exception as erro:
                evento({"tipo": "falha", "texto": str(erro)})
            return
        if not TRAVA_PERGUNTA.acquire(blocking=False):
            avisar("Outra pergunta está sendo respondida; aguardando a vez...")
            TRAVA_PERGUNTA.acquire()
            # Esperou a vez: se era a mesma pergunta, a resposta dela acabou de ser guardada.
            guardada = None if de_novo else HISTORICO.procurar(pergunta, modo)
            if guardada:
                TRAVA_PERGUNTA.release()
                return evento({"tipo": "final", "modo": guardada["modo"], "resposta": guardada["resposta"], "fontes": guardada["fontes"],
                               "id": guardada["id"], "guardada": {"quando_br": tarefas.quando_br(guardada["quando"])},
                               "gasto": "0 Wh: a mesma pergunta acabou de ser respondida"})
        try:
            AGORA.clear()
            PEDIU_AGORA.clear()
            tarefa = "rapida" if modo == "rapida" else "perguntar"
            watts = float(((energia().get("tarefas") or {}).get(tarefa) or {}).get("watts") or 170)
            if modo == "rapida":
                garantir_ligados(["chat"], avisar)
                # O botao "Responder agora" so aparece quando ja ha o que responder: o modelo esta ligado.
                evento({"tipo": "inicio", "watts": watts})
                inicio = time.time()
                avisar(f"Respondendo com {tarefas.MODELO_RAPIDO}, sem consultar a biblioteca")
                r = {"resposta": sabio.responder_direto(pergunta, tarefas.MODELO_RAPIDO, parar=AGORA), "fontes": [],
                     "modelo": tarefas.MODELO_RAPIDO}
            else:
                evento({"tipo": "inicio", "watts": watts})
                garantir_ligados(["chat", "biblioteca"], avisar)
                inicio = time.time()
                r = sabio.perguntar_com_fonte(pergunta, avisar=avisar, parar=AGORA) | {"modelo": sabio.MODELO_CHAT}
            segundos = time.time() - inicio
            wh = watts * segundos / 3600
            sabio.registrar_gasto(tarefa, segundos, watts)
            interrompida = PEDIU_AGORA.is_set() or "(resposta interrompida a pedido)" in r["resposta"]
            item = HISTORICO.guardar(pergunta, modo, r["resposta"], r.get("fontes"), wh, segundos, r["modelo"], interrompida)
            evento({"tipo": "final", "modo": modo, **r, "id": item["id"],
                    "gasto": f"{segundos:.0f} s com o PC em ~{watts:.0f} W: {texto_custo(wh)}"})
        except Exception as erro:
            evento({"tipo": "falha", "texto": str(erro)})
        finally:
            TRAVA_PERGUNTA.release()


def main() -> None:
    ap = argparse.ArgumentParser(description="Central do Cofre (painel no navegador)")
    ap.add_argument("--porta", type=int, default=8070)
    args = ap.parse_args()
    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Central)
    print(f"Central do Cofre:  http://127.0.0.1:{args.porta}")
    print("Para parar: Ctrl+C nesta janela (os servicos ligados continuam).", flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
