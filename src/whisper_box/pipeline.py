import json
import os
import time
from pathlib import Path

import av
import numpy as np

from .config import BoxError, Settings
from .jobs import ARTIFACTS
from .model import sha256_file


def audio_chunks(path: Path, seconds: int = 300):
    """Decodifica em blocos limitados; memória independente da duração total."""
    size = seconds * 16000
    buffer = np.empty(size, dtype=np.float32)
    used = 0
    offset = 0.0
    try:
        with av.open(str(path)) as media:
            if not media.streams.audio:
                raise BoxError("no_audio", "A mídia não possui stream de áudio.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)

            def frames():
                for frame in media.decode(audio=0):
                    yield from resampler.resample(frame)
                yield from resampler.resample(None)

            for frame in frames():
                samples = frame.to_ndarray().reshape(-1)
                position = 0
                while position < len(samples):
                    count = min(size - used, len(samples) - position)
                    buffer[used:used + count] = samples[position:position + count].astype(np.float32) / 32768.0
                    used += count
                    position += count
                    if used == size:
                        yield offset, buffer
                        offset += used / 16000
                        buffer = np.empty(size, dtype=np.float32)
                        used = 0
            if used:
                yield offset, buffer[:used]
    except av.error.FFmpegError as exc:
        raise BoxError("invalid_media", "Não foi possível decodificar a mídia.") from exc


def timestamp(seconds: float, srt: bool = False) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    if srt:
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def transcribe(settings: Settings, job: dict, model, progress):
    config = json.loads(job["config"])
    temporary = settings.outputs / ".partial" / job["id"] / str(job["attempts"])
    temporary.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    duration = vad_duration = 0.0
    count = 0
    detected_languages = set()
    with (temporary / ARTIFACTS["text"]).open("w", encoding="utf-8") as text, \
         (temporary / ARTIFACTS["srt"]).open("w", encoding="utf-8") as subtitles, \
         (temporary / ARTIFACTS["segments"]).open("w", encoding="utf-8") as segments_file:
        last_progress = 0.0
        for offset, audio in audio_chunks(Path(job["input_path"]), config["chunk_seconds"]):
            duration = offset + len(audio) / 16000
            segments, info = model.transcribe(
                audio,
                language=None if config["language"] == "auto" else config["language"],
                beam_size=config["beam_size"], vad_filter=config["vad_filter"],
                condition_on_previous_text=config["condition_on_previous_text"],
            )
            detected_languages.add(info.language)
            vad_duration += info.duration_after_vad
            for segment in segments:
                count += 1
                start = offset + segment.start
                end = offset + segment.end
                content = segment.text.strip()
                record = {"inicio": start, "fim": end, "texto": content,
                          "confianca_log": segment.avg_logprob,
                          "sem_fala": segment.no_speech_prob}
                segments_file.write(json.dumps(record, ensure_ascii=False) + "\n")
                text.write(f"[{timestamp(start)}–{timestamp(end)}] {content}\n")
                subtitles.write(f"{count}\n{timestamp(start, True)} --> {timestamp(end, True)}\n{content}\n\n")
                if time.monotonic() - last_progress >= 5:
                    progress(end)
                    last_progress = time.monotonic()
            progress(duration)
        for stream in (text, subtitles, segments_file):
            stream.flush()
            os.fsync(stream.fileno())
    if duration == 0:
        raise BoxError("empty_audio", "O stream de áudio está vazio.")
    metadata = {
        "job_id": job["id"], "input_sha256": job["input_hash"],
        "config": config, "duration_seconds": round(duration, 3),
        "speech_seconds": round(vad_duration, 3), "segments": count,
        "no_speech": count == 0, "detected_languages": sorted(detected_languages),
        "processing_seconds": round(time.monotonic() - started, 3),
        "attempt": job["attempts"], "interruptions": job["interruptions"],
    }
    (temporary / ARTIFACTS["metadata"]).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest = {"fingerprint": job["fingerprint"], "sha256": {
        name: sha256_file(temporary / name) for name in ARTIFACTS.values()
    }}
    (temporary / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # Diretório final só aparece depois dos quatro artefatos e do manifesto completos.
    final = settings.outputs / job["id"]
    if final.exists():
        raise BoxError("output_conflict", "Já existe uma saída incompatível para este trabalho.")
    temporary.rename(final)
