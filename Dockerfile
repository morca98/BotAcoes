FROM python:3.11-slim

WORKDIR /app

# Instalar curl para healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Instalar dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Railway usa a variável PORT, mas o bot agora é focado em polling. 
# Mantemos o CMD simples para evitar erros de porta.
CMD ["python", "bot.py"]
