# models.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from database import Base

# CLASSE USER REMOVIDA COMPLETAMENTE

class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    # Removido owner_id
    client_id = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=True)
    manufacturer = Column(String, nullable=True)
    ip_address = Column(String)
    port = Column(Integer, default=554)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    rtsp_url = Column(String, nullable=True)
    is_configured = Column(Boolean, default=False)
    processing_start_time = Column(String, nullable=True) # Ex: "08:00"
    processing_end_time = Column(String, nullable=True)   # Ex: "18:00"
    lines_config = Column(JSON, nullable=True)

class Video(Base):
    __tablename__ = "videos"

    id = Column(String, primary_key=True, index=True)
    # Removido user_id
    original_video_path = Column(String)
    first_frame_path = Column(String)
    processed_video_path = Column(String, nullable=True)
    report_path = Column(String, nullable=True)
    status = Column(String, default="pending") 
    results = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())