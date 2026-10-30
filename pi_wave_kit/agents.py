"""One interface for running coding-agent jobs on pi, OpenCode, Codex or Claude Code: start a job
(non-blocking, usable as run_wave's launch_fn), resume an existing session with a new message (the
headless way to steer it), and collect the result -- final text, session id, real token counts --
optionally logged to the cost ledger. Issue #12; the research behind it is
wiki/research/coding-agents-keys-logins-and-control.md.

pi keeps its own tested path (run_pi's session-file cost reading). The other three are run in their
one-shot JSON modes, and their usage is read from what they print -- shapes captured live from the
installed binaries on 2026-10-30:

- opencode run --format json: JSON lines; `sessionID` on every event; `text` events carry the
  answer; each `step_finish` carries `tokens` {input, output, reasoning, cache{read, write}} (input
  excludes cache) and its own `cost`.
- codex exec --json: JSON lines; `thread.started.thread_id`; `item.completed` items of type
  `agent_message` carry the answer; `turn.completed.usage` has input_tokens (INCLUDES cached),
  cached_input_tokens, output_tokens, reasoning_output_tokens; no cost at all.
- claude -p --output-format json: one JSON object; `session_id`, `result`, `usage`
  {input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens}, the model as
  the key of `modelUsage`, `total_cost_usd`, `is_error`.

`env` on every call adds variables for that one process -- how a job runs on a given client's API
key or config home (CODEX_HOME, CLAUDE_CONFIG_DIR, PI_CODING_AGENT_DIR, DEEPSEEK_API_KEY, ...)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from llm_ledger_client import LedgerClient

from . import run_pi as pi
from .wave import WaveJobResult

_logger = logging.getLogger("pi_wave_kit.agents")

AGENTS = ("pi", "opencode", "codex", "claude")

# The provider name each agent's own API bills under, for the ledger (OpenCode and pi name it per call).
_FIXED_PROVIDER = {"codex": "openai", "claude": "anthropic"}

# Variables a parent Claude Code session sets that change how a child `claude` behaves (a child that
# inherits them silently stops saving its transcript -- found live in agent-watch-daemon's tests).
_CLAUDE_PARENT_VARS = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT")


@dataclass
class AgentResult:
    job_id: str
    agent: str
    returncode: int | None
    wall_seconds: float
    session_id: str  # pass back as `session_id` to resume; for pi it is the session FILE path
    text: str  # the agent's final answer, as printed (empty for pi: read it from the session file)
    timed_out: bool = False
    error: str = ""
    provider: str = ""
    # "<provider>/<model>", the ledger's ModelPricing key (a bare model name is booked at $0), same as
    # run_pi's PiResult.model.
    model: str = ""
    prompt_tokens: int = 0  # input not served from cache
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0  # informational; already inside completion_tokens
    reported_cost_usd: float = 0.0  # the agent's OWN figure -- evidence only; the ledger prices tokens itself
    billing: str = "api"  # "api" or "subscription"
    output_path: Path | None = None
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.error


@dataclass
class AgentHandle:
    """A started job. `proc.poll()` works like run_pi's handles, so run_wave can schedule it."""

    job_id: str
    agent: str
    proc: subprocess.Popen
    started_monotonic: float
    timeout_seconds: float | None
    model: str
    billing: str
    output_path: Path | None = None
    output_file: object = None
    stderr_file: object = None
    resumed_session: str = ""
    pi_handle: object = None  # the wrapped run_pi handle, for agent == "pi"


def split_model(model: str) -> tuple[str, str]:
    """"deepseek/deepseek-flash" -> ("deepseek", "deepseek-flash"); no slash -> ("", model)."""
    provider, sep, name = model.partition("/")
    return (provider, name) if sep else ("", model)


def default_billing(agent: str, model: str, env: dict | None = None) -> str:
    """Best guess at whether this job spends API money or rides a subscription; pass `billing`
    explicitly when you know. An API key in the environment means API billing for Claude Code and
    Codex; otherwise they are on the logged-in subscription. pi/OpenCode bill the provider's API,
    except GitHub Copilot, which is a subscription."""
    effective = {**os.environ, **(env or {})}
    if agent == "claude":
        return "api" if effective.get("ANTHROPIC_API_KEY") else "subscription"
    if agent == "codex":
        return "api" if effective.get("CODEX_API_KEY") else "subscription"
    return "subscription" if split_model(model)[0] == "github-copilot" else "api"


def build_command(agent: str, *, prompt: str, model: str, session_id: str = "",
                  extra_args: list[str] | None = None) -> list[str]:
    """The argv for one opencode/codex/claude job; a non-empty `session_id` resumes that session."""
    extra = list(extra_args or [])
    if agent == "opencode":
        cmd = ["opencode", "run", "--format", "json", "-m", model]
        if session_id:
            cmd += ["--session", session_id]
        return cmd + extra + [prompt]
    if agent == "codex":
        cmd = ["codex", "exec"] + (["resume"] if session_id else [])
        cmd += ["--json", "--skip-git-repo-check"] + (["-m", model] if model else []) + extra
        return cmd + ([session_id] if session_id else []) + [prompt]
    if agent == "claude":
        cmd = ["claude", "-p", "--output-format", "json"] + (["--model", model] if model else [])
        if session_id:
            cmd += ["--resume", session_id]
        return cmd + extra + [prompt]
    raise ValueError(f"unknown agent {agent!r}; expected one of {AGENTS}")


def _child_env(agent: str, env: dict | None) -> dict:
    merged = {**os.environ, **(env or {})}
    if agent == "claude":
        for name in _CLAUDE_PARENT_VARS:
            merged.pop(name, None)
    return merged


def start_agent(
    agent: str,
    job_id: str,
    *,
    prompt: str,
    model: str,
    cwd: str | Path,
    out_dir: str | Path,
    session_id: str = "",
    extra_args: list[str] | None = None,
    timeout_seconds: float | None = None,
    env: dict | None = None,
    billing: str | None = None,
    thinking: str = "low",
    cgroup: pi.CgroupLimits | None = None,
) -> AgentHandle:
    """Non-blocking. `model` is "provider/model" for pi and opencode, the agent's own model name for
    codex and claude. Output goes under `out_dir` (one directory per job: output.jsonl, stderr.log;
    pi also keeps its sessions/ there). `session_id` resumes instead of starting fresh: an
    AgentResult.session_id from an earlier job (for pi, the session file path)."""
    if agent not in AGENTS:
        raise ValueError(f"unknown agent {agent!r}; expected one of {AGENTS}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    billing = billing or default_billing(agent, model, env)

    if agent == "pi":
        provider, name = split_model(model)
        common = dict(provider=provider or "deepseek", model=name, thinking=thinking, prompt=prompt, cwd=cwd,
                      extra_args=extra_args, timeout_seconds=timeout_seconds, log_path=out_dir / "log.txt",
                      cgroup=cgroup, env=env)
        if session_id:
            inner = pi.start_pi_resume(job_id, session=session_id, **common)
        else:
            inner = pi.start_pi(job_id, session_dir=out_dir / "sessions", **common)
        return AgentHandle(job_id=job_id, agent=agent, proc=inner.proc, started_monotonic=inner.started_monotonic,
                           timeout_seconds=timeout_seconds, model=model, billing=billing,
                           resumed_session=session_id, pi_handle=inner)

    cmd = build_command(agent, prompt=prompt, model=model, session_id=session_id, extra_args=extra_args)
    if cgroup is not None:
        cmd = cgroup.systemd_run_prefix() + cmd
    output_path = out_dir / "output.jsonl"
    out_f = open(output_path, "w", encoding="utf-8")
    err_f = open(out_dir / "stderr.log", "w", encoding="utf-8")
    # Own process group, so a timeout kill reaches whatever the agent spawned (run_pi does the same).
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f,
                            start_new_session=True, env=_child_env(agent, env))
    _logger.info("agents: started %s job %s (%s)%s", agent, job_id, model,
                 f", resuming {session_id}" if session_id else "")
    return AgentHandle(job_id=job_id, agent=agent, proc=proc, started_monotonic=time.monotonic(),
                       timeout_seconds=timeout_seconds, model=model, billing=billing, output_path=output_path,
                       output_file=out_f, stderr_file=err_f, resumed_session=session_id)


def _json_lines(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def parse_opencode(text: str) -> dict:
    out = {"session_id": "", "texts": [], "error": "", "prompt": 0, "completion": 0, "reasoning": 0,
           "cache_read": 0, "cache_write": 0, "cost": 0.0}
    for ev in _json_lines(text):
        out["session_id"] = out["session_id"] or ev.get("sessionID", "")
        part = ev.get("part") or {}
        if ev.get("type") == "text" and part.get("text"):
            out["texts"].append(part["text"])
        elif ev.get("type") == "step_finish":
            tokens = part.get("tokens") or {}
            cache = tokens.get("cache") or {}
            out["prompt"] += tokens.get("input", 0)
            # OpenCode counts reasoning apart from output; both are billed as output tokens.
            out["completion"] += tokens.get("output", 0) + tokens.get("reasoning", 0)
            out["reasoning"] += tokens.get("reasoning", 0)
            out["cache_read"] += cache.get("read", 0)
            out["cache_write"] += cache.get("write", 0)
            out["cost"] += part.get("cost") or 0.0
        elif ev.get("type") == "error":
            err = ev.get("error") or {}
            out["error"] = (err.get("data") or {}).get("message") or err.get("name") or "error"
    return out


def parse_codex(text: str) -> dict:
    out = {"session_id": "", "texts": [], "error": "", "prompt": 0, "completion": 0, "reasoning": 0,
           "cache_read": 0, "cache_write": 0, "cost": 0.0}
    for ev in _json_lines(text):
        kind = ev.get("type")
        if kind == "thread.started":
            out["session_id"] = ev.get("thread_id", "")
        elif kind == "item.completed":
            item = ev.get("item") or {}
            if item.get("type") == "agent_message" and item.get("text"):
                out["texts"].append(item["text"])
        elif kind == "turn.completed":
            usage = ev.get("usage") or {}
            cached = usage.get("cached_input_tokens", 0)
            written = usage.get("cache_write_input_tokens", 0)
            # input_tokens includes the cached part (OpenAI convention): split it out so cached input
            # is never priced twice.
            out["prompt"] += max(0, usage.get("input_tokens", 0) - cached - written)
            out["cache_read"] += cached
            out["cache_write"] += written
            out["completion"] += usage.get("output_tokens", 0)
            out["reasoning"] += usage.get("reasoning_output_tokens", 0)
        elif kind in ("turn.failed", "error"):
            err = ev.get("error") if kind == "turn.failed" else ev
            out["error"] = (err or {}).get("message", "error")
    return out


def parse_claude(text: str) -> dict:
    out = {"session_id": "", "texts": [], "error": "", "prompt": 0, "completion": 0, "reasoning": 0,
           "cache_read": 0, "cache_write": 0, "cost": 0.0, "model": ""}
    results = [ev for ev in _json_lines(text) if ev.get("type") == "result"]
    if not results:
        return out
    res = results[-1]
    usage = res.get("usage") or {}
    out.update(
        session_id=res.get("session_id", ""),
        texts=[res["result"]] if res.get("result") else [],
        prompt=usage.get("input_tokens", 0),
        completion=usage.get("output_tokens", 0),
        reasoning=(usage.get("output_tokens_details") or {}).get("thinking_tokens", 0),
        cache_read=usage.get("cache_read_input_tokens", 0),
        cache_write=usage.get("cache_creation_input_tokens", 0),
        cost=res.get("total_cost_usd") or 0.0,
        model=next(iter(res.get("modelUsage") or {}), ""),
    )
    if res.get("is_error"):
        out["error"] = res.get("result") or res.get("subtype") or "error"
    return out


_PARSERS = {"opencode": parse_opencode, "codex": parse_codex, "claude": parse_claude}


def kill_if_timed_out(handle: AgentHandle) -> bool:
    """run_wave's is_timed_out hook: kills the job's whole process group once past its timeout."""
    if handle.timeout_seconds is None or time.monotonic() - handle.started_monotonic <= handle.timeout_seconds:
        return False
    pi._kill_group(handle.proc)
    return True


def collect_agent_result(
    handle: AgentHandle,
    *,
    timed_out: bool = False,
    ledger: LedgerClient | None = None,
    run_pk: int | None = None,
    call_purpose: str = "",
) -> AgentResult:
    """Call once `handle.proc.poll()` is not None (or after a timeout kill). With `ledger` and
    `run_pk`, the real token counts are logged to that run before returning (idempotent by job id)."""
    if handle.agent == "pi":
        return _collect_pi(handle, timed_out, ledger, run_pk, call_purpose)

    for f in (handle.output_file, handle.stderr_file):
        if f is not None:
            f.close()
    wall = time.monotonic() - handle.started_monotonic
    raw = handle.output_path.read_text(encoding="utf-8") if handle.output_path else ""
    parsed = _PARSERS[handle.agent](raw)

    if handle.agent == "opencode":
        provider = split_model(handle.model)[0]
        model = handle.model
    else:
        provider = _FIXED_PROVIDER[handle.agent]
        model = f"{provider}/{parsed.get('model') or handle.model}"
    error = parsed["error"]
    if not error and handle.proc.returncode not in (0, None) and not timed_out:
        error = _stderr_tail(handle)
    result = AgentResult(
        job_id=handle.job_id, agent=handle.agent, returncode=handle.proc.returncode, wall_seconds=wall,
        session_id=parsed["session_id"] or handle.resumed_session, text="\n".join(parsed["texts"]),
        timed_out=timed_out, error=error, provider=provider, model=model,
        prompt_tokens=parsed["prompt"], completion_tokens=parsed["completion"],
        cache_read_tokens=parsed["cache_read"], cache_creation_tokens=parsed["cache_write"],
        reasoning_tokens=parsed["reasoning"], reported_cost_usd=parsed["cost"], billing=handle.billing,
        output_path=handle.output_path,
        extra={"resumed_session": handle.resumed_session} if handle.resumed_session else {},
    )
    if ledger is not None and run_pk is not None:
        _log(ledger, run_pk, result, call_purpose)
    return result


def _stderr_tail(handle: AgentHandle, lines: int = 5) -> str:
    path = handle.output_path.parent / "stderr.log" if handle.output_path else None
    if not path or not path.is_file():
        return f"exited {handle.proc.returncode}"
    tail = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-lines:]
    return "\n".join(tail) or f"exited {handle.proc.returncode}"


def _collect_pi(handle, timed_out, ledger, run_pk, call_purpose) -> AgentResult:
    inner = handle.pi_handle
    if isinstance(inner, pi.PiResumeHandle):
        res = pi.collect_pi_resume_result(inner, timed_out=timed_out, ledger=ledger, run_pk=run_pk,
                                          call_purpose=call_purpose)
    else:
        res = pi.collect_pi_result(inner, timed_out=timed_out, ledger=ledger, run_pk=run_pk,
                                   call_purpose=call_purpose)
    return AgentResult(
        job_id=res.job_id, agent="pi", returncode=res.returncode, wall_seconds=res.wall_seconds,
        session_id=str(res.session_file) if res.session_file else handle.resumed_session, text="",
        timed_out=res.timed_out, provider=res.provider, model=res.model,
        prompt_tokens=res.prompt_tokens, completion_tokens=res.completion_tokens,
        cache_read_tokens=res.cache_read_tokens, cache_creation_tokens=res.cache_creation_tokens,
        reported_cost_usd=res.cost_usd, billing=handle.billing, extra=res.extra,
    )


def _log(ledger: LedgerClient, run_pk: int, result: AgentResult, call_purpose: str) -> None:
    if not result.provider or not result.model:
        _logger.warning("agents: %s job %s reported no provider/model, nothing logged", result.agent, result.job_id)
        return
    if not (result.prompt_tokens or result.completion_tokens or result.cache_read_tokens):
        _logger.warning("agents: %s job %s reported no usage, nothing logged", result.agent, result.job_id)
        return
    resume = f":resume:{result.session_id}" if result.extra.get("resumed_session") else ""
    ledger.log_call(
        run_pk, provider=result.provider, model=result.model,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        cache_read_tokens=result.cache_read_tokens, cache_creation_tokens=result.cache_creation_tokens,
        billing=result.billing, external_id=f"pi-wave-kit:{result.agent}:{result.job_id}{resume}",
        call_purpose=call_purpose,
        # The agent's own figure, kept as evidence beside the ledger's own price (6 decimals or the API 400s).
        api_equivalent_cost_usd=round(result.reported_cost_usd, 6) if result.reported_cost_usd else None,
    )


def run_agent(agent: str, job_id: str, *, ledger: LedgerClient | None = None, run_pk: int | None = None,
              call_purpose: str = "", **kwargs) -> AgentResult:
    """Blocking: start one job (or resume, with `session_id=`), wait, collect."""
    handle = start_agent(agent, job_id, **kwargs)
    timed_out = False
    try:
        handle.proc.wait(timeout=handle.timeout_seconds)
    except subprocess.TimeoutExpired:
        pi._kill_group(handle.proc)
        timed_out = True
    return collect_agent_result(handle, timed_out=timed_out, ledger=ledger, run_pk=run_pk,
                                call_purpose=call_purpose)


def to_wave_result(result: AgentResult) -> WaveJobResult:
    """Adapter for run_wave's collect_fn. The cost counted against the wave cap is the agent's own
    reported figure -- Codex reports none, so a Codex job counts $0 there (the ledger still prices
    its tokens)."""
    status = "success" if result.ok else "failed"
    reason = "timed out" if result.timed_out else result.error
    return WaveJobResult(job_id=result.job_id, status=status, cost_usd=result.reported_cost_usd, reason=reason,
                         wall_seconds=result.wall_seconds,
                         extra={"agent": result.agent, "session_id": result.session_id})
