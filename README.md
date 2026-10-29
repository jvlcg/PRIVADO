# Cofre de IAs

Biblioteca de inteligência artificial que funciona sem internet: modelos abertos, os programas que os
rodam, a Wikipédia e outras bibliotecas offline, e ferramentas para usar tudo isso. Este repositório guarda
só o "cérebro" do cofre (scripts, catálogo, guia e ferramentas). Os arquivos grandes (modelos, bibliotecas,
motores; cerca de 1,6 TB) ficam nos discos e são baixados de novo pelos scripts, com conferência de SHA256.

- **Começar:** dois cliques em `IA.cmd` (menu) ou em `Painel.cmd` (Central do Cofre: liga e desliga tudo pelo navegador). Explicação curta em [LEIA-ME.md](LEIA-ME.md).
- **Guia completo:** [docs/GUIA.md](docs/GUIA.md).
- **Base de dados:** [catalogo/modelos.json](catalogo/modelos.json) (o que existe) e `catalogo/estado.json`
  (o que foi baixado, com hashes).
- **Recriar o cofre em outro disco:** clone este repositório na raiz do disco e rode
  `powershell -ExecutionPolicy Bypass -File scripts\sincronizar-cofre.ps1`.

| Pasta | Conteúdo |
| --- | --- |
| `scripts/` | todos os comandos (menu, downloads, servidores, integridade, backup) |
| `catalogo/` | catálogo de modelos, bibliotecas e motores; estado; relatórios semanais |
| `dev/ferramentas/` | Sabio (perguntas com fonte e RAG), Conselho de IAs, Central do Cofre e falar (texto para voz) |
| `dev/lora/` | modelo de treino LoRA |
| `dev/configs/` | configuração do Continue (VS Code) |
| `docs/` | guia offline e a página da Central (`painel.html`) |
| `linux/` | configuração do Ubuntu no WSL2 |
