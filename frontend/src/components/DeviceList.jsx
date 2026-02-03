import React, { useState, useEffect, useRef } from 'react';
import api, { getDeviceSnapshot, updateDeviceAdvanced, configureDevice, getDeviceLiveStats } from '../services/api';
import './DeviceList.css';

const API_BASE = 'http://localhost:8000';

const DrawingCanvas = ({ imageUrl, entrantPoints, setEntrantPoints, passerbyPoints, setPasserbyPoints, activeLine, inSide }) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    
    const drawLine = (ctx, points, color, label) => {
        if (points.length === 0) return;
        ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.fillStyle = color;
        ctx.beginPath();
        points.forEach((p, i) => { i===0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y); ctx.fillRect(p.x-3, p.y-3, 6, 6); });
        ctx.stroke();

        if (points.length >= 2) {
            const mid = Math.floor(points.length/2);
            const p1 = points[mid-1]||points[0]; const p2 = points[mid];
            const mx = (p1.x+p2.x)/2; const my = (p1.y+p2.y)/2;
            ctx.font = 'bold 16px Arial'; ctx.fillStyle = 'white';
            ctx.fillText(label, mx+10, my-10);
            if (label === "Entrantes") {
                const dx = p2.x-p1.x; const dy = p2.y-p1.y;
                // Vetor normal
                const norm = {x: -dy, y: dx}; const len = Math.sqrt(norm.x**2+norm.y**2)||1;
                const un = {x: norm.x/len, y: norm.y/len};
                const t1 = {x: mx+un.x*30, y: my+un.y*30}; 
                const t2 = {x: mx-un.x*30, y: my-un.y*30};
                ctx.fillText(inSide==='right'?"IN":"OUT", t1.x, t1.y);
                ctx.fillText(inSide==='right'?"OUT":"IN", t2.x, t2.y);
            }
        }
    };

    useEffect(() => {
        const cvs = canvasRef.current; if(!cvs) return;
        const ctx = cvs.getContext('2d');
        const img = containerRef.current.querySelector('img');
        if(img && img.complete) {
            cvs.width = img.width; cvs.height = img.height;
            ctx.clearRect(0,0,cvs.width,cvs.height);
            drawLine(ctx, entrantPoints, '#00ff00', "Entrantes");
            drawLine(ctx, passerbyPoints, '#ffff00', "Passantes");
        }
    }, [entrantPoints, passerbyPoints, activeLine, imageUrl, inSide]);

    const handleClick = (e) => {
        const rect = canvasRef.current.getBoundingClientRect();
        const pt = {x: e.clientX-rect.left, y: e.clientY-rect.top};
        activeLine === 'entrant' ? setEntrantPoints([...entrantPoints, pt]) : setPasserbyPoints([...passerbyPoints, pt]);
    };

    return (
        <div ref={containerRef} className="drawing-container">
            <img src={imageUrl} alt="Snapshot" onLoad={() => {
                const cvs = canvasRef.current;
                if(cvs) cvs.width = cvs.width; // Hack para redraw
            }}/>
            <canvas ref={canvasRef} onClick={handleClick} />
        </div>
    );
};

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

 // ESTADOS PARA CONFIGURAÇÃO AVANÇADA
    const [configDevice, setConfigDevice] = useState(null); 
    const [snapshotUrl, setSnapshotUrl] = useState(null);
    const [entrantPoints, setEntrantPoints] = useState([]);
    const [passerbyPoints, setPasserbyPoints] = useState([]);
    const [activeLine, setActiveLine] = useState('entrant');
    const [inSide, setInSide] = useState('right');
    const [schedule, setSchedule] = useState({ start: "08:00", end: "18:00" });
    // ESTADO PARA MONITORAMENTO (STATS)
    const [statsDevice, setStatsDevice] = useState(null);
    const [liveStats, setLiveStats] = useState(null);
    const statsIntervalRef = useRef(null);

    const handleOpenStats = (device) => {
        setStatsDevice(device);
        setLiveStats(null); // Limpa dados antigos
        fetchStats(device.id); // Busca imediatamente
        
        // Inicia Polling a cada 2 segundos
        if (statsIntervalRef.current) clearInterval(statsIntervalRef.current);
        statsIntervalRef.current = setInterval(() => fetchStats(device.id), 2000);
    };

    const handleCloseStats = () => {
        setStatsDevice(null);
        if (statsIntervalRef.current) clearInterval(statsIntervalRef.current);
    };

    const fetchStats = async (id) => {
        try {
            const data = await getDeviceLiveStats(id);
            setLiveStats(data);
        } catch (error) {
            console.error("Erro ao buscar stats", error);
        }
    };
    
    // Limpa intervalo ao desmontar componente
    useEffect(() => {
        return () => {
            if (statsIntervalRef.current) clearInterval(statsIntervalRef.current);
        };
    }, []);

    // Função para abrir o modal de configuração
    const handleOpenConfig = async (device) => {
        try {
            // 1. Pega snapshot
            const res = await getDeviceSnapshot(device.id);
            setSnapshotUrl(`${API_BASE}${res.url}`);
            
            // 2. Carrega configurações existentes se houver
            if (device.lines_config) {
                const cfg = device.lines_config; 
                setEntrantPoints(cfg.entrant || []);
                setPasserbyPoints(cfg.passerby || []);
                setInSide(cfg.in_side || 'right');
            } else {
                setEntrantPoints([]);
                setPasserbyPoints([]);
            }

            if (device.processing_start_time) {
                setSchedule({ 
                    start: device.processing_start_time, 
                    end: device.processing_end_time 
                });
            }

            setConfigDevice(device);
        } catch (error) {
            console.error(error);
            alert("Erro ao carregar snapshot. A câmera está online?");
        }
    };

    const handleSaveConfig = async () => {
        if (!configDevice) return;
        
        const linesConfig = {
            entrant: entrantPoints,
            passerby: passerbyPoints,
            in_side: inSide
        };

        const payload = {
            name: configDevice.name,
            username: configDevice.username,
            password: configDevice.password,
            manufacturer: configDevice.manufacturer,
            processing_start_time: schedule.start,
            processing_end_time: schedule.end,
            lines_config: linesConfig
        };

        try {
            await updateDeviceAdvanced(configDevice.id, payload);
            alert("Configuração salva com sucesso!");
            setConfigDevice(null);
            loadSavedDevices(); 
        } catch (error) {
            console.error(error);
            alert("Erro ao salvar configuração.");
        }
    };

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
                                {/* Botão MONITORAR (Azul) */}
                                <button 
                                    onClick={() => handleOpenStats(dev)}
                                    style={{marginLeft: '5px', background: '#17a2b8', border:'none', padding:'5px 10px', borderRadius:'4px', cursor:'pointer', color:'#fff'}}
                                >
                                    📊 Monitorar
                                </button>

                                <button 
                                    className="btn-config" 
                                    onClick={() => handleOpenConfig(dev)} 
                                    style={{marginLeft: '5px', background: '#e0a800', border:'none', padding:'5px 10px', borderRadius:'4px', cursor:'pointer', color:'#fff'}}
                                >
                                    ⚙️ Config
                                </button>
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

            {/* MODAL DE CONFIGURAÇÃO AVANÇADA */}
            {configDevice && snapshotUrl && (
                <div className="modal-overlay">
                    <div className="modal-content config-modal" style={{width: '900px', maxWidth: '95%'}}>
                        <h3>Configurar: {configDevice.name}</h3>
                        
                        <div className="config-grid" style={{display:'flex', gap:'20px', flexWrap:'wrap'}}>
                            <div className="config-visual" style={{flex: 2, minWidth: '300px'}}>
                                <h4>1. Desenhe as Linhas</h4>
                                <div className="drawing-buttons">
                                    <button style={{background: activeLine==='entrant'?'#00cc00':'#555'}} onClick={()=>setActiveLine('entrant')}>Linha Entrada (Verde)</button>
                                    <button style={{background: activeLine==='passerby'?'#cccc00':'#555'}} onClick={()=>setActiveLine('passerby')}>Linha Passagem (Amarelo)</button>
                                    <button onClick={()=>activeLine==='entrant'?setEntrantPoints([]):setPasserbyPoints([])}>Limpar</button>
                                    <button onClick={()=>setInSide(inSide==='right'?'left':'right')}>Inverter Lado</button>
                                </div>
                                <DrawingCanvas 
                                    imageUrl={snapshotUrl} 
                                    entrantPoints={entrantPoints} 
                                    setEntrantPoints={setEntrantPoints} 
                                    passerbyPoints={passerbyPoints} 
                                    setPasserbyPoints={setPasserbyPoints} 
                                    activeLine={activeLine} 
                                    inSide={inSide}
                                />
                            </div>

                            <div className="config-form" style={{flex: 1, minWidth: '250px'}}>
                                <h4>2. Agendamento</h4>
                                <p>Defina o horário de funcionamento da IA para esta câmera.</p>
                                <div className="form-group">
                                    <label>Início Processamento:</label>
                                    <input type="time" value={schedule.start} onChange={e => setSchedule({...schedule, start: e.target.value})} />
                                </div>
                                <div className="form-group">
                                    <label>Fim Processamento:</label>
                                    <input type="time" value={schedule.end} onChange={e => setSchedule({...schedule, end: e.target.value})} />
                                </div>
                                
                                <div className="modal-actions" style={{marginTop: '50px'}}>
                                    <button onClick={() => setConfigDevice(null)}>Cancelar</button>
                                    <button className="btn-connect" onClick={handleSaveConfig}>Salvar Configuração</button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* MODAL DE MONITORAMENTO (STATS) */}
            {statsDevice && (
                <div className="modal-overlay">
                    <div className="modal-content" style={{textAlign: 'center', minWidth: '400px'}}>
                        <h3>Monitoramento: {statsDevice.name}</h3>
                        <p style={{color: '#aaa', fontSize: '0.9em'}}>Atualização em tempo real (a cada 2s)</p>
                        
                        <div className="stats-box" style={{marginTop: '20px', display: 'flex', justifyContent: 'center', gap: '30px'}}>
                            {liveStats ? (
                                <>
                                    {liveStats.status === 'online' ? (
                                        <>
                                            <div style={{background: '#28a745', padding: '20px', borderRadius: '10px', minWidth: '120px'}}>
                                                <h1 style={{fontSize: '3em', margin: 0}}>{liveStats.data?.entrantes?.Total || 0}</h1>
                                                <span>Entrantes</span>
                                            </div>
                                            <div style={{background: '#ffc107', padding: '20px', borderRadius: '10px', minWidth: '120px', color: '#000'}}>
                                                <h1 style={{fontSize: '3em', margin: 0}}>{liveStats.data?.passantes?.Total || 0}</h1>
                                                <span>Passantes</span>
                                            </div>
                                        </>
                                    ) : (
                                        <div style={{padding: '20px', background: '#555', borderRadius: '8px', width: '100%'}}>
                                            <h4>Processamento Parado ou Offline</h4>
                                            <p>Aguardando horário agendado ou conexão.</p>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <p>Carregando dados...</p>
                            )}
                        </div>

                        {liveStats && liveStats.status === 'online' && (
                            <div style={{marginTop: '20px', padding: '10px', background: '#333', borderRadius: '5px'}}>
                                <p><strong>Última atualização do servidor:</strong> {liveStats.server_time}</p>
                                <p style={{fontSize: '0.8em', color: '#ccc'}}>Total Geral: {liveStats.data?.total_geral?.Total || 0}</p>
                            </div>
                        )}

                        <button onClick={handleCloseStats} style={{marginTop: '20px', padding: '10px 30px', background: '#666', border: 'none', color: '#fff', borderRadius: '5px', cursor: 'pointer'}}>
                            Fechar
                        </button>
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