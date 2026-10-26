# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = ["unsloth", "datasets", "trl"]
# ///
"""
Treina um adaptador LoRA (ajuste fino leve) com Unsloth e exporta o resultado em GGUF,
pronto para o llama-server do SSD. Feito para rodar no Linux do WSL com a RTX 4070 (12 GB).

MODELO (nao testado neste PC ainda): a primeira execucao baixa ~6 GB de pacotes (PyTorch, CUDA).

Dados: um arquivo .jsonl, uma conversa por linha (veja exemplo-dados.jsonl):
  {"messages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}

Uso (dentro do Linux):
  cd /mnt/a/dev/lora
  uv run treinar-lora.py --dados exemplo-dados.jsonl --modelo unsloth/Qwen3.5-4B --nome meu-assistente

Modelos que cabem em 12 GB para treinar em 4 bits: ate ~14B (Qwen3.5 4B/9B, Gemma 4 12B).
O GGUF final vai para /mnt/a/dev/modelos-proprios/<nome>/ ; adicione-o ao catalogo para usar no chat.
"""
import argparse
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dados", required=True, help="arquivo .jsonl com conversas")
    p.add_argument("--modelo", default="unsloth/Qwen3.5-4B")
    p.add_argument("--nome", default="meu-modelo")
    p.add_argument("--epocas", type=float, default=1.0)
    p.add_argument("--rank", type=int, default=16, help="tamanho do LoRA (8 a 64)")
    p.add_argument("--contexto", type=int, default=2048)
    p.add_argument("--saida", default="/mnt/a/dev/modelos-proprios")
    args = p.parse_args()

    from unsloth import FastLanguageModel  # importar antes do trl/transformers
    from datasets import load_dataset
    from trl import SFTConfig, SFTTrainer

    modelo, tok = FastLanguageModel.from_pretrained(args.modelo, max_seq_length=args.contexto, load_in_4bit=True)
    modelo = FastLanguageModel.get_peft_model(
        modelo,
        r=args.rank,
        lora_alpha=args.rank,
        lora_dropout=0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    dados = load_dataset("json", data_files=args.dados, split="train")
    dados = dados.map(lambda ex: {"text": tok.apply_chat_template(ex["messages"], tokenize=False)})

    saida = Path(args.saida) / args.nome
    treino = SFTTrainer(
        model=modelo,
        processing_class=tok,
        train_dataset=dados,
        args=SFTConfig(
            dataset_text_field="text",
            max_length=args.contexto,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            num_train_epochs=args.epocas,
            learning_rate=2e-4,
            warmup_steps=5,
            logging_steps=5,
            optim="adamw_8bit",
            output_dir=str(saida / "checkpoints"),
            report_to="none",
        ),
    )
    treino.train()

    modelo.save_pretrained(str(saida / "adaptador"))
    tok.save_pretrained(str(saida / "adaptador"))
    modelo.save_pretrained_gguf(str(saida / "gguf"), tok, quantization_method="q4_k_m")
    print(f"Pronto: {saida}")


if __name__ == "__main__":
    main()
