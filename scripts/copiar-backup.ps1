<#
.SYNOPSIS
  Copia o SSD de IAs para outro disco (regra 3-2-1: tenha pelo menos 2 copias em discos diferentes).
  So copia arquivos novos ou alterados e NUNCA apaga nada no destino.
  Por padrao copia o que e insubstituivel (dev, catalogo, scripts, docs); com -Tudo inclui modelos e motores.
.EXAMPLE
  .\copiar-backup.ps1 -Destino D:\Backup-SSD-IA
  .\copiar-backup.ps1 -Destino E:\SSD-IA -Tudo
#>
param(
    [Parameter(Mandatory = $true)][string]$Destino,
    [switch]$Tudo
)
. "$PSScriptRoot\comum.ps1"

if ($Destino.TrimEnd('\').StartsWith($Raiz.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'O destino precisa estar em outro disco, nao dentro do proprio SSD.'
}
$pastas = @('dev', 'catalogo', 'scripts', 'docs')
if ($Tudo) { $pastas += @('modelos', 'conhecimento', 'motores') }
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
foreach ($f in 'LEIA-ME.md', 'README.md', 'IA.cmd', 'Painel.cmd', 'SHA256SUMS.txt') { if (Test-Path (Join-Path $Raiz $f)) { Copy-Item (Join-Path $Raiz $f) $Destino -Force } }

foreach ($p in $pastas) {
    $origem = Join-Path $Raiz $p
    if (-not (Test-Path -LiteralPath $origem)) { continue }
    Titulo "Copiando $p"
    # /E subpastas | /XO pula o que ja esta igual ou mais novo | /MT:16 em paralelo | sem /MIR: nada e apagado no destino
    Executar-Nativo 'robocopy.exe' @($origem, (Join-Path $Destino $p), '/E', '/XO', '/MT:16', '/R:2', '/W:5', '/NP', '/NFL', '/NDL', '/XD', '.venv', '__pycache__')
    if ($LASTEXITCODE -ge 8) { Aviso "robocopy terminou com erro ($LASTEXITCODE) em $p" } else { Ok "$p copiado" }
}
Info "Backup em $Destino"
