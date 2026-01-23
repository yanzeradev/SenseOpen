import torch
import torchvision.transforms as T
from PIL import Image
import cv2
import numpy as np
import torch.nn.functional as F


from transreid.config import cfg
from transreid.model import make_model

class TransReIDWrapper(torch.nn.Module):
    def __init__(self, config_file, model_path, device):
        super().__init__()
        self.device = device

        if config_file:
            cfg.merge_from_file(config_file)
        
        cfg.defrost()
        cfg.MODEL.PRETRAIN_PATH = model_path
        cfg.MODEL.DEVICE = device.type
        cfg.INPUT.SIZE_TEST = [384, 128]
        cfg.MODEL.NAME = 'transformer'
        cfg.MODEL.TRANSFORMER_TYPE = 'vit_base_patch16_224_TransReID'
        cfg.freeze()

        self.model = make_model(cfg, num_class=1, camera_num=1, view_num=1)
        self.model.to(device).eval()
        self.init_smoothing()



        self.transform = T.Compose([
            T.Resize(cfg.INPUT.SIZE_TEST),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

        # ==============================
        # ReID SMOOTHING – memória por track
        # ==============================
        self.smooth_memory = {}  # track_id → embedding suavizado
        self.alpha = 0.3         # suavização (0.2–0.4 ideal)

        # --- MEMÓRIA para ReID smoothing ---
    def init_smoothing(self):
        self.track_memory = {}  # track_id -> feature
        self.momentum = 0.9     # EMA forte para suavizar

    # Retorna embedding suavizado usando EMA por track_id
    def get_smooth_feature(self, track_id, crop):
        # Extrai embedding cru
        feat = self.forward([crop])[0].numpy()

        # Primeira vez → salva direto
        if track_id not in self.track_memory:
            self.track_memory[track_id] = feat
            return feat

        # EMA smoothing
        old = self.track_memory[track_id]
        new = old * self.momentum + feat * (1 - self.momentum)

        self.track_memory[track_id] = new
        return new


    def forward(self, crops):
        """Processa lotes de crops de imagens JÁ RECORTADAS."""
        if not crops:
            return torch.empty((0, 384), device='cpu')

        batch = torch.stack([self.transform(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))) for crop in crops])
        
        with torch.no_grad():
            features = self.model(batch.to(self.device))

        features = F.normalize(features, p=2, dim=1)
        
        return features.cpu()

    def get_features(self, bboxes, img):
        """
        Recorta as imagens com base nas bboxes e extrai as features.
        Esta é a função que o BoT-SORT espera encontrar.
        """
        if bboxes is None or len(bboxes) == 0:
            return torch.empty(0, 384) 

        crops = []
        for bbox in bboxes:
            x1, y1, x2, y2 = map(int, bbox[:4])

            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
            
            h, w, _ = img.shape

            pad = 0.1  # aumenta o quadro em 10%

            bx1 = max(0, int(x1 - pad * (x2 - x1)))
            by1 = max(0, int(y1 - pad * (y2 - y1)))
            bx2 = min(w, int(x2 + pad * (x2 - x1)))
            by2 = min(h, int(y2 + pad * (y2 - y1)))

            crop = img[by1:by2, bx1:bx2]

            
            if crop.shape[0] > 0 and crop.shape[1] > 0:
                crops.append(crop)

        if not crops:
            return torch.empty(0, 384)

        return self.forward(crops)


    def get_embeddings(self, img, bboxes):
        """
        Método compatível com o BotSort.
        Recebe: 
            img -> frame BGR completo
            bboxes -> Nx4 array (x1, y1, x2, y2)
        Retorna:
            Nx384 numpy array
        """

        if bboxes is None or len(bboxes) == 0:
            return torch.empty((0, 384)).cpu().numpy()

        # Extrai features (tensor Nx384)
        feats = self.get_features(bboxes, img)

        # Converte para numpy
        return feats.detach().cpu().numpy()

        def get_smooth_feature(self, track_id, crop_img):
            """
            Suaviza embeddings para reduzir ID-switches.
            """
            # Extrai embedding bruto
            raw = self.forward([crop_img])[0].numpy()

            # Normaliza
            raw = raw / (np.linalg.norm(raw) + 1e-8)

            # Primeiro frame desse track
            if track_id not in self.smooth_memory:
                self.smooth_memory[track_id] = raw
                return raw

            prev = self.smooth_memory[track_id]

            # Exponential moving average
            smooth = self.alpha * raw + (1 - self.alpha) * prev
            smooth = smooth / (np.linalg.norm(smooth) + 1e-8)

            self.smooth_memory[track_id] = smooth
            return smooth


