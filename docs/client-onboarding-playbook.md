# OKO Client Onboarding Playbook — Framework and Worked TPA Case

**Status:** Aligned (June 2026)
**Companion docs:** [`validation-and-pilot-plan.md`](./validation-and-pilot-plan.md) (pilot protocol this playbook feeds), [`data-sourcing-engine.md`](./data-sourcing-engine.md) §5 (data contract, posture).

**Posture, restated because it governs everything here:** OKO does no client data processing. We provide the specification, deterministic tooling, and the reference graph; **the client performs every step that touches their data, inside their environment.** Onboarding is them conforming to a contract — not us running a data project. This is what makes the feasibility test fast, repeatable, and zero-egress.

---

## The answer to "What do you need us to do with our data?"

The scripted answer, verbatim:

> "Three things, all inside your environment. **One:** run the extract spec below against your claims warehouse — it's a handful of flat tables, and your data team has written this query a hundred times. **Two:** run our validator and normalizer CLIs on the extract; they tell you immediately what's missing or malformed and produce a coverage report. **Three:** hand us the coverage report — numbers only, no records. If the coverage gates pass, we proceed to a blind pilot scored against your own historical SIU outcomes, with success criteria we agree on before anything runs. We never see, clean, or map your data; nothing leaves your network."

---

## Onboarding framework (any client)

### Phase 0 — Qualification (one call, no data)

We ask for five facts, answerable from their data dictionary:

1. Claim volume and history depth (need ≥ 24 months).
2. NPI presence on claims (billing/rendering/referring fields populated? approximate fill rate).
3. Address fields available as raw strings (service, billing, provider).
4. Note text availability (adjuster/SIU notes, in queryable text — not scanned PDFs).
5. Historical SIU outcomes: referral and investigation dispositions, with dates (this is the pilot's ground truth — see validation plan).

A "no" on 1, 2, or 5 ends qualification honestly: 1–2 mean the graph can't anchor; 5 means feasibility can't be measured.

### Phase 1 — Extract spec (the contract, client-side work)

Flat tables (Parquet or CSV), one row per record. **Required fields bolded.**

| Table | Fields |
|---|---|
| `claims` | **claim_id**, **billing_npi**, rendering_npi, referring_npi, **service_date_start**, service_date_end, **paid_amount**, billed_amount, claim_type, procedure summary or pre-aggregated numeric features |
| `providers` (their provider master, if distinct) | **provider_key**, **npi**, tin/ein, provider_name, **raw address fields** |
| `parties` (optional: claimants/employers/facilities) | **party_key**, party_type, name, tin/ein where lawful, **raw address fields** |
| `notes` (optional) | **claim_id**, note_text (or pre-computed 768-d embeddings) |
| `outcomes` (pilot ground truth) | **claim_id or provider_key**, **disposition** (mappable to fraud-confirmed / fraud-suspected / cleared / not-investigated), **disposition_date**, referral_date |

Explicitly **not accepted:** raw X12 837/835 EDI (warehouse extracts only, v1), SSNs, member medical detail beyond claim-level features, scanned documents.

### Phase 2 — Client-side preparation (their data team, our CLIs)

1. **Column mapping** — map warehouse names to contract names (a mapping workbook, filled by them).
2. **`oko-ingest validate`** — pandera contract checker; actionable per-field errors (their iteration loop, no OKO involvement).
3. **`oko-ingest normalize-addresses`** — deterministic canonical address keys (sourcing doc §5.2).
4. **Local note embedder** (shipped utility) — note_text → 768-d `note_emb` on their hardware; raw text never leaves.
5. **Coverage report** (deterministic counts, no records): NPI match rate against the reference snapshot, address canonicalization rate, outcome volume by disposition and year, claims-per-provider distribution.

### Phase 3 — Feasibility gates and tier assignment (decided from the coverage report alone)

The gates below assign the client a **standard tier** (product-scope Requirement 5), not just pass/fail: Tier 1 (claims + NPIs) → provider-centric scoring; Tier 2 (+ structured parties incl. attorneys/firms) → full ring detection; Tier 3 (+ notes/embeddings) → richest evidence. A client below Tier 2 is onboarded at the tier they support and grown later, rather than rejected. Default thresholds — tune with experience, but agree on them *before* Phase 2:

| Gate | Default threshold | Why |
|---|---|---|
| Claims with valid billing NPI matched to reference graph | ≥ 85% | The deterministic join is the architecture's anchor |
| Addresses canonicalized | ≥ 70% | Below this, shared-address structure is too sparse to help |
| Confirmed-fraud outcomes | ≥ 300, spanning ≥ 18 months | Enough positives for fine-tune + a temporally held-out evaluation period |
| Claims history | ≥ 24 months | Temporal split (P1 train / P2 blind) needs room |
| Notes coverage (if notes promised) | ≥ 50% of claims | Otherwise run the pilot without `note_emb` and say so |

Pass → pilot. Marginal → pilot with documented caveats. Fail → we say no, with the specific gap; this protects the benchmark integrity of every future pilot.

### Phase 4 — Blind pilot (validation plan, §"blind pilot protocol")

Pre-registered metrics → temporal split → blind scoring of P2 → client-computed lift report. We see metrics, never records.

### Phase 5 — Readout and decision

Pass: production deployment; their historical outcomes become the first fine-tuning labels; flywheel starts. Fail: pre-registration means the result is diagnostic (which gate or metric, by how much), not a vibes-based breakup.

---

## Worked case: hypothetical client "TPA-1"

**Profile:** national third-party administrator; ~3M medical claims/year across self-funded employer health plans, all 50 states; claims warehouse on Snowflake; adjuster notes in the claims system; an 8-person SIU reviewing ~250 referrals/month; no ML fraud scores today (rules + adjuster referrals). Arrives with "all of our structured data and all of our notes" and the question this playbook scripts.

**Phase 0 (call):** 6 years of history; billing NPI ~97% populated, rendering ~88% (institutional claims missing rendering — normal); provider master with TINs; notes queryable text, ~70% of claims; SIU dispositions tracked since 2021 — ~1,900 confirmed-fraud claims, ~7,400 cleared, dated. **Qualified.**

**Phase 1–2 (their side, ~2 engineer-weeks typical):** five extract tables from Snowflake; mapping workbook (~40 columns); validator catches their date format and a claim_type enum mismatch — fixed by them in two iterations; normalizer + embedder run on a VM in their VPC; coverage report produced.

**Phase 3 (coverage report says):** billing-NPI reference match 94% (unmatched: atypical providers, new enumerations — become local nodes); addresses canonicalized 81%; 1,900 confirmed positives over 4+ years; notes on 70%. **All gates pass.**

**Phase 4 (pre-registered, then run):** train on 2021–2023 outcomes (P1), blind-score 2024–H1 2025 (P2). Pre-registered criteria, agreed with their SIU director: (a) ≥ 2× confirmed-fraud capture vs their incumbent referral ordering in a top-250/month queue; (b) dollar-weighted recall ≥ 1.5× incumbent at same k; (c) report rank-stability across two retrain seeds. Their analyst runs the shipped report script against held-back P2 dispositions.

**Phase 5:** metrics-only readout. Pass → contract; the 2021–2025 dispositions seed production fine-tuning; SME labels accumulate from the live queue thereafter (product-scope staged promise).

**Total client effort in the worked case: one call, one extract, one mapping workbook, four CLI runs, one analyst-day of evaluation.** That sentence is the onboarding pitch.

---

## Failure modes to anticipate (and the framework's answer)

| Failure mode | Answer |
|---|---|
| "Our notes are PDFs/images" | Out of scope v1 — run without `note_emb`; the graph still scores. Revisit at their OCR maturity. |
| Low rendering-NPI fill on institutional claims | Expected; billing NPI anchors the join. Note in coverage report, proceed. |
| Outcomes recorded per-provider, not per-claim | Acceptable — pilot evaluates at provider level (Track-A style); claim-level lift deferred to production labels. |
| They ask us to write the warehouse queries | Decline (posture). Provide the spec + field dictionary; their engineers own their schema. |
| They want to send us data "to make it easier" | Decline. Zero-egress is a feature, their counsel will agree. |
| < 300 confirmed outcomes | Offer the provider-level public backtest (Track A) scoped to their network as evidence, and a longer pilot window; don't fake a claim-level result. |
