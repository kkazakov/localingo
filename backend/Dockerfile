FROM pytorch/pytorch:2.7.0-cuda12.6-cudnn9-runtime

WORKDIR /app

# Install build dependencies for llama-cpp-python
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV HF_HOME=/models/hf_cache

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
