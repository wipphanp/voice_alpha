# Use python 3.11 slim as base image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system-level dependencies for audio processing and networking
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory inside the container
WORKDIR /app

# Copy python dependencies file first to leverage Docker cache
COPY requirements.txt .

# Install python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Fix potential Windows CRLF line endings in start.sh and make it executable
RUN apt-get update && apt-get install -y --no-install-recommends dos2unix \
    && dos2unix start.sh \
    && apt-get --purge remove -y dos2unix \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x start.sh

# Expose the port FastAPI runs on
EXPOSE 8000

# Set entrypoint to run both agent and server
CMD ["./start.sh"]
