# SEC access note

Round 3 status, after the round-2 review and the lead review of 2026-11-19.

- The brief's fallback client name (`OrderGuard-Lab research`) received **HTTP 403** from `www.sec.gov` for both N-PORT data-set ZIPs. No contact `SEC_USER_AGENT` was available, and I did not invent an email.
- The lead review explicitly accepts the Internet Archive copy of the SEC's own published N-PORT data sets and says **not** to write `BLOCKED.md`.
- Sources used:
  - 2026q1 (frozen-rule evaluation): `https://web.archive.org/web/20260406172749if_/https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q1_nport.zip`; 463,076,167 bytes; SHA-1 base32 `KFOZ7DK2247LE7CYQH4AW3DAE36LDOEL`, matching the snapshot digest; SHA-256 `7626e33d21ab48169db412f7370190a9ba8d6a2c921718e59a445b333b23694c`.
  - 2026q2 (exploratory): `https://web.archive.org/web/20260803175507if_/https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q2_nport.zip`; 440,699,889 bytes; SHA-1 base32 `GZENDVDXBQRAYO5KMMY5S4WKGRTHXR7Y`, matching the snapshot digest; SHA-256 `077cc836a978a593b29012219395fbe9c303d5e930f5be3b5f4353c3b02296fc`.
- All requests, including retries and redirects, are paced at at most 10 per second. Both quarters were downloaded in round 3. The 2026q1 download made 147 requests with a measured maximum of 8 in any 1-second window; the 2026q2 download made 150 requests with the same maximum.
- If a founder-approved `SEC_USER_AGENT` is set later, `download.py` probes SEC directly even when a cache exists. On HTTP 200 it attempts a direct download to a temporary path and records `direct_sha256` and `direct_sha256_matches_archive`; on a refusal or error it records the attempt. Either way it keeps the verified archive. The live EDGAR check is in `verify_edgar.py`; without `SEC_USER_AGENT` it prints `skipped: no SEC_USER_AGENT`.
- Privacy: the raw cache contains the public registrant business-contact block in `REGISTRANT.tsv` (address, city, state, country, ZIP, phone). It is entity contact data, not natural-person data; the pipeline reads only `CIK` and `REGISTRANT_NAME` from that table and never emits the contact fields. See `privacy_scan.json` and section 3.10 of `REPORT.md`.
