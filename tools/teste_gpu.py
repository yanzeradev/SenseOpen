import torch
import sys

print(f"Python version: {sys.version}")
print(f"Torch version: {torch.__version__}")
print("-" * 30)
print(f"CUDA disponível? {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"Quantidade de GPUs: {torch.cuda.device_count()}")
    print(f"Nome da GPU 0: {torch.cuda.get_device_name(0)}")
    print(f"Versão do CUDA compilado: {torch.version.cuda}")
else:
    print("❌ ALERTA: O PyTorch está rodando em modo CPU!")
    print("Provavelmente você instalou a versão errada do torch.")