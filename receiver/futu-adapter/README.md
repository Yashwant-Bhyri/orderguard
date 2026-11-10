> Status: unexercised. This adapter has never been run against a Futu OpenD SIMULATE account in this repository, it is closed by default behind two environment flags, and no test or script here enables it or calls a broker.

# OrderGuard Futu SIMULATE adapter

The adapter bridges an already committed OrderGuard paper-ledger order to a
local Futu OpenD account in `TrdEnv.SIMULATE`. Its safety boundary is the
receiving mesh: the committed order, approved execution, mapped HK symbol,
selected paper account, quote freshness, and Futu response are checked before
the dispatch can be reconciled.

```text
roster proposal -> mandate receiver -> committed paper ledger
                              |                     |
                         blocked/held           approved
                              |                     v
                         no dispatch        Futu adapter -> OpenD SIMULATE
                                                   |
                                   order list + positions reconciliation
```

The adapter has no `REAL`, unlock, password-entry, or `trade:write` route. OpenD
must already be running and logged in; the adapter never signs in or unlocks.
`config.json` maps fictional MANDATE-M1 symbols to HK listings for simulator
routing only. Those aliases do not identify or represent the issuers.

## Current evidence status — 2026-11-03

| Evidence | Status | Bounded result |
|---|---|---|
| SIMULATE-only refusal paths | **CONFIRMED**, narrow | REAL, unlock, and ambiguous non-paper account requests refuse before a gateway call. |
| LocalSim offline fault campaign | **OWNER-MEASURED** | 18/18 local cases pass; zero OpenD calls, Futu submissions, and provider calls. The release artifact passes the v2 local integrity audit. This is not live Futu behavior. |
| Dispatch worker crash/restart | **OWNER-MEASURED**, synthetic | 10/10 process crashes after a synthetic venue acceptance recover by remark reconciliation, with one placement each and zero position/order mismatches; an uncommitted dispatch is refused (1/1). No OpenD, Futu, provider, or external network calls. This exercises the adapter worker boundary, not a live broker or the W3 policy host. |
| Lock-2 sidecar outage / W2 LocalSim gate seam | **OWNER-MEASURED**, synthetic | The actual `intel/second-lock.ts` reviewer reached a closed loopback sidecar and failed closed with `step_up` in 10/10 flagged cases; all 10 then hit the adapter's missing-commit refusal with zero LocalSim placements. Paired clean controls allowed and reconciled 10/10 through LocalSim (10 placements, zero mismatches). No provider, OpenD, Futu, or external-network calls. This is a reviewer-to-adapter seam harness, not an actual W3 policy-host process crash or live Futu evidence. |
| Scheduler quote timestamp gate | **OWNER-MEASURED**, synthetic | Validates HK/offset timestamps, rejects quotes older than 60 seconds or more than 5 seconds ahead, and fails closed on malformed timestamps. The 12-row proof does not call OpenD or Futu. |
| Scheduler process status | **OWNER-MEASURED**, synthetic | Separates `alive`, `dead`, and `unknown` PID outcomes. Unknown ownership is displayed as unverified; start avoids a duplicate and stop refuses to signal it. Synthetic proof: 4/4 outcomes. |
| Current host scheduler status | **UNVERIFIED** | The PID file names unverified scheduler PID, but this host cannot establish process identity. The status command now reports `state=unverified`; do not infer that the scheduler is running or stopped from the PID file. |
| Monday HK SIMULATE batch | **PENDING / blocked** | Both Nov 2 scheduled health gates stopped before demo startup. No order batch ran, so placement, blocked-to-Futu, reconciliation, and latency KPIs are unmeasured. |

The live batch remains the acceptance proof. Never interpret a health-stop row
or an offline LocalSim case as `blocked_sent_to_futu=0` for a live batch.
See W2 evidence index (evidence archive not included in this repository) for commands, literal outputs,
result files, and review status.

## Safe offline verification

Install the pinned Python SDK only if you need the live adapter. The local
fault campaign and its saved-result audit do not call OpenD, Futu, or a model.

```sh
env -u OPENROUTER_API_KEY -u OPENAI_API_KEY -u LIQUID_API_KEY -u TYPESAFE_API_KEY \
  ORDERGUARD_DISABLE_LOCAL_ENV=1 \
  python3 futu-adapter/offline_fault_campaign_audit.py \
  futu-adapter/results/release/2026-11-02/offline-fault-campaign.json
```

The audit prints `PASS_WITH_LOCAL_PROVENANCE` only when the saved 18-case JSON
and its sibling source bundle agree on the exact case set, source hashes, and
synthetic quote-fixture hash. It checks bundle consistency; it does not
authenticate a publisher or establish OpenD/Futu behavior.

The scheduler also has a deterministic timestamp-only preflight proof. Its
clock is fixed to a synthetic HKT instant and the script has no venue or model
calls:

```sh
env -u OPENROUTER_API_KEY -u OPENAI_API_KEY -u LIQUID_API_KEY -u TYPESAFE_API_KEY \
  ORDERGUARD_DISABLE_LOCAL_ENV=1 \
  python3 futu-adapter/offline_quote_freshness_proof.py
```

The scheduler rejects malformed timestamps, quotes more than 60 seconds old,
and timestamps more than 5 seconds ahead of the local HK clock.

Process supervision uses a three-state PID check. A synthetic permission denial
is reported as unverified rather than running; the scheduler avoids a second
launch and refuses to send a stop signal until process identity is knowable.
The proof uses mocked PID outcomes and never signals a host process.

The Lock-2 outage seam has a separate one-command proof. It uses the real
TypeScript reviewer with synthetic trusted-state readers, reserves then closes
loopback ports to make the decision sidecar unavailable, and pairs flagged
orders with clean LocalSim controls. It never starts a model/provider, OpenD,
Futu, or the scheduler:

```sh
env -u OPENROUTER_API_KEY -u OPENAI_API_KEY -u LIQUID_API_KEY -u TYPESAFE_API_KEY \
  ORDERGUARD_DISABLE_LOCAL_ENV=1 PYTHONDONTWRITEBYTECODE=1 \
  ./node_modules/.bin/tsx futu-adapter/offline_lock2_outage_localsim_proof.mts
```

The saved result records n=20, k=20 across 10 flagged outage cases and 10
benign controls. The loopback refusal demonstrates the sidecar-unavailable
fallback in the reviewer; the Python bridge separately demonstrates the
uncommitted adapter gate and a synthetic LocalSim accepted/reconcile path. It
does not establish a process crash in W3's host or any live broker behavior.

## Attended SIMULATE replay

The one-command entrypoint is `python3 futu-adapter/demo.py`. First create the
pinned environment and set paths to local-only configuration files. Do not
put key values in command-line arguments or repository files.

```sh
python3 -m venv futu-adapter/.venv
futu-adapter/.venv/bin/python -m pip install -r futu-adapter/requirements.txt
ORDERGUARD_FUTU_ENV_FILE=/path/to/private/provider-keys.local \
ORDERGUARD_ROOM_SPEND_CSV=/path/to/room/SPEND.csv \
futu-adapter/.venv/bin/python futu-adapter/demo.py
```

The env file is read into the demo process and passed to the mesh child in
memory; values are not written to results or logs. Before any proposal, the
entrypoint checks OpenD, the HK market session, the SIMULATE stock account,
and mapped quotes no older than 60 seconds. An unhealthy gate stops before the batch. A healthy
gate submits the planned 20–50 proposals through the mesh and reconciles Futu
order-list and position state against the ledger. Run this only as an attended
SIMULATE session; the Nov 2 live acceptance batch is still pending.

For scheduled HK sessions, configure `ORDERGUARD_FUTU_ENV_FILE`,
`ORDERGUARD_FUTU_SESSIONS_CSV`, and optionally `ORDERGUARD_ROOM_ROOT` and
`ORDERGUARD_ROOM_SPEND_CSV`, then run `python3 futu-adapter/scheduler.py start`
once. The runner uses a singleton lock, health-checks each scheduled session,
and fails closed. Its default state and session files are user-cache and
component-results paths; it writes a room alert only when a room root is
configured.

## Mapped symbols

`VLTA`, `ACMX`, and `BRSK` are fictional mandate symbols mapped to HK listing
codes for paper simulation. `HLQ` and `SYNTH3` intentionally have no route.
The mapping is an execution fixture, not an issuer-identity assertion or
investment recommendation.

## References used by this component

- [Futu Python SDK — Place Orders](https://openapi.futunn.com/futu-api-doc/en/trade/place-order.html): explicit environment/account arguments; this adapter pins `SIMULATE`.
- [Futu Python SDK — Get Order List](https://openapi.futunn.com/futu-api-doc/en/trade/get-order-list.html) and [Get Position List](https://openapi.futunn.com/futu-api-doc/en/trade/get-position-list.html): reconciliation inputs.
- [Futu API Program Samples](https://openapi.futunn.com/futu-api-doc/en/quick/demo.html): documented HK SIMULATE order-type behavior used for a narrowly scoped translation bucket.
- [vn.py Futu gateway](https://github.com/veighna-global/vnpy_futu/blob/main/vnpy_futu/futu_gateway.py): order-state and broker-identifier mapping patterns.
