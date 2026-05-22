FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PROJECT_ROOT=/workspace

WORKDIR /app

RUN mkdir -p /workspace

COPY apps/api/requirements.txt /tmp/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements.txt

COPY apps/api /app
COPY control_settings.py /workspace/control_settings.py

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
