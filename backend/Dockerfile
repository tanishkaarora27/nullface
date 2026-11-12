FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements.txt backend/requirements-full.txt ./
ARG FULL=0
RUN pip install -r requirements.txt && if [ "$FULL" = "1" ]; then pip install -r requirements-full.txt; fi
COPY backend/app ./app
COPY frontend/public /srv/frontend/public
ENV NF_FRONTEND_DIR=/srv/frontend/public NF_EPHEMERAL_DIR=/dev/shm
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
