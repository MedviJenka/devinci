import asyncio
import io
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from PyQt6.QtCore import QThread, pyqtSignal

from settings import Config

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_024          # ~64 ms per chunk
ENERGY_THRESHOLD = 0.008       # tune per microphone
SILENCE_CHUNKS = 22            # ~1.4 s of silence ends an utterance
WAKE_PHRASES = ("hey claude", "hey, claude", "ok claude", "okay claude")
SESSION_WINDOW = 60.0          # seconds to stay active after last wake

_SYSTEM = """You are a voice coding assistant. Keep all responses to 1-2 short spoken sentences.
No markdown, no code blocks. When you write or edit a file say "Done, I wrote [what] to [file]".
Be direct and concise."""

_TOOLS = [
    {
        "name": "read_file",
        "description": "Read the contents of a file in the project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates parent dirs if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_directory",
        "description": "List files and folders at a path in the project.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "search_code",
        "description": "Search for a text pattern across project files.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "glob": {"type": "string", "default": "**/*.py"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command in the project directory (git, pytest…).",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
]


class PipelineThread(QThread):
    state_changed = pyqtSignal(str)   # "standby" | "listening" | "processing" | "speaking"

    def __init__(self):
        super().__init__()
        self._running = True
        self._stop_capture = threading.Event()
        self._last_activation = 0.0
        self._wd = Path(Config.WORKING_DIR).resolve()

    def stop(self):
        self._running = False
        self._stop_capture.set()

    # ── thread entry ──────────────────────────────────────────────────────────

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._pipeline())
        except Exception as e:
            print(f"[pipeline] fatal error: {e}")

    async def _pipeline(self):
        anthropic_key = Config.CLAUDE_API_KEY if Config.CLAUDE_API_KEY not in ("", ".") else Config.ANTHROPIC_API_KEY
        openai_key = Config.OPENAI_API_KEY
        print(f"[pipeline] Anthropic key: {'set' if anthropic_key and anthropic_key not in ('sk-ant-...', '.', '') else 'MISSING'}")
        print(f"[pipeline] OpenAI key:    {'set' if openai_key and openai_key not in ('sk-...', '') else 'MISSING — need real key for Whisper/TTS'}")
        print(f"[pipeline] Working dir:   {self._wd}")
        print("[pipeline] Listening for microphone...")

        openai = AsyncOpenAI(api_key=openai_key)
        claude = AsyncAnthropic(api_key=anthropic_key)

        while self._running:
            self.state_changed.emit("standby")
            self._stop_capture.clear()

            audio = await asyncio.get_event_loop().run_in_executor(None, self._capture)
            if audio is None or len(audio) < SAMPLE_RATE * 0.25:
                continue

            self.state_changed.emit("processing")
            print(f"[pipeline] Captured {len(audio)/SAMPLE_RATE:.1f}s — transcribing...")
            transcript = await self._stt(openai, audio)
            print(f"[pipeline] Transcript: {transcript!r}")
            if not transcript:
                continue

            text = transcript.lower()
            has_wake = any(p in text for p in WAKE_PHRASES)

            if has_wake:
                self._last_activation = time.monotonic()
            elif time.monotonic() - self._last_activation > SESSION_WINDOW:
                continue                         # not addressed — stay silent

            self.state_changed.emit("listening")
            command = _extract_command(transcript)
            await asyncio.sleep(0.08)

            self.state_changed.emit("processing")
            response = await self._ask_claude(claude, command)

            if response:
                self.state_changed.emit("speaking")
                await asyncio.get_event_loop().run_in_executor(
                    None, self._speak_sync, openai, response
                )

    # ── audio capture ─────────────────────────────────────────────────────────

    def _capture(self) -> np.ndarray | None:
        chunks: list[np.ndarray] = []
        silence = [0]
        active = [False]
        done = threading.Event()

        def cb(indata, _frames, _cb_time, _status):
            energy = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            if energy > ENERGY_THRESHOLD:
                active[0] = True
                silence[0] = 0
            elif active[0]:
                silence[0] += 1
                if silence[0] >= SILENCE_CHUNKS:
                    done.set()
                    return
            if active[0]:
                chunks.append(indata.copy().flatten().astype(np.float32))

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=CHUNK_SAMPLES,
            callback=cb,
        ):
            while not done.is_set() and not self._stop_capture.is_set():
                done.wait(timeout=1.0)

        if not chunks or not self._running:
            return None
        return np.concatenate(chunks)

    # ── STT ──────────────────────────────────────────────────────────────────

    async def _stt(self, client: AsyncOpenAI, audio: np.ndarray) -> str:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio * 32_767).astype(np.int16).tobytes())
        buf.seek(0)
        buf.name = "audio.wav"
        try:
            r = await client.audio.transcriptions.create(model="whisper-1", file=buf)
            return r.text.strip()
        except Exception as e:
            print(f"[pipeline] STT error: {e}")
            return ""

    # ── LLM ──────────────────────────────────────────────────────────────────

    async def _ask_claude(self, client: AsyncAnthropic, command: str) -> str:
        messages = [{"role": "user", "content": command}]
        for _ in range(6):
            try:
                resp = await client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=450,
                    system=_SYSTEM,
                    tools=_TOOLS,
                    messages=messages,
                )
            except Exception as e:
                return f"Error reaching Claude: {e}"

            if resp.stop_reason != "tool_use":
                return next((b.text for b in resp.content if hasattr(b, "text")), "")

            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = self._run_tool(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": results})

        return "Done."

    def _run_tool(self, name: str, args: dict) -> str:
        try:
            match name:
                case "read_file":
                    return (self._wd / args["path"]).read_text(encoding="utf-8")
                case "write_file":
                    p = self._wd / args["path"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(args["content"], encoding="utf-8")
                    return f"Written {args['path']}"
                case "list_directory":
                    p = self._wd / args.get("path", ".")
                    return "\n".join(
                        e.name + ("/" if e.is_dir() else "") for e in sorted(p.iterdir())
                    )
                case "search_code":
                    r = subprocess.run(
                        ["rg", args["pattern"], "--glob", args.get("glob", "**/*.py"), "-n", "--max-count=15"],
                        capture_output=True, text=True, cwd=self._wd, timeout=10,
                    )
                    return r.stdout or "No matches."
                case "run_command":
                    r = subprocess.run(
                        args["command"], shell=True, capture_output=True,
                        text=True, cwd=self._wd, timeout=30,
                    )
                    return (r.stdout + r.stderr)[:1500] or f"exit {r.returncode}"
        except Exception as e:
            return f"Error: {e}"
        return "Unknown tool."

    # ── TTS + playback (runs in executor, no async clients needed) ────────────

    def _speak_sync(self, client: AsyncOpenAI, text: str) -> None:
        import asyncio as _asyncio
        loop = _asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._speak_async(client, text))
        finally:
            loop.close()

    async def _speak_async(self, client: AsyncOpenAI, text: str) -> None:
        try:
            resp = await client.audio.speech.create(
                model="tts-1",
                voice="shimmer",
                input=text,
                response_format="pcm",   # raw 24 kHz 16-bit mono
            )
            pcm = np.frombuffer(resp.content, dtype=np.int16).astype(np.float32) / 32_768.0
            sd.play(pcm, samplerate=24_000)
            sd.wait()
        except Exception:
            pass


# ── helpers ───────────────────────────────────────────────────────────────────

def _extract_command(transcript: str) -> str:
    for phrase in WAKE_PHRASES:
        idx = transcript.lower().find(phrase)
        if idx != -1:
            after = transcript[idx + len(phrase):].strip(" ,.")
            if after:
                return after
    return transcript
