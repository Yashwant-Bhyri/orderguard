export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit";
export type OrderGuardClientOptions = {
  baseUrl?: string;
  token?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
};
export type ProposeOrderInput = {
  mandateId: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  orderType?: OrderType;
  limitPrice?: string | number;
  session?: "regular" | "premarket" | "afterhours" | "overnight" | "hk_regular";
  timeInForce?: "day" | "gtc";
};
export class OrderGuardError extends Error {
  status: number;
  payload: Record<string, unknown>;
}
export class OrderGuardUnavailable extends Error {
  outcomeUnknown: boolean;
}
/** One mandate as listed by `getMandate()`. The receiver may add fields. */
export type MandateRow = {
  mandateId: string;
  active: boolean;
  symbol?: string;
  side?: OrderSide;
  maxQuantityPerOrder?: number;
  allowedOrderTypes?: OrderType[];
  session?: string;
  timeInForce?: string;
  expiresAt?: number | string;
  [field: string]: unknown;
};
export type MandateStatus = { mandates: MandateRow[]; [field: string]: unknown };
/** A check the receiver ran on a preview, with its plain-language detail. */
export type Finding = { code: string; detail: string };
/**
 * Result of `proposeOrder`. A refusal has `state` "denied" (the receiver refused the order), "proposal_denied" (refused at preview, or the
 * typed order did not match what the receiver parsed) or "unknown" (no answer: check `orderStatus` before sending anything new), and always
 * carries a `reason`. Any other `state` is the receiver's order status, for example "filled", and comes with an `orderId`.
 */
export type ProposeOrderResult =
  | { state: string; orderId: string; symbol: string; side: OrderSide; quantity: number; executionMesh?: string; idempotentReplay: boolean }
  | { state: "denied"; statusCode: number; reason: string; findings?: unknown; venueDispatchAttempted: false; retryGuidance: { message: string; allowedShape?: Record<string, unknown> } | null }
  | { state: "proposal_denied"; reason: string; findings?: Finding[]; venueDispatchAttempted?: false }
  | { state: "unknown"; reason: string; venueDispatchAttempted?: "unknown"; guidance?: string };
export type OrderStatusResult = { orderId: string; status: string; symbol?: string; side?: OrderSide; quantity?: number; filledQuantity?: number; updatedAt?: string | number };
export class OrderGuardClient {
  constructor(options?: OrderGuardClientOptions);
  getMandate(): Promise<MandateStatus>;
  proposeOrder(input: ProposeOrderInput): Promise<ProposeOrderResult>;
  orderStatus(orderId: string): Promise<OrderStatusResult>;
  cancel(orderId: string): Promise<Record<string, unknown>>;
}
