FROM python:3.12.12-slim-bookworm
WORKDIR /workspace
COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt
COPY printflow ./printflow
COPY web ./web
COPY printer_preferences.json ./
RUN mkdir -p /workspace/models /data && useradd --uid 10001 --create-home printflow && chown -R printflow:printflow /workspace /data
USER printflow
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PRINTFLOW_DATA_DIR=/data
CMD ["python", "-m", "uvicorn", "printflow.api:app", "--host", "0.0.0.0", "--port", "8000"]
