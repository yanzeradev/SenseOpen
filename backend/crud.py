# crud.py

from sqlalchemy.orm import Session
import models, schemas
from typing import List, Optional


def create_user_video(db: Session, user_id: int, video_id: str, original_video_path: str, first_frame_path: str):
    db_video = models.Video(
        id=video_id,
        original_video_path=original_video_path,
        first_frame_path=first_frame_path,
        status="pending"
    )
    db.add(db_video)
    db.commit()
    db.refresh(db_video)
    return db_video

def report_found_devices(db: Session, user_id: int, devices: List[schemas.DeviceReport]):
    """
    Salva dispositivos reportados pelo instalador (Suporte a go2rtc local)
    """
    for dev_data in devices:
        # Verifica se já existe
        existing = db.query(models.Device).filter(
            models.Device.owner_id == user_id,
            models.Device.ip_address == dev_data.ip_address
        ).first()
        
        if not existing:

            # Criamos um objeto temporário para gerar o ID e garantir um client_id único
            db_device = models.Device(
                ip_address=dev_data.ip_address,
                port=dev_data.port,
                owner_id=user_id,
                manufacturer=dev_data.path, # Aqui guardamos o nome da stream (ex: cam1)
                is_configured=False
            )
            db.add(db_device)
            db.flush() # Gera o ID no banco sem commitar a transação ainda

            # O client_id agora é baseado no ID real do banco, 
            # garantindo que nunca haverá duplicata no Nginx (ex: client1_dev42)
            db_device.client_id = f"client{user_id}_dev{db_device.id}"

            db.add(db_device)
    db.commit()
    
def get_user_devices(db: Session, user_id: int):
    return db.query(models.Device).filter(models.Device.owner_id == user_id).all()

def update_device_config(db: Session, device_id: int, config: schemas.DeviceUpdate, rtsp_url: str):
    dev = db.query(models.Device).filter(models.Device.id == device_id).first()
    if dev:
        # Atualiza campos básicos apenas se fornecidos
        if config.name is not None:
            dev.name = config.name
        if config.username is not None:
            dev.username = config.username
        if config.password is not None:
            dev.password = config.password
        if config.manufacturer is not None:
            dev.manufacturer = config.manufacturer
            
        # Atualiza configurações de processamento se fornecidas
        if config.processing_start_time is not None:
            dev.processing_start_time = config.processing_start_time
        if config.processing_end_time is not None:
            dev.processing_end_time = config.processing_end_time
        if config.lines_config is not None:
            dev.lines_config = config.lines_config
            
        # RTSP URL sempre é recalculada/atualizada pelo endpoint chamador se necessário,
        # mas aqui mantemos a lógica original de atualizar se passado
        if rtsp_url:
            dev.rtsp_url = rtsp_url
            
        dev.is_configured = True
        if not dev.client_id:
            dev.client_id = f"client{dev.id}" # Simplificado ID
            
        db.commit()
        db.refresh(dev)
    return dev

def get_video(db: Session, video_id: str):
    return db.query(models.Video).filter(models.Video.id == video_id).first()

def get_user_videos(db: Session):
    return db.query(models.Video).order_by(models.Video.created_at.desc()).all()

def update_video_status(db: Session, video_id: str, status: str):
    db_video = get_video(db, video_id)
    if db_video:
        db_video.status = status
        db.commit()
        db.refresh(db_video)
    return db_video

def update_video_after_processing(db: Session, video_id: str, processed_path: str, report_path: str, results: dict, status: str):
    db_video = get_video(db, video_id)
    if db_video:
        db_video.processed_video_path = processed_path
        db_video.report_path = report_path
        db_video.results = results
        db_video.status = status
        db.commit()
        db.refresh(db_video)
    return db_video

# NOVA FUNÇÃO ABAIXO
def delete_video_by_id(db: Session, video: models.Video):
    db.delete(video)
    db.commit()
