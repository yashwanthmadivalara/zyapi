FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
RUN mkdir -p /app/data/uploads /app/data/clips

ENV DATABASE_PATH=/app/data/viralflow.db
ENV UPLOAD_DIR=/app/data/uploads
ENV CLIP_DIR=/app/data/clips
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
