import time
import subprocess
import fnmatch
from pathlib import Path
from livekit.agents import AgentSession, Agent, JobContext, WorkerOptions, cli
from livekit.agents.llm import function_tool
from livekit.plugins import openai as lkopenai
from livekit.plugins import anthropic as lkanthropic
from livekit.plugins import silero
from settings import Config

WAKE_PHRASES = ("hey claude", "hey, claude", "okay claude", "ok claude")
SESSION_WINDOW = 60.0  # seconds before returning to standby after last activation

INSTRUCTIONS = """You are a voice-activated coding assistant named Claude.
The user works in a project directory and gives you coding tasks by voice.

Rules for spoken responses:
- Be concise — one or two sentences unless asked for detail
- Never read code aloud — describe what you did instead
- Say file paths naturally: "main dot py", "api slash v1 slash routes dot py"
- Confirm actions briefly: "Done, I added the endpoint to api/v1/routes.py"

You have tools to read, write, list, search, and run commands in the project.
"""


class VoiceCodingAgent(Agent):

    def __init__(self, working_dir: Path):
        super().__init__(instructions=INSTRUCTIONS)
        self._wd = working_dir
        self._last_activation: float = 0.0

    def _is_session_active(self) -> bool:
        return time.monotonic() - self._last_activation < SESSION_WINDOW

    def _activate(self) -> None:
        self._last_activation = time.monotonic()

    async def llm_node(self, chat_ctx, tools, model_settings):
        last_user = next((m for m in reversed(chat_ctx.messages) if m.role == "user"), None)

        if last_user is not None:
            text = (last_user.text_content or "").lower()

            if any(phrase in text for phrase in WAKE_PHRASES):
                self._activate()
            elif not self._is_session_active():
                return  # not addressed — stay silent

        async for chunk in super().llm_node(chat_ctx, tools, model_settings):
            yield chunk

    @function_tool
    async def read_file(self, path: str) -> str:
        """Read the contents of a file in the project."""
        try:
            return (self._wd / path).read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading {path}: {e}"

    @function_tool
    async def write_file(self, path: str, content: str) -> str:
        """Write content to a file. Creates parent directories if needed."""
        try:
            p = self._wd / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Written {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    @function_tool
    async def list_directory(self, path: str = ".") -> str:
        """List files and folders at the given path in the project."""
        try:
            p = self._wd / path
            return "\n".join(
                e.name + ("/" if e.is_dir() else "")
                for e in sorted(p.iterdir())
            )
        except Exception as e:
            return f"Error listing {path}: {e}"

    @function_tool
    async def search_code(self, pattern: str, glob: str = "**/*.py") -> str:
        """Search for a text pattern across project files."""
        try:
            result = subprocess.run(
                ["rg", pattern, "--glob", glob, "-n", "--max-count=20"],
                capture_output=True, text=True, cwd=self._wd, timeout=10,
            )
            return result.stdout or "No matches found."
        except FileNotFoundError:
            matches = []
            ext = glob.split("/")[-1]
            for f in self._wd.rglob("*"):
                if fnmatch.fnmatch(f.name, ext):
                    try:
                        for i, line in enumerate(
                            f.read_text(errors="ignore").splitlines(), 1
                        ):
                            if pattern.lower() in line.lower():
                                matches.append(
                                    f"{f.relative_to(self._wd)}:{i}: {line.strip()}"
                                )
                    except Exception:
                        pass
            return "\n".join(matches[:20]) or "No matches found."
        except Exception as e:
            return f"Error: {e}"

    @function_tool
    async def run_command(self, command: str) -> str:
        """Run a shell command in the project directory (e.g. git status, pytest)."""
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=self._wd, timeout=30)
            out = (result.stdout + result.stderr).strip()
            return out[:2000] if out else f"Exit code {result.returncode}"

        except subprocess.TimeoutExpired:
            return "Command timed out after 30 seconds."

        except Exception as e:
            return f"Error: {e}"


async def entrypoint(ctx: JobContext):
    await ctx.connect()

    working_dir = Path(Config.WORKING_DIR).resolve()

    session = AgentSession(
        stt=lkopenai.STT(model="whisper-1"),
        llm=lkanthropic.LLM(model="claude-sonnet-4-6"),
        tts=lkopenai.TTS(voice="shimmer"),
        vad=silero.VAD.load(),
    )

    agent = VoiceCodingAgent(working_dir=working_dir)
    await session.start(ctx.room, agent=agent)
    await session.say(text="Ready. Say hey Claude to start.", allow_interruptions=False)


if __name__ == "__main__":
    worker = WorkerOptions(
        entrypoint_fnc=entrypoint,
        ws_url=Config.LIVEKIT_URL or Config.LIVEKIT_WEBSOCKET_URL,
        api_key=Config.LIVEKIT_API_KEY,
        api_secret=Config.LIVEKIT_API_SECRET,
    )
    cli.run_app(worker)
