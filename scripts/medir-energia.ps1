<#
.SYNOPSIS
  Mede quanta energia o PC gasta numa tarefa (ou parado) e quanto isso custa em reais.
  A placa de video e medida pelo sensor da NVIDIA. O resto do PC (processador, placa-mae, memoria,
  discos, ventoinhas e perdas da fonte) e estimado pela carga do processador, pois este PC nao tem
  sensor de consumo total. Para medir na tomada de verdade, use um medidor de tomada (wattimetro).
  Cada medicao e anotada em logs\energia.csv.
.EXAMPLE
  .\medir-energia.ps1 -Segundos 60                                  # PC parado por 1 minuto
  .\medir-energia.ps1 -Comando { .\conselho.ps1 "pergunta" } -Nome conselho
  .\medir-energia.ps1 -Segundos 60 -Tarifa 0.92                     # tarifa da sua conta (R$/kWh)
#>
param(
    [scriptblock]$Comando,
    [int]$Segundos = 0,
    [double]$Tarifa = 1.00,
    [string]$Nome = ''
)
. "$PSScriptRoot\comum.ps1"

# Modelo do resto do PC (Ryzen 9 7900X + X670E): processador ~35 W parado e ~195 W com todos os nucleos;
# placa-mae, memoria, discos e ventoinhas ~40 W; fonte com ~88% de eficiencia.
$CpuParado = 35; $CpuExtra = 160; $Plataforma = 40; $Eficiencia = 0.88

if (-not $Comando -and $Segundos -le 0) { throw 'Informe -Comando { ... } ou -Segundos N.' }
$inv = [Globalization.CultureInfo]::InvariantCulture
$amostras = Join-Path $env:TEMP "energia-$PID.csv"
Remove-Item -LiteralPath $amostras -ErrorAction SilentlyContinue

$coletor = Start-Job -ArgumentList $amostras -ScriptBlock {
    param($arquivo)
    $inv = [Globalization.CultureInfo]::InvariantCulture
    while ($true) {
        $gpu = 0.0
        try { $gpu = [double]::Parse(((& nvidia-smi --query-gpu=power.draw --format=csv,noheader,nounits) | Select-Object -First 1).Trim(), $inv) } catch {}
        $cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
        Add-Content -LiteralPath $arquivo -Value ([string]::Format($inv, '{0};{1};{2}', [DateTime]::Now.Ticks, $gpu, $cpu))
        Start-Sleep -Milliseconds 900
    }
}

$inicio = Get-Date
try {
    # A saida da tarefa vai para a tela, para nao se misturar com o resultado da medicao.
    if ($Comando) { & $Comando | Out-Host } else { Start-Sleep -Seconds $Segundos }
} finally {
    Start-Sleep -Seconds 1
    Stop-Job $coletor; Remove-Job $coletor -Force
}
$fim = Get-Date

$linhas = @(Get-Content -LiteralPath $amostras -ErrorAction SilentlyContinue | ForEach-Object {
    $p = $_ -split ';'
    [pscustomobject]@{ t = [long]$p[0]; gpu = [double]::Parse($p[1], $inv); cpu = [double]::Parse($p[2], $inv) }
})
Remove-Item -LiteralPath $amostras -ErrorAction SilentlyContinue
if ($linhas.Count -lt 2) { throw 'Poucas amostras; a tarefa terminou rapido demais para medir.' }

# Integra no tempo: cada amostra vale ate a proxima.
$wh = 0.0; $whGpu = 0.0
for ($i = 0; $i -lt $linhas.Count - 1; $i++) {
    $h = ($linhas[$i + 1].t - $linhas[$i].t) / [TimeSpan]::TicksPerHour
    $tomada = ($linhas[$i].gpu + $CpuParado + $CpuExtra * $linhas[$i].cpu / 100 + $Plataforma) / $Eficiencia
    $wh += $tomada * $h; $whGpu += $linhas[$i].gpu * $h
}
$horas = ($linhas[-1].t - $linhas[0].t) / [TimeSpan]::TicksPerHour
$res = [pscustomobject]@{
    tarefa        = $(if ($Nome) { $Nome } elseif ($Comando) { $Comando.ToString().Trim() } else { "parado $Segundos s" })
    inicio        = $inicio.ToString('s')
    segundos      = [math]::Round(($fim - $inicio).TotalSeconds)
    gpu_media_w   = [math]::Round(($linhas | Measure-Object gpu -Average).Average, 1)
    gpu_max_w     = [math]::Round(($linhas | Measure-Object gpu -Maximum).Maximum, 1)
    cpu_media_pct = [math]::Round(($linhas | Measure-Object cpu -Average).Average, 1)
    pc_medio_w    = [math]::Round($wh / $horas, 1)
    energia_wh    = [math]::Round($wh, 2)
    gpu_wh        = [math]::Round($whGpu, 2)
    custo_reais   = [math]::Round($wh / 1000 * $Tarifa, 4)
    tarifa        = $Tarifa
}

$log = Join-Path $Raiz 'logs\energia.csv'
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$res | Export-Csv -LiteralPath $log -Append -NoTypeInformation -Delimiter ';' -Encoding UTF8

Titulo "Energia: $($res.tarefa)"
Info ("Duracao: {0} s | placa de video: media {1} W, pico {2} W | processador: {3}% de carga" -f $res.segundos, $res.gpu_media_w, $res.gpu_max_w, $res.cpu_media_pct)
Info ("PC inteiro (estimado): {0} W em media -> {1} Wh -> R$ {2:N4} (tarifa R$ {3:N2}/kWh)" -f $res.pc_medio_w, $res.energia_wh, $res.custo_reais, $Tarifa)
$res
