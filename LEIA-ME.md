# COFRE DE IAs - LEIA-ME

Este SSD e uma biblioteca de inteligencia artificial que funciona SEM INTERNET:
modelos de IA abertos, os programas que os rodam, a Wikipedia e outras bibliotecas offline,
e as ferramentas para usar tudo isso. Montado em 25/10/2026.

## Como comecar

1. De dois cliques em `IA.cmd` (nesta pasta). Abre o menu.
2. Opcao 1: chat com os modelos, no navegador (http://127.0.0.1:8080). Na primeira vez o chat pede a
   chave de acesso: ela ja vai copiada, e so colar com Ctrl+V (fica em catalogo\chave-api.txt).
3. Opcao 2: biblioteca offline - Wikipedia, enciclopedia medica, manuais de conserto (http://127.0.0.1:8081).
4. Opcao 3: pergunte algo; o modelo responde citando a Wikipedia e as outras bibliotecas.

Precisa de Windows 10/11. Com placa NVIDIA fica rapido; sem ela, funciona mais devagar.
Os scripts estao em `scripts\` e todos tem ajuda: `Get-Help .\scripts\<nome>.ps1 -Examples`

## O que tem aqui

| Pasta          | Conteudo |
|----------------|----------|
| `modelos\`     | os modelos de IA, por tipo: llm, codigo, medicina, traducao, ocr, leve, embeddings, audio, imagem |
| `conhecimento\`| bibliotecas offline (.zim): Wikipedia PT, WikiMed, iFixit, livros, foruns praticos |
| `motores\`     | programas: llama.cpp, whisper.cpp, ComfyUI, Kiwix, Python (uv), Ollama |
| `motores\llama.cpp-outras-maquinas\` | llama.cpp para Windows sem GPU, Linux, Raspberry Pi, Mac, Android + codigo-fonte |
| `catalogo\`    | `modelos.json` (a lista de tudo) e `estado.json` (o que foi baixado, com hashes) |
| `dev\`         | projetos proprios, RAG, treino de LoRA, configuracoes |
| `linux\`       | disco do Linux (WSL2) e script de configuracao |
| `SHA256SUMS.txt` | hash de cada arquivo, para conferir a integridade |

Ha um segundo disco, o COFRE PROFUNDO (`D:\COFRE-IA`), com os modelos gigantes, a Wikipedia em ingles,
o Projeto Gutenberg, o Stack Overflow e uma copia de seguranca deste SSD.

## Escolha do modelo

| Para                         | Use |
|------------------------------|-----|
| conversar rapido             | gemma-4-12b |
| melhor resposta geral        | gemma-4-26b-a4b ou qwen3.8-27b (mais lento) |
| programar                    | qwen3-coder-next |
| saude                        | medgemma-27b (junto com a WikiMed; nao substitui medico) |
| traduzir                     | translategemma-12b |
| ler documento ou foto        | glm-ocr |
| computador fraco ou sem GPU  | gemma-4-e4b, qwen3.5-2b, lfm2.5-1.2b, qwen3.5-0.8b |
| o maior que roda aqui        | nemotron-3.5-bolt-74b (fica no HD: ~5 min para carregar) |
| varias IAs decidindo juntas  | Conselho de IAs: menu, opcao 13 (http://127.0.0.1:8090) |

## Economizar energia

- Ao terminar, menu opcao 15: fecha tudo que o cofre abriu e libera a placa de video.
- Mesmo sem isso, o servidor de modelos tira da memoria o modelo parado ha 15 minutos.
- Suspenda o PC quando nao for usar. Custos e dicas: guia, secao "Custo de energia".

## Conferir se nada estragou

No PowerShell: `powershell -ExecutionPolicy Bypass -File .\scripts\verificar-integridade.ps1`
Em qualquer Linux, na raiz deste disco: `sha256sum -c SHA256SUMS.txt`

## Manter atualizado (quando houver internet)

Menu, opcao 8 (sincronizar o cofre). Uma tarefa do Windows tambem verifica novidades toda segunda as 10h.

## Guia completo

`docs\GUIA.md` (copia offline) e https://claude.ai/artifact/XuMQNn1aZENjqeAZKDqruw