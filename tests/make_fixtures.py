"""Gera mídia sintética local; não inclui gravações no repositório."""

import sys
import wave
from pathlib import Path

import av
import numpy as np


def main(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    for name, duration in (("silencio.wav", 2), ("silencio-duas-horas.wav", 7200)):
        with wave.open(str(destination / name), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            for _ in range(duration):
                stream.writeframes(bytes(32000))
    for extension, codec in (("mp3", "libmp3lame"), ("m4a", "aac"), ("mp4", "aac")):
        with av.open(str(destination / f"silencio.{extension}"), "w") as container:
            stream = container.add_stream(codec, rate=16000)
            stream.layout = "mono"
            frame = av.AudioFrame.from_ndarray(np.zeros((1, 32000), dtype=np.int16), format="s16", layout="mono")
            frame.sample_rate = 16000
            for packet in stream.encode(frame):
                container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    (destination / "invalido.mp4").write_bytes(b"not a media file")
    print("Fixtures locais geradas.")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
