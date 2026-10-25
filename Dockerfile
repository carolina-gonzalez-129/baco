FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    HF_HUB_DISABLE_PROGRESS_BARS=1 \
    TQDM_DISABLE=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY baco ./baco

# Precargar modelos ONNX INT8 en la imagen durante el build para arranque instantáneo por stdio
RUN python -c "from baco.server.services.embeddings import get_model_titulo, get_model_texto; get_model_titulo(); get_model_texto()"

ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

ENTRYPOINT ["python", "-m", "baco.server.mcp_server"]
