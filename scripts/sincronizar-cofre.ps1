<#
.SYNOPSIS
  Um comando para deixar o cofre inteiro em dia. Roda, em ordem:
    1. motores (instala versoes novas ao lado das antigas)
    2. arruma modelos que estao no disco errado (mover-modelo)
    3. modelos e bibliotecas do SSD (nucleo)
    4. modelos e bibliotecas do cofre (disco de arquivo)
    5. copia de seguranca do SSD para o cofre (espelho)
    6. conferencia de integridade (SHA256) e SHA256SUMS.txt
  Pode ser interrompido e rodado de novo: continua de onde parou e pula o que ja esta conferido.
.EXAMPLE
  .\sincronizar-cofre.ps1
  .\sincronizar-cofre.ps1 -SoNucleo          # ignora o cofre (por exemplo, com o HD desligado)
  .\sincronizar-cofre.ps1 -SemEspelho -SemIntegridade
#>
param([switch]$SoNucleo, [switch]$SemEspelho, [switch]$SemIntegridade, [int]$Prioridade = 2)
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'

New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
$log = Join-Path $PastaLogs ("sincronizar-{0}.txt" -f (Get-Date -Format 'yyyy-MM-dd_HHmm'))
Start-Transcript -Path $log -Force | Out-Null
$inicio = Get-Date
$rc = Raiz-Cofre
$temCofre = (-not $SoNucleo) -and $rc -and (Test-Path ([IO.Path]::GetPathRoot($rc)))
if (-not $SoNucleo -and -not $temCofre) { Aviso "Cofre ($rc) indisponivel: sincronizando so o SSD." }
if ($temCofre) { New-Item -ItemType Directory -Force -Path $rc | Out-Null }

function Etapa($nome, [scriptblock]$acao) {
    Write-Host ''
    Write-Host ("#### {0}  ({1:HH:mm})" -f $nome, (Get-Date)) -ForegroundColor Magenta
    try { & $acao } catch { Write-Host "Erro em '$nome': $($_.Exception.Message)" -ForegroundColor Red }
}

Etapa 'Motores' { & "$PSScriptRoot\instalar-motores.ps1" -Todos }
if ($temCofre) { Etapa 'Arrumar modelos entre SSD e cofre' { & "$PSScriptRoot\mover-modelo.ps1" } }
Etapa 'Modelos do SSD' { & "$PSScriptRoot\baixar-modelo.ps1" -Prioridade $Prioridade -Local nucleo -Silencioso }
Etapa 'Bibliotecas do SSD' { & "$PSScriptRoot\baixar-conhecimento.ps1" -Local nucleo -Silencioso }
if ($temCofre) {
    # Bibliotecas (Kiwix) e modelos (Hugging Face) vem de servidores diferentes: baixam ao mesmo tempo,
    # a biblioteca numa janela propria. O estado.json e protegido por trava, entao nao ha conflito.
    $logBib = Join-Path $PastaLogs ("bibliotecas-cofre-{0}.txt" -f (Get-Date -Format 'yyyy-MM-dd_HHmm'))
    $cmdBib = "Start-Transcript -Path '$logBib' -Force | Out-Null; & '$PSScriptRoot\baixar-conhecimento.ps1' -Local cofre -Silencioso; Stop-Transcript | Out-Null"
    $bib = Start-Process powershell -PassThru -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $([Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmdBib)))"
    Info "Bibliotecas do cofre baixando em paralelo (log: $(Caminho-Relativo $logBib))"
    Etapa 'Modelos do cofre' { & "$PSScriptRoot\baixar-modelo.ps1" -Prioridade $Prioridade -Local cofre -Silencioso }
    if (-not $SemEspelho) { Etapa 'Copia de seguranca do SSD no cofre' { & "$PSScriptRoot\copiar-backup.ps1" -Destino (Join-Path $rc 'espelho-ssd') -Tudo } }
    Etapa 'Esperando as bibliotecas do cofre' { $bib.WaitForExit() }
}
# Cada arquivo ja foi conferido no download; aqui basta checar tamanhos e gravar os SHA256SUMS.txt.
# A conferencia completa (relendo tudo) e o verificar-integridade.ps1 sem -Rapido, a cada poucos meses.
if (-not $SemIntegridade) { Etapa 'Conferencia de integridade' { & "$PSScriptRoot\verificar-integridade.ps1" -Rapido } }

Titulo 'Sincronizacao terminada'
Info ("Duracao: {0:hh\:mm\:ss}" -f ((Get-Date) - $inicio))
Info "Log completo: $(Caminho-Relativo $log)"
Stop-Transcript | Out-Null
Notificar 'SSD de IAs' 'Sincronizacao do cofre terminada. Veja o log em A:\logs.'
