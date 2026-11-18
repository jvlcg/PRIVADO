# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Papeis do cofre: quem faz o que. As ferramentas pedem o modelo pelo papel ("principal", "rapida", "codigo"...),
nunca pelo nome. Atualizar um modelo e trocar o modelo do papel em catalogo\\papeis.json (pela Central, secao
Modelos, ou por scripts\\trocar-modelo.ps1): tudo passa a usar o novo na hora, sem mexer em codigo, e o anterior
fica guardado para voltar com um clique.

O arquivo e lido a cada consulta (e pequeno): uma troca vale sem reiniciar a Central nem o conselho.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO = RAIZ / "catalogo" / "papeis.json"
CATALOGO = RAIZ / "catalogo" / "modelos.json"
ESTADO = RAIZ / "catalogo" / "estado.json"
REGISTRO = RAIZ / "logs" / "trocas-de-modelo.csv"

# O time de 17/11/2026: vale se o papeis.json faltar ou estragar (o cofre nunca fica sem modelo).
PADRAO = {
    "principal": "gemma-4-26b-a4b-qat", "rapida": "gemma-4-12b-qat", "profundo": "qwen3.8-27b-iq3",
    "segunda-opiniao": "gpt-oss-20b", "codigo": "ornith-1.5-35b-a3b", "medicina": "medgemma-27b",
    "traducao": "translategemma-12b", "documentos": "glm-ocr", "leve": "gemma-4-e4b",
    "busca": "qwen3-embedding-0.6b", "reordenar": "qwen3-reranker-0.6b",
    "transcricao": "whisper-large-v3-turbo", "voz": "piper-pt-br", "imagem": "z-image-turbo",
}


def _json(caminho: Path) -> dict:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8-sig"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


def ler() -> list[dict]:
    """Os papeis, na ordem do arquivo. Sem o arquivo, os do PADRAO (so id e modelo)."""
    papeis = _json(ARQUIVO).get("papeis")
    if isinstance(papeis, list) and papeis:
        return [p for p in papeis if isinstance(p, dict) and p.get("id")]
    return [{"id": i, "nome": i, "modelo": m} for i, m in PADRAO.items()]


def modelo(papel: str) -> str:
    """O modelo que faz o papel agora."""
    for p in ler():
        if p.get("id") == papel and p.get("modelo"):
            return str(p["modelo"])
    return PADRAO.get(papel, "")


def resolver(valor):
    """'@principal' vira o modelo do papel; nome comum fica como esta. Vale dentro de listas e dicionarios, entao a
    secao "conselho" do catalogo pode usar papeis ("@principal") e nomes de modelo misturados."""
    if isinstance(valor, str) and valor.startswith("@"):
        return modelo(valor[1:]) or valor
    if isinstance(valor, list):
        return [resolver(v) for v in valor]
    if isinstance(valor, dict):
        return {k: resolver(v) for k, v in valor.items()}
    return valor


def catalogo() -> dict[str, dict]:
    return {m["id"]: m for m in _json(CATALOGO).get("modelos") or [] if isinstance(m, dict) and m.get("id")}


def baixados() -> set[str]:
    estado = _json(ESTADO)
    fora = set(estado.get("aposentados") or [])
    return {i for i, m in (estado.get("modelos") or {}).items() if isinstance(m, dict) and m.get("completo") and i not in fora}


def _resumo(m: dict | None, ident: str, feitos: set[str]) -> dict:
    m = m or {}
    return {"id": ident, "nome": m.get("nome") or ident, "tamanho_gb": m.get("tamanho_gb"), "parametros": m.get("parametros"),
            "licenca": m.get("licenca"), "local": m.get("local"), "tipo": m.get("tipo"), "uso": m.get("uso"),
            "baixado": ident in feitos, "no_catalogo": bool(m)}


def serve(papel: dict, m: dict) -> bool:
    """O modelo do catalogo serve para o papel: do tipo certo e do mesmo motor."""
    tipos = papel.get("tipos") or []
    return (not tipos or m.get("tipo") in tipos) and (not papel.get("motor") or m.get("motor") == papel["motor"])


def listar() -> list[dict]:
    """Os papeis com o modelo atual, o anterior (para voltar) e os candidatos do catalogo: os ja baixados primeiro."""
    cat, feitos = catalogo(), baixados()
    saida = []
    for p in ler():
        atual = str(p.get("modelo") or PADRAO.get(p["id"], ""))
        candidatos = [_resumo(m, i, feitos) for i, m in cat.items() if i != atual and serve(p, m)]
        candidatos.sort(key=lambda c: (not c["baixado"], str(c["nome"]).lower()))
        anterior = str(p.get("anterior") or "")
        saida.append({
            "id": p["id"], "nome": p.get("nome") or p["id"], "grupo": p.get("grupo") or "Outros", "uso": p.get("uso") or "",
            "tipos": p.get("tipos") or [], "motor": p.get("motor") or "", "troca": p.get("troca") or "automatica",
            "trocado_em": p.get("trocado_em") or "", "modelo": _resumo(cat.get(atual), atual, feitos),
            "anterior": _resumo(cat.get(anterior), anterior, feitos) if anterior else None, "candidatos": candidatos,
        })
    return saida


def usado_por(modelo_id: str) -> list[str]:
    """Os papeis que usam (ou guardam para voltar) este modelo, e o conselho se o citar pelo nome."""
    nomes = [str(p.get("nome") or p["id"]) for p in ler() if modelo_id in (p.get("modelo"), p.get("anterior"))]
    conselho = _json(CATALOGO).get("conselho") or {}
    citados = [conselho.get(k) for k in ("relator", "relator_profundo", "triagem")] + list(conselho.get("membros") or [])
    citados += list((conselho.get("especialistas") or {}).values())
    if modelo_id in citados:
        nomes.append("Conselho de IAs")
    return nomes


def _papeis_para_gravar() -> tuple[dict, list[dict]]:
    dados = _json(ARQUIVO)
    papeis = dados.get("papeis")
    if not isinstance(papeis, list) or not papeis:
        raise RuntimeError(f"Não achei os papéis em {ARQUIVO}: restaure o arquivo (git) antes de trocar modelos.")
    return dados, papeis


def _gravar(dados: dict) -> None:
    temporario = ARQUIVO.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporario.replace(ARQUIVO)  # troca de uma vez: uma queda de energia no meio nao estraga o arquivo


def _registrar(papel: str, de: str, para: str, acao: str) -> None:
    try:
        REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        novo = not REGISTRO.exists()
        with REGISTRO.open("a", encoding="utf-8") as f:
            if novo:
                f.write("data;papel;de;para;acao\n")
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')};{papel};{de};{para};{acao}\n")
    except OSError:
        pass


def _achar(papeis: list[dict], papel: str) -> dict:
    p = next((x for x in papeis if isinstance(x, dict) and x.get("id") == papel), None)
    if not p:
        raise ValueError(f"Papel desconhecido: {papel}.")
    return p


def trocar(papel: str, novo: str) -> dict:
    """Troca o modelo de um papel e guarda o anterior. So aceita modelo do catalogo, do tipo certo e ja baixado
    (baixar e com o trocar-modelo.ps1, que tambem testa o modelo antes de trocar)."""
    dados, papeis = _papeis_para_gravar()
    p = _achar(papeis, papel)
    nome = p.get("nome") or papel
    if p.get("troca") == "manual":
        raise ValueError(f"{nome}: a troca é manual (a ferramenta precisa de ajuste). Veja o guia, seção Modelos.")
    m = catalogo().get(novo)
    if not m:
        raise ValueError(f"{novo} não está no catálogo (catalogo\\modelos.json).")
    if not serve(p, m):
        raise ValueError(f"{m.get('nome') or novo} não serve para {nome}: é do tipo {m.get('tipo')}, e o papel pede {', '.join(p.get('tipos') or [])}.")
    if novo not in baixados():
        raise ValueError(f"{m.get('nome') or novo} ainda não foi baixado. Use o trocar-modelo.ps1: ele baixa, confere e testa antes de trocar.")
    if novo == p.get("modelo"):
        return p
    p["anterior"], p["modelo"] = str(p.get("modelo") or ""), novo
    p["trocado_em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _gravar(dados)
    _registrar(papel, p["anterior"], novo, "trocou")
    return p


def voltar(papel: str) -> dict:
    """Desfaz a ultima troca: o anterior volta, e o que estava passa a ser o anterior."""
    dados, papeis = _papeis_para_gravar()
    p = _achar(papeis, papel)
    anterior = str(p.get("anterior") or "")
    if not anterior:
        raise ValueError(f"{p.get('nome') or papel}: não há modelo anterior para voltar.")
    if anterior not in baixados():
        raise ValueError(f"O anterior ({anterior}) já foi guardado para apagar: baixe de novo para voltar a ele.")
    p["modelo"], p["anterior"] = anterior, str(p.get("modelo") or "")
    p["trocado_em"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _gravar(dados)
    _registrar(papel, p["anterior"], anterior, "voltou")
    return p


def manter(papel: str) -> dict:
    """Gostou do novo: o anterior deixa de ser a volta. Diz se ele ficou sem uso, para guardar os arquivos e apagar."""
    dados, papeis = _papeis_para_gravar()
    p = _achar(papeis, papel)
    antigo = str(p.get("anterior") or "")
    p["anterior"] = ""
    _gravar(dados)
    if antigo:
        _registrar(papel, antigo, str(p.get("modelo") or ""), "manteve")
    return {"papel": p, "antigo": antigo, "sem_uso": bool(antigo) and not usado_por(antigo)}


def main(argv: list[str]) -> int:
    """Linha de comando, para os scripts do PowerShell (um so lugar grava o papeis.json):
    papeis.py | json | trocar PAPEL MODELO | voltar PAPEL | manter PAPEL | usado-por MODELO"""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    acao = argv[0] if argv else "listar"
    try:
        if acao == "listar":
            for item in listar():
                volta = f"  (volta: {item['anterior']['id']})" if item["anterior"] else ""
                print(f"{item['grupo']:14} {item['nome']:24} {item['modelo']['id']}{volta}")
            return 0
        if acao == "json":
            resultado = listar()
        elif acao == "trocar" and len(argv) == 3:
            resultado = trocar(argv[1], argv[2])
        elif acao == "voltar" and len(argv) == 2:
            resultado = voltar(argv[1])
        elif acao == "manter" and len(argv) == 2:
            resultado = manter(argv[1])
        elif acao == "usado-por" and len(argv) == 2:
            resultado = usado_por(argv[1])
        else:
            print(main.__doc__, file=sys.stderr)
            return 1
    except (ValueError, RuntimeError) as erro:
        print(str(erro), file=sys.stderr)
        return 2
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
