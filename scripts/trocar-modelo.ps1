<#
  Trocar modelo: atualiza o modelo de um papel do cofre (quem faz o que: catalogo\papeis.json) com seguranca.

  As ferramentas (Central, perguntar, conselho, chat sugerido, busca, transcricao) pedem o modelo pelo papel,
  nunca pelo nome. Trocar o modelo de um papel e o jeito de atualizar: tudo passa a usar o novo, sem mexer em
  codigo, e o anterior fica guardado para voltar.

  Os passos da troca
    1. Confere se o modelo novo esta no catalogo e serve para o papel (tipo e motor certos), e mostra se ele
       cabe na placa de video, se vai usar a RAM tambem (mais lento) ou se e grande demais para este PC.
    2. Baixa, se faltar (baixar-modelo.ps1: confere o SHA-256 de cada arquivo).
    3. Testa: liga o modelo numa porta de teste, faz uma pergunta curta e mede a velocidade. Se ele nao
       responder, nada e trocado. (Modelos fora do llama.cpp, como o Whisper, pulam o teste.)
    4. Troca o papel e guarda o anterior: -Voltar desfaz, e nada foi apagado.
  Gostou do novo? -Manter tira o anterior da volta. Se nenhum outro papel usar o anterior, os arquivos dele vao
  para _para-apagar (apague voce com Shift+Delete) e ele nao volta sozinho na sincronizacao.

  Uso
    .\trocar-modelo.ps1                                    # os papeis e o modelo de cada um
    .\trocar-modelo.ps1 -Papel rapida -Candidatos          # os modelos do catalogo que servem para o papel
    .\trocar-modelo.ps1 -Papel rapida -Para gemma-5-12b    # baixa, confere, testa e troca
    .\trocar-modelo.ps1 -Papel rapida -Voltar              # volta ao anterior
    .\trocar-modelo.ps1 -Papel rapida -Manter              # fica com o novo e guarda o anterior para apagar
    -SemTeste   troca sem o teste do passo 3      -Sim   nao pergunta antes
  Modelo que ainda nao esta no catalogo: acrescente em catalogo\modelos.json (repo e arquivos) e troque.
#>
param(
    [string]$Papel,
    [string]$Para,
    [switch]$Voltar,
    [switch]$Manter,
    [switch]$Candidatos,
    [switch]$SemTeste,
    [switch]$Sim
)
. "$PSScriptRoot\comum.ps1"

$ArquivoAndamento = Join-Path $PastaLogs 'troca-de-modelo.json'   # a Central mostra o andamento na ilha
$PortaTeste = 8099

# ---------- Utilidades ----------
function Papeis-Py([string[]]$argumentos) {
    $uv = Preparar-Uv
    $script = Join-Path $Raiz 'dev\ferramentas\papeis.py'
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $linhas = @(& $uv run --offline --quiet --script $script @argumentos 2>&1) } finally { $ErrorActionPreference = $eap }
    $codigo = $LASTEXITCODE
    $erros = @($linhas | Where-Object { $_ -is [Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() })
    $saida = @($linhas | Where-Object { $_ -isnot [Management.Automation.ErrorRecord] } | ForEach-Object { [string]$_ })
    if ($codigo -ne 0) { throw ((($erros + $saida) -join ' ').Trim()) }
    return (($saida -join "`n") | ConvertFrom-Json)
}

function Andamento([string]$etapa, [string]$texto, [int]$passo = 0, [string]$fim = '') {
    try {
        New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
        Salvar-Json ([ordered]@{
            papel = $Papel; para = $Para; etapa = $etapa; texto = $texto; passo = $passo; passos = 4; fim = $fim
            pid = $PID; quando = (Get-Date).ToString('s')
        }) $ArquivoAndamento
    } catch {}
}

function Memorias {
    $vram = 0.0
    try { $vram = [double]((& nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1).Trim()) / 1024 } catch {}
    $ram = [double](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB
    return [pscustomobject]@{ vram = $vram; ram = $ram }
}
$script:Mem = $null
function Onde-Cabe([double]$gb, [string]$motor = 'llama.cpp') {
    if ($motor -notin 'llama.cpp', 'comfyui') { return 'roda no processador ou no proprio programa' }
    if (-not $script:Mem) { $script:Mem = Memorias }
    if ($gb -le 0) { return '' }
    if ($script:Mem.vram -gt 0 -and $gb -le $script:Mem.vram - 1.5) { return 'cabe na placa' }
    if ($gb -le $script:Mem.vram + $script:Mem.ram - 8) { return 'usa a placa e a RAM, mais lento' }
    return 'grande demais para este PC'
}
function Texto-GB($gb) { if ($gb) { return [string]::Format($CulturaBR, '{0:N1} GB', [double]$gb) } return '?' }

function Serve($p, $m) {
    $tipos = @($p.tipos)
    return ((-not $tipos.Count) -or $tipos -contains $m.tipo) -and ((-not $p.motor) -or $m.motor -eq $p.motor)
}

# ---------- Teste do modelo novo, numa porta so dele ----------
function Testar-Modelo($m, [string]$papel) {
    $exe = Achar-Exe 'llama.cpp' 'llama-server.exe'
    $arqs = @($m.arquivos | ForEach-Object { Caminho-Destino $m $_ })
    $gguf = $arqs | Where-Object { (Split-Path $_ -Leaf) -notmatch '^(mmproj|mtp-)' -and $_ -match '\.gguf$' } | Select-Object -First 1
    if (-not $gguf -or -not (Test-Path -LiteralPath $gguf)) { return [pscustomobject]@{ ok = $false; motivo = 'arquivo do modelo nao encontrado' } }
    $argumentos = @('-m', "`"$gguf`"", '--host', '127.0.0.1', '--port', "$PortaTeste", '-c', '4096', '--fit', 'on', '--reasoning-budget', '0')
    $argumentos += @(([string]$m.args) -split '\s+' | Where-Object { $_ })
    New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
    $log = Join-Path $PastaLogs 'teste-modelo.log'
    $proc = Start-Process -FilePath $exe -ArgumentList $argumentos -WindowStyle Hidden -PassThru -RedirectStandardError $log
    $relogio = [Diagnostics.Stopwatch]::StartNew()
    $base = "http://127.0.0.1:$PortaTeste"
    try {
        $pronto = $false
        while ($relogio.Elapsed.TotalSeconds -lt 240 -and -not $proc.HasExited) {
            try { if ((Invoke-WebRequest -UseBasicParsing "$base/health" -TimeoutSec 3).StatusCode -eq 200) { $pronto = $true; break } } catch {}
            Start-Sleep -Milliseconds 800
        }
        if (-not $pronto) { return [pscustomobject]@{ ok = $false; motivo = 'o modelo nao carregou (veja logs\teste-modelo.log)' } }
        $carregou = $relogio.Elapsed.TotalSeconds
        $t0 = [Diagnostics.Stopwatch]::StartNew()
        $cab = @{ 'Content-Type' = 'application/json; charset=utf-8' }
        if ($papel -eq 'busca') {
            $r = Invoke-RestMethod -Method Post -Uri "$base/v1/embeddings" -Headers $cab -TimeoutSec 120 -Body ([Text.Encoding]::UTF8.GetBytes('{"input": ["como purificar agua da chuva"]}'))
            $ok = @($r.data[0].embedding).Count -gt 0
            $resposta = "vetor de $(@($r.data[0].embedding).Count) numeros"
            $tps = 0
        } elseif ($papel -eq 'reordenar') {
            $corpo = '{"query": "como purificar agua", "documents": ["Ferver a agua por um minuto mata os germes.", "Troque o oleo do carro a cada 10 mil km."], "top_n": 2}'
            $r = Invoke-RestMethod -Method Post -Uri "$base/v1/rerank" -Headers $cab -TimeoutSec 120 -Body ([Text.Encoding]::UTF8.GetBytes($corpo))
            $primeiro = @($r.results)[0]
            $ok = $null -ne $primeiro -and [int]$primeiro.index -eq 0
            $resposta = if ($ok) { 'pos o trecho certo em primeiro' } else { 'ordem errada' }
            $tps = 0
        } else {
            $corpo = '{"messages": [{"role": "user", "content": "Em uma frase curta, em portugues: por que ferver a agua antes de beber?"}], "max_tokens": 200, "temperature": 0.2}'
            $r = Invoke-RestMethod -Method Post -Uri "$base/v1/chat/completions" -Headers $cab -TimeoutSec 240 -Body ([Text.Encoding]::UTF8.GetBytes($corpo))
            $msg = $r.choices[0].message
            $resposta = ([string]$msg.content).Trim()
            if (-not $resposta) { $resposta = ([string]$msg.reasoning_content).Trim() }
            $ok = [bool]$resposta
            $tps = if ($t0.Elapsed.TotalSeconds -gt 0 -and $r.usage.completion_tokens) { [double]$r.usage.completion_tokens / $t0.Elapsed.TotalSeconds } else { 0 }
        }
        return [pscustomobject]@{ ok = $ok; motivo = $(if ($ok) { '' } else { 'resposta vazia ou errada' }); carregou = $carregou; segundos = $t0.Elapsed.TotalSeconds; tps = $tps; resposta = $resposta }
    } catch {
        return [pscustomobject]@{ ok = $false; motivo = "erro no teste: $($_.Exception.Message)" }
    } finally {
        if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue }
        Registrar-Gasto 'trocar-modelo' $relogio.Elapsed.TotalSeconds 170
    }
}

# ---------- Aposentar: arquivos para _para-apagar, sem apagar nada ----------
function Aposentar([string]$id) {
    $cat = Ler-Catalogo
    $m = @($cat.modelos | Where-Object { $_.id -eq $id }) | Select-Object -First 1
    if (-not $m) { Aviso "$id nao esta mais no catalogo: os arquivos ficaram onde estavam."; return }
    $estado = Ler-Estado
    $loc = if ($estado.modelos.Contains($id) -and $estado.modelos[$id].local) { $estado.modelos[$id].local } elseif ($m.local) { $m.local } else { 'nucleo' }
    $base = Base-Local $loc
    [int64]$movido = 0
    foreach ($a in @($m.arquivos)) {
        $origem = Caminho-Destino $m $a
        if (-not (Test-Path -LiteralPath $origem)) { continue }
        $rel = $origem.Substring((Join-Path $base 'modelos').Length).TrimStart('\')
        $alvo = Join-Path (Join-Path $base '_para-apagar\modelos') $rel
        New-Item -ItemType Directory -Force -Path (Split-Path $alvo -Parent) | Out-Null
        if (Test-Path -LiteralPath $alvo) { $alvo = "$alvo.$(Get-Date -Format 'yyyyMMdd-HHmmss')" }
        $movido += (Get-Item -LiteralPath $origem).Length
        Move-Item -LiteralPath $origem -Destination $alvo
    }
    Atualizar-Estado {
        param($e)
        if ($e.modelos.Contains($id)) { $e.modelos[$id].completo = $false }
        $e['aposentados'] = @(@($e.aposentados) + $id | Where-Object { $_ } | Select-Object -Unique)
    } | Out-Null
    Ok ([string]::Format($CulturaBR, '{0}: {1:N1} GB foram para {2}. Apague com Shift+Delete quando quiser; ele nao volta na sincronizacao.', $id, $movido / 1GB, (Join-Path $base '_para-apagar')))
}

# ---------- Principal ----------
try {
    $papeis = @(Papeis-Py @('json'))
} catch {
    Aviso "Nao deu para ler os papeis: $($_.Exception.Message)"
    exit 1
}

if (-not $Papel) {
    Titulo 'Papeis: quem faz o que no cofre'
    foreach ($g in @($papeis | Select-Object -ExpandProperty grupo -Unique)) {
        Write-Host "    $g" -ForegroundColor Cyan
        foreach ($p in @($papeis | Where-Object { $_.grupo -eq $g })) {
            $volta = if ($p.anterior) { "  [volta: $($p.anterior.id)]" } else { '' }
            $cabe = Onde-Cabe ([double]$p.modelo.tamanho_gb) $p.motor
            Info ("  {0,-24} {1,-26} {2,8}  {3}{4}" -f $p.nome, $p.modelo.id, (Texto-GB $p.modelo.tamanho_gb), $cabe, $volta)
        }
    }
    Info ''
    Info 'Para ver o que serve num papel:  .\trocar-modelo.ps1 -Papel rapida -Candidatos'
    Info 'Para trocar:                     .\trocar-modelo.ps1 -Papel rapida -Para <modelo>'
    exit 0
}

$p = @($papeis | Where-Object { $_.id -eq $Papel }) | Select-Object -First 1
if (-not $p) { Aviso "Papel desconhecido: $Papel. Os papeis: $(($papeis | ForEach-Object { $_.id }) -join ', ')."; exit 1 }

if ($Candidatos) {
    Titulo "$($p.nome): o que serve"
    Info "Agora: $($p.modelo.id) ($(Texto-GB $p.modelo.tamanho_gb), $(Onde-Cabe ([double]$p.modelo.tamanho_gb)))"
    foreach ($c in @($p.candidatos)) {
        $b = if ($c.baixado) { 'baixado' } else { "baixar $(Texto-GB $c.tamanho_gb)" }
        Info ("  {0,-30} {1,8}  {2,-14} {3}" -f $c.id, (Texto-GB $c.tamanho_gb), $b, (Onde-Cabe ([double]$c.tamanho_gb)))
    }
    exit 0
}

if ($Voltar) {
    try {
        $r = Papeis-Py @('voltar', $Papel)
        Andamento 'pronto' "$($p.nome) voltou para $($r.modelo)" 4 'ok'
        Ok "$($p.nome) voltou para $($r.modelo). O que estava ($($r.anterior)) ficou guardado para voltar."
        exit 0
    } catch { Aviso $_.Exception.Message; exit 1 }
}

if ($Manter) {
    try { $r = Papeis-Py @('manter', $Papel) } catch { Aviso $_.Exception.Message; exit 1 }
    if (-not $r.antigo) { Info "$($p.nome): nao havia modelo anterior guardado."; exit 0 }
    if (-not $r.sem_uso) { Ok "$($p.nome) fica com o $($r.papel.modelo). O anterior ($($r.antigo)) continua em uso por outro papel e fica onde esta."; exit 0 }
    Ok "$($p.nome) fica com o $($r.papel.modelo)."
    Aposentar $r.antigo
    exit 0
}

if (-not $Para) { Aviso 'Diga para qual modelo: -Para <id> (veja os que servem com -Candidatos).'; exit 1 }
if ($p.troca -eq 'manual') { Aviso "$($p.nome): a troca e manual (a ferramenta precisa de ajuste). Veja o guia, secao Modelos."; exit 1 }
$cat = Ler-Catalogo
$m = @($cat.modelos | Where-Object { $_.id -eq $Para }) | Select-Object -First 1
if (-not $m) { Aviso "$Para nao esta no catalogo. Acrescente em catalogo\modelos.json (repo e arquivos) e rode de novo."; exit 1 }
if (-not (Serve $p $m)) { Aviso "$($m.nome) nao serve para $($p.nome): e do tipo $($m.tipo) ($($m.motor)), e o papel pede $(@($p.tipos) -join ', ') ($($p.motor))."; exit 1 }
if ($p.modelo.id -eq $Para) { Ok "$Para ja e o modelo de $($p.nome)."; exit 0 }

$estado = Ler-Estado
$baixado = $estado.modelos.Contains($Para) -and $estado.modelos[$Para].completo -and -not (@($estado.aposentados) -contains $Para)
$testavel = (-not $SemTeste) -and $m.motor -eq 'llama.cpp'
$cabe = Onde-Cabe ([double]$m.tamanho_gb)
Titulo "Trocar $($p.nome)"
Info "De:   $($p.modelo.id) ($(Texto-GB $p.modelo.tamanho_gb))"
Info "Para: $($m.id) - $($m.nome) ($(Texto-GB $m.tamanho_gb), $cabe)"
if ($cabe -eq 'grande demais para este PC') { Aviso 'Grande demais: ele leria do disco a cada palavra e travaria o PC. Melhor escolher outro.' }
if ($p.id -eq 'rapida' -and $cabe -ne 'cabe na placa') { Aviso 'A resposta rapida so e rapida com o modelo inteiro na placa de video.' }
$segBaixar = if ($baixado) { 0 } else { [double]$m.tamanho_gb * 1e9 / 13e6 }   # ~13 MB/s (medido nos espelhos)
$whBaixar = (Energia-Catalogo).pc_parado_w * $segBaixar / 3600
$whTeste = if ($testavel) { 170 * 75 / 3600 } else { 0 }
Info "Passos: $(if ($baixado) { 'ja baixado' } else { "baixar $(Texto-GB $m.tamanho_gb) (~$([math]::Max(1, [math]::Round($segBaixar / 60))) min)" }), $(if ($testavel) { 'testar (~1 min)' } else { 'sem teste' }), trocar."
Mostrar-Estimativa 'trocar-modelo' (Texto-Custo ($whBaixar + $whTeste))
if ($testavel -and (ModoJogo-Ativo)) {
    Aviso 'Modo jogo ligado: o teste usa a placa de video. Saia do modo jogo (menu, opcao 12) ou troque sem testar: -SemTeste.'
    exit 3
}
if (-not $Sim) {
    $r = Read-Host '  Trocar agora? (s/n)'
    if ($r -notmatch '^\s*[sS]') { Info 'Nada foi trocado.'; exit 0 }
}

$inicio = Get-Date
try {
    if (-not $baixado) {
        Andamento 'baixar' "Baixando $($m.nome)" 1
        & "$PSScriptRoot\baixar-modelo.ps1" -Id $Para
        $estado = Ler-Estado
        if (-not ($estado.modelos.Contains($Para) -and $estado.modelos[$Para].completo)) { throw 'o download nao terminou (rode de novo: ele continua de onde parou)' }
    }
    if ($testavel) {
        Andamento 'testar' "Testando $($m.nome)" 2
        Titulo 'Testando o modelo novo'
        $t = Testar-Modelo $m $p.id
        if (-not $t.ok) { throw "o modelo novo falhou no teste: $($t.motivo). Nada foi trocado." }
        $vel = if ($t.tps -gt 0) { [string]::Format($CulturaBR, ', ~{0:N0} tokens/s', $t.tps) } else { '' }
        Ok ([string]::Format($CulturaBR, 'carregou em {0:N0} s e respondeu em {1:N1} s{2}', $t.carregou, $t.segundos, $vel))
        $amostra = ($t.resposta -replace '\s+', ' ')
        if ($amostra.Length -gt 160) { $amostra = $amostra.Substring(0, 157) + '...' }
        Info "Resposta: $amostra"
    }
    Andamento 'trocar' "Trocando $($p.nome)" 3
    $r = Papeis-Py @('trocar', $Papel, $Para)
    Andamento 'pronto' "$($p.nome) agora usa $($m.nome)" 4 'ok'
    Titulo 'Pronto'
    Ok "$($p.nome) agora usa $($m.id). O anterior ($($r.anterior)) ficou guardado."
    Info "Voltar:        .\trocar-modelo.ps1 -Papel $Papel -Voltar"
    Info "Gostou? Manter: .\trocar-modelo.ps1 -Papel $Papel -Manter   (o anterior vai para _para-apagar)"
    $ini = Join-Path $PastaCatalogo 'llama-presets.ini'
    if ($m.motor -eq 'llama.cpp' -and -not ((Test-Path -LiteralPath $ini) -and (Select-String -LiteralPath $ini -SimpleMatch "[$Para]" -Quiet))) {
        Info 'O servidor de modelos conhece o modelo novo na proxima vez que ligar: se ele estiver aberto, feche (menu 11) e ligue de novo.'
    }
    Mostrar-GastoFinal 'trocar-modelo' $inicio
} catch {
    Andamento 'falhou' $_.Exception.Message 0 'erro'
    Aviso $_.Exception.Message
    exit 2
}
