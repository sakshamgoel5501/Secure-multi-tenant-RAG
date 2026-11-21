FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    FASTEMBED_CACHE_PATH=/app/.model_cache HF_HOME=/app/.model_cache
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[real]"
COPY data/baseline.json ./data/baseline.json
RUN useradd -m rag && mkdir -p /app/.model_cache && chown -R rag /app
USER rag
EXPOSE 8000
CMD ["uvicorn", "serving.main_stack:app", "--host", "0.0.0.0", "--port", "8000"]

