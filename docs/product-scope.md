# OKO Product Scope & Roadmap

**Status:** Aligned (June 2026)
**Companion docs:** [`data-sourcing-engine.md`](./data-sourcing-engine.md) (Layer 0 design), [`validation-and-pilot-plan.md`](./validation-and-pilot-plan.md) (proof program & blind pilot), [`client-onboarding-playbook.md`](./client-onboarding-playbook.md) (onboarding framework + worked TPA case), repo README (Layer 1 scoring engine).

## North star

**Everything in this stack exists to serve one end state: a genius-level AI fraud-investigation agent operating at the highest possible level.** The predictive infrastructure — reference graph, GNN scorer, evidence extraction, label flywheel — is the substrate that agent stands on. Every layer below is judged by one question: *does it give the agent better-ranked cases, richer multi-hop evidence, and cleaner citations to reason over?* The agent's advantage over a human reviewer is contextual attention quality across the full graph — it can hold every hop, every provenance record, and every prior pattern in view at once. Our job is to make sure that when it looks, the evidence is there, ranked, and citable.

Posture (unchanged): OKO is a model/intelligence provider, not a data-onboarding service. Clients join on deterministic keys ("contract, not consultancy" — see sourcing doc §5.1).

## The four layers

| Layer | What | Status |
|---|---|---|
| **0 — Reference graph** | Public bad-actor + registry data fused into a versioned graph snapshot (NPPES, LEIE, SAM, PECOS reassignment edges, registries, enforcement actions) | Designed — sourcing doc |
| **1 — Scoring engine** | Heterogeneous GNN: self-supervised pretrain → fine-tune → calibrated ranking of `claim` nodes | Built (this repo); cold-start path designed |
| **2 — Evidence & explanation** | Per-claim evidence-subgraph extraction + agentic narration with public-record citations | Scoped below |
| **3 — Review queue & label capture** | Thin SME interface: ranked queue, accept/reject, label persistence | Scoped below (deliberately thin) |

## Requirement 1 — Scraped bad-actor data

**Verdict: keep, exactly as designed. This is the moat, and it compounds with every monthly refresh.**

Precision about where the signal lives: a *direct* hit (claim touches a LEIE-excluded NPI) is a compliance signal — payers are required to screen exclusions and such claims should be blocked upstream. The ML signal is **proximity and structure**: claims one or two hops from bad actors via shared (suite-level, agent-filtered) addresses, PECOS billing-reassignment chains, common officers, co-location with enforcement targets. No rules engine expresses this well and no client's claims data contains it — it exists only because the reference graph exists. This is also precisely the multi-hop substrate the Layer-2 agent reasons over.

## Requirement 2 — Zero-label cold start, seamless improvement

**Verdict: feasible, with one correction and one staged promise.**

**The correction:** self-supervised pretraining alone cannot produce a fraud ranking — DGI/GraphMAE yield representations; a ranking needs a head, and a head needs *some* supervision signal. Day-one sorting therefore comes from three cheap sources, combined:

1. **Enforcement-derived weak labels** (sourcing doc §4.3): proximity-to-excluded weak positives, positive-unlabeled framing, temporal-split discipline, low `sample_weight`.
2. **Transfer from the overlay graph** (sourcing doc §4.2): a head trained on real-topology + planted patterns, transferred to the client graph.
3. **Anomaly scoring**: GraphMAE reconstruction error as an unsupervised outlier signal — free, since we pretrain anyway.

**The staged promise (sales- and docs-facing language):**
- **Day one:** *risk rank-ordering* — quality sorting of the queue, honest and useful, but not calibrated probabilities.
- **As SME labels accumulate:** calibration (ECE-tracked) and client-specific pattern lift arrive through the existing fine-tuning path; SME labels (weight 1.0) progressively dominate weak labels.
- Never promise calibrated fraud probabilities at zero labels; that is mathematically dishonest.

**Two engineering line-items hidden inside "seamless":**
- **Rank-stability monitoring across retrains.** Investigators lose trust if the queue reshuffles arbitrarily. Track rank correlation between model versions; gate deployments on it alongside AUC.
- **Exploration slice in the review queue.** SMEs only label what we surface — a pure exploit loop confirms itself. A small randomized/diversity slice of the queue (config-driven %) keeps the label distribution honest. Cheap, but only if planned now.

## The baseline gate (non-negotiable)

Before the GNN is trusted (or sold) as the scorer, build the **XGBoost baseline on graph-derived features** — hops-to-nearest-excluded, address entity-density, reassignment fan-in, officer-overlap counts, computed from the *same* reference graph. Much of bad-actor-proximity value is capturable by hand-crafted graph features in a GBM that is explainable nearly for free (SHAP). The GNN must demonstrate lift over that — not over a feature-poor strawman — or it is complexity tax. Either outcome is a win: lift proven → sell the GNN with evidence; lift absent → ship the cheaper model and keep the GNN as a research track. The README has always listed this; it is hereby promoted to a roadmap gate (M4b below).

## Requirement 3 — The investigation agent

**Verdict: right end goal, wrong substrate if taken literally. The agent reasons over evidence, not neurons.**

Raw embeddings and attention weights are not reliable explanation substrates (attention ≠ explanation is well-established; neuron-level interpretation of a trained GNN is open research with no product timeline). The decomposition that gets the genius agent *and* keeps the scorer uncompromised:

1. **Scorer optimizes ranking. Untouched.** No explainability constraint enters the architecture → **no accuracy trade-off, by construction.** Explanation is post-hoc.
2. **Evidence extraction** per flagged claim: v1 is the k-hop neighborhood with edge importances (`FraudScorer.get_embeddings()` already exists for exactly this); v2 adds learned explainers (GNNExplainer/PGExplainer family — which *do* frame explanation as an optimizable probabilistic objective: a subgraph mask maximizing mutual information with the prediction, scored on fidelity/sparsity metrics). The "make explainability a research-optimization problem" instinct is correct — the field has already built the objective functions; we adopt, not invent.
3. **The agent reasons over the symbolic evidence subgraph**: nodes, edges, and — critically — **provenance from Layer 0**. Every hop is citable to a public record: *"flagged because: shares suite-level address with provider excluded 2024-03 (LEIE row), billing reassigned through entity whose officer appears in the 2025 DOJ takedown (citation)."* This is agentic GraphRAG over a graph we own.

**Built ready for the agent** means the predictive infrastructure exposes, as first-class artifacts: ranked claim queues with scores; per-claim evidence subgraphs with edge importances; node/edge provenance and license tags down to source row; embedding access for similarity retrieval ("find prior cases that looked like this"); and stable IDs across snapshot versions so the agent's case memory survives refreshes. These are the agent's senses; Layers 0–2 are specced to provide all five.

**Sequencing discipline:** evidence-retrieval + citation narration delivers ~80% of investigator trust at ~10% of the effort; learned explainers are added when SME agreement-rate data says narration fidelity is the bottleneck. Do not start with neuron-level interpretability research.

## Risk register (business)

| Risk | Read | Mitigation |
|---|---|---|
| Cold-start quality bar | If day-one sorting is mediocre, the "improves with labels" promise never gets tested | Overlay graph (Mode B) is the honest pre-sale benchmark *and* the demo asset |
| Rank churn | Trust erosion is silent and fatal in SIU workflows | Rank-stability gate on retrains |
| GNN lift uncertainty | Complexity tax if GBM matches it | Baseline gate (M4b); either outcome is a win |
| FCRA boundary | Scores drifting from investigator queue toward claim adjudication re-classifies us as a CRA | Contractual + product framing as investigative leads; counsel trigger (sourcing doc §3.3) |
| Reference-data errors harming real providers | NPPES self-reported staleness, false linkage | Precision-first linkage, provenance on every edge, agent citations make errors *visible and contestable* |

## Roadmap (extends sourcing doc §6)

- **M1–M3** — as in sourcing doc: Tier-1 bulk ingestion → internal resolution + first Reference Graph Snapshot → file contract + connectors + normalizer CLI.
- **M4** — Overlay generator (Mode B) + weak-label wiring (Mode C). *Output: the cold-start scorer and the honest benchmark.*
- **M4b — Baseline gate.** XGBoost on graph-derived features vs GNN on the overlay benchmark. Decision point, not a formality.
- **M5** — Tier-3 enforcement scrapers + Tier-2 procurement (per sourcing doc), feeding richer weak labels and provenance.
- **M6 — Evidence layer.** Per-claim evidence-subgraph extraction API (k-hop + importances + provenance), exploration-slice and rank-stability instrumentation.
- **M7 — Agent v1.** GraphRAG narration over evidence subgraphs with public-record citations; SME agreement-rate telemetry from day one (it decides when learned explainers are worth it).
- **M8 — Thin review queue** (Layer 3): ranked queue, accept/reject, label persistence into the fine-tuning flywheel. Deliberately minimal — it exists to feed labels and host the agent's output, not to be a workflow product.

Parked, explicitly: court-records expansion (co-defendant edges from RICO/takedown dockets, PACER RSS pending-case feeds) — high-value Layer-0 enrichment once M1–M4 land; learned explainers (post-M7, telemetry-driven); non-NPI verticals (auto/P&C) pending a linkage-key strategy.
