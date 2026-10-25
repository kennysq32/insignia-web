FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY build.py editor.py content_editor.py ./
COPY templates ./templates
COPY assets ./assets
COPY md2xtc ./md2xtc
ENV INSIGNIA_DATA_ROOT=/workspace INSIGNIA_BIND=0.0.0.0 PORT=8000 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
EXPOSE 8000
CMD ["python", "build.py", "serve", "--port", "8000"]
