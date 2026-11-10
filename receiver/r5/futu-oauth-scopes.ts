export const FUTU_QUOTE_READ_SCOPE = 'quote:read';

export class OAuthGenerationFence {
  #generation = 0;

  begin(): number {
    this.#generation += 1;
    return this.#generation;
  }

  current(): number {
    return this.#generation;
  }

  isCurrent(generation: number): boolean {
    return generation === this.#generation;
  }

  invalidate(): number {
    this.#generation += 1;
    return this.#generation;
  }
}

export function exactQuoteReadScopes(scopeValue: unknown, previouslyValidated?: readonly string[]): string[] | null {
  const scopes = typeof scopeValue === 'string'
    ? scopeValue.split(/\s+/).filter(Boolean)
    : previouslyValidated ? [...previouslyValidated] : [];
  return scopes.length === 1 && scopes[0] === FUTU_QUOTE_READ_SCOPE ? scopes : null;
}

export function exactQuoteReadRefreshScopes(input: {
  scopeProvided: boolean;
  scopeMalformed: boolean;
  scopeValue: unknown;
  previouslyValidated: readonly string[];
}): string[] | null {
  if (input.scopeMalformed) return null;
  if (!input.scopeProvided) return exactQuoteReadScopes(undefined, input.previouslyValidated);
  return typeof input.scopeValue === 'string' ? exactQuoteReadScopes(input.scopeValue) : null;
}
