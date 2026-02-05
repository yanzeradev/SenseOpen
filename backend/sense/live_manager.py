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

# Filas para transmissão de vídeo processado (MJPEG)
monitor_queues = {} 

active_tasks = {}
stop_signals = {} 

def get_stream_resolution(rtsp_url):
    try:
        cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", rtsp_url]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        if output:
            w, h = map(int, output.split(','))
            return w, h
    except: pass
    try:
        cap = cv2.VideoCapture(rtsp_url)
        if cap.isOpened():
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            return w, h
    except: pass
    return 1920, 1080

async def scheduler_loop(processor_ref):
    print("⏰ Scheduler de Câmeras Iniciado (Modo Self-Healing).")
    while True:
        try:
            # 1. Limpeza de tarefas mortas (Self-Healing)
            for dev_id in list(active_tasks.keys()):
                task = active_tasks[dev_id]
                if task.done():
                    try:
                        exc = task.exception()
                        if exc:
                            print(f"⚠️ Tarefa da Câmera {dev_id} caiu com erro: {exc}")
                        else:
                            print(f"ℹ️ Tarefa da Câmera {dev_id} finalizou normalmente.")
                    except: pass
                    
                    if dev_id in active_tasks: del active_tasks[dev_id]
                    if dev_id in stop_signals: del stop_signals[dev_id]
                    if dev_id in monitor_queues: del monitor_queues[dev_id]
                    print(f"♻️ Câmera {dev_id} limpa da memória e pronta para reiniciar.")

            # 2. Verificação de Agendamento
            db = SessionLocal()
            devices = db.query(models.Device).filter(models.Device.is_configured == True).all()
            now = datetime.now()
            current_time_str = now.strftime("%H:%M")
            
            for dev in devices:
                if not dev.processing_start_time or not dev.processing_end_time or not dev.lines_config:
                    continue
                
                start, end = dev.processing_start_time, dev.processing_end_time
                is_time = start <= current_time_str < end
                
                # INICIAR
                if is_time and dev.id not in active_tasks:
                    print(f"▶️ Iniciando: {dev.name} ({current_time_str} dentro de {start}-{end})")
                    stop_event = asyncio.Event()
                    stop_signals[dev.id] = stop_event
                    
                    monitor_queues[dev.id] = asyncio.Queue(maxsize=2)
                    
                    task = asyncio.create_task(run_live_camera_ffmpeg(dev.id, dev.rtsp_url, dev.lines_config, stop_event, processor_ref))
                    active_tasks[dev.id] = task

                # PARAR
                elif not is_time and dev.id in active_tasks:
                    print(f"⏹️ Parando: {dev.name} (Fora do horário {start}-{end})")
                    stop_signals[dev.id].set()
                    try:
                        await asyncio.wait_for(active_tasks[dev.id], timeout=5.0)
                    except: pass
                    
                    if dev_id in active_tasks: del active_tasks[dev_id]
                    if dev_id in stop_signals: del stop_signals[dev_id]
                    if dev_id in monitor_queues: del monitor_queues[dev_id]

            db.close()
        except Exception as e:
            print(f"❌ Erro Crítico no Scheduler: {e}")
            traceback.print_exc()
        
        await asyncio.sleep(10)

def draw_visuals(frame, tracks, line_ent, line_pass, counts, fps):
    # Desenha Linhas
    if len(line_ent) > 1:
        pts = np.array(line_ent, np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], False, (0, 255, 0), 3)
        cv2.putText(frame, "Entrada", (int(line_ent[0][0]), int(line_ent[0][1])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    if len(line_pass) > 1:
        pts = np.array(line_pass, np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], False, (0, 255, 255), 3)
        cv2.putText(frame, "Passagem", (int(line_pass[0][0]), int(line_pass[0][1])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    # Desenha Tracks
    for t in tracks:
        bbox = t['bbox']
        tid = t['track_id']
        x1, y1, x2, y2 = map(int, bbox) 
        
        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 100, 0), 2)
        
        cx, cy = int((x1+x2)/2), int((y1+y2)/2)
        cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
        cv2.putText(frame, f"ID: {tid}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)

    # Painel
    cv2.rectangle(frame, (10, 10), (250, 130), (0, 0, 0), -1)
    cv2.putText(frame, f"Entrantes: {counts['entrantes']['Total']}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.putText(frame, f"Passantes: {counts['passantes']['Total']}", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.putText(frame, f"FPS: {fps:.1f}", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

    return frame

async def run_live_camera_ffmpeg(device_id, rtsp_url, lines_config, stop_event, processor_ref):
    db = SessionLocal()
    video_id = f"live_{device_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    process = None
    
    try:
        # Configuração Go2RTC
        stream_name = f"camera_{device_id}"
        go2rtc_api = "http://sense_go2rtc:1984/api/streams"
        try:
            requests.put(go2rtc_api, params={"src": rtsp_url, "name": stream_name}, timeout=5)
        except: pass

        local_rtsp = f"rtsp://sense_go2rtc:8554/{stream_name}"
        
        # Inicializa DB
        initial_stats = {"total_geral": {"Total": 0}, "entrantes": {"Person": 0, "Total": 0}, "passantes": {"Person": 0, "Total": 0}}
        crud.create_user_video(db, 0, video_id, rtsp_url, "")
        crud.update_video_after_processing(db, video_id, None, None, initial_stats, "live_processing")

        WIDTH, HEIGHT = get_stream_resolution(local_rtsp)
        FRAME_SIZE = WIDTH * HEIGHT * 3 

        print(f"🔌 Iniciando Processamento Visual: {local_rtsp}")

        command = ['ffmpeg', '-rtsp_transport', 'tcp', '-i', local_rtsp, '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-r', '15', '-an', '-sn', '-y', '-']
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)

        # Configs e LIMPEZA DOS PONTOS
        lc = lines_config if isinstance(lines_config, dict) else json.loads(lines_config)
        
        def clean_points(pts):
            cleaned = []
            if not pts: return []
            for p in pts:
                if isinstance(p, dict):
                    cleaned.append([int(p.get('x', 0)), int(p.get('y', 0))])
                elif isinstance(p, (list, tuple)):
                    cleaned.append([int(p[0]), int(p[1])])
            return cleaned

        line_ent = clean_points(lc.get('entrant', []))
        line_pass = clean_points(lc.get('passerby', []))
        in_side = lc.get('in_side', 'right')

        track_states = {}
        counts = {"entrantes": {"Person": 0, "Total": 0}, "passantes": {"Person": 0, "Total": 0}}
        
        frame_count = 0
        t0 = time.time()
        fps = 0
        last_save = time.time()
        
        while not stop_event.is_set():
            try:
                raw_frame = await asyncio.to_thread(process.stdout.read, FRAME_SIZE)
            except ValueError:
                break # Pipe fechado
            
            if len(raw_frame) != FRAME_SIZE:
                print(f"⚠️ Frame incompleto dev {device_id}. Reiniciando pipe...")
                process.terminate()
                await asyncio.sleep(2)
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
                continue

            # Frame bufferizado -> Numpy
            frame = np.frombuffer(raw_frame, np.uint8).reshape((HEIGHT, WIDTH, 3)).copy()

            frame_count += 1
            if time.time() - t0 > 1:
                fps = frame_count / (time.time() - t0)
                frame_count = 0
                t0 = time.time()

            # IA Processing (já roda em thread via to_thread dentro do scheduler, mas aqui chamamos direto)
            # Como estamos dentro de uma task async, o ideal é manter o processamento pesado também off-loaded se possível
            # Mas como `processor.process_frame` é CPU-bound, o ideal é:
            processor = processor_ref.get("processor")
            if not processor: break
            
            # Offload do processamento da IA para não bloquear o loop enquanto calcula
            tracks = await asyncio.to_thread(processor.process_frame, frame)

            # --- LÓGICA DE CONTAGEM ---
            for t in tracks:
                tid = t["track_id"]
                bbox = t["bbox"]
                # Ponto de Referência: Centro do BBox (Bolinha Vermelha)
                ref_point = (int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2))

                if tid not in track_states:
                    track_states[tid] = {
                        'status': 'neutral',  # neutral -> passerby -> entrant
                        'last_point': ref_point
                    }
                
                state = track_states[tid]
                prev_point = state['last_point']

                # Só processa se houve deslocamento
                if prev_point != ref_point:
                    
                    # 1. VERIFICAÇÃO PASSANTES (Qualquer sentido)
                    # Se cruzar qualquer segmento da linha de passantes, conta.
                    crossed_pass = False
                    for i in range(len(line_pass) - 1):
                        if geometry.segments_intersect(prev_point, ref_point, line_pass[i], line_pass[i+1]):
                            crossed_pass = True
                            break
                    
                    if crossed_pass:
                        # Se ainda não foi contado como passante (e não é entrante ainda)
                        if state['status'] == 'neutral':
                            state['status'] = 'passerby'
                            counts['passantes']['Person'] += 1
                            counts['passantes']['Total'] += 1

                    # 2. VERIFICAÇÃO ENTRANTES (Sentido OUT -> IN)
                    # Verifica se cruzou algum segmento da linha de entrada
                    for i in range(len(line_ent) - 1):
                        p_start = line_ent[i]
                        p_end = line_ent[i+1]
                        
                        if geometry.segments_intersect(prev_point, ref_point, p_start, p_end):
                            # Cruzou a linha física. Agora validamos a direção.
                            # Para ser entrante, o ponto ANTERIOR deve estar no lado 'OUT'.
                            # Se in_side='right', então out_side='left'.
                            
                            side_prev = geometry.get_side_of_segment(prev_point, p_start, p_end)
                            required_prev_side = 'left' if in_side == 'right' else 'right'

                            if side_prev == required_prev_side:
                                # Transição de Estado
                                if state['status'] == 'neutral':
                                    state['status'] = 'entrant'
                                    counts['entrantes']['Person'] += 1
                                    counts['entrantes']['Total'] += 1
                                    
                                elif state['status'] == 'passerby':
                                    # Correção da Dupla Contagem:
                                    # Se ele já era passante, removemos dele e jogamos para entrante
                                    state['status'] = 'entrant'
                                    counts['passantes']['Person'] -= 1
                                    counts['passantes']['Total'] -= 1
                                    counts['entrantes']['Person'] += 1
                                    counts['entrantes']['Total'] += 1
                                break # Já contou, sai do loop de segmentos

                # Atualiza ponto anterior para o próximo frame
                state['last_point'] = ref_point

            # --- DESENHO E STREAMING ---
            processed_frame = draw_visuals(frame, tracks, line_ent, line_pass, counts, fps)
            
            if device_id in monitor_queues:
                q = monitor_queues[device_id]
                if q.full():
                    try: q.get_nowait()
                    except: pass
                
                ret, buffer = cv2.imencode('.jpg', processed_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                if ret:
                    await q.put(buffer.tobytes())

            # DB Save - Otimizado com Context Manager para evitar Connection Leaks
            if time.time() - last_save > 2:
                total = {"Total": counts['entrantes']['Total'] + counts['passantes']['Total']}
                res = {"total_geral": total, "entrantes": counts['entrantes'], "passantes": counts['passantes']}
                try:
                    # Uso correto de context manager garante o fechamento da sessão mesmo com erro
                    with SessionLocal() as db_save:
                        crud.update_video_after_processing(db_save, video_id, None, None, res, "live_processing")
                except Exception as e:
                    print(f"Erro ao salvar stats live (ignorado): {e}")
                last_save = time.time()
            
            await asyncio.sleep(0.001)

    except Exception as e:
        print(f"❌ Erro fatal thread {device_id}: {traceback.format_exc()}")
    finally:
        if process: process.terminate()
        db.close()
        if device_id in monitor_queues: del monitor_queues[device_id]
        try:
            db_final = SessionLocal()
            crud.update_video_status(db_final, video_id, "done")
            db_final.close()
        except: pass
        print(f"✅ Finalizado: {device_id}")