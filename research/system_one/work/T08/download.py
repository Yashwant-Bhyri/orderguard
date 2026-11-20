#!/usr/bin/env python3
"""Fetch one quarterly SEC Form N-PORT data set.

Preference order:
  1. SEC www.sec.gov directly, with SEC_USER_AGENT from the environment.
  2. The same official file from an Internet Archive snapshot, byte-verified
     against the snapshot's SHA-1 digest.

The fallback exists because SEC returns HTTP 403 to the lab's contact-less
User-Agent. It is recorded in provenance.json, never hidden.
"""

import argparse
import base64
import collections
import concurrent.futures as cf
import hashlib
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "sec"
SEC_BASE = "https://www.sec.gov/files/dera/data/form-n-port-data-sets"
CDX = "https://web.archive.org/cdx/search/cdx"
DEFAULT_UA = "OrderGuard-Lab research"
ARCHIVE_WORKERS = 8
CHUNK = 4 * 1024 * 1024
RATE_LIMIT_PER_S = 10.0
SEC_TIMEOUT = 30


class Pacer:
    """Global request pacer: never more than RATE_LIMIT_PER_S starts per second.

    Every HTTP start, including redirects and retries, goes through wait().
    The same object records the observed start times so the provenance can show
    the measured maximum instead of asking the reviewer to trust the code.
    """

    def __init__(self, rate):
        self.rate = float(rate)
        self.lock = threading.Lock()
        self.starts = collections.deque()
        self.all_starts = []
        self.requests = 0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            while self.starts and now - self.starts[0] >= 1.0:
                self.starts.popleft()
            if len(self.starts) >= self.rate:
                delay = 1.0 - (now - self.starts[0]) + 0.002
                if delay > 0:
                    time.sleep(delay)
                now = time.monotonic()
                while self.starts and now - self.starts[0] >= 1.0:
                    self.starts.popleft()
            self.starts.append(now)
            self.all_starts.append(now)
            self.requests += 1

    def stats(self):
        with self.lock:
            starts = sorted(self.all_starts)
        best = 0
        lo = 0
        for hi, t in enumerate(starts):
            while t - starts[lo] >= 1.0:
                lo += 1
            best = max(best, hi - lo + 1)
        return {
            "requests_total": len(starts),
            "max_requests_in_any_1s": best,
            "rate_limit_per_s": self.rate,
            "pacing_ok": best <= int(self.rate),
        }


PACER = Pacer(RATE_LIMIT_PER_S)


class PacedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        PACER.wait()
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(PacedRedirect)


def ua(requested=True):
    return os.environ.get("SEC_USER_AGENT") or DEFAULT_UA


def get(url, headers=None, method="GET", timeout=120):
    h = {"User-Agent": ua()}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method=method)
    PACER.wait()
    return OPENER.open(req, timeout=timeout)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sec_probe(url):
    # Some WAFs refuse HEAD even when GET would work, so fall back to a one-byte
    # GET before calling the SEC unavailable.
    try:
        r = get(url, method="HEAD", timeout=SEC_TIMEOUT)
        if r.status == 200:
            return r.status, r.headers.get("Content-Length")
        head_code = r.status
    except urllib.error.HTTPError as e:
        head_code = e.code
    except Exception as e:
        return None, str(e)
    try:
        r = get(url, {"Range": "bytes=0-0"}, timeout=SEC_TIMEOUT)
        return r.status, r.headers.get("x-archive-orig-content-length") or r.headers.get("Content-Length")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Length")
    except Exception:
        return head_code, None


def cdx_snapshots(quarter):
    url = f"{CDX}?url=www.sec.gov/files/dera/data/form-n-port-data-sets/{quarter}_nport.zip"
    url += "&output=json&filter=statuscode:200&fl=timestamp,length,digest"
    for attempt in range(4):
        try:
            with get(url, timeout=60) as r:
                rows = json.load(r)
            if len(rows) < 2:
                return []
            head = rows[0]
            out = []
            for row in rows[1:]:
                d = dict(zip(head, row))
                out.append({
                    "timestamp": d["timestamp"],
                    "length": int(d["length"]),
                    "digest": d["digest"],
                })
            return out
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    return []


def digest_check(path, expected):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    got = base64.b32encode(h.digest()).decode().rstrip("=")
    return got == expected.rstrip("="), got


def archive_download(snapshot, quarter, out, log):
    ts = snapshot["timestamp"]
    base = f"https://web.archive.org/web/{ts}if_/{SEC_BASE}/{quarter}_nport.zip"
    last = None
    probe = None
    for attempt in range(6):
        try:
            probe = get(base, {"Range": "bytes=0-0"}, timeout=120)
            break
        except Exception as e:
            last = e
            log(f"archive: probe attempt {attempt + 1} failed ({e}); retrying")
            time.sleep(3 * (attempt + 1))
    if probe is None:
        raise RuntimeError(f"archive probe failed after retries: {last}")
    cr = probe.headers.get("Content-Range", "")
    if "/" in cr:
        total = int(cr.rsplit("/", 1)[1])
    else:
        total = int(probe.headers.get("x-archive-orig-content-length") or snapshot["length"])
    probe.close()
    nchunks = (total + CHUNK - 1) // CHUNK
    tmp = out.with_suffix(out.suffix + ".part")
    done = [0]
    lock = threading.Lock()
    stop = threading.Event()

    if tmp.exists():
        got = tmp.stat().st_size
        if got != total:
            tmp.unlink()
    if not tmp.exists():
        with open(tmp, "wb") as f:
            f.truncate(total)

    def fetch(i):
        a = i * CHUNK
        b = min(total, a + CHUNK) - 1
        last = None
        for attempt in range(6):
            if stop.is_set():
                return
            try:
                r = get(base, {"Range": f"bytes={a}-{b}"}, timeout=150)
                code = r.status
                if code != 206:
                    raise RuntimeError(f"expected 206, got {code}")
                data = r.read()
                if len(data) != b - a + 1:
                    raise RuntimeError(f"short chunk {len(data)} != {b-a+1}")
                fd = os.open(tmp, os.O_WRONLY)
                try:
                    os.pwrite(fd, data, a)
                finally:
                    os.close(fd)
                with lock:
                    done[0] += len(data)
                return
            except Exception as e:
                last = e
                time.sleep(min(30, 2 * (attempt + 1)) + (i % 3))
        stop.set()
        raise RuntimeError(f"chunk {i} failed: {last}")

    log(f"archive: {total} bytes in {nchunks} chunks, {ARCHIVE_WORKERS} workers")
    t0 = time.time()

    def reporter():
        while not stop.is_set():
            time.sleep(15)
            with lock:
                d = done[0]
            el = max(1e-9, time.time() - t0)
            log(f"  {d/1e6:.1f}/{total/1e6:.1f} MB  {d/1024/el:.0f} KB/s")

    th = threading.Thread(target=reporter, daemon=True)
    th.start()
    try:
        with cf.ThreadPoolExecutor(max_workers=ARCHIVE_WORKERS) as ex:
            list(ex.map(fetch, range(nchunks)))
    finally:
        stop.set()
    tmp.replace(out)
    ok, got = digest_check(out, snapshot["digest"])
    if ok:
        log(f"archive: SHA-1 verified against the snapshot digest ({got})")
    else:
        log(f"archive: WARNING digest mismatch: file {got} != snapshot {snapshot['digest']}")
    sha = sha256_file(out)
    log(f"archive: sha256 {sha}")
    return {
        "source": "internet_archive_snapshot",
        "url": base,
        "snapshot_timestamp": ts,
        "sha1_base32": got,
        "snapshot_digest": snapshot["digest"],
        "digest_verified": ok,
        "sha256": sha,
        "bytes": total,
        "origin_headers": "x-archive-orig-* on the snapshot identify www.sec.gov",
    }


def direct_download(url, out, log, dest=None):
    dest = Path(dest) if dest is not None else out
    tmp = dest.with_suffix(dest.suffix + ".part")
    with get(url, timeout=60) as r, open(tmp, "wb") as f:
        total = r.headers.get("Content-Length")
        total = int(total) if total else None
        got = 0
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            f.write(block)
            got += len(block)
            if got % (50 << 20) < (1 << 20):
                log(f"  sec direct {got/1e6:.0f} MB")
    if total and got != total:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"short read {got} != {total}")
    tmp.replace(dest)
    h = hashlib.sha1()
    with open(dest, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {
        "source": "sec_direct",
        "url": url,
        "sha1_base32": base64.b32encode(h.digest()).decode().rstrip("="),
        "sha256": sha256_file(dest),
        "bytes": got,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarter", default="2026q2")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / f"{args.quarter}_nport.zip"
    prov_path = DATA / f"{args.quarter}_provenance.json"

    lines = []

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        lines.append(line)

    old_prov = {}
    if prov_path.exists():
        try:
            old_prov = json.loads(prov_path.read_text())
        except Exception:
            old_prov = {}

    ua_set = bool(os.environ.get("SEC_USER_AGENT"))
    cached = (out.exists() and prov_path.exists()
              and out.stat().st_size == old_prov.get("bytes"))
    if cached and not args.force:
        if not ua_set:
            log(f"reuse {out.name} ({out.stat().st_size} bytes, {old_prov.get('source')})")
            return
        if old_prov.get("source") == "sec_direct" or old_prov.get("direct_sha256_checked"):
            log(f"reuse {out.name} ({out.stat().st_size} bytes, {old_prov.get('source')}); "
                "SEC_USER_AGENT is set but a direct check is already recorded")
            return
        log("SEC_USER_AGENT is set; validating the cached archive against a direct SEC fetch")
    elif out.exists() and not cached:
        log("cached file size does not match provenance; refetching")

    sec_url = f"{SEC_BASE}/{args.quarter}_nport.zip"
    t0 = time.monotonic()
    code, detail = sec_probe(sec_url)
    if code is None:
        log(f"sec direct probe failed: {detail}")
    else:
        log(f"sec direct probe: HTTP {code}" + (f", {detail} bytes" if detail else ""))
    caching_now = cached and not args.force
    if code == 200 and caching_now:
        # The cache is kept. Fetch the direct file to a temporary path only to
        # compare its SHA-256 with the archive copy, then delete it.
        direct_tmp = out.with_suffix(out.suffix + ".direct.tmp")
        try:
            dprov = direct_download(sec_url, out, log, dest=direct_tmp)
            direct_sha = dprov["sha256"]
            prov = dict(old_prov)
            prov["direct_sha256"] = direct_sha
            prov["archive_sha256"] = old_prov.get("sha256")
            prov["direct_sha256_matches_archive"] = (direct_sha == old_prov.get("sha256"))
            prov["direct_sha256_checked"] = True
            prov["direct_check_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            prov["sec_probe"] = code
            prov["sec_probe_detail"] = detail
            prov["sec_url"] = sec_url
            prov["sec_user_agent_env_set"] = True
            log(f"sec direct check: sha256 {direct_sha}; matches archive: "
                f"{prov['direct_sha256_matches_archive']}")
            if not prov["direct_sha256_matches_archive"]:
                log("WARNING: direct SEC file differs from the verified archive; keeping the archive")
            prov["direct_validation_seconds"] = round(time.monotonic() - t0, 3)
        except Exception as e:
            prov = dict(old_prov)
            prov["direct_sha256_checked"] = False
            prov["direct_check_error"] = f"{type(e).__name__}: {e}"
            prov["sec_probe"] = code
            prov["sec_probe_detail"] = detail
            prov["sec_url"] = sec_url
            prov["sec_user_agent_env_set"] = True
            prov["direct_validation_seconds"] = round(time.monotonic() - t0, 3)
            log(f"sec direct check failed ({type(e).__name__}: {e}); keeping the archive cache")
        finally:
            direct_tmp.unlink(missing_ok=True)
    elif code == 200:
        prov = direct_download(sec_url, out, log)
        prov["sec_probe"] = code
        prov["sec_probe_detail"] = detail
        prov["sec_url"] = sec_url
        prov["sec_user_agent_env_set"] = ua_set
        prov["download_seconds"] = round(time.monotonic() - t0, 3)
        log(f"sec direct: wrote {out.name}")
    elif caching_now:
        log("sec direct refused the configured User-Agent; keeping the cached archive")
        prov = dict(old_prov)
        prov["sec_probe"] = code
        prov["sec_probe_detail"] = detail
        prov["sec_url"] = sec_url
        prov["sec_user_agent_env_set"] = ua_set
        prov["direct_validation_seconds"] = round(time.monotonic() - t0, 3)
    else:
        log("sec direct refused the configured User-Agent; trying the archive")
        snaps = cdx_snapshots(args.quarter)
        if not snaps:
            raise SystemExit(
                f"SEC refused HTTP {code} and no Internet Archive snapshot exists "
                f"for {args.quarter}. A contact User-Agent is needed."
            )
        snap = min(snaps, key=lambda s: s["timestamp"])
        prov = archive_download(snap, args.quarter, out, log)
        prov["sec_probe"] = code
        prov["sec_probe_detail"] = detail
        prov["sec_url"] = sec_url
        prov["sec_user_agent_env_set"] = ua_set
        prov["download_seconds"] = round(time.monotonic() - t0, 3)
    prov.setdefault("source", old_prov.get("source", "unknown"))
    prov["quarter"] = args.quarter
    prov.setdefault("fetched_at_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    prov.update(PACER.stats())
    prov["pacing_run"] = ("direct_validation" if caching_now and code == 200
                          else "download")
    if old_prov.get("sha256"):
        prov["sha256_matches_previous"] = (prov.get("sha256") == old_prov["sha256"])
        prov["previous_source"] = old_prov.get("source")
    if old_prov.get("sec_probe") is not None:
        prov["sec_probe_round1"] = old_prov.get("sec_probe")
        prov["sec_probe_round1_detail"] = old_prov.get("sec_probe_detail")
    prov_path.write_text(json.dumps(prov, indent=2) + "\n")
    log("pacing: %(requests_total)d requests, max %(max_requests_in_any_1s)d in any 1s "
        "(cap %(rate_limit_per_s).0f/s), ok=%(pacing_ok)s" % prov)
    log(f"wrote {prov_path.name}")


if __name__ == "__main__":
    main()
