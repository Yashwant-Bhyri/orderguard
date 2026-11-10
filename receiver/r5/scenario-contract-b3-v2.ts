import { createHash } from 'node:crypto';
import { createScenarioMandateV1, type ScenarioMandateV1 } from './scenario-contract.js';

export type B3ModelConditionV2 = 'control' | 'attack';
export type B3ModelFamilyV2 = 'poisoned-news' | 'direct-override' | 'compromised-client';
export type B3RequestedModelV2 = 'openai/gpt-6-luna' | 'deepseek/deepseek-v4.1-flash-1017' | 'z-ai/glm-5.3-flash' | 'no-model-call';

export interface B3ScenarioClockV2 {
  now_ms: number;
  session_close_ms: number;
  market_data_at_ms: number;
}

export interface B3CardReferenceV2 {
  card_id: string;
  card_version: string;
  sha256: string;
}

export interface B3ModelMetadataV2 {
  provider: 'openai' | 'openrouter' | 'none';
  requested_model: B3RequestedModelV2;
  returned_model: string;
  model_version: string;
  seed: number;
  prompt_sha256: string | null;
  tool_schema_sha256: string | null;
  response_id: string | null;
  call_id: string | null;
}

export interface B3OrderArgsV2 {
  market: 'US' | 'HK';
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  orderType: 'market' | 'limit';
  limitPrice: { amount_minor: number; currency: 'HKD' } | null;
  session: 'regular' | 'premarket' | 'afterhours' | 'overnight' | 'hk_regular';
  timeInForce: 'day' | 'gtc';
  rationale?: string;
}

export type B3ElicitationV2 =
  | { kind: 'tool_call'; tool_name: 'draft_paper_order'; tool_args: B3OrderArgsV2 }
  | { kind: 'no_tool_call'; rationale: string };

export interface B3ModelRunRequestV2 {
  schema_version: '2.0.0';
  cell_id: string;
  run_id: string;
  seed: number;
  scenario_clock: B3ScenarioClockV2;
  card_ref: B3CardReferenceV2;
  mandate: ScenarioMandateV1;
  model_metadata: B3ModelMetadataV2;
  condition: B3ModelConditionV2;
  elicitation: B3ElicitationV2;
}

export interface B3ContextDeliveryV2 {
  schema_version: '2.0.0';
  family: B3ModelFamilyV2;
  condition: B3ModelConditionV2;
  research_note_delivered: boolean;
  attack_instruction_delivered: boolean;
  untrusted_context_present: boolean;
  direct_user_input_delivered: boolean;
  compromised_client_origin: boolean;
}

const orderArgKeys = ['market', 'symbol', 'side', 'quantity', 'orderType', 'limitPrice', 'session', 'timeInForce'];
const cardByFamily: Record<B3ModelFamilyV2, string> = {
  'poisoned-news': 'OG-PN-001',
  'direct-override': 'OG-DO-001',
  'compromised-client': 'OG-CC-001',
};
const familyByCard: Record<string, B3ModelFamilyV2> = {
  'OG-PN-001': 'poisoned-news',
  'OG-PN-009': 'poisoned-news',
  'OG-DO-001': 'direct-override',
  'OG-CC-001': 'compromised-client',
};
const modelBackedModels: ReadonlySet<string> = new Set([
  'openai/gpt-6-luna',
  'deepseek/deepseek-v4.1-flash-1017',
  'z-ai/glm-5.3-flash',
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    throw new Error(`${label} has missing or unsupported fields.`);
  }
}

function boundedString(value: unknown, label: string, min: number, max: number): asserts value is string {
  if (typeof value !== 'string' || value.length < min || value.length > max) {
    throw new Error(`${label} must be ${min}-${max} characters.`);
  }
}

function boundedInteger(value: unknown, label: string, min: number, max: number): asserts value is number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < min || value > max) {
    throw new Error(`${label} must be an integer in [${min}, ${max}].`);
  }
}

function validateOrderArgs(value: unknown): asserts value is B3OrderArgsV2 {
  if (!isRecord(value)) throw new Error('Typed order arguments must be an object.');
  const actualKeys = Object.keys(value).sort();
  const expectedKeys = [orderArgKeys, [...orderArgKeys, 'rationale']].map((keys) => [...keys].sort());
  if (!expectedKeys.some((keys) => keys.length === actualKeys.length
    && keys.every((key, index) => key === actualKeys[index]))) {
    throw new Error('Typed order arguments have missing or unsupported fields.');
  }
  if (value.market !== 'HK' && value.market !== 'US') throw new Error('Typed order market is unsupported.');
  if (typeof value.symbol !== 'string' || !['VLTA', 'ACMX', 'BRSK', 'HLQ', 'SYNTH3'].includes(value.symbol)) {
    throw new Error('Typed order symbol is outside the synthetic schema allow-list.');
  }
  if (value.side !== 'buy' && value.side !== 'sell') throw new Error('Typed order side is unsupported.');
  boundedInteger(value.quantity, 'Typed order quantity', 1, 10_000);
  if (value.orderType !== 'market' && value.orderType !== 'limit') throw new Error('Typed order type is unsupported.');
  if (value.orderType === 'market') {
    if (value.limitPrice !== null) throw new Error('A market order must use limitPrice=null.');
  } else {
    if (!isRecord(value.limitPrice)) throw new Error('A limit order requires a minor-unit limit price.');
    exactKeys(value.limitPrice, ['amount_minor', 'currency'], 'Typed limit price');
    boundedInteger(value.limitPrice.amount_minor, 'Limit price amount_minor', 1, 1_000_000_000_000);
    if (value.limitPrice.currency !== 'HKD') throw new Error('Synthetic v2 limit prices must use HKD minor units.');
  }
  if (!['regular', 'premarket', 'afterhours', 'overnight', 'hk_regular'].includes(String(value.session))) {
    throw new Error('Typed order session is unsupported.');
  }
  if (value.timeInForce !== 'day' && value.timeInForce !== 'gtc') throw new Error('Typed order timeInForce is unsupported.');
  if (Object.hasOwn(value, 'rationale')) boundedString(value.rationale, 'Typed order rationale', 1, 2_000);
}

function validateModelMetadata(value: unknown, seed: number, cardId: string): asserts value is B3ModelMetadataV2 {
  if (!isRecord(value)) throw new Error('Model metadata must be an object.');
  exactKeys(value, ['provider', 'requested_model', 'returned_model', 'model_version', 'seed', 'prompt_sha256', 'tool_schema_sha256', 'response_id', 'call_id'], 'Model metadata');
  if (value.seed !== seed) throw new Error('Model metadata seed must equal the scenario seed.');
  boundedString(value.returned_model, 'Returned model', 1, 128);
  boundedString(value.model_version, 'Model version', 1, 128);
  for (const key of ['response_id', 'call_id'] as const) {
    if (value[key] !== null && (typeof value[key] !== 'string' || value[key].length < 1 || value[key].length > 256)) {
      throw new Error(`Model metadata ${key} must be null or bounded text.`);
    }
  }
  if (cardId === 'OG-CC-001') {
    if (value.provider !== 'none' || value.requested_model !== 'no-model-call' || value.returned_model !== 'no-model-call'
      || value.prompt_sha256 !== null || value.tool_schema_sha256 !== null || value.response_id !== null || value.call_id !== null) {
      throw new Error('OG-CC-001 is scripted and requires provider=none with no model call metadata.');
    }
    return;
  }
  const isOpenRouterModel = value.provider === 'openrouter'
    && typeof value.requested_model === 'string'
    && modelBackedModels.has(value.requested_model);
  const isDirectOpenAILuna = value.provider === 'openai' && value.requested_model === 'openai/gpt-6-luna';
  if (!isOpenRouterModel && !isDirectOpenAILuna) {
    throw new Error('Model-backed B3 provider/model pair is not preregistered.');
  }
  const returned = value.returned_model as string;
  if (!(returned === value.requested_model || returned.startsWith(`${value.requested_model}-`))) {
    throw new Error('Returned model does not match the preregistered requested model.');
  }
  for (const key of ['prompt_sha256', 'tool_schema_sha256'] as const) {
    if (typeof value[key] !== 'string' || !/^[a-f0-9]{64}$/.test(value[key] as string)) {
      throw new Error(`Model metadata ${key} must be a lowercase SHA-256 digest.`);
    }
  }
}

export function validateB3ModelRunRequestV2(value: unknown): asserts value is B3ModelRunRequestV2 {
  if (!isRecord(value)) throw new Error('B3 v2 request must be an object.');
  exactKeys(value, ['schema_version', 'cell_id', 'run_id', 'seed', 'scenario_clock', 'card_ref', 'mandate', 'model_metadata', 'condition', 'elicitation'], 'B3 v2 request');
  if (value.schema_version !== '2.0.0') throw new Error('Unsupported B3 model-run contract version.');
  boundedString(value.cell_id, 'B3 cell ID', 1, 160);
  if (!/^[A-Za-z0-9][A-Za-z0-9/._:-]{0,159}$/.test(value.cell_id)) throw new Error('B3 cell ID contains unsupported characters.');
  boundedString(value.run_id, 'Run ID', 1, 96);
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value.run_id)) throw new Error('Run ID contains unsupported characters.');
  boundedInteger(value.seed, 'Scenario seed', 1, 30);
  if (value.condition !== 'control' && value.condition !== 'attack') throw new Error('Condition must be control or attack.');

  if (!isRecord(value.scenario_clock)) throw new Error('Scenario clock must be an object.');
  exactKeys(value.scenario_clock, ['now_ms', 'session_close_ms', 'market_data_at_ms'], 'Scenario clock');
  boundedInteger(value.scenario_clock.now_ms, 'Scenario clock now_ms', 0, 8_640_000_000_000_000);
  boundedInteger(value.scenario_clock.session_close_ms, 'Scenario clock session_close_ms', 1, 8_640_000_000_000_000);
  boundedInteger(value.scenario_clock.market_data_at_ms, 'Scenario clock market_data_at_ms', 0, 8_640_000_000_000_000);
  if (value.scenario_clock.now_ms >= value.scenario_clock.session_close_ms
    || value.scenario_clock.market_data_at_ms !== value.scenario_clock.now_ms) {
    throw new Error('B3 v2 clock must be pre-close with market data timestamp equal to now_ms.');
  }

  if (!isRecord(value.card_ref)) throw new Error('Card reference must be an object.');
  exactKeys(value.card_ref, ['card_id', 'card_version', 'sha256'], 'Card reference');
  boundedString(value.card_ref.card_id, 'Card ID', 3, 64);
  boundedString(value.card_ref.card_version, 'Card version', 5, 32);
  if (!/^[A-Z0-9][A-Z0-9-]{2,63}$/.test(value.card_ref.card_id)
    || !/^\d+\.\d+\.\d+$/.test(value.card_ref.card_version)
    || typeof value.card_ref.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.card_ref.sha256)) {
    throw new Error('Card reference requires a stable ID, semantic version, and lowercase SHA-256 digest.');
  }
  if (!Object.hasOwn(familyByCard, value.card_ref.card_id)) throw new Error('B3 v2 accepts only the three preregistered M1 cards.');

  if (!isRecord(value.mandate)) throw new Error('Mandate must be an object.');
  const expiry = new Date(value.scenario_clock.session_close_ms as number).toISOString();
  const canonicalMandate = createScenarioMandateV1(['VLTA', 'ACMX', 'BRSK'], expiry);
  if (stableJson(value.mandate) !== stableJson(canonicalMandate)) throw new Error('B3 v2 requires the exact canonical MANDATE-M1 v1.0.0 object.');

  validateModelMetadata(value.model_metadata, value.seed as number, value.card_ref.card_id as string);
  const metadata = value.model_metadata as B3ModelMetadataV2;
  const cardReference = value.card_ref as unknown as B3CardReferenceV2;
  const expectedCellId = b3CellIdV2(metadata.requested_model, cardReference.card_id, value.seed as number, value.condition as B3ModelConditionV2);
  if (value.cell_id !== expectedCellId) throw new Error('B3 cell ID does not match the requested model, card, seed, and condition.');

  if (!isRecord(value.elicitation)) throw new Error('Elicitation result must be an object.');
  if (value.elicitation.kind === 'tool_call') {
    exactKeys(value.elicitation, ['kind', 'tool_name', 'tool_args'], 'Tool-call elicitation');
    if (value.elicitation.tool_name !== 'draft_paper_order') throw new Error('Only draft_paper_order is supported by B3 v2.');
    validateOrderArgs(value.elicitation.tool_args);
  } else if (value.elicitation.kind === 'no_tool_call') {
    if (value.card_ref.card_id === 'OG-CC-001') {
      throw new Error('OG-CC-001 is a fixed scripted pair and cannot produce no_tool_call.');
    }
    exactKeys(value.elicitation, ['kind', 'rationale'], 'No-tool-call elicitation');
    boundedString(value.elicitation.rationale, 'No-tool-call rationale', 1, 1_000);
  } else {
    throw new Error('Elicitation kind must be tool_call or no_tool_call.');
  }
}

export function deriveB3ContextDeliveryV2(family: B3ModelFamilyV2, condition: B3ModelConditionV2): B3ContextDeliveryV2 {
  if (family === 'poisoned-news') {
    return {
      schema_version: '2.0.0', family, condition,
      research_note_delivered: true,
      attack_instruction_delivered: condition === 'attack',
      untrusted_context_present: true,
      direct_user_input_delivered: false,
      compromised_client_origin: false,
    };
  }
  if (family === 'direct-override') {
    return {
      schema_version: '2.0.0', family, condition,
      research_note_delivered: false,
      attack_instruction_delivered: false,
      untrusted_context_present: false,
      direct_user_input_delivered: true,
      compromised_client_origin: false,
    };
  }
  return {
    schema_version: '2.0.0', family, condition,
    research_note_delivered: false,
    attack_instruction_delivered: false,
    untrusted_context_present: false,
    direct_user_input_delivered: false,
    compromised_client_origin: true,
  };
}

export function b3FamilyForCardV2(cardId: string): B3ModelFamilyV2 | null {
  return familyByCard[cardId] ?? null;
}

export function b3CellIdV2(model: B3RequestedModelV2, cardId: string, seed: number, condition: B3ModelConditionV2): string {
  return `${model}:${cardId}:seed-${seed}:${condition}`;
}

export function b3ModelRequestDigestV2(request: B3ModelRunRequestV2): string {
  return createHash('sha256').update(stableJson(request), 'utf8').digest('hex');
}

export function b3ProposalDigestV2(args: B3OrderArgsV2): string {
  // Match the mesh receiver's existing recorded-proposal digest, preserving
  // the submitted JSON field order and values byte-for-byte.
  return createHash('sha256').update(JSON.stringify(args), 'utf8').digest('hex');
}

export function b3StableJsonV2(value: unknown): string {
  return stableJson(value);
}

export function b3CardFamilyMapV2(): Readonly<Record<B3ModelFamilyV2, string>> {
  return cardByFamily;
}
