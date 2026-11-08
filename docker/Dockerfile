FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    FRAME_CONFIG_PATH=/app/config.json

WORKDIR /app

# Install system dependencies: libusb for USB access, curl, and fontconfig
RUN apt-get update && apt-get install -y --no-install-recommends \
    libusb-1.0-0 \
    curl \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser and its system-level shared dependencies
RUN playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy application source code
COPY service/ /app/service/

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8080"]
