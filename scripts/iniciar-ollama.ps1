<#
.SYNOPSIS
  Roda o Ollama a partir do SSD, guardando os modelos dele em modelos\ollama.
  Nao muda nenhuma configuracao do Windows: a pasta vale so para esta janela.
  Observacao: o Ollama guarda os modelos no formato proprio dele. Para nao ocupar espaco
  duas vezes, prefira o llama.cpp (iniciar-chat.ps1) e use o Ollama so com apps que exigem.
.EXAMPLE
  .\iniciar-ollama.ps1
  # em outra janela:  A:\motores\ollama\<versao>\ollama.exe run gemma4:12b
#>
. "$PSScriptRoot\comum.ps1"

$exe = Achar-Exe 'ollama' 'ollama.exe'
$env:OLLAMA_MODELS = Join-Path $PastaModelos 'ollama'
$env:OLLAMA_HOST = '127.0.0.1:11434'
Titulo 'Ollama'
Info "Modelos em: $(Caminho-Relativo $env:OLLAMA_MODELS)"
Info "API:        http://$($env:OLLAMA_HOST)"
Info "Comandos:   & '$exe' pull <modelo>   |   & '$exe' run <modelo>"
Info 'Para parar: Ctrl+C nesta janela.'
Executar-Nativo $exe @('serve')
