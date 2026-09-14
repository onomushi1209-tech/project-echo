# Research Intelligence (STEP 3)

This document covers everything added in STEP 3: turning a `TrendCandidate`
and the `SourceItem`s it was detected from into a structured
`ResearchPacket` -- claims, evidence, conflicts, confidence, research
status -- without any external AI API. For the DISCOVER pipeline this
feeds from, see [SOURCE_INTELLIGENCE.md](SOURCE_INTELLIGENCE.md); for the
pipeline this feeds into (SCORE, CREATE, COMPLIANCE, Human Review), see
[ARCHITECTURE.md](ARCHITECTURE.md).

## Pipeline

```
TrendCandidate -> Relevant Source Collection -> Fact/Claim Extraction
                -> Claim Grouping -> Conflict Detection
                -> Source Independence + Confidence Calculation
                -> ResearchPacket
```

- **`echo.research`** owns everything from a `TrendCandidate` to a fully
  scored `ResearchPacket` (source selection, extraction, claim grouping,
  conflict detection, confidence, status, summary) -- one small,
  independently-testable module per concern, not one large `research.py`.
- **`echo.brains.RealResearchBrain`** composes those modules behind the
  same `ResearchBrain` Protocol STEP 1's `DummyResearchBrain` satisfies.

## Research lifecycle

1. `echo trends detect` (STEP 2) persists `TrendCandidate`s.
2. `echo research run <trend_id>` loads that trend, loads the vertical's
   stored `SourceItem`s and Source Registry, and runs `RealResearchBrain`:
   - **Relevant Source Collection** (`echo.research.source_selection`):
     starts from `TrendCandidate.sources`, then re-derives "same event"
     membership over a time-bounded candidate pool using
     `echo.trend.clustering.cluster_source_items` -- STEP 2's own
     clustering module, reused rather than copied. `TrendCandidate.sources`
     alone is never trusted blindly: a SourceItem ingested *after* the
     trend was detected can still be pulled in.
   - **Fact/Claim Extraction** (`echo.research.extraction`): deterministic
     sentence splitting over `title`/`content`, dropping empty/very-short/
     navigation-like fragments and same-item duplicate sentences.
   - **Claim Grouping** (`echo.research.claims`): groups fact-candidate
     sentences describing the same fact (stemmed token-Jaccard similarity)
     into one `ResearchClaim` each, with the `EvidenceItem`s backing it.
   - **Conflict Detection** (`echo.research.conflicts`): deterministic
     heuristics over pairs within a claim group.
   - **Source Independence** (`echo.research.independence`): distinct
     `source_key` counting.
   - **Confidence Calculation** (`echo.research.confidence`): config-driven,
     [0, 1], per-claim and packet-level.
   - **Research Status** (`echo.research.status`): `READY` /
     `NEEDS_MORE_SOURCES` / `CONFLICTED` / `LOW_CONFIDENCE` /
     `INSUFFICIENT_EVIDENCE` -- informational, never a publish decision.
   - **Summary** (`echo.research.summary`): a deterministic, templated
     rollup of counts -- not prose generation.
3. `repository.save_research(packet)` persists the `research` row plus
   every claim/evidence/conflict it carries.
4. `echo research show|claims|conflicts <id>` inspect a persisted run.

From there, STEP 1's pipeline (SCORE, threshold check, CREATE, COMPLIANCE,
Human Review) takes over unchanged -- `ResearchPacket`'s STEP 1 fields
(`summary`, `key_facts`, `sources`, `source_quality`,
`conflicting_information`, `confidence`) are exactly what
`DummyScoringBrain`/`DummyContentBrain` already read.

## Claims

`ResearchClaim` (`echo.models.research`) represents one fact, not one
article -- multiple sources describing the same fact are one claim with
multiple evidence items, not N separate claims.

| field | notes |
|---|---|
| `claim_id` | |
| `text` / `normalized_text` | representative surface text: the earliest-published fact candidate in the group |
| `claim_type` | free-form label; STEP 3 always uses `"general"` |
| `evidence_ids` | every `EvidenceItem` backing this claim |
| `supporting_source_ids` / `contradicting_source_ids` | distinct `SourceConfig.id` values, split by whether a confirmed (non-`POTENTIAL`) conflict was found against the representative |
| `confidence` | `echo.research.confidence.claim_confidence` |
| `status` | `ClaimStatus` -- see the ladder below |

### Claim status ladder

Deterministic, in `echo.research.claims._claim_status`:

1. Any confirmed (non-`POTENTIAL`) conflict in the group -> `CONFLICTED`.
2. `>= 2` independent supporting sources, one primary or tier_a -> `CONFIRMED`.
3. `>= 2` independent supporting sources, none primary/tier_a -> `SUPPORTED`.
4. Exactly 1 independent supporting source, primary or tier_a/b -> `SINGLE_SOURCE`.
5. Exactly 1 independent supporting source, non-primary tier_c -> `UNVERIFIED`.

### Claim grouping

`echo.research.claims.group_fact_candidates`: greedy single-pass grouping
by Jaccard similarity over **stemmed** tokens (a crude suffix strip local
to this module -- "releases"/"released"/"release" all reduce to the same
stem) against `ResearchConfig.claim_grouping_similarity_threshold`
(default `0.45`). Stemming matters here specifically: without it, "OpenAI
launches X" and "OpenAI announces the launch of X" share too few exact
tokens to clear the threshold, even though they're clearly the same fact.

Sentences that share a subject but assert opposite things (e.g. "launches
X" / "delays X") are **still grouped** -- they're about the same claim --
but `echo.research.conflicts` catches the contradiction within the group,
so they are never silently counted as agreeing with each other. This is
the deliberate design: grouping answers "is this the same claim?",
conflict detection answers "do these sources agree on it?".

## Evidence & provenance

`EvidenceItem` (`echo.models.research`) is always resolvable back to the
`SourceItem` (and its original URL) it came from -- `source_item_id` is
`SourceItem.source_id`. It never carries a full article body: `excerpt` is
bounded to `ResearchConfig.max_excerpt_length` characters (default 240).
One `EvidenceItem` is created per fact-candidate sentence that ended up in
a claim group (so one `SourceItem` can produce several `EvidenceItem`s if
multiple of its sentences supported different claims).

`reliability_tier` / `is_primary_source` on each `EvidenceItem` come from
`echo.research.evidence.SourceRegistryInfo`, injected by the caller (the
CLI, from the loaded Source Registry) -- `echo.research` never imports
`echo.source` and never hard-codes a source's identity.

## Source independence

`echo.research.independence`: two `SourceItem`s from the same
`source_key` count as **one** independent source, never two --
`independent_source_count` is the single source of truth both claim-level
and packet-level independence figures go through. Syndication/copied-
article detection (the same article mirrored under two different
registered sources) is a natural future extension of this module without
changing its signature.

Packet trust statistics count only sources that actually contributed extracted
evidence: primary/tier A presence, independence and source quality all use that
contributor set. Selection alone cannot earn a confidence bonus. `sources` and
`source_assessments` retain the selected pool for provenance, including sources
with `evidence_count=0`; these do not affect trust statistics.

## Primary-source priority

`SourceConfig.primary_source` / `reliability_tier` (STEP 2, `config/sources/
*.yaml`) drive claim status and confidence directly:

- A primary source's evidence is the strongest support a claim can have
  (`CONFIRMED`/`SINGLE_SOURCE` status, `primary_source_bonus` in the
  confidence engine).
- A secondary (tier_b) source confirms/adds context.
- A discovery-only (tier_c) source's confirmation is weighted lowest
  (`UNVERIFIED` when it's the only support).

No company or product name is ever hard-coded in `echo.research` or
`echo.brains.RealResearchBrain` -- see docs/DEVELOPMENT_RULES.md rule 2.

## Conflict detection

`echo.research.conflicts.detect_conflict`: four deterministic heuristics,
tried in order, each returning at most one signal per sentence pair so a
mismatch is never double-counted:

| heuristic | fires when |
|---|---|
| `status_keyword` | one sentence uses a word from a known opposite-status pair (e.g. "released"/"delayed", "approved"/"rejected") that the other doesn't, while sharing other context |
| `date` | both sentences mention a date-like token and the tokens differ |
| `negation` | otherwise near-identical (>= 0.5 token-Jaccard) sentences where exactly one contains a negation marker |
| `numeric` | both sentences contain standalone numbers and the numbers differ |

Status words require whole lexical tokens and exclusive opposite sides.
`unavailable` never matches `available` internally. Identical statements are
not conflicts; a statement containing both sides is ambiguous and does not
establish an exclusive status contrast.

No full natural-language understanding -- STEP 3 scope. Exclusive status-word
contrasts use their own remaining-context overlap check (major at 0.15 or
above, otherwise potential). Subsequent date/negation/numeric checks require
the subject-overlap gate (`_SUBJECT_OVERLAP_THRESHOLD`, default 0.25).
When a heuristic fires but the surrounding context match is thin, it uses
`ConflictSeverity.POTENTIAL` instead of asserting a confirmed
contradiction -- a `POTENTIAL` conflict is recorded (for audit/
traceability) but does not, by itself, flip a claim to `CONFLICTED` or
reassign its supporting/contradicting sources; only `MINOR`/`MAJOR`
conflicts do.

`ConflictRecord` always names both sides (`source_key_a`/`source_key_b`,
`evidence_id_a`/`evidence_id_b`), the heuristic that fired
(`conflict_type`), a human-readable `reason`, and `severity`.

## Research Confidence Engine

`echo.research.confidence`, entirely config-driven via
`ResearchConfig.confidence_weights` (`ResearchConfidenceWeights`) -- every
term is a named, documented field, never an unlabeled magic number:

```
score = base_confidence
       + primary_source_bonus        (if a primary source is present)
       + tier_a_source_bonus         (if a tier_a source is present)
       + independent_source_bonus    (per independent source beyond the first, capped)
       + agreement_bonus             (scaled by the fraction of claims CONFIRMED/SUPPORTED)
       + evidence_coverage_bonus     (if evidence_count >= minimum_evidence_items)
       - conflict_penalty            (per conflict, scaled by severity: potential < minor < major)
```

Clamped to `[0.0, 1.0]` -- STEP 3 never mixes a 0-100 scale in. Claim-level
confidence (`claim_confidence`) uses the same weights over a single
claim's own supporting-source reliabilities/independence/conflict state.

## Research status

`ResearchStatus` (`echo.models.enums`) -- informational only, **never** a
publish/reject decision; COMPLIANCE and the Human Review Gate keep that
responsibility (docs/DEVELOPMENT_RULES.md rule 3). Determined by
`echo.research.status.determine_research_status`, in order:

1. `evidence_count < minimum_evidence_items` -> `INSUFFICIENT_EVIDENCE`.
2. Any confirmed (non-`POTENTIAL`) conflict -> `CONFLICTED`.
3. `independent_source_count < minimum_independent_sources` **and not**
   (a single primary/allowed source is present) -> `NEEDS_MORE_SOURCES`.
4. No claims -> `INSUFFICIENT_EVIDENCE`; exclusively `UNVERIFIED` claims ->
   `LOW_CONFIDENCE`, even when a numeric threshold is met.
5. `confidence < minimum_confidence` -> `LOW_CONFIDENCE`.
6. Otherwise -> `READY`.

`RealResearchBrain` always supplies claims to the status function. Its new
optional `claims` argument preserves the older low-level call signature;
callers using that older form remain responsible for validating claim support.

## Minimum evidence rules

`ResearchConfig` (`echo.research.config`), conservative defaults:

| field | default | meaning |
|---|---|---|
| `minimum_evidence_items` | 1 | floor before a research run is even considered |
| `minimum_independent_sources` | 2 | the normal bar for "enough confirmation" |
| `minimum_confidence` | 0.4 | floor for `READY` |
| `require_primary_source_for_single_source_claim` | `True` | see below |

**A lone official primary source reporting breaking news is not
automatically rejected.** If `primary_source_present` and at least one
independent source exists, `NEEDS_MORE_SOURCES` is bypassed even below
`minimum_independent_sources` -- the claim itself is `SINGLE_SOURCE` (not
silently upgraded to `CONFIRMED`), and the packet can still reach `READY`
if confidence/evidence are otherwise sufficient. Setting
`require_primary_source_for_single_source_claim=False` extends that same
bypass to *any* single source, not just a primary one.

## Observability

After `RealResearchBrain.research(...)` returns, `brain.last_run`
(`ResearchRunStats`) exposes: `sources_considered`, `sources_selected`,
`claims_extracted` (pre-grouping fact candidates), `claims_grouped`
(final claim count), `conflicts_detected`, `primary_source_present`,
`independent_source_count`, `confidence`. `echo research run` prints these
before the report. The stats contain only counts and confidence. Evidence
excerpts are bounded; claim text and templated summaries remain available
through inspection commands.

The selection counts include `candidates_clustered` and
`candidates_truncated`. Trust-related counts describe evidence contributors;
`sources_selected` describes the broader selected pool. Claim text and the
templated summary remain available through the existing inspection commands.

## Performance safeguards

`echo.research.source_selection` first selects the time window around the
trend's source items, then caps the actual clustering input with
`ResearchConfig.max_research_candidates` (default 200,
`ECHO_MAX_RESEARCH_CANDIDATES`). Priority is direct trend anchors first,
then newest publication time, with source ID as a deterministic tie-break.
If anchors alone exceed the cap, their newest bounded subset survives.
Excluded items cannot reenter via the direct-match fallback.

The final selected output has a separate newest-first cap:
`max_research_sources` (default 20, `ECHO_MAX_RESEARCH_SOURCES`). Selection
has no source-quality ranking; registry quality is evaluated after extraction.
Candidate counts before/after truncation are reported explicitly. The history
scan and bounded candidate ranking still scale with input size; only the
clustering input receives a hard count limit. Counts must be positive integers;
similarity/confidence thresholds must be finite values in [0, 1]. Invalid config
fails at construction. See `.env.example` for all six supported research overrides.

## Minimal Japanese text support

Shared normalization uses Unicode NFKC for fullwidth/halfwidth forms. English
ASCII token filtering stays intact; Japanese/CJK runs contribute character
bigrams for deterministic similarity. Japanese content splits at `。！？`
without requiring following spaces. English sentences retain a route based on
three meaningful whitespace words, including at least three ASCII-containing
words when a Japanese product name is present. Symbol-only chunks do not count.
Other sentences containing Japanese can qualify
with at least six Japanese characters, `min_sentence_length` useful alphanumeric
characters (default 20), and three distinct useful characters. Empty, symbol-only,
very short and symbol-padded noise stays excluded.

This supports ordinary Japanese research text without dependencies. It is not
morphological analysis or semantic contradiction detection. Status/negation
heuristics retain their documented English vocabulary; do not interpret a lack
of detected Japanese conflicts as proof of agreement or permission to publish.

## Security

STEP 3 adds no new external communication. `echo.research` only reads
`SourceItem`s already fetched and stored by STEP 2's bounded, http(s)-only
fetch layer (see [SOURCE_INTELLIGENCE.md](SOURCE_INTELLIGENCE.md)
"Redirect scheme security") -- it never re-fetches a URL, never opens a
user-supplied URL, and performs no authentication/robots/WAF bypass of any
kind.

## LLM-free design

Every STEP 3 module is a deterministic, closed-form function: sentence
splitting, stemmed token-Jaccard grouping, keyword/negation/numeric/date
heuristics, config-weighted arithmetic. No embeddings, no LLM calls (see
docs/DEVELOPMENT_RULES.md rule 13, extended to Research Intelligence).
Each module's signature is deliberately stable so a future step could
swap one piece for an LLM-based implementation without touching the
others:

- `extract_fact_candidates(list[SourceItem], ResearchConfig) ->
  list[FactCandidate]` could become an LLM-based claim extractor.
- `detect_conflict(str, str) -> ConflictSignal | None` could become an
  LLM-based contradiction checker.
- `build_summary(...) -> str` could become an LLM-based summarizer.

None of `echo.research.claims`, `confidence`, `status`,
`echo.brains.RealResearchBrain`, or the storage layer would need to
change for any of those swaps, as long as the replacement respects the
same signature.

## Adding a new conflict heuristic

1. Add a `_check_<name>` function to `echo.research.conflicts` returning
   `ConflictSignal | None`.
2. Wire it into `detect_conflict`'s priority order (most-confident checks
   first, so a single pair yields at most one signal).
3. Pick a `ConflictSeverity` -- use `POTENTIAL` if the heuristic can be
   ambiguous.
4. Add fixture tests (see `tests/test_research_conflicts.py`).

## Network tests vs. offline tests

Like STEP 2, `pytest` never touches the network -- STEP 3 doesn't even
have a real-network code path (it only reads already-stored `SourceItem`s).
All fixtures are synthetic (`example.com`), matching STEP 2's convention.
