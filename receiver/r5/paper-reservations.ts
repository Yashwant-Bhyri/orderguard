export interface PendingPaperReservation {
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  reservedUsd: number;
}

export class PendingPaperReservationBook {
  #reservations = new Map<string, PendingPaperReservation>();

  hold(runId: string, reservation: PendingPaperReservation): void {
    if (!runId || !reservation.symbol || !Number.isInteger(reservation.quantity) || reservation.quantity <= 0
      || !Number.isFinite(reservation.reservedUsd) || reservation.reservedUsd < 0) {
      throw new Error('Pending paper reservation failed its typed capacity checks.');
    }
    this.#reservations.set(runId, Object.freeze({ ...reservation }));
  }

  release(runId: string): void {
    this.#reservations.delete(runId);
  }

  has(runId: string): boolean {
    return this.#reservations.has(runId);
  }

  reservedBuyUsd(symbol?: string, excludeRunId?: string): number {
    return [...this.#reservations.entries()].reduce((total, [runId, reservation]) =>
      runId !== excludeRunId && reservation.side === 'buy' && (!symbol || reservation.symbol === symbol)
        ? total + reservation.reservedUsd : total, 0);
  }

  reservedSellQuantity(symbol: string, excludeRunId?: string): number {
    return [...this.#reservations.entries()].reduce((total, [runId, reservation]) =>
      runId !== excludeRunId && reservation.side === 'sell' && reservation.symbol === symbol
        ? total + reservation.quantity : total, 0);
  }
}
