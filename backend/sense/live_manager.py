import asyncio
import cv2
import time
import os
import json
import requests
import traceback
from datetime import datetime
from sqlalchemy.orm import Session
from . import config, video_process, geometry
import crud, models
from database import SessionLocal

# Dicionário global para controlar tarefas ativas
active_tasks = {}
stop_signals = {} 

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
                if not dev.processing_start_time or not dev.processing_end_time or not dev.lines_config:
                    continue

                start = dev.processing_start_time
                end = dev.processing_end_time
                
                # Lógica simples de intervalo (mesmo dia)
                is_time = start <= current_time_str < end
                
                if is_time and dev.id not in active_tasks:
                    print(f"▶️ Iniciando processamento: {dev.name} ({dev.id})")
                    stop_event = asyncio.Event()
                    stop_signals[dev.id] = stop_event
                    
                    task = asyncio.create_task(
                        run_live_camera(dev.id, dev.rtsp_url, dev.lines_config, stop_event, processor_ref)
                    )
                    active_tasks[dev.id] = task

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

async def run_live_camera(device_id, rtsp_url, lines_config, stop_event, processor_ref):
    """
    Conecta no stream via Go2RTC (estabilidade) e processa frames.
    """
    db = SessionLocal()
    video_id = f"live_{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
        # 1. Garante que o stream existe no Go2RTC
        stream_name = f"camera_{device_id}"
        go2rtc_api = "http://sense_go2rtc:1984/api/streams"
        try:
            requests.put(go2rtc_api, params={"src": rtsp_url, "name": stream_name}, timeout=5)
        except Exception as e:
            print(f"⚠️ Aviso: Não foi possível registrar no Go2RTC: {e}")

        # 2. Conecta no RTSP LOCAL do Go2RTC (Zero latência, H264/MJPEG compatível)
        local_rtsp = f"rtsp://sense_go2rtc:8554/{stream_name}"
        print(f"🔌 Conectando IA em: {local_rtsp}")

        # Inicializa registro no banco com contadores zerados
        initial_stats = {
            "total_geral": {"Total": 0}, 
            "entrantes": {"Person": 0, "Total": 0}, 
            "passantes": {"Person": 0, "Total": 0}
        }
        crud.create_user_video(db, 0, video_id, rtsp_url, "")
        # Força atualização imediata para o frontend não pegar JSON null
        crud.update_video_after_processing(db, video_id, None, None, initial_stats, "live_processing")
        # Força TCP para evitar corrupção de H.265 (Erro PPS/ref frames)
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        
        cap = cv2.VideoCapture(local_rtsp)

        cap = cv2.VideoCapture(local_rtsp)
        
        # Parse da config
        lc = lines_config if isinstance(lines_config, dict) else json.loads(lines_config)
        line_ent = lc.get('entrant', [])
        line_pass = lc.get('passerby', [])
        in_side = lc.get('in_side', 'right')

        track_states = {}
        counts = {"entrantes": {"Person": 0, "Total": 0}, "passantes": {"Person": 0, "Total": 0}}
        
        frame_count = 0
        last_save = time.time()
        
        # Loop de processamento
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print(f"⚠️ Stream {device_id} sem sinal. Reconectando...")
                cap.release()
                await asyncio.sleep(5)
                cap = cv2.VideoCapture(local_rtsp)
                continue

            frame_count += 1
            if frame_count % 3 != 0: continue # Processa 1 a cada 3 frames

            processor = processor_ref.get("processor")
            if not processor: break

            tracks = await asyncio.to_thread(processor.process_frame, frame)

            for t in tracks:
                tid = t["track_id"]
                bbox = t["bbox"]
                ref_point = (int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2))

                if tid not in track_states:
                    track_states[tid] = {'status': 'neutral', 'last_ent_side': 'unknown', 'last_pass_side': 'unknown'}

                state = track_states[tid]

                # Lógica Passante
                curr_pass = geometry.get_point_side(ref_point, line_pass)
                if curr_pass != 'on_line' and state['last_pass_side'] != 'unknown' and state['last_pass_side'] != curr_pass:
                    if state['status'] == 'neutral':
                        state['status'] = 'passerby'
                        counts['passantes']['Person'] += 1
                        counts['passantes']['Total'] += 1
                state['last_pass_side'] = curr_pass

                # Lógica Entrante
                curr_ent = geometry.get_point_side(ref_point, line_ent)
                entrant_out = 'left' if in_side == 'right' else 'right'
                
                if curr_ent != 'on_line' and state['last_ent_side'] == entrant_out and curr_ent == in_side:
                    if state['status'] == 'neutral':
                        state['status'] = 'entrant'
                        counts['entrantes']['Person'] += 1
                        counts['entrantes']['Total'] += 1
                    elif state['status'] == 'passerby': # Era passante e virou entrante
                        state['status'] = 'entrant'
                        counts['passantes']['Person'] -= 1
                        counts['passantes']['Total'] -= 1
                        counts['entrantes']['Person'] += 1
                        counts['entrantes']['Total'] += 1
                state['last_ent_side'] = curr_ent

            # Salva no banco a cada 2s (mais rápido para ver "real time")
            if time.time() - last_save > 2:
                total_geral = {"Total": counts['entrantes']['Total'] + counts['passantes']['Total']}
                final_res = {"total_geral": total_geral, "entrantes": counts['entrantes'], "passantes": counts['passantes']}
                
                # Usa nova sessão para evitar "PendingRollbackError" em threads longas
                try:
                    db_save = SessionLocal()
                    crud.update_video_after_processing(db_save, video_id, None, None, final_res, "live_processing")
                    db_save.close()
                except Exception as e:
                    print(f"Erro ao salvar stats: {e}")
                
                last_save = time.time()
            
            await asyncio.sleep(0.01)

        cap.release()
        crud.update_video_status(db, video_id, "done")
        print(f"✅ Processamento finalizado: {device_id}")

    except Exception as e:
        print(f"❌ Erro fatal thread {device_id}: {traceback.format_exc()}")
    finally:
        db.close()