# Estágio 1: Instalar dependências do sistema e do Python
FROM python:3.11-slim

# Instala dependências do sistema
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    ffmpeg \
    libsm6 \
    libxext6 \
    wget \
    git \
    build-essential \
    curl \
    gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && apt-get update && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Instala Poetry
RUN pip install poetry

# Configura o diretório de trabalho
WORKDIR /app

# Copia os arquivos de dependência
COPY pyproject.toml ./

RUN pip install --no-cache-dir \
    torch torchvision torchaudio \

    --index-url https://download.pytorch.org/whl/cu121
    # EM CASO DE NÃO POSSUIR GPU NVIDIA, USE A LINHA ABAIXO E COMENTE A LINHA DE CIMA
    #--index-url https://download.pytorch.org/whl/cpu
    

RUN pip install --no-cache-dir ultralytics

RUN pip install --no-cache-dir git+https://github.com/yanzeradev/TransReID.git
RUN pip install --no-cache-dir git+https://github.com/yanzeradev/boxmot.git

RUN rm -f poetry.lock

ENV POETRY_REQUESTS_TIMEOUT=10000
# Aumenta o número de tentativas em caso de falha
ENV POETRY_HTTP_BASIC_RETRY=5

# Monta um cache no diretório onde o Poetry guarda os downloads
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    poetry config virtualenvs.create false && \
    poetry install --no-root --without dev

# Copia o resto do código
COPY . .

# Cria o diretório explicitamente
RUN mkdir -p /app/sense/

# Cria os diretórios estáticos
RUN mkdir -p /app/static/uploads /app/static/frames /app/static/output_videos /app/static/reports

# Comando para rodar a aplicação
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
