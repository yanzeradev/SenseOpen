from ultralytics import YOLO
import torch
import os

# ======================
# CONFIGURAÇÕES
# ======================
PROJECT_NAME = "SenseProduct_PeopleCounting"
RUN_NAME = "pretrain_coco_crowd_v1"
DATA_YAML = "dataset_yolo/data.yaml" 
HYP_YAML = "sense/hyp_dataset.yaml" 

# Escolha do modelo: 
# yolov8n.pt (Nano) - Mais rápido, menos preciso
# yolov8s.pt (Small) - Recomendado para sua RTX 2060
# yolov8m.pt (Medium) - Pode estourar a VRAM de 6GB se a imagem for grande
MODEL_WEIGHTS = "yolov8s.pt" 

EPOCHS = 100         # Para datasets grandes, 50-100 é um bom começo
IMG_SIZE = 640       # 640 é padrão. Se quiser detectar pessoas muito longe, tente 1280 (mas vai pesar na GPU)

def train_model():
    # Verifica GPU
    device = 0 if torch.cuda.is_available() else "cpu"
    print(f"🚀 Iniciando treinamento no dispositivo: {torch.cuda.get_device_name(0) if device == 0 else 'CPU'}")

    # Carrega o modelo pré-treinado na COCO (transfer learning base)
    model = YOLO(MODEL_WEIGHTS)

    # Inicia o treinamento
    results = model.train(
        data=DATA_YAML,
        epochs=EPOCHS,
        imgsz=IMG_SIZE,
        batch=-1,        # AutoBatch: define automaticamente baseada na VRAM da RTX 2060
        device=device,
        project=PROJECT_NAME,
        name=RUN_NAME,
        cfg=HYP_YAML,    # Seus hiperparâmetros personalizados
        patience=15,     # Para se o modelo parar de aprender por 15 épocas
        save=True,       # Salva os checkpoints
        exist_ok=True,   # Sobrescreve se a pasta já existir
        verbose=True,
        # Otimizações de sistema
        workers=8,       # Ajuste conforme seu processador (número de threads)
        cache=False      # False para economizar RAM (se tiver >32GB RAM, pode por True)
    )

    print("✅ Treinamento concluído!")
    print(f"Melhor modelo salvo em: {PROJECT_NAME}/{RUN_NAME}/weights/best.pt")

if __name__ == '__main__':
    # Fix para Windows (multiprocessing)
    train_model()