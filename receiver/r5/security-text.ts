const SECURITY_CONTROL_WORDS = new Set([
  "no", "not", "never", "without", "avoid", "exclude", "except", "skip", "stop",
  "dont", "don't", "don’t", "cannot", "cant", "can't", "can’t", "isnt", "isn't", "isn’t",
  "doesnt", "doesn't", "doesn’t", "shouldnt", "shouldn't", "shouldn’t",
  "wouldnt", "wouldn't", "wouldn’t", "couldnt", "couldn't", "couldn’t",
  "wont", "won't", "won’t", "mustnt", "mustn't", "mustn’t",
]);

// High-confidence Greek/Cyrillic letters commonly substituted for Latin letters.
// This is a narrow control-word guard, not a complete UTS #39 confusables table.
const LATIN_LOOKALIKE: Readonly<Record<string, string>> = {
  а: 'a', Α: 'a', α: 'a', е: 'e', Ε: 'e', ε: 'e', і: 'i', Ι: 'i', ι: 'i',
  к: 'k', Κ: 'k', κ: 'k', м: 'm', Μ: 'm', μ: 'm', о: 'o', Ο: 'o', ο: 'o',
  р: 'p', Ρ: 'p', ρ: 'p', с: 'c', ϲ: 'c', т: 't', Τ: 't', τ: 't',
  у: 'y', Υ: 'y', υ: 'y', х: 'x', Χ: 'x', χ: 'x', ν: 'n', Ν: 'n', ј: 'j', ѕ: 's', ӏ: 'l',
};

const SECURITY_CONTROL_TOKEN = /[\p{L}\p{M}]+(?:['’][\p{L}\p{M}]+)?/gu;

/** Detect high-confidence Greek/Cyrillic lookalikes in security-control words. */
export function hasConfusableSecurityControlWord(text: string): boolean {
  const tokens = text.normalize('NFKC').match(SECURITY_CONTROL_TOKEN) ?? [];
  for (const token of tokens) {
    const normalized = token.normalize('NFKD').toLowerCase().replace(/\p{M}/gu, '');
    let usedLookalike = false;
    const skeleton = [...normalized].map((character) => {
      const replacement = LATIN_LOOKALIKE[character];
      if (replacement !== undefined) usedLookalike = true;
      return replacement ?? character;
    }).join('');
    if (usedLookalike && SECURITY_CONTROL_WORDS.has(skeleton)) return true;
  }
  return false;
}
