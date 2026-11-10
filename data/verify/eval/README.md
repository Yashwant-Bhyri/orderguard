# Eval fixtures (the DEVELOPMENT set)

This is the synthetic development set: 80 cases written by the builder, tuned against, and used by `og eval` and `og gate`. It shows that rules fire. It is **not** a held-out result; that is the native-error test (`docs/PROTOCOL.md`, `og native`).

Every memo in `cases.json` is a SYNTHETIC test fixture, not real research. The figures are real SEC numbers or, in
planted cases, deliberately wrong ones; the rumours and opinions are invented. `specs.json` is the answer key,
`memos.json` the prose (hand-written by `tools/write_memos.py`), `cases.json` the merged result.
