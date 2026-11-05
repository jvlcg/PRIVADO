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
// Controle (XInput): o numero do pacote muda a cada botao ou alavanca mexida. Devolve a soma dos 4 controles.
[StructLayout(LayoutKind.Sequential)] public struct XESTADO { public uint pacote; public ushort botoes; public byte lt, rt; public short lx, ly, rx, ry; }
[DllImport("xinput1_4.dll", EntryPoint = "XInputGetState")] static extern uint XInputGetState(uint i, out XESTADO e);
public static long Controles() {
    long soma = 0;
    try { for (uint i = 0; i < 4; i++) { XESTADO e; if (XInputGetState(i, out e) == 0) soma += e.pacote + 1; } } catch { }
    return soma;
}
'@
}

# Jogos e tarefas longas seguram o desligamento, mesmo com teclado, mouse e placa parados
# (um jogo leve com controle deixa os tres sinais parados; um download nao usa a placa).
$PastasDeJogo = '\steamapps\common\', '\Epic Games\', '\GOG Galaxy\Games\', '\XboxGames\', '\Riot Games\'
$TarefasLongas = 'sincronizar-cofre', 'baixar-modelo', 'baixar-conhecimento', 'verificar-integridade', 'copiar-backup', 'gerar.ps1', 'instalar-motores'
function Ocupado {
    $jogo = Get-Process -ErrorAction SilentlyContinue | Where-Object { $p = $_.Path; $p -and @($PastasDeJogo | Where-Object { $p -like "*$_*" }).Count } | Select-Object -First 1
    if ($jogo) { return "jogo aberto ($($jogo.ProcessName))" }
    $tarefa = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $c = $_.CommandLine; $c -and @($TarefasLongas | Where-Object { $c -like "*$_*" }).Count } | Select-Object -First 1
    if ($tarefa) { return 'tarefa longa do cofre rodando' }
    return $null
}
$script:ultimoControle = [SsdIa.Ocioso]::Controles()
$script:quandoControle = Get-Date

function Anotar($texto) {
    $linha = "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $texto"
    Add-Content -LiteralPath $log -Value $linha -Encoding UTF8
    Write-Host "  $linha"
}

function Vigia-Aberta {
    if (-not (Test-Path -LiteralPath $arquivoPid)) { return $null }
    $id = 0
    if (-not [int]::TryParse(((Get-Content -LiteralPath $arquivoPid -TotalCount 1) -as [string]).Trim(), [ref]$id) -or $id -eq $PID) { return $null }
    # So conta se o processo e mesmo esta vigia: um PID velho (o PC desligou sem apagar o arquivo) pode ter sido
    # reaproveitado por outro programa, que entao nasceu DEPOIS de o arquivo ser gravado.
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    $gravado = (Get-Item -LiteralPath $arquivoPid).LastWriteTime
    if ($p -and $p.ProcessName -match '^(powershell|pwsh)$' -and $p.StartTime -le $gravado.AddSeconds(5)) { return $p }
    return $null
}

function Sinais {
    $ultima = Get-ChildItem -LiteralPath $conversas -Recurse -Filter '*.jsonl' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime | Select-Object -Last 1
    $semClaude = if ($ultima) { ((Get-Date) - $ultima.LastWriteTime).TotalMinutes } else { [double]::MaxValue }
    $gpu = $null
    try { $gpu = [int]((& nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>$null | Select-Object -First 1).Trim()) } catch {}
    $controle = [SsdIa.Ocioso]::Controles()
    if ($controle -ne $script:ultimoControle) { $script:ultimoControle = $controle; $script:quandoControle = Get-Date }
    $teclado = [SsdIa.Ocioso]::Segundos() / 60
    return [pscustomobject]@{
        SemClaude = $semClaude
        Parado    = [math]::Min($teclado, ((Get-Date) - $script:quandoControle).TotalMinutes)
        Gpu       = $gpu
        Ocupado   = Ocupado
    }
}

function Texto-Sinais($s) {
    $gpu = if ($null -eq $s.Gpu) { 'sem leitura' } else { "$($s.Gpu) %" }
    $extra = if ($s.Ocupado) { ", $($s.Ocupado)" } else { '' }
    return ('Claude parado ha {0:N0} min, teclado/mouse/controle parados ha {1:N0} min, placa a {2}{3}' -f [math]::Min($s.SemClaude, 99999), $s.Parado, $gpu, $extra)
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
Info "Desliga quando: Claude parado ha $MinutosSemClaude min + teclado/mouse/controle parados ha $MinutosParado min + placa abaixo de $GpuOcupada %."
Info 'Nunca desliga com jogo aberto (Steam, Epic, GOG, Xbox) nem com download, sincronizacao ou conferencia do cofre rodando.'
Info "Antes, $([math]::Round($Aviso / 60)) min de aviso na tela; mexer no PC cancela. Para parar a vigia: .\desligar-ao-terminar.ps1 -Parar"
Mostrar-Estimativa 'vigia'
Anotar "vigia ligada ($(Texto-Sinais (Sinais)))"

$agendado = $false
try {
    while ($true) {
        $s = Sinais
        $usando = $s.Parado -lt 1
        if ($agendado) {
            if ($usando -or $s.SemClaude -lt 1 -or $s.Ocupado) {
                & shutdown.exe /a 2>$null | Out-Null
                $agendado = $false
                $motivo = if ($usando) { 'voce voltou a usar o PC' } elseif ($s.Ocupado) { $s.Ocupado } else { 'o Claude voltou a trabalhar' }
                Anotar "desligamento cancelado: $motivo"
            }
        } elseif (-not $s.Ocupado -and $s.SemClaude -ge $MinutosSemClaude -and $s.Parado -ge $MinutosParado -and ($null -eq $s.Gpu -or $s.Gpu -lt $GpuOcupada)) {
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
    # Parada com Ctrl+C durante o aviso: o desligamento ja agendado nao pode ficar valendo sem a vigia.
    if ($agendado) { & shutdown.exe /a 2>$null | Out-Null; Anotar 'vigia parada durante o aviso: desligamento cancelado' }
    Remove-Item -LiteralPath $arquivoPid -ErrorAction SilentlyContinue
}
