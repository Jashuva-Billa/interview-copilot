"""Exercise the frozen Windows app using virtual devices and a loopback API."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

QUESTION = "How do you handle retries?"
CANDIDATE = "Can you repeat the question?"
FOLLOW_UP = "What happens when all retries fail?"
RECOVERED = "How would you monitor this?"
ANSWER = "Use bounded exponential backoff."


class Provider(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, status, body, content_type="application/json"):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        state = self.server.state
        try:
            if self.path == "/v1/audio/transcriptions":
                marker = data.index(b"RIFF")
                with wave.open(io.BytesIO(data[marker:]), "rb") as wav:
                    assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
                    pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
                assert np.count_nonzero(np.abs(pcm.astype(np.int32)) > 1000) >= 12800, "WAV lost callback samples"
                dominant = np.argmax(np.abs(np.fft.rfft(pcm))) * 16000 / len(pcm)
                text = QUESTION if dominant < 600 else CANDIDATE
                state.audio.append(text)
                self.send(200, json.dumps({"text": text}))
                return

            assert self.path == "/v1/chat/completions"
            request = json.loads(data)
            state.chat.append(request)
            assert self.headers["Authorization"] == f"Bearer {state.key}", "Wrong API key"
            if state.mode == "retry":
                state.mode = "normal"
                self.send(503, '{"error":{"message":"Retry me","type":"server_error"}}')
                return
            if state.mode == "quota":
                self.send(429, '{"error":{"message":"No credits","type":"insufficient_quota","code":"insufficient_quota"}}')
                return
            if state.mode == "vision":
                image = request["messages"][0]["content"][1]["image_url"]["url"]
                with Image.open(io.BytesIO(base64.b64decode(image.split(",", 1)[1]))) as photo:
                    assert photo.format == "JPEG"
                    assert photo.size == (32, 24)
                chunks = ("===PROBLEM===\nWhich answer is correct?\n", "===ANSWER===\nOption B.")
            else:
                chunks = ("Use bounded ", "exponential backoff.")
            lines = [f"data: {json.dumps({'choices': [{'delta': {'content': part}}]})}\n\n" for part in chunks]
            self.send(200, "".join(lines) + "data: [DONE]\n\n", "text/event-stream")
        except Exception as exc:
            state.errors.append(str(exc))
            self.send(400, '{"error":{"message":"Invalid test request"}}')


class FakeStream:
    def __init__(self, callback):
        self.callback = callback
        self.active = False

    def start(self):
        assert not self.active
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.stop()

    start_stream = start
    stop_stream = stop


def wait(app, condition, label):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for {label}")


def feed(stream, rate, frequency, *, wasapi=False):
    assert stream.active
    tone = (0.18 * np.sin(2 * np.pi * frequency * np.arange(rate) / rate)).astype(np.float32)
    samples = np.concatenate((tone, np.zeros(rate * 4, dtype=np.float32)))
    # Alternating half and double blocks exercises frame preservation in the real callback.
    position = 0
    for count in (rate // 100, rate // 25) * 100:
        block = samples[position:position + count]
        if wasapi:
            stereo = np.column_stack((block, block * 0.8))
            stream.callback(stereo.tobytes(), len(block), None, None)
        else:
            stream.callback(block[:, None], len(block), None, None)
        position += count
    assert position == len(samples)


def check(app_runner, report):
    from app import credentials
    from audio_processing import audio_capture as capture

    state = SimpleNamespace(mode="retry", audio=[], chat=[], errors=[], key="sk-packaged-test")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    server.state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{server.server_port}/v1"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(name, None)
    os.environ["NO_PROXY"] = "127.0.0.1"
    credentials.QInputDialog = SimpleNamespace(getText=lambda *_: ("sk-packaged-test", True))
    assert not credentials.config.openai_key_configured(), "test profile already contains an API key"
    assert credentials.configure_openai()
    assert "sk-packaged-test" in Path(credentials.config.env_file_path()).read_text(encoding="utf-8")
    report.append("First-run key setup persisted in isolated profile")

    pyaudio_device = {"name": "Virtual speaker loopback", "index": 1, "maxInputChannels": 2, "defaultSampleRate": 48000}

    class AudioBackend:
        def get_host_api_info_by_type(self, _):
            return {"defaultOutputDevice": 0}

        def get_device_info_by_index(self, index):
            return pyaudio_device if index else {"name": "Virtual speaker"}

        def get_loopback_device_info_generator(self):
            yield pyaudio_device

        def open(self, **kwargs):
            assert kwargs["rate"] == 48000 and kwargs["channels"] == 2
            stream = FakeStream(kwargs["stream_callback"])
            if kwargs.get("start", True):
                stream.start()
            return stream

        def terminate(self):
            pass

    # Import the bundled hardware library before substituting its device boundary.
    import pyaudiowpatch

    sys.modules["pyaudiowpatch"] = SimpleNamespace(
        PyAudio=AudioBackend, paWASAPI=pyaudiowpatch.paWASAPI,
        paFloat32=pyaudiowpatch.paFloat32, paContinue=pyaudiowpatch.paContinue,
    )
    capture.sd.InputStream = lambda **kwargs: FakeStream(kwargs["callback"])
    app = app_runner()
    app._watch_timer.stop()
    failures, quotas = [], []
    app.bridge.error.connect(failures.append)
    app.bridge.credits_exhausted.connect(quotas.append)
    app._start_listening()
    try:
        assert app.system_recorder and app.mic_recorder, failures
        app.system_recorder.on_partial = lambda _: None
        system_stream = app.system_recorder._stream.stream
        mic_stream = app.mic_recorder._stream
        feed(system_stream, 48000, 440, wasapi=True)
        wait(app.app, lambda: len(app.conversation) == 2 and not app._busy, "streamed response and retry")
        assert app.conversation[0]["content"] == QUESTION
        assert app.conversation[1]["content"] == ANSWER
        assert len(state.chat) == 2 and not failures and not quotas
        assert ANSWER in app.window.columns["openai"]["answer_box"].toPlainText()

        feed(mic_stream, 16000, 880)
        wait(app.app, lambda: CANDIDATE in app.window.live_transcript_box.toPlainText(), "candidate transcript")
        assert state.audio == [QUESTION, CANDIDATE]
        assert len(state.chat) == 2 and len(app.conversation) == 2
        report.append("WASAPI conversion, variable buffers, VAD, SDK retry, streamed UI, mic isolation")

        app._stop_listening()
        assert not system_stream.active and not mic_stream.active
        app._start_listening()
        assert app.system_recorder._stream.stream is not system_stream
        assert app.mic_recorder._stream is not mic_stream
        app._stop_listening()
        report.append("Start/stop/restart released both inputs")

        state.mode = "quota"
        credentials.QInputDialog = SimpleNamespace(getText=lambda *_: ("sk-replacement-test", True))
        app._queue_question(FOLLOW_UP)
        wait(app.app, lambda: quotas and not app._busy, "credit recovery")
        assert quotas == ["openai"] and len(app.conversation) == 2
        assert "sk-replacement-test" in Path(credentials.config.env_file_path()).read_text(encoding="utf-8")
        state.mode = "normal"
        state.key = "sk-replacement-test"
        app._queue_question(RECOVERED)
        wait(app.app, lambda: len(app.conversation) == 4 and not app._busy, "successful request after key replacement")
        assert app.conversation[-2]["content"] == RECOVERED
        report.append("Credits exhausted, key persisted, subsequent request succeeded")

        state.mode = "vision"
        image = io.BytesIO()
        Image.new("RGB", (32, 24), "white").save(image, "JPEG")
        assert app._try_start_work()
        app.executor.submit(app._worker_solve_jpeg, image.getvalue(), "high")
        wait(app.app, lambda: len(app.conversation) == 6 and not app._busy, "screenshot answer")
        assert "Option B" in app.conversation[-1]["content"]
        assert not state.errors, state.errors
        report.append("Screenshot JPEG round trip and response parsing")
    finally:
        app._stop_listening()
        for executor in (app.executor, app.audio_executor, app.partial_executor):
            executor.shutdown(wait=True)
        app.window.close()
        server.shutdown()
        server.server_close()
        thread.join()


def run(app_runner):
    report = []
    try:
        check(app_runner, report)
    except Exception:
        report.append(traceback.format_exc())
        return_code = 1
    else:
        return_code = 0
    Path("package-smoke.log").write_text("\n".join(report) + "\n", encoding="utf-8")
    return return_code
