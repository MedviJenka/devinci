"""Background CrewAI crew for complex multi-step coding tasks.

Planner reads the codebase and produces a numbered plan.
Coder executes the plan, reads files before editing, runs checks after.
Progress is streamed back via the `log` callback (→ WebSocket → dashboard).
"""
import subprocess
from pathlib import Path
from typing import Callable

from crewai import Agent, Crew, Task, Process, LLM
from crewai.tools import tool

from settings import Config


def _make_llm() -> LLM:
    ak = (
        Config.CLAUDE_API_KEY
        if Config.CLAUDE_API_KEY not in ("", ".")
        else Config.ANTHROPIC_API_KEY
    )
    return LLM(model="anthropic/claude-sonnet-4-6", api_key=ak)


def make_crew(
    task_description: str,
    working_dir: Path,
    log: Callable[[str, str], None],
) -> Crew:
    """Build a two-agent crew for the given task."""
    wd = working_dir
    llm = _make_llm()

    # ── tools ────────────────────────────────────────────────────────────────

    @tool("read_file")
    def read_file(path: str) -> str:
        """Read the full contents of a file in the project."""
        try:
            return (wd / path).read_text(encoding="utf-8")
        except Exception as e:
            return f"Error reading {path}: {e}"

    @tool("write_file")
    def write_file(path: str, content: str) -> str:
        """Write content to a file, creating parent directories as needed."""
        try:
            p = wd / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            log("info", f"wrote {path}")
            return f"Written {path}"
        except Exception as e:
            return f"Error writing {path}: {e}"

    @tool("list_directory")
    def list_directory(path: str = ".") -> str:
        """List files and folders at a path in the project."""
        try:
            p = wd / path
            return "\n".join(
                e.name + ("/" if e.is_dir() else "") for e in sorted(p.iterdir())
            )
        except Exception as e:
            return f"Error listing {path}: {e}"

    @tool("search_code")
    def search_code(pattern: str, glob: str = "**/*.py") -> str:
        """Search for a text pattern across project files."""
        try:
            r = subprocess.run(
                ["rg", pattern, "--glob", glob, "-n", "--max-count=20"],
                capture_output=True, text=True, cwd=wd, timeout=10,
            )
            return r.stdout or "No matches."
        except Exception as e:
            return f"Error: {e}"

    @tool("run_command")
    def run_command(command: str) -> str:
        """Run a shell command in the project directory (git, pytest, etc.)."""
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True,
                text=True, cwd=wd, timeout=30,
            )
            out = (r.stdout + r.stderr).strip()
            return out[:2000] or f"exit {r.returncode}"
        except Exception as e:
            return f"Error: {e}"

    read_tools = [read_file, list_directory, search_code]
    all_tools   = [read_file, write_file, list_directory, search_code, run_command]

    # ── agents ───────────────────────────────────────────────────────────────

    planner = Agent(
        role="Software Architect",
        goal="Analyse the codebase and produce a precise numbered implementation plan.",
        backstory=(
            "Expert at quickly understanding Python codebases and planning the minimal, "
            "safest changes needed. You never write code — only plans."
        ),
        tools=read_tools,
        llm=llm,
        verbose=False,
        max_iter=5,
    )

    coder = Agent(
        role="Senior Developer",
        goal="Implement the plan exactly — clean, working code, nothing beyond scope.",
        backstory=(
            "You read each file before editing it and run tests after writing. "
            "You implement precisely what the plan specifies."
        ),
        tools=all_tools,
        llm=llm,
        verbose=False,
        max_iter=10,
    )

    # ── tasks ────────────────────────────────────────────────────────────────

    plan_task = Task(
        description=(
            f"Working directory: {wd}\n\n"
            f"User task: {task_description}\n\n"
            "Explore the codebase as needed. Output a numbered plan: which files to change, "
            "what exactly to change in each, and why. Be specific — file paths and line-level detail."
        ),
        expected_output="A numbered implementation plan with file paths and specific changes.",
        agent=planner,
    )

    code_task = Task(
        description=(
            f"Working directory: {wd}\n\n"
            f"User task: {task_description}\n\n"
            "Execute the Planner's plan exactly. Read each file before writing. "
            "After writing files, run relevant tests or linters to verify. "
            "Return a concise one-sentence summary of what was done."
        ),
        expected_output="A one-sentence summary of the completed implementation.",
        agent=coder,
        context=[plan_task],
    )

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _step_cb(step_output) -> None:
        try:
            text = getattr(step_output, "result", None) or str(step_output)
            text = str(text).strip()
            if text:
                log("info", text[:140])
        except Exception:
            pass

    return Crew(
        agents=[planner, coder],
        tasks=[plan_task, code_task],
        process=Process.sequential,
        step_callback=_step_cb,
        verbose=False,
    )
