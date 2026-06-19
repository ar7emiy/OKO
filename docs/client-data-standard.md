# OKO Client Data Standard — v1 (Medical Claims)

**Status:** Draft for review (June 2026) — spec only; not yet implemented (no connectors/validators built against it)
**Last updated:** 2026-06-19
**Companion docs:** [`product-scope.md`](./product-scope.md) (Req 5: why the standard is part of the product), [`client-onboarding-playbook.md`](./client-onboarding-playbook.md) (how a client conforms), [`data-sourcing-engine.md`](./data-sourcing-engine.md) (the reference graph this joins against).

This is the contract for what a client provides. It is a **highest-performance target**, not a lowest-common-denominator minimum: it lays out everything that optimizes model performance on the assumption that clients will build the processes — including **extracting structured data from their own unstructured notes and documents** — to meet it. The **tiers (§7) are a maturity ramp** toward this target, so a less-mature client still onboards at the tier they support today and grows. Resolution and scoring run **inside the client's environment** (on-prem/VPC, or a confidential-computing enclave) — raw data never egresses.

---

## 1. First principles

1. **The division of labor: client extracts and surfaces; OKO resolves and scores.** The client's job is to *surface* every relevant actor, relationship, event, and narrative as structured rows — **including standing up extraction processes (their own NER) to pull legal entities, parties, and events out of unstructured notes and documents.** OKO's job is to *resolve* those surfaced actors against the scraped reference graph and score the graph. The boundary is extraction (theirs) vs. resolution-against-reference-data + modeling (ours).
2. **Entity resolution is the product, not client homework.** Clients surface a messy mention (e.g. an attorney name string); OKO connects it to scraped fraud signal. Clients do **not** resolve entities, assign our keys, or clean their claim fields (amounts, codes). They DO extract, surface, and pseudonymize.
3. **Ask in priority order (§2.1).** "Whatever optimizes performance" is a *ranked* list, not a firehose — so client investment goes to the highest-yield data first (edges and surfacing before documents).
4. **Established vocabulary + a thin OKO profile — not a new standard.** We do **not** invent a vocabulary: every field anchors to the HIPAA-mandatory code systems (NPI, CPT/HCPCS, ICD-10-CM, POS, CARC/RARC, TIN) that 837/835 and FHIR already use. We **do** define a thin OKO *profile* — a flat-table selection of those fields — plus a small set of **extensions no claims standard has** (the parties/attorney table, `entity_events`, claimant pseudonymization, resolution refs), because no established standard models attorneys-as-parties or per-entity behavioral history, and those are our differentiator. This mirrors how FHIR CARIN BB is itself a profile on base FHIR. Discipline: anchor everything possible to established vocabulary, keep extensions additive (never redefine an existing concept), minimize the extension surface. Container is a flat table (Parquet/CSV); optional FHIR-EOB / 837 ingestion for clients further along the CMS-interoperability curve.
5. **Resolution runs where the data lives.** Reference snapshot + resolution engine + scorer deploy into the client environment. No live web calls at scoring time; web-scraping already happened in batch to build the snapshot.

### 1.1 What moves model performance (the ranking that orders client investment)

For a heterogeneous GNN fraud scorer, marginal value runs **top-down**:

1. **Entity surfacing + resolution keys** — no graph exists without surfaced, resolvable actors.
2. **Relationship edges** — the GNN's core power; especially keyless-party edges (attorney↔claim↔clinic).
3. **Labels** — scarce supervised signal (SIU outcomes, dated).
4. **Behavioral / temporal entity history** (`entity_events`) — fraud is temporal (billing velocity, procedure drift, time-clustering).
5. **Unstructured narrative embeddings per entity** (`entity_narrative`) — rich latent signal + agent evidence; noisier, diminishing without 1–3.
6. **Full source documents** — richest but highest extraction cost.

Clients build top-down; we never ask for #6 before #1–2 are solid.

## 2. The two entity categories (the load-bearing distinction)

| | **Category A — Public actors** | **Category B — Private individuals** |
|---|---|---|
| Examples | providers, attorneys, law firms, facilities, DME suppliers, employers, marketers | claimant / member (the insured person) |
| In the public world? | Yes — we scrape them (NPPES, bar/court/registries) | No |
| Handling | **Resolved** against the reference graph (deterministic on NPI/TIN; probabilistic on name+address) | **Pseudonymized** — client hashes to a stable key; never resolved externally |
| Purpose | latch the claim onto scraped fraud signal (the moat) | link a person's claims internally (ring detection) |
| Identity visible to OKO? | Yes (public actors, in the clear) | No (hash only) |

Pseudonymization (Category B) and entity resolution (Category A) apply to **disjoint sets** — there is no contradiction between them.

## 3. Tables

Required fields **bold**. `ref` columns are the client's *own local IDs* (any stable string) used to wire rows together; OKO maps them to graph nodes. Providers can be auto-derived from claim NPIs, so a separate provider master is enrichment, not required. The **parties table is the net-new ask** — it's where attorneys/firms enter.

### 3.1 `claims` (Tier 1)
| Field | Notes |
|---|---|
| **claim_id** | unique |
| **claimant_key** | Category B — client-generated stable pseudonymous hash (§6). Links claims by the same person. |
| **line_of_business** | enum: group_health, wc_medical, auto_pip, medpay |
| **service_date_start** | ISO date; service_date_end optional |
| **billed_amount**, paid_amount, allowed_amount | paid drives dollar-weighted metrics |
| **billing_provider_ref** | → `providers` (or inline NPI) |
| place_of_service | POS code system |
| claim_type | professional / institutional |

### 3.2 `claim_lines` (Tier 1, recommended)
| Field | Notes |
|---|---|
| **claim_id**, **line_number** | |
| **procedure_code** | CPT/HCPCS |
| diagnosis_code | ICD-10-CM (repeatable) |
| units, line_charge, line_paid | |
| rendering_provider_ref | → `providers` |

### 3.3 `providers` (Tier 1; Category A — resolved)
| Field | Notes |
|---|---|
| **provider_ref** | client local id |
| npi | deterministic join key when present |
| tin | entity join key when present |
| name, address fields | drive probabilistic resolution when NPI absent |
| taxonomy / specialty | enrichment |

### 3.4 `parties` (Tier 2; Category A — resolved) — the net-new ask
| Field | Notes |
|---|---|
| **party_ref** | client local id |
| **party_type** | enum: attorney, law_firm, facility, dme_supplier, employer, marketer, other |
| **name** | minimum viable input — resolution can run on name+address alone |
| identifier, identifier_type | optional: bar_number, tin, npi, etc. |
| address fields | improves match precision |

### 3.5 `claim_party_links` (Tier 2) — the edges
| Field | Notes |
|---|---|
| **claim_id**, **party_ref** | |
| **role** | enum: attorney_of_record, referring, servicing_facility, employer, supplier, marketer, other |

### 3.6 `labels` (optional at onboarding; required for pilot/fine-tune)
Two label targets, feeding the two scorer heads (product-scope Req 2): **fraud propensity** (confirmed outcomes) and **investigation-worthiness** (was-referred). Supplying both is ideal; either alone is usable.
| Field | Notes |
|---|---|
| **subject_ref** | claim_id or provider_ref |
| fraud_label | 1 confirmed fraud / 0 confirmed not / null unknown → trains the fraud head |
| referred_label | 1 was referred for investigation / 0 not → trains the referral head |
| disposition, disposition_date | SIU outcome + date (temporal-split discipline; `is_outcome` events held out of fraud-head features) |
| sample_weight | default 1.0; weak labels lower |

### 3.7 `entity_events` (Tier 2–3) — behavioral / action history ("actions of all types")
A dated timeline per entity — the client's *private* behavioral record, which the public reference graph cannot contain. Feeds temporal/behavioral node features and event edges.
| Field | Notes |
|---|---|
| **subject_ref** | the entity this event is about (provider_ref / party_ref / claim_id / claimant_key) |
| **event_type** | enum: claim_submitted, claim_denied, prior_referral, prior_investigation, license_action, sanction, address_change, ownership_change, … |
| **event_date** | **required** — every event is date-stamped (leakage rail, §6.1) |
| attributes | typed payload (amount, code, counterparty_ref, …) |
| **source** | provenance (claim system, SIU case, correspondence, …) |
| is_outcome | true for investigation/disposition events — held out of features for claims predating `event_date` (§6.1) |

### 3.8 `entity_narrative` (Tier 3) — unstructured per-entity text
Notes, SIU narratives, demand letters, correspondence **about an entity** (not only a claim). The architecture already supports note embeddings on *every* node type (`data[ntype].note_emb`), so this is natively ingestible.
| Field | Notes |
|---|---|
| **subject_ref** | claim_id / provider_ref / party_ref (Category-A actors preferred; claimant narrative minimized — §6) |
| narrative_text **or** narrative_embedding | embedded locally → 768-d vector; raw text never egresses |
| doc_type, doc_date | provenance + date (leakage rail applies) |

## 4. Code systems (the vocabulary anchor)

NPI (providers) · CPT/HCPCS (procedures) · ICD-10-CM (diagnoses) · CMS Place-of-Service codes · X12 CARC/RARC (adjustment/denial reasons) · TIN/EIN (entities). Using these means "paid amount" or "rendering provider" is unambiguous and already what the client's warehouse stores.

## 5. Entity resolution & join rules (OKO side, in-environment)

- **Providers / parties (Category A):** deterministic union on NPI/TIN where present; otherwise probabilistic resolution (Splink baseline; Alper phases) on normalized name+address against the reference graph. Precision-first thresholds — a false merge manufactures a fake ring, so the ambiguous band routes to review, not to a weak edge.
- **Addresses:** passed through the shipped deterministic normalizer → canonical keys matching reference `address` nodes.
- **Claimant (Category B):** the pseudonymous key links claims internally; **never** resolved against external data.
- **Unmatched actors → local nodes** with only the client's data. The graph still scores them; they simply carry no scraped context. Latch rate per actor type = our reference-graph coverage of that type (providers near-complete; attorneys/firms grow with Layer-0 scraping).

### 5.1 Where the connections get made (no raw data egress)
The "connect external dots with internal ones" happens **without the client sending us raw data**, two ways:
- **Default — ship the reference graph in.** The reference snapshot + resolution engine deploy into the client environment; their data resolves against our shipped public graph locally. This *inverts the flow* (our public data goes to them, not their private data to us) and adds ~no legal complexity.
- **v2 — privacy-preserving set intersection (PSI).** If shipping the whole reference graph in risks exposing our scraped asset (IP), the client hashes their entity keys locally and sends only tokens; we return only matched links, never raw data. Motivation is IP-protection, not privacy.

Note the data is **complementary, not a superset either way**: our public relational breadth (co-defendants, shared registrations/addresses, sanctions) exceeds what a carrier scrapes, but the carrier's private transactional behavior (who billed under whom in their book) is unscrapeable. The product fuses both.

## 6. Discipline rails on behavioral & narrative data

### 6.1 Temporal / leakage discipline (the biggest risk in ingesting history)
Every `entity_events` and `entity_narrative` row carries a date. An event flagged `is_outcome` (investigation, referral, disposition, sanction) **must be held out of features for any claim predating its `event_date`** — otherwise the model learns "this entity was investigated" ⇒ "this entity is fraud," which is label leakage, not signal. This is the same temporal-split discipline as enforcement weak labels (sourcing doc §4.3).

### 6.2 Privacy & pseudonymization
- Runs on client infra / enclave; raw claim, member, and narrative data never leaves their environment.
- **claimant_key** is a client-computed stable salted hash of member identity, applied *before* data enters OKO. OKO never receives member PII.
- **Behavioral/narrative history is rich for Category-A public actors** (providers, attorneys — defensible) and **minimized + gated for Category-B claimants** (full action narrative is medical-history-sensitive and FCRA-adjacent; capture only what a specific use case justifies).
- No SSN, no DOB, no biometrics ingested.
- Cross-client claimant linkage (same fraudster across carriers) is **out of scope v1** — needs a shared hashing scheme or privacy-preserving set intersection; noted as future.

## 7. Tiers & conformance

| Tier | Client provides | Product |
|---|---|---|
| **1 — Core** | claims, claim_lines, providers (+ labels for pilot) | provider-centric scoring |
| **2 — Parties + events** | + parties, claim_party_links, entity_events | ring detection + behavioral/temporal signal (the differentiator) |
| **3 — Narrative** | + entity_narrative (+ client-side NER feeding more parties/events) | richest latent signal + agent evidence |

Reaching Tier 2–3 generally requires the client to **build extraction processes** (their own NER on notes/documents) to surface parties and events structurally. The tiers are a maturity ramp: conformance is mechanical (the `validate` CLI checks schema + code systems; the coverage report — counts only, no records — reports NPI match %, address canonicalization %, party-resolution %, event/narrative coverage, label volume) and **assigns the achieved tier**. A client below Tier 2 onboards where they are and grows; they are not rejected.

## 8. Division of labor (the onboarding pitch)

| Step | Client | OKO (shipped, automated) |
|---|---|---|
| Extract | warehouse query to the table specs | spec + field dictionary |
| Surface actors | pull provider NPIs and **surface attorneys/parties + events — including NER over their own notes/documents** | — |
| Pseudonymize | hash member identity → `claimant_key` | hashing spec |
| Validate / normalize / embed | run the CLIs locally | `validate`, `normalize-addresses`, local embedder |
| **Resolve entities** | — | **resolution engine (the product), in-environment** |
| Coverage / tier | read the report | coverage report + tier assignment |

The client extracts and surfaces (incl. structured-from-unstructured); OKO resolves and scores. No client-side entity resolution, no key assignment, no data egress.

## 9. Open items for review

- Confirm `line_of_business` enum scope (group health + WC-medical + auto-PIP/med-pay) matches the target market.
- Parties enum completeness — are there actor types (interpreters, transportation, durable-goods brokers) worth first-classing in v1?
- Whether to ship the optional FHIR-EOB ingestion path in v1 or defer until a client requests it.
- Cross-client claimant linkage: confirm out-of-scope for v1.
