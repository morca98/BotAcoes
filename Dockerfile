FROM python:3.11-slim

WORKDIR /app

# Instalar dependências de sistema para o pandas/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway usa a porta 8080 por padrão
ENV PORT=8080

CMD ["python", "bot.py"]
