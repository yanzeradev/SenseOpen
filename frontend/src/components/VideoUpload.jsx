// src/components/VideoUpload.jsx
import React, { useState, useRef, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import api from '../services/api';
import './VideoUpload.css';

const API_BASE = 'http://localhost:8000';

const CountBlock = ({ title, counts }) => {
    if (!counts) return null;
    return (
        <div className="stats-output">
            <h3>{title}</h3>
            <ul>
                <li className="total-count">Total: <strong>{counts.Total}</strong></li>
            </ul>
        </div>
    );
};

const AvgTimeBlock = ({ metrics }) => {
    if (!metrics) return null;
    return (
        <div className="stats-output stats-time">
            <h3>Tempo Médio de Permanência</h3>
            <div className="time-display">
                <span className="time-value">{metrics.tempo_medio_formatado}</span>
                <span className="time-label"> - (Hora:Minuto:Segundo)</span>
            </div>
            <ul className="time-details">
                <li>Saídas: <strong>{metrics.total_saidas}</strong></li>
                <li>Ocupação Final: <strong>{metrics.ocupacao_final}</strong></li>
            </ul>
        </div>
    );
};

const DrawingCanvas = ({ imageUrl, entrantPoints, setEntrantPoints, passerbyPoints, setPasserbyPoints, activeLine, onImageLoad, inSide }) => {
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
                const norm = {x: -dy, y: dx}; const len = Math.sqrt(norm.x**2+norm.y**2)||1;
                const un = {x: norm.x/len, y: norm.y/len};
                const t1 = {x: mx+un.x*30, y: my+un.y*30}; const t2 = {x: mx-un.x*30, y: my-un.y*30};
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
            <img src={imageUrl} onLoad={(e)=>{onImageLoad({width:e.target.width, height:e.target.height}); setEntrantPoints([...entrantPoints]);}} alt="" />
            <canvas ref={canvasRef} onClick={handleClick} />
        </div>
    );
};

const VideoUpload = ({ onProcessComplete }) => { 
    const [stage, setStage] = useState('initial');
    const [error, setError] = useState('');
    const [videoId, setVideoId] = useState(null);
    const [firstFrameUrl, setFirstFrameUrl] = useState(null);
    const [entrantPoints, setEntrantPoints] = useState([]);
    const [passerbyPoints, setPasserbyPoints] = useState([]);
    const [activeLine, setActiveLine] = useState('entrant');
    const [progress, setProgress] = useState(0);
    const [counts, setCounts] = useState(null);
    const [outputUrl, setOutputUrl] = useState(null); // URL relativa do vídeo final
    const [streamUrl, setStreamUrl] = useState(null);
    const [dims, setDims] = useState(null);
    const [inSide, setInSide] = useState('right');
    const [reportUrl, setReportUrl] = useState(null);
    const ws = useRef(null);

    const reset = () => { setStage('initial'); setVideoId(null); setEntrantPoints([]); setPasserbyPoints([]); setCounts(null); setOutputUrl(null); };

    const handleUpload = async (e) => {
        const file = e.target.files[0]; if(!file) return;
        setStage('uploading');
        const fd = new FormData(); fd.append('video_file', file);
        try {
            const token = localStorage.getItem('token');
            const res = await api.post('/upload-video/', fd, { headers: {'Content-Type': 'multipart/form-data', Authorization: `Bearer ${token}`} });
            setVideoId(res.data.video_id);
            setFirstFrameUrl(`${API_BASE}${res.data.first_frame_url}`);
            setStage('drawing');
        } catch { setError('Erro no upload'); setStage('initial'); }
    };

    const handleProcess = async () => {
        if(entrantPoints.length<2 || passerbyPoints.length<2) return alert("Desenhe AMBAS as linhas!");
        setStage('processing');
        const clientId = uuidv4();
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsHost = window.location.host;
        ws.current = new WebSocket(`ws://localhost:8000/ws/progress/${clientId}`);
        ws.current.onmessage = (e) => {
            const d = JSON.parse(e.data);
            if(d.type==='progress') setProgress(Math.round(d.value));
            if(d.type==='results') { 
                setCounts(d.value.counts); 
                setReportUrl(`${API_BASE}${d.value.report_url}`);
                ws.current.close(); 
                setStage('finished');
                
                // Atualiza o histórico assim que terminar
                if (onProcessComplete) onProcessComplete(); 
            }
        };
        try {
            const token = localStorage.getItem('token');
            const res = await api.post('/process-video/', {
                video_id: videoId, client_id: clientId,
                entrant_line_points: entrantPoints, passerby_line_points: passerbyPoints,
                frame_dimensions: dims, in_side: inSide
            }, { headers: {Authorization: `Bearer ${token}`} });
            setStreamUrl(`${API_BASE}${res.data.stream_url}`);
            setOutputUrl(`${API_BASE}${res.data.download_url}`);
        } catch { setError('Erro ao processar'); setStage('drawing'); }
    };

    const handleDownload = () => {
        if (!videoId) return;
        
        const API_BASE = 'http://localhost:8000';
        
        // Redireciona o navegador para a rota de download forçado
        // Como a resposta tem header "attachment", a página NÃO muda, o download apenas começa.
        window.location.href = `${API_BASE}/download-video/${videoId}`;
    };

    return (
        <div className="video-processor">
            {stage==='initial' && <div className="input-group"><label className="custom-file-upload"><input type="file" onChange={handleUpload}/>Carregar Vídeo</label></div>}
            
            {stage==='drawing' && firstFrameUrl && (
                <div className="drawing-phase">
                    <h3>Configure as Áreas</h3>
                    <small>v3.0 - Reclassificação e Toque</small>
                    <div className="drawing-buttons">
                        <button style={{background: activeLine==='entrant'?'#00cc00':'#555', color:'white'}} onClick={()=>setActiveLine('entrant')}>Linha Entrantes (Verde)</button>
                        <button style={{background: activeLine==='passerby'?'#cccc00':'#555', color:'black'}} onClick={()=>setActiveLine('passerby')}>Linha Passantes (Amarelo)</button>
                        <button onClick={()=>activeLine==='entrant'?setEntrantPoints([]):setPasserbyPoints([])}>Limpar Linha</button>
                        <button onClick={()=>setInSide(inSide==='right'?'left':'right')}>Inverter IN/OUT</button>
                    </div>
                    <DrawingCanvas imageUrl={firstFrameUrl} entrantPoints={entrantPoints} setEntrantPoints={setEntrantPoints} passerbyPoints={passerbyPoints} setPasserbyPoints={setPasserbyPoints} activeLine={activeLine} onImageLoad={setDims} inSide={inSide} />
                    <button className="custom-file-upload" style={{marginTop:'20px', background:'#28a745'}} onClick={handleProcess}>Processar Vídeo</button>
                </div>
            )}

            {stage==='processing' && <div className="processing-view"><h3>Processando... {progress}%</h3><div style={{background:'#444', height:'10px', width:'100%'}}><div style={{background:'#00ff00', height:'100%', width:`${progress}%`}}></div></div>{streamUrl && <img src={streamUrl} style={{maxWidth:'100%', marginTop:'10px'}}/>}</div>}

            {stage==='finished' && counts && (
                <div className="results-section">
                    <h3>Resultados Finais</h3>
                    <div className="all-stats-container">
                        <CountBlock title="Entrantes" counts={counts.entrantes}/>
                        <CountBlock title="Passantes" counts={counts.passantes}/>
                        <AvgTimeBlock title="Tempo Médio de Permanência" metrics={counts.metricas_loja} />
                        <CountBlock title="Total Geral" counts={counts.total_geral}/>
                    </div>
                    <div className="download-section">
                        <button className="download-button" onClick={handleDownload} disabled={!outputUrl}>Baixar Vídeo</button>
                        {reportUrl && <a className="download-button report-button" href={reportUrl}>Baixar Relatório</a>}
                        <button className="download-button" style={{background:'#d9534f'}} onClick={reset}>Novo Vídeo</button>
                    </div>
                    {/* Player de Vídeo simples se disponível */}
                    {/*{outputUrl && <video controls src={outputUrl} width="100%" style={{marginTop:'20px'}}/>}*/}
                </div>
                
            )}
            {error && <p style={{color:'red', textAlign:'center'}}>{error}</p>}
        </div>
    );
};
export default VideoUpload;