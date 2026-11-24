#!/usr/bin/env python3
"""Pull-based deploy and health watch for the NUC. Standard library only.

    deployer.py deploy [--dry-run]   deploy the latest verified, CI-green commit on main
    deployer.py health               alert (Telegram) when the app is down, and when it recovers
    deployer.py adopt                record the checked-out commit as already deployed (setup)
    deployer.py test-notify          send a test Telegram message

Nothing listens and nothing is pushed to the host: a systemd timer runs this, and it only makes
outbound requests to GitHub and Telegram. A commit is deployed only if it is the tip of the
configured branch, GitHub has verified its signature and every required check passed on it.
Configuration comes from environment variables (see `Config.from_env` and ops/deploy/README.md).
The Telegram token is never printed or logged.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info < (3, 10):  # noqa: UP036 - the NUC's Python may be older than the repo's
    sys.exit("deployer.py needs Python 3.10 or newer")

API = "https://api.github.com"
DEFAULT_CHECKS = ("backend", "frontend", "image", "skills")

Http = Callable[[str, bytes | None], tuple[int, Any]]
Run = Callable[[list[str], dict[str, str]], tuple[int, str]]


@dataclass
class Config:
    repo: str = "jsmithedin/darkroom"
    branch: str = "main"
    checkout: Path = Path("/opt/darkroom/repo")
    env_file: Path = Path("/opt/darkroom/.env")
    state_dir: Path = Path("/var/lib/darkroom-deploy")
    project: str = "darkroom"
    required_checks: tuple[str, ...] = DEFAULT_CHECKS
    require_verified: bool = True
    health_url: str = ""  # public URL, optional; checked from the NUC through Cloudflare
    health_wait_seconds: int = 90
    failures_before_alert: int = 2
    repeat_alert_seconds: int = 6 * 3600
    telegram_token: str = field(default="", repr=False)
    telegram_chat: str = ""

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        e = env if env is not None else dict(os.environ)
        checks = tuple(c for c in e.get("REQUIRED_CHECKS", "").split(",") if c) or DEFAULT_CHECKS
        return cls(
            repo=e.get("DEPLOY_REPO", cls.repo),
            branch=e.get("DEPLOY_BRANCH", cls.branch),
            checkout=Path(e.get("DEPLOY_CHECKOUT", str(cls.checkout))),
            env_file=Path(e.get("DEPLOY_ENV_FILE", str(cls.env_file))),
            state_dir=Path(e.get("DEPLOY_STATE_DIR", str(cls.state_dir))),
            project=e.get("COMPOSE_PROJECT_NAME", cls.project),
            required_checks=checks,
            require_verified=e.get("REQUIRE_VERIFIED", "1") != "0",
            health_url=e.get("DEPLOY_HEALTH_URL", ""),
            health_wait_seconds=int(e.get("HEALTH_WAIT_SECONDS", "90")),
            failures_before_alert=int(e.get("FAILURES_BEFORE_ALERT", "2")),
            repeat_alert_seconds=int(e.get("REPEAT_ALERT_SECONDS", str(6 * 3600))),
            telegram_token=e.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat=e.get("TELEGRAM_CHAT_ID", ""),
        )


# ---------------------------------------------------------------- decisions (pure)


@dataclass(frozen=True)
class Latest:
    sha: str
    verified: bool
    subject: str = ""


@dataclass(frozen=True)
class Decision:
    action: str  # deploy, current, failed-before, wait, checks-failed, unverified
    reason: str = ""


def check_state(runs: list[dict[str, Any]], required: tuple[str, ...]) -> tuple[str, str]:
    """('passed'|'pending'|'failed', detail) for the newest run of each required check."""
    newest: dict[str, dict[str, Any]] = {}
    for run in runs:
        name = run.get("name", "")
        if name in required and run.get("id", 0) >= newest.get(name, {}).get("id", -1):
            newest[name] = run
    missing = [name for name in required if name not in newest]
    if missing:
        return "pending", "not started: " + ", ".join(missing)
    failed = [
        n
        for n, r in newest.items()
        if r.get("status") == "completed" and r.get("conclusion") != "success"
    ]
    if failed:
        return "failed", "not successful: " + ", ".join(sorted(failed))
    waiting = [n for n, r in newest.items() if r.get("status") != "completed"]
    if waiting:
        return "pending", "still running: " + ", ".join(sorted(waiting))
    return "passed", ""


def decide(
    latest: Latest,
    state: dict[str, Any],
    checks: tuple[str, str],
    require_verified: bool,
) -> Decision:
    if latest.sha == state.get("deployed_sha"):
        return Decision("current")
    if latest.sha == state.get("failed_sha"):
        return Decision("failed-before", "this commit already failed to deploy")
    if require_verified and not latest.verified:
        return Decision("unverified", "GitHub does not show this commit as verified")
    kind, detail = checks
    if kind == "failed":
        return Decision("checks-failed", detail)
    if kind == "pending":
        return Decision("wait", detail)
    return Decision("deploy")


def health_step(
    state: dict[str, Any], ok: bool, detail: str, now: float, threshold: int, repeat: int
) -> tuple[dict[str, Any], str | None]:
    """Advance the health state machine. Returns (new state, message to send or None)."""
    h = dict(state.get("health", {}))
    h.setdefault("failures", 0)
    h.setdefault("alerted_at", 0)
    message: str | None = None
    if ok:
        if h["alerted_at"]:
            message = "Darkroom is back up."
        h = {"failures": 0, "alerted_at": 0}
    else:
        h["failures"] += 1
        h["detail"] = detail
        if h["failures"] >= threshold and (not h["alerted_at"] or now - h["alerted_at"] >= repeat):
            first = not h["alerted_at"]
            h["alerted_at"] = now
            message = ("Darkroom is DOWN: " if first else "Darkroom is STILL down: ") + detail
    out = dict(state)
    out["health"] = h
    return out, message


# ---------------------------------------------------------------- effects


def real_http(url: str, data: bytes | None = None) -> tuple[int, Any]:
    headers = {"User-Agent": "darkroom-deployer", "Accept": "application/vnd.github+json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return 0, None  # deliberately no message: the URL may contain a secret


def real_run(cmd: list[str], env: dict[str, str]) -> tuple[int, str]:
    try:
        done = subprocess.run(
            cmd, env={**os.environ, **env}, capture_output=True, text=True, timeout=1800
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, str(exc)
    return done.returncode, (done.stdout + done.stderr)[-4000:]


class Deployer:
    def __init__(
        self,
        config: Config,
        http: Http = real_http,
        run: Run = real_run,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda m: print(m, flush=True),
    ) -> None:
        self.c = config
        self.http = http
        self.run = run
        self.clock = clock
        self.sleep = sleep
        self.log = log

    # state ---------------------------------------------------------------
    @property
    def state_file(self) -> Path:
        return self.c.state_dir / "state.json"

    def load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text())  # type: ignore[no-any-return]
        except (OSError, ValueError):
            return {}

    def save_state(self, state: dict[str, Any]) -> None:
        self.c.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(self.state_file)

    # telegram ------------------------------------------------------------
    def notify(self, text: str) -> bool:
        self.log("notify: " + text.splitlines()[0][:200])
        if not (self.c.telegram_token and self.c.telegram_chat):
            self.log("notify: Telegram is not configured, message not sent")
            return False
        body = json.dumps({"chat_id": self.c.telegram_chat, "text": text[:3900]}).encode()
        status, _ = self.http(
            "https://api.telegram.org/bot" + self.c.telegram_token + "/sendMessage", body
        )
        if status != 200:
            self.log(f"notify: Telegram returned status {status}")
        return status == 200

    def notify_once(self, state: dict[str, Any], key: str, text: str) -> None:
        """Send `text` unless the same `key` was already reported (no spam every 5 minutes)."""
        if state.get("last_notified") != key:
            self.notify(text)
            state["last_notified"] = key

    # github --------------------------------------------------------------
    def latest(self) -> Latest | None:
        status, data = self.http(f"{API}/repos/{self.c.repo}/commits/{self.c.branch}", None)
        if status != 200 or not data:
            self.log(f"github: could not read the latest commit (status {status})")
            return None
        return Latest(
            sha=data["sha"],
            verified=bool(data.get("commit", {}).get("verification", {}).get("verified")),
            subject=(data.get("commit", {}).get("message", "") or "").splitlines()[0][:100],
        )

    def checks(self, sha: str) -> tuple[str, str] | None:
        url = f"{API}/repos/{self.c.repo}/commits/{sha}/check-runs?per_page=100"
        status, data = self.http(url, None)
        if status != 200 or data is None:
            self.log(f"github: could not read check runs (status {status})")
            return None
        return check_state(data.get("check_runs", []), self.c.required_checks)

    # docker / git --------------------------------------------------------
    def compose(self, *args: str) -> tuple[int, str]:
        """Run docker compose from the checkout, with the pinned project name and env file."""
        cmd = [
            "docker",
            "compose",
            "--project-directory",
            str(self.c.checkout),
            "--env-file",
            str(self.c.env_file),
            *args,
        ]
        return self.run(cmd, {"COMPOSE_PROJECT_NAME": self.c.project})

    def git(self, *args: str) -> tuple[int, str]:
        return self.run(["git", "-C", str(self.c.checkout), *args], {})

    def checkout_sha(self, sha: str) -> tuple[bool, str]:
        code, out = self.git("fetch", "--quiet", "origin", self.c.branch)
        if code:
            return False, "git fetch failed: " + out[-300:]
        code, out = self.git("merge-base", "--is-ancestor", sha, "origin/" + self.c.branch)
        if code:
            return False, f"commit is not on origin/{self.c.branch}"
        code, out = self.git(
            "-c", "advice.detachedHead=false", "checkout", "--force", "--detach", sha
        )
        if code:
            return False, "git checkout failed: " + out[-300:]
        return True, ""

    def app_healthy(self) -> tuple[bool, str]:
        probe = (
            "import json,urllib.request as u;"
            "d=json.load(u.urlopen('http://localhost:8000/api/health'));"
            "raise SystemExit(0 if d.get('db') is True else 1)"
        )
        code, out = self.compose("exec", "-T", "app", "python", "-c", probe)
        if code:
            return False, "app container health check failed"
        if self.c.health_url:
            status, data = self.http(self.c.health_url, None)
            if status != 200 or not isinstance(data, dict) or data.get("db") is not True:
                return False, f"public URL check failed (status {status})"
        return True, ""

    def wait_healthy(self) -> tuple[bool, str]:
        deadline = self.clock() + self.c.health_wait_seconds
        detail = ""
        while True:
            ok, detail = self.app_healthy()
            if ok:
                return True, ""
            if self.clock() >= deadline:
                return False, detail
            self.sleep(3)

    # deploy --------------------------------------------------------------
    def build_and_start(self) -> tuple[bool, str]:
        code, out = self.compose("up", "-d", "--build", "--remove-orphans")
        if code:
            return False, "docker compose up failed: " + out[-500:]
        return self.wait_healthy()

    def deploy(self, dry_run: bool = False) -> int:
        state = self.load_state()
        latest = self.latest()
        if latest is None:
            return 0  # GitHub unreachable: try again next time, no alert
        checks = (
            self.checks(latest.sha) if latest.sha != state.get("deployed_sha") else ("passed", "")
        )
        if checks is None:
            return 0
        decision = decide(latest, state, checks, self.c.require_verified)
        short = latest.sha[:7]
        self.log(f"{short} {latest.subject}: {decision.action} {decision.reason}")
        if dry_run:
            return 0
        if decision.action in ("current", "failed-before", "wait"):
            return 0
        if decision.action in ("checks-failed", "unverified"):
            self.notify_once(
                state,
                "refused:" + latest.sha,
                f"Darkroom: NOT deploying {short} ({latest.subject}). {decision.reason}",
            )
            self.save_state(state)
            return 0

        previous = state.get("deployed_sha")
        ok, why = self.checkout_sha(latest.sha)
        if not ok:
            self.notify_once(
                state,
                "fetch:" + latest.sha,
                f"Darkroom: deploy of {short} stopped: {why}",
            )
            self.save_state(state)
            return 1
        code, out = self.compose("run", "--rm", "backup", "once")
        if code:
            self.notify_once(
                state,
                "backup:" + latest.sha,
                f"Darkroom: deploy of {short} stopped because the pre-deploy backup failed. "
                f"Nothing changed.\n{out[-400:]}",
            )
            self.save_state(state)
            return 1

        self.notify(f"Darkroom: deploying {short} ({latest.subject})")
        ok, why = self.build_and_start()
        if ok:
            state.update(deployed_sha=latest.sha, last_notified=None)
            state.pop("failed_sha", None)
            self.save_state(state)
            self.notify(f"Darkroom: deployed {short} and it is healthy.")
            return 0

        state["failed_sha"] = latest.sha
        message = f"Darkroom: deploy of {short} FAILED: {why}."
        if previous:
            ok_prev, _ = self.checkout_sha(previous)
            rolled = ok_prev and self.build_and_start()[0]
            message += (
                f" Rolled back to {previous[:7]} and it is healthy."
                if rolled
                else f" Rolling back to {previous[:7]} ALSO failed: check the NUC now."
            )
            message += " (A migration from the failed version may already have run.)"
        else:
            message += " There is no earlier deploy to roll back to: check the NUC now."
        self.save_state(state)
        self.notify(message)
        return 1

    # health --------------------------------------------------------------
    def containers_ok(self) -> tuple[bool, str]:
        code, out = self.compose("ps", "--format", "json")
        if code:
            return False, "docker compose ps failed"
        rows: list[dict[str, Any]] = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                with contextlib.suppress(ValueError):
                    rows.append(json.loads(line))
            elif line.startswith("["):
                with contextlib.suppress(ValueError):
                    rows.extend(json.loads(line))
        running = {r.get("Service"): r.get("State") for r in rows}
        down = [s for s in ("app", "db") if running.get(s) != "running"]
        if down:
            return False, "container not running: " + ", ".join(
                "{} ({})".format(s, running.get(s, "missing")) for s in down
            )
        return True, ""

    def adopt(self) -> int:
        """Record the checked-out commit as the one that is running (first-time setup)."""
        code, out = self.git("rev-parse", "HEAD")
        if code:
            self.log("adopt: git rev-parse failed")
            return 1
        state = self.load_state()
        state["deployed_sha"] = out.strip()
        state.pop("failed_sha", None)
        self.save_state(state)
        self.log(f"adopt: recorded {out.strip()[:7]} as deployed")
        return 0

    def health(self) -> int:
        state = self.load_state()
        ok, detail = self.containers_ok()
        if ok:
            ok, detail = self.app_healthy()
        new_state, message = health_step(
            state,
            ok,
            detail,
            self.clock(),
            self.c.failures_before_alert,
            self.c.repeat_alert_seconds,
        )
        self.log("health: {} {}".format("ok" if ok else "FAIL", detail))
        self.save_state(new_state)
        if message:
            self.notify(message)
        return 0 if ok else 1


# ---------------------------------------------------------------- entry point


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "deploy"
    config = Config.from_env()
    deployer = Deployer(config)
    if command == "test-notify":
        return 0 if deployer.notify("Darkroom deployer test message: Telegram works.") else 1
    if command not in ("deploy", "health", "adopt"):
        print(__doc__)
        return 2
    config.state_dir.mkdir(parents=True, exist_ok=True)
    # One run at a time. A health check that finds a deploy running skips quietly, so a
    # restart in progress is not reported as an outage.
    lock = open(config.state_dir / "lock", "w")  # noqa: SIM115 - held for the whole run
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("another run is in progress, skipping")
        return 0
    if command == "health":
        return deployer.health()
    if command == "adopt":
        return deployer.adopt()
    return deployer.deploy(dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
