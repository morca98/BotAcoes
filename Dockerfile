FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Health check (5 min interval)
HEALTHCHECK --interval=5m --timeout=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Run
CMD ["python", "bot.py"]
