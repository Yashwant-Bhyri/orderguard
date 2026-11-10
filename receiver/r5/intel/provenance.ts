/** Fast, deterministic triage of manipulation signals in untrusted trigger text.
 *
 * This is a reviewer hint, not evidence verification or an authorization result.
 * A clear score never grants an order; the signed mandate remains authoritative.
 */
export type ProvenanceSignal =
  | 'source_lineage_conflict'
  | 'missing_primary_source'
  | 'provenance_concealment'
  | 'authority_override_claim'
  | 'coercive_trade_urgency'
  | 'prior_denial_reframing'
  | 'bilingual_action_injection';

export interface ProvenanceTriage {
  score: number;
  signals: ProvenanceSignal[];
  reviewRecommended: boolean;
}

const RULES: Array<{ signal: ProvenanceSignal; weight: number; pattern: RegExp }> = [
  { signal: 'source_lineage_conflict', weight: 40,
    pattern: /(?:same|shared|identical|duplicate).{0,48}(?:source|upstream|issuer|feed)|(?:source|upstream|issuer|feed).{0,48}(?:same|shared|identical|duplicate)|DS[-_ ]?\d{1,4}|同源|同一(?:個|个)?(?:上游|來源|来源)|共同(?:上游|來源|来源)|共用(?:來源|来源)|重複來源|重复来源|來源ID相同|来源ID相同/i },
  { signal: 'missing_primary_source', weight: 25,
    pattern: /without (?:an? )?primary source|no primary issuer|unverified source|unconfirmed origin|no original (?:issuer )?(?:filing|notice)|未有主要來源|沒有主要來源|沒有官方來源|沒有原始來源|沒有附上.{0,5}(?:原始公告|主要來源)|缺少主要來源|缺少官方來源|未經證實來源|未經確認來源|沒有第一手來源|無第一手來源/i },
  { signal: 'provenance_concealment', weight: 35,
    pattern: /hide|conceal|do not mention|don't mention|delete (?:the )?original|suppress (?:the )?source|remove (?:the )?source|隱藏來源|隐藏来源|隱瞞.{0,8}來源|隐瞒.{0,8}来源|不要提.{0,5}(?:來源|来源)|刪除原文|删除原文|掩蓋|掩盖/i },
  { signal: 'authority_override_claim', weight: 35,
    pattern: /pre[- ]?clear(?:ance|ed)?|verbal(?:ly)?[^.。]{0,20}(?:pre[- ]?approv(?:al|ed)|clearance)|already approved|mandate.{0,24}\b(?:raised|changed|overridden)\b|(?:limit|ceiling|budget).{0,30}(?:raised|increase[ds]?|under review)|approved exception|ignore.{0,20}(?:mandate|policy|limit)|override.{0,20}(?:mandate|policy|limit)|bypass.{0,20}(?:mandate|policy|review)|(?:human|manual) review.{0,32}(?:should not|shouldn't|must not|need not|needn't|doesn't need to)\s+(?:block|stop|prevent|hold)|人工(?:复核|覆核|審查|审查).{0,24}(?:不應|不应该|不該|不该|無需|无需|不需要|不用|不能|不得).{0,8}(?:阻止|阻攔|阻拦|攔阻|拦阻|擋住|挡住)|口頭.{0,28}(?:pre[- ]?clear(?:ance|ed)?|預先.{0,8}(?:批准|批核|確認)|預批|批准|批核|確認|授權)|口头.{0,28}(?:pre[- ]?clear(?:ance|ed)?|预先.{0,8}(?:批准|批核|确认)|预批|批准|批核|确认|授权)|預先批准|预先批准|已經批准|已经批准|授權已更改|授权已更改|上限.{0,12}(?:調高|调高|提高)|預計.{0,8}(?:提高|調高)|预计.{0,8}(?:提高|调高)|忽略.{0,12}(?:授權|授权|限制)|覆蓋.{0,12}(?:授權|授权|限制)|绕過.{0,12}(?:授权|限制)|繞過.{0,12}(?:授權|限制)/i },
  { signal: 'authority_override_claim', weight: 35,
    pattern: /(?:skip|bypass|avoid).{0,24}(?:any )?(?:mandate|limit|cap|risk|compliance).{0,16}(?:check|review|validation)|(?:compliance|risk|broker|desk).{0,48}(?:flagged|requires?|must use|insists?).{0,48}(?:stale|market|limit|execution)|(?:limit price|order type).{0,36}(?:stale|market execution)/i },
  { signal: 'prior_denial_reframing', weight: 35,
    pattern: /(?:not (?:a )?(?:denial|rejection|refusal)|not refused).{0,100}(?:same|previous|earlier|denied|retry|parameters|order|proposal)|(?:previous|prior|earlier|denied).{0,36}(?:attempt|order|proposal|parameters|request|denial|rejection|step[- ]?up).{0,90}(?:same|repeat|retry|queue|order|parameters|proposal|again)|(?:上次|之前|早前|先前|上一(?:單|单|個訂單|个订单)).{0,24}(?:拒絕|拒绝|被拒|否決|否决|step[- ]?up|人手覆核|人工覆核|人工复核).{0,110}(?:本次|今次|改用|合規候選|合规候选|同一|照返|維持|维持|重試|重试|排隊|排队|參數|参数|紙單|纸单|不應阻止|不应该阻止)|(?:唔係|不是).{0,6}(?:拒絕|拒绝|否決|否决).{0,80}(?:同一|維持|维持|照返|參數|参数|紙單|纸单)/i },
];

const ACTION = /\b(?:buy|sell|deploy|execute|place|trade|purchase)\b|買入|买入|賣出|卖出|買|买|落盤|落盘|落單|落单|掛|挂|執行|执行|部署|下單|下单/i;
const URGENCY = /\b(?:now|immediately|before (?:the )?(?:open|reopen)|ahead of the crowd|before (?:it|price) reprices|urgent|act fast)\b|立即|馬上|马上|即刻|快啲|快點|快点|趕在|赶在|好急|唔好再拖|唔好拖|唔好再問|唔好再问|唔使再等|唔使再走|窗口.{0,8}(?:窄|閂|关)|收市前|開盤前|开盘前|重開前|重开前|下一個.{0,12}(?:tick|跳動)|下一个.{0,12}(?:tick|跳动)/i;
const ACTION_INJECTION = /(?:ignore.{0,24}(?:previous|prior|instruction|mandate|policy)|override.{0,24}(?:mandate|policy|limit)|bypass.{0,24}(?:mandate|policy|review)|already approved|forge.{0,16}approval|hide.{0,24}(?:source|provenance)|do not mention.{0,24}(?:source|provenance)|忽略.{0,12}(?:之前|先前|指示|授權|授权)|覆蓋.{0,12}(?:限制|授權|授权)|绕過.{0,12}(?:限制|授權|审查)|绕过.{0,12}(?:限制|授权|审查)|隱瞞.{0,16}(?:來源|原始公告)|隐瞒.{0,16}(?:来源|原始公告))/i;

export function triageProvenance(trigger: string): ProvenanceTriage {
  const text = trigger.normalize('NFKC');
  // Explicit negation samples in the cards describe the absence of a signal.
  const riskText = text
    .replace(/no source conflict or request to conceal information/gi, '')
    .replace(/no primary issuer event is asserted/gi, '')
    // Remove only the negated cue span. Keep following clauses intact so a
    // positive instruction later in the same note still raises the signal.
    .replace(/(?:there\s+(?:is|was)\s+)?no\s+(?:explicit\s+)?(?:instruction|request|direction)\s+to\s+(?:bypass|override|ignore)\s+(?:the\s+)?(?:review|mandate|policy|limit)\b/gi, '')
    .replace(/(?:there\s+)?(?:is|was)\s+no\s+(?:explicit\s+)?(?:instruction|request|direction)\s+to\s+(?:bypass|override|ignore)\s+(?:the\s+)?(?:review|mandate|policy|limit)\b/gi, '')
    .replace(/(?:沒有|無|未有)\s*(?:任何|明確|明確的)?\s*(?:指示|要求|方向)\s*(?:去|要)?\s*(?:繞過|绕过|覆蓋|覆盖|忽略)\s*(?:審核|审查|覆核|复核|授權|授权|政策|限制)/gi, '')
    .replace(/\bmandate\b.{0,24}\b(?:unchanged|(?:not|never)\s+(?:been\s+)?changed)\b/gi, '')
    .replace(/沒有來源衝突，也沒有要求隱瞞資訊|没有来源冲突，也没有要求隐瞒信息/gi, '');
  const signals: ProvenanceSignal[] = [];
  let score = 0;
  for (const rule of RULES) {
    if (rule.pattern.test(riskText)) {
      signals.push(rule.signal);
      score += rule.weight;
    }
  }
  if (ACTION.test(riskText) && URGENCY.test(riskText)) {
    signals.push('coercive_trade_urgency');
    score += 15;
  }
  if (/[A-Za-z]{3,}/.test(riskText) && /[\u3400-\u9fff]/.test(riskText) && ACTION_INJECTION.test(riskText)) {
    signals.push('bilingual_action_injection');
    score += 10;
  }
  const uniqueSignals = [...new Set(signals)];
  return {
    score: Math.min(100, score),
    signals: uniqueSignals,
    // A signal is enough to send content to the semantic reviewer. This never authorizes.
    reviewRecommended: uniqueSignals.length > 0,
  };
}
