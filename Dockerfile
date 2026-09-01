# Dockerfile for Google Cloud Run deployment.
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    WEB_APP_PORT=8080 \
    MCP_SERVER_PORT=8081 \
    MCP_SERVER_URL=http://127.0.0.1:8081/mcp

WORKDIR /app

# build-essential covers any dependency without a prebuilt wheel for slim.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project source code
COPY . .

# Expose port
EXPOSE 8080

# Command to run both FastMCP & Web Dashboard
CMD ["python", "run.py"]
