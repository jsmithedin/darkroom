"""Tests for ops/deploy/deployer.py with the network, git, docker and clock all faked."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("deployer", ROOT / "ops" / "deploy" / "deployer.py")
assert spec and spec.loader
deployer = importlib.util.module_from_spec(spec)
sys.modules["deployer"] = deployer  # dataclasses look the module up by name
spec.loader.exec_module(deployer)

REQUIRED = ("backend", "frontend", "image", "skills")
SHA, OLD = "a" * 40, "b" * 40


def runs(**conclusions: Any) -> list[dict[str, Any]]:
    out = []
    for i, name in enumerate(REQUIRED):
        status, conclusion = conclusions.get(name, ("completed", "success"))
        out.append({"id": i, "name": name, "status": status, "conclusion": conclusion})
    return out


# ---------------------------------------------------------------- check_state


def test_all_required_checks_passed() -> None:
    assert deployer.check_state(runs(), REQUIRED) == ("passed", "")


def test_missing_check_is_pending() -> None:
    kind, detail = deployer.check_state(runs()[:3], REQUIRED)
    assert kind == "pending" and "skills" in detail


def test_running_check_is_pending() -> None:
    kind, _ = deployer.check_state(runs(image=("in_progress", None)), REQUIRED)
    assert kind == "pending"


def test_failed_check_is_failed_even_if_others_pending() -> None:
    kind, detail = deployer.check_state(
        runs(backend=("completed", "failure"), image=("in_progress", None)), REQUIRED
    )
    assert kind == "failed" and "backend" in detail


def test_newest_run_of_a_check_wins() -> None:
    older_failed = {"id": 99, "name": "backend", "status": "completed", "conclusion": "failure"}
    rerun = {"id": 100, "name": "backend", "status": "completed", "conclusion": "success"}
    assert deployer.check_state([older_failed, *runs()[1:], rerun], REQUIRED)[0] == "passed"


def test_unrelated_checks_are_ignored() -> None:
    extra = {"id": 50, "name": "codecov", "status": "completed", "conclusion": "failure"}
    assert deployer.check_state([*runs(), extra], REQUIRED)[0] == "passed"


# ---------------------------------------------------------------- decide


def latest(verified: bool = True) -> Any:
    return deployer.Latest(SHA, verified, "feat: thing")


def test_decide_deploys_a_new_verified_green_commit() -> None:
    assert deployer.decide(latest(), {}, ("passed", ""), True).action == "deploy"


def test_decide_skips_what_is_running() -> None:
    assert (
        deployer.decide(latest(), {"deployed_sha": SHA}, ("passed", ""), True).action == "current"
    )


def test_decide_does_not_retry_a_failed_commit() -> None:
    state = {"deployed_sha": OLD, "failed_sha": SHA}
    assert deployer.decide(latest(), state, ("passed", ""), True).action == "failed-before"


def test_decide_refuses_unverified_commits() -> None:
    assert deployer.decide(latest(False), {}, ("passed", ""), True).action == "unverified"
    assert deployer.decide(latest(False), {}, ("passed", ""), False).action == "deploy"


def test_decide_waits_for_pending_and_refuses_failed_checks() -> None:
    assert deployer.decide(latest(), {}, ("pending", "x"), True).action == "wait"
    assert deployer.decide(latest(), {}, ("failed", "x"), True).action == "checks-failed"


# ---------------------------------------------------------------- health_step


def step(state: dict[str, Any], ok: bool, now: float) -> tuple[dict[str, Any], str | None]:
    return deployer.health_step(state, ok, "app down", now, 2, 6 * 3600)


def test_one_failure_is_not_reported_two_are() -> None:
    state, message = step({}, False, 0)
    assert message is None
    state, message = step(state, False, 300)
    assert message == "Darkroom is DOWN: app down"


def test_no_repeat_until_the_interval_then_still_down() -> None:
    state, _ = step({}, False, 0)
    state, _ = step(state, False, 300)
    state, message = step(state, False, 600)
    assert message is None
    state, message = step(state, False, 300 + 6 * 3600)
    assert message == "Darkroom is STILL down: app down"


def test_recovery_is_reported_once_and_a_blip_is_silent() -> None:
    state, _ = step({}, False, 0)
    state, message = step(state, True, 300)
    assert message is None and state["health"]["failures"] == 0
    state, _ = step(state, False, 600)
    state, _ = step(state, False, 900)
    state, message = step(state, True, 1200)
    assert message == "Darkroom is back up."
    state, message = step(state, True, 1500)
    assert message is None


# ---------------------------------------------------------------- Deployer flow


class Fake:
    """Scripted world: GitHub, git, docker and Telegram."""

    def __init__(self, tmp_path: Path) -> None:
        self.sent: list[str] = []
        self.commands: list[list[str]] = []
        self.sha = SHA
        self.verified = True
        self.check_runs = runs()
        self.github_status = 200
        self.fail: set[str] = set()  # command keywords that exit non-zero
        self.healthy = True
        self.bad_shas: set[str] = set()  # commits whose containers never become healthy
        self.current = ""
        self.public_ok = True
        self.ps_rows = [
            {"Service": "app", "State": "running"},
            {"Service": "db", "State": "running"},
        ]
        self.now = 1000.0
        self.config = deployer.Config(
            checkout=tmp_path / "repo",
            env_file=tmp_path / ".env",
            state_dir=tmp_path / "state",
            health_url="https://film.example/api/health",
            health_wait_seconds=10,
            telegram_token="123:SECRET",
            telegram_chat="42",
        )
        self.d = deployer.Deployer(
            self.config, self.http, self.run, self.clock, self.sleep, lambda m: None
        )

    def http(self, url: str, data: bytes | None) -> tuple[int, Any]:
        if url.startswith("https://api.telegram.org/"):
            self.sent.append(json.loads(data or b"{}")["text"])
            return 200, {"ok": True}
        if "check-runs" in url:
            return self.github_status, {"check_runs": self.check_runs}
        if url.startswith("https://api.github.com/"):
            body = {
                "sha": self.sha,
                "commit": {
                    "message": "feat: thing\n\nbody",
                    "verification": {"verified": self.verified},
                },
            }
            return self.github_status, body
        return (200, {"db": True}) if self.public_ok else (502, None)

    def run(self, cmd: list[str], env: dict[str, str]) -> tuple[int, str]:
        self.commands.append(cmd)
        if any(word in cmd for word in self.fail):
            return 1, "boom"
        if "checkout" in cmd:
            self.current = cmd[-1]
        if "exec" in cmd:
            return (0 if self.healthy and self.current not in self.bad_shas else 1), ""
        if "ps" in cmd:
            return 0, "\n".join(json.dumps(r) for r in self.ps_rows)
        if "rev-parse" in cmd:
            return 0, self.sha + "\n"
        return 0, ""

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def steps(self) -> list[str]:
        names = []
        for cmd in self.commands:
            if "checkout" in cmd:
                names.append("checkout " + cmd[-1][:1])
            elif "backup" in cmd:
                names.append("backup")
            elif "up" in cmd:
                names.append("up")
        return names

    def state(self) -> dict[str, Any]:
        return self.d.load_state()


@pytest.fixture
def world(tmp_path: Path) -> Fake:
    return Fake(tmp_path)


def test_successful_deploy_backs_up_first_then_starts_and_records(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    assert world.d.deploy() == 0
    assert world.steps() == ["checkout a", "backup", "up"]
    assert world.state()["deployed_sha"] == SHA
    assert world.sent[0].startswith("Darkroom: deploying aaaaaaa")
    assert world.sent[-1] == "Darkroom: deployed aaaaaaa and it is healthy."


def test_nothing_happens_when_already_deployed(world: Fake) -> None:
    world.d.save_state({"deployed_sha": SHA})
    assert world.d.deploy() == 0
    assert world.commands == [] and world.sent == []


def test_dry_run_changes_nothing(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    assert world.d.deploy(dry_run=True) == 0
    assert world.commands == [] and world.sent == []
    assert world.state()["deployed_sha"] == OLD


def test_pending_checks_wait_silently(world: Fake) -> None:
    world.check_runs = runs(image=("in_progress", None))
    assert world.d.deploy() == 0
    assert world.commands == [] and world.sent == []


def test_failed_checks_are_reported_once_not_every_five_minutes(world: Fake) -> None:
    world.check_runs = runs(backend=("completed", "failure"))
    world.d.deploy()
    world.d.deploy()
    assert world.commands == []
    assert len(world.sent) == 1 and "NOT deploying aaaaaaa" in world.sent[0]


def test_unverified_commit_is_refused(world: Fake) -> None:
    world.verified = False
    world.d.deploy()
    assert world.commands == [] and "verified" in world.sent[0]


def test_failed_start_rolls_back_and_does_not_retry(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    world.bad_shas = {SHA}  # the new version never becomes healthy, the old one is fine
    assert world.d.deploy() == 1
    assert world.steps() == ["checkout a", "backup", "up", "checkout b", "up"]
    state = world.state()
    assert state["failed_sha"] == SHA and state["deployed_sha"] == OLD
    assert (
        "FAILED" in world.sent[-1] and "Rolled back to bbbbbbb and it is healthy" in world.sent[-1]
    )
    world.commands.clear()
    world.d.deploy()  # same commit again: left alone
    assert world.commands == []


def test_rollback_that_also_fails_says_so(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    world.bad_shas = {SHA, OLD}
    world.d.deploy()
    assert "ALSO failed" in world.sent[-1]


def test_failure_with_nothing_to_roll_back_to(world: Fake) -> None:
    world.bad_shas = {SHA}
    world.d.deploy()
    assert "no earlier deploy" in world.sent[-1]


def test_backup_failure_stops_before_touching_anything(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    world.fail = {"backup"}
    assert world.d.deploy() == 1
    assert "up" not in world.steps()
    assert "backup failed" in world.sent[-1] and "Nothing changed" in world.sent[-1]
    assert world.state()["deployed_sha"] == OLD


def test_commit_not_on_branch_is_refused(world: Fake) -> None:
    world.fail = {"merge-base"}
    assert world.d.deploy() == 1
    assert world.steps() == []
    assert "not on origin/main" in world.sent[-1]


def test_github_outage_is_quiet(world: Fake) -> None:
    world.github_status = 503
    assert world.d.deploy() == 0
    assert world.commands == [] and world.sent == []


def test_public_url_failure_counts_as_unhealthy(world: Fake) -> None:
    world.d.save_state({"deployed_sha": OLD})
    world.public_ok = False
    world.d.deploy()
    assert "public URL" in world.sent[-1]


def test_telegram_token_never_reaches_the_log(tmp_path: Path) -> None:
    logged: list[str] = []
    fake = Fake(tmp_path)
    fake.d.log = logged.append
    fake.d.notify("hello")
    fake.d.deploy()
    assert not any("SECRET" in line for line in logged)


def test_missing_telegram_config_does_not_crash(world: Fake) -> None:
    world.config.telegram_token = ""
    assert world.d.notify("x") is False
    assert world.sent == []


# ---------------------------------------------------------------- health command


def test_health_alerts_after_two_failures_then_recovers(world: Fake) -> None:
    world.ps_rows = [{"Service": "app", "State": "exited"}, {"Service": "db", "State": "running"}]
    assert world.d.health() == 1 and world.sent == []
    world.now += 300
    world.d.health()
    assert world.sent == ["Darkroom is DOWN: container not running: app (exited)"]
    world.ps_rows = [{"Service": "app", "State": "running"}, {"Service": "db", "State": "running"}]
    world.now += 300
    assert world.d.health() == 0
    assert world.sent[-1] == "Darkroom is back up."


def test_health_checks_the_app_and_the_public_url(world: Fake) -> None:
    world.healthy = False
    world.d.health()
    world.d.health()
    assert "app container health check failed" in world.sent[0]


def test_adopt_records_the_running_commit(world: Fake) -> None:
    assert world.d.adopt() == 0
    assert world.state()["deployed_sha"] == SHA


def test_health_alert_says_why_compose_ps_failed(world: Fake) -> None:
    world.fail = {"ps"}
    world.d.health()
    world.d.health()
    assert world.sent == ["Darkroom is DOWN: docker compose ps failed: boom"]
