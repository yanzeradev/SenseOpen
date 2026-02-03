import asyncio
import cv2
import time
import os
import json
import requests
import subprocess
import numpy as np
import traceback
from datetime import datetime
from sqlalchemy.orm import Session
from . import config, video_process, geometry
import crud, models
from database import SessionLocal

# Dicionário global para controlar tarefas ativas
active_tasks = {}
stop_signals = {} 

def get_stream_resolution(rtsp_url):
    """
    Descobre a resolução real do stream para configurar o buffer corretamente.
    """
    try:
        # Tenta via FFprobe (mais rápido/leve)
        cmd = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0",
            rtsp_url
        ]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if output:
            w, h = map(int, output.split(','))
            print(f"📏 Resolução detectada (FFprobe): {w}x{h}")
            return w, h
    except:
        pass

    try:
        # Fallback: Tenta via OpenCV
        cap = cv2.VideoCapture(rtsp_url)
        if cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            print(f"📏 Resolução detectada (OpenCV): {w}x{h}")
            return w, h
    except:
        pass
        
    print("⚠️ Não foi possível detectar resolução. Usando padrão 1920x1080.")
    return 1920, 1080

async def scheduler_loop(processor_ref):
    print("⏰ Scheduler de Câmeras Iniciado.")
    while True:
        try:
            db = SessionLocal()
            devices = db.query(models.Device).filter(models.Device.is_configured == True).all()
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            
            for dev in devices:
                if not dev.processing_start_time or not dev.processing_end_time or not dev.lines_config:
                    continue
                
                start = dev.processing_start_time
                end = dev.processing_end_time
                is_time = start <= current_time_str < end
                
                # INICIAR
                if is_time and dev.id not in active_tasks:
                    print(f"▶️ Iniciando processamento: {dev.name} ({dev.id})")
                    stop_event = asyncio.Event()
                    stop_signals[dev.id] = stop_event
                    
                    task = asyncio.create_task(
                        run_live_camera_ffmpeg(dev.id, dev.rtsp_url, dev.lines_config, stop_event, processor_ref)
                    )
                    active_tasks[dev.id] = task

                # PARAR
                elif not is_time and dev.id in active_tasks:
                    print(f"⏹️ Parando processamento (Horário): {dev.name}")
                    stop_signals[dev.id].set()
                    await active_tasks[dev.id]
                    del active_tasks[dev.id]
                    del stop_signals[dev.id]

            db.close()
        except Exception as e:
            print(f"❌ Erro no Scheduler: {e}")
            traceback.print_exc()
        
        await asyncio.sleep(60)

async def run_live_camera_ffmpeg(device_id, rtsp_url, lines_config, stop_event, processor_ref):
    db = SessionLocal()
    video_id = f"live_{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    process = None
    
    try:
        # 1. Registrar/Atualizar no Go2RTC
        stream_name = f"camera_{device_id}"
        go2rtc_api = "http://sense_go2rtc:1984/api/streams"
        try:
            requests.put(go2rtc_api, params={"src": rtsp_url, "name": stream_name}, timeout=5)
        except:
            pass

        # URL local TCP
        local_rtsp = f"rtsp://sense_go2rtc:8554/{stream_name}"
        
        # 2. Inicializa Banco
        initial_stats = {
            "total_geral": {"Total": 0}, 
            "entrantes": {"Person": 0, "Total": 0}, 
            "passantes": {"Person": 0, "Total": 0}
        }
        crud.create_user_video(db, 0, video_id, rtsp_url, "")
        crud.update_video_after_processing(db, video_id, None, None, initial_stats, "live_processing")

        # 3. Detecta Resolução REAL para alinhar com as linhas desenhadas
        WIDTH, HEIGHT = get_stream_resolution(local_rtsp)
        FRAME_SIZE = WIDTH * HEIGHT * 3 # BGR24

        print(f"🔌 Iniciando FFmpeg para {local_rtsp} [{WIDTH}x{HEIGHT}]")

        # 4. Comando FFmpeg (Sem redimensionamento forçado)
        command = [
            'ffmpeg',
            '-rtsp_transport', 'tcp',
            '-i', local_rtsp,
            '-f', 'rawvideo',
            '-pix_fmt', 'bgr24',
            '-r', '15',                 # 15 FPS
            '-an', '-sn',
            '-y', 
            '-'
        ]

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)

        # Parse config das linhas
        lc = lines_config if isinstance(lines_config, dict) else json.loads(lines_config)
        line_ent = lc.get('entrant', [])
        line_pass = lc.get('passerby', [])
        in_side = lc.get('in_side', 'right')

        track_states = {}
        counts = {"entrantes": {"Person": 0, "Total": 0}, "passantes": {"Person": 0, "Total": 0}}
        last_save = time.time()
        
        while not stop_event.is_set():
            # Leitura do buffer exato
            raw_frame = process.stdout.read(FRAME_SIZE)
            
            if len(raw_frame) != FRAME_SIZE:
                print(f"⚠️ Frame incompleto ou stream caiu. Reiniciando pipe...")
                process.terminate()
                await asyncio.sleep(2)
                # Recria processo
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
                continue

            # Converte para imagem OpenCV
            frame = np.frombuffer(raw_frame, np.uint8).reshape((HEIGHT, WIDTH, 3))

            # IA
            processor = processor_ref.get("processor")
            if not processor: break

            tracks = await asyncio.to_thread(processor.process_frame, frame)

            # --- DEBUG LOG (Para sabermos se o YOLO está vendo algo) ---
            if len(tracks) > 0:
                print(f"👀 Detecções: {len(tracks)} pessoas. (Coords ex: {tracks[0]['bbox'][0]:.0f},{tracks[0]['bbox'][1]:.0f})")

            # Lógica de Contagem
            for t in tracks:
                tid = t["track_id"]
                bbox = t["bbox"]
                ref_point = (int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2))

                if tid not in track_states:
                    track_states[tid] = {'status': 'neutral', 'last_ent_side': 'unknown', 'last_pass_side': 'unknown'}

                state = track_states[tid]
                
                # Passante
                curr_pass = geometry.get_point_side(ref_point, line_pass)
                if curr_pass != 'on_line' and state['last_pass_side'] != 'unknown' and state['last_pass_side'] != curr_pass:
                    if state['status'] == 'neutral':
                        state['status'] = 'passerby'
                        counts['passantes']['Person'] += 1
                        counts['passantes']['Total'] += 1
                        print(f"🚶 NOVO PASSANTE! Total: {counts['passantes']['Total']}")
                state['last_pass_side'] = curr_pass

                # Entrante
                curr_ent = geometry.get_point_side(ref_point, line_ent)
                entrant_out = 'left' if in_side == 'right' else 'right'
                
                if curr_ent != 'on_line' and state['last_ent_side'] == entrant_out and curr_ent == in_side:
                    if state['status'] == 'neutral':
                        state['status'] = 'entrant'
                        counts['entrantes']['Person'] += 1
                        counts['entrantes']['Total'] += 1
                        print(f"🚪 NOVO ENTRANTE! Total: {counts['entrantes']['Total']}")
                    elif state['status'] == 'passerby':
                        state['status'] = 'entrant'
                        counts['passantes']['Person'] -= 1
                        counts['passantes']['Total'] -= 1
                        counts['entrantes']['Person'] += 1
                        counts['entrantes']['Total'] += 1
                        print(f"🚪 PASSANTE VIROU ENTRANTE!")
                state['last_ent_side'] = curr_ent

            # Salvar no DB a cada 2s
            if time.time() - last_save > 2:
                total_geral = {"Total": counts['entrantes']['Total'] + counts['passantes']['Total']}
                final_res = {"total_geral": total_geral, "entrantes": counts['entrantes'], "passantes": counts['passantes']}
                try:
                    db_save = SessionLocal()
                    crud.update_video_after_processing(db_save, video_id, None, None, final_res, "live_processing")
                    db_save.close()
                except Exception as e:
                    print(f"Erro db stats: {e}")
                last_save = time.time()
            
            await asyncio.sleep(0.001)

    except Exception as e:
        print(f"❌ Erro fatal thread {device_id}: {traceback.format_exc()}")
    finally:
        if process:
            process.terminate()
        db.close()
        try:
            db_final = SessionLocal()
            crud.update_video_status(db_final, video_id, "done")
            db_final.close()
        except:
            pass
        print(f"✅ Processamento finalizado: {device_id}")