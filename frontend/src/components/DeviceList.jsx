import React, { useState, useEffect, useRef } from 'react';
import api from '../services/api';
import './DeviceList.css';

const API_BASE = 'http://localhost:8000';

const DeviceList = () => {
    const [savedDevices, setSavedDevices] = useState([]);
    const [scannedIps, setScannedIps] = useState([]);
    const [isScanning, setIsScanning] = useState(false);
    const [isConnecting, setIsConnecting] = useState(false);
    
    // Estado para o formulário de conexão
    const [authData, setAuthData] = useState({ ip: '', username: 'admin', password: '', port: '554' });
    const [showAuthModal, setShowAuthModal] = useState(false);

    // Estado para visualização do stream
    const [viewingDevice, setViewingDevice] = useState(null);
    const [streamUrl, setStreamUrl] = useState(null);
    const videoRef = useRef(null); // Referência direta ao elemento de vídeo

    const handleViewStream = async (device) => {
        try {
            const res = await api.get(`/stream-camera/${device.id}`);
            const streamName = res.data.stream_name;
            
            // Usa stream.mp4 que é compatível com MSE (baixa latência)
            const go2rtcUrl = `http://${window.location.hostname}:1984/api/stream.mp4?src=${streamName}`;
            
            setStreamUrl(go2rtcUrl);
            setViewingDevice(device);
        } catch (error) {
            console.error("Erro ao iniciar stream", error);
            alert("Erro ao iniciar o stream. Verifique se o Go2RTC está rodando.");
        }
    };

    const closeStream = () => {
        setViewingDevice(null);
        setStreamUrl(null);
    };

    useEffect(() => {
        loadSavedDevices();
    }, []);

    const loadSavedDevices = async () => {
        try {
            const res = await api.get('/devices/');
            setSavedDevices(res.data);
        } catch (error) {
            console.error("Erro ao carregar dispositivos salvos", error);
        }
    };

    const handleScan = async () => {
        setIsScanning(true);
        setScannedIps([]);
        try {
            // Chama a nova rota de scan do backend
            const res = await api.get('/devices/scan');
            // Filtra IPs que já estão salvos
            const savedIps = savedDevices.map(d => d.ip_address);
            const newIps = res.data.filter(ip => !savedIps.includes(ip));
            setScannedIps(newIps);
            if (newIps.length === 0) alert("Nenhuma câmera nova encontrada (Verifique se estão na mesma rede).");
        } catch (error) {
            alert("Erro ao escanear rede.");
        } finally {
            setIsScanning(false);
        }
    };

    const openAuthModal = (ip) => {
        setAuthData({ ...authData, ip: ip });
        setShowAuthModal(true);
    };

    const handleConnect = async (e) => {
        e.preventDefault();
        setIsConnecting(true);
        try {
            // Chama a rota de autodiscover
            await api.post('/devices/autodiscover', {
                ip_address: authData.ip,
                username: authData.username,
                password: authData.password,
                port: authData.port
            });
            
            setShowAuthModal(false);
            setScannedIps(scannedIps.filter(ip => ip !== authData.ip)); // Remove da lista de escaneados
            loadSavedDevices(); // Recarrega lista de salvos
            alert("Câmera conectada com sucesso!");
        } catch (error) {
            alert("Falha ao conectar: Verifique a senha ou se a câmera suporta RTSP padrão.");
        } finally {
            setIsConnecting(false);
        }
    };

    const handleDelete = async (id) => {
        if(window.confirm("Remover esta câmera?")) {
            await api.delete(`/devices/${id}`);
            loadSavedDevices();
        }
    };


    return (
        <div className="device-manager">
            <h2>Gerenciamento de Câmeras Locais</h2>

            {/* SEÇÃO 1: CÂMERAS SALVAS */}
            <div className="saved-devices-section">
                <h3>Minhas Câmeras</h3>
                <div className="device-grid">
                    {savedDevices.map(dev => (
                        <div key={dev.id} className="device-card saved">
                            <div className="card-header">
                                <span className="status-dot online"></span>
                                <strong>{dev.name || dev.ip_address}</strong>
                            </div>
                            <p>{dev.manufacturer} (RTSP)</p>
                            <div className="card-actions">
                                <button className="btn-view" onClick={() => handleViewStream(dev)}>👁️ Visualizar</button>
                                <button className="btn-delete" onClick={() => handleDelete(dev.id)}>Remover</button>
                            </div>
                        </div>
                    ))}
                    {savedDevices.length === 0 && <p className="empty-msg">Nenhuma câmera salva.</p>}
                </div>
            </div>

            <hr />

            {/* SEÇÃO 2: ESCANEAR NOVA */}
            <div className="scan-section">
                <h3>Adicionar Nova Câmera</h3>
                <div className="scan-controls">
                    <button className="btn-scan" onClick={handleScan} disabled={isScanning}>
                        {isScanning ? 'Escaneando Rede...' : '🔍 Escanear Rede Local'}
                    </button>
                    <button className="btn-manual" onClick={() => openAuthModal('')}>+ Adicionar Manualmente</button>
                </div>

                {/* LISTA DE IPS ENCONTRADOS */}
                {scannedIps.length > 0 && (
                    <div className="found-ips-list">
                        <h4>Dispositivos Encontrados ({scannedIps.length})</h4>
                        <div className="ip-grid">
                            {scannedIps.map(ip => (
                                <div key={ip} className="ip-card">
                                    <span>📷 {ip}</span>
                                    <button onClick={() => openAuthModal(ip)}>Conectar</button>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>

            {/* MODAL DE CONEXÃO */}
            {showAuthModal && (
                <div className="modal-overlay">
                    <div className="modal-content">
                        <h3>Conectar Câmera</h3>
                        <p>IP: <strong>{authData.ip || 'Manual'}</strong></p>
                        
                        <form onSubmit={handleConnect}>
                            {!authData.ip && (
                                <div className="form-group">
                                    <label>IP da Câmera:</label>
                                    <input type="text" value={authData.ip} onChange={e => setAuthData({...authData, ip: e.target.value})} required placeholder="Ex: 192.168.0.105" />
                                </div>
                            )}
                            
                            <div className="form-group">
                                <label>Usuário (Câmera):</label>
                                <input type="text" value={authData.username} onChange={e => setAuthData({...authData, username: e.target.value})} required />
                            </div>

                            <div className="form-group">
                                <label>Senha (Câmera):</label>
                                <input type="password" value={authData.password} onChange={e => setAuthData({...authData, password: e.target.value})} required />
                            </div>

                            <div className="form-group">
                                <label>Porta (Padrão 554):</label>
                                <input type="number" value={authData.port} onChange={e => setAuthData({...authData, port: e.target.value})} />
                            </div>

                            <div className="modal-actions">
                                <button type="button" onClick={() => setShowAuthModal(false)} disabled={isConnecting}>Cancelar</button>
                                <button type="submit" className="btn-connect" disabled={isConnecting}>
                                    {isConnecting ? 'Testando Conexão...' : 'Conectar e Salvar'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* MODAL DE STREAMING (VISUALIZAÇÃO) */}
            {viewingDevice && (
                <div className="modal-overlay" onClick={closeStream}>
                    <div className="modal-content stream-modal" onClick={e => e.stopPropagation()}>
                        <div className="stream-header">
                            <h3>{viewingDevice.name}</h3>
                            <button className="close-btn" onClick={closeStream}>X</button>
                        </div>
                        <div className="stream-container">
                            {/* Player Otimizado para Autoplay e Buffer Inicial */}
                            {streamUrl ? (
                                <video 
                                    ref={videoRef}
                                    src={streamUrl}
                                    className="live-stream"
                                    controls 
                                    muted 
                                    playsInline
                                    preload="auto"
                                    // onCanPlay dispara quando o navegador já baixou frames suficientes para tocar
                                    onCanPlay={() => {
                                        if (videoRef.current) {
                                            const playPromise = videoRef.current.play();
                                            if (playPromise !== undefined) {
                                                playPromise.catch(error => {
                                                    console.log("Autoplay bloqueado pelo navegador (interaja com a página):", error);
                                                });
                                            }
                                        }
                                    }}
                                    onError={(e) => console.error("Erro no player de vídeo", e)}
                                />
                            ) : (
                                <p>Carregando stream...</p>
                            )}
                        </div>
                        <p className="stream-info">
                            Modo: MJPEG (Compatível com H.265/UDP Transcodificado)
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
};

export default DeviceList;