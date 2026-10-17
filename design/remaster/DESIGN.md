# Blackwall leaderboard remaster

A working prototype of the next leaderboard page, built from the real `board.json` plus one run still in progress. Open `index.html`, or rebuild it with `./build.sh [live-run-id]`.

## The idea

The board answers one question for three kinds of reader. A visitor wants the answer in five seconds. A builder wants to know which model fits their job. A skeptic wants to check the work. The remaster keeps one page and puts each reader one step deeper than the last, never more than two levels.

1. **Five seconds.** A sentence generated from the data ("Qwen 3.8 27B leads the board", or "X and Y are tied for the lead" when the intervals overlap), then three answer cards: smartest, fastest, leanest.
2. **A minute.** The wall, a quality-against-speed chart where the green line is the Pareto frontier, linked to the board table by hover.
3. **Depth.** Open any row for strengths and gaps, the inside of a task, behaviour, and provenance.

## What is on the page

| Pattern | What it does here | Evidence |
|---|---|---|
| Headline, then highlight cards | Verdict sentence and three clickable cards before any table | Artificial Analysis leads with one index and highlight cards above the table |
| Pareto frontier as the hero | Staircase wall, shaded dominated region, labels only on the wall and the focused model | Artificial Analysis and OpenRouter plot a frontier ("Show Pareto") |
| Interval on every number | Whisker on every dot, `±` on every score, per-task interval in the profile | Scale and Epoch print `±` and show standard-error bands |
| Rank ranges from reruns | `#1-2` badge from 1,600 simulated reruns of the index, and "chance it is truly first" | Chatbot Arena paper derives rank ranges from interval overlap (arXiv 2403.04132) |
| Reruns you can see | Optional ghost dots jitter inside their own error margin | Hypothetical outcome plots (Hullman Lab 2015 and 2018) |
| Weigh it your way | Five sliders and five presets re-rank the table and move the chart live; `default rank to your rank` arrows keep the default visible; a sentence says who moved | Pattern from weighted rankings; the live-linked chart and the always-visible default are the additions |
| Honest provisional rows | A run in progress sits below the table with a hatched bar for the span its index can still land in | New |
| Row expands into a profile | Dot strip against the board's range, per-part bars with the weakest task preselected, behaviour facts, run provenance, copyable reproduce command | Aider expands each row into run details (commit, error counts); Epoch links per-run logs |
| Compare dock | Pin up to four (shift-click or `c`); profile strip plus pairwise sentences that call a difference only when its interval clears zero | OpenRouter lets you pin models to compare |
| Command palette | `Ctrl K` or `/`: models, effort, axis, weight presets, theme | cmdk-style, keyboard first |
| Glossary in place | Dotted terms open a popover (`wall`, `95% interval`, `cut off`) | Native Popover API, 95.9% support |
| Narrow screens | Container queries collapse the table to cards under 640px | Container queries, 95.9% support |
| Two levels of disclosure at most | Row, then profile; nothing deeper | NN/g on progressive disclosure |

Support figures are the numbers the research pass read from caniuse on 2026-10-17: view transitions 92.9%, `:has()` 93.6%, container queries 95.9%, popover 95.9%. The prototype uses container queries, popover and `<dialog>`; re-sorting animates with the Web Animations API (FLIP), so it needs no view-transition support.

## Choices worth defending

- **Rank is a range, not a number.** Qwen 3.8 and Super are `#1-2` because their intervals overlap. The page says tied when the leader's chance of first place is under 80%.
- **The weights panel is the main new idea.** The index is an equal-weight average of five groups (the page now says so). Letting people change that, with the default always shown next to their ranking, turns a verdict into a tool. Drop long-context weight and Super passes Qwen; weight code and tools and GPT-OSS climbs.
- **Plain words over jargon.** "First token", "cut off", "per correct answer", with the technical term one tap away.
- **Colour carries meaning, not decoration.** Green is the wall and positive; amber means unfinished; the A to D pin colours are the only categorical colours; cyan and red are kept for the wordmark and for gaps.
- **Brand kept.** The glitch wordmark, black ground, `#76b900`, Archivo for display, Atkinson Hyperlegible for text and numerals. The page stays dark by default; a light theme sits behind the toggle and is remembered.

## Accessibility

- Table semantics with `aria-sort` on real buttons, `aria-expanded` rows, `aria-pressed` toggles, and a live region that announces re-rankings.
- Keyboard: `/` and `Ctrl K` search, `j` `k` move, `Enter` opens, `c` pins, `w` weights, `Esc` closes.
- Focus rings everywhere. Neon green is only used as text where it clears 4.5:1 on the ground (`--green-ink`), a darker green in the light theme.
- `prefers-reduced-motion` turns off the wordmark glitch, row animation and the rerun ghosts (one static draw remains).
- No colour-only encoding: every colour is paired with a letter, a position or text.

## What the real site needs (not in the prototype)

1. `board.json` already has per-part scores (`parts`), per-task tokens, cut-off share and latency, speed by prompt length, energy and submissions. Add `live`: the runs in progress with per-task `done/total` and the scored groups, written by the worker (a `status.json`). The prototype computes this from the run files.
2. Per-row `dataChecks` (failed items, retries, interruptions) and the engine launch command, so the provenance block is not reconstructed.
3. Reproducible rank ranges. The simulation is seeded, so the page is stable; export the simulation parameters in `board.json` so other readers get the same ranges.
4. Real URL state (`?effort=max&axis=ttft&w=1,1,3,1,3&open=...`) with `pushState`. The artifact sandbox blocks it, so the prototype keeps state in memory and `localStorage`.
5. A static `<noscript>` table so the board reads with scripts off, and per-model Open Graph cards (the share card exists).

## What the research could not verify

Live Chatbot Arena, OECD Better Life Index, Observable and Datawrapper pages returned errors or blocked access, so the rank-range display, flower-slider weighting and in-cell sparkline patterns are taken from papers and documentation, not from watching those pages. RTINGS' usage lists are on its page but its score sliders were not seen. Scroll-driven animations and anchor positioning support were not confirmed, so they are not used.

## Sources opened

artificialanalysis.ai, epoch.ai/benchmarks, aider.chat/docs/leaderboards, openrouter.ai/rankings, labs.scale.com/leaderboard, llm-stats.com, mlcommons.org inference results, localmaxxing.com, swebench.com; arxiv.org/abs/2403.04132; hullmanlab.northwestern.edu HOP papers; worrydream.com/ExplorableExplanations; nngroup.com progressive disclosure; MDN View Transitions and History; W3C APG sortable table; WCAG 1.4.3 and 2.3.3; caniuse container queries, `:has()`, popover, view transitions.
