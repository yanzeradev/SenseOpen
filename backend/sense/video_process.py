import cv2
from ultralytics import YOLO
from boxmot import BotSort
import torch
import os 
import numpy as np

# Importações dos nossos módulos
from . import config
from .reid_osnet import OSNetWrapper 

class VideoProcessor:
    def __init__(self):
        print(f"--- Inicializando VideoProcessor no dispositivo: {config.DEVICE} ---")
        self.device = config.DEVICE
        self.class_names = config.CLASS_NAMES
        self.class_colors = config.CLASS_COLORS

        # 1. Carrega YOLO
        model_path = str(config.YOLO_MODEL_PATH)
        print(f"[YOLO] Carregando modelo de: {model_path}")
        
        # Verifica se é modelo acelerado (ONNX/TensorRT)
        self.is_accelerated = model_path.endswith('.onnx') or model_path.endswith('.engine')

        if self.is_accelerated:
            # Modelos exportados não aceitam .to(), o device é definido na inferência
            self.yolo_model = YOLO(model_path, task='detect')
            print(f"[YOLO] Modo Acelerado ativado ({model_path.split('.')[-1]}) 🚀")
        else:
            # Modelos .pt padrões precisam ser movidos para a GPU explicitamente
            self.yolo_model = YOLO(model_path).to(self.device)

        # Cache de features para tracking consistente
        self.feature_cache = {}  
        self.cache_size = 10     

        # 2. Configura caminho do ReID (OSNet)
        osnet_weights = config.REID_MODEL_PATH
        print(f"[ReID] Procurando pesos em: {osnet_weights}")

        # 3. Inicializa ReID
        self.reid_model = OSNetWrapper(
            weights_path=osnet_weights,
            device=self.device
        )

        # 4. Inicializa BoT-SORT
        print("[Tracker] Inicializando BoT-SORT...")
        self.tracker = BotSort(
            reid_weights=self.reid_model,
            device=self.device,
            half=True, 
            **config.TRACKER_CONFIG
        )
        print("✅ VideoProcessor pronto!")

    def process_frame(self, frame):
        # Define o dispositivo para inferência
        # Se for GPU (cuda:0), passamos o índice 0. Se for CPU, passamos 'cpu'.
        inference_device = 0 if self.device.type == 'cuda' else 'cpu'

        # Inferência YOLO
        # Usamos .predict() que funciona tanto para .pt quanto para .onnx/.engine
        results = self.yolo_model.predict(
            source=frame,
            verbose=False,
            conf=0.25,
            device=inference_device  # Obrigatório para ONNX/TRT
        )
        
        # Se não detectou nada, retorna vazio
        if len(results[0].boxes) == 0:
            self.tracker.update(np.empty((0, 6)), frame)
            self._clean_feature_cache()
            return []

        # Extrai caixas do YOLO
        detections = results[0].boxes.data.cpu().numpy()
        detections = self._filter_detections(detections, frame.shape)
        
        # Atualiza Tracker (BoT-SORT + ReID)
        tracks = self.tracker.update(detections, frame)
        
        # Atualiza cache de features
        self._update_feature_cache(tracks, frame)
        
        # Suavização
        if len(tracks) > 0:
            tracks = self._apply_temporal_smoothing(tracks)
        
        processed_data = []
        if len(tracks) > 0:
            for track in tracks:
                # Formato BoT-SORT: [x1, y1, x2, y2, id, conf, class_id]
                x1, y1, x2, y2 = map(int, track[:4])
                track_id = int(track[4])
                conf = float(track[5])
                cls_id = int(track[6])
                
                processed_data.append({
                    "bbox": [x1, y1, x2, y2],
                    "track_id": track_id,
                    "confidence": conf,
                    "class_id": cls_id,
                    "class_name": self.class_names.get(cls_id, f"Classe {cls_id}")
                })
        
        return processed_data

    def draw_tracks(self, frame, tracks_data):
        for data in tracks_data:
            x1, y1, x2, y2 = data["bbox"]
            cls_id = data["class_id"]
            label = f'{data["class_name"]} ID:{data["track_id"]}'
            
            color = self.class_colors.get(cls_id, (0, 255, 0))

            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
            cv2.rectangle(frame, (x1, y1 - h - 10), (x1 + w, y1), color, -1)
            cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            
        return frame

    def _filter_detections(self, detections, frame_shape):
        filtered = []
        img_h, img_w = frame_shape[:2]
        
        for det in detections:
            x1, y1, x2, y2, conf, cls = det[:6]
            w, h = x2 - x1, y2 - y1
            
            if w > 15 and h > 30:
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img_w, x2), min(img_h, y2)
                
                if x2 > x1 and y2 > y1:
                    filtered.append([x1, y1, x2, y2, conf, cls])
        
        return np.array(filtered) if filtered else np.empty((0, 6))
    
    def _update_feature_cache(self, tracks, frame):
        if len(tracks) == 0: return
            
        for track in tracks:
            track_id = int(track[4])
            x1, y1, x2, y2 = map(int, track[:4])
            
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 10: continue
            
            try:
                feature = self.reid_model.forward([crop])
                if len(feature) > 0:
                    feature = feature[0]
                    if track_id not in self.feature_cache:
                        self.feature_cache[track_id] = []
                    self.feature_cache[track_id].append(feature)
                    if len(self.feature_cache[track_id]) > self.cache_size:
                        self.feature_cache[track_id].pop(0)
            except Exception: continue
    
    def _clean_feature_cache(self):
        if hasattr(self.tracker, 'tracked_stracks'):
            current_ids = set(int(track.track_id) for track in self.tracker.tracked_stracks)
        else:
            current_ids = set(self.feature_cache.keys())
        
        for tid in list(self.feature_cache.keys()):
            if tid not in current_ids:
                del self.feature_cache[tid]
    
    def _apply_temporal_smoothing(self, tracks):
        if len(tracks) == 0: return tracks
        smoothed_tracks = []
        for track in tracks:
            track_id = int(track[4])
            if track_id in self.feature_cache:
                if len(self.feature_cache[track_id]) >= 1:
                    smoothed_tracks.append(track)
            else:
                smoothed_tracks.append(track)
        return smoothed_tracks if len(smoothed_tracks) > 0 else tracks