FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends iputils-ping && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts/nms-snmp-agent.py ./agents/nms-snmp-agent.py
COPY scripts/nms-syslog-agent.py ./agents/nms-syslog-agent.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
