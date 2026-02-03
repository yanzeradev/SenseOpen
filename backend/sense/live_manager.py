import asyncio
import cv2
import time
import os
import json
import uuid
import traceback
from datetime import datetime
from sqlalchemy.orm import Session
from . import config, video_process, geometry
import crud, models
from database import SessionLocal

# Dicionário global para controlar tarefas ativas: {device_id: Task}
active_tasks = {}
stop_signals = {} # {device_id: Event}

async def scheduler_loop(processor_ref):
    """
    Loop infinito que roda a cada 60s para verificar agendamentos.
    """
    print("⏰ Scheduler de Câmeras Iniciado.")
    while True:
        try:
            db = SessionLocal()
            devices = db.query(models.Device).filter(models.Device.is_configured == True).all()
            
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            
            for dev in devices:
                # Verifica se tem configuração válida de horário e linhas
                if not dev.processing_start_time or not dev.processing_end_time or not dev.lines_config:
                    continue

                # Lógica simplificada de intervalo (considerando mesmo dia)
                start = dev.processing_start_time
                end = dev.processing_end_time
                
                is_time = start <= current_time_str < end
                
                # INICIAR PROCESSAMENTO
                if is_time and dev.id not in active_tasks:
                    print(f"▶️ Iniciando processamento agendado: {dev.name} ({dev.id})")
                    stop_event = asyncio.Event()
                    stop_signals[dev.id] = stop_event
                    
                    # Cria task em background
                    task = asyncio.create_task(
                        run_live_camera(dev.id, dev.rtsp_url, dev.lines_config, stop_event, processor_ref)
                    )
                    active_tasks[dev.id] = task

                # PARAR PROCESSAMENTO
                elif not is_time and dev.id in active_tasks:
                    print(f"⏹️ Parando processamento (Horário fim): {dev.name}")
                    stop_signals[dev.id].set()
                    await active_tasks[dev.id]
                    del active_tasks[dev.id]
                    del stop_signals[dev.id]

            db.close()
        except Exception as e:
            print(f"❌ Erro no Scheduler: {e}")
        
        await asyncio.sleep(60) # Verifica a cada 1 minuto

async def run_live_camera(device_id, rtsp_url, lines_config, stop_event, processor_ref):
    """
    Conecta na câmera e processa frames em tempo real.
    """
    # Cria uma sessão de banco dedicada para esta thread
    db = SessionLocal()
    
    try:
        # Cria registro de Vídeo "Live" para histórico do dia
        video_id = f"live_{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Cria entrada no histórico (reaproveitando tabela Video)
        # Salva um placeholder no original_path pois é stream
        crud.create_user_video(db, 0, video_id, rtsp_url, "") 
        crud.update_video_status(db, video_id, "live_processing")

        cap = cv2.VideoCapture(rtsp_url)
        
        # Configurações das linhas
        lc = lines_config if isinstance(lines_config, dict) else json.loads(lines_config)
        line_ent = lc.get('entrant', [])
        line_pass = lc.get('passerby', [])
        in_side = lc.get('in_side', 'right') # default

        # Estado local
        track_states = {}
        counts = {"entrantes": {"Person": 0, "Total": 0}, "passantes": {"Person": 0, "Total": 0}}
        
        frame_count = 0
        last_save = time.time()

        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print(f"⚠️ Falha stream dev {device_id}. Tentando reconectar...")
                cap.release()
                await asyncio.sleep(5)
                cap = cv2.VideoCapture(rtsp_url)
                continue

            # Otimização: Processa 1 a cada 3 frames para aliviar CPU/GPU
            frame_count += 1
            if frame_count % 3 != 0:
                continue

            # Processamento IA (usa o processador global passado por referência)
            processor = processor_ref.get("processor")
            if not processor:
                break

            # Roda detecção e tracking
            tracks = await asyncio.to_thread(processor.process_frame, frame)

            # Lógica de Contagem (Simplificada do main.py)
            for t in tracks:
                tid = t["track_id"]
                bbox = t["bbox"]
                
                # Centro do BBox
                ref_point = (int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2))

                if tid not in track_states:
                    track_states[tid] = {'status': 'neutral', 'last_ent_side': 'unknown', 'last_pass_side': 'unknown'}

                state = track_states