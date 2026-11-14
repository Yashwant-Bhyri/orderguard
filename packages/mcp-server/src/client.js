const LOOPBACK_NAMES = new Set(["localhost", "127.0.0.1", "::1"]);

function isLoopback(hostname) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "").replace(/\.$/, "");
  if (LOOPBACK_NAMES.has(host)) return true;
  const v4 = host.split(".").map(Number);
  return v4.length === 4 && v4.every((n) => Number.isInteger(n) && n >= 0 && n <= 255) && v4[0] === 127;
}

function decimal(value, label) {
  if (typeof value !== "string" && typeof value !== "number") throw new TypeError(`${label} must be a positive decimal.`);
  const text = String(value).trim();
  if (!/^(?:0|[1-9]\d*)(?:\.\d+)?$/.test(text)) throw new TypeError(`${label} must be a positive decimal.`);
  const normalized = text.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
  if (/^0(?:\.0*)?$/.test(normalized)) throw new TypeError(`${label} must be a positive decimal.`);
  return { text, normalized };
}

export class OrderGuardError extends Error {
  constructor(status, payload = {}) {
    const reason = payload?.error ?? payload?.reason ?? "receiver_request_failed";
    super(`OrderGuard HTTP ${status}: ${String(reason)}`);
    this.name = "OrderGuardError";
    this.status = status;
    this.payload = payload;
  }
}

/**
 * The receiver could not be reached or did not answer in time. `outcomeUnknown` is true when the request may have been applied
 * (it was sent and no complete answer came back); check the order status before submitting anything new.
 */
export class OrderGuardUnavailable extends Error {
  constructor(cause, outcomeUnknown) {
    const kind = cause?.name === "TimeoutError" || cause?.name === "AbortError" ? "did not answer in time" : "could not be reached";
    super(`OrderGuard receiver ${kind}. ${outcomeUnknown
      ? "The request may or may not have been applied: check the order status before submitting a new order."
      : "Nothing was sent. Check that the receiver is running and ORDERGUARD_URL is correct, then try again."}`);
    this.name = "OrderGuardUnavailable";
    this.outcomeUnknown = outcomeUnknown;
  }
}

const MAX_RESPONSE_BYTES = 1_048_576;

/**
 * Agent-side convenience client. It carries no signing key and is not an
 * authorization boundary: every order is submitted to the mesh receiver.
 */
export class OrderGuardClient {
  constructor({ baseUrl, token, timeoutMs = 15_000, fetchImpl = globalThis.fetch } = {}) {
    const rawUrl = (baseUrl ?? process.env.ORDERGUARD_URL ?? "http://127.0.0.1:4173").replace(/\/$/, "");
    let parsed;
    try { parsed = new URL(rawUrl); } catch { throw new TypeError("OrderGuard URL is malformed."); }
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.search || parsed.hash) {
      throw new TypeError("OrderGuard URL must be HTTP(S) without credentials, query, or fragment.");
    }
    if (parsed.protocol === "http:" && !isLoopback(parsed.hostname)) throw new TypeError("HTTPS is required for non-loopback OrderGuard URLs.");
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new TypeError("OrderGuard timeout must be positive.");
    if (typeof fetchImpl !== "function") throw new TypeError("A Fetch-compatible implementation is required.");
    this.baseUrl = rawUrl;
    this.token = token ?? process.env.ORDERGUARD_BEARER_TOKEN;
    this.timeoutMs = timeoutMs;
    this.fetch = fetchImpl;
  }

  async request(method, path, body) {
    const url = new URL(path, `${this.baseUrl}/`);
    const headers = { accept: "application/json" };
    if (body !== undefined) headers["content-type"] = "application/json";
    if (isLoopback(url.hostname)) headers.origin = url.origin;
    if (this.token) headers.authorization = `Bearer ${this.token}`;
    let response;
    try {
      response = await this.fetch(url, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (error) {
      // A connection refused before sending is certain; anything else (timeout, reset) may have happened after the receiver acted.
      const refused = error?.cause?.code === "ECONNREFUSED" || error?.cause?.code === "ENOTFOUND";
      throw new OrderGuardUnavailable(error, method !== "GET" && !refused);
    }
    let payload;
    try {
      const text = await response.text();
      if (text.length > MAX_RESPONSE_BYTES) throw new Error("too large");
      payload = JSON.parse(text);
    } catch { payload = { error: "receiver returned an invalid or oversized reply" }; }
    if (!response.ok) throw new OrderGuardError(response.status, payload);
    return payload && typeof payload === "object" ? payload : { value: payload };
  }

  getMandate() {
    return this.request("GET", "/api/human-mandate/status");
  }

  async proposeOrder({ mandateId, symbol, side, quantity, orderType = "market", limitPrice, session = "regular", timeInForce = "day" }) {
    if (typeof mandateId !== "string" || !mandateId.trim()) throw new TypeError("mandateId is required.");
    if (typeof symbol !== "string" || !/^[A-Za-z0-9._-]{1,24}$/.test(symbol.trim())) throw new TypeError("symbol is invalid.");
    const normalizedSymbol = symbol.trim().toUpperCase();
    if (!["buy", "sell"].includes(side)) throw new TypeError("side must be buy or sell.");
    if (!Number.isSafeInteger(quantity) || quantity <= 0) throw new TypeError("quantity must be a positive integer.");
    if (!["market", "limit"].includes(orderType)) throw new TypeError("orderType must be market or limit.");
    if (orderType === "limit" && limitPrice === undefined) throw new TypeError("limitPrice is required for limit orders.");
    if (orderType === "market" && limitPrice !== undefined) throw new TypeError("market orders must not include limitPrice.");
    const price = limitPrice === undefined ? undefined : decimal(limitPrice, "limitPrice");
    const sessions = {
      regular: "regular market hours",
      premarket: "pre-market trading",
      afterhours: "after-hours trading",
      overnight: "overnight trading",
      hk_regular: "HK regular hours",
    };
    if (!Object.hasOwn(sessions, session)) throw new TypeError("session is invalid.");
    const isHongKong = normalizedSymbol.endsWith(".HK");
    if ((isHongKong && session !== "hk_regular") || (!isHongKong && session === "hk_regular")) throw new TypeError("session must match the symbol market.");
    if (!["day", "gtc"].includes(timeInForce)) throw new TypeError("timeInForce must be day or gtc.");
    const currency = isHongKong ? "HKD" : "USD";
    const pricePhrase = orderType === "limit" ? ` limit at ${price.text} ${currency}` : " market order";
    const prompt = `${side[0].toUpperCase()}${side.slice(1)} ${quantity} ${normalizedSymbol}${pricePhrase} during ${sessions[session]}, ${timeInForce}.`;
    const preview = await this.request("POST", "/api/chat", { prompt, provider: "local", verifier: "none" });
    const run = preview?.run;
    const confirmation = preview?.paperConfirmation;
    const intent = run?.intent;
    const matches = intent
      && intent.symbol === normalizedSymbol
      && intent.side === side
      && intent.quantity === quantity
      && intent.market === (isHongKong ? "HK" : "US")
      && intent.orderType === orderType
      && intent.session === session
      && intent.timeInForce === timeInForce
      && (price === undefined ? intent.limitPrice == null : decimal(intent.limitPrice, "receiver limitPrice").normalized === price.normalized);
    if (run?.outcome !== "ready" || !matches) return { state: "proposal_denied", reason: "typed_proposal_did_not_match_receiver_intent" };
    if (![run.id, confirmation?.token, confirmation?.intentHash].every((value) => typeof value === "string" && value)) {
      return { state: "proposal_denied", reason: "required_receiver_capability_missing" };
    }
    try {
      const result = await this.request("POST", "/api/paper-orders", {
        runId: run.id,
        mandateId,
        previewToken: confirmation.token,
        intentHash: confirmation.intentHash,
      });
      const order = result.order;
      if (!order || typeof order !== "object") return { state: "unknown", reason: "receiver_response_missing_order" };
      return {
        state: order.status ?? "accepted",
        orderId: order.id,
        symbol: normalizedSymbol,
        side,
        quantity,
        executionMesh: result.executionMesh,
        idempotentReplay: result.idempotentReplay === true,
      };
    } catch (error) {
      if (error instanceof OrderGuardUnavailable && error.outcomeUnknown) {
        // Do NOT build a new proposal: a fresh preview would be a new order. Report that the first one is unresolved.
        return {
          state: "unknown",
          reason: "receiver_did_not_answer",
          venueDispatchAttempted: "unknown",
          guidance: "The order may have been placed. Call order_status or inspect the receiver snapshot before proposing again; do not repeat the order until it is resolved.",
        };
      }
      if (!(error instanceof OrderGuardError)) throw error;
      return {
        state: "denied",
        statusCode: error.status,
        reason: error.payload?.error ?? error.payload?.reason ?? "receiver_denied",
        findings: error.payload?.findings,
        venueDispatchAttempted: false,
        retryGuidance: await this.retryGuidance(mandateId),
      };
    }
  }

  async retryGuidance(mandateId) {
    try {
      const status = await this.getMandate();
      const active = Array.isArray(status.mandates) ? status.mandates.find((row) => row?.mandateId === mandateId && row.active === true) : undefined;
      if (!active) return { message: "No active human-signed mandate is available. Ask the owner to sign or renew one." };
      return {
        message: "Retry only if the original user request still authorizes an action within these fields. The receiver will check the new proposal again.",
        allowedShape: {
          symbol: active.symbol,
          side: active.side,
          maxQuantityPerOrder: active.maxQuantityPerOrder,
          allowedOrderTypes: active.allowedOrderTypes,
          session: active.session,
          timeInForce: active.timeInForce,
          expiresAt: active.expiresAt,
          active: active.active,
        },
      };
    } catch { return null; }
  }

  async orderStatus(orderId) {
    const snapshot = await this.request("GET", "/api/snapshot");
    const order = Array.isArray(snapshot.orders) ? snapshot.orders.find((row) => row?.id === orderId) : undefined;
    if (!order) return { orderId, status: "not_found" };
    const execution = order.executionOrder ?? {};
    return {
      orderId: order.id,
      status: order.status,
      symbol: execution.symbol,
      side: execution.side,
      quantity: execution.quantity,
      filledQuantity: order.filledQuantity,
      updatedAt: order.updatedAt,
    };
  }

  async cancel(orderId) {
    if (typeof orderId !== "string" || !orderId) throw new TypeError("orderId is required.");
    const path = `/api/paper-orders/${encodeURIComponent(orderId)}/cancel/options`;
    const challenge = await this.request("POST", path, {});
    return {
      state: "human_step_up_required",
      orderId,
      order: challenge.order,
      challengeId: challenge.challengeId,
      approvalRoute: `/api/paper-orders/${encodeURIComponent(orderId)}/cancel`,
      message: "The owner must review and sign this cancellation on the trusted device. The agent cannot complete it.",
    };
  }
}
