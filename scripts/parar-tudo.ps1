<#
.SYNOPSIS
  Fecha tudo que o cofre abriu (servidor de modelos, biblioteca, ComfyUI, conselho, Ollama)
  e libera a placa de video e a memoria. Use quando terminar de usar as IAs, para economizar energia.
  So fecha programas que rodam de dentro das pastas do cofre (motores e cache); nada do Windows.
  Se uma sincronizacao estiver baixando algo, o download para e continua na proxima vez.
.EXAMPLE
  .\parar-tudo.ps1
  .\parar-tudo.ps1 -Manter 1234,5678   # deixa estes processos abertos (a Central do Cofre usa isso)
#>
param([string]$Manter = '')
. "$PSScriptRoot\comum.ps1"

$manterIds = @($Manter -split ',' | Where-Object { $_.Trim() -match '^\d+$' } | ForEach-Object { [int]$_.Trim() })
if ($manterIds.Count -gt 0) {
    # Poupa tambem quem abriu esses processos (uv e o lancador do Python), senao a janela deles fecharia.
    $pais = @{}
    Get-CimInstance Win32_Process | ForEach-Object { $pais[[int]$_.ProcessId] = [int]$_.ParentProcessId }
    foreach ($id in @($manterIds)) {
        $atual = $id
        for ($n = 0; $n -lt 6 -and $pais.ContainsKey($atual) -and $pais[$atual] -gt 4; $n++) {
            $atual = $pais[$atual]
            $manterIds += $atual
        }
    }
}
$alvos = @(Processos-Cofre | Where-Object { $manterIds -notcontains $_.Id })

Titulo 'Fechando o que o cofre abriu'
if ($alvos.Count -eq 0) { Ok 'Nada do cofre estava aberto.' }
foreach ($p in $alvos) {
    # Fechar o servidor principal ja fecha os filhos dele; esses aparecem como encerrados aqui.
    if ($p.HasExited) { continue }
    try { Stop-Process -Id $p.Id -Force -ErrorAction Stop; Ok "$($p.ProcessName) (PID $($p.Id))" }
    catch { if (-not $p.HasExited) { Aviso "Nao consegui fechar $($p.ProcessName) (PID $($p.Id)): $($_.Exception.Message)" } }
}

Start-Sleep -Seconds 2
try {
    $uso = (& nvidia-smi --query-gpu=memory.used,power.draw --format=csv,noheader) | Select-Object -First 1
    Info "Placa de video agora: $uso (memoria usada, consumo)"
} catch {}
Info 'Para gastar ainda menos: suspenda o PC quando sair (Iniciar > Energia > Suspender).'
