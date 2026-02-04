// frontend/src/services/api.js
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000', 
});

// Interceptor para adicionar o token a cada requisição autenticada
api.interceptors.request.use(async (config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --- Funções de API para Dispositivos e Histórico ---

// Busca o histórico de vídeos do usuário
export const getHistory = async () => {
  // Nota: Se sua baseURL terminar em /api, a rota final será /sense/api/users/me/videos
  // Certifique-se que o Nginx redireciona corretamente.
  const response = await api.get('/videos/me/'); 
  return response.data;
};

// Busca lista de dispositivos encontrados pelo instalador
export const getDevices = async () => {
  // Rota no Backend: /api/devices
  // Como a baseURL já tem /api, chamamos apenas /devices
  const response = await api.get('/devices'); 
  return response.data;
};

// Busca lista de fabricantes (Intelbras, Hikvision, etc)
export const getManufacturers = async () => {
  // Rota no Backend: /api/manufacturers
  const response = await api.get('/manufacturers');
  return response.data;
};

// Envia a configuração (usuário/senha/fabricante) para o dispositivo
export const configureDevice = async (deviceId, configData) => {
  // Rota no Backend: /api/devices/{id}/configure
  // configData deve conter: { name, username, password, manufacturer }
  const response = await api.put(`/devices/${deviceId}/configure`, configData);
  return response.data;
};

// Busca um snapshot (frame estático) da câmera para configuração
export const getDeviceSnapshot = async (deviceId) => {
  const response = await api.get(`/devices/${deviceId}/snapshot`);
  return response.data; // Retorna { url: "/static/frames/..." }
};

// Atualiza a configuração avançada (Horários e Linhas)
// Nota: Reutilizamos a rota de config, enviando os dados novos junto com os antigos
export const updateDeviceAdvanced = async (deviceId, fullConfigData) => {
  const response = await api.put(`/devices/${deviceId}/config`, fullConfigData);
  return response.data;
};

// Busca estatísticas em tempo real
export const getDeviceLiveStats = async (deviceId) => {
  const response = await api.get(`/devices/${deviceId}/live_stats`);
  return response.data;
};

export default api;
