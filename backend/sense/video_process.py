import cv2
from ultralytics import YOLO
from boxmot import BotSort
import torch
import os 
import numpy as np

# Importações dos nossos módulos
from . import config
from .reid_osnet import OSNetWrapper 
#from .reid import TransReIDWrapper

class VideoProcessor:
    def __init__(self):
        print(f"--- Inicializando VideoProcessor no dispositivo: {config.DEVICE} ---")
        self.device = config.DEVICE
        self.class_names = config.CLASS_NAMES
        self.class_colors = config.CLASS_COLORS

        # 1. Carrega YOLO
        print(f"[YOLO] Carregando modelo de: {config.YOLO_MODEL_PATH}")
        self.yolo_model = YOLO(config.YOLO_MODEL_PATH).to(self.device)
        
        # Cache de features para tracking consistente
        self.feature_cache = {}  # {track_id: [feature1, feature2, ...]}
        self.cache_size = 10     # Número de features históricas por ID

        # 2. Configura caminho do ReID (OSNet)
        # Pega o diretório onde ESTE arquivo (video_process.py) está: .../sense
        current_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Constrói o caminho para: .../sense/log/osnet_custom/model.pth.tar-60
        # Ajuste o nome do arquivo se o seu treino salvou com outro nome (ex: model.pth.tar-50)
        osnet_weights = config.REID_MODEL_PATH
        
        print(f"[ReID] Procurando pesos em: {osnet_weights}")

        # 3. Inicializa ReID
        #self.reid_model = TransReIDWrapper(
        #    config_file=config.TRANSREID_CONFIG_FILE,
        #    model_path=config.TRANSREID_MODEL_PATH,
        #    device=self.device
        #)

        self.reid_model = OSNetWrapper(
            weights_path=osnet_weights,
            device=self.device
        )

        # 4. Inicializa BoT-SORT
        print("[Tracker] Inicializando BoT-SORT...")
        self.tracker = BotSort(
            reid_weights=self.reid_model, # Passa nosso wrapper corrigido
            device=self.device,
            half=True, 
            **config.TRACKER_CONFIG
        )
        print("✅ VideoProcessor pronto!")

    def process_frame(self, frame):
        # Detecção YOLO com confiança mínima
        results = self.yolo_model(frame, verbose=False, conf=0.25)
        
        # Se não detectou nada, retorna vazio para não quebrar o tracker
        if len(results[0].boxes) == 0:
            # Atualiza tracker com vazio para manter a coerência temporal
            self.tracker.update(np.empty((0, 6)), frame)
            # Limpa cache de tracks antigos
            self._clean_feature_cache()
            return []

        # Extrai caixas do YOLO com filtragem
        detections = results[0].boxes.data.cpu().numpy()
        detections = self._filter_detections(detections, frame.shape)
        
        # Atualiza Tracker
        # O BoT-SORT vai chamar reid_model.forward() internamente
        tracks = self.tracker.update(detections, frame)
        
        # Atualiza cache de features com os novos tracks
        self._update_feature_cache(tracks, frame)
        
        # Suavização temporal dos IDs (reduz switches)
        if len(tracks) > 0:
            tracks = self._apply_temporal_smoothing(tracks)
        
        processed_data = []
        if len(tracks) > 0:
            for track in tracks:
                # Formato BoT-SORT: [x1, y1, x2, y2, id, conf, class_id, ...]
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
        """Filtra detecções muito pequenas ou fora da imagem"""
        filtered = []
        img_h, img_w = frame_shape[:2]
        
        for det in detections:
            x1, y1, x2, y2, conf, cls = det[:6]
            w, h = x2 - x1, y2 - y1
            
            # Filtra por tamanho mínimo (ajuste conforme sua cena)
            if w > 15 and h > 30:   # Pessoas muito pequenas são ruidosas
                # Garante dentro dos limites
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img_w, x2), min(img_h, y2)
                
                if x2 > x1 and y2 > y1:  # Bbox válida
                    filtered.append([x1, y1, x2, y2, conf, cls])
        
        return np.array(filtered) if filtered else np.empty((0, 6))
    
    def _update_feature_cache(self, tracks, frame):
        """Armazena features históricas para cada track"""
        if len(tracks) == 0:
            return
            
        for track in tracks:
            track_id = int(track[4])
            x1, y1, x2, y2 = map(int, track[:4])
            
            # Recorta a região atual
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0 or crop.shape[0] < 20 or crop.shape[1] < 10:
                continue
            
            # Extrai feature usando o modelo ReID
            try:
                feature = self.reid_model.forward([crop])
                if len(feature) > 0:
                    feature = feature[0]  # Pega a primeira (e única) feature
                    
                    # Armazena no cache
                    if track_id not in self.feature_cache:
                        self.feature_cache[track_id] = []
                    
                    self.feature_cache[track_id].append(feature)
                    
                    # Mantém apenas as últimas N features
                    if len(self.feature_cache[track_id]) > self.cache_size:
                        self.feature_cache[track_id].pop(0)
            except Exception as e:
                # Ignora erros na extração de features
                continue
    
    def _clean_feature_cache(self):
        """Remove tracks antigos do cache"""
        if hasattr(self.tracker, 'tracked_stracks'):
            current_ids = set(int(track.track_id) for track in self.tracker.tracked_stracks)
        else:
            # Fallback: mantém cache por mais tempo
            current_ids = set(self.feature_cache.keys())
        
        # Remove IDs não mais ativos (mantém por alguns frames no buffer)
        max_age_frames = 30
        for tid in list(self.feature_cache.keys()):
            if tid not in current_ids:
                # Opcional: implementar aging do cache
                del self.feature_cache[tid]
    
    def _apply_temporal_smoothing(self, tracks):
        """Suavização temporal para IDs instáveis"""
        if len(tracks) == 0:
            return tracks
            
        smoothed_tracks = []
        
        for track in tracks:
            track_id = int(track[4])
            
            # Se o track tem histórico mínimo, considera válido
            if track_id in self.feature_cache:
                if len(self.feature_cache[track_id]) >= 1:
                    # Track estável - mantém
                    smoothed_tracks.append(track)
                else:
                    # Track muito novo - pode ser ruído
                    # Opcional: filtrar ou marcar como provisório
                    continue
            else:
                # Track sem cache ainda - mantém mas monitora
                smoothed_tracks.append(track)
        
        return smoothed_tracks if len(smoothed_tracks) > 0 else tracks
    
    def _is_valid_track(self, track_id, bbox):
        """Valida se o track é consistente (usado no draw_tracks se quiser filtrar)"""
        # Verifica se o track tem histórico mínimo
        if track_id in self.feature_cache:
            if len(self.feature_cache[track_id]) < 1:
                return False  # Track sem histórico
        
        # Verifica se a bbox tem tamanho razoável
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        
        # Filtra bboxes inválidas ou muito pequenas
        if w <= 0 or h <= 0 or w > 1000 or h > 1000:
            return False
            
        return w > 15 and h > 30