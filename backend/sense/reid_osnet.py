import torch
import torch.nn as nn
import torchvision.transforms as T
import torchreid
from PIL import Image
import cv2
import numpy as np
import os
import torch.nn.functional as F

class OSNetWrapper(nn.Module):
    def __init__(self, weights_path, device):
        super().__init__()
        self.device = device
        
        # Inicializa a arquitetura OSNet
        # num_classes é ignorado na inferência
        self.model = torchreid.models.build_model(
            name='osnet_x1_0', 
            num_classes=100, 
            loss='softmax',
            pretrained=False
        )
        
        # Carrega os pesos se o arquivo existir
        if os.path.exists(weights_path):
            try:
                torchreid.utils.load_pretrained_weights(self.model, weights_path)
                print(f"✅ [ReID] Pesos carregados: {weights_path}")
            except Exception as e:
                print(f"❌ [ReID] Erro ao carregar pesos: {e}")
        else:
            print(f"⚠️ [ReID] Arquivo de pesos não encontrado: {weights_path}")
            print("   -> Usando pesos aleatórios (o rastreamento será instável!)")

        self.model.to(device).eval()

        # Pré-processamento (Resize -> Tensor -> Normalize)
        self.transform = T.Compose([
            T.Resize((256, 128)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
        ])

    def forward(self, crops):
        """
        Processa os recortes (crops) e retorna os vetores de características.
        """
        # Se a lista estiver vazia, retorna array vazio compatível com BoT-SORT
        if not crops:
            return np.empty((0, 512))

        batch = []
        for crop in crops:
            # O BoT-SORT envia crops como numpy arrays (BGR)
            if isinstance(crop, np.ndarray):
                # Converte BGR (OpenCV) para RGB (PIL)
                img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                batch.append(self.transform(img))
            elif isinstance(crop, Image.Image):
                 batch.append(self.transform(crop))
            else:
                continue
            
        if not batch:
             return np.empty((0, 512))

        #print(f"DEBUG: Extraindo features de {len(batch)} objetos.")

        # Empilha e envia para GPU
        batch_tensor = torch.stack(batch).to(self.device)
        
        with torch.no_grad():
            features = self.model(batch_tensor)

        features = F.normalize(features, p=2, dim=1)

        # CORREÇÃO CRÍTICA 1: Traz de volta da GPU para CPU e converte para Numpy
        return features.cpu().numpy()

    def get_features(self, bboxes, img):
        """
        CORREÇÃO CRÍTICA 2: Função exigida pelo BoT-SORT.
        Recorta a imagem original usando as bboxes e chama o forward.
        """
        if bboxes is None or len(bboxes) == 0:
            return np.empty((0, 512))

        crops = []
        # img é um array numpy (frame do vídeo)
        img_h, img_w = img.shape[:2]

        for bbox in bboxes:
            # Garante coordenadas inteiras e dentro da imagem
            x1, y1, x2, y2 = map(int, bbox[:4])
            
            # Expande ligeiramente a bbox para contexto (melhora ReID)
            exp = 5  # pixels de expansão
            x1 = max(0, x1 - exp)
            y1 = max(0, y1 - exp)
            x2 = min(img_w, x2 + exp)
            y2 = min(img_h, y2 + exp)
            
            # Verifica tamanho mínimo (evita crops muito pequenos)
            if (x2 - x1) < 10 or (y2 - y1) < 20:
                continue
            
            # Recorta
            crop = img[y1:y2, x1:x2]
            
            # Evita crops vazios (causas de erro)
            if crop.size > 0:
                # Redimensiona mantendo aspecto para melhor performance do ReID
                h, w = crop.shape[:2]
                if h > 0 and w > 0:
                    aspect = w / h
                    target_h = 256
                    target_w = int(target_h * aspect)
                    
                    if target_w > 0:
                        crop = cv2.resize(crop, (target_w, target_h))
                        
                        # Padding para o tamanho esperado (128x256)
                        if target_w < 128:
                            pad_w = 128 - target_w
                            left = pad_w // 2
                            right = pad_w - left
                            crop = cv2.copyMakeBorder(crop, 0, 0, left, right, 
                                                     cv2.BORDER_CONSTANT, value=(0,0,0))
                        elif target_w > 128:
                            # Crop central se for muito largo
                            start = (target_w - 128) // 2
                            crop = crop[:, start:start+128]
                        
                        crops.append(crop)
            # Não adiciona placeholder - melhor ignorar crop ruim

        # Chama o forward que já trata a conversão para GPU->CPU->Numpy
        return self.forward(crops) if crops else np.empty((0, 512))