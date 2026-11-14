// Request reading and error mapping for the receiver bridge. Kept free of ports and globals so it can be tested directly.
import { homedir } from "node:os";

export class HttpError extends Error {
  constructor(status, code, detail) { super(detail); this.name = "HttpError"; this.status = status; this.code = code; }
}

/** Remove the home directory and anything that looks like a bearer token or key assignment from text meant for a log or a client. */
export function scrub(text) {
  let out = String(text ?? "");
  const home = homedir();
  if (home && home.length > 1) out = out.split(home).join("~");
  out = out.replace(/\/(?:Users|home)\/[^\s/'"]+/g, "~");
  out = out.replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer ***");
  out = out.replace(/\b((?:api[_-]?key|secret|token|password)\s*[=:]\s*)[^\s,;'"]+/gi, "$1***");
  return out;
}

/**
 * Read one JSON object from a request. Refuses (never truncates) anything over `limit` bytes, a body that is not a JSON
 * object, and a client that stalls longer than `timeoutMs`. An empty body is an empty object.
 */
export function readJsonBody(req, { limit = 65536, timeoutMs = 10_000 } = {}) {
  return new Promise((ok, bad) => {
    const declared = Number(req.headers?.["content-length"]);
    if (Number.isFinite(declared) && declared > limit) {
      return bad(new HttpError(413, "body_too_large", `The request body is larger than ${limit} bytes. Send only the order fields.`));
    }
    const chunks = [];
    let size = 0;
    let settled = false;
    const settle = (fn, value) => { if (settled) return; settled = true; clearTimeout(timer); fn(value); };
    const timer = setTimeout(() => settle(bad, new HttpError(408, "request_timeout", "The request body did not arrive in time. Retry; the order was not recorded.")), timeoutMs);
    timer.unref?.();
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) settle(bad, new HttpError(413, "body_too_large", `The request body is larger than ${limit} bytes. Send only the order fields.`));
      else if (!settled) chunks.push(chunk);
    });
    req.on("end", () => {
      if (!chunks.length) return settle(ok, {});
      let value;
      try { value = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
      catch { return settle(bad, new HttpError(400, "invalid_json", "The request body is not valid JSON.")); }
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return settle(bad, new HttpError(400, "invalid_body", "The request body must be a JSON object."));
      }
      settle(ok, value);
    });
    req.on("error", () => settle(bad, new HttpError(400, "request_aborted", "The connection dropped before the request was complete. Retry; the order was not recorded.")));
    req.on("aborted", () => settle(bad, new HttpError(400, "request_aborted", "The connection dropped before the request was complete. Retry; the order was not recorded.")));
  });
}

const INTERNAL = { error: "internal_error", detail: "The receiver hit an internal error. Nothing is lost: retry with the same clientOrderId and it is applied at most once." };

/** Map a thrown value to [status, body]. Unexpected errors are 500 with no internal detail; the detail goes to the log only. */
export function failure(error, { domainStatus = 500 } = {}) {
  if (error instanceof HttpError) return [error.status, { error: error.code, detail: error.message }];
  const internal = error?.name === "LedgerError" || error?.name === "LedgerFileError" || error?.code === "ERR_SQLITE_ERROR" || !(error instanceof Error);
  if (domainStatus !== 500 && !internal) return [domainStatus, { error: scrub(error.message).slice(0, 200) }];
  return [500, INTERNAL];
}
