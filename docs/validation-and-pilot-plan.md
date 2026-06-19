# OKO Validation & Pilot Plan — Proving Accuracy and Value Without Client Data

**Status:** Aligned (June 2026) — plan only; no validation runs executed yet (the reference graph that Track A needs is not yet built from real data)
**Last updated:** 2026-06-19
**Companion docs:** [`product-scope.md`](./product-scope.md), [`data-sourcing-engine.md`](./data-sourcing-engine.md), [`client-onboarding-playbook.md`](./client-onboarding-playbook.md)

The validation problem has a structural advantage: **the provider-level half of OKO's claim can be proven on fully public data with real labels.** Exclusions and indictments are dated public events; the reference graph is built from dated public snapshots. Claim-level proof requires either synthetic claims (mechanism proof) or a blind pilot on client infrastructure (field proof). The program below sequences all three.

**Guiding principle — land on zero client conformance.** The proof must be strong enough that a client never has to weigh "do we conform our data to them" before believing — they believe *first*, on data they did not lift a finger to prepare, then conform. So the sequencing is deliberate: **Track A and Track C require zero client data; the first pilot is Tier-1 only** (claims + NPIs they already have — no NER, parties, or events); the maximal standard is the *expansion*, never the entry bar (product-scope: "Land-and-expand"). These tests must be *hyper-realistic* — real entities, real outcomes, honest time-ordering — not toy demos.

---

## Track A — Temporal backtest on public data (flagship)

**The experiment:** build the reference graph *as-of* time T0, score every provider, then measure how many providers excluded (LEIE) or indicted (DOJ/OIG enforcement) in the following 12–24 months appear in our top-k.

- **As-of reconstruction:** NPPES monthly files are full replacements with archived vintages (NBER mirrors historical files — verify availability at build time); LEIE supplements and enforcement actions are dated; CMS utilization is published per calendar year. All features must be reconstructable as-of T0 — same temporal discipline as sourcing doc §4.3.
- **Outputs:** precision@top-k, lift over random, lift over the M4b XGBoost baseline. Headline format: *"Of providers excluded in year Y, X% were in our top 1% of risk 12 months earlier — N× lift over random, M× over the GBM baseline."*
- **External anchor:** an established academic line uses LEIE labels on CMS utilization data (classical ML, ~0.8 AUC range). Verify current published SOTA at build time; beating it on a comparable split is a citable claim.
- **Hard dependency:** snapshot-vintage retention is an **M1 ingestion requirement** (sourcing doc §6) — store every snapshot from day one, backfill historical vintages where archives allow. Without as-of graph reconstruction, this track cannot run.

## Track B — Overlay benchmark (claim-level mechanism proof)

Mode B (sourcing doc §4.2): real entity/address/NPI topology + synthetic claims + planted patterns. **Honest framing:** proves the *mechanism* (the GNN finds rings in realistic structure), not field accuracy — synthetic claims cannot certify claim-level precision. Its real value is **ablations**, each a quantified answer to a buyer question:

| Ablation | Buyer question answered |
|---|---|
| Pretrain vs `--skip-pretrain` | "Why self-supervision?" |
| Reference-graph features on/off | "Why do I need your scraped data?" |
| GNN vs XGBoost-on-graph-features (M4b gate) | "Why a GNN?" |
| Weak labels vs none at zero SME labels | "What do I get on day one?" |

## Track C — Case-study replays (qualitative demo)

Rebuild the pre-indictment public graph around defendants of a named enforcement action (e.g., the 2025 DOJ National Takedown) and show the connective tissue — shared addresses, reassignment chains, common officers — was visible in public data *before* the indictment, with every hop cited to a public record. Doubles as the Layer-2 agent showcase.

---

## Buyer-shaped metrics (pre-registered, not post-hoc)

AUC is for internal gates. External claims use:

- **Precision @ reviewer capacity** — "your SIU reviews ~200 claims/month; we put X confirmed-bad in those 200 vs Y under your current ordering."
- **Dollar-weighted recall** — share of fraudulent *paid amount* captured in top-k.
- **Lift vs incumbent queue** — against their current rules/score ordering, not against random only.
- **False-positive burden** — clean claims per investigator-hour at the chosen k.
- **Rank stability** across retrains (trust metric, reported alongside accuracy).

All pilot success criteria are **pre-registered**: metric definitions, k, evaluation window, and pass thresholds agreed in writing before any scoring run. This is both honest and a sales asset — it signals we expect to pass.

---

## The blind pilot protocol (their data, their infra, zero egress)

Key reframe: clients "without labels" still hold **historical SIU referral and investigation outcomes** — ground truth for a backtest, even though their live claims are unlabeled.

1. **Deploy on their infrastructure** via the standard contract path (onboarding playbook). No claim data egresses; we ship software + the reference snapshot in.
2. **Temporal split:** fine-tune on outcomes from period P1, score the held-out period P2 *blind* — model never sees P2 outcomes.
3. **They evaluate:** P2 scores vs P2 outcomes they hold, computing the pre-registered metrics with a shipped report script.
4. **Deliverable:** a lift report generated locally. We see metrics, never records.
5. **Conversion logic:** if pre-registered thresholds pass, the same historical outcomes become the first production fine-tuning labels — the flywheel starts at signature.

What makes this incentive-compatible for the client: Tracks A/C earn the meeting with public-data evidence; the pilot costs them one warehouse extract and compute, risks no data exposure and no production change, and pass/fail is defined before we run.

## Sequencing

Track B ablations come free with M4/M4b. Track A lands after M1–M2 (requires vintages + resolution). Track C is cheap after M2 and is the demo asset. The pilot protocol activates per-client after M3 (contract + connectors + validator tooling exist).
