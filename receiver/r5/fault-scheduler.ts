export const B4_FAULT_SITES = [
  'worker.request.before',
  'worker.response.after',
  'ledger.before_commit',
  'ledger.after_commit_before_reply',
  'mandate.approval.before_commit',
] as const;

export type B4FaultSite = (typeof B4_FAULT_SITES)[number];
export type B4FaultAction = 'drop' | 'duplicate' | 'delay' | 'crash' | 'revoke';

export interface B4FaultEvent {
  id: string;
  site: B4FaultSite;
  occurrence: number;
  action: B4FaultAction;
  delayTicks?: number;
}

export interface B4FaultScheduleV1 {
  schemaVersion: 1;
  seed: number;
  events: B4FaultEvent[];
}

export interface B4FaultObservation {
  site: B4FaultSite;
  occurrence: number;
  eventId?: string;
  action?: B4FaultAction;
  applied?: boolean;
  detail?: string;
  evidence?: Record<string, string | number | boolean>;
}

export interface B4FaultScheduleReport {
  schedule: B4FaultScheduleV1;
  siteHitCounts: Record<B4FaultSite, number>;
  observations: B4FaultObservation[];
  unappliedEventIds: string[];
}

const ACTION_ORDER: readonly B4FaultAction[] = ['drop', 'duplicate', 'delay', 'crash', 'revoke'];

function assertSchedule(schedule: B4FaultScheduleV1): void {
  if (!schedule || schedule.schemaVersion !== 1 || !Number.isSafeInteger(schedule.seed)
    || schedule.seed < 0 || schedule.seed > 0xffff_ffff || !Array.isArray(schedule.events)
    || schedule.events.length > 16) {
    throw new Error('B4 fault schedule must be a bounded version-1 schedule with an unsigned 32-bit seed.');
  }
  const seen = new Set<string>();
  for (const event of schedule.events) {
    if (!event || typeof event.id !== 'string' || !/^[A-Za-z0-9._:-]{1,96}$/.test(event.id)
      || !B4_FAULT_SITES.includes(event.site) || !Number.isSafeInteger(event.occurrence) || event.occurrence < 1
      || !ACTION_ORDER.includes(event.action)) {
      throw new Error('B4 fault schedule contains an invalid site, occurrence, ID, or action.');
    }
    if (event.action === 'delay') {
      if (!Number.isSafeInteger(event.delayTicks) || event.delayTicks! < 1 || event.delayTicks! > 32) {
        throw new Error('B4 logical delay must be between 1 and 32 ticks.');
      }
    } else if (event.delayTicks !== undefined) {
      throw new Error('Only a delay fault may carry delayTicks.');
    }
    const key = event.site + ':' + event.occurrence;
    if (seen.has(key)) throw new Error('B4 schedule cannot assign two faults to the same named-site occurrence.');
    seen.add(key);
    if (event.action === 'revoke' && event.site !== 'mandate.approval.before_commit') {
      throw new Error('B4 revocation must be scheduled after approval and before the ledger commit.');
    }
    if (event.action === 'duplicate' && event.site !== 'ledger.before_commit') {
      throw new Error('B4 duplicate delivery must target the idempotent ledger commit boundary.');
    }
    if (event.action === 'crash' && event.site !== 'ledger.after_commit_before_reply') {
      throw new Error('B4 crash recovery must target the ledger commit/reply gap.');
    }
  }
}

function xorshift32(initial: number): () => number {
  let state = initial >>> 0;
  if (state === 0) state = 0x6d2b79f5;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return state >>> 0;
  };
}

/** A stratified, replayable seed schedule: every five consecutive seeds cover all five fault actions. */
export function createSeededB4FaultSchedule(seed: number): B4FaultScheduleV1 {
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > 0xffff_ffff) {
    throw new Error('B4 seed must be an unsigned 32-bit integer.');
  }
  const next = xorshift32(seed);
  const action = ACTION_ORDER[seed % ACTION_ORDER.length]!;
  const occurrence = 1 + (next() % 4);
  const event: B4FaultEvent = action === 'drop'
    ? { id: 'seed-' + seed + '-drop', site: 'worker.request.before', occurrence, action }
    : action === 'duplicate'
      ? { id: 'seed-' + seed + '-duplicate', site: 'ledger.before_commit', occurrence: 1, action }
      : action === 'delay'
        ? { id: 'seed-' + seed + '-delay', site: 'worker.request.before', occurrence, action, delayTicks: 1 + (next() % 3) }
        : action === 'crash'
          ? { id: 'seed-' + seed + '-crash', site: 'ledger.after_commit_before_reply', occurrence: 1, action }
          : { id: 'seed-' + seed + '-revoke', site: 'mandate.approval.before_commit', occurrence: 1, action };
  const schedule: B4FaultScheduleV1 = { schemaVersion: 1, seed, events: [event] };
  assertSchedule(schedule);
  return schedule;
}

export class B4FaultScheduler {
  readonly schedule: B4FaultScheduleV1;
  private readonly hits = new Map<B4FaultSite, number>();
  private readonly observations: B4FaultObservation[] = [];
  private readonly applied = new Set<string>();

  constructor(schedule: B4FaultScheduleV1) {
    assertSchedule(schedule);
    this.schedule = structuredClone(schedule);
  }

  visit(site: B4FaultSite): B4FaultEvent | null {
    const occurrence = (this.hits.get(site) ?? 0) + 1;
    this.hits.set(site, occurrence);
    const event = this.schedule.events.find((item) => item.site === site && item.occurrence === occurrence && !this.applied.has(item.id));
    this.observations.push({ site, occurrence, ...(event ? { eventId: event.id, action: event.action } : {}) });
    return event ?? null;
  }

  markApplied(event: B4FaultEvent, detail: string, evidence?: Record<string, string | number | boolean>): void {
    if (!this.schedule.events.some((item) => item.id === event.id)) throw new Error('Cannot apply a fault outside the realized schedule.');
    if (this.applied.has(event.id)) throw new Error('A scheduled fault can be applied only once.');
    this.applied.add(event.id);
    const observation = [...this.observations].reverse().find((item) => item.eventId === event.id);
    if (observation) {
      observation.applied = true;
      observation.detail = detail;
      if (evidence) observation.evidence = { ...evidence };
    }
  }

  recordEvidence(eventId: string, evidence: Record<string, string | number | boolean>): void {
    const observation = [...this.observations].reverse().find((item) => item.eventId === eventId);
    if (!observation?.applied) throw new Error('Additional evidence requires an observed, applied fault event.');
    observation.evidence = { ...(observation.evidence ?? {}), ...evidence };
  }

  report(): B4FaultScheduleReport {
    const siteHitCounts = Object.fromEntries(B4_FAULT_SITES.map((site) => [site, this.hits.get(site) ?? 0])) as Record<B4FaultSite, number>;
    return {
      schedule: structuredClone(this.schedule),
      siteHitCounts,
      observations: structuredClone(this.observations),
      unappliedEventIds: this.schedule.events.filter((event) => !this.applied.has(event.id)).map((event) => event.id),
    };
  }
}

export async function applyLogicalDelay(ticks: number): Promise<void> {
  if (!Number.isSafeInteger(ticks) || ticks < 1 || ticks > 32) throw new Error('Logical delay tick count is out of range.');
  for (let tick = 0; tick < ticks; tick += 1) await Promise.resolve();
}
