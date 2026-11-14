"""Owner CLI for the signed paper receiver and its revision-bound authorizations."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx

from . import init_cmd
from .gate import Mandate, canonical_json, private_key_from_b64, public_key_to_b64
from .mandate_fit import check_mandate_fit
from . import ROOT
from .receiver_client import Bridge, Receiver, ReceiverError, scrub

ACTIVATE = "orderguard.paper-draft-activation.v1"
APPROVE = "orderguard.paper-order-approval.v1"
REVOCATIONS = "revoked-mandates.json"
LEDGER_TOOL = ROOT / "receiver" / "bridge" / "ledger-tool.mjs"
DEFAULT_LEDGER = Path("ledger") / "paper-ledger.sqlite"


def _writable(path: Path) -> bool:
    """Could `path` be created? Checks the nearest directory that exists."""
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    return probe.is_dir() and os.access(probe, os.W_OK | os.X_OK)


def resolve_ledger(directory: Path, explicit=None, ephemeral: bool = False, env=None) -> tuple[Path | None, str]:
    """Where the paper receiver keeps its ledger: -> (path or None for a throw-away ledger, note for the person starting it).

    Order: --ephemeral, then --ledger, then ORDERGUARD_LEDGER (`:ephemeral` also means throw-away), then `<config dir>/ledger/paper-ledger.sqlite`.
    If that default is not writable (a read-only container mount) the receiver still starts, but says plainly that nothing will persist."""
    env = os.environ if env is None else env
    if ephemeral:
        return None, "Ledger: throw-away (--ephemeral). Orders and idempotency keys are lost when the receiver stops."
    chosen = explicit or env.get("ORDERGUARD_LEDGER") or None
    if chosen == ":ephemeral":
        return None, "Ledger: throw-away (:ephemeral). Orders and idempotency keys are lost when the receiver stops."
    if chosen:
        return Path(chosen), "Ledger: persistent, verified at start."
    default = directory / DEFAULT_LEDGER
    if _writable(default.parent):
        return default, f"Ledger: persistent at {scrub(default)}, verified at start."
    return None, ("Ledger: throw-away, because the config directory is not writable. Orders and idempotency keys are lost when the receiver "
                  "stops. Pass --ledger PATH (or set ORDERGUARD_LEDGER) to a writable location to keep them.")


def _proof(payload: bytes, signature: bytes) -> dict:
    return {"payload": base64.b64encode(payload).decode("ascii"),
            "signature": base64.b64encode(signature).decode("ascii")}


def parent_proof(parent: dict) -> dict:
    mandate = Mandate.from_dict(parent)
    return _proof(canonical_json(mandate.to_dict(with_signature=False)), base64.b64decode(mandate.signature, validate=True))


def sign_action(key, state: dict, purpose: str, **terms) -> dict:
    payload = canonical_json({"purpose": purpose, "parentId": state["parentId"], "ledgerId": state["ledgerId"],
                              "revision": state["revision"], **terms})
    return _proof(payload, key.sign(payload))


def _configured(directory: Path):
    from orderguard_arena.policy_review import load_parent

    parent, key, revoked = load_parent("configured", directory)
    mandate = Mandate.from_dict(parent)
    fit = check_mandate_fit(parent, mandate.to_dict(with_signature=False), key, revoked=revoked)
    if not fit["fits"]:
        raise ValueError(fit["violations"][0]["reason"])
    return parent, key, revoked, mandate.id


def paper_receiver(a) -> int:
    directory = (a.dir or init_cmd.default_dir()).resolve()
    try:
        parent, _, _, _ = _configured(directory)
        with TemporaryDirectory(prefix="orderguard-parent-") as tmp:
            path = Path(tmp) / "parent.json"
            path.write_text(json.dumps(parent_proof(parent)), encoding="utf-8")
            ledger, note = resolve_ledger(directory, a.ledger, a.ephemeral)
            with Bridge.start(path, port=a.port, owner_public_key=directory / init_cmd.PUB_FILE,
                              revocations=directory / REVOCATIONS, ledger=ledger) as bridge:
                print(f"Signed paper receiver at http://127.0.0.1:{bridge.port}", flush=True)
                print(note, flush=True)
                return bridge.proc.wait()
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, ReceiverError) as exc:
        print(f"Paper receiver could not start. {scrub(exc)}", file=sys.stderr)
        return 1


def _loopback(value: str) -> str:
    url = urlsplit(value)
    if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.netloc != f"127.0.0.1:{url.port}" or (
        url.path not in ("", "/") or url.query or url.fragment
    ):
        raise ValueError("Use the signed paper receiver's http://127.0.0.1:PORT address.")
    return f"http://127.0.0.1:{url.port}"


def _receiver_state(receiver: Receiver, parent_id: str) -> dict:
    state = receiver.policy()
    if not isinstance(state, dict):
        raise ValueError("The receiver did not return a policy object.")
    ledger_id, revision = state.get("ledgerId"), state.get("revision")
    if state.get("parentId") != parent_id or not isinstance(ledger_id, str) or not re.fullmatch(r"[0-9a-f]{32}", ledger_id) or (
        type(revision) is not int or not 0 <= revision < 2**53 - 1
    ):
        raise ValueError("The receiver did not return a revision for the configured signed parent.")
    return state


def owner_action(a) -> int:
    directory = (a.dir or init_cmd.default_dir()).resolve()
    try:
        url = _loopback(a.receiver)
        parent, public_key, revoked, parent_id = _configured(directory)
        activate = a.cmd == "activate-draft"
        if activate:
            draft = json.loads(a.draft.read_text(encoding="utf-8"))
            fit = check_mandate_fit(parent, draft, public_key, revoked=revoked)
            if not fit["fits"]:
                print(json.dumps(fit, indent=2))
                return 1
        with httpx.Client(trust_env=False) as client:
            receiver = Receiver(url, client=client)
            state = _receiver_state(receiver, parent_id)
            key = private_key_from_b64((directory / init_cmd.KEY_FILE).read_text(encoding="utf-8").strip())
            if public_key_to_b64(key.public_key()) != public_key_to_b64(public_key):
                raise ValueError("The local signing key does not match the configured owner public key.")
            if activate:
                result = receiver.activate_policy(sign_action(key, state, ACTIVATE, draft=fit["draft"]))
                ok = "policy" in result
            else:
                result = receiver.approve_paper_order(a.order_id, sign_action(key, state, APPROVE, orderId=a.order_id))
                ok = result.get("decision") == "filled"
        print(json.dumps(result, indent=2))
        return 0 if ok else 1
    except (ValueError, OSError, ReceiverError) as exc:
        print(f"Owner action failed. {scrub(exc)}", file=sys.stderr)
        return 1


def ledger_tool(a) -> int:
    """verify | export | backup for a paper ledger file. Works while the receiver runs. Exit 0 verified, 1 failed verification, 2 other problem."""
    directory = (a.dir or init_cmd.default_dir()).resolve()
    ledger, _ = resolve_ledger(directory, a.ledger)
    if ledger is None:
        print("No persistent ledger is configured. Pass --ledger PATH, or start the receiver with a writable config directory.", file=sys.stderr)
        return 2
    if shutil.which("node") is None or not LEDGER_TOOL.exists():
        print("The ledger tool needs Node 22.13+ and the receiver/ directory of this checkout.", file=sys.stderr)
        return 2
    args = [a.action, "--ledger", str(ledger)]
    if a.action != "verify":
        out = a.out
        if out is None:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            name = f"ledger-{a.action}-{stamp}." + ("json" if a.action == "export" else "sqlite")
            out = ledger.parent / "backups" / name
        Path(out).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args += ["--out", str(out)]
    if a.action == "verify" and a.expect_head:
        args += ["--expect-head", a.expect_head]
    done = subprocess.run(["node", str(LEDGER_TOOL), *args], cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    print(scrub(done.stdout), end="")
    if done.stderr.strip():
        print(scrub(done.stderr.strip()), file=sys.stderr)
    return done.returncode


def add_commands(sub) -> None:
    serve = sub.add_parser("paper-receiver", help="start a paper receiver with the configured signed parent")
    serve.add_argument("--dir", type=Path, help="owner configuration directory")
    serve.add_argument("--port", type=int, default=8700)
    serve.add_argument("--ledger", help="persistent ledger file (default: <config dir>/ledger/paper-ledger.sqlite, or $ORDERGUARD_LEDGER)")
    serve.add_argument("--ephemeral", action="store_true", help="use a throw-away ledger removed when the receiver stops")
    serve.set_defaults(fn=paper_receiver)
    for action, text in (("verify", "check a paper ledger's hash chain and records"), ("export", "write a JSON export of a paper ledger"),
                         ("backup", "write a verified SQLite backup of a paper ledger")):
        cmd = sub.add_parser(f"ledger-{action}", help=text)
        cmd.add_argument("--dir", type=Path, help="owner configuration directory")
        cmd.add_argument("--ledger", help="ledger file (default: the receiver's default ledger)")
        if action != "verify":
            cmd.add_argument("--out", type=Path, help="output file (default: next to the ledger, in backups/)")
        else:
            cmd.add_argument("--expect-head", help="SEQ:HASH recorded earlier; fails if the ledger no longer contains it")
        cmd.set_defaults(fn=ledger_tool, action=action, **({"out": None} if action == "verify" else {"expect_head": None}))
    activate = sub.add_parser("activate-draft", help="sign and activate a contained draft on the local paper receiver")
    activate.add_argument("draft", type=Path, help="unsigned draft JSON")
    approve = sub.add_parser("approve-paper-order", help="sign a step-up approval for one held paper order")
    approve.add_argument("order_id")
    for command in (activate, approve):
        command.add_argument("--dir", type=Path, help="owner configuration directory")
        command.add_argument("--receiver", default="http://127.0.0.1:8700", help="signed paper receiver address")
        command.set_defaults(fn=owner_action)
