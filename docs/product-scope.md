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
| **3 — Review queue & feedback capture** | Case-level review UI (thin) over a structured feedback schema (load-bearing): disposition + connection-validity + evidence-quality, routed to their sinks | Scoped below (Requirement 4) |

## Requirement 1 — Scraped bad-actor data

**Verdict: keep, exactly as designed. This is the moat, and it compounds with every monthly refresh.**

Precision about where the signal lives: a *direct* hit (claim touches a LEIE-excluded NPI) is a compliance signal — payers are required to screen exclusions and such claims should be blocked upstream. The ML signal is **proximity and structure**: claims one or two hops from bad actors via shared (suite-level, agent-filtered) addresses, PECOS billing-reassignment chains, common officers, co-location with enforcement targets. No rules engine expresses this well and no client's claims data contains it — it exists only because the reference graph exists. This is also precisely the multi-hop substrate the Layer-2 agent reasons over.

**The keyless-party correction (important — it reweights the resolution layer):** deterministic keys are rich for *one* sub-graph — healthcare billing/rendering providers, which carry NPIs by regulation. But the highest-signal ring *connectors* are frequently **keyless**: attorneys, law firms, marketers/runners/cappers, body shops, interpreters. Industry evidence is strong that the law firm is often the *hub* of a staged-accident/organized ring (the facilitator "from intake through payout"; cf. the FedEx RICO suit against the Ikhilov Law Group), and incumbent SIU tooling already treats attorney/clinic/claimant resolution and "attorney–clinic pairing" detection as table stakes. Attorneys have no NPI; clients track these parties poorly; they sometimes appear only in terse adjuster notes (caseloads of 110–340 claims/adjuster degrade note quality — deep entity mentions are unrealistic). **Consequence:** dirty/probabilistic entity resolution is not a residual edge case — for ring detection it is close to the main event, which (a) raises the priority of scraping the keyless-party universe into Layer 0 (state bar registries incl. disciplinary history as a weak signal; court records for attorney-of-record; business registries for firm entities — this un-parks and elevates the court-records expansion), and (b) surfaces an open strategic decision recorded in "Open decisions" below.

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

## Requirement 4 — The human feedback loop (review → continuous improvement)

**Verdict: feasible and it sharpens the product rather than expanding it — all in Layers 2–3, no change to the scorer. But the intuition "reviewers approve/reject the model's connections and that trains the model" must be decomposed, or the loop collects feedback it cannot use.**

### Feedback has three sinks, not one

The single most important correction: connection-level feedback does not train the scorer's weights. It routes to three different systems, and conflating them is the central design risk.

| Feedback type | Example | Sink | Effect |
|---|---|---|---|
| **Case disposition** | "this claim/ring is fraud" / "clean" | **Scorer** (existing fine-tune: label + `sample_weight`) | Strongest, cleanest accuracy signal. Already supported. |
| **Connection validity** | "this shared-address link is spurious — registered-agent address" / "legitimate referral" | **Graph cleaning + entity resolution** (edge prune/down-weight, address-type classifier, `same_as` correction) | Highest-leverage: fixing the input graph improves *every* future prediction over it. |
| **Evidence usefulness** | "the agent's reasoning here was good/weak" | **Explainer** (tune subgraph extraction / learned explainer) | Improves narration quality and reviewer throughput; not a ranking-accuracy signal. |

The trap to retire explicitly: rejecting an edge does not "lower the fraud score" — the GNN's score is not a human-legible sum of edges. Supervising the GNN's internal edge-importances to match human judgment is the least reliable corner of the research space (attention-supervision rarely improves ranking, often hurts). So: **disposition trains the model; connection feedback cleans the graph the model reasons over.**

### The "rich volume" premise is optimistic — design for scarce, structured labels

Self-supervision is the cold-start lever and does *not* depend on review volume; review volume is the fine-tuning lever. SIU labor is scarce (TPA-1: 8 reviewers, ~250 cases/month), so realistic feedback is *hundreds of high-quality structured labels/month*, not thousands — plenty to fine-tune a pretrained model, but it means the UI optimizes for label **quality and structure**, not throughput. Counterintuitively, high volume drawn only from the model's high-confidence region *worsens* selective-label bias (the model learns to agree with itself) — which is exactly why the exploration slice (Requirement 2) is mandatory, not optional, the moment a feedback loop exists.

### UX/UI shape (the founder's instinct, made precise)

Well-trodden pattern: technology-assisted review (e-discovery TAR) crossed with a bank fraud-alert queue. Three specifics:

1. **Unit of review is a *case*, not an edge.** A flagged claim/ring *with its evidence subgraph*; the reviewer affirms/corrects specific evidence items within it. Hierarchical, not a flat swipe-deck of edges (too granular, low-information, exhausting).
2. **Reframe authoring → verifying.** The agent pre-drafts the case narrative with public-record citations; the reviewer verifies or corrects the agent's asserted connections. Faster, and it makes feedback naturally structured — every correction attaches to a specific assertion.
3. **Structured reason codes first, free text second.** A small taxonomy (spurious-address, legitimate-referral, confirmed-ring-member, identity-mismatch…) maps each correction directly to a sink and is consistent across reviewers and immediately trainable; free text feeds the agent's context and is parsed later. This delivers both throughput and trainability — the resolution of the "consistent text-based feedback" goal.

### Two design decisions this surfaces

- **A feedback taxonomy that routes each signal to its sink** (disposition → scorer; connection-validity → graph/resolution; evidence-quality → explainer). Without it, feedback accumulates unusable. This makes Layer 3's *schema* strategically load-bearing even though its *UI* stays minimal — the schema is the actual flywheel.
- **Feedback scoping: client-local vs. global.** Structural corrections to *public* reference data (e.g., flagging a registered-agent address) may promote to the shared reference graph with review and help every client; anything touching client claims/dispositions stays client-private. Privacy and anti-overfitting both demand this line be explicit.

Plus one data-quality operational note: with multiple reviewers, track inter-reviewer agreement and lightly adjudicate the gold set — disagreement is label noise that silently caps model quality.

## Requirement 5 — The input-data standard (garbage-in is the real ceiling)

**Verdict: correct and load-bearing — arguably the most important product realization so far. A pure scoring model's accuracy ceiling is the client's data quality, which varies wildly across TPAs/carriers. So the *input standard is part of the product*, not an onboarding detail. But the standard must be adoptable, privacy-preserving, and tiered, or it either produces a bad product (too loose) or has no addressable market (too strict).**

### Don't invent a standard — profile an existing one

The industry already has claims standards, and CMS is actively mandating them:
- **X12 837** (claims) / **835** (remittance): the universal EDI format every payer/TPA already emits.
- **HL7 FHIR**, specifically the **CARIN Blue Button** IG (claims/EOB, v2.1.0) and **Da Vinci PAS** — the modern API direction, now pushed by the CMS interoperability rule **CMS-0057-F** ([CARIN BB](https://build.fhir.org/ig/HL7/carin-bb/), [FHIR vs 837](https://www.flexpa.com/blog/fhir-vs-x12-837-simplifying-claims-data)).

OKO's contract should be a **constrained profile of FHIR CARIN BB (and/or an 837 subset) plus OKO extensions** (canonical address keys, resolved party IDs, and the structured **parties/attorney table**). This rides a tailwind: payers are *already* being forced to build FHIR claims capability, so our standard piggybacks on mandated spend, and clearinghouse converters (837↔FHIR) already exist. This revises the earlier "refuse raw 837": we don't parse arbitrary EDI, but we anchor our contract to its vocabulary so client data teams and clearinghouses already know how to produce it.

### Tiered standard with graceful degradation (resolves the high-bar/few-clients tension)

A single strict standard would exclude messy-data clients (most of them); a loose one yields a bad product. Resolve with tiers, where the onboarding coverage gates *determine the tier* rather than pass/fail:

| Tier | Client provides | Product delivered |
|---|---|---|
| **1 — Core** | Claims + provider NPIs (canonical addresses) | Provider-centric scoring |
| **2 — Parties** | + structured party records incl. attorneys/firms/marketers | Full ring detection (the differentiated value) |
| **3 — Narrative** | + adjuster notes (or pre-computed embeddings) | Richest evidence + note signal |

This lets us sell to a messy-data client at Tier 1 and grow them, while never silently running ring-detection on data that can't support it. **It also resolves the notes/keyless-party fork:** structured parties move *into the standard* (extraction burden shifts to the client/clearinghouse who must produce a conformant parties table), so client-note-NER becomes an **optional best-effort enrichment** for Tier 3, not a core commitment. We get the keyless parties by raising the input bar, not by doing everyone's extraction.

### Privacy: "they send it, we don't see it, we send results back"

Three options, in adoption order — note the founder's instinct maps to TEE, not homomorphic encryption:
- **v1 — On-prem / VPC deployment (already our design).** OKO runs inside the client environment; data never egresses; we never see it. Solves the privacy requirement outright for any infra-capable client — which is every large carrier/TPA, and what their security teams already demand.
- **v2 — Confidential computing / GPU TEE (hosted-but-blind).** For clients who can't self-host: client encrypts → computation runs inside a hardware enclave we cannot inspect → encrypted result returned, with remote attestation letting the client cryptographically verify our blindness. Production-ready in 2026: NVIDIA H100/H200 confidential computing runs at 95–99% of native performance (<5% typical overhead), on Azure/AWS, ~10–15% price premium ([NVIDIA](https://developer.nvidia.com/blog/confidential-computing-on-h100-gpus-for-secure-and-trustworthy-ai/), [benchmark](https://arxiv.org/html/2409.03992v2)). This is the credible realization of the encrypt→compute-blind→decrypt idea.
- **Parked — FHE / MPC.** Literal computation on encrypted data remains impractical for heterogeneous GNNs over large graphs (bootstrapping dominates ~84% of latency; demos are small CNNs). Research watch only; do not promise.

### Onboarding leverage: ensure the carrier-side work without becoming a consultancy

- **Conformance certification ("OKO-Ready").** The `validate` CLI + coverage report (onboarding playbook Phases 2–3) *are* the conformance test suite. Publish the profile + tests; clients self-certify by passing the tier gates. This creates lock-in and pushes prep work to them, by spec rather than by our labor.
- **Clearinghouses as certified integration partners.** Availity, Optum/Change, Waystar et al. already transform claims between formats for a living — they are the natural partners to emit OKO-standard output from a carrier's raw systems, so the carrier doesn't do the work *and* we don't run per-client data projects. We define the spec; partners meet it.
- **A formal standards consortium is a later option, not a now-build** — pursue only on demonstrated market pull; it is a different business and a distraction at this stage.

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
- **M8 — Review queue & feedback capture** (Layer 3, Requirement 4): case-level review UI (thin) over a structured feedback schema (load-bearing) that routes disposition → scorer fine-tune, connection-validity → graph/resolution cleaning, evidence-quality → explainer. Agent-verification framing, reason codes + free text, inter-reviewer agreement tracking, client-local vs global feedback scoping. It exists to feed the flywheel and host the agent's output, not to be a workflow product.

Parked, explicitly: court-records expansion (co-defendant edges from RICO/takedown dockets, PACER RSS pending-case feeds) — high-value Layer-0 enrichment once M1–M4 land; learned explainers (post-M7, telemetry-driven); non-NPI verticals (auto/P&C) pending a linkage-key strategy.

## Research watch

- **Alper — "Adaptive Graph Refinement and Label Propagation with LLMs for Cost-Effective Entity Resolution"** ([arXiv:2605.25814](https://arxiv.org/abs/2605.25814), 2026; full PDF read). Relevant to M2. It rejects the static blocking→matching→clustering cascade (our planned Splink pipeline) in favor of iterative probabilistic label propagation over an evolving KNN graph, spending a fixed LLM-query budget only on ambiguous pairs via a value-density greedy selector. **Adopt phased and modular** — it decomposes into independently deployable components, each built on production tech and each a standalone experiment; stop wherever marginal gain over the Splink baseline stops paying:
  - **Phase 0 — Semantic blocking (no LLM).** PLM/SBERT embeddings + approximate KNN graph (FAISS/hnswlib), edge weight = α·cosine. Replaces brittle rule-blocks, raises candidate recall; this is the embedding-ANN blocking already noted in sourcing §3.4. Deterministic. Win condition: blocking recall vs Splink rule-blocks at equal candidate volume.
  - **Phase 1 — Weighted label propagation (no LLM).** Soft-transitivity over the KNN graph auto-resolves high-confidence matches for free and reserves hard cases. Classic, deterministic, no external calls. Win condition: auto-resolve precision at zero query cost.
  - **Phase 2 — Budgeted LLM adjudication (full method).** Value-density selection spends a hard $ budget of LLM pairwise queries only on the ambiguous band, feeding verdicts back into the graph (label flip, neighborhood expansion). This is sourcing §3.4 stage-4 made principled and integrated. Reported result: beats SOTA cascaded pipelines (ZeroER, CollaborEM, BatchER, ComEM, LLM-CER) on pairwise-F1 and NMI across 8 benchmarks at $0.5–$3/dataset budgets; ablation shows removing either propagation or the LLM costs >6% F1 — the synergy is the contribution.
  - **Phase-2 adoption gates (non-negotiable):** (a) determinism/audit — cache every LLM pair-verdict as an immutable, versioned decision so reruns reproduce and every match is provenance-logged (model + prompt + verdict); (b) privacy — run only over public reference data or *inside the client enclave*, never shipping client PII to an external LLM. Phases 0–1 carry neither gate and can land first.
  - **Scope:** deterministic NPI/EIN keys stay the spine; Alper's machinery targets the keyless-party residual (attorneys/firms/marketers) where it is actually needed.

## Open decisions

- **Client-side keyless-party resolution (the central fork) — RESOLVED via the input standard (Requirement 5).** Rather than committing to note-NER on client data, we raise the input bar: structured party records (incl. attorneys/firms/marketers) become **Tier 2** of the standard, shifting extraction to the client/clearinghouse. Client-note-NER is demoted to **optional Tier-3 best-effort enrichment**. Internal probabilistic *party* resolution against the reference graph remains core (the moat); we still never clean clients' structured claim fields. This preserves "contract, not consultancy" and avoids betting v1 on note-NER yield over terse notes. Residual guardrail still required: precision-first thresholds + confidence-carried edges + human review band, because false merges manufacture fake rings.
- **Still open:** (a) FHIR-CARIN-profile-first vs. flat-tabular-profile-first for the v1 contract (FHIR rides the CMS mandate but is heavier; flat tabular is faster to pilot). (b) Build the confidential-computing (TEE) hosted option in the M-series or defer until a no-self-host client appears. (c) Whether to pursue a clearinghouse integration partnership early (accelerates onboarding, adds BD surface) or stay direct-only through first pilots.
- Weak-label weight as a config field (`train.weak_label_weight`) vs. folded into the label store.
- OpenCorporates Enterprise budget vs. FL/NY/OH + on-demand state lookups.
