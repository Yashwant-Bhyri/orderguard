# Release portability patches

The r5 release subset is based on the candidate snapshot named in `SOURCE-MAP.json`. Three files have release-only edits; every other listed source file retains its candidate SHA-256. The map records the release hash for each file. The candidate digest is an upstream snapshot identifier and does not mean these edits are part of that candidate.

- `server.ts`: the scenario-card path is receiver-relative; arena spend logging requires `ORDERGUARD_SPEND_CSV`; provider keys are loaded from a file only when `ORDERGUARD_ENV_FILE` is explicitly set.
- `execution-mesh.ts`: the packaged service worker searches receiver ancestors for the repository `tsx` loader.
- `intel/second-lock.ts`: spend rows are written only when `ORDERGUARD_SPEND_FILE` is explicitly set.

The duplicated W3 copy at `receiver/intel/second-lock.ts` has the same explicit spend-file behavior. The W3 research scripts use `ORDERGUARD_*` overrides and repository-relative defaults in place of workstation paths. The Hunter LLM ASB report copies and Scout/W6 indexes also replace workstation-specific path text with release-relative wording. These portability edits do not change the published evidence status.
- `server.ts` (later edit): the static-asset allow-list no longer names evidence and result files that are not part of this repository, so those paths always return 404. The recorded hash for `server.ts` in `SOURCE-MAP.json` predates this edit.
- `server.ts` (anchor renewal): `ORDERGUARD_HUMAN_MANDATE_TTL_MS` shortens the human mandate lifetime (clamped to 2 s to 1 h, default unchanged at 1 h). The bridge sets it so its one-share anchor mandate can be renewed and tested in seconds.
