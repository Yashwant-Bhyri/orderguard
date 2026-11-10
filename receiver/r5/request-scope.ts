const READ_ACTION = /\b(?:show|get|read|fetch|pull|check|view|list|retrieve|inspect|summari[sz]e|what(?:'s| is)?|how much|tell me|give me|look up|display|find)\b|查看|显示|顯示|展示|查詢|查询|查一下|读取|讀取|看一下|列出|获取|獲取|告诉我|告訴我/i;
const ATTRIBUTED_SOURCE = /(?:\b(?:my|our|the)\s+(?:colleague|coworker|friend|manager|broker|analyst|advisor|email|document|message|note|article|website|prompt|model|assistant)\b|\b(?:someone|they|he|she)\b)[^.!?;\n]{0,100}\b(?:said|says|told|asked|recommended|suggested|advised|claims?|states?)\b/i;
const NEGATION = /\b(?:do not|don't|never|not|without|avoid|exclude|skip|stop|no need to|no)\b|(?:不要|不需要|不看|不读取|不讀取|别|別|排除|避免)/i;
const HYPOTHETICAL = /\b(?:what if|suppose|imagine|if only|whether to)\b|假设|假設|如果/i;
const QUOTED_TEXT = /"[^"\n]{0,600}"|“[^”\n]{0,600}”|‘[^’\n]{0,600}’|(?<![\w'])'[^'\n]{0,600}'(?![\w'])/g;

export function isAffirmativeReadRequest(prompt: string, targetPattern: RegExp, vetoPattern: RegExp = targetPattern): boolean {
  const normalized = prompt.normalize('NFKC');
  const target = new RegExp(targetPattern.source, targetPattern.flags.replace(/[gy]/g, ''));
  const veto = new RegExp(vetoPattern.source, vetoPattern.flags.replace(/[gy]/g, ''));
  let quotedRead = false;
  const scopeText = normalized.replace(QUOTED_TEXT, (quote) => {
    target.lastIndex = 0;
    const includesTarget = target.test(quote);
    target.lastIndex = 0;
    if (includesTarget && READ_ACTION.test(quote)) quotedRead = true;
    const entities = [...quote.matchAll(new RegExp(target.source, target.flags + 'g'))].map((match) => match[0]);
    return ' ' + entities.join(' ') + ' ';
  });
  if (quotedRead) return false;

  const clauses = scopeText.split(/[.!?;；\n,，。！？]+/).map((clause) => clause.trim()).filter(Boolean);
  let affirmative = false;
  for (const clause of clauses) {
    target.lastIndex = 0;
    const containsTarget = target.test(clause);
    target.lastIndex = 0;
    if (!containsTarget) continue;

    veto.lastIndex = 0;
    const vetoedScope = veto.test(clause) && NEGATION.test(clause);
    veto.lastIndex = 0;
    if (vetoedScope) return false;
    if (HYPOTHETICAL.test(clause) || ATTRIBUTED_SOURCE.test(clause)) return false;
    if (READ_ACTION.test(clause)) affirmative = true;
  }
  if (!affirmative) return false;

  // A separate sentence can negate the data class without repeating its exact target.
  // This also makes a positive clause plus a conflicting negative clause fail closed.
  for (const clause of clauses) {
    veto.lastIndex = 0;
    const vetoedScope = veto.test(clause) && NEGATION.test(clause);
    veto.lastIndex = 0;
    if (vetoedScope) return false;
  }
  return true;
}
