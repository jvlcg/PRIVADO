<#
.SYNOPSIS
  Cria (ou atualiza) a tarefa do Windows que roda verificar-atualizacoes.ps1 toda semana.
  A tarefa e do seu usuario, nao precisa de administrador, so verifica e avisa (nao baixa nada).
  Se houver novidade, aparece uma notificacao e o relatorio fica em catalogo\relatorios\.
.EXAMPLE
  .\agendar-verificacao.ps1                       # segunda-feira as 10h
  .\agendar-verificacao.ps1 -Dia Friday -Hora 18:30
  .\agendar-verificacao.ps1 -Remover
#>
param(
    [ValidateSet('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')][string]$Dia = 'Monday',
    [string]$Hora = '10:00',
    [switch]$Remover
)
. "$PSScriptRoot\comum.ps1"

$nome = 'SSD-IA - verificar atualizacoes'
if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Ok "Tarefa '$nome' removida."
    return
}

$script = Join-Path $PSScriptRoot 'verificar-atualizacoes.ps1'
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`" -Agendado"
$gatilho = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Dia -At $Hora
$config = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $config -Force `
    -Description 'Confere modelos novos e atualizacoes do acervo do SSD de IAs. Criada por A:\scripts\agendar-verificacao.ps1' | Out-Null

$t = Get-ScheduledTask -TaskName $nome
$prox = (Get-ScheduledTaskInfo -TaskName $nome).NextRunTime
Ok "Tarefa '$nome' criada ($($t.State))."
Info "Proxima execucao: $prox"
Info 'Se o PC estiver desligado no horario, ela roda assim que ele ligar.'
