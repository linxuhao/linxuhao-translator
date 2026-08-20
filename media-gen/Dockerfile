# ==========================================
# 文件名: media-gen/Dockerfile
# 架构定位: GPU 1 (7800 XT) - 文生图 (FLUX.2 Klein) + 文生音乐 (ACE-Step)
# ==========================================
FROM rocm/pytorch:latest

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 9010

CMD ["python", "app.py"]
