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
	&& rm -rf /var/lib/apt/lists/*

COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --default-timeout=1000 -r /code/requirements.txt

COPY . /code

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]