# /// script
# requires-python = ">=3.11"
# dependencies = ["piper-tts>=1.8"]
# ///
"""
Texto para voz em portugues do Brasil com o Piper, offline e so em CPU.

Uso (pelo wrapper A:\\scripts\\falar.ps1):
  falar.ps1 "Bom dia. O cofre esta funcionando."
  falar.ps1 -Arquivo C:\\texto.txt -Voz cadu -Saida C:\\audio.wav
"""
import argparse
import sys
import wave
from pathlib import Path

from piper import PiperVoice


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("texto", nargs="?", help="texto a falar (ou use --arquivo)")
    p.add_argument("--arquivo", help="arquivo .txt com o texto")
    p.add_argument("--modelo", required=True, help="caminho do .onnx da voz")
    p.add_argument("--saida", required=True, help="arquivo .wav a gerar")
    args = p.parse_args()

    texto = Path(args.arquivo).read_text(encoding="utf-8") if args.arquivo else args.texto
    if not texto:
        sys.exit("Informe o texto ou --arquivo.")
    voz = PiperVoice.load(args.modelo)
    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(args.saida, "wb") as wav:
        voz.synthesize_wav(texto, wav)
    print(args.saida)


if __name__ == "__main__":
    main()
