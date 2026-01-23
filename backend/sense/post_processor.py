"""
Módulo para pós-processamento de tracks e correção de ID switches
"""

import numpy as np
from collections import defaultdict
from scipy.spatial.distance import cdist

class TrackPostProcessor:
    def __init__(self, window_size=10, spatial_threshold=50):
        """
        Args:
            window_size: Tamanho da janela temporal para análise
            spatial_threshold: Distância máxima para considerar tracks como o mesmo objeto
        """
        self.window_size = window_size
        self.spatial_threshold = spatial_threshold
        self.track_history = defaultdict(list)
        self.id_mapping = {}  # Mapeamento de IDs temporários para IDs corrigidos
        
    def process_frame_tracks(self, frame_tracks, frame_idx):
        """
        Processa tracks de um frame e aplica correções de ID
        
        Args:
            frame_tracks: Lista de dicionários com tracks do frame atual
            frame_idx: Índice do frame atual
            
        Returns:
            Lista de tracks corrigidos
        """
        if not frame_tracks:
            return frame_tracks
            
        # Atualiza histórico
        for track in frame_tracks:
            track_id = track["track_id"]
            center_x = (track["bbox"][0] + track["bbox"][2]) / 2
            center_y = (track["bbox"][1] + track["bbox"][3]) / 2
            
            self.track_history[track_id].append({
                "frame": frame_idx,
                "center": (center_x, center_y),
                "bbox": track["bbox"]
            })
            
            # Mantém apenas os últimos N pontos
            if len(self.track_history[track_id]) > self.window_size:
                self.track_history[track_id].pop(0)
        
        # Aplica correção de IDs
        corrected_tracks = self._correct_id_switches(frame_tracks, frame_idx)
        
        return corrected_tracks
    
    def _correct_id_switches(self, frame_tracks, frame_idx):
        """
        Corrige switches de ID baseado em trajetória espacial
        """
        if len(frame_tracks) < 2:
            return frame_tracks
            
        # Calcula centros atuais
        current_centers = []
        for track in frame_tracks:
            bbox = track["bbox"]
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            current_centers.append(center)
        
        # Para cada track, verifica continuidade com histórico
        corrected_tracks = []
        used_ids = set()
        
        for i, track in enumerate(frame_tracks):
            track_id = track["track_id"]
            
            # Se já temos histórico para este track
            if track_id in self.track_history and len(self.track_history[track_id]) > 1:
                # Pega a última posição conhecida (exceto a atual)
                history = self.track_history[track_id][:-1] if len(self.track_history[track_id]) > 1 else self.track_history[track_id]
                
                if history:
                    last_entry = history[-1]
                    last_center = last_entry["center"]
                    current_center = current_centers[i]
                    
                    # Calcula deslocamento
                    dx = current_center[0] - last_center[0]
                    dy = current_center[1] - last_center[1]
                    displacement = np.sqrt(dx*dx + dy*dy)
                    
                    # Se o deslocamento é muito grande para ser o mesmo objeto
                    if displacement > self.spatial_threshold * 3:
                        # Procura track mais próximo no frame anterior
                        best_match_id = self._find_best_match(track_id, current_center, used_ids)
                        
                        if best_match_id is not None and best_match_id != track_id:
                            # Corrige o ID
                            track["track_id"] = best_match_id
                            print(f"Corrigido ID switch: {track_id} -> {best_match_id} no frame {frame_idx}")
            
            # Garante IDs únicos no frame
            while track["track_id"] in used_ids:
                track["track_id"] += 1000  # Offset para evitar conflitos
            
            used_ids.add(track["track_id"])
            corrected_tracks.append(track)
        
        return corrected_tracks
    
    def _find_best_match(self, current_id, current_center, used_ids):
        """
        Encontra o melhor match para um track baseado em trajetória
        """
        best_match = None
        min_distance = float('inf')
        
        for track_id, history in self.track_history.items():
            if track_id == current_id or track_id in used_ids:
                continue
                
            if len(history) > 0:
                last_entry = history[-1]
                last_center = last_entry["center"]
                
                # Calcula distância
                dx = current_center[0] - last_center[0]
                dy = current_center[1] - last_center[1]
                distance = np.sqrt(dx*dx + dy*dy)
                
                # Considera velocidade razoável (pixels/frame)
                if distance < self.spatial_threshold and distance < min_distance:
                    min_distance = distance
                    best_match = track_id
        
        return best_match
    
    def reset(self):
        """Reseta o histórico"""
        self.track_history.clear()
        self.id_mapping.clear()