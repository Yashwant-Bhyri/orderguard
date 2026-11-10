# Architecture

## The goal

By Nov 22, the product goal is a workflow where a human sets a bounded strategy, agents act on valid signals, and each receiver checks the exact action before any effect. The lab attacks the same path, and each decision should be traceable to its source and authority. [PENDING] This is the roadmap destination, not a claim that every capability is already shipped.

## The request path

The SDK and MCP server are client interfaces. The receiver is the enforcement boundary. A local ledger records the result. Optional Lock-2 can deny or request human step-up, but cannot loosen the deterministic decision.

~~~mermaid
flowchart LR
  H[Human signs bounded mandate] --> A[Agent client: SDK or MCP]
  A --> R[Receiver verifies exact action]
  R --> F[Field authority and current receiver state]
  F --> L[Atomic local paper ledger]
  R -->|signal or uncertainty| G[Lock-2: deny or step up]
  G -->|within first-lock authority| F
  L --> V[Venue adapter: in evaluation]
  V --> E[Audit evidence]
~~~

The owner-run integration quickstart used a synthetic signer and loopback LocalSim paper receiver. [OWNER-MEASURED] The documented npm quickstart, package tests and committable-file scan passed from an isolated release copy; see the clean-copy record (evidence archive not included in this repository). [OWNER-MEASURED] The example does not yet select the packaged `receiver/r5` entry point; that integration remains [PENDING].

## Technical layers

| Layer | Responsibility | Current status |
|---|---|---|
| Human-signed mandate | Define instruments, actions, price/quantity authority, budget and expiry; keep the signing key out of the agent process. | [LIVE] MANDATE-M1 is a synthetic scenario. Quickstart signing is virtual, not a physical passkey ceremony. |
| SDK and MCP adoption surface | Let an agent read its mandate, submit a typed proposal, query status and request cancellation. | [LIVE] Packaged in this repository. These clients do not enforce authority on their own. |
| Receiver | Verify signature, audience, account, expiry, revocation and exact canonical action at the receiving boundary. | [VERIFIED] B9 confirms one recorded scripted pair (evidence archive not included in this repository) in synthetic state. The r5 source digest remains a candidate pending independent suite review. |
| Field authority | Check which proposal fields are exact user values and which may vary only inside signed bounds. | [OWNER-MEASURED] Implemented in the mesh; open field-authority variants remain in docs/findings.md. |
| Atomic paper ledger | Recheck budget, idempotency and revocation while committing a synthetic state change. | [VERIFIED · historical] N1/N2 (evidence archive not included in this repository) cover bounded local fault, mutation and race cases. One-host SQLite only. |
| Lock-2 | Add a hold, denial or human step-up for suspicious in-mandate behavior. Never authorize a deterministic denial. | [OWNER-MEASURED · CP2; verifier review pending] V-033 reports an exact U+200B feature miss in a bounded synthetic replay; no broad efficacy claim. See docs/results.md. |
| Revocation and venue closeout | Block new work after revoke/expiry and reconcile queued or venue-resident orders. | [VERIFIED] Q5 (evidence archive not included in this repository) is a joined recorded-action replay only; provider authenticity is not established. Venue closeout remains [PENDING]. |
| Venue adapters | Route a verified effect to a simulator or explicitly scoped test environment. | [IN-EVALUATION] Futu SIMULATE and Binance Testnet have no cleared result counts. |
| Audit chain | Preserve decision and effect records so a result can be checked against the ledger state. | [OWNER-MEASURED] Local integrity checks exist; rollback resistance and journal completeness have open findings. |
| Key hygiene | Keep provider and signing credentials in their owning process, never in source, logs or evidence. | [LIVE] Release rule. The repository contains no keys or private audit sidecars. |

## Product capabilities by stage

The end goal is broader than the current receiver demo. The labels below distinguish shipped scope from intended work.

| Capability | Status | What it means |
|---|---|---|
| Pre-signed authority | [LIVE] | A human defines an allowed action envelope before the agent acts. |
| Exact order check | [LIVE] | A receiver checks the action before an effect. |
| Holds under failure | [VERIFIED] | Seeded local faults preserve the stated ledger invariants in the tested scope. |
| Evidence status on claims | [LIVE] | Results are labeled by measurement and review state. |
| SDK and MCP interfaces | [LIVE] | Standard agent integration paths submit proposals to the receiver. |
| Strategy-wide mandate | [DESIGN] | Sign once for an entire strategy's universe, sizing rule and expiry. |
| Provenance chain per action | [DESIGN] | Bind each action to its source, freshness and signed authority. |
| Independent proof-verifier agents | [DESIGN] | Check claims and evidence before use; these agents can only deny or ask a human. |
| Blast-radius containment | [DESIGN] | Keep triggers scoped to their instrument and limits; require step-up for fan-out. |
| Revocation sweep | [BUILDING] | Cancel or reconcile queued and venue-resident orders after revocation. |
| Detonation chamber | [BUILDING] | Replay memories and new information under simulated futures to find planted time-bombs before use. |
| Brittle-points registry | [DESIGN] | Track combinations of rules, holdings and alerts that could fail together. |
| Hybrid graph | [DESIGN] | Connect rules, positions, news and agent notes to reveal cascades. |
| Mature-trader sandbox | [BUILDING] | Compare legitimate task utility with and without controls in a realistic workflow. |
| Second lock | [BUILDING] | Review suspicious in-scope actions; catch rate remains pending. |
| Venue readiness | [BUILDING] | Evaluate adapters separately before any broader venue claim. |
| Adversarial lab | [BUILDING] | Expand repeatable attacks, bug hunting and public benchmark comparisons. |

## Trust boundaries

- **Trusted by the receiver:** verified human signature, receiver configuration, receiver-owned account and quote fields, current ledger state and revocation state.
- **Untrusted:** agent proposals, news, retrieved documents, tool outputs, model explanations and client-side policy checks.
- **Deterministic floor:** exact mandate and field checks decide whether an action is allowed. Intelligence can add a hold or step-up but cannot grant authority.
- **Evidence boundary:** each measurement belongs to its stated source snapshot, fixture and denominator. Simulation evidence does not establish production or broker behavior.

## Current limits

The receiver evidence is local and synthetic. Multi-host consistency, production-scale concurrency, live brokerage execution, venue-specific cancellation and the truth of an agent's beliefs remain [PENDING]. The receiver bounds authorized effects; it does not establish that an allowed action is wise.
