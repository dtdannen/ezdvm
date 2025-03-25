FROM python:3.11-slim

WORKDIR /app

# Install git and wget (needed for model download)
RUN apt-get update && \
    apt-get install -y git wget && \
    rm -rf /var/lib/apt/lists/*

# Disable HF transfer and set offline mode
ENV HF_HUB_ENABLE_HF_TRANSFER=0
ENV TRANSFORMERS_OFFLINE=1

# Pre-download the model and tokenizer files
RUN mkdir -p /root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0 && \
    cd /root/.cache/huggingface/hub && \
    # Download model and tokenizer files
    wget -O pytorch_model.bin https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/pytorch_model.bin && \
    wget -O config.json https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/config.json && \
    wget -O tokenizer.json https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/tokenizer.json && \
    wget -O tokenizer_config.json https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/tokenizer_config.json && \
    wget -O special_tokens_map.json https://huggingface.co/BAAI/bge-large-en-v1.5/resolve/main/special_tokens_map.json && \
    # Move files to the correct location
    mv pytorch_model.bin models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0/ && \
    mv config.json models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0/ && \
    mv tokenizer.json models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0/ && \
    mv tokenizer_config.json models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0/ && \
    mv special_tokens_map.json models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0/ && \
    # Create model.json to tell transformers where to find the files
    echo '{"bge-large-en-v1.5": "/root/.cache/huggingface/hub/models--BAAI--bge-large-en-v1.5/snapshots/c43af0e0c0d29de68b4d14e2cc489aa098caf7f0"}' > /root/.cache/huggingface/hub/models.json

COPY requirements.txt .
RUN pip config set global.timeout 300 && \
    pip config set global.retries 10 && \
    pip config set global.index-url https://pypi.org/simple && \
    pip install --no-cache-dir -r requirements.txt


# Copy the rest of the application
COPY . .

# Run the application
CMD ["python", "-m", "src.main"]