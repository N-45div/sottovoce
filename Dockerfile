FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY sottovoce ./sottovoce
RUN pip install --no-cache-dir .

# Bake the speech model into the image so the first job does not download it.
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

ENV SOTTOVOCE_DATA=/data \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    PORT=8080
CMD ["sh", "-c", "exec uvicorn sottovoce.server:app --host 0.0.0.0 --port ${PORT}"]
