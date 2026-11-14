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
export class OrderGuardClient {
  constructor(options?: OrderGuardClientOptions);
  getMandate(): Promise<Record<string, unknown>>;
  proposeOrder(input: ProposeOrderInput): Promise<Record<string, unknown>>;
  orderStatus(orderId: string): Promise<Record<string, unknown>>;
  cancel(orderId: string): Promise<Record<string, unknown>>;
}
