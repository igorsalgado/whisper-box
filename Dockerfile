FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src \
    OMP_NUM_THREADS=2 HF_HUB_DISABLE_TELEMETRY=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock && pip check
COPY src ./src
COPY tests ./tests
ENTRYPOINT ["python", "-m", "whisper_box"]
CMD ["worker"]
