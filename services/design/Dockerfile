FROM python:3.12.12-slim-bookworm
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libgomp1 libxrender1 libsm6 && rm -rf /var/lib/apt/lists/*
COPY requirements-design.txt ./
RUN pip install --no-cache-dir -r requirements-design.txt
COPY printflow ./printflow
RUN useradd --uid 10001 --create-home printflow
USER printflow
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PRINTFLOW_DATA_DIR=/tmp/printflow
CMD ["python", "-m", "uvicorn", "printflow.design_worker:app", "--host", "0.0.0.0", "--port", "8000"]
