FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY agent/requirements.txt /app/agent/requirements.txt
RUN pip install -r /app/agent/requirements.txt

COPY agent/ /app/agent/
COPY eval/ /app/eval/

ENV PYTHONPATH=/app/agent:/app/eval \
    PORT=8080

EXPOSE 8080

# Default: run the FastAPI agent. The Cloud Run Job overrides --command/--args
# to invoke `python /app/eval/run_eval.py` instead.
CMD ["uvicorn", "--app-dir", "/app/agent", "server:app", "--host", "0.0.0.0", "--port", "8080"]
