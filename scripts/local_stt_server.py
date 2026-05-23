from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


HOST = os.getenv("LOCAL_STT_HOST", "127.0.0.1")
PORT = int(os.getenv("LOCAL_STT_PORT", "18100"))
MODEL_SIZE = os.getenv("LOCAL_STT_MODEL", "small")
MODEL_DIR = os.getenv("LOCAL_STT_MODEL_DIR") or str(Path.home() / "Desktop" / "whisper_models")
LANGUAGE = os.getenv("LOCAL_STT_LANGUAGE", "ru")

logger = logging.getLogger("local_stt_server")
model = None


def load_model():
    global model
    if model is not None:
        return model
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster_whisper is not installed in this Python environment") from exc

    device = os.getenv("LOCAL_STT_DEVICE", "cpu")
    compute_type = os.getenv("LOCAL_STT_COMPUTE_TYPE", "int8")
    logger.info("Loading faster-whisper model=%s device=%s model_dir=%s", MODEL_SIZE, device, MODEL_DIR)
    model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute_type, download_root=MODEL_DIR)
    return model


def transcribe_file(path: Path) -> str:
    stt_model = load_model()
    segments, _ = stt_model.transcribe(
        str(path),
        language=LANGUAGE,
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )
    return " ".join(segment.text for segment in segments).strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "LocalWhisperSTT/1.0"

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(404)
            return
        self._send_json(200, {"status": "ok", "model": MODEL_SIZE})

    def do_POST(self) -> None:
        if self.path != "/transcribe":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            self._send_json(400, {"error": "empty body"})
            return

        filename = self.headers.get("X-Filename", "voice.ogg")
        suffix = Path(filename).suffix or ".ogg"
        payload = self.rfile.read(length)

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(payload)
                tmp_path = Path(tmp.name)
            text = transcribe_file(tmp_path)
        except Exception as exc:
            logger.exception("Transcription failed")
            self._send_json(500, {"error": str(exc)})
            return
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

        self._send_json(200, {"text": text})

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    logging.basicConfig(level=os.getenv("LOCAL_STT_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    try:
        load_model()
    except Exception:
        logger.exception("Failed to initialize local STT model")
        return 1
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    logger.info("Local STT server listening on http://%s:%s", HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopping local STT server")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
