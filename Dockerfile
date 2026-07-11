FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-railway.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY start.py ./start.py

ENV PORT=8000
ENV CE_TRANSCRIBE_MODE=openai
ENV CE_ALLOW_YTDLP_DOWNLOAD=false
EXPOSE 8000

CMD ["python", "-u", "start.py"]
