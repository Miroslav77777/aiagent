FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY . .

RUN pip install --no-cache-dir .

CMD ["python", "main.py"]
