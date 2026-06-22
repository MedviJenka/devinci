"""Standalone asyncio pipeline — serves state over WebSocket for Electron UI."""
import asyncio
import io
import json
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from websockets.asyncio.server import ServerConnection, serve as ws_serve

from settings import Config

WS_PORT = 7788
SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 1_024
ENERGY_THRESHOLD = 0.008
SILENCE_CHUNKS = 22
WAKE_PHRASES = ("hey claude", "hey, claude", "ok claude", "okay claude")
SESSION_WINDOW = 60.0

_clients: set[ServerConnection] = set()

_SYSTEM = """You are a voice coding assistant. Keep all responses to 1-2 short spoken sentences.
No markdown, no code blocks. When you write or edit a file say "Done, I wrote [what] to [file]".
Be direct and concise."""

_TOOLS = [
    {"name": "read_file",      "description": "Read a file.",               "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},                                                    "required": ["path"]}},
    {"name": "write_file",     "description": "Write content to a file.",   "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},                     "required": ["path", "content"]}},
    {"name": "list_directory", "description": "List directory contents.",   "input_schema": {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}},
    {"name": "search_code",    "description": "Search files for pattern.",  "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "glob": {"type": "string", "default": "**/*.py"}}, "required": ["pattern"]}},
    {"name": "run_command",    "description": "Run a shell command.",        "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},                                                 "required": ["command"]}},
]


async def _broadcast(state: str) -> None:
    if not _clients:
        return
    msg = json.dumps({"state": state})
    await asyncio.gather(*[c.send(msg) for c in list(_clients)], return_exceptions=True)


async def _ws_handler(ws: ServerConnection) -> None:
    _clients.add(ws)
    print(f"[ws] client connected ({len(_clients)})")
    try:
        await ws.wait_closed()
    finally:
        _clients.discard(ws)
        print(f"[ws] client disconnected ({len(_clients)})")


def _extract_command(transcript: str) -> str:
    for phrase in WAKE_PHRASES:
        idx = transcript.lower().find(phrase)
        if idx != -1:
            after = transcript[idx + len(phrase):].strip(" ,.")
            if after:
                return after
    return transcript


class Pipeline:
    def __init__(self) -> None:
        self._running = True
        self._stop_ev = threading.Event()
        self._last_activation = 0.0
        self._wd = Path(Config.WORKING_DIR).resolve()

    async def run(self) -> None:
        ak = Config.CLAUDE_API_KEY if Config.CLAUDE_API_KEY not in ("", ".") else Config.ANTHROPIC_API_KEY
        ok = Config.OPENAI_API_KEY
        print(f"[pipeline] Anthropic key : {'ok' if ak and ak not in ('sk-ant-...', '.', '') else 'MISSING'}")
        print(f"[pipeline] OpenAI key    : {'ok' if ok and ok not in ('sk-...', '') else 'MISSING — Whisper/TTS disabled'}")
        print(f"[pipeline] Working dir   : {self._wd}")
        print(f"[pipeline] WebSocket     : ws://localhost:{WS_PORT}")
        print("[pipeline] Listening for microphone...")

        openai = AsyncOpenAI(api_key=ok)
        claude = AsyncAnthropic(api_key=ak)

        while self._running:
            await _broadcast("standby")
            self._stop_ev.clear()

            audio = await asyncio.get_event_loop().run_in_executor(None, self._capture)
            if audio is None or len(audio) < SAMPLE_RATE * 0.25:
                continue

            await _broadcast("processing")
            print(f"[pipeline] captured {len(audio)/SAMPLE_RATE:.1f}s → transcribing...")
            transcript = await self._stt(openai, audio)
            print(f"[pipeline] transcript: {transcript!r}")
            if not transcript:
                continue

            text = transcript.lower()
            if any(p in text for p in WAKE_PHRASES):
                self._last_activation = time.monotonic()
            elif time.monotonic() - self._last_activation > SESSION_WINDOW:
                continue

            await _broadcast("listening")
            command = _extract_command(transcript)
            await asyncio.sleep(0.08)

            await _broadcast("processing")
            response = await self._ask_claude(claude, command)
            print(f"[pipeline] response: {response!r}")

            if response:
                await _broadcast("speaking")
                await asyncio.get_event_loop().run_in_executor(
                    None, self._speak_sync, openai, response
                )

    # ── audio capture ──────────────────────────────────────────────────────────

    def _capture(self) -> np.ndarray | None:
        chunks: list[np.ndarray] = []
        silence = [0]
        active = [False]
        done = threading.Event()

        def cb(indata, _frames, _t, _status):
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

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=CHUNK_SAMPLES, callback=cb):
            while not done.is_set() and not self._stop_ev.is_set():
                done.wait(timeout=1.0)

        return np.concatenate(chunks) if chunks and self._running else None

    # ── STT ────────────────────────────────────────────────────────────────────

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

    # ── LLM ────────────────────────────────────────────────────────────────────

    async def _ask_claude(self, client: AsyncAnthropic, command: str) -> str:
        messages: list = [{"role": "user", "content": command}]
        for _ in range(6):
            try:
                resp = await client.messages.create(
                    model="claude-sonnet-4-6", max_tokens=450,
                    system=_SYSTEM, tools=_TOOLS, messages=messages,
                )
            except Exception as e:
                return f"Error: {e}"

            if resp.stop_reason != "tool_use":
                return next((b.text for b in resp.content if hasattr(b, "text")), "")

            results = []
            for block in resp.content:
                if block.type == "tool_use":
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": self._run_tool(block.name, block.input)})
            messages += [{"role": "assistant", "content": resp.content},
                         {"role": "user",      "content": results}]
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
                    return "\n".join(e.name + ("/" if e.is_dir() else "") for e in sorted(p.iterdir()))
                case "search_code":
                    r = subprocess.run(
                        ["rg", args["pattern"], "--glob", args.get("glob", "**/*.py"), "-n", "--max-count=15"],
                        capture_output=True, text=True, cwd=self._wd, timeout=10)
                    return r.stdout or "No matches."
                case "run_command":
                    r = subprocess.run(args["command"], shell=True, capture_output=True,
                                       text=True, cwd=self._wd, timeout=30)
                    return (r.stdout + r.stderr)[:1500] or f"exit {r.returncode}"
        except Exception as e:
            return f"Error: {e}"
        return "Unknown tool."

    # ── TTS ────────────────────────────────────────────────────────────────────

    def _speak_sync(self, client: AsyncOpenAI, text: str) -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._speak_async(client, text))
        finally:
            loop.close()

    async def _speak_async(self, client: AsyncOpenAI, text: str) -> None:
        try:
            resp = await client.audio.speech.create(
                model="tts-1", voice="shimmer", input=text, response_format="pcm")
            pcm = np.frombuffer(resp.content, dtype=np.int16).astype(np.float32) / 32_768.0
            sd.play(pcm, samplerate=24_000)
            sd.wait()
        except Exception as e:
            print(f"[pipeline] TTS error: {e}")


async def _main() -> None:
    pipeline = Pipeline()
    async with ws_serve(_ws_handler, "localhost", WS_PORT):
        print(f"[ws] server ready on ws://localhost:{WS_PORT}")
        await pipeline.run()


if __name__ == "__main__":
    asyncio.run(_main())
