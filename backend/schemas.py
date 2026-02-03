# schemas.py

from pydantic import BaseModel, Field
from typing import Optional, List
import datetime

# --- User Schemas ---
class UserBase(BaseModel):
    username: str

class UserRegisterIP(BaseModel):
    """Usado pelo instalador para reportar o IP do Tailscale"""
    tailscale_ip: str

class UserCreate(UserBase):
    password: str = Field(..., min_length=4, max_length=72)

class User(UserBase):
    id: int
    tailscale_ip: Optional[str] = None
    
    class Config:
        from_attributes = True # Atualizado para Pydantic v2+

# --- Schemas para Dispositivos ---

class DeviceBase(BaseModel):
    ip_address: str
    port: int = 554

class DeviceReport(DeviceBase):
    """Usado pelo Instalador .exe para reportar dispositivos encontrados"""
    path: Optional[str] = None       # <--- NOVO: Recebe "cam1"
    original_ip: Optional[str] = None # <--- NOVO: Recebe "192.168.0.102"
    client_id: Optional[str] = None
    pass

class DeviceUpdate(BaseModel):
    """Usado pelo Frontend para configurar o fabricante e credenciais"""
    name: str
    username: str
    password: str
    manufacturer: str
    processing_start_time: Optional[str] = None
    processing_end_time: Optional[str] = None
    lines_config: Optional[dict] = None
    
class DeviceResponse(DeviceBase):
    id: int
    client_id: str | None = None
    name: str | None = None
    manufacturer: str | None = None
    is_configured: bool
    rtsp_url: str | None = None
    processing_start_time: Optional[str] = None
    processing_end_time: Optional[str] = None
    lines_config: Optional[dict] = None

    class Config:
        from_attributes = True

# --- Video Schemas ---
class VideoResponse(BaseModel):
    id: str
    status: str
    created_at: datetime.datetime
    first_frame_url: str
    processed_video_url: Optional[str] = None
    report_url: Optional[str] = None
    results: Optional[dict] = None

    class Config:
        from_attributes = True

# --- Token Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

    
class DeviceConnect(BaseModel):
    ip_address: str
    username: str
    password: str
    port: str = "554"

class DeviceScanResult(BaseModel):
    ip: str
    port: int
    is_saved: bool