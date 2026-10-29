# Menu do cofre de IAs. Abra com dois cliques em A:\IA.cmd
. "$PSScriptRoot\comum.ps1"
$ErrorActionPreference = 'Continue'

function Nova-Janela($script, $argumentos = '') {
    # Servidores abrem em janela propria para o menu continuar livre.
    Start-Process powershell -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$PSScriptRoot\$script`" $argumentos"
}

while ($true) {
    Write-Host ''
    Write-Host '================ COFRE DE IAs ================' -ForegroundColor Cyan
    Write-Host ' USAR'
    Write-Host '  1) Chat com todos os modelos (navegador, porta 8080)'
    Write-Host '  2) Biblioteca offline: Wikipedia, WikiMed, iFixit (porta 8081)'
    Write-Host '  3) Perguntar com fonte (modelo + biblioteca)'
    Write-Host '  4) Gerar imagem, video, musica ou 3D (ComfyUI)'
    Write-Host '  5) Transcrever audio (Whisper)'
    Write-Host ' 11) Gerar imagem ou video pelo terminal (com o ComfyUI aberto)'
    Write-Host ' 12) Falar um texto em voz alta (Piper)'
    Write-Host ' 13) Conselho de IAs: varias IAs respondem e decidem juntas (painel no navegador)'
    Write-Host ' 14) Medir o consumo de energia do PC (1 minuto parado)'
    Write-Host ' 15) Fechar tudo que o cofre abriu (libera a placa de video, economiza energia)'
    Write-Host ' 16) Central do Cofre no navegador: ve o que esta ligado e liga/desliga com um clique'
    Write-Host ' MANTER'
    Write-Host '  6) Status do acervo'
    Write-Host '  7) Verificar novidades e atualizacoes'
    Write-Host '  8) Sincronizar o cofre inteiro (baixa o que falta, atualiza, confere)'
    Write-Host '  9) Conferir integridade (SHA256)'
    Write-Host ' 10) Ver catalogo de modelos e bibliotecas'
    Write-Host ' 17) Testar o projeto (scripts, catalogo, arquivos e segredos; sem rodar modelos)'
    Write-Host '  0) Sair'
    $op = Read-Host 'Escolha'
    try {
        switch ($op) {
            '1' { Nova-Janela 'iniciar-servidor.ps1' }
            '2' { Nova-Janela 'iniciar-biblioteca.ps1' }
            '3' {
                $q = Read-Host 'Sua pergunta'
                if ($q) { & "$PSScriptRoot\perguntar.ps1" $q }
            }
            '4' { Nova-Janela 'iniciar-comfyui.ps1' }
            '5' {
                $f = Read-Host 'Caminho do arquivo de audio (WAV)'
                if ($f) { & "$PSScriptRoot\transcrever.ps1" -Audio $f.Trim('"') }
            }
            '6' { & "$PSScriptRoot\status.ps1" }
            '7' { & "$PSScriptRoot\verificar-atualizacoes.ps1" }
            '8' { Nova-Janela 'sincronizar-cofre.ps1' }
            '9' { & "$PSScriptRoot\verificar-integridade.ps1" }
            '10' { & "$PSScriptRoot\baixar-modelo.ps1" -Listar; & "$PSScriptRoot\baixar-conhecimento.ps1" -Listar }
            '11' {
                $tipo = Read-Host 'Imagem (i) ou video (v)?'
                $texto = Read-Host 'Descreva (de preferencia em ingles)'
                if ($texto -and $tipo -eq 'v') { & "$PSScriptRoot\gerar.ps1" -Video $texto }
                elseif ($texto) { & "$PSScriptRoot\gerar.ps1" -Imagem $texto }
            }
            '12' {
                $texto = Read-Host 'Texto para falar'
                if ($texto) { & "$PSScriptRoot\falar.ps1" $texto -Tocar }
            }
            '13' { Nova-Janela 'conselho.ps1' '-Servir' }
            '14' { & "$PSScriptRoot\medir-energia.ps1" -Segundos 60 | Out-Null }
            '15' { & "$PSScriptRoot\parar-tudo.ps1" }
            '17' { & "$PSScriptRoot\testar-cofre.ps1" }
            '16' { Start-Process powershell -WindowStyle Minimized -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSScriptRoot\central.ps1`"" }
            '0' { return }
        }
    } catch {
        Write-Host "Erro: $($_.Exception.Message)" -ForegroundColor Red
    }
}
