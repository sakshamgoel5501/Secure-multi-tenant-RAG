FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install ".[real]"
RUN useradd -m rag && mkdir -p /app/.model_cache /app/data && chown -R rag /app
USER rag
EXPOSE 8000
CMD ["uvicorn", "serving.main_stack:app", "--host", "0.0.0.0", "--port", "8000"]


