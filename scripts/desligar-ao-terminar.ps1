<#
.SYNOPSIS
  Desliga o PC quando a sessao do Claude parar (por exemplo, quando acabarem os creditos) e voce
  tambem nao estiver usando o PC. A cada minuto confere tres sinais:
    1. a conversa do Claude parou: nenhum registro em ~\.claude\projects mudou ha -MinutosSemClaude;
    2. teclado e mouse parados ha -MinutosParado (lendo ou jogando com eles, nao desliga);
    3. a placa de video folgada, abaixo de -GpuOcupada % (um jogo aberto segura o desligamento).
  Com os tres, agenda o desligamento com -Aviso segundos de aviso na tela. Se voce mexer no PC durante
  o aviso, ele e cancelado sozinho; para cancelar na mao: Win+R, "shutdown /a".
  Vale so enquanto esta vigia estiver aberta: nao muda nenhuma configuracao do Windows.
.EXAMPLE
  .\desligar-ao-terminar.ps1              # vigia com os padroes (20 min sem Claude, 15 min parado)
  .\desligar-ao-terminar.ps1 -Status      # mostra se a vigia esta ligada e os sinais agora
  .\desligar-ao-terminar.ps1 -Parar       # para a vigia e cancela um desligamento ja agendado
#>
param(
    [int]$MinutosSemClaude = 20,
    [int]$MinutosParado = 15,
    [int]$GpuOcupada = 40,
    [int]$Aviso = 300,
    [switch]$Status,
    [switch]$Parar
)
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'
New-Item -ItemType Directory -Force -Path $PastaLogs | Out-Null
$arquivoPid = Join-Path $PastaLogs 'vigia-desligar.pid'
$log = Join-Path $PastaLogs 'vigia-desligar.log'
$conversas = Join-Path $env:USERPROFILE '.claude\projects'

if (-not ('SsdIa.Ocioso' -as [type])) {
    Add-Type -Namespace SsdIa -Name Ocioso -MemberDefinition @'
[StructLayout(LayoutKind.Sequential)] public struct ULTIMA { public uint cbSize; public uint dwTime; }
[DllImport("user32.dll")] static extern bool GetLastInputInfo(ref ULTIMA u);
public static double Segundos() {
    var u = new ULTIMA(); u.cbSize = (uint)Marshal.SizeOf(u);
    if (!GetLastInputInfo(ref u)) return 0;
    return unchecked((uint)Environment.TickCount - u.dwTime) / 1000.0;
}
'@
}

function Anotar($texto) {
    $linha = "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $texto"
    Add-Content -LiteralPath $log -Value $linha -Encoding UTF8
    Write-Host "  $linha"
}

function Vigia-Aberta {
    if (-not (Test-Path -LiteralPath $arquivoPid)) { return $null }
    $id = [int](Get-Content -LiteralPath $arquivoPid -TotalCount 1)
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if ($p -and $id -ne $PID) { return $p }
    return $null
}

function Sinais {
    $ultima = Get-ChildItem -LiteralPath $conversas -Recurse -Filter '*.jsonl' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1
    $semClaude = if ($ultima) { ((Get-Date) - $ultima.LastWriteTime).TotalMinutes } else { [double]::MaxValue }
    $gpu = $null
    try { $gpu = [int]((& nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>$null | Select-Object -First 1).Trim()) } catch {}
    return [pscustomobject]@{
        SemClaude = $semClaude
        Parado    = [SsdIa.Ocioso]::Segundos() / 60
        Gpu       = $gpu
    }
}

function Texto-Sinais($s) {
    $gpu = if ($null -eq $s.Gpu) { 'sem leitura' } else { "$($s.Gpu) %" }
    return ('Claude parado ha {0:N0} min, teclado/mouse parados ha {1:N0} min, placa a {2}' -f [math]::Min($s.SemClaude, 99999), $s.Parado, $gpu)
}

if ($Parar) {
    $v = Vigia-Aberta
    if ($v) { Stop-Process -Id $v.Id -Force; Ok 'Vigia parada.' } else { Info 'A vigia nao estava aberta.' }
    Remove-Item -LiteralPath $arquivoPid -ErrorAction SilentlyContinue
    & shutdown.exe /a 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok 'Um desligamento agendado foi cancelado.' }
    return
}

if ($Status) {
    $v = Vigia-Aberta
    if ($v) { Ok "Vigia ligada (processo $($v.Id), desde $($v.StartTime.ToString('dd/MM HH:mm')))." } else { Info 'Vigia desligada.' }
    Info (Texto-Sinais (Sinais))
    if (Test-Path -LiteralPath $log) { Info 'Ultimas anotacoes:'; Get-Content -LiteralPath $log -Tail 5 | ForEach-Object { Info "  $_" } }
    return
}

if (Vigia-Aberta) { Ok 'A vigia ja esta ligada. Para ver: -Status. Para parar: -Parar.'; return }
Set-Content -LiteralPath $arquivoPid -Value $PID
Titulo 'Desligar o PC quando o Claude terminar'
Info "Desliga quando: Claude parado ha $MinutosSemClaude min + teclado/mouse parados ha $MinutosParado min + placa abaixo de $GpuOcupada %."
Info "Antes, $([math]::Round($Aviso / 60)) min de aviso na tela; mexer no PC cancela. Para parar a vigia: .\desligar-ao-terminar.ps1 -Parar"
Mostrar-Estimativa 'vigia'
Anotar "vigia ligada ($(Texto-Sinais (Sinais)))"

$agendado = $false
try {
    while ($true) {
        $s = Sinais
        $usando = $s.Parado -lt 1
        if ($agendado) {
            if ($usando -or $s.SemClaude -lt 1) {
                & shutdown.exe /a 2>$null | Out-Null
                $agendado = $false
                Anotar "desligamento cancelado: $(if ($usando) { 'voce voltou a usar o PC' } else { 'o Claude voltou a trabalhar' })"
            }
        } elseif ($s.SemClaude -ge $MinutosSemClaude -and $s.Parado -ge $MinutosParado -and ($null -eq $s.Gpu -or $s.Gpu -lt $GpuOcupada)) {
            $msg = "Cofre de IAs: o Claude terminou e o PC esta parado. Desligando em $([math]::Round($Aviso / 60)) min. Mexa no mouse para cancelar (ou Win+R: shutdown /a)."
            & shutdown.exe /s /t $Aviso /c $msg 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $agendado = $true
                Anotar "desligamento agendado ($(Texto-Sinais $s))"
                Notificar 'Cofre de IAs' "O PC desliga em $([math]::Round($Aviso / 60)) min. Mexa no mouse para cancelar."
            } else {
                Anotar "o Windows recusou agendar o desligamento (codigo $LASTEXITCODE)"
            }
        }
        Start-Sleep -Seconds 60
    }
} finally {
    Remove-Item -LiteralPath $arquivoPid -ErrorAction SilentlyContinue
}
