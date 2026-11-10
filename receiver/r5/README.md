# r5 receiver (imported snapshot)

Runtime source and web assets imported from an earlier receiver snapshot. `SOURCE-MAP.json` records source hashes; `PATCHES.md` lists the portability edits made to three files.

In this repository r5 is used for the owner passkey ceremony and for the signed human mandate and its revocation state. The scope and budget checks for the bridge live in `../core`. The earlier test evidence for r5 is not included here, so treat its claims as unverified. Run `npm run quickstart` from the repository root for a no-key demo; it makes no provider, venue or live-order calls.
