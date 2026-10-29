<#
.SYNOPSIS
  Confere novidades e gera um relatorio em catalogo\relatorios\AAAA-MM-DD.md:
    1. versoes novas dos arquivos dos modelos que voce baixou;
    2. mudancas nos modelos de fronteira que o catalogo observa;
    3. modelos novos publicados pelos laboratorios da lista observar_orgs;
    4. versoes novas dos motores (llama.cpp, Ollama, ComfyUI, whisper.cpp).
  Nao baixa nada: so avisa. Para baixar, use baixar-modelo.ps1 / instalar-motores.ps1.
.EXAMPLE
  .\verificar-atualizacoes.ps1
  .\verificar-atualizacoes.ps1 -Dias 60     # na primeira vez, lista o que saiu nos ultimos 60 dias
#>
param([int]$Dias = 30, [switch]$SemDescoberta, [switch]$Agendado)
. "$PSScriptRoot\comum.ps1"
if ($Agendado) {
    # Rodando pela tarefa semanal: guarda a saida em logs\ para consulta.
    New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
    Start-Transcript -Path (Join-Path $PastaLogs ("verificacao-{0}.txt" -f (Get-Date -Format 'yyyy-MM-dd'))) -Force | Out-Null
}

$cat = Ler-Catalogo
$estado = Ler-Estado
$hoje = Get-Date -Format 'yyyy-MM-dd'
$md = New-Object System.Collections.Generic.List[string]
$md.Add("# Atualizacoes - $hoje")
$pendencias = 0
$novidades = 0

# Estima o tamanho em Q4 pelo nome ("27B", "35B-A3B", "2.4T"): cerca de 0,6 GB por bilhao de parametros.
function Estimar-Q4GB($nome) {
    if ($nome -match '(?i)(\d+(?:\.\d+)?)([BT])(?![a-z])') {
        $n = [double]$Matches[1]
        if ($Matches[2] -match '(?i)t') { $n *= 1000 }
        return [math]::Round($n * 0.6, 1)
    }
    return $null
}

# 1. Modelos baixados
Titulo 'Modelos baixados'
$md.Add(''); $md.Add('## Modelos baixados'); $md.Add('')
$baixados = @($cat.modelos | Where-Object { $_.status -eq 'baixar' -and $estado.modelos.Contains($_.id) })
if ($baixados.Count -eq 0) { Info 'Nenhum modelo baixado ainda.'; $md.Add('Nenhum modelo baixado ainda.') }
foreach ($m in $baixados) {
    $reg = $estado.modelos[$m.id]
    foreach ($a in $m.arquivos) {
        $nome = Split-Path $a.caminho -Leaf
        try { $info = Obter-InfoArquivo $m.repo $a.caminho }
        catch {
            Aviso "$($m.id): $nome sumiu do repositorio"
            $md.Add("- **$($m.id)**: $nome nao existe mais em $($m.repo); ajuste o catalogo")
            $pendencias++
            continue
        }
        $loc = $reg.arquivos[$a.caminho]
        if (-not $loc) {
            Aviso "$($m.id): $nome ainda nao baixado"
            $md.Add("- $($m.id): $nome ainda nao baixado")
            $pendencias++
        } elseif ($info.sha256 -and $loc.sha256 -ne $info.sha256) {
            Aviso "$($m.id): $nome tem versao nova"
            $md.Add(("- **$($m.id)**: $nome tem versao nova ({0:N2} GB). Rode ``.\baixar-modelo.ps1 -Id $($m.id)``" -f ($info.tamanho / 1GB)))
            $pendencias++
        } else {
            Ok "$($m.id): $nome em dia"
        }
    }
}

# 1b. Bibliotecas offline (Kiwix): saiu edicao mais nova?
Titulo 'Bibliotecas offline'
$md.Add(''); $md.Add('## Bibliotecas offline (Kiwix)'); $md.Add('')
foreach ($item in @($cat.conhecimento)) {
    if (-not $estado.conhecimento.Contains($item.id)) { continue }
    $reg = $estado.conhecimento[$item.id]
    try { $ultima = Versao-Zim $item } catch { Aviso "$($item.id): falha ao consultar a Kiwix"; continue }
    if ($ultima -and $ultima.versao -gt $reg.versao) {
        Aviso "$($item.id): edicao $($ultima.versao) disponivel (voce tem $($reg.versao))"
        $md.Add("- **$($item.nome)**: edicao $($ultima.versao) disponivel (voce tem $($reg.versao)). Rode ``.\baixar-conhecimento.ps1 -Id $($item.id)``")
        $pendencias++
    } else {
        Ok "$($item.id) $($reg.versao) em dia"
    }
}
# Bibliotecas que entraram no catalogo e ainda nao vieram (as "em observacao" so baixam com -Id).
$faltam = @($cat.conhecimento | Where-Object { $_.status -ne 'observar' -and -not $estado.conhecimento.Contains($_.id) })
if ($faltam.Count -gt 0) {
    $gb = [math]::Round(($faltam | Measure-Object tamanho_gb -Sum).Sum, 1)
    Aviso "$($faltam.Count) biblioteca(s) do catalogo ainda nao baixada(s), cerca de $gb GB"
    $md.Add("- **$($faltam.Count) biblioteca(s) do catalogo ainda nao baixada(s)** (cerca de $gb GB): $(($faltam | ForEach-Object id) -join ', '). Rode a sincronizacao (menu, opcao 8).")
    $pendencias++
}

# 2. Modelos de fronteira observados
Titulo 'Modelos observados'
$md.Add(''); $md.Add('## Modelos observados (fronteira)'); $md.Add('')
foreach ($m in @($cat.modelos | Where-Object { $_.status -eq 'observar' })) {
    try { $r = Obter-InfoRepo $m.repo } catch { Aviso "$($m.id): repositorio nao encontrado"; continue }
    $mod = [string]$r.lastModified
    $dia = $mod.Substring(0, [math]::Min(10, $mod.Length))
    $antes = $estado.observados[$m.id]
    if ($antes -and $antes -ne $mod) {
        Aviso "$($m.id) mudou em $dia"
        $md.Add("- **$($m.nome)** foi atualizado em $dia")
        $pendencias++
    } else {
        Info "$($m.id): ultima mudanca em $dia"
        $md.Add("- $($m.nome): ultima mudanca em $dia ($($m.motivo))")
    }
    $estado.observados[$m.id] = $mod
}

# 3. Modelos novos dos laboratorios
if (-not $SemDescoberta) {
    Titulo 'Novidades dos laboratorios'
    $md.Add(''); $md.Add('## Modelos novos publicados'); $md.Add('')
    $md.Add('| Modelo | Publicado | Q4 estimado | Cabe no PC? |')
    $md.Add('| --- | --- | --- | --- |')
    # Ignora variantes que so mudam o formato (FP8, MLX...) ou versoes sem filtro de seguranca.
    $ruido = '(?i)(FP8|NVFP4|MXFP8|FP4|eagle|dflash|-mlx|GPTQ|AWQ|-ct$|w4a16|-hf$|BF16|-Base$|abliterated|uncensored|heretic|for-testing)'
    # So tipos que interessam ao acervo; de quem so republica (unsloth, ggml-org), so os GGUF.
    $tiposUteis = 'text-generation', 'image-text-to-text', 'any-to-any', 'text-to-image', 'image-to-image',
                  'automatic-speech-recognition', 'text-to-speech', 'feature-extraction', 'sentence-similarity',
                  'text-to-video', 'image-to-video', 'visual-question-answering'
    $republicadores = 'unsloth', 'ggml-org', 'bartowski', 'lmstudio-community'
    foreach ($org in $cat.observar_orgs) {
        try { $lista = Invoke-Api "https://huggingface.co/api/models?author=$org&sort=createdAt&direction=-1&limit=40" }
        catch { Aviso "${org}: falha na consulta"; continue }
        $lista = @($lista | ForEach-Object { $_ })
        if ($lista.Count -eq 0) { continue }
        $visto = $estado.orgs_visto[$org]
        if ($visto) { $limite = [datetime]$visto } else { $limite = (Get-Date).AddDays(-$Dias) }
        $ehRepub = $republicadores -contains $org
        $novos = @($lista | Where-Object {
            $gguf = (@($_.tags) -contains 'gguf') -or $_.id -match '(?i)gguf'
            [datetime]$_.createdAt -gt $limite -and $_.id -notmatch $ruido -and
            ($tiposUteis -contains $_.pipeline_tag -or $gguf) -and (-not $ehRepub -or $gguf)
        })
        foreach ($n in $novos) {
            $gb = Estimar-Q4GB ($n.id -replace '^[^/]+/', '')
            $txtGb = '?'
            $cabe = 'conferir'
            if ($null -ne $gb) {
                $txtGb = "$gb GB"
                if ($gb -le 10) { $cabe = 'sim, inteiro na GPU' } elseif ($gb -le 45) { $cabe = 'sim, GPU + RAM' } else { $cabe = 'nao' }
            }
            $dia = ([string]$n.createdAt).Substring(0, 10)
            Info ("{0,-60} {1}  {2}" -f $n.id, $dia, $cabe)
            $md.Add("| [$($n.id)](https://huggingface.co/$($n.id)) | $dia | $txtGb | $cabe |")
            $novidades++
        }
        $estado.orgs_visto[$org] = [string]$lista[0].createdAt
    }
    if ($novidades -eq 0) { Info 'Nada novo desde a ultima verificacao.' }
}

# 4. Motores
Titulo 'Motores'
$md.Add(''); $md.Add('## Motores'); $md.Add('')
foreach ($def in $cat.motores) {
    $pad = Padroes-Motor $def
    try { $rel = Obter-ReleaseComAsset $def.github $pad.principal }
    catch { Aviso "$($def.id): falha ao consultar o GitHub"; continue }
    if (-not $rel) { Aviso "$($def.id): nenhuma versao para Windows encontrada"; continue }
    $inst = $null
    if ($estado.motores.Contains($def.id)) { $inst = $estado.motores[$def.id].versao }
    if (-not $inst) {
        Info "$($def.id): nao instalado (ultima versao: $($rel.tag_name))"
        $md.Add("- $($def.id): nao instalado; ultima versao $($rel.tag_name)")
    } elseif ($inst -ne $rel.tag_name) {
        Aviso "$($def.id): $inst instalado, $($rel.tag_name) disponivel"
        $md.Add("- **$($def.id)**: versao nova $($rel.tag_name) (instalada: $inst). Rode ``.\instalar-motores.ps1 -Motor $($def.id)``")
        $pendencias++
    } else {
        Ok "$($def.id) $inst em dia"
        $md.Add("- $($def.id) $inst em dia")
    }
}

$estado.ultima_verificacao = (Get-Date -Format s)
Salvar-Estado $estado
$arqRel = Join-Path $PastaCatalogo "relatorios\$hoje.md"
[IO.File]::WriteAllLines($arqRel, $md, (New-Object Text.UTF8Encoding $false))

Titulo 'Pronto'
Info "Relatorio: $(Caminho-Relativo $arqRel)"
Info "$pendencias item(ns) pedem acao; $novidades modelo(s) novo(s) publicados."
if ($Agendado) {
    if ($pendencias -gt 0 -or $novidades -gt 0) {
        Notificar 'SSD de IAs' "$pendencias atualizacao(oes) e $novidades modelo(s) novo(s). Veja catalogo\relatorios\$hoje.md"
    }
    Stop-Transcript | Out-Null
}
