FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the DVM code
COPY src/ ./src/

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the DVM
CMD ["python", "src/main.py"]
