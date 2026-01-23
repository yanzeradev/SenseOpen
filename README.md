# SenseVision - Open Source 👁️

**SenseVision** é uma ferramenta de visão computacional desenvolvida para **contagem e rastreamento de pessoas** em vídeos. Esta versão Open Source foi adaptada para execução local simplificada, ideal para desenvolvedores, pesquisadores e entusiastas testarem algoritmos de Computer Vision (YOLO + BoT-SORT + ReID).

---

## 🚀 Funcionalidades

* **Processamento de Vídeo Local:** Upload e análise de arquivos `.mp4` diretamente do navegador.
* **Pipeline de IA:** Utiliza **YOLOv8** (Detecção), **BoT-SORT** (Rastreamento) e **FastReID** (Re-identificação) para contagem precisa.
* **Contagem Bidirecional:** Defina linhas virtuais de "Entrada" e "Passagem" para métricas de fluxo.
* **Interface Reativa:** Frontend em React com visualização de histórico e status em tempo real.
* **Zero Configuração de Banco:** Utiliza SQLite nativo, sem necessidade de configurar servidores de banco de dados externos.

---

## 🛠️ Tecnologias

* **Backend:** Python 3.11, FastAPI, PyTorch, OpenCV.
* **Frontend:** React (Vite), CSS Modules.
* **Infraestrutura:** Docker & Docker Compose.
* **Banco de Dados:** SQLite (Arquivo local).

---

## 📋 Pré-requisitos

Para rodar o projeto, você precisa apenas de:

1.  **Docker** e **Docker Compose** instalados.
2.  **Git** para clonar o repositório.
3.  *(Opcional)* **GPU NVIDIA** com drivers atualizados (para processamento rápido). O projeto roda em CPU, mas será consideravelmente mais lento.

---

## ⚡ Como Executar

### 1. Clone o Repositório

Execute os seguintes comandos abaixo:

`git clone https://github.com/yanzeradev/SenseOpen.git`

`cd SenseOpen`

`wget https://github.com/yanzeradev/SenseOpen/releases/download/model/model_coco_crowd.pt -UseBasicParsing -OutFile backend/sense/model_coco_crowd.pt`



### 2. Build e Execução (Docker)
Execute o comando abaixo para construir as imagens e iniciar os containers.

`docker-compose up --build`

Nota: A primeira execução pode demorar alguns minutos, pois o Docker fará o download automático dos pesos dos modelos de IA (YOLO e ReID) definidos no Dockerfile.

Após o término do build, os serviços estarão disponíveis em:

Frontend (Interface): http://localhost:5173

Backend (API Docs): http://localhost:8000/docs

### 3. Como Usar
Acesse http://localhost:5173.

Vá na aba "Processar Vídeo".

Faça o upload de um vídeo curto (ex: 1 minuto) no formato .mp4.

Configure as linhas de contagem (clique no vídeo para desenhar as linhas de "Entrada" e "Passagem").

Clique em "Processar".

Acompanhe o progresso e, ao finalizar, visualize o vídeo processado e o relatório na aba "Histórico".

### 4. Estrutura do Projeto
backend/sense/main.py: Ponto de entrada da API FastAPI.

backend/sense/: Núcleo de Visão Computacional (Lógica de processamento, tracking e geometria).

frontend/: Código fonte da interface React.

docker-compose.yml: Orquestração dos serviços (Backend + Frontend).

sense.db: Arquivo de banco de dados (criado automaticamente na primeira execução).

### 5. Notas sobre GPU ⚠️
O docker-compose.yml vem configurado por padrão para rodar em qualquer máquina (CPU). Se você possui uma placa NVIDIA e quer ativar a aceleração por hardware:

Certifique-se de ter o NVIDIA Container Toolkit instalado.

No arquivo docker-compose.yml, descomente a seção deploy dentro do serviço backend.

### Contribuição
Sinta-se à vontade para abrir Issues ou enviar Pull Requests. O objetivo deste projeto é fornecer uma base sólida para estudos de Analytics de Varejo e Visão Computacional.
