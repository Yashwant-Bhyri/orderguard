"""Owner CLI for the signed paper receiver and its revision-bound authorizations."""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import httpx

from . import init_cmd
from .gate import Mandate, canonical_json, private_key_from_b64, public_key_to_b64
from .mandate_fit import check_mandate_fit
from .receiver_client import Bridge, Receiver, ReceiverError

ACTIVATE = "orderguard.paper-draft-activation.v1"
APPROVE = "orderguard.paper-order-approval.v1"
REVOCATIONS = "revoked-mandates.json"


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
            with Bridge.start(path, port=a.port, owner_public_key=directory / init_cmd.PUB_FILE,
                              revocations=directory / REVOCATIONS) as bridge:
                print(f"Signed paper receiver at http://127.0.0.1:{bridge.port}", flush=True)
                return bridge.proc.wait()
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, ReceiverError) as exc:
        print(f"Paper receiver could not start. {exc}", file=sys.stderr)
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
        print(f"Owner action failed. {exc}", file=sys.stderr)
        return 1


def add_commands(sub) -> None:
    serve = sub.add_parser("paper-receiver", help="start a paper receiver with the configured signed parent")
    serve.add_argument("--dir", type=Path, help="owner configuration directory")
    serve.add_argument("--port", type=int, default=8700)
    serve.set_defaults(fn=paper_receiver)
    activate = sub.add_parser("activate-draft", help="sign and activate a contained draft on the local paper receiver")
    activate.add_argument("draft", type=Path, help="unsigned draft JSON")
    approve = sub.add_parser("approve-paper-order", help="sign a step-up approval for one held paper order")
    approve.add_argument("order_id")
    for command in (activate, approve):
        command.add_argument("--dir", type=Path, help="owner configuration directory")
        command.add_argument("--receiver", default="http://127.0.0.1:8700", help="signed paper receiver address")
        command.set_defaults(fn=owner_action)
