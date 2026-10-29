# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Central do Cofre: painel no navegador (http://127.0.0.1:8070) que mostra o que esta ligado, liga
cada servico com um clique, mostra os modelos na memoria e o consumo da placa de video, fecha tudo
e responde perguntas citando as bibliotecas (o mesmo do sabio.py, com um modelo so).
So atende este PC (127.0.0.1) e recusa pedidos vindos de outros sites.

Uso (pelo wrapper A:\\scripts\\central.ps1: menu, opcao 1, ou dois cliques em A:\\Painel.cmd):
  central.py [--porta 8070]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sabio  # noqa: E402  (HTTP com a chave de acesso e a checagem de origem)

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
LIGANDO: dict[str, float] = {}  # servico -> quando foi pedido; evita abrir duas janelas do mesmo
ESPERA_LIGAR = 300  # depois disso o painel avisa que o servico nao ligou
_placa = {"quando": 0.0, "dados": None}
_mapa = {"quando": 0.0, "url": None}


def endereco_mapa() -> str | None:
    """Pagina do mapa offline na biblioteca (o do Brasil, se houver; senao o primeiro mapa), guardada por 60 s."""
    if time.time() - _mapa["quando"] < 60:
        return _mapa["url"]
    mapas = sorted(nome for nome, _ in sabio.livros_kiwix() if nome.startswith("maps_"))
    preferido = next((m for m in mapas if m.startswith("maps_en_brazil")), mapas[0] if mapas else None)
    _mapa.update(quando=time.time(), url=f"{sabio.KIWIX}/content/{preferido}" if preferido else None)
    return _mapa["url"]


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


def texto_custo(wh: float) -> str:
    """'~1,4 Wh ≈ R$ 0,002' na tarifa do catalogo."""
    reais = wh / 1000 * float(energia().get("tarifa_kwh") or 1.25)
    txt_wh = f"{wh / 1000:.2f} kWh" if wh >= 1000 else f"{wh:.0f} Wh" if wh >= 10 else f"{wh:.1f} Wh"
    txt_r = "menos de R$ 0,001" if reais < 0.0005 else f"R$ {reais:.3f}" if reais < 0.1 else f"R$ {reais:.2f}"
    return f"~{txt_wh} ≈ {txt_r}".replace(".", ",")


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
        "mapa": endereco_mapa() if ligados["biblioteca"] else None,
        "modo_jogo": MODO_JOGO.exists(),
        "pc_w": pc_w,
        "pc_custo_hora": texto_custo(pc_w) + " por hora" if pc_w else None,
        "energia": {"distribuidora": e.get("distribuidora", ""), "tarifa": f"R$ {float(e.get('tarifa_kwh') or 0):.2f}/kWh".replace(".", ","),
                    "estimativas": {t: estimativa(t) for t in ("chat", "biblioteca", "perguntar", "conselho", "comfyui", "pc-ligado")}},
    }


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
    _placa["quando"] = _mapa["quando"] = 0.0
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
    _placa["quando"] = _mapa["quando"] = 0.0
    return {"ok": r.returncode == 0, "ligado": MODO_JOGO.exists(), "texto": (r.stdout or r.stderr).strip()[-600:]}


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
        self.end_headers()
        self.wfile.write(dados)

    def _json(self, codigo: int, obj) -> None:
        self._enviar(codigo, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _local_ok(self) -> bool:
        return sabio.pedido_local_ok(self.headers.get("Host"), self.headers.get("Origin"))

    def do_GET(self):
        if not self._local_ok():
            return self._json(403, {"erro": "pedido de outro site bloqueado"})
        if self.path in ("/", "/index.html"):
            self._enviar(200, "text/html; charset=utf-8", PAINEL.read_bytes())
        elif self.path == "/api/estado":
            self._json(200, estado())
        elif self.path == "/api/chave":
            # So esta pagina le a resposta: a Central nao libera CORS, barra nomes de dominio (DNS rebinding)
            # e recusa o que o navegador marca como vindo de outro site, mesmo sem Origin.
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self._json(403, {"erro": "pedido de outro site bloqueado"})
            self._json(200, {"chave": sabio.chave_api()})
        elif self.path == "/health":
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
                self._perguntar(str(corpo["pergunta"]).strip())
            elif self.path == "/api/agora":
                AGORA.set()
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

    def _perguntar(self, pergunta: str) -> None:
        """Perguntar com fonte (o mesmo do menu, opcao 4), com o andamento em tempo real (SSE)."""
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

        if not TRAVA_PERGUNTA.acquire(blocking=False):
            avisar("Outra pergunta esta sendo respondida; aguardando a vez...")
            TRAVA_PERGUNTA.acquire()
        try:
            if MODO_JOGO.exists():
                raise RuntimeError("Modo jogo ligado: as IAs estao desligadas. Saia do modo jogo para perguntar.")
            AGORA.clear()
            garantir_ligados(["chat", "biblioteca"], avisar)
            evento({"tipo": "final", **sabio.perguntar_com_fonte(pergunta, avisar=avisar, parar=AGORA)})
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
