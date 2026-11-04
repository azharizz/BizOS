"""Hands-free: an offline "Hey BizOS" listener. Run by the desktop app as `python -m bizos.wake`.

Audio stays on this machine (Vosk, a local speech model); the only thing printed is the word "wake".
The recognizer is restricted to the wake phrases, so ordinary talk comes out as [unk] and never triggers it.
"""
import io
import json
import queue
import sys
import time
import zipfile
from collections.abc import Iterable
from pathlib import Path

import httpx
import vosk

from .web import TLS

NAME = "vosk-model-small-en-us-0.15"
MODEL = Path.home() / ".bizos" / "models" / NAME
URL = f"https://alphacephei.com/vosk/models/{NAME}.zip"
RATE = 16000
# "BizOS" isn't an English word; spelled as the model hears it.
GRAMMAR = ["hey biz oh s", "okay biz oh s", "[unk]"]
COOLDOWN = 3  # seconds: ignore the tail of the same "Hey BizOS"


def heard(text: str) -> bool:
    return "biz oh s" in text


def recognizer() -> vosk.KaldiRecognizer:
    vosk.SetLogLevel(-1)
    return vosk.KaldiRecognizer(vosk.Model(str(MODEL)), RATE, json.dumps(GRAMMAR))


def detect(rec: vosk.KaldiRecognizer, chunks: Iterable[bytes]) -> bool:
    """True as soon as the wake phrase is heard in a stream of 16 kHz mono int16 chunks."""
    for chunk in chunks:
        done = rec.AcceptWaveform(chunk)
        if heard(json.loads(rec.Result() if done else rec.PartialResult()).get("text" if done else "partial", "")):
            rec.Reset()
            return True
    return heard(json.loads(rec.FinalResult())["text"])


def download():
    print("status downloading speech model (40 MB, once)", flush=True)
    with httpx.Client(verify=TLS, timeout=120, follow_redirects=True) as c:
        data = c.get(URL).raise_for_status().content
    zipfile.ZipFile(io.BytesIO(data)).extractall(MODEL.parent)


def main():
    import sounddevice as sd  # only needed when actually listening

    if not MODEL.exists():
        download()
    rec, q = recognizer(), queue.Queue()
    with sd.RawInputStream(samplerate=RATE, blocksize=4000, dtype="int16", channels=1, callback=lambda d, *_: q.put(bytes(d))):
        print("status listening", flush=True)
        while True:
            if detect(rec, iter(q.get, None)):
                print("wake", flush=True)
                time.sleep(COOLDOWN)
                with q.mutex:
                    q.queue.clear()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # shown in the overlay
        print(f"error {e}", flush=True)
        sys.exit(1)
