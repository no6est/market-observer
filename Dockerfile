FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY app/ app/
COPY configs/ configs/

RUN pip install --no-cache-dir -e .

RUN mkdir -p data reports

# Default: run daily pipeline
CMD ["python", "-m", "app", "run-daily", "--config", "configs/config.yaml"]
