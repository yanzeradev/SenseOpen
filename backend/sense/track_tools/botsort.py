import cv2
from ultralytics import YOLO
from boxmot import BotSort
import torch
import numpy as np
import time

from . import config
from .reid_osnet import OSNetWrapper

class VideoProcessor:
    def __init__(self):
        print(f"--- [BoT-SORT] Inicializando VideoProcessor no: {config.DEVICE} ---")
        self.device = config.DEVICE
        self.class_names = config.CLASS_NAMES
        self.class_colors = config.CLASS_COLORS

        # 1. Carrega YOLO Otimizado
        self.yolo_model = YOLO(config.YOLO_MODEL_PATH)
        
        # Aquecimento da GPU (Warmup)
        print("[YOLO] Aquecendo GPU...")
        self.yolo_model(np.zeros((640, 640, 3), dtype=np.uint8), verbose=False)

        # 2. Inicializa ReID (OSNet)
        print(f"[ReID] Carregando pesos: {config.REID_MODEL_PATH}")
        self.reid_model = OSNetWrapper(
            weights_path=config.REID_MODEL_PATH,
            device=self.device
        )

        # 3. Inicializa BoT-SORT (Versão Simplificada)
        print("[Tracker] Inicializando BoT-SORT...")
        self.tracker = BotSort(
            reid_weights=self.reid_model, # O tracker usa o ReID internamente
            device=self.device,
            half=True,                    # FP16 para performance
            track_high_thresh=0.45,        # Confiança para detecções boas
            new_track_thresh=0.6,         # Confiança para criar novo rastro
            match_thresh=0.7,             # IoU para associação
            track_buffer=90,
    
            # Proximidade (evita que IDs pulem entre pessoas muito próximas)
            proximity_thresh=0.5,
            appearance_thresh=0.25,
        )
        
        print("✅ VideoProcessor (BoT-SORT) pronto!")

    def process_frame(self, frame):
        # Detecção YOLO OTIMIZADA
        results = self.yolo_model(frame, 
                                  imgsz=640, 
                                  conf=0.4, 
                                  iou=0.5, 
                                  half=True, 
                                  verbose=False)
        
        if len(results[0].boxes) == 0:
            self.tracker.update(np.empty((0, 6)), frame)
            return []

        # O BoT-SORT espera: [x1, y1, x2, y2, conf, class_id]
        detections = results[0].boxes.data.cpu().numpy()
        
        # Atualiza Tracker (Associação por movimento + aparência visual)
        tracks = self.tracker.update(detections, frame)
        
        processed_data = []
        if len(tracks) > 0:
            for track in tracks:
                # Retorno: [x1, y1, x2, y2, id, conf, class_id]
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
        
        return processed_data

    def draw_tracks(self, frame, tracks_data):
        for data in tracks_data:
            x1, y1, x2, y2 = data["bbox"]
            cls_id = data["class_id"]
            track_id = data["track_id"]
            
            color = self.class_colors.get(cls_id, (0, 255, 0))
            label = f"{data['class_name']} ID {track_id}"
            
            # Desenha Bbox e Label
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(frame, (x1, y1 - h - 5), (x1 + w, y1), color, -1)
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
        return frame