# Threat model

## Goal

Prevent an agent, compromised client or misleading input from causing a receiver-side effect outside the human's signed authority. The receiver controls the final action boundary.

## Threats and controls

| Attack family | Example | Main control | Evidence and current boundary |
|---|---|---|---|
| Compromised client | Client changes a valid proposal into a broader order. | Receiver verifies the exact signed scope at commit time. | [VERIFIED] B9 (evidence archive not included in this repository) confirms one recorded scripted pair; its matched control passed after the script widened signed scope. |
| Poisoned news or retrieved text | A planted instruction asks the agent to trade an unapproved instrument. | Treat context and agent reasoning as untrusted; exact receiver mandate check remains authoritative. | [VERIFIED] N4 (evidence archive not included in this repository) validates static scenario cards. [OWNER-MEASURED] Saved-response evidence is a diagnostic, not a fresh model trial. |
| Forged or absent human proof | Caller submits an invalid or missing assertion. | Verify the challenge and signature before granting authority. | [OWNER-MEASURED] Hunter-sys V-015 (evidence archive not included in this repository) has ten synthetic trials per case; independent review pending. |
| Stale, spoofed or substituted fields | Proposal supplies favorable account or quote values. | Read authority fields from receiver-owned sources and bind content provenance. | [OWNER-MEASURED] Narrow component evidence; V-002, V-005, V-011 and V-022 remain open. |
| Duplicate, delayed or interrupted requests | Retry, crash or timeout races a ledger write. | Atomic reservation, idempotency and fail-closed commit path. | [VERIFIED] N1 and N2 (evidence archive not included in this repository) cover one-host local simulation and bounded schedules. |
| Revoked mandate | Mandate is withdrawn while a request is in flight. | Check revocation again at the receiver boundary. | [VERIFIED] Q5 (evidence archive not included in this repository) is a joined recorded-action replay: GLM-labelled actions, 30/30 front-door-only effects vs 0/30 receiver effects; benign utility was Luna 27/27, GLM 30/30 and DeepSeek 29/29 in both arms. Provider authenticity is not established. |
| Manipulation inside allowed scope | Price, timing or rationale is suspicious although action is in mandate. | Optional Lock-2 may hold or ask for human step-up; it can only deny or step up. | [OWNER-MEASURED · CP2; verifier pending] V-033 reports 8/10 exact U+200B variants allowed and committed; the ordinary-space counterpart stepped up 10/10. This is a bounded intent/provenance failure, not an out-of-mandate bypass. |

## In scope

The release demonstrates mandate-bound actions on a local paper ledger and packages offline lab artifacts. Its evidence covers input manipulation, compromised clients, authorization failures, stale fields, retries and recorded-action revocation replay. Each result is limited to its named fixture and source snapshot.

## Out of scope

The current release does not establish protection against every model, every attack, multiple hosts, production-scale concurrency, real brokerage execution, venue-specific cancellation, or losses caused by an action that is valid under the signed mandate. The receiver's deterministic boundary bounds authority; it does not establish that the agent's beliefs are true.
