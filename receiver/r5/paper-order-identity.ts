/** Canonical identity for a recorded model proposal's synthetic paper order. */
export function paperOrderIdForTask(taskId: string): string {
  return 'paper:' + taskId;
}

/** Bind a mandate-scoped paper commit to the same durable order identity. */
export function mandatePaperOrderIdempotencyKey(mandateId: string, orderId: string): string {
  return 'idem-' + mandateId + '-' + orderId;
}
