<#
.SYNOPSIS
  Modo jogo: fecha todas as IAs e tudo ligado a elas (chat, biblioteca, conselho, ComfyUI, Ollama e a
  Central) e libera a placa de video, a memoria e o disco para jogar. Enquanto estiver ligado, nada das
  IAs abre sozinho, nem a verificacao semanal de novidades. Rodar de novo (ou -Sair) volta ao normal.
.EXAMPLE
  .\modo-jogo.ps1           # liga (ou desliga, se ja estiver ligado)
  .\modo-jogo.ps1 -Ligar
  .\modo-jogo.ps1 -Sair
#>
param([switch]$Ligar, [switch]$Sair, [string]$Manter = '')
. "$PSScriptRoot\comum.ps1"

if (-not $Ligar -and -not $Sair) { if (ModoJogo-Ativo) { $Sair = $true } else { $Ligar = $true } }

if ($Sair) {
    Remove-Item -LiteralPath $ArquivoModoJogo -ErrorAction SilentlyContinue
    Titulo 'Modo jogo desligado'
    Ok 'As IAs voltam a abrir normalmente (menu ou Central).'
    return
}

[IO.File]::WriteAllText($ArquivoModoJogo, "Modo jogo ligado em $(Get-Date -Format s)", (New-Object Text.UTF8Encoding $false))
Titulo 'Modo jogo ligado'
& "$PSScriptRoot\parar-tudo.ps1" -Manter $Manter
try {
    $os = Get-CimInstance Win32_OperatingSystem
    Info ([string]::Format($CulturaBR, 'Memoria RAM livre: {0:N1} GB de {1:N1} GB', $os.FreePhysicalMemory / 1MB, $os.TotalVisibleMemorySize / 1MB))
} catch {}
Ok 'Pode jogar: nada das IAs vai abrir ate voce sair do modo jogo.'
Info 'Para sair: menu, opcao 12, ou dois cliques em A:\Painel.cmd e "Sair do modo jogo".'
