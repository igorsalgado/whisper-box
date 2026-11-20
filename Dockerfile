FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

# OMP_NUM_THREADS=2 e apenas o padrao da imagem; o Compose o define a partir de WHISPER_BOX_CPUS.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    OMP_NUM_THREADS=2 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && pip check
COPY src ./src
COPY tests ./tests
COPY whisper-box.py ./
# Rótulo com o digest do código (calculado por whisper-box.py); o doctor detecta imagem defasada.
ARG SOURCE_DIGEST=unknown
LABEL whisper-box.source-digest=$SOURCE_DIGEST
ENTRYPOINT ["python", "-m", "whisper_box"]
CMD ["worker"]
