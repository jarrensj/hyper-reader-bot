FROM python:3.12-slim

WORKDIR /app
COPY hyper_reader.py .

# Mount a Railway volume at /data so /watch state survives redeploys.
ENV PYTHONUNBUFFERED=1 STATE_FILE=/data/watchers.json

CMD ["python", "hyper_reader.py"]
