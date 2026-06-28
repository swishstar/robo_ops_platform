FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic

COPY app.py .

ENV PORT=9002

EXPOSE 9002

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
