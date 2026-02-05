import os
import uuid
import shutil
import cv2
import asyncio
import json
import numpy as np
import pandas as pd
from datetime import timedelta, datetime
import ffmpeg
import json
import requests
from urllib.parse import urlparse, quote
import time
import socket
import ffmpeg
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, Depends, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from typing import Dict, List, Any
from collections import Counter
from pydantic import BaseModel
from sqlalchemy.orm import Session
from urllib.parse import quote

# Importações do projeto
from sense import config, video_process, geometry, live_manager
import crud, models, schemas
from database import engine, get_db
import subprocess
from typing import Dict, List, Any, Optional


ml_models = {}
processing_jobs: Dict[str, Dict[str, Any]] = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando o servidor...")
    try:
        # Carrega Modelos IA
        ml_models["processor"] = video_process.VideoProcessor()
        print("✅ VideoProcessor carregado.")
        
        # Inicia Scheduler em Background
        asyncio.create_task(live_manager.scheduler_loop(ml_models))
        
    except Exception as e:
        print(f"❌ Erro no VideoProcessor ou Scheduler: {e}")
        ml_models["processor"] = None
    yield
    ml_models.clear()
    print("Servidor desligado.")

app = FastAPI(title="SenseProduct API", lifespan=lifespan)
models.Base.metadata.create_all(bind=engine)
origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")

# --- Schemas Auxiliares ---
class ConnectionManager:
    def __init__(self): self.active_connections: Dict[str, WebSocket] = {}
    async def connect(self, websocket: WebSocket, client_id: str): await websocket.accept(); self.active_connections[client_id] = websocket
    def disconnect(self, client_id: str):
        if client_id in self.active_connections: del self.active_connections[client_id]
    async def _send_json(self, client_id: str, data: dict):
        if client_id in self.active_connections:
            try: await self.active_connections[client_id].send_text(json.dumps(data))
            except Exception: self.disconnect(client_id)
    async def send_progress(self, client_id: str, progress: float): await self._send_json(client_id, {"type": "progress", "value": progress})
    async def send_final_results(self, client_id: str, results: dict): await self._send_json(client_id, {"type": "results", "value": results})

manager = ConnectionManager()

class FrameDimensions(BaseModel): width: int; height: int
class ProcessRequest(BaseModel):
    video_id: str; client_id: str
    entrant_line_points: List[Dict[str, float]]; passerby_line_points: List[Dict[str, float]]
    frame_dimensions: FrameDimensions; in_side: str

# --- LÓGICA GEOMÉTRICA (Refatorada para sense/geometry.py) ---
# As funções get_point_side, get_closest_segment_side e bbox_intersects_line foram removidas daqui.

def draw_line_visuals(frame, line_points, color, label, in_side=None):
    if len(line_points) < 2: return
    for i in range(len(line_points) - 1):
        p1 = (int(line_points[i]['x']), int(line_points[i]['y']))
        p2 = (int(line_points[i+1]['x']), int(line_points[i+1]['y']))
        cv2.line(frame, p1, p2, color, 3)
    
    mid = len(line_points) // 2
    p1, p2 = line_points[mid-1], line_points[mid]
    mx, my = (p1['x']+p2['x'])/2, (p1['y']+p2['y'])/2
    
    if in_side: # Lógica Entrantes
        dx, dy = p2['x']-p1['x'], p2['y']-p1['y']
        norm = {'x': -dy, 'y': dx}; length = np.sqrt(norm['x']**2 + norm['y']**2) or 1
        un = {'x': norm['x']/length, 'y': norm['y']/length}
        t1 = (int(mx + un['x']*40), int(my + un['y']*40))
        t2 = (int(mx - un['x']*40), int(my - un['y']*40))
        cv2.putText(frame, "IN" if in_side=='right' else "OUT", t1, cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
        cv2.putText(frame, "OUT" if in_side=='right' else "IN", t2, cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    else: # Lógica Passantes
        cv2.putText(frame, label, (int(mx), int(my-10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

# --- CORE: Processamento de Vídeo ---
async def run_video_processing(video_id: str, line_ent_raw: list, line_pass_raw: list, client_id: str, dims: dict, in_side: str, db: Session):
    processor = ml_models.get("processor")
    job = processing_jobs.get(video_id)
    if not all([processor, job]): return

    crud.update_video_status(db, video_id, "processing")
    frame_queue, ready_event = job["queue"], job["ready_event"]
    video = crud.get_video(db, video_id)
    
    vid = cv2.VideoCapture(video.original_video_path)
    if not vid.isOpened(): ready_event.set(); await frame_queue.put(None); return
    
    fw = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH)); fh = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = vid.get(cv2.CAP_PROP_FPS); total = int(vid.get(cv2.CAP_PROP_FRAME_COUNT))
    
    # Escalar linhas
    sx = fw / dims['width'] if dims['width'] else 1; sy = fh / dims['height'] if dims['height'] else 1
    def sc(pts): return [{'x': int(p['x']*sx), 'y': int(p['y']*sy)} for p in pts]
    line_ent = sc(line_ent_raw); line_pass = sc(line_pass_raw)
    
    # Output - Tenta usar codec H.264 (avc1) se disponível, fallback para mp4v
    out_path = os.path.join(config.OUTPUT_DIR, f"{video_id}_processed.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(out_path, fourcc, fps, (fw, fh))
    if not out.isOpened(): # Fallback
        out = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (fw, fh))

    # --- ESTADO E CONTAGEM ---
    # track_states: 'neutral' | 'passerby' | 'entrant'
    track_states = {} 
    
    # Contadores (Apenas Entrantes e Passantes)
    count_entrant = 0
    count_passerby = 0
    
    # Removido: count_exit, current_occupancy, total_dwell_time_accumulated
    
    # Buffer para identificar gêneros
    track_classes = {} 

    entrant_out_side = 'left' if in_side == 'right' else 'right'
    
    ready_event.set()
    curr_frame = 0
    
    while True:
        ret, frame = vid.read()
        if not ret: break
        
        # Desenhar linhas
        draw_line_visuals(frame, line_ent, (0, 255, 0), "Entrantes", in_side)
        draw_line_visuals(frame, line_pass, (0, 255, 255), "Passantes")
        
        tracks = await asyncio.to_thread(processor.process_frame, frame)
        
        for t in tracks:
            tid = t["track_id"]; bbox = t["bbox"]; cls = t["class_id"]
            
            # Inicializa estado se novo ID
            if tid not in track_states:
                track_states[tid] = {
                    'status': 'neutral', 
                    'last_ent_side': 'unknown',
                    'last_pass_side': 'unknown' # Rastreia lado da linha de passantes
                }
                track_classes[tid] = []
            
            track_classes[tid].append(cls)
            state = track_states[tid]
            
            # --- PONTO DE REFERÊNCIA: CENTRO DO BBOX ---
            # Antes: Pé ((x1+x2)/2, y2)
            # Agora: Centro ((x1+x2)/2, (y1+y2)/2)
            ref_point = (int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2))

            # Desenha o ponto de referência para debug visual
            cv2.circle(frame, ref_point, 4, (0, 0, 255), -1)

            # -----------------------------------------------------------
            # 1. Checa Passante (Lógica: Cruzamento de Linha)
            # -----------------------------------------------------------
            curr_pass_side = geometry.get_point_side(ref_point, line_pass)

            if curr_pass_side != 'on_line':
                last_pass_side = state['last_pass_side']
                
                # Se mudou de lado (e o lado anterior era conhecido)
                if last_pass_side != 'unknown' and last_pass_side != curr_pass_side:
                    
                    # Só conta se ainda for neutro (prioridade para entrante se necessário, ou independente)
                    # Aqui assumo que se virou passante, conta.
                    if state['status'] == 'neutral':
                        state['status'] = 'passerby'
                        count_passerby += 1
                        cv2.rectangle(frame, (int(bbox[0]), int(bbox[1])), (int(bbox[2]), int(bbox[3])), (0, 255, 255), 4)
                        # Opcional: Feedback visual de "Cruzou Passante"

                # Atualiza o último lado conhecido
                state['last_pass_side'] = curr_pass_side

            # -----------------------------------------------------------
            # 2. Checa Entrante (Lógica: Cruzamento OUT -> IN)
            # -----------------------------------------------------------
            curr_ent_side = geometry.get_point_side(ref_point, line_ent)
            
            if curr_ent_side != 'on_line':
                last_ent_side = state['last_ent_side']
                
                # Detecta cruzamento válido (Entrada)
                if last_ent_side == entrant_out_side and curr_ent_side == in_side:
                    
                    if state['status'] == 'neutral':
                        state['status'] = 'entrant'
                        count_entrant += 1
                        cv2.circle(frame, ref_point, 20, (0, 255, 0), -1)
                        
                    elif state['status'] == 'passerby':
                        # Reclassificação: Era passante, mas entrou na loja
                        state['status'] = 'entrant'
                        count_passerby -= 1 # Remove dos passantes
                        count_entrant += 1  # Adiciona nos entrantes
                        cv2.circle(frame, ref_point, 20, (0, 255, 0), -1)
                        cv2.putText(frame, "TROCOU!", (int(bbox[0]), int(bbox[1]-20)), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,255), 2)

                # Atualiza o último lado conhecido
                state['last_ent_side'] = curr_ent_side

        annotated = processor.draw_tracks(frame, tracks)
        
        # Desenha placar no vídeo (Sem "Na Loja")
        cv2.putText(annotated, f"Entrantes: {count_entrant}", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3)
        cv2.putText(annotated, f"Passantes: {count_passerby}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
        
        out.write(annotated)
        
        ret_enc, buf = cv2.imencode('.jpg', annotated)
        if ret_enc: await frame_queue.put(buf.tobytes())
        
        curr_frame += 1
        if curr_frame % 15 == 0 and total > 0: await manager.send_progress(client_id, (curr_frame/total)*100)

    vid.release(); out.release()
    await frame_queue.put(None)

    final_entrantes = {"Person": 0}
    final_passantes = {"Person": 0}
    
    for tid, info in track_states.items():
        status_final = info['status']
        if status_final == 'neutral': continue
        
        # Como só tem 1 classe, não precisamos de lógica de votação complexa
        # Mas mantemos a estrutura caso volte a usar multiclasse no futuro
        c_list = track_classes.get(tid, [])
        if not c_list: 
            g = "Person" # Fallback
        else:
            # Pega a classe mais comum (será sempre 0="Person" neste caso)
            common = Counter(c_list).most_common(1)[0][0]
            g = config.CLASS_NAMES.get(common, "Person")
        
        if status_final == 'entrant':
            # Se a chave não existir (ex: ruído), usa fallback ou ignora
            if g in final_entrantes: 
                final_entrantes[g] += 1
            else:
                final_entrantes["Person"] += 1 # Garante contagem
                
        elif status_final == 'passerby':
            if g in final_passantes: 
                final_passantes[g] += 1
            else:
                final_passantes["Person"] += 1

    # Calcula totais
    final_entrantes['Total'] = sum(v for k, v in final_entrantes.items() if k != 'Total')
    final_passantes['Total'] = sum(v for k, v in final_passantes.items() if k != 'Total')
    
    total_geral = {
        "Person": final_entrantes.get("Person", 0) + final_passantes.get("Person", 0),
        "Total": final_entrantes['Total'] + final_passantes['Total']
    }

    # JSON Final Simplificado (Sem métricas de loja/ocupação)
    final_counts = {
        "total_geral": total_geral, 
        "entrantes": final_entrantes, 
        "passantes": final_passantes
    }
    
    # Gera Relatório
    report_path = os.path.join(config.REPORTS_DIR, f"{video_id}_report.xlsx")
    pd.DataFrame(final_counts).T.to_excel(report_path)
    
    video_url = f"/static/output_videos/{video_id}_processed.mp4"
    report_url = f"/static/reports/{video_id}_report.xlsx"
    
    crud.update_video_after_processing(db, video_id, out_path, report_url, final_counts, "done")
    await manager.send_final_results(client_id, {"counts": final_counts, "report_url": report_url})

@app.get("/devices/{device_id}/monitor_stream")
async def monitor_stream(device_id: int):
    """
    Stream MJPEG em tempo real do processamento da IA (Visual).
    """
    # Verifica se o dispositivo tem uma fila ativa no live_manager
    if device_id not in live_manager.monitor_queues:
        # Se não estiver rodando (fora do horário?), retorna erro ou imagem estática
        return Response(status_code=404, content="Monitoramento inativo ou câmera desligada.")

    async def frame_generator():
        q = live_manager.monitor_queues[device_id]
        while True:
            try:
                # Aguarda novo frame processado (timeout para não travar conexões mortas)
                frame_bytes = await asyncio.wait_for(q.get(), timeout=5.0)
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"Erro stream monitoring: {e}")
                break

    return StreamingResponse(frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")
    
@app.post("/upload-video/")
def upload_video(video_file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    NOTA DO ESPECIALISTA: Removido 'async' para evitar bloqueio do Event Loop.
    O FastAPI executará esta função síncrona (IO-bound) em uma thread separada (threadpool),
    permitindo que o servidor continue respondendo a outras requisições enquanto o arquivo é copiado.
    """
    vid_id = str(uuid.uuid4())
    v_path = os.path.join(config.UPLOAD_DIR, f"{vid_id}.mp4")
    f_path = os.path.join(config.FRAMES_DIR, f"{vid_id}_frame.jpg")
    
    # Operação bloqueante (IO de disco) segura agora que estamos em uma thread
    with open(v_path, "wb") as b: 
        shutil.copyfileobj(video_file.file, b)
        
    cap = cv2.VideoCapture(v_path); ret, frame = cap.read(); cap.release()
    if ret: cv2.imwrite(f_path, frame)
    
    # Passamos 0 como user_id (ignorado pelo CRUD no modelo novo)
    crud.create_user_video(db, 0, vid_id, v_path, f_path)
    return {"video_id": vid_id, "first_frame_url": f"/static/frames/{vid_id}_frame.jpg"}

@app.get("/video-stream/{video_id}")
async def video_stream(video_id: str):
    async def gen(vid_id):
        job = processing_jobs.get(vid_id)
        if not job: return
        await job["ready_event"].wait()
        while True:
            frame = await job["queue"].get()
            if frame is None: break
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        del processing_jobs[vid_id]
    return StreamingResponse(gen(video_id), media_type='multipart/x-mixed-replace; boundary=frame')

@app.websocket("/ws/progress/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: manager.disconnect(client_id)

@app.post("/process-video/")
async def process_video(req: ProcessRequest, bg: BackgroundTasks, db: Session = Depends(get_db)):
    if req.video_id in processing_jobs: raise HTTPException(409, "Já processando")
    processing_jobs[req.video_id] = {"queue": asyncio.Queue(), "ready_event": asyncio.Event()}
    bg.add_task(run_video_processing, req.video_id, req.entrant_line_points, req.passerby_line_points, req.client_id, req.frame_dimensions.dict(), req.in_side, next(get_db()))
    return {"stream_url": f"/video-stream/{req.video_id}", "download_url": f"/static/output_videos/{req.video_id}_processed.mp4"}

@app.get("/videos/me/", response_model=List[schemas.VideoResponse])
async def history(db: Session = Depends(get_db)):
    # crud.get_user_videos agora retorna todos os vídeos (sem filtro de ID)
    return [schemas.VideoResponse(id=v.id, status=v.status, created_at=v.created_at, first_frame_url=f"/static/frames/{v.id}_frame.jpg", processed_video_url=f"/static/output_videos/{v.id}_processed.mp4" if v.processed_video_path else None, report_url=f"/static/reports/{v.id}_report.xlsx" if v.report_path else None, results=v.results) for v in crud.get_user_videos(db)]

@app.delete("/videos/{video_id}", status_code=204)
async def delete_vid(video_id: str, db: Session = Depends(get_db)):
    v = crud.get_video(db, video_id)
    if not v: raise HTTPException(404)
    for p in [v.original_video_path, v.first_frame_path, v.processed_video_path, os.path.join(config.REPORTS_DIR, f"{video_id}_report.xlsx")]:
        if p and os.path.exists(p): os.remove(p)
    crud.delete_video_by_id(db, v)
    return Response(status_code=204)

@app.get("/download-video/{video_id}")
async def download_video_endpoint(video_id: str):
    """Rota dedicada para forçar o download do vídeo processado"""
    file_path = os.path.join(config.OUTPUT_DIR, f"{video_id}_processed.mp4")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Vídeo processado não encontrado")
    
    return FileResponse(
        path=file_path, 
        filename=f"SenseVision_{video_id}.mp4", # Nome que aparecerá pro usuário
        media_type='application/octet-stream'    # Força o navegador a baixar
    )

async def check_port(ip, port, timeout=0.5):
    """Verifica se uma porta está aberta (usado para achar câmeras)"""
    try:
        conn = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return ip
    except:
        return None

@app.get("/devices/scan", response_model=List[str])
async def scan_network():
    """
    Escaneia redes domésticas comuns (192.168.0.x e 1.x)
    pois o Docker no Windows não enxerga a rede do host diretamente.
    """
    print("🕵️ Iniciando varredura de rede...")
    
    # Lista de subredes para forçar a busca
    target_subnets = ['192.168.0.', '192.168.1.']
    
    # Tenta descobrir o IP do container também (caso esteja em Linux/Host mode)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1))
        local_ip = s.getsockname()[0]
        s.close()
        container_subnet = '.'.join(local_ip.split('.')[:-1]) + '.'
        
        # Só adiciona se não for uma das comuns já listadas e não for a rede interna do Docker (172.)
        if container_subnet not in target_subnets and not container_subnet.startswith('172.'):
            target_subnets.append(container_subnet)
    except Exception:
        pass

    tasks = []
    
    # Cria tarefas para varrer todos os IPs das subredes listadas
    for subnet in target_subnets:
        print(f"   -> Varrendo faixa: {subnet}1-254")
        for i in range(1, 255):
            ip = f"{subnet}{i}"
            # Timeout aumentado para 1.0s para evitar falhas na primeira tentativa
            tasks.append(check_port(ip, 554, timeout=1.0))
    
    # Executa as centenas de conexões em paralelo
    results = await asyncio.gather(*tasks)
    
    # Filtra apenas os que responderam (não nulos)
    found_ips = [ip for ip in results if ip is not None]
    
    print(f"✅ Dispositivos encontrados: {found_ips}")
    return found_ips

@app.post("/devices/autodiscover")
async def autodiscover_camera(dev: schemas.DeviceConnect, db: Session = Depends(get_db)):
    """
    Testa URLs RTSP. Se detectar Intelbras/Dahua, escaneia múltiplos canais (DVR/NVR).
    """
    print(f"🕵️ Testando conexão para {dev.ip_address} (Porta {dev.port})...")

    # 1. Prepara credenciais e timeout
    safe_user = quote(dev.username)
    safe_pass = quote(dev.password)
    
    # 2. Definição de Padrões
    # Lista de tuplas: (Nome, Path Template, Protocolo, É_Intelbras?)
    # O Template tem {ch} que será substituído por 1 no teste inicial
    patterns = [
        ('Yoosee/Onvif (UDP)', '/onvif1', 'udp', False),
        ('Yoosee/Onvif (TCP)', '/onvif1', 'tcp', False),
        
        # Padrão Intelbras/Dahua: Canal variavel {ch}
        ('Intelbras/Dahua (TCP)', '/cam/realmonitor?channel={ch}&subtype=0', 'tcp', True),
        ('Intelbras/Dahua (UDP)', '/cam/realmonitor?channel={ch}&subtype=0', 'udp', True),
        
        ('Hikvision', '/Streaming/Channels/{ch}01', 'tcp', False), # Hikvision geralmente é 101, 201...
        
        ('Yoosee Live', '/live/ch0', 'udp', False),
        ('Genérico', '/live', 'tcp', False),
    ]

    working_config = None
    saved_devices = []

    # 3. Teste Inicial (Canal 1 ou Padrão)
    for name, template, proto, is_multi_channel in patterns:
        # Substitui {ch} por 1 para o teste inicial
        path = template.format(ch=1)
        url = f"rtsp://{safe_user}:{safe_pass}@{dev.ip_address}:{dev.port}{path}"
        
        print(f"   👉 Tentando {name}...", end=" ")
        try:
            # Probe rápido
            await asyncio.to_thread(ffmpeg.probe, url, rtsp_transport=proto, timeout='10000000', analyzeduration='10000000')
            print("✅ SUCESSO!")
            working_config = (name, template, proto, is_multi_channel)
            break
        except ffmpeg.Error:
            print("❌ Falha")
            continue

    if not working_config:
        raise HTTPException(status_code=400, detail="Não foi possível conectar. Verifique credenciais ou rede.")

    name_found, template_found, proto_found, is_multi = working_config

    # 4. Função auxiliar para salvar no banco
    def save_device(channel_num, url_rtsp):
        # Verifica duplicidade por IP e URL
        existing = db.query(models.Device).filter(
            models.Device.ip_address == dev.ip_address,
            models.Device.rtsp_url == url_rtsp
        ).first()

        dev_name = f"Cam {dev.ip_address.split('.')[-1]}"
        if is_multi:
            dev_name += f" - Ch {channel_num}"

        if existing:
            existing.username = dev.username
            existing.password = dev.password
            existing.name = dev_name
            existing.is_configured = True
            existing.port = int(dev.port)
            db.commit()
            saved_devices.append(existing)
        else:
            new_dev = models.Device(
                ip_address=dev.ip_address,
                username=dev.username,
                password=dev.password,
                port=int(dev.port),
                rtsp_url=url_rtsp,
                is_configured=True,
                name=dev_name,
                manufacturer=name_found.split(' ')[0],
                client_id=f"cam_{str(uuid.uuid4())[:8]}"
            )
            db.add(new_dev)
            db.commit()
            saved_devices.append(new_dev)

    # 5. Salva o primeiro canal encontrado (Canal 1)
    url_ch1 = f"rtsp://{safe_user}:{safe_pass}@{dev.ip_address}:{dev.port}{template_found.format(ch=1)}"
    save_device(1, url_ch1)

    # 6. Se for Multi-Channel (Intelbras), escaneia canais 2-16
    if is_multi:
        print("🕵️ Dispositivo Multi-Canal detectado. Verificando canais 2 a 16...")
        
        async def check_channel(ch_num):
            path = template_found.format(ch=ch_num)
            url = f"rtsp://{safe_user}:{safe_pass}@{dev.ip_address}:{dev.port}{path}"
            try:
                # Timeout curto (2s) para scan rápido
                await asyncio.to_thread(ffmpeg.probe, url, rtsp_transport=proto_found, timeout='2000000', analyzeduration='2000000')
                return ch_num, url
            except:
                return None

        # Cria tarefas para canais 2 a 16
        tasks = [check_channel(ch) for ch in range(2, 17)]
        results = await asyncio.gather(*tasks)

        for res in results:
            if res:
                ch_num, url = res
                print(f"   ✅ Canal {ch_num} Ativo! Salvando...")
                save_device(ch_num, url)

    # Retorna o primeiro dispositivo (para manter compatibilidade com frontend) ou lista
    # Como o frontend não lê o retorno, retornar o primeiro objeto é seguro.
    return saved_devices[0]

@app.get("/devices/", response_model=List[schemas.DeviceResponse])
def read_devices(db: Session = Depends(get_db)):
    return db.query(models.Device).all()

@app.delete("/devices/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db)):
    dev = db.query(models.Device).filter(models.Device.id == device_id).first()
    if dev:
        db.delete(dev)
        db.commit()
    return {"ok": True}

@app.put("/devices/{device_id}/config")
def update_device_configuration(device_id: int, config_data: schemas.DeviceUpdate, db: Session = Depends(get_db)):
    """
    Atualiza configurações avançadas: Horários e Linhas de Contagem.
    """
    dev = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    
    # Atualiza usando a função do CRUD (certifique-se que o CRUD já suporta os novos campos)
    # Passamos a URL atual para manter a mesma
    crud.update_device_config(db, device_id, config_data, dev.rtsp_url)
    return {"status": "updated"}

@app.get("/devices/{device_id}/snapshot")
def get_device_snapshot(device_id: int, db: Session = Depends(get_db)):
    """
    Captura 1 frame solicitando diretamente ao Go2RTC (que lida bem com H.265).
    """
    dev = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    
    # URL interna do serviço Go2RTC (dentro da rede Docker)
    GO2RTC_API = "http://sense_go2rtc:1984/api"
    stream_name = f"camera_{dev.id}"
    
    os.makedirs(config.FRAMES_DIR, exist_ok=True)
    filename = f"snapshot_{device_id}_{int(time.time())}.jpg"
    filepath = os.path.join(config.FRAMES_DIR, filename)
    
    # 1. Garante que o stream está registrado no Go2RTC
    # (Mesmo que já esteja, o PUT atualiza ou confirma sem erro)
    try:
        print(f"📡 Registrando stream '{stream_name}' no Go2RTC...")
        requests.put(f"{GO2RTC_API}/streams", params={"src": dev.rtsp_url, "name": stream_name}, timeout=3)
    except Exception as e:
        print(f"⚠️ Erro ao registrar stream no Go2RTC: {e}")
        # Segue o fluxo, pois pode já existir

    # 2. Tenta pegar o snapshot (frame.jpeg)
    # Fazemos algumas tentativas pois se o stream estava parado, demora uns segundos para ter o frame
    success = False
    for attempt in range(5):
        try:
            print(f"📸 Solicitando frame ao Go2RTC (Tentativa {attempt+1}/5)...")
            res = requests.get(f"{GO2RTC_API}/frame.jpeg", params={"src": stream_name}, timeout=5)
            
            if res.status_code == 200:
                with open(filepath, "wb") as f:
                    f.write(res.content)
                success = True
                print("✅ Snapshot capturado com sucesso via Go2RTC.")
                break
            else:
                print(f"⏳ Go2RTC ainda não tem frame (Status {res.status_code}). Aguardando...")
                time.sleep(1.5) # Espera o buffer encher
        except Exception as e:
            print(f"❌ Erro na requisição ao Go2RTC: {e}")
            time.sleep(1)

    if not success:
        raise HTTPException(status_code=500, detail="Não foi possível obter snapshot do Go2RTC (Timeout/Codec)")

    return {"url": f"/static/frames/{filename}"}

@app.get("/devices/{device_id}/live_stats")
def get_device_live_stats(device_id: int, db: Session = Depends(get_db)):
    try:
        prefix = f"live_{device_id}_"
        latest_video = db.query(models.Video)\
            .filter(models.Video.id.like(f"{prefix}%"))\
            .order_by(models.Video.created_at.desc())\
            .first()

        if not latest_video:
            return {"status": "offline", "message": "Aguardando inicio..."}

        # Garante que data não seja None
        data = latest_video.results if latest_video.results else {}

        if latest_video.status != "live_processing":
            return {
                "status": "stopped", 
                "data": data,
                "last_update": str(latest_video.created_at)
            }

        return {
            "status": "online",
            "data": data,
            "server_time": datetime.now().strftime("%H:%M:%S")
        }
    except Exception as e:
        print(f"Erro em live_stats: {e}")
        # Retorna erro tratado 500 mas com JSON para não quebrar o frontend
        return {"status": "error", "message": str(e)}

@app.get("/stream-camera/{device_id}")
def stream_camera_feed(device_id: int, db: Session = Depends(get_db)):
    """
    Registra a câmera no serviço Go2RTC e retorna as informações para o Frontend conectar.
    """
    dev = db.query(models.Device).filter(models.Device.id == device_id).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")

    stream_name = f"camera_{dev.id}"
    
    # URL base da API do Go2RTC
    go2rtc_api_url = "http://sense_go2rtc:1984/api/streams"
    
    # Payload correto usando params (Deixa o 'requests' tratar a codificação de caracteres especiais)
    payload = {
        "src": dev.rtsp_url,
        "name": stream_name
    }

    try:
        # Usa requests.put com 'params' para garantir URL válida
        response = requests.put(go2rtc_api_url, params=payload)
        
        if response.status_code not in [200, 201]:
            # Se der erro 400, imprime o que o servidor respondeu para debug
            print(f"⚠️ Aviso: Go2RTC retornou {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Erro ao conectar no Go2RTC: {e}")
        pass

    # Retorna o nome do stream para o frontend montar a URL final
    return {"stream_name": stream_name}