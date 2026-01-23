// frontend/src/components/VideoHistory.jsx
import React, { useState, useEffect } from 'react';
import api from '../services/api';
import './VideoHistory.css';

const API_BASE = 'http://localhost:8000';

const VideoCard = ({ video, onDelete }) => {
    const thumbnailUrl = video.first_frame_url ? `${API_BASE}${video.first_frame_url}` : null;
    const processedUrl = video.processed_video_url ? `${API_BASE}${video.processed_video_url}` : null;
    
    // NOVO: URL específica para forçar o download
    const forceDownloadUrl = `${API_BASE}/download-video/${video.id}`;
    const reportUrl = video.report_url ? `${API_BASE}${video.report_url}` : null;

    const handleDeleteClick = () => {
        if (window.confirm("Tem certeza que deseja excluir este vídeo e seus dados? Esta ação não pode ser desfeita.")) {
            onDelete(video.id);
        }
    };

    return (
        <div className="video-card">
            <div className="video-thumbnail-wrapper">
                
                {/* Renderiza o <video> com POSTER (Capa) para identificação fácil */}
                {video.status === 'done' && processedUrl ? (
                    <video
                        src={processedUrl}
                        poster={thumbnailUrl} // <--- Mostra o primeiro frame como capa
                        className="video-thumbnail"
                        controls // Permite dar play se quiser assistir
                        playsInline
                        preload="metadata"
                    />
                ) : (
                    // Mostra o thumbnail se o vídeo não estiver pronto
                    <img src={thumbnailUrl} alt={`Frame do vídeo ${video.id}`} className="video-thumbnail" />
                )}

                <button onClick={handleDeleteClick} className="delete-button" title="Excluir Vídeo">×</button>
            </div>
            <div className="video-info">
                <p><strong>Data:</strong> {new Date(video.created_at).toLocaleString()}</p>
                <p><strong>Status:</strong> <span className={`status status-${video.status}`}>{video.status}</span></p>
                <div className="video-actions">
                    {video.status === 'done' && (
                        <>
                            {processedUrl && (
                                <a href={forceDownloadUrl} className="action-button download-button" style={{marginRight: '5px', background: '#007bff'}}>
                                    Baixar Vídeo
                                </a>
                            )}
                            {reportUrl && (
                                <a href={reportUrl} download={`relatorio_${video.id}.xlsx`} className="action-button download-button">
                                    Baixar Relatório
                                </a>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};


const VideoHistory = ({ refreshTrigger }) => { 
    const [videos, setVideos] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const fetchVideos = async () => {
        try {
            setError('');
            setLoading(true);
            const response = await api.get('/videos/me/');
            setVideos(response.data);
        } catch (err) {
            setError('Não foi possível carregar o histórico de vídeos.');
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchVideos();
    }, [refreshTrigger]); 

    const handleDeleteVideo = async (videoId) => {
        try {
            await api.delete(`/videos/${videoId}`);
            setVideos(currentVideos => currentVideos.filter(video => video.id !== videoId));
        } catch (err) {
            setError('Falha ao excluir o vídeo. Tente novamente.');
            console.error(err);
        }
    };

    if (loading) {
        return <p>Carregando histórico...</p>;
    }

    if (error) {
        return <p className="error-message">{error}</p>;
    }

    return (
        <div className="video-history-container">
            {videos.length === 0 ? (
                <p>Nenhum vídeo processado ainda.</p>
            ) : (
                <div className="video-grid">
                    {videos.map(video => (
                        <VideoCard key={video.id} video={video} onDelete={handleDeleteVideo} />
                    ))}
                </div>
            )}
        </div>
    );
};

export default VideoHistory;
