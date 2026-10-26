<#
.SYNOPSIS
  Instala o Linux (Ubuntu LTS mais recente) dentro do Windows pelo WSL2, com o disco virtual
  do Linux no SSD (A:\linux\ubuntu). A GPU funciona dentro do Linux pelo driver do Windows.
  PRECISA de PowerShell como Administrador. Na primeira vez, o Windows pede para reiniciar:
  reinicie e rode este script de novo.
.EXAMPLE
  # Menu Iniciar > digite PowerShell > "Executar como administrador", depois:
  powershell -ExecutionPolicy Bypass -File A:\scripts\instalar-wsl.ps1
#>
#Requires -RunAsAdministrator
param([string]$Distro = '')
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'
$env:WSL_UTF8 = '1'

$pasta = Join-Path $Raiz 'linux\ubuntu'
New-Item -ItemType Directory -Force -Path (Split-Path $pasta -Parent) | Out-Null

Titulo 'WSL2'
$status = (& wsl.exe --status 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $status -match 'not installed|nao esta instalado|não está instalado') {
    Info 'Ativando o WSL2 no Windows...'
    & wsl.exe --install --no-distribution
    Aviso 'Reinicie o PC e rode este script de novo para instalar o Ubuntu.'
    return
}
Ok 'WSL2 ativo'
& wsl.exe --update | Out-Null

if (-not $Distro) {
    $online = (& wsl.exe --list --online 2>&1 | Out-String)
    $Distro = [regex]::Matches($online, 'Ubuntu-(\d\d)\.04') | ForEach-Object { $_.Value } | Sort-Object -Unique |
        Sort-Object { [int]($_ -replace 'Ubuntu-(\d\d)\.04', '$1') } | Select-Object -Last 1
    if (-not $Distro) { $Distro = 'Ubuntu' }
}
Titulo "Instalando $Distro em $pasta"
& wsl.exe --install $Distro --location $pasta --no-launch
if ($LASTEXITCODE -ne 0) {
    Aviso 'Esta versao do WSL nao aceita --location; instalando no lugar padrao e movendo para o SSD.'
    & wsl.exe --install $Distro --no-launch
    & wsl.exe --manage $Distro --move $pasta
}
Ok "Pronto. Abra o Linux com:  wsl -d $Distro"
Info 'Na primeira abertura ele pede um nome de usuario e uma senha para o Linux.'
Info 'O SSD aparece no Linux em /mnt/a. Para preparar as ferramentas de IA, rode dentro do Linux:'
Info '  bash /mnt/a/linux/configurar-ubuntu.sh'
