# OKO Client Data Standard — v1 (Medical Claims)

**Status:** Draft for review (June 2026)
**Companion docs:** [`product-scope.md`](./product-scope.md) (Req 5: why the standard is part of the product), [`client-onboarding-playbook.md`](./client-onboarding-playbook.md) (how a client conforms), [`data-sourcing-engine.md`](./data-sourcing-engine.md) (the reference graph this joins against).

This is the contract for what a client provides. **It is not a requirement that their data be pre-cleaned or pre-keyed.** The client brings what they have; OKO's pipeline resolves entities against the reference graph **inside the client's environment** (on-prem/VPC, or a confidential-computing enclave) — raw data never egresses. The standard defines the *shape* of the extract, not a data-quality bar the client must hit alone.

---

## 1. First principles

1. **Entity resolution is the product, not client homework.** Clients have incomplete, messy data on the actors in a claim (especially attorneys/firms — often just a name). Connecting those messy mentions to our scraped reference graph is the core value. The client surfaces actors; **OKO resolves them.**
2. **What the client does NOT have to do:** clean their claim fields (amounts, codes), resolve entities, or assign our keys. What they DO: pull a flat extract from the warehouse they already have, and *surface* actors as structured rows.
3. **Vocabulary over container.** Fields are anchored to the HIPAA-mandatory code systems (NPI, CPT/HCPCS, ICD-10-CM, POS, CARC/RARC, TIN) that every payer already stores. The container is a flat table (Parquet/CSV) pulled by a warehouse query — cheapest and most universal. Optional FHIR-EOB / clearinghouse-837 ingestion paths exist for clients further along the CMS-interoperability curve.
4. **Resolution runs where the data lives.** The reference snapshot + resolution engine + scorer deploy into the client environment. No live web calls at scoring time; the web-scraping already happened in batch to build the snapshot.

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
| Field | Notes |
|---|---|
| **subject_ref** | claim_id or provider_ref |
| **label** | 1 fraud / 0 not / null unlabeled |
| disposition, disposition_date | SIU outcome + date (temporal-split discipline) |
| sample_weight | default 1.0; weak labels lower |

### 3.7 `notes` (Tier 3, optional)
| Field | Notes |
|---|---|
| **claim_id** | |
| note_text **or** note_embedding | raw text embedded locally → 768-d vector; raw text never egresses. Tier-3 NER may surface additional `parties` rows. |

## 4. Code systems (the vocabulary anchor)

NPI (providers) · CPT/HCPCS (procedures) · ICD-10-CM (diagnoses) · CMS Place-of-Service codes · X12 CARC/RARC (adjustment/denial reasons) · TIN/EIN (entities). Using these means "paid amount" or "rendering provider" is unambiguous and already what the client's warehouse stores.

## 5. Entity resolution & join rules (OKO side, in-environment)

- **Providers / parties (Category A):** deterministic union on NPI/TIN where present; otherwise probabilistic resolution (Splink baseline; Alper phases) on normalized name+address against the reference graph. Precision-first thresholds — a false merge manufactures a fake ring, so the ambiguous band routes to review, not to a weak edge.
- **Addresses:** passed through the shipped deterministic normalizer → canonical keys matching reference `address` nodes.
- **Claimant (Category B):** the pseudonymous key links claims internally; **never** resolved against external data.
- **Unmatched actors → local nodes** with only the client's data. The graph still scores them; they simply carry no scraped context. Latch rate per actor type = our reference-graph coverage of that type (providers near-complete; attorneys/firms grow with Layer-0 scraping).

## 6. Privacy & pseudonymization

- Runs on client infra / enclave; raw claim and member data never leaves their environment.
- **claimant_key** is computed by the client (stable salted hash of member identity) *before* data enters OKO. OKO never receives member PII.
- No SSN, no DOB, no biometrics ingested.
- Category-A resolution operates on business/licensed-professional names and addresses (low sensitivity), not patient data.
- Cross-client claimant linkage (same fraudster across carriers) is **out of scope v1** — it would require a shared hashing scheme or privacy-preserving set intersection; noted as future.

## 7. Tiers & conformance

| Tier | Client provides | Product |
|---|---|---|
| **1 — Core** | claims, claim_lines, providers (+ labels for pilot) | provider-centric scoring |
| **2 — Parties** | + parties, claim_party_links | ring detection (the differentiator) |
| **3 — Narrative** | + notes/embeddings | richest evidence; Tier-3 NER may surface more parties |

Conformance is mechanical: the `validate` CLI checks schema + code systems; the coverage report (counts only, no records) reports NPI match %, address canonicalization %, party-resolution %, label volume — and **assigns the achieved tier**. A client below Tier 2 onboards at the tier they support and grows; they are not rejected.

## 8. Division of labor (the onboarding pitch)

| Step | Client | OKO (shipped, automated) |
|---|---|---|
| Extract | warehouse query to the table specs | spec + field dictionary |
| Surface actors | pull provider NPIs (mostly already in lines) and **attorney/party names into the parties table** | — |
| Pseudonymize | hash member identity → `claimant_key` | hashing spec |
| Validate / normalize / embed | run the CLIs locally | `validate`, `normalize-addresses`, local embedder |
| **Resolve entities** | — | **resolution engine (the product), in-environment** |
| Coverage / tier | read the report | coverage report + tier assignment |

The client surfaces; OKO resolves and scores. No client-side data cleaning, no key assignment, no data egress.

## 9. Open items for review

- Confirm `line_of_business` enum scope (group health + WC-medical + auto-PIP/med-pay) matches the target market.
- Parties enum completeness — are there actor types (interpreters, transportation, durable-goods brokers) worth first-classing in v1?
- Whether to ship the optional FHIR-EOB ingestion path in v1 or defer until a client requests it.
- Cross-client claimant linkage: confirm out-of-scope for v1.
