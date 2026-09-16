FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for audio conversion
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Every module the server imports at runtime. app.py alone was what shipped before, so a
# rebuild silently dropped gpu_client, video_tools and the prompt the running image had.
COPY app.py gpu_client.py video_tools.py ./
COPY prompts/ ./prompts/

EXPOSE 9003 9004

CMD ["python", "app.py"]