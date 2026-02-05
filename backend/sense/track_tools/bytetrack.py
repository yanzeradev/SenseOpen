import cv2
from ultralytics import YOLO
# MUDANÇA 1: Importamos ByteTrack em vez de BotSort
from boxmot import ByteTrack
import torch
import os 
import numpy as np
import time

from . import config
# from .reid_osnet import OSNetWrapper  <-- NÃO PRECISA MAIS DISSO PARA BYTETRACK

class VideoProcessor:
    def __init__(self):
        print(f"--- Inicializando VideoProcessor (Modo Speed) no: {config.DEVICE} ---")
        self.device = config.DEVICE
        self.class_names = config.CLASS_NAMES
        self.class_colors = config.CLASS_COLORS

        # 1. Carrega YOLO
        print(f"[YOLO] Carregando modelo...")
        self.yolo_model = YOLO(config.YOLO_MODEL_PATH)
        
        # Aquecimento do YOLO (Warmup) - Roda uma vez para alocar memória na GPU
        print("[YOLO] Aquecendo GPU...")
        self.yolo_model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)

        # 2. Inicializa ByteTrack (O Rastreador mais rápido)
        # ByteTrack não usa ReID (pesos visuais), usa apenas matemática (Kalman Filter)
        print("[Tracker] Inicializando ByteTrack...")
        
        self.tracker = ByteTrack(
            track_thresh=0.4,  # Confiança mínima para iniciar um rastro
            match_thresh=0.8,  # Tolerância de movimento
            frame_rate=30,     # FPS esperado do vídeo
        )
        # Nota: ByteTrack não precisa de .to(device) da mesma forma que redes neurais
        
        print("✅ VideoProcessor pronto para alta performance!")

    def process_frame(self, frame):
        # Medição de tempo para debug (pode remover depois)
        t0 = time.time()

        # Detecção YOLO OTIMIZADA
        results = self.yolo_model.predict(frame, 
                                  imgsz=640, 
                                  conf=0.4,    # Filtrar confiáveis
                                  iou=0.5, 
                                  half=True,   # FP16 (Essencial para GPU)
                                  verbose=False,
                                  device=self.device)
        
        t1 = time.time() # Tempo do YOLO

        if len(results[0].boxes) == 0:
            self.tracker.update(np.empty((0, 6)), frame)
            return []

        # Extração das caixas
        # O ByteTrack espera: [x1, y1, x2, y2, conf, class_id]
        detections = results[0].boxes.data.cpu().numpy()
        
        # Atualiza Tracker
        tracks = self.tracker.update(detections, frame)
        
        t2 = time.time() # Tempo do Tracker

        processed_data = []
        if len(tracks) > 0:
            for track in tracks:
                # O ByteTrack retorna: [x1, y1, x2, y2, id, conf, class_id]
                coords = track[:4].astype(int)
                track_id = int(track[4])
                conf = float(track[5])
                cls_id = int(track[6])
                
                processed_data.append({
                    "bbox": coords.tolist(),
                    "track_id": track_id,
                    "confidence": conf,
                    "class_id": cls_id,
                    "class_name": self.class_names.get(cls_id, f"{cls_id}")
                })
        
        # Se quiser debug de performance no console, descomente:
        # print(f"YOLO: {(t1-t0)*1000:.1f}ms | Tracker: {(t2-t1)*1000:.1f}ms")
        
        return processed_data

    def draw_tracks(self, frame, tracks_data):
        for data in tracks_data:
            x1, y1, x2, y2 = data["bbox"]
            cls_id = data["class_id"]
            track_id = data["track_id"]
            
            # Cor baseada no ID para diferenciar visualmente (opcional) ou na classe
            color = self.class_colors.get(cls_id, (0, 255, 0))
            
            # Desenha caixa
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            # Label simplificado
            label = f"ID {track_id}"
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(frame, (x1, y1 - h - 5), (x1 + w, y1), color, -1)
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
        return frame