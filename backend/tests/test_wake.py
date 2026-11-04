import shutil
import subprocess
import sys
import wave

import pytest

from bizos import wake


def test_heard_matches_only_the_wake_phrase():
    assert wake.heard("hey biz oh s")
    assert wake.heard("okay biz oh s [unk]")
    assert not wake.heard("hey [unk]")
    assert not wake.heard("[unk] biz [unk]")


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("say") or not wake.MODEL.exists(), reason="needs macOS say + model")
@pytest.mark.parametrize("phrase,expected", [
    ("Hey BizOS", True), ("OK BizOS", True), ("Hey Biz OS, what is our revenue", True),
    ("Hey boss", False), ("hey, these old shoes", False), ("the bus is late again", False), ("Hey Siri", False),
])
def test_real_speech(tmp_path, phrase, expected):
    aiff, wav = tmp_path / "s.aiff", tmp_path / "s.wav"
    subprocess.run(["say", "-o", aiff, phrase], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    w = wave.open(str(wav))
    chunks = iter(lambda: w.readframes(4000), b"")
    assert wake.detect(wake.recognizer(), chunks) == expected
