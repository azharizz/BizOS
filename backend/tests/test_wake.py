import json
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
    assert wake.detect(wake.recognizer(), speech(tmp_path, phrase)) == expected


def speech(tmp_path, phrase):
    aiff, wav = tmp_path / "s.aiff", tmp_path / "s.wav"
    subprocess.run(["say", "-o", aiff, phrase], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, wav], check=True)
    w = wave.open(str(wav))
    return iter(lambda: w.readframes(4000), b"")


def test_stop_words():
    assert wake.stopped("hey biz oh s stop") and wake.stopped("cancel")
    assert not wake.stopped("hey biz oh s") and not wake.stopped("[unk]")


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("say") or not wake.MODEL.exists(), reason="needs macOS say + model")
@pytest.mark.parametrize("phrase,expected", [("Hey BizOS, stop", True), ("Hey BizOS, cancel that", True),
                                             ("Hey BizOS, what is our revenue", False)])
def test_stop_right_after_the_wake_phrase(tmp_path, phrase, expected):
    rec, chunks = wake.recognizer(), speech(tmp_path, phrase)
    assert wake.detect(rec, chunks)
    assert wake.follow(rec, chunks) == expected

