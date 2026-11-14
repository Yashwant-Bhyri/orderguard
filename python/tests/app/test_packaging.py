"""Packaging lint that needs no Docker daemon: Dockerfile, compose, ignore rules, env template, CI wiring, quickstart script."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _read(name):
    return (ROOT / name).read_text()


def test_dockerfile_runs_as_a_non_root_user_with_a_healthcheck():
    d = _read("Dockerfile")
    lines = [ln.strip() for ln in d.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    users = [ln.split()[1] for ln in lines if ln.startswith("USER ")]
    assert users and users[-1] not in ("root", "0"), "the final USER must be unprivileged"
    assert any(ln.startswith("HEALTHCHECK") for ln in lines) and "/api/health" in d
    assert "ORDERGUARD_APP_TOKEN" in d.split("HEALTHCHECK", 1)[1], "the healthcheck must send the token when one is set, or it fails under auth"
    assert re.search(r"useradd .*--uid 1\d{4}", d) and "chown" in d
    assert "OG_LLM=replay" in d, "the image must default to no model calls"
    assert "PYTHONDONTWRITEBYTECODE=1" in d, "read-only root filesystem: no bytecode writes"
    assert "pip install -e" in d and "editable" in d.lower(), "the editable install needs its rationale next to it"
    assert not re.search(r"(?i)(api_key|token|secret)\s*=\s*\S+", "\n".join(ln for ln in lines if ln.startswith(("ENV", "ARG", "RUN")))), "no secret baked into the image"
    assert lines[0].startswith("FROM ") and all(":" in ln.split()[1] for ln in lines if ln.startswith("FROM ") and "AS" in ln or ln.startswith("FROM ")), "pin base image tags"
    assert "latest" not in d


def test_compose_is_read_only_least_privilege_and_loopback_only():
    c = _read("docker-compose.yml")
    assert c.count("read_only: true") >= 3 and c.count("cap_drop: [ALL]") == 2 and c.count("no-new-privileges:true") == 2
    ports = re.findall(r'-\s*"([^"]*:\d+:\d+)"', c)
    assert ports and all(p.startswith("127.0.0.1:") for p in ports), "published ports must bind loopback"
    assert "privileged" not in c and "/var/run/docker.sock" not in c
    assert "required: false" in c, "the app must start without a .env file"


def test_dockerignore_keeps_secrets_and_state_out_of_the_image():
    ig = _read(".dockerignore").splitlines()
    for must in (".git", ".venv", "node_modules", ".env", ".env.*", "!.env.example", "var"):
        assert must in ig, must


def test_env_example_has_names_only():
    for ln in _read(".env.example").splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        name, _, value = ln.partition("=")
        if name.endswith(("_KEY", "_TOKEN")):
            assert value.strip() == "", f"{name} must be empty in the template"
    assert "OG_LLM=live" in _read(".env.example")


def test_ci_builds_the_image_runs_tests_and_scans_secrets():
    ci = _read(".github/workflows/ci.yml")
    assert "docker/build-push-action" in ci and "push: false" in ci, "CI must build the image (without pushing)"
    assert "scan_committable.sh" in ci and "pytest" in ci and "gen_api_docs.py --check" in ci
    assert re.search(r"needs:\s*\[[^\]]*python", ci)


def test_quickstart_is_valid_posix_sh_and_documents_its_flags():
    q = ROOT / "scripts" / "quickstart.sh"
    r = subprocess.run(["sh", "-n", str(q)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    h = subprocess.run(["sh", str(q), "--help"], capture_output=True, text=True)
    assert h.returncode == 0 and "--no-serve" in h.stdout and "--skip-tests" in h.stdout
    bad = subprocess.run(["sh", str(q), "--bogus"], capture_output=True, text=True)
    assert bad.returncode == 2 and "unknown option" in bad.stderr and "--help" in bad.stderr
    text = q.read_text()
    assert "set -eu" in text and "127.0.0.1" in text and "exec .venv/bin/orderguard serve" in text
