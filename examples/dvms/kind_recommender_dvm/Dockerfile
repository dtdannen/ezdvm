FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY examples/dvms/kind_recommender_dvm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the ezdvm package and install it
COPY ezdvm/ ./ezdvm/
COPY pyproject.toml .
RUN pip install -e .

# Copy the application code
COPY examples/dvms/kind_recommender_dvm/ .

# Run the DVM
CMD ["python", "src/main.py"]
