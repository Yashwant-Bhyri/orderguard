"""`orderguard init` and `orderguard doctor`: create and validate a local configuration directory.

    orderguard init [--dir PATH] [--provider deepseek|openrouter] [--force]
    orderguard init --check [--dir PATH]
    orderguard init --resign [--dir PATH]

The directory (default `$ORDERGUARD_HOME`, else `./var/orderguard`) holds:

  signing.key     Ed25519 private key for mandate signing (base64, mode 0600). Never printed, never logged.
  signing.pub     the matching public key (base64).
  mandate.json    an editable mandate template, signed by `signing.key`. Edit the limits, then run `init --resign`:
                  any edit invalidates the signature, and the gate refuses an unsigned or altered mandate.
  .env            variable NAMES with empty values. Put real keys here or in the environment; the file is mode 0600.

`init` is idempotent: it refuses to overwrite anything without `--force`. `doctor` reports problems as plain sentences and
never includes a key value.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import stat
from pathlib import Path

from .gate import (Mandate, MandateInvalid, generate_keypair, private_key_from_b64, private_key_to_b64,
                   public_key_from_b64, public_key_to_b64, sign_mandate)

KEY_FILE, PUB_FILE, MANDATE_FILE, ENV_FILE = "signing.key", "signing.pub", "mandate.json", ".env"
PROVIDERS = {"deepseek": "DEEPSEEK_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
DEFAULT_EXPIRY_DAYS = 30


def default_dir() -> Path:
    return Path(os.getenv("ORDERGUARD_HOME") or "var/orderguard")


def mandate_template(now: dt.datetime | None = None, days: int = DEFAULT_EXPIRY_DAYS) -> dict:
    """Conservative defaults. `referencePrices` are PLACEHOLDERS the receiver values orders at: replace them with real figures."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return {
        "symbols": ["AAPL"],
        "sides": ["buy", "sell"],
        "maxOrderNotionalUsd": 1000.0,
        "maxDailyNotionalUsd": 2500.0,
        "priceBandPct": 2.0,
        "stepUpAboveUsd": 500.0,
        "expiresAt": (now + dt.timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "referencePrices": {"AAPL": 200.0},
    }


def env_template(provider: str) -> str:
    key_name = PROVIDERS[provider]
    other = next(v for k, v in PROVIDERS.items() if k != provider)
    return (
        "# Variable names only. Fill in values here (file is mode 0600) or export them; never commit this file.\n"
        f"OG_PROVIDER={provider}\n"
        f"{key_name}=\n"
        f"{other}=\n"
        "OG_LLM=live            # live | replay (replay never calls a model)\n"
        "OG_BUDGET_USD=0.05     # hard spend ceiling for model calls\n"
        "ORDERGUARD_APP_TOKEN=  # bearer token the web app requires; generate a long random string\n"
        "ORDERGUARD_RECEIVER_URL=  # e.g. http://127.0.0.1:8700 ; empty means no receiver\n"
    )


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
    finally:
        os.chmod(path, 0o600)           # also fixes the mode when the file already existed


def init(directory: Path, provider: str = "deepseek", force: bool = False, now: dt.datetime | None = None) -> list[str]:
    """Create the config directory. Returns the files written. Raises FileExistsError (no changes made) without `force`."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    directory = Path(directory)
    names = (KEY_FILE, PUB_FILE, MANDATE_FILE, ENV_FILE)
    existing = [n for n in names if (directory / n).exists()]
    if existing and not force:
        raise FileExistsError("already exists: " + ", ".join(existing) + " (use --force to overwrite; the old signing key is lost)")
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    priv, pub = generate_keypair()
    _write_private(directory / KEY_FILE, private_key_to_b64(priv) + "\n")
    (directory / PUB_FILE).write_text(public_key_to_b64(pub) + "\n")
    signed = sign_mandate(mandate_template(now), priv)
    (directory / MANDATE_FILE).write_text(json.dumps(signed, indent=2) + "\n")
    _write_private(directory / ENV_FILE, env_template(provider))
    return list(names)


def resign(directory: Path) -> None:
    """Re-sign `mandate.json` with the existing key after the human edited its limits."""
    d = Path(directory)
    priv = private_key_from_b64((d / KEY_FILE).read_text().strip())
    body = json.loads((d / MANDATE_FILE).read_text())
    (d / MANDATE_FILE).write_text(json.dumps(sign_mandate(body, priv), indent=2) + "\n")


def doctor(directory: Path | None = None, *, check_receiver: bool = True, now=None) -> list[str]:
    """Validate the configuration. Returns problems as plain sentences (empty list = healthy). Never includes a secret."""
    d = Path(directory) if directory else default_dir()
    problems: list[str] = []
    if not d.is_dir():
        return [f"config directory {d} does not exist: run `orderguard init`"]
    key, pub = d / KEY_FILE, d / PUB_FILE
    priv_obj = None
    if not key.exists():
        problems.append(f"{KEY_FILE} is missing: run `orderguard init`")
    else:
        if stat.S_IMODE(key.stat().st_mode) & 0o077:
            problems.append(f"{KEY_FILE} is readable by other users: run chmod 600 on it")
        try:
            priv_obj = private_key_from_b64(key.read_text().strip())
        except Exception:
            problems.append(f"{KEY_FILE} is not a valid Ed25519 key")
    pub_obj = None
    if pub.exists():
        try:
            pub_obj = public_key_from_b64(pub.read_text().strip())
        except Exception:
            problems.append(f"{PUB_FILE} is not a valid Ed25519 public key")
    if priv_obj is not None and pub_obj is not None and public_key_to_b64(priv_obj.public_key()) != public_key_to_b64(pub_obj):
        problems.append(f"{PUB_FILE} does not match {KEY_FILE}")
    verifier = pub_obj or (priv_obj.public_key() if priv_obj else None)

    mp = d / MANDATE_FILE
    if not mp.exists():
        problems.append(f"{MANDATE_FILE} is missing: run `orderguard init`")
    else:
        try:
            m = Mandate.load(mp)
            if verifier is None:
                problems.append("cannot verify the mandate without a signing key")
            else:
                m.verify(verifier, now=now)
        except MandateInvalid as e:
            problems.append(f"mandate: {e}")
        except Exception:
            problems.append(f"{MANDATE_FILE} is not a valid mandate file")

    env = _read_env(d / ENV_FILE)
    provider = os.getenv("OG_PROVIDER") or env.get("OG_PROVIDER") or "deepseek"
    key_name = PROVIDERS.get(provider)
    live = (os.getenv("OG_LLM") or env.get("OG_LLM") or "live").split()[0] != "replay"
    if key_name is None:
        problems.append(f"OG_PROVIDER is {provider!r}; expected deepseek or openrouter")
    elif live and not (os.getenv(key_name) or env.get(key_name)):
        problems.append(f"{key_name} is not set (in the environment or {ENV_FILE}); live model calls will fail")
    if not (os.getenv("ORDERGUARD_APP_TOKEN") or env.get("ORDERGUARD_APP_TOKEN")):
        problems.append("ORDERGUARD_APP_TOKEN is not set: the app should not be exposed without one")

    url = os.getenv("ORDERGUARD_RECEIVER_URL") or env.get("ORDERGUARD_RECEIVER_URL")
    if url and check_receiver:
        from .receiver_client import Receiver, ReceiverError
        rc = Receiver(url, timeout=3.0)
        try:
            h = rc.health()
            if h.get("revoked"):
                problems.append("the receiver reports the mandate as revoked")
        except ReceiverError as e:
            problems.append(f"receiver at the configured URL: {e}")
        finally:
            rc.close()
    return problems


def _read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="orderguard init", description="Create or check the OrderGuard configuration directory.")
    ap.add_argument("--dir", default=None, help="config directory (default $ORDERGUARD_HOME or ./var/orderguard)")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="deepseek")
    ap.add_argument("--force", action="store_true", help="overwrite existing files (generates a new signing key)")
    ap.add_argument("--resign", action="store_true", help="re-sign an edited mandate.json with the existing key")
    ap.add_argument("--check", action="store_true", help="validate an existing directory instead of creating one")
    a = ap.parse_args(argv)
    d = Path(a.dir) if a.dir else default_dir()
    if a.resign:
        try:
            resign(d)
        except (OSError, ValueError) as e:
            print(f"cannot re-sign: {type(e).__name__}")
            return 1
        print(f"re-signed {d / MANDATE_FILE}")
        return 0
    if a.check:
        problems = doctor(d)
        if not problems:
            print(f"ok: configuration in {d} is healthy")
            return 0
        print(f"{len(problems)} problem{'s' if len(problems) != 1 else ''} found in {d}:")
        for p in problems:
            print("problem:", p)
        print("fix them, then run `orderguard doctor` again. See docs/GUIDE.md (Troubleshooting) for each message.")
        return 1
    try:
        init(d, a.provider, a.force)
    except FileExistsError as e:
        print(f"refusing: {e}")
        return 1
    print(f"created {d}: {KEY_FILE} (mode 600, not shown), {PUB_FILE}, {MANDATE_FILE} (signed), {ENV_FILE} (names only)")
    print("next steps:")
    print(f"  1. edit {d / MANDATE_FILE} limits and referencePrices, then re-sign: `orderguard init --resign`")
    print(f"  2. put {PROVIDERS[a.provider]} and ORDERGUARD_APP_TOKEN in {d / ENV_FILE} (or export them)")
    print("  3. verify with `orderguard doctor`")
    print(f"  4. start the receiver: node receiver/bridge/serve.mjs --mandate {d / MANDATE_FILE}")
    print("  5. open the dashboard: `orderguard serve` then http://127.0.0.1:8600")
    return 0
