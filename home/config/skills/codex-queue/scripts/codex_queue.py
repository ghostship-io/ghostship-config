#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from string import Template


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parents[1]
TEMPLATE_PATH = SKILL_DIR / "references" / "worker-prompt-template.md"

DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_BATCH_SIZE = 10
DEFAULT_MONITOR_INTERVAL = 300
DEFAULT_STATE_ROOT = "codex-queue"

SMOKE_SITES = [
    ("site-01", "https://example.com"),
    ("site-02", "https://www.iana.org/domains/reserved"),
    ("site-03", "https://www.w3.org/"),
    ("site-04", "https://www.gnu.org/"),
    ("site-05", "https://www.kernel.org/"),
    ("site-06", "https://www.debian.org/"),
    ("site-07", "https://archlinux.org/"),
    ("site-08", "https://www.nixos.org/"),
    ("site-09", "https://www.python.org/"),
    ("site-10", "https://docs.python.org/3/"),
    ("site-11", "https://www.rust-lang.org/"),
    ("site-12", "https://nodejs.org/"),
    ("site-13", "https://www.npmjs.com/"),
    ("site-14", "https://git-scm.com/"),
    ("site-15", "https://www.sqlite.org/"),
    ("site-16", "https://www.mozilla.org/"),
    ("site-17", "https://github.com/"),
    ("site-18", "https://openai.com/"),
    ("site-19", "https://www.cloudflare.com/"),
    ("site-20", "https://www.wikipedia.org/"),
]


class QueueError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run_command(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise QueueError(f"{' '.join(args)} failed: {detail}")
    return result


def require_command(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise QueueError(f"required command not found: {name}")
    return path


def repo_root(cwd: Path) -> Path:
    result = run_command(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(result.stdout.strip()).resolve()


def git_output(root: Path, args: list[str]) -> str:
    return run_command(["git", *args], cwd=root).stdout.strip()


def current_head(root: Path) -> str:
    return git_output(root, ["rev-parse", "HEAD"])


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def slugify(value: str, max_len: int = 48) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "queue")[:max_len]


def shell_double_quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )
    return f'"{escaped}"'


def load_jsonl(path: Path, require_ids: bool) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    seen: set[str] = set()
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise QueueError(f"{path}:{line_no}: each JSONL row must be an object")
        task_id = item.get("id")
        if require_ids and not isinstance(task_id, str):
            raise QueueError(f"{path}:{line_no}: known-size queues require string id")
        if not isinstance(task_id, str):
            task_id = f"row-{line_no}"
            item["id"] = task_id
        if task_id in seen:
            raise QueueError(f"{path}:{line_no}: duplicate id {task_id!r}")
        seen.add(task_id)
        tasks.append(item)
    if not tasks:
        raise QueueError(f"{path}: queue is empty")
    return tasks


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def default_parallel_queues(
    item_count: int,
    override: int | None = None,
    unknown_size: bool = False,
) -> int:
    if override is not None:
        if override < 1:
            raise QueueError("--parallel-queues must be at least 1")
        return override
    if unknown_size:
        return 1
    if item_count > 300:
        return 3
    if item_count > 200:
        return 2
    return 1


def split_items(items: list[dict[str, object]], queue_count: int) -> list[list[dict[str, object]]]:
    if queue_count < 1:
        raise QueueError("queue_count must be at least 1")
    if queue_count > len(items):
        queue_count = len(items)
    base, extra = divmod(len(items), queue_count)
    chunks: list[list[dict[str, object]]] = []
    index = 0
    for queue_index in range(queue_count):
        size = base + (1 if queue_index < extra else 0)
        chunks.append(items[index : index + size])
        index += size
    return chunks


def state_root_path(root: Path, state_root: str) -> Path:
    path = Path(state_root)
    if path.is_absolute():
        return path
    return root / path


def run_dir_path(root: Path, run_name: str, state_root: str) -> Path:
    return state_root_path(root, state_root) / run_name


def read_run(root: Path, run_name: str, state_root: str) -> dict[str, object]:
    run_file = run_dir_path(root, run_name, state_root) / "run.json"
    if not run_file.exists():
        raise QueueError(f"run metadata not found: {run_file}")
    data = json.loads(run_file.read_text())
    if not isinstance(data, dict):
        raise QueueError(f"invalid run metadata: {run_file}")
    return data


def render_prompt(
    template_path: Path,
    run: dict[str, object],
    queue: dict[str, object],
    prompt_addendum: str,
) -> str:
    template = Template(template_path.read_text())
    unknown = "Final completion requires queue_complete. Known task IDs are also checked."
    if run.get("unknown_size"):
        unknown = "This run is marked unknown-size; final completion requires queue_complete."
    values = {
        "RUN_NAME": str(run["run_name"]),
        "QUEUE_ID": str(queue["id"]),
        "QUEUE_PATH": str(queue["queue_path"]),
        "LEDGER_PATH": str(queue["ledger_path"]),
        "OUTPUTS_DIR": str(queue["outputs_dir"]),
        "BATCH_SIZE": str(run["batch_size"]),
        "TASK_COUNT": str(queue["task_count"]),
        "UNKNOWN_SIZE_TEXT": unknown,
        "OBJECTIVE": str(run["objective"]),
        "SUPPORT_TOOLING": str(run["support_tooling"]),
        "PROMPT_ADDENDUM": prompt_addendum,
    }
    return template.safe_substitute(values)


def prompt_addendum_from_args(path: str | None) -> str:
    if not path:
        return ""
    return Path(path).read_text()


def prepare_run(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    queue_input = Path(args.queue)
    if not queue_input.is_absolute():
        queue_input = (Path.cwd() / queue_input).resolve()
    tasks = load_jsonl(queue_input, require_ids=not args.unknown_size)
    queue_count = default_parallel_queues(
        len(tasks),
        override=args.parallel_queues,
        unknown_size=args.unknown_size,
    )
    chunks = split_items(tasks, queue_count)
    run_dir = run_dir_path(root, args.run_name, args.state_root)
    if run_dir.exists():
        raise QueueError(f"run directory already exists: {run_dir}")

    queue_dir = run_dir / "queues"
    ledger_dir = run_dir / "ledgers"
    prompt_dir = run_dir / "prompts"
    output_dir = run_dir / "outputs"
    for path in (queue_dir, ledger_dir, prompt_dir, output_dir):
        path.mkdir(parents=True, exist_ok=True)

    run: dict[str, object] = {
        "schema": 1,
        "run_name": args.run_name,
        "created_at": utc_now(),
        "base_ref": current_head(root),
        "objective": args.objective,
        "support_tooling": args.support_tooling,
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "batch_size": args.batch_size,
        "monitor_interval": args.monitor_interval,
        "parallel_queues": queue_count,
        "unknown_size": args.unknown_size,
        "state_root": relpath(state_root_path(root, args.state_root), root),
        "queues": [],
    }

    prompt_addendum = prompt_addendum_from_args(args.prompt_addendum)
    for index, chunk in enumerate(chunks, start=1):
        queue_id = f"queue-{index:02d}"
        queue_path = queue_dir / f"{queue_id}.jsonl"
        ledger_path = ledger_dir / f"{queue_id}.jsonl"
        prompt_path = prompt_dir / f"{queue_id}.md"
        outputs_path = output_dir / queue_id
        outputs_path.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text("")
        write_jsonl(queue_path, chunk)

        queue = {
            "id": queue_id,
            "index": index,
            "task_count": len(chunk),
            "task_ids": [str(item["id"]) for item in chunk],
            "queue_path": relpath(queue_path, root),
            "ledger_path": relpath(ledger_path, root),
            "prompt_path": relpath(prompt_path, root),
            "outputs_dir": relpath(outputs_path, root),
            "branch": f"codex/{slugify(args.run_name)}-q{index:02d}",
            "tmux_session": f"cq-{slugify(args.run_name, 34)}-q{index:02d}",
        }
        prompt_path.write_text(render_prompt(TEMPLATE_PATH, run, queue, prompt_addendum))
        run["queues"].append(queue)

    (run_dir / "run.json").write_text(json.dumps(run, indent=2, sort_keys=True) + "\n")
    print(f"prepared_run={args.run_name}")
    print(f"run_dir={relpath(run_dir, root)}")
    print(f"queues={queue_count}")
    print("next=review and commit the run state before spawn")


def preflight(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    print(f"repo_root={root}")
    for command in ("git", "tmux", "codex"):
        print(f"{command}={require_command(command)}")
    if args.require_agent_browser:
        print(f"agent-browser={require_command('agent-browser')}")
    print(f"default_model={args.model}")
    print(f"default_reasoning_effort={args.reasoning_effort}")
    if args.queue:
        queue = Path(args.queue)
        if not queue.is_absolute():
            queue = (Path.cwd() / queue).resolve()
        tasks = load_jsonl(queue, require_ids=not args.unknown_size)
        queues = default_parallel_queues(
            len(tasks),
            override=args.parallel_queues,
            unknown_size=args.unknown_size,
        )
        print(f"queue_items={len(tasks)}")
        print(f"planned_queues={queues}")
    print("ok=true")


def git_dirty_for_path(root: Path, path: Path) -> str:
    if not is_relative_to(path, root):
        raise QueueError(f"run state must be inside repo before spawning: {path}")
    relative = relpath(path, root)
    return run_command(
        ["git", "status", "--porcelain", "--untracked-files=normal", "--", relative],
        cwd=root,
    ).stdout.strip()


def ensure_run_state_committed(root: Path, run_name: str, state_root: str) -> None:
    dirty = git_dirty_for_path(root, run_dir_path(root, run_name, state_root))
    if dirty:
        raise QueueError(
            "run state has uncommitted changes; commit codex-queue run state before spawn:\n"
            + dirty
        )


def branch_exists(root: Path, branch: str) -> bool:
    result = run_command(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=root,
        check=False,
        capture=False,
    )
    return result.returncode == 0


def tmux_has_session(session: str) -> bool:
    result = run_command(
        ["tmux", "has-session", "-t", session],
        check=False,
        capture=True,
    )
    return result.returncode == 0


def worktree_for_branch(root: Path, branch: str) -> Path | None:
    target_ref = f"refs/heads/{branch}"
    output = git_output(root, ["worktree", "list", "--porcelain"])
    current_worktree: Path | None = None
    current_branch = ""
    for raw in output.splitlines() + [""]:
        if raw.startswith("worktree "):
            current_worktree = Path(raw.removeprefix("worktree ")).resolve()
            current_branch = ""
        elif raw.startswith("branch "):
            current_branch = raw.removeprefix("branch ")
        elif raw == "":
            if current_worktree is not None and current_branch == target_ref:
                return current_worktree
            current_worktree = None
            current_branch = ""
    return None


def build_codex_command(
    source_root: Path,
    worktree: Path,
    queue: dict[str, object],
    model: str,
    reasoning_effort: str,
) -> str:
    prompt_path = shlex.quote(str(worktree / str(queue["prompt_path"])))
    cd = shlex.quote(str(worktree))
    model_arg = shlex.quote(model)
    reasoning_arg = shell_double_quote(f'model_reasoning_effort="{reasoning_effort}"')
    source_trust_arg = shell_double_quote(
        f'projects.{json.dumps(str(source_root))}.trust_level="trusted"'
    )
    worktree_trust_arg = shell_double_quote(
        f'projects.{json.dumps(str(worktree))}.trust_level="trusted"'
    )
    codex_command = (
        f"codex --no-alt-screen -a never -s danger-full-access "
        f"-m {model_arg} -c {reasoning_arg} "
        f"-c {source_trust_arg} -c {worktree_trust_arg} "
        f"-C {cd} \"$(cat {prompt_path})\""
    )
    return (
        f"cd {cd} && {codex_command}; "
        "rc=$?; "
        "printf '\\n[codex-queue] codex exited with status %s\\n' \"$rc\"; "
        "sleep 600; "
        "exit \"$rc\""
    )


def spawn_workers(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    run = read_run(root, args.run_name, args.state_root)
    ensure_run_state_committed(root, args.run_name, args.state_root)
    model = args.model or str(run["model"])
    reasoning_effort = args.reasoning_effort or str(run["reasoning_effort"])
    worktree_parent = Path(args.worktree_parent).resolve() if args.worktree_parent else root.parent
    worktree_parent.mkdir(parents=True, exist_ok=True)
    base = current_head(root)

    for queue in run["queues"]:
        assert isinstance(queue, dict)
        branch = str(queue["branch"])
        session = str(queue["tmux_session"])
        if branch_exists(root, branch):
            raise QueueError(f"branch already exists: {branch}")
        if tmux_has_session(session):
            raise QueueError(f"tmux session already exists: {session}")
        worktree = worktree_parent / f"{root.name}-{slugify(args.run_name)}-{queue['id']}"
        if worktree.exists():
            raise QueueError(f"worktree path already exists: {worktree}")
        run_command(["git", "branch", branch, base], cwd=root)
        run_command(["git", "worktree", "add", str(worktree), branch], cwd=root)
        command = build_codex_command(root, worktree, queue, model, reasoning_effort)
        run_command(["tmux", "new-session", "-d", "-s", session, "bash", "-lc", command])
        print(f"spawned_queue={queue['id']} branch={branch} worktree={worktree} tmux={session}")


def read_ledger(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    entries: list[dict[str, object]] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise QueueError(f"{path}:{line_no}: invalid ledger JSON: {exc}") from exc
        if not isinstance(item, dict):
            raise QueueError(f"{path}:{line_no}: ledger entry must be an object")
        entries.append(item)
    return entries


def ledger_state(queue: dict[str, object], ledger_path: Path, unknown_size: bool) -> dict[str, object]:
    entries = read_ledger(ledger_path)
    task_ids = [str(task_id) for task_id in queue.get("task_ids", [])]
    reviewed = {
        str(entry.get("task_id"))
        for entry in entries
        if entry.get("task_id") is not None and entry.get("manual_review") is True
    }
    queue_complete = any(
        entry.get("event") == "queue_complete" or entry.get("status") == "queue_complete"
        for entry in entries
    )
    if unknown_size:
        complete = queue_complete
    else:
        complete = all(task_id in reviewed for task_id in task_ids) and queue_complete
    return {
        "entries": len(entries),
        "reviewed": len(reviewed),
        "expected": len(task_ids),
        "queue_complete": queue_complete,
        "complete": complete,
    }


def pane_is_working(text: str, bottom_lines: int = 20) -> bool:
    lines = text.splitlines()
    tail = lines[-bottom_lines:] if len(lines) > bottom_lines else lines
    active_markers = ("Working (", "Waiting for background terminal", "esc to interrupt")
    return any(any(marker in line for marker in active_markers) for line in tail)


class TmuxClient:
    def capture(self, session: str) -> str:
        result = run_command(
            ["tmux", "capture-pane", "-pt", session, "-S", "-60"],
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout

    def send_continue(self, session: str, sleep_seconds: float = 2.0) -> None:
        run_command(["tmux", "send-keys", "-t", session, "continue"], check=True)
        time.sleep(sleep_seconds)
        run_command(["tmux", "send-keys", "-t", session, "Enter"], check=True)

    def send_escape(self, session: str) -> None:
        run_command(["tmux", "send-keys", "-t", session, "Escape"], check=True)

    def send_enter(self, session: str) -> None:
        run_command(["tmux", "send-keys", "-t", session, "Enter"], check=True)


def queue_worktree_or_root(root: Path, queue: dict[str, object]) -> Path:
    try:
        return worktree_for_branch(root, str(queue["branch"])) or root
    except QueueError:
        return root


def queue_statuses(root: Path, run: dict[str, object], tmux: TmuxClient) -> list[dict[str, object]]:
    statuses: list[dict[str, object]] = []
    for queue in run["queues"]:
        assert isinstance(queue, dict)
        worktree = queue_worktree_or_root(root, queue)
        ledger_path = worktree / str(queue["ledger_path"])
        state = ledger_state(queue, ledger_path, bool(run.get("unknown_size")))
        pane = tmux.capture(str(queue["tmux_session"]))
        working = pane_is_working(pane)
        statuses.append(
            {
                "queue": queue,
                "worktree": worktree,
                "ledger_path": ledger_path,
                "state": state,
                "working": working,
            }
        )
    return statuses


def print_status(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    run = read_run(root, args.run_name, args.state_root)
    statuses = queue_statuses(root, run, TmuxClient())
    for status in statuses:
        queue = status["queue"]
        state = status["state"]
        print(
            f"{queue['id']} reviewed={state['reviewed']}/{state['expected']} "
            f"queue_complete={state['queue_complete']} complete={state['complete']} "
            f"working={status['working']} ledger={status['ledger_path']}"
        )
    print(f"all_complete={all(status['state']['complete'] for status in statuses)}")


def monitor_once(
    root: Path,
    run: dict[str, object],
    tmux: TmuxClient,
    sleep_seconds: float = 2.0,
) -> list[str]:
    actions: list[str] = []
    for status in queue_statuses(root, run, tmux):
        queue = status["queue"]
        state = status["state"]
        if state["complete"]:
            actions.append(f"{queue['id']}:complete")
            continue
        if status["working"]:
            actions.append(f"{queue['id']}:working")
            continue
        tmux.send_continue(str(queue["tmux_session"]), sleep_seconds=sleep_seconds)
        actions.append(f"{queue['id']}:continue_sent")
    return actions


def monitor(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    run = read_run(root, args.run_name, args.state_root)
    interval = args.monitor_interval or int(run["monitor_interval"])
    tmux = TmuxClient()
    while True:
        actions = monitor_once(root, run, tmux)
        print(f"{utc_now()} {' '.join(actions)}", flush=True)
        if actions and all(action.endswith(":complete") for action in actions):
            return
        time.sleep(interval)


def spawn_monitor(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    run = read_run(root, args.run_name, args.state_root)
    interval = args.monitor_interval or int(run["monitor_interval"])
    session = f"cq-{slugify(args.run_name, 34)}-monitor"
    if tmux_has_session(session):
        raise QueueError(f"tmux monitor session already exists: {session}")
    command = (
        f"cd {shlex.quote(str(root))} && "
        f"{shlex.quote(str(SCRIPT_PATH))} --repo {shlex.quote(str(root))} "
        f"monitor --run-name {shlex.quote(args.run_name)} "
        f"--state-root {shlex.quote(args.state_root)} "
        f"--monitor-interval {interval}"
    )
    run_command(["tmux", "new-session", "-d", "-s", session, "bash", "-lc", command])
    print(f"spawned_monitor={session}")


def changed_paths_for_branch(root: Path, branch: str, target_ref: str) -> list[str]:
    result = run_command(
        ["git", "diff", "--name-only", f"{target_ref}...{branch}"],
        cwd=root,
        check=False,
    )
    if result.returncode != 0:
        result = run_command(["git", "diff", "--name-only", f"{target_ref}..{branch}"], cwd=root)
    return [line for line in result.stdout.splitlines() if line.strip()]


def find_overlaps(branch_paths: dict[str, list[str]]) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for branch, paths in branch_paths.items():
        for path in paths:
            owners.setdefault(path, []).append(branch)
    return {path: branches for path, branches in owners.items() if len(branches) > 1}


def merge_preflight(args: argparse.Namespace) -> None:
    root = repo_root(Path(args.repo))
    run = read_run(root, args.run_name, args.state_root)
    target_ref = args.target_ref
    statuses = queue_statuses(root, run, TmuxClient())
    all_complete = all(status["state"]["complete"] for status in statuses)
    print(f"all_complete={str(all_complete).lower()}")
    branch_paths: dict[str, list[str]] = {}
    for status in statuses:
        queue = status["queue"]
        branch = str(queue["branch"])
        paths = changed_paths_for_branch(root, branch, target_ref)
        branch_paths[branch] = paths
        print(f"queue={queue['id']} branch={branch} worktree={status['worktree']}")
        for path in paths:
            print(f"changed_path[{branch}]={path}")
    overlaps = find_overlaps(branch_paths)
    for path, branches in overlaps.items():
        print(f"overlap_path={path} branches={','.join(branches)}")
    print("merge_order=" + ",".join(str(queue["branch"]) for queue in run["queues"]))
    print("manual_reconciliation_required=true")


def smoke_queue_path(root: Path) -> Path:
    rows = [
        {
            "id": site_id,
            "url": url,
            "review_task": "Visit the live page with agent-browser and write a short manual summary.",
        }
        for site_id, url in SMOKE_SITES
    ]
    queue_path = root / "smoke-sites.jsonl"
    write_jsonl(queue_path, rows)
    return queue_path


def smoke_objective() -> str:
    return textwrap.dedent(
        """
        Manually review each queued URL. Before browser commands, run
        `agent-browser skills get core`. For each item, use agent-browser to
        open the URL, inspect live page content with snapshot and title/url/text
        commands as needed, then write one short summary of that specific page.
        Do not summarize from memory. Do not summarize multiple sites at once.
        Each ledger evidence list must mention the agent-browser commands or
        live page facts inspected for that item.
        """
    ).strip()


def wait_for_worker_start(
    run: dict[str, object],
    tmux: TmuxClient,
    timeout: int = 180,
) -> None:
    queue = run["queues"][0]
    assert isinstance(queue, dict)
    session = str(queue["tmux_session"])
    deadline = time.time() + timeout
    while time.time() < deadline:
        pane = tmux.capture(session)
        if "Do you trust the contents of this directory?" in pane:
            tmux.send_enter(session)
            time.sleep(5)
            continue
        if pane_is_working(pane):
            print("smoke_worker_started=true", flush=True)
            return
        time.sleep(5)
    raise QueueError("worker did not enter an active Codex turn before monitor start")


def wait_for_git_clean(worktree: Path, timeout: int = 300) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = run_command(["git", "status", "--short"], cwd=worktree).stdout.strip()
        if not status:
            return
        time.sleep(5)
    status = run_command(["git", "status", "--short"], cwd=worktree).stdout.strip()
    raise QueueError(f"smoke worktree did not become clean after completion:\n{status}")


def cleanup_smoke_sessions(run: dict[str, object]) -> None:
    for queue in run["queues"]:
        assert isinstance(queue, dict)
        run_command(
            ["tmux", "kill-session", "-t", str(queue["tmux_session"])],
            check=False,
        )
    run_command(
        ["tmux", "kill-session", "-t", f"cq-{slugify(str(run['run_name']), 34)}-monitor"],
        check=False,
    )


def initialize_smoke_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    run_command(["git", "init", "-b", "main"], cwd=root)
    run_command(["git", "config", "user.email", "codex-queue-smoke@example.invalid"], cwd=root)
    run_command(["git", "config", "user.name", "codex Queue Smoke"], cwd=root)
    (root / "AGENTS.md").write_text(
        "Use non-interactive commands. This temporary repo is for codex-queue smoke testing.\n"
    )
    run_command(["git", "add", "AGENTS.md"], cwd=root)
    run_command(["git", "commit", "-m", "initial smoke repo"], cwd=root)


def smoke(args: argparse.Namespace) -> None:
    require_command("agent-browser")
    run_command(["agent-browser", "skills", "get", "core"], check=True)
    if args.smoke_dir:
        smoke_root = Path(args.smoke_dir).resolve()
    else:
        smoke_parent = Path.home() / ".cache" / "codex-queue-smoke"
        smoke_parent.mkdir(parents=True, exist_ok=True)
        smoke_root = Path(tempfile.mkdtemp(prefix="run-", dir=smoke_parent))
    if smoke_root.exists() and any(smoke_root.iterdir()):
        raise QueueError(f"smoke directory must be empty: {smoke_root}")
    if not smoke_root.exists():
        smoke_root.mkdir(parents=True)
        smoke_root.rmdir()
    initialize_smoke_repo(smoke_root)
    queue_path = smoke_queue_path(smoke_root)
    run_command(["git", "add", "smoke-sites.jsonl"], cwd=smoke_root)
    run_command(["git", "commit", "-m", "add smoke queue"], cwd=smoke_root)

    prepare_args = argparse.Namespace(
        repo=str(smoke_root),
        queue=str(queue_path),
        run_name=args.run_name,
        state_root=DEFAULT_STATE_ROOT,
        objective=smoke_objective(),
        support_tooling="Use agent-browser only as an inspection tool for one queued URL at a time.",
        model=args.model,
        reasoning_effort=args.reasoning_effort,
        batch_size=args.batch_size,
        monitor_interval=args.monitor_interval,
        parallel_queues=args.parallel_queues,
        unknown_size=False,
        prompt_addendum=None,
    )
    prepare_run(prepare_args)
    run_command(["git", "add", DEFAULT_STATE_ROOT], cwd=smoke_root)
    run_command(["git", "commit", "-m", "prepare codex queue smoke run"], cwd=smoke_root)

    spawn_workers(
        argparse.Namespace(
            repo=str(smoke_root),
            run_name=args.run_name,
            state_root=DEFAULT_STATE_ROOT,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            worktree_parent=str(smoke_root.parent),
        )
    )
    root = repo_root(smoke_root)
    run = read_run(root, args.run_name, DEFAULT_STATE_ROOT)
    tmux = TmuxClient()
    wait_for_worker_start(run, tmux)
    spawn_monitor(
        argparse.Namespace(
            repo=str(smoke_root),
            run_name=args.run_name,
            state_root=DEFAULT_STATE_ROOT,
            monitor_interval=args.monitor_interval,
        )
    )

    interrupted = False
    resumed = False
    deadline = time.time() + args.timeout
    print(f"smoke_root={smoke_root}")
    while time.time() < deadline:
        statuses = queue_statuses(root, run, tmux)
        status = statuses[0]
        state = status["state"]
        print(
            f"{utc_now()} smoke reviewed={state['reviewed']}/{state['expected']} "
            f"complete={state['complete']} working={status['working']}",
            flush=True,
        )
        if not interrupted and int(state["reviewed"]) >= 10:
            tmux.send_escape(str(status["queue"]["tmux_session"]))
            interrupted = True
            print("smoke_interruption=escape_sent", flush=True)
        if interrupted and not resumed and int(state["reviewed"]) > 10:
            resumed = True
            print("smoke_resume=ledger_advanced_after_escape", flush=True)
        if state["complete"]:
            entries = read_ledger(Path(status["ledger_path"]))
            validate_smoke_ledger(entries)
            wait_for_git_clean(Path(status["worktree"]))
            cleanup_smoke_sessions(run)
            if not interrupted or not resumed:
                raise QueueError("smoke completed but interruption/resume was not validated")
            print("smoke_complete=true")
            return
        time.sleep(10)
    raise QueueError(f"smoke timed out after {args.timeout} seconds")


def validate_smoke_ledger(entries: list[dict[str, object]]) -> None:
    reviewed = [entry for entry in entries if entry.get("task_id")]
    if len(reviewed) != len(SMOKE_SITES):
        raise QueueError(f"expected {len(SMOKE_SITES)} reviewed entries, got {len(reviewed)}")
    for entry in reviewed:
        if entry.get("manual_review") is not True:
            raise QueueError(f"ledger entry lacks manual_review=true: {entry}")
        summary = str(entry.get("summary", "")).strip()
        evidence = entry.get("evidence")
        if not summary:
            raise QueueError(f"ledger entry lacks summary: {entry}")
        if not isinstance(evidence, list) or not evidence:
            raise QueueError(f"ledger entry lacks evidence list: {entry}")
        joined = " ".join(str(item).lower() for item in evidence)
        if "agent-browser" not in joined and "live" not in joined and "snapshot" not in joined:
            raise QueueError(f"ledger evidence does not show browser inspection: {entry}")
    if not any(entry.get("event") == "queue_complete" for entry in entries):
        raise QueueError("ledger lacks queue_complete entry")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex manual queue orchestration")
    parser.add_argument("--repo", default=os.getcwd(), help="Git repo root or path inside it")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--queue")
    preflight_parser.add_argument("--require-agent-browser", action="store_true")
    preflight_parser.add_argument("--model", default=DEFAULT_MODEL)
    preflight_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    preflight_parser.add_argument("--parallel-queues", type=int)
    preflight_parser.add_argument("--unknown-size", action="store_true")
    preflight_parser.set_defaults(func=preflight)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--run-name", required=True)
    prepare_parser.add_argument("--queue", required=True)
    prepare_parser.add_argument("--objective", required=True)
    prepare_parser.add_argument("--support-tooling", default="Use existing repo tools only to surface evidence for one item at a time.")
    prepare_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    prepare_parser.add_argument("--model", default=DEFAULT_MODEL)
    prepare_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    prepare_parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    prepare_parser.add_argument("--monitor-interval", type=int, default=DEFAULT_MONITOR_INTERVAL)
    prepare_parser.add_argument("--parallel-queues", type=int)
    prepare_parser.add_argument("--unknown-size", action="store_true")
    prepare_parser.add_argument("--prompt-addendum")
    prepare_parser.set_defaults(func=prepare_run)

    spawn_parser = subparsers.add_parser("spawn")
    spawn_parser.add_argument("--run-name", required=True)
    spawn_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    spawn_parser.add_argument("--model")
    spawn_parser.add_argument("--reasoning-effort")
    spawn_parser.add_argument("--worktree-parent")
    spawn_parser.set_defaults(func=spawn_workers)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-name", required=True)
    status_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    status_parser.set_defaults(func=print_status)

    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--run-name", required=True)
    monitor_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    monitor_parser.add_argument("--monitor-interval", type=int)
    monitor_parser.set_defaults(func=monitor)

    spawn_monitor_parser = subparsers.add_parser("spawn-monitor")
    spawn_monitor_parser.add_argument("--run-name", required=True)
    spawn_monitor_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    spawn_monitor_parser.add_argument("--monitor-interval", type=int)
    spawn_monitor_parser.set_defaults(func=spawn_monitor)

    merge_parser = subparsers.add_parser("merge-preflight")
    merge_parser.add_argument("--run-name", required=True)
    merge_parser.add_argument("--state-root", default=DEFAULT_STATE_ROOT)
    merge_parser.add_argument("--target-ref", default="HEAD")
    merge_parser.set_defaults(func=merge_preflight)

    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.add_argument("--run-name", default="smoke")
    smoke_parser.add_argument("--smoke-dir")
    smoke_parser.add_argument("--model", default=DEFAULT_MODEL)
    smoke_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    smoke_parser.add_argument("--batch-size", type=int, default=5)
    smoke_parser.add_argument("--parallel-queues", type=int, default=1)
    smoke_parser.add_argument("--monitor-interval", type=int, default=15)
    smoke_parser.add_argument("--timeout", type=int, default=7200)
    smoke_parser.set_defaults(func=smoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except QueueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
