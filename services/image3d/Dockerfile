ARG BASE_IMAGE=python:3.12.12-slim-bookworm
FROM ${BASE_IMAGE}
ARG TORCH_INSTALL=cpu
WORKDIR /workspace
COPY services/image3d/requirements.txt ./requirements-image3d.txt
RUN if [ "$TORCH_INSTALL" = "cpu" ]; then python -m pip install --no-cache-dir torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu; fi
RUN python -m pip install --no-cache-dir -r requirements-image3d.txt
COPY services/image3d/bootstrap.py ./bootstrap.py
RUN python bootstrap.py source /opt/triposr
COPY printflow ./printflow
RUN useradd --uid 10001 --create-home printflow && mkdir -p /weights && chown printflow:printflow /weights
USER printflow
ENV PYTHONPATH=/opt/triposr PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PRINTFLOW_WEIGHTS_DIR=/weights PRINTFLOW_DATA_DIR=/tmp/printflow HF_HUB_OFFLINE=1
CMD ["python", "-m", "uvicorn", "printflow.image3d_worker:app", "--host", "0.0.0.0", "--port", "8000"]
