# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /code

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=1000

RUN apt-get update \
	&& apt-get install -y --no-install-recommends \
	   antiword \
	   libreoffice-core \
	   libreoffice-writer \
	   libreoffice-impress \
	   default-jre-headless \
	   libgl1 \
	   libglib2.0-0 \
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt

# Option A: CPU-only PyTorch (~200MB download, fast & lightweight) [ACTIVE]
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install --default-timeout=1000 --retries=10 torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --default-timeout=1000 --retries=10 -r /code/requirements.txt

# Option B: GPU/CUDA PyTorch (~2.5GB+ download, requires NVIDIA GPU runtime) [COMMENTED]
# RUN --mount=type=cache,target=/root/.cache/pip \
#     pip install --upgrade pip \
#     && pip install --default-timeout=1000 --retries=10 -r /code/requirements.txt

COPY . /code

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]