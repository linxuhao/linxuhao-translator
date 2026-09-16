FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for audio conversion
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY gpu_client.py video_tools.py ./
COPY prompts/ ./prompts/

EXPOSE 9003 9004

CMD ["python", "app.py"]
