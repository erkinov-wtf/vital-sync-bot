FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies (optional): add build tools if wheels are unavailable
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Optional: include a pre-authenticated Telethon session file at build time.
# If bot.session is present in the project root, copy it into the image so no interactive login is needed.
COPY bot.session /app/bot.session
ENV SESSION_NAME=/app/bot.session
COPY interactive_call_session.session /app/interactive_call_session.session

EXPOSE 8081 8082

CMD ["python", "main.py"]
