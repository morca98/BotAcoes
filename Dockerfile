FROM python:3.11-slim

WORKDIR /app

# Instalar curl para healthchecks
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway exige uma porta exposta
EXPOSE 8080
ENV PORT=8080

CMD ["python", "bot.py"]
