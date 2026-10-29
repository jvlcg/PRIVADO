<#
.SYNOPSIS
  Confere o projeto em poucos segundos, sem rodar nenhum modelo:
    1. segredos (chave de acesso, tokens) nos arquivos que vao para o GitHub
    2. sintaxe dos scripts e acentos (o PowerShell 5.1 le errado acento em script sem BOM; com BOM pode)
    3. ferramentas Python (compilam? passam nos testes de dev\ferramentas\testes.py?)
    4. catalogo e estado (JSON valido, ids repetidos, time do conselho)
    5. arquivos dos modelos e bibliotecas marcados como baixados (existem, com o tamanho certo)
    6. scripts citados no menu e no guia existem
  Termina com codigo 1 se achar problema.
.EXAMPLE
  .\testar-cofre.ps1
  .\testar-cofre.ps1 -SoSegredos     # so a busca por segredos (a sincronizacao usa antes de enviar)
#>
param([switch]$SoSegredos)
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'
$problemas = New-Object System.Collections.Generic.List[string]
function Problema($texto) { $problemas.Add($texto); Aviso $texto }

# Arquivos que o git guarda ou guardaria no proximo "git add -A" (o .gitignore ja tira os grandes e pessoais).
Push-Location $Raiz
try { $doGit = @(git ls-files 2>$null) + @(git ls-files --others --exclude-standard 2>$null) | Sort-Object -Unique }
finally { Pop-Location }
$textos = @($doGit | Where-Object { $_ -match '\.(ps1|py|md|json|txt|ya?ml|cmd|sh|html|ini|csv)$' -or $_ -match '(^|/)\.git(ignore|attributes)$' } |
    ForEach-Object { Join-Path $Raiz ($_ -replace '/', '\') } | Where-Object { Test-Path -LiteralPath $_ })

Titulo '1. Segredos nos arquivos que vao para o GitHub'
$padroes = [ordered]@{
    'token do Hugging Face' = 'hf_[A-Za-z0-9]{30,}'
    'token do GitHub'       = '(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'
    'chave de API (sk-)'    = '\bsk-[A-Za-z0-9_-]{20,}'
    'chave da AWS'          = '\bAKIA[0-9A-Z]{16}\b'
    'chave privada'         = '-----BEGIN [A-Z ]*PRIVATE KEY-----'
}
$achados = 0
foreach ($nome in $padroes.Keys) {
    foreach ($a in @(Select-String -LiteralPath $textos -Pattern $padroes[$nome] -ErrorAction SilentlyContinue)) {
        Problema "$nome em $(Caminho-Relativo $a.Path), linha $($a.LineNumber)"; $achados++
    }
}
if (Test-Path -LiteralPath $ArquivoChave) {
    $chave = (Get-Content -LiteralPath $ArquivoChave -TotalCount 1).Trim()
    foreach ($a in @(Select-String -LiteralPath $textos -Pattern $chave -SimpleMatch -ErrorAction SilentlyContinue)) {
        Problema "a chave de acesso deste PC esta em $(Caminho-Relativo $a.Path), linha $($a.LineNumber)"; $achados++
    }
    Push-Location $Raiz
    try { git check-ignore -q 'catalogo/chave-api.txt' 2>$null; $ignorada = ($LASTEXITCODE -eq 0) } finally { Pop-Location }
    if (-not $ignorada) { Problema 'catalogo\chave-api.txt nao esta no .gitignore' ; $achados++ }
}
if ($achados -eq 0) { Ok "nenhum segredo em $($textos.Count) arquivos" }
if ($SoSegredos) { exit [int]($problemas.Count -gt 0) }

Titulo '2. Scripts do PowerShell'
$scripts = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.ps1' -File)
foreach ($s in $scripts) {
    $erros = $null
    [void][Management.Automation.Language.Parser]::ParseFile($s.FullName, [ref]$null, [ref]$erros)
    foreach ($e in @($erros)) { Problema "$($s.Name), linha $($e.Extent.StartLineNumber): $($e.Message)" }
    # Acento so funciona no PowerShell 5.1 com o arquivo em UTF-8 com BOM (como o menu.ps1).
    $inicio = [IO.File]::ReadAllBytes($s.FullName) | Select-Object -First 3
    $temBom = $inicio.Count -eq 3 -and $inicio[0] -eq 0xEF -and $inicio[1] -eq 0xBB -and $inicio[2] -eq 0xBF
    $linhas = [IO.File]::ReadAllLines($s.FullName)
    for ($i = 0; $i -lt $linhas.Count -and -not $temBom; $i++) {
        if ($linhas[$i] -match '[^\x00-\x7F]') { Problema "$($s.Name), linha $($i + 1): acento ou simbolo fora do ASCII sem BOM (o PowerShell 5.1 le errado; grave em UTF-8 com BOM)"; break }
    }
}
Ok "$($scripts.Count) scripts lidos"

Titulo '3. Ferramentas Python'
$pys = @($doGit | Where-Object { $_ -match '\.py$' } | ForEach-Object { Join-Path $Raiz ($_ -replace '/', '\') } | Where-Object { Test-Path -LiteralPath $_ })
if ($pys.Count -gt 0) {
    try {
        $uv = Preparar-Uv
        $saida = & $uv run --offline --no-project python -m py_compile @pys 2>&1
        if ($LASTEXITCODE -eq 0) { Ok "$($pys.Count) arquivos compilam" } else { Problema "Python com erro: $(($saida | Out-String).Trim())" }
        $testes = Join-Path $Raiz 'dev\ferramentas\testes.py'
        if (Test-Path -LiteralPath $testes) {
            $env:PYTHONIOENCODING = 'utf-8'
            $saida = & $uv run --offline --no-project python $testes 2>&1 | Out-String
            $total = [regex]::Match($saida, 'Ran (\d+) test').Groups[1].Value
            if ($LASTEXITCODE -eq 0) { Ok "$total testes das ferramentas passaram" } else { Problema "testes das ferramentas falharam:`n$($saida.Trim())" }
        }
    } catch { Aviso "Nao consegui rodar o Python do SSD: $($_.Exception.Message)" }
}

Titulo '4. Catalogo e estado'
$cat = $null; $estado = $null
try { $cat = Ler-Catalogo; Ok 'modelos.json e JSON valido' } catch { Problema "modelos.json invalido: $($_.Exception.Message)" }
try { $estado = Ler-Estado; Ok 'estado.json e JSON valido' } catch { Problema "estado.json invalido: $($_.Exception.Message)" }
if ($cat) {
    foreach ($secao in 'modelos', 'conhecimento', 'motores') {
        foreach ($g in @($cat.$secao | Group-Object id | Where-Object Count -gt 1)) { Problema "id repetido em $secao`: $($g.Name)" }
    }
    $prontos = @($cat.modelos | Where-Object { $_.status -eq 'baixar' })
    foreach ($m in $prontos) {
        foreach ($campo in 'nome', 'tipo', 'motor', 'local', 'pasta', 'arquivos', 'tamanho_gb') {
            if (-not $m.$campo) { Problema "modelo $($m.id) sem o campo '$campo'" }
        }
        if ($m.local -and $m.local -notin 'nucleo', 'cofre') { Problema "modelo $($m.id): local '$($m.local)' (use nucleo ou cofre)" }
    }
    if ($cat.conselho) {
        $ids = @($prontos | ForEach-Object id)
        $time = @($cat.conselho.membros) + @($cat.conselho.relator, $cat.conselho.relator_profundo, $cat.conselho.triagem)
        if ($cat.conselho.especialistas) { $time += @($cat.conselho.especialistas.PSObject.Properties | ForEach-Object Value) }
        foreach ($t in @($time | Where-Object { $_ } | Sort-Object -Unique)) { if ($ids -notcontains $t) { Problema "conselho usa '$t', que nao esta no catalogo para baixar" } }
    }
    Ok "$(@($cat.modelos).Count) modelos, $(@($cat.conhecimento).Count) bibliotecas e $(@($cat.motores).Count) motores no catalogo"
}

Titulo '5. Arquivos marcados como baixados'
if ($cat -and $estado) {
    $temCofre = $false
    try { $rc = Raiz-Cofre; $temCofre = $rc -and (Test-Path -LiteralPath $rc) } catch {}
    $conferidos = 0; $pulados = 0
    $itens = @()
    foreach ($id in @($estado.modelos.Keys)) {
        $reg = $estado.modelos[$id]
        if (-not $reg.completo) { continue }
        $local = if ($reg.local) { $reg.local } else { 'nucleo' }
        foreach ($nome in @($reg.arquivos.Keys)) { $itens += [pscustomobject]@{ quem = "modelo $id"; destino = $reg.arquivos[$nome].destino; tamanho = $reg.arquivos[$nome].tamanho; local = $local } }
    }
    foreach ($id in @($estado.conhecimento.Keys)) {
        $reg = $estado.conhecimento[$id]
        $local = if ($reg.local) { $reg.local } else { 'nucleo' }
        $itens += [pscustomobject]@{ quem = "biblioteca $id"; destino = $reg.destino; tamanho = $reg.tamanho; local = $local }
    }
    foreach ($x in $itens) {
        if ($x.local -eq 'cofre' -and -not $temCofre) { $pulados++; continue }
        $caminho = Caminho-Absoluto $x.destino $x.local
        if (-not (Test-Path -LiteralPath $caminho)) { Problema "$($x.quem): falta $caminho"; continue }
        if ($x.tamanho -and (Get-Item -LiteralPath $caminho).Length -ne [long]$x.tamanho) { Problema "$($x.quem): tamanho diferente do baixado em $caminho" }
        $conferidos++
    }
    Ok "$conferidos arquivos no lugar e com o tamanho certo"
    if ($pulados -gt 0) { Aviso "$pulados arquivos do cofre nao conferidos (o HD do cofre nao esta ligado)" }
}

Titulo '6. Scripts citados no menu e no guia'
$citados = @()
$citados += @([regex]::Matches((Get-Content -LiteralPath (Join-Path $PSScriptRoot 'menu.ps1') -Raw), "[\\']([\w-]+\.ps1)") | ForEach-Object { $_.Groups[1].Value })
foreach ($doc in 'docs\GUIA.md', 'LEIA-ME.md', 'README.md') {
    $p = Join-Path $Raiz $doc
    if (Test-Path -LiteralPath $p) { $citados += @([regex]::Matches((Get-Content -LiteralPath $p -Raw -Encoding UTF8), '`([\w-]+\.ps1)') | ForEach-Object { $_.Groups[1].Value }) }
}
$faltando = @($citados | Sort-Object -Unique | Where-Object { -not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $_)) })
foreach ($f in $faltando) { Problema "citado mas nao existe: scripts\$f" }
if ($faltando.Count -eq 0) { Ok "$(@($citados | Sort-Object -Unique).Count) scripts citados, todos existem" }

Write-Host ''
if ($problemas.Count -eq 0) { Ok 'Tudo certo.' } else { Aviso "$($problemas.Count) problema(s) acima."; exit 1 }
