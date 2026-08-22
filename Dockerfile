FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency install
RUN pip install --no-cache-dir uv==0.1.44

COPY pyproject.toml .
RUN uv pip install --system --no-cache .

COPY . .

EXPOSE 8000
