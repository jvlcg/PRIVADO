<#
.SYNOPSIS
  Confere se o acervo esta integro, no SSD e no cofre: recalcula o SHA256 de cada modelo e biblioteca
  e compara com o registrado no download. Lista arquivos que o catalogo nao conhece.
  Tambem grava um SHA256SUMS.txt na raiz de cada disco, no formato padrao: em qualquer Linux,
  "sha256sum -c SHA256SUMS.txt" confere tudo sem precisar destes scripts.
  Rode depois de copiar o acervo, a cada poucos meses, ou se um modelo se comportar estranho.
.EXAMPLE
  .\verificar-integridade.ps1
  .\verificar-integridade.ps1 -Rapido       # so confere tamanhos (segundos em vez de horas)
  .\verificar-integridade.ps1 -Local nucleo # so o SSD
#>
param([switch]$Rapido, [ValidateSet('nucleo', 'cofre', 'todos')][string]$Local = 'todos')
. "$PSScriptRoot\comum.ps1"
if (-not $Rapido) { Bloquear-SeModoJogo 'a conferencia completa (le os dois discos inteiros)' }

$estado = Ler-Estado
$ok = 0; $ruim = 0; $falta = 0
$conhecidos = @{}
$somas = @{ nucleo = New-Object System.Collections.Generic.List[string]; cofre = New-Object System.Collections.Generic.List[string] }
$log = New-Object System.Collections.Generic.List[string]

# Junta modelos e bibliotecas numa lista so: (local, caminho relativo, tamanho, sha256)
$entradas = @()
foreach ($id in @($estado.modelos.Keys)) {
    $reg = $estado.modelos[$id]
    $loc = 'nucleo'
    if ($reg.local) { $loc = $reg.local }
    foreach ($k in @($reg.arquivos.Keys)) { $f = $reg.arquivos[$k]; $entradas += [pscustomobject]@{ local = $loc; rel = $f.destino; tamanho = [int64]$f.tamanho; sha = $f.sha256 } }
}
foreach ($id in @($estado.conhecimento.Keys)) {
    $c = $estado.conhecimento[$id]
    $entradas += [pscustomobject]@{ local = $c.local; rel = $c.destino; tamanho = [int64]$c.tamanho; sha = $c.sha256 }
}
if ($Local -ne 'todos') { $entradas = @($entradas | Where-Object { $_.local -eq $Local }) }

Titulo 'Conferindo o acervo'
$inicio = Get-Date
if ($Rapido) { Mostrar-Estimativa 'verificar' "$(Texto-Custo 0.5) (so confere tamanhos)" }
else { Mostrar-Estimativa 'integridade' "$(Texto-Estimativa 'integridade'): rele todos os arquivos dos dois discos" }
foreach ($x in $entradas) {
    try { $cam = Caminho-Absoluto $x.rel $x.local } catch { Aviso "Cofre indisponivel para $($x.rel)"; $falta++; continue }
    $conhecidos[$cam.ToLower()] = $true
    if (-not (Test-Path -LiteralPath $cam)) { Aviso "FALTANDO       $cam"; $log.Add("FALTANDO $cam"); $falta++; continue }
    if ((Get-Item -LiteralPath $cam).Length -ne $x.tamanho) { Aviso "TAMANHO ERRADO $cam"; $log.Add("TAMANHO $cam"); $ruim++; continue }
    if (-not $Rapido) {
        Info "calculando $cam ..."
        if ((Hash-Arquivo $cam) -ne $x.sha) { Aviso "CORROMPIDO     $cam"; $log.Add("CORROMPIDO $cam"); $ruim++; continue }
    }
    Ok $cam
    $log.Add("OK $cam")
    $somas[$x.local].Add("$($x.sha) *$($x.rel.Replace('\', '/'))")
    $ok++
}

Titulo 'Arquivos fora do catalogo'
$exts = '.gguf', '.safetensors', '.bin', '.pth', '.pt', '.onnx', '.zim'
$pastas = @()
foreach ($loc in 'nucleo', 'cofre') {
    if ($Local -ne 'todos' -and $Local -ne $loc) { continue }
    try { $b = Base-Local $loc } catch { continue }
    foreach ($sub in 'modelos', 'conhecimento') { $p = Join-Path $b $sub; if (Test-Path -LiteralPath $p) { $pastas += $p } }
}
$extras = @($pastas | ForEach-Object { Get-ChildItem -LiteralPath $_ -Recurse -File -ErrorAction SilentlyContinue } |
    Where-Object { $exts -contains $_.Extension.ToLower() -and -not $conhecidos.ContainsKey($_.FullName.ToLower()) -and $_.FullName -notmatch '\\ollama\\' })
if ($extras.Count -eq 0) { Info 'Nenhum.' }
foreach ($x in $extras) { Info ("{0}  ({1:N2} GB)" -f $x.FullName, ($x.Length / 1GB)); $log.Add("FORA-DO-CATALOGO $($x.FullName)") }

# SHA256SUMS.txt (com os hashes conferidos no download) so e regravado quando nada falhou.
if ($ruim -eq 0 -and $falta -eq 0) {
    foreach ($loc in 'nucleo', 'cofre') {
        if ($somas[$loc].Count -eq 0) { continue }
        $arq = Join-Path (Base-Local $loc) 'SHA256SUMS.txt'
        [IO.File]::WriteAllLines($arq, ($somas[$loc] | Sort-Object { $_.Substring(66) }), (New-Object Text.UTF8Encoding $false))
        Info "Gravado $arq ($($somas[$loc].Count) arquivos)"
    }
}

Titulo 'Resultado'
Info "$ok ok, $ruim com problema, $falta faltando, $($extras.Count) fora do catalogo."
Mostrar-GastoFinal 'integridade' $inicio
if ($ruim -gt 0 -or $falta -gt 0) { Aviso 'Para reparar: rode baixar-modelo.ps1 -Id <id> ou baixar-conhecimento.ps1 -Id <id> do item afetado.' }
New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
$arqLog = Join-Path $PastaLogs ("integridade-{0}.txt" -f (Get-Date -Format 'yyyy-MM-dd'))
[IO.File]::WriteAllLines($arqLog, $log, (New-Object Text.UTF8Encoding $false))
Info "Log: $(Caminho-Relativo $arqLog)"
