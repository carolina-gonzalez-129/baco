# Imagen única de Baco: la usan los servicios app, rebuild y frontend del docker-compose.yml
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/opt/hf \
    DATA_DIR=/app/data

# libgomp1: OpenMP nativo que requieren onnxruntime y torch
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) torch CPU antes que el resto, para que sentence-transformers no arrastre CUDA (~3 GB)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# 2) Dependencias de producción (sin el extra [test]), en capa propia para aprovechar caché
COPY pyproject.toml README.md ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt

# 3) Modelos ONNX horneados en la imagen (~410 MB). Se cargan desde embeddings.py
#    como archivo suelto (sin importar el paquete baco) para usar exactamente los mismos modelos.
COPY baco/server/services/embeddings.py /tmp/embeddings.py
RUN python -c "import importlib.util as u; s=u.spec_from_file_location('emb','/tmp/embeddings.py'); m=u.module_from_spec(s); s.loader.exec_module(m); m.get_model_titulo(); m.get_model_texto()" \
    && rm /tmp/embeddings.py

# 4) Código, semilla de artículos y front. Instalación editable para que
#    Path(__file__).parents[N] resuelva a /app (y no a site-packages)
COPY baco ./baco
COPY data/articulos.json ./data/articulos.json
COPY frontend ./frontend
RUN pip install --no-deps -e . \
    && mkdir -p /app/data/temp_sesiones

EXPOSE 8080 5173

CMD ["uvicorn", "baco.server.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
