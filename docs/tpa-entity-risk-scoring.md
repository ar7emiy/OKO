# Entity Risk Scoring for a TPA — What OKO Can Offer

**Status:** Proposal / discovery response (June 2026)
**Audience:** internal (sales engineering + product) and the requesting TPA
**Companion docs:** [`product-scope.md`](./product-scope.md), [`client-data-standard.md`](./client-data-standard.md), [`client-onboarding-playbook.md`](./client-onboarding-playbook.md), [`data-sourcing-engine.md`](./data-sourcing-engine.md)

---

## 1. The ask, restated

A third-party administrator (TPA) wants to **efficiently produce a risk score for every entity** that appears in their claim notes. Their situation:

- **Structured data:** entities with metadata — names, addresses, occasional NPIs, EINs, etc.
- **Note-extracted entities:** a pipeline runs NER over claim notes and emits entities in a bespoke format. It attempts to also pull **address**, a **category** (legal / medical / …), and a **subcategory/taxonomy**. The latter extraction is *finicky* — it often gets the entity name but leaves everything else null.
- **Watch lists they own:** an NICB feed and a **custom BOLO list**.
- **Full access to claim notes.**

**What they do today:** for each extracted entity name, fuzzy-match (token/string similarity) against their internal watch list; **≥ 90%** similarity → a hit. A **hard constraint** requires the same **category** to match (a "John Doe" tagged *legal* cannot match a "John Doe" tagged *medical*) — but the note classifier that assigns that category is exactly the finicky, null-heavy component.

So the live system has two coupled failure modes:

1. **Name-only fuzzy matching is simultaneously over- and under-inclusive.** Over-inclusive on common names ("John Doe", "ABC Medical"); under-inclusive on nicknames, legal-suffix variants ("Smith LLC" vs "Smith Group"), abbreviations, transpositions, and address-disambiguated namesakes that fall just under 90%.
2. **The hard category gate silently drops true matches** whenever the note classifier mislabels or — more often — *fails to label* the category. A null or wrong category becomes a veto, not missing information.

And underneath both: **"risk score" is being collapsed into a single binary** (matched ≥ 90% & same category → flagged). There is no graded risk, no calibration, no use of *structure* (shared addresses, shared NPIs, co-occurrence on claims, proximity to known bad actors).

> **The reframe that unlocks everything below:** what the TPA calls "fuzzy matching to a watch list" is **entity resolution**, and OKO already treats entity resolution as *the product, not client homework* (`client-data-standard.md` §1.2). Their finicky note-category classifier is the textbook reason OKO argues category should be a **weighted, null-tolerant feature**, never a hard gate. Their problem is squarely OKO's core competency — we are not bending the engine to fit, we are pointing it at the use case it was designed for.

---

## 2. Two scores are being conflated — separate them

The single most useful conceptual change. The current pipeline answers one yes/no question. There are really **two distinct probabilities**, and good scoring keeps them apart:

| | Question | OKO mechanism | Output |
|---|---|---|---|
| **(A) Match / resolution confidence** | "Is this note-extracted mention the *same real-world entity* as a watch-list / structured record?" | Probabilistic entity resolution (`oko_ingest/resolve/`) | calibrated **P(same entity)** + a review band |
| **(B) Entity risk** | "Given who this entity resolves to, how *risky* is it?" | Graph-structural scoring (reference graph + GBM/GNN) | calibrated **risk score** with cited evidence |

Today both are smashed into one threshold. Separating them is what makes the output *defensible*: a high-confidence match to a clean entity is low risk; a medium-confidence match to a BOLO-listed ring connector is worth a look. You cannot express that with a single 90% gate.

The rest of this doc is organized around delivering (A) cheaply first, then (B) as the differentiator.

---

## 3. What we can repurpose, almost as-is

OKO already contains the hard parts. Mapping the TPA's needs onto existing components:

### 3.1 Deterministic + probabilistic entity resolution → fixes the matching directly

`oko_ingest/resolve/` is exactly the matching engine the TPA hand-rolled, done properly:

- **`normalize.py` (built, deterministic, no deps):** produces *blocking keys* that already solve half their precision problem before any similarity is computed:
  - `normalize_org_name` strips legal suffixes (LLC/INC/PC/GROUP…) **and expands medical abbreviations** (MED→MEDICAL, CTR→CENTER, HOSP→HOSPITAL…). "Smith Medical Group LLC" and "Smith Med Ctr" collapse toward the same key.
  - `normalize_person_name` → `LAST FIRST MIDDLE-INITIAL`, dropping honorifics/degrees (MD/DO/RN…) so "Robert J Smith MD" and "Robert James Smith" block together.
  - `normalize_address` → USPS-canonical key (suite/unit folding, ZIP5) so "Ste 100 / Suite #100 / Street vs St" stop fragmenting the address signal — and **the address becomes a usable disambiguator**, which is precisely what name-only fuzzy matching lacks for the John-Doe problem.
- **`deterministic.py` (built):** union-find clustering on **exact, immutable keys** — NPI (checksum-validated), EIN/TIN, UEI, CAGE. This is the part the TPA underuses: **when an NPI or EIN is present on either side, you don't fuzzy-match at all — you join.** Their "occasional NPIs/EINs" become free, zero-false-positive anchors. Typed key namespaces (`NPI:…`, `CAGE:…`) prevent cross-identifier collisions.
- **`probabilistic.py` (documented stub — the planned home for the fuzzy stage):** the Fellegi-Sunter / Splink pass (and the Alper phased plan in `product-scope.md` "Research watch") that replaces a flat 90% string cutoff with **frequency-adjusted, multi-feature scoring** and a **banded** decision (auto-match / **review** / no-match). This is where the TPA's matching should live.

**Why this beats a 90% name cutoff specifically:**

| TPA pain today | Resolution-layer fix |
|---|---|
| "John Doe" matches the wrong John Doe | **Term-frequency weighting** (Fellegi-Sunter): agreement on a *rare* surname is strong evidence; agreement on "Smith"/"Doe" is weak. A common-name agreement no longer clears the bar on its own. |
| Variants fall under 90% and are missed | **Normalization + blocking** fold variants together *before* similarity, raising recall without lowering the threshold blindly. |
| Hard category gate vetoes true matches when the note classifier is null/wrong | Category becomes **one weighted feature among many** (name, address, NPI, EIN). A **null contributes neutral evidence, not a rejection**; a disagreement is down-weighted, not a veto. (Detailed in §4.) |
| One binary, no human-in-the-loop | **Three bands.** The ambiguous middle routes to review instead of being force-decided — precision-first, because a false merge *manufactures a fake ring*. |

### 3.2 NICB + custom BOLO → reference-graph watch lists

OKO's Layer 0 (`oko_ingest/sources/`) already ingests public bad-actor lists (LEIE, SAM, PECOS, NPPES) into snapshot-dated, provenance-tagged tables via the `BulkSource` → `SOURCE_REGISTRY` pattern. The **NICB feed and the custom BOLO list are two more sources** — register each as a `BulkSource` subclass (or, for the BOLO, a thin client-owned watch-list table) and they flow through the same normalize → resolve path. The TPA's watch lists stop being a flat string list and become **resolved nodes in a graph**, carryable as boolean flags (`bolo_listed`, `nicb_flagged`) exactly like `leie_excluded` / `sam_excluded` today (`oko_ingest/resolve/graph.py`).

This is also where their watch lists get **multiplied in value**: a direct hit on the BOLO is the easy case they already catch; the new signal is everything **one or two hops away** — entities sharing a suite-level address, an NPI, or a claim with a BOLO/NICB entity (see §3.4).

### 3.3 Authoritative category — stop depending on the finicky classifier

A subtle, high-leverage point. The note classifier's category/subcategory is noisy **because it's inferred from free text**. But **once an entity resolves to a reference record, its category comes from authoritative data**: NPPES `taxonomy_code` and `entity_type` (org vs person) already flow through `reference graph` construction (`resolve/graph.py`); attorneys/firms resolve against bar/registry data (the keyless-party scraping on OKO's roadmap). So:

> The note-extracted category should be treated as **weak corroboration, available before resolution**, and **superseded by the resolved entity's true taxonomy after resolution.** The brittle classifier stops being load-bearing.

This directly retires the "John Doe legal vs John Doe medical" failure: post-resolution you know which John Doe each is from NPI/taxonomy/address, not from a guess off the note text.

### 3.4 Graph-structural risk → the actual differentiator

Matching (score A) only tells you *who* the entity is. **Risk (score B)** comes from structure, and this is what no fuzzy-matcher can produce:

- Build a `HeteroData` graph (`oko/graph/builder.py`) over node types `entity`, `address`, `npi`, `claim` with edges `located_at`, `has_npi`, `associated_with`, `appears_on`/`files` (the schema already ships — `oko/graph/schema.py`).
- Score each entity by **proximity and structure** relative to bad actors (NICB/BOLO + LEIE/SAM): hops-to-nearest-flagged, shared-address entity density, NPI reuse, co-occurrence on claims, reassignment/association fan-in. These are exactly the planted patterns `oko/synthetic/generator.py` already models (shared-address rings, NPI reuse, feature anomalies).

Two delivery options, in increasing order of effort (and lift):

1. **XGBoost on graph-derived features (recommended first).** `product-scope.md` makes this a non-negotiable baseline gate, and it is **the most "efficient" answer to their efficiency ask**: hand-crafted graph features (hops-to-nearest-bad-actor, address density, fan-in) in a GBM that is **explainable nearly for free (SHAP)**, fast to train, easy to operate. For "very efficiently produce a risk score per entity," this is likely the right *first* deliverable.
2. **The GNN (`FraudScorer`), upside.** Self-supervised pretrain (DGI/GraphMAE) needs **zero labels** and yields a usable day-one **anomaly/risk ranking** (GraphMAE reconstruction error as an unsupervised outlier signal — free, since we pretrain anyway). As the TPA confirms/dispositions entities, the existing fine-tune path adds calibration and client-specific lift. Sell the GNN only once it demonstrates lift over the GBM (the baseline gate) — either outcome is a win.

---

## 4. The category problem, handled precisely

Because this is the TPA's sharpest pain, here is the exact treatment:

- **Never gate on category.** Replace the hard equality constraint with category as a **comparison feature** inside the Fellegi-Sunter score, with three states:
  - **Agree** (both present, same): positive evidence (modest — categories are coarse).
  - **Disagree** (both present, different): negative evidence, **down-weighted** because the note classifier is known-unreliable. It lowers the match probability; it does not zero it.
  - **Missing** (either side null): **neutral** (the "missing → neutral" rule, not "missing → reject"). This is the single change that recovers the matches their current pipeline silently drops.
- **Prefer resolved taxonomy over extracted category** (§3.3): once NPI/EIN/address resolve the entity, use the authoritative `entity_type`/`taxonomy_code`; the note category is only a tiebreaker when nothing else resolves.
- **Calibrate the weights from their own data.** Fellegi-Sunter `m`/`u` weights (or the Alper propagation thresholds) are *learned*, so the relative trust placed in name vs address vs category vs NPI is fit to the TPA's actual extraction quality, not guessed.

Net effect: a "John Doe, category=null" extracted mention can still match the right John Doe via **address + a rare-name signal**, and a "John Doe legal" vs "John Doe medical" pair is correctly *separated by address/NPI*, not by trusting a classifier that may be wrong.

---

## 5. Honest gaps — what isn't free

Two engineering realities to be upfront about:

1. **The scorer is claim-centric today.** `FraudScorer.target_node_type` is **hardcoded to `"claim"`** (`oko/models/scorer.py:50`), and labels/masks attach to the `claim` node type in the builder. The TPA wants the **`entity`** node type scored. Repointing the target node type is a **small, contained change** (parameterize the hardcoded target; attach labels/masks to `entity`) — but it is a change, not a config flip. The resolution layer (§3.1) and the GBM baseline (§3.4 option 1) need **none** of this and can ship first.
2. **The probabilistic resolution stage is a documented stub.** `resolve_probabilistic` raises `NotImplementedError` — by design, because it needs *real data to tune* (EM training, term-frequency adjustment, blocking-rule selection). The TPA's data is exactly what unblocks it. Expect a tuning loop, not a drop-in. The deterministic layer and normalizers are fully built and usable immediately.

Neither gap is on the critical path for an early, useful deliverable.

---

## 6. Recommended phased offer

Ordered by value-per-effort, each phase independently shippable:

- **Phase 0 — Deterministic anchoring (days).** Run the TPA's structured entities + note-extracted entities + NICB/BOLO through `normalize.py` + `deterministic.py`. Every present NPI/EIN becomes a zero-false-positive join. Immediate precision win, no ML, no tuning. *Deliverable: clean blocking keys + exact-match clusters + a coverage report (match rates, null rates by field).*
- **Phase 1 — Probabilistic matching that replaces fuzzy+hardcat (1–2 weeks).** Stand up the Fellegi-Sunter/Splink stage (or Alper Phase 0–1: semantic blocking + label propagation, no LLM) over name + address + NPI + EIN + **soft category**. Output **calibrated P(same entity)** in three bands. *This alone fixes both live failure modes (§1).*
- **Phase 2 — Graph-structural risk via GBM (2–3 weeks).** Build the reference graph (LEIE/SAM/NICB/BOLO + TPA entities), compute graph features, train XGBoost → **explainable per-entity risk score** with SHAP attributions. The "very efficient" risk score they asked for. *Deliverable: score B, separated from score A.*
- **Phase 3 — GNN upside (later, label-gated).** Pretrain (zero-label anomaly ranking) → fine-tune as dispositions accumulate. Ship only if it beats the GBM baseline.
- **Phase 4 — Two-head productization (optional).** If they later want both *risk* and *investigation-worthiness*, the dual-head pattern in `product-scope.md` (Req 2) applies unchanged.

**Privacy posture is a selling point, not an afterthought:** per `client-data-standard.md` §5.1, resolution + scoring run **in the TPA's environment**; the reference graph (incl. our public scrapes) ships *in*; their notes/claims **never egress**. NICB/BOLO are their own data and stay local.

---

## 7. One-paragraph answer for the TPA

> What you're doing — fuzzy-matching entity names against a watch list — is **entity resolution**, and it's the thing our engine is built around. We'd replace the brittle parts directly: first, **use your NPIs and EINs as exact joins** (no fuzzy matching needed when a real identifier is present); second, **normalize names and addresses** with our built-in canonicalizers so legal-suffix and abbreviation variants stop slipping under your 90% cutoff and addresses become a real disambiguator for common names; third, **make category a soft, optional signal instead of a hard gate** — a missing or wrong category from your note extractor will no longer veto a real match, and once an entity resolves we read its *true* category from authoritative provider/registry data rather than trusting the note classifier at all. That gives you a **calibrated match confidence with a human-review band** instead of one yes/no. Then, separately, we score **risk** from graph structure — proximity to your NICB/BOLO entities and to public bad-actor data through shared addresses, shared NPIs, and co-billing — starting with a fast, fully explainable model and adding the GNN only if it proves additional lift. All of it runs inside your environment; your notes never leave.

---

## 8. Follow-up: notes are the primary source, and the value is *around* the name

A sharper version of the problem, raised after the above. For this TPA, **notes are the primary data source right now**, and the entities in them rarely carry an NPI/EIN. What the notes *do* carry is **contextual signal wrapped around each name** — an email address, a location or "section," and the entity's **behaviors and actions** — and the TPA's pain is that they can **neither extract that context nor resolve on it**. They're stuck matching a bare name string.

This is the **keyless-party / dirty-ER case** that `product-scope.md` (Requirement 1, "keyless-party correction") already names as *close to the main event, not a residual edge case*, and it sits exactly on the design seam the sourcing doc calls out: an unresolved mention is **still scored from its own features, its note embedding, and whatever edges did resolve** (`data-sourcing-engine.md` §5.3, graceful degradation). So the architecture is already pointed at this; the question is which levers to pull.

### Three complementary tracks

**Track 1 — Use the context *without* extracting it into fields (note/context embeddings).** This is the biggest unlock for a notes-primary client and needs no structured extraction at all.
- The architecture stores `data[ntype].note_emb` on **every** node type (not just claims). Embed the **note span around each name** — the sentence/paragraph that includes the email, the location, the described behavior — into a 768-d vector and attach it to that **entity** node (the `entity_narrative` table in `client-data-standard.md` §3.8 is exactly this contract).
- That single vector then powers three things at once: **(a) semantic blocking** — Alper Phase 0: an ANN/KNN graph over embeddings finds candidate same-entity mentions by *contextual* similarity, so "J. Smith, ortho, downtown, jsmith@clinicx" lands next to its other mentions even when the **name string itself is degraded**; **(b) a risk feature** — the context feeds the GBM/GNN directly; **(c) similarity retrieval** — "find entities whose note-context looks like this known BOLO actor." The information they *can't* parse into columns is still fully usable as latent signal.

**Track 2 — Extract the *few* high-value structured signals and turn them into keys/features.** Not full NER — just the high-yield quasi-identifiers.
- **Email is the headline.** An email is a near-identifier — far more discriminating than a name and often the only quasi-key in a note. Add a typed `EMAIL:<normalized>` key to `deterministic.py` so an exact email match becomes a **strong anchor** — the keyless-party substitute for NPI/EIN. Caveat handled the same way as the John-Doe problem: **shared/role emails** (`frontdesk@`, `info@clinic.com`) are the email analog of a common name, so frequency-down-weight them — a unique personal email is a strong edge, a shared inbox is a weak one. **Phone numbers** behave identically; add as another typed key.
- **Location / "section"** → the existing address normalizer + `located_at` edges; even partial (city/state, or a facility/department "section") is a probabilistic feature, never a requirement.
- **Behaviors / actions** → the `entity_events` table (`client-data-standard.md` §3.7): a **dated per-entity timeline** (referrals, denials, address/ownership changes, billing-velocity events…) that feeds temporal/behavioral node features and event edges. This is precisely how "their actions" become structure — and the temporal-leakage rail (§6.1) applies (outcome events held out of features for prior-dated claims).

**Track 3 — Help with the extraction itself (the part they say they can't do): in-enclave LLM extraction + adjudication.** This is the real capability gap and the one posture shift.
- OKO's Alper Phase-2 design already pulls an LLM **into the resolution loop as the adjudicator of the Fellegi-Sunter gray band** (`product-scope.md` "Research watch"; `data-sourcing-engine.md` §3.4 stage 4). The natural extension for a notes-primary client: the **same in-enclave LLM also extracts** the contextual fields (email, role/category, location, described actions) from the note span **and adjudicates** same-vs-different-entity decisions *using that context* — i.e., it reads "the John Doe who emails from the law firm and keeps showing up referring to the same clinic" and resolves accordingly. That is exactly the reasoning the TPA cannot do today.
- **Non-negotiable rails** (`product-scope.md` Phase-2 adoption gates + `client-data-standard.md` §6): runs **inside the client enclave**, **never** ships client notes/PII to an external LLM; **every** extraction and pair-verdict is cached as an immutable, versioned, provenance-logged decision (model + prompt + verdict) so reruns reproduce and every match is auditable; **Category-A public actors** (providers, attorneys, firms) are resolved in the clear, while **Category-B claimant** context is pseudonymized/minimized (FCRA-adjacent, medical-history-sensitive).

### What needs to adjust (concrete)

| # | Change | Size | Notes |
|---|---|---|---|
| 1 | Add `email_key` / `phone_key` typed keys + normalizers to `oko_ingest/resolve/deterministic.py`; union on them | **Small** | Highest value-per-effort for keyless parties; mirrors the existing NPI/UEI/CAGE key pattern |
| 2 | Build the probabilistic stage (`probabilistic.py` stub → real): **semantic blocking (embeddings + ANN)** + Fellegi-Sunter over name/email/phone/address/**context-embedding** with term-frequency weighting + banding | **Medium** | The main net-new build; needs their data to tune (EM weights, thresholds) |
| 3 | Wire **entity-level** note/context embeddings: an entity-scoped vector connector + the shipped local embedder pointed at note spans | **Small–Med** | Architecture already supports `note_emb` per node type; this is plumbing + an embedder run, in-environment |
| 4 | `entity_events` ingestion + a behavioral/temporal feature extractor (velocity, recency, action-type counts) | **Medium** | Turns "actions" into node features under the leakage rail |
| 5 | *Optional* in-enclave LLM **extraction + adjudication** service | **Large / new scope** | Crosses the historical "client does extraction" line — see posture decision below; privacy/audit gates mandatory |
| 6 | (carryover from §5) repoint `FraudScorer.target_node_type` from `"claim"` to `"entity"` | **Small** | Needed for per-entity scoring regardless |

### The posture decision this surfaces (genuinely a product call)

OKO's stated division of labor is **"client extracts (including their own NER over notes), OKO resolves and scores"** (`client-data-standard.md` §1, §8; `product-scope.md` "Open decisions"). A notes-primary client **inverts** that: extraction is the bottleneck they're asking us to solve. Two honest paths:

- **(a) Hold posture — ship Tracks 1–2.** Note-context **embeddings** + **email/phone keys** + **entity_events** get most of the lift while asking the client only to surface a *handful* of fields (or just the note span to embed locally) — a far lighter ask than full NER, and squarely within current scope. **Recommended starting point.**
- **(b) Extend scope — Track 3.** OKO provides in-enclave LLM extraction/adjudication. Largest value for exactly their gap, but it is **new product surface** with hard privacy/audit obligations and a posture change. Worth doing if notes-primary clients are a target segment — but it's a deliberate decision, not a default.

Both are real; (a) is shippable now and de-risks (b). The choice of how far to move the extraction boundary is the open call.

### One-paragraph answer for the TPA (notes-primary)

> You don't need an NPI or EIN on every name to make notes work for you. First, we capture the **context around each name** — the email, the location, the behavior described — as an **embedding on that entity**, so even when your extractor can't parse those into fields, that context still drives matching (entities with similar context cluster together, even when the name string is messy) and feeds the risk score. Second, we promote the **highest-value identifiers you *can* get from a note — email and phone — into exact-match keys**, which for parties without an NPI are the strongest anchor available (we down-weight shared inboxes like `frontdesk@` the same way we down-weight common names). Third, the **behaviors and actions** in your notes become a **dated timeline per entity** that feeds temporal risk features. The matching becomes a calibrated confidence with a review band, not a 90% name cutoff. If you want us to go further and have the system **read the notes and pull that context out for you**, we can run an LLM-based extractor-and-adjudicator **inside your environment** — your notes never leave, and every decision it makes is logged and reproducible.
