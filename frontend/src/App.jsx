import React, { useState } from 'react';
import VideoUpload from './components/VideoUpload';
import VideoHistory from './components/VideoHistory';
import DeviceList from './components/DeviceList'; // <--- Restaurei o import
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('upload');

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>SenseVision 👁️ <small style={{fontSize: '0.5em', opacity: 0.7}}>Local Dev</small></h1>
      </header>

      <nav className="app-nav">
        <button 
          className={activeTab === 'upload' ? 'active' : ''} 
          onClick={() => setActiveTab('upload')}
        >
          Processar Vídeo
        </button>
        
        {/* --- ABA RESTAURADA --- */}
        <button 
          className={activeTab === 'devices' ? 'active' : ''} 
          onClick={() => setActiveTab('devices')}
        >
          Câmeras (Local)
        </button>
        {/* ---------------------- */}

        <button 
          className={activeTab === 'history' ? 'active' : ''} 
          onClick={() => setActiveTab('history')}
        >
          Histórico
        </button>
      </nav>

      <main className="app-main">
        {activeTab === 'upload' && <VideoUpload />}
        {/* --- COMPONENTE RESTAURADO --- */}
        {activeTab === 'devices' && <DeviceList />}
        {/* ----------------------------- */}
        {activeTab === 'history' && <VideoHistory />}
      </main>
    </div>
  );
}

export default App;