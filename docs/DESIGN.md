# OrderGuard design language

OrderGuard's job is to say, with evidence, why an AI agent's order was allowed, held or refused. The interface exists
to make that decision legible in one glance and auditable in one click. Everything below serves that.

## 1. Principles

1. **The decision is the hero.** Every tool ends in one verdict: allow, hold, refuse or quarantine. It is the largest
   thing on screen, it names the layer that decided, and it gives the reasons as plain sentences.
2. **Claimed versus trusted.** The core idea of the product is that the agent's numbers are not trusted. Wherever a
   number appears, show what the agent claimed next to what OrderGuard trusts, and what the difference means.
3. **Show the path, not just the result.** The pipeline (L1 to L8) is drawn as a rail. Each run lights the stations it
   passed and stops at the one that acted.
4. **Quiet until it matters.** Neutral greys carry the page. Colour appears only for meaning (verdicts, layers, live
   status). No gradients, no shadows deeper than one step, no decoration.
5. **Numbers are instruments.** Monospaced tabular figures, units always shown, signs explicit (+/−), money as $12,345.
6. **Honest by default.** Caveats sit next to the numbers they qualify, not in a footer.

## 2. Tokens

Defined once as CSS variables on `:root`, redefined under `@media (prefers-color-scheme: dark)` and on
`[data-theme="dark"]` / `[data-theme="light"]` (a theme toggle in the top bar sets the attribute and remembers it in
`localStorage`, wrapped in try/catch).

| token | light | dark | use |
|---|---|---|---|
| `--bg` | #F7F7F5 | #0E0F11 | page |
| `--surface` | #FFFFFF | #16181B | cards, panels |
| `--surface-2` | #F1F1EE | #1D2024 | inset areas, table headers, code |
| `--line` | #E4E4DF | #2A2E33 | hairlines (1px) |
| `--line-strong` | #CFCFC8 | #3A3F46 | inputs, focused containers |
| `--text` | #16181B | #ECEDEE | primary text |
| `--text-2` | #55595F | #A3A8AF | secondary text |
| `--text-3` | #83878D | #6F757D | hints, captions |
| `--accent` | #3355E6 | #7C93FF | links, primary buttons, focus |
| `--allow` | #127A44 / bg #E6F4EC | #4ADE80 / bg #10291B | allow, confirmed, pass |
| `--hold` | #A35C00 / bg #FBF0DD | #FBBF24 / bg #2E2310 | hold, step-up, stale, uncertain |
| `--refuse` | #B42318 / bg #FBE9E7 | #F87171 / bg #351615 | refuse, contradicted, executed attack |
| `--quarantine` | #6B3FD4 / bg #EFE9FC | #B69CFF / bg #251B3D | L2/L3 quarantine |

Contrast: every text/background pair must meet WCAG AA (4.5:1 body, 3:1 large). Check the dark values.

Spacing scale (px): 4, 8, 12, 16, 24, 32, 48, 64. Radius: 6 (controls), 10 (cards), 999 (pills). Borders: 1px
`--line`. Elevation: a single `0 1px 2px rgb(0 0 0 / .06)` on cards; none in dark mode (use `--line` instead).

Type: system UI stack (`-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif`); mono stack
(`ui-monospace, "SF Mono", Menlo, Consolas, monospace`) for tickers, prices, ids, JSON. Use
`font-variant-numeric: tabular-nums` for every number. Scale: 12 caption, 13 label, 14 body, 16 lead, 20 h3,
24 h2, 32 h1 (overview hero only). Weights 400 and 600 only. Line height 1.5 body, 1.2 headings. Sentence case
everywhere; never all caps except layer codes (L1…L8).

Motion: 120 ms ease-out for hover/focus, 200 ms for panel open; the rail animates station-by-station at 60 ms per
station when a result arrives. All motion off under `prefers-reduced-motion: reduce`.

## 3. Layout

- **Shell.** Desktop (≥ 960px): a 232px left sidebar and a content column (max 1120px, 32px gutters). The sidebar
  holds the wordmark, the navigation (Overview, Screen text, Check order, Triggers, Scenarios, Ledger, Results) each
  with the layer codes it exercises as small pills (e.g. Check order: L5 L6), and at the bottom the environment block:
  mode (replay/record/live), provider + model, budget meter (spent of cap), receiver status dot. Below 960px the
  sidebar collapses into a top bar with a menu button; content gutters 16px; no horizontal scroll at 360px.
- **Top of every page:** title (h2), one-sentence purpose, and the layer pills it uses. The research-prototype notice
  is one quiet line in the sidebar footer and on the overview, not a banner on every page.
- **Tool pages** use a two-column layout on desktop: inputs left (40%), result right (60%, sticky). On mobile, result
  below inputs and the page scrolls to it when a run finishes.
- **Command palette** (⌘K / Ctrl+K): jump to any page, run any preset ("Check: fake split order", "Screen: hidden
  instruction"). Plus shortcuts: `g o` overview, `g s` screen, `g c` check order, `?` shows shortcuts.

## 4. Signature components

### The rail
A horizontal row of eight stations (vertical on mobile), L1 to L8, each a 28px circle with the code, the layer name
under it, connected by a 2px line. States: idle (outline `--line-strong`), passed (filled `--text-3`), acted
(filled with the verdict colour, ring 3px of its bg colour), off (dashed outline, 40% opacity), not reached (outline,
the connector after the deciding station is dashed). Hover/focus on a station shows a tooltip with what that layer
checked and its result for this run. Used on: Overview (status of each layer on this server), every result panel
(the path of this run), each scenario timeline step (compact 16px version).

### Verdict card
Top of every result. A 4px left border in the verdict colour, background its bg tint. Contents: the verdict word
(20px, 600, verdict colour, with an icon so it is never colour alone: ✓ allow, ‖ hold, ✕ refuse, ◆ quarantine),
"Decided by L5 order gate" chip, then the reasons as a numbered list of plain sentences, then "Show raw JSON"
disclosure (mono, `--surface-2`, copy button).

### Claimed vs trusted (Check order)
Two aligned columns, "The agent says" and "OrderGuard trusts": limit price vs trusted price, notional at the
limit vs notional at the trusted price, with the difference (±%). Under it, horizontal meters: per-order cap and
daily cap, each a bar showing this order's notional at the trusted price against the cap (fills `--allow` under the
cap, `--refuse` beyond, with the cap as a tick mark), and the price band as a bar with the trusted price at the centre
and the limit marked. Cited figures render as a table: figure, claimed, filed truth, status pill
(confirmed/contradicted/stale/not public yet/unverifiable), source (form, filed date).

### Revealed text (Screen text)
Show the input text with what L1 found made visible: hidden characters as small inline chips (`ZWSP`, `TAG`),
mixed-script tokens underlined with their folded spelling on hover, base64 runs collapsed with the decoded payload
shown beneath. Then three detector rows: local classifier (probability bar 0–1 with the threshold tick, top features as
highlighted spans), fast model (if configured), main model screen; each with its own verdict pill and latency.

### Trigger board (Triggers)
A table of sources (venue/wire × price/claim × independence group, quarantined struck through), the median line,
the rule with its threshold, and the outcome (fires / held, with "needs 2 independent sources, has 1"). Blast radius
as inline SVG horizontal bars: "if source S lies by X%, these rules fire, $N at risk".

### Timeline (Scenarios)
Vertical list of agent steps: tool call (mono name + args summary), the compact rail showing which layers acted, the
gate decision chip, and quarantine/figure notices inline. The final step shows the run's verdict card.

### Results
Headline tiles (4 across desktop, 2 mobile): harmful orders executed (full guard), attack success bare model, clean
tasks completed (full guard), live spend. Then a grouped bar chart in inline SVG: attack success by family (A–F) for
naive / gate_only / full, with Wilson 95% intervals as whiskers; colours: naive `--refuse`, gate_only `--hold`, full
`--allow`, plus distinct patterns or labels so it reads without colour. Then the tables with a family/arm filter. The
"Honest caveats" panel sits directly under the headline tiles.

## 5. States

Every panel has: empty (one line saying what will appear and a "Try an example" button), loading (skeleton rows,
button shows a spinner and is disabled, `aria-busy`), error (inline, `--refuse`, with what to do next), and result.
Errors from the API are shown in words, never as a stack or raw status code alone.

## 6. Voice

Plain, specific, calm. Say what happened and why, with the number: "Refused: 440 shares at the trusted $222.70 is
$97,988, over the $10,000 per-order cap." Never "Oops", never exclamation marks, never "AI-powered". Buttons are
verbs: "Check order", "Screen text", "Evaluate rules", "Run scenario".

## 7. Accessibility

Semantic landmarks (nav, main, header), one h1 per page, labels on every control, `aria-describedby` for errors and
hints, `aria-live="polite"` on result regions, visible 2px `--accent` focus rings with 2px offset, full keyboard use
(palette, tabs, disclosures), hit targets ≥ 36px, never colour alone (icons and words with every colour).

## 8. Constraints

No external requests (strict CSP stays), no frameworks, no build step, no `innerHTML` with any string that came from
the server or the user (build nodes, set `textContent`). Charts are inline SVG built with `createElementNS`. Keep total
static weight under 260 KB uncompressed (200 KB before the Swarm Theater added its page, stylesheet and script). This ceiling includes the Swarm Theater, the Swarm arena's recorded-feed tape, charts, envelope
lab and order-risk card, and the mandate-policy page; `python/tests/app/test_arena_page.py` enforces it so the product keeps the arena without adding a frontend build step.
