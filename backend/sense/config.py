import torch
import os

# --- CONFIGURAÇÃO DE CAMINHOS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, 'static')

# Subpastas
UPLOAD_DIR = os.path.join(STATIC_DIR, 'uploaded_videos')
OUTPUT_DIR = os.path.join(STATIC_DIR, 'output_videos')
FRAMES_DIR = os.path.join(STATIC_DIR, 'frames')
REPORTS_DIR = os.path.join(STATIC_DIR, 'reports')

# Cria diretórios se não existirem
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FRAMES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

# --- MODELOS DE IA (Caminhos Relativos) ---
# O usuário deve baixar os modelos e colocar na pasta 'sense' ou raiz
YOLO_MODEL_PATH = os.path.join(BASE_DIR, 'sense', 'model_coco_crowd.pt') 
REID_MODEL_PATH = os.path.join(BASE_DIR, 'sense', 'osnet_x1_0_imagenet.pth')

# --- DEVICE (GPU/CPU) ---
DEVICE = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')

# --- CONFIGURAÇÕES DO TRACKER (BoT-SORT) ---
TRACKER_CONFIG = {
    'track_high_thresh': 0.4,
    'track_low_thresh': 0.1,
    'new_track_thresh': 0.7,
    'track_buffer': 300,
    'match_thresh': 0.8,
    'appearance_thresh': 0.4,
    'with_reid': True,
    'proximity_thresh': 0.5,
    'appearance_weight': 0.6,
    'gmc_method': 'sparseOptFlow',
    'fuse_score': True,
    'fuse_first_associate': True,
}

# --- CLASSES ---
CLASS_NAMES = { 0: "Person" }
CLASS_COLORS = { 0: (0, 255, 0) }