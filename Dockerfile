FROM node:24-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LDS_PYTHON=/opt/venv/bin/python
EXPOSE 5173
CMD ["node", "--use-system-ca", "scripts/local-dashboard.mjs"]

