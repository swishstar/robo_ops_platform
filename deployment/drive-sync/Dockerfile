FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sync_drive_to_gcs.py .

# Cloud Run Job entrypoint
ENTRYPOINT ["python", "/app/sync_drive_to_gcs.py"]
