# TPA Data Request — Field-Level Specification

**Status:** Draft for TPA review (July 2026)
**Companion docs:** [`tpa-entity-risk-scoring.md`](./tpa-entity-risk-scoring.md) (the proposal this serves), [`client-data-standard.md`](./client-data-standard.md) (the general v1 standard this profiles and extends)

This is the complete, field-by-field specification of the data the TPA should provide for entity resolution and entity risk scoring. It profiles the general OKO client data standard for this TPA's situation: **notes-primary**, an existing **igraph** entity graph, **NICB + custom BOLO** watch lists, and a party universe that is **broader than medical providers** (attorneys, repair shops, witnesses, interpreters, etc.).

## 0. How to read this document

Every field carries a requirement level:

| Level | Meaning |
|---|---|
| **MUST** | Without it the pipeline cannot run (or cannot run honestly). |
| **SHOULD** | Materially improves resolution precision or risk-score quality; provide if it exists anywhere in your systems. |
| **MAY** | Optimizes further; worth providing when cheap. |

**Give us raw, not cleaned.** Do not pre-normalize names, addresses, phones, or emails — our normalizers are deterministic and we need the original strings as provenance. Do not deduplicate entities — resolution is our job, and your merge decisions (especially fuzzy-match ones) would bake in errors we can't see. The one transformation you *must* perform is claimant pseudonymization (§10).

**Nulls are fine; wrong is not.** Every non-MUST field may be null. A null contributes neutral evidence; a fabricated or guessed value poisons matching. If your extractor is unsure, leave it null.

### Minimum viable bundle (what unblocks Phase 0–1)

1. `parties` (§3) or the igraph export (§8) — the entities to score
2. `mentions` (§4) or `notes` access (§5) — where the entities live
3. `watchlists` (§7) — NICB + BOLO
4. `claims` (§1) — the spine the entities hang off
5. `outcomes` (§9) — required before any supervised fine-tune or pilot evaluation; optional to start

## 0.1 Global conventions (apply to every table)

| Convention | Rule |
|---|---|
| Container | Parquet preferred (CSV accepted), one row per record, UTF-8 |
| Dates | ISO-8601 (`YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SS`); **every event-like row is dated** (temporal-leakage rail) |
| IDs (`*_ref`, `*_id`) | Your own stable local identifiers, any string. **Stable across extracts** — the same real-world record keeps the same ID next month. We never ask you to assign our keys. |
| `extract_date` | Every table delivery is stamped with its as-of date (file name or column) |
| `source` column | SHOULD on every row: which system produced it (claims warehouse, note-NER, manual entry, igraph, …) |
| Text encoding | Send original strings; do not upper-case, trim, abbreviate, or expand |
| **Never send** | SSNs, dates of birth, member medical detail beyond claim-level features, biometrics, raw member identity (see §10), scanned PDFs/images (out of scope — see companion doc §11.5) |

---

## 1. `claims` — the claim spine

One row per claim.

| Field | Req | Notes |
|---|---|---|
| `claim_id` | **MUST** | Unique, stable |
| `claimant_key` | **MUST** | Pseudonymous hash of member identity (§10) — links one person's claims internally; never their real identity |
| `line_of_business` | **MUST** | e.g. `group_health`, `wc_medical`, `auto_pip`, `medpay` — tell us your enum and we map it |
| `service_date_start` | **MUST** | `service_date_end` MAY |
| `billed_amount` | **MUST** | `paid_amount` **SHOULD** (drives dollar-weighted metrics), `allowed_amount` MAY |
| `billing_provider_ref` | **SHOULD** | → `providers`; inline NPI accepted |
| `rendering_provider_ref`, `referring_provider_ref` | SHOULD | Where populated |
| `place_of_service` | SHOULD | POS code |
| `claim_type` | SHOULD | professional / institutional |
| `report_date` / `received_date` | SHOULD | When the claim entered your system (temporal features) |
| `claim_status` | MAY | open / closed / denied etc., with status date |

`claim_lines` (per-line procedure/diagnosis detail: `claim_id`, `line_number`, `procedure_code` CPT/HCPCS, `diagnosis_code` ICD-10-CM, `units`, `line_charge`, `line_paid`, `rendering_provider_ref`) — **SHOULD** as a separate table if your warehouse has it.

## 2. `providers` — NPI-bearing actors (your provider master)

One row per provider record *as your systems know it* — do not merge duplicates.

| Field | Req | Notes |
|---|---|---|
| `provider_ref` | **MUST** | Your local ID |
| `npi` | **SHOULD** | The deterministic anchor where present; leave null where absent |
| `tin` / `ein` | **SHOULD** | Org identity key |
| `provider_name` | **MUST** | Raw string; split fields (below) preferred where you have them |
| `first_name`, `last_name`, `middle_name` | SHOULD | For individual providers — our person normalizer takes split fields |
| `org_name` | SHOULD | For organizational providers |
| `address_line1`, `address_line2`, `city`, `state`, `zip` | **SHOULD** | Raw components, un-normalized; multiple addresses per provider welcome (one row per address, or an addresses side-table) |
| `taxonomy_code` / `specialty` | SHOULD | |
| `email`, `phone` | SHOULD | Quasi-identity keys — high resolution value |
| `first_seen_date`, `last_seen_date` | MAY | In your book |

## 3. `parties` — the broader actor universe (the net-new ask)

One row per party record: **attorneys, law firms, repair/body shops, towing, interpreters, witnesses, employers, facilities, DME suppliers, marketers, medical providers appearing outside the provider master** — every actor type your extraction or adjusters track. Include records even when only a name is known.

| Field | Req | Notes |
|---|---|---|
| `party_ref` | **MUST** | Your local ID — if the party lives in your igraph, use the igraph vertex ID so scores map back (§8) |
| `party_type` | **MUST** | Your taxonomy is fine; we map. Include `witness` explicitly — witnesses get private-individual handling (§10) |
| `party_subtype` | SHOULD | Your extractor's subcategory (e.g. Cairo taxonomy); **nulls fine** — this is corroboration, never a gate |
| `name` | **MUST** | Raw surface string as recorded |
| `first_name`, `last_name`, `middle_name` | SHOULD | Persons, where split |
| `org_name` | SHOULD | Organizations, where known |
| `is_person` / `is_org` | SHOULD | Even a guess helps blocking; null fine |
| `ein` / `tin` | **SHOULD** | Identity key — same EIN = same entity |
| `npi` | SHOULD | Some parties (facilities, DME) carry one |
| `bar_number` + `bar_state` | **SHOULD** | Attorney identity key (state-scoped) |
| `license_number` + `license_issuer` | **SHOULD** | Repair/contractor/adjuster/interpreter licenses — issuer-scoped identity key |
| `email` | **SHOULD** | Near-identity key; the single highest-value field extractable from notes |
| `phone` | **SHOULD** | Same |
| `address_line1/2`, `city`, `state`, `zip` | **SHOULD** | Raw; the main disambiguator for common names |
| `employer_or_firm` | MAY | Free text ("associate at Ikhilov Law Group") — feeds context embedding |
| `first_seen_date`, `last_seen_date` | SHOULD | Temporal features |
| `source` | **SHOULD** | structured-system vs note-extraction vs manual |

### 3.1 `claim_party_links` — the edges

One row per (claim, party, role) association. **This is where ring structure comes from — the highest-value table after the parties themselves.**

| Field | Req | Notes |
|---|---|---|
| `claim_id`, `party_ref` | **MUST** | |
| `role` | **MUST** | attorney_of_record, referring, servicing_facility, repair_shop, towing, interpreter, witness, employer, supplier, marketer, other — your enum, we map |
| `link_date` | **SHOULD** | When the association was established/observed |
| `link_source` | SHOULD | structured / note-extracted / manual |
| `confidence` | MAY | If your extractor scores its own links |
| `case_number` | **SHOULD** | Where a legal case connects parties. We use case numbers as **association evidence only** (co-occurrence edges), never to merge identities — so send them freely, even messy |

## 4. `mentions` — your note-extraction output (notes-primary core)

One row per **entity mention in a note**: the raw output of your NER pipeline, *before* any watch-list matching. This is the table your current fuzzy-match process consumes — give us its input, not its output.

| Field | Req | Notes |
|---|---|---|
| `mention_id` | **MUST** | Unique |
| `note_id` | **MUST** | → `notes` (§5) |
| `claim_id` | **MUST** | The claim the note belongs to |
| `surface_text` | **MUST** | The name exactly as it appears in the note |
| `party_ref` | **SHOULD** | Your igraph vertex, if your pipeline already links mention → entity; null fine |
| `char_start`, `char_end` | **SHOULD** | Span offsets in the note text — enables span-level citations and context-window embedding |
| `context_snippet` | SHOULD (if no offsets) | ±1–2 sentences around the mention — the fallback if offsets are unavailable |
| `extracted_category` | SHOULD | Your legal/medical/etc. classification — **nulls expected and fine** |
| `extracted_subcategory` | MAY | Same |
| `extracted_email`, `extracted_phone`, `extracted_address` | **SHOULD** | Whenever your extractor caught them; null otherwise |
| `extraction_date`, `extractor_version` | SHOULD | Provenance |

## 5. `notes` — the notes themselves

Raw note text (or governed access to it) is required for context embeddings and citable evidence; the mentions table alone is not enough.

| Field | Req | Notes |
|---|---|---|
| `note_id` | **MUST** | Unique, stable |
| `claim_id` | **MUST** | |
| `note_text` | **MUST** (one of the three delivery options below) | Full text, unredacted except member PII per §10 |
| `note_date` | **MUST** | Authoring date — temporal-leakage rail applies |
| `author_role` | SHOULD | adjuster / SIU / nurse-reviewer / system |
| `note_type` | MAY | Your taxonomy |

**Delivery options, in preference order:**

1. **Raw text table** (Parquet) — we embed locally with our pinned model. Simplest and best.
2. **Azure AI Search index access** — read credentials + index schema/field mapping. We build a connector against it. If the index stores vectors, tell us the **embedding model + version** used; either we adopt it as the pinned model on both sides or we ignore the stored vectors and pull raw text.
3. **Pre-computed embeddings** (768-d, one per note or per mention-context) — only with the model name + version pinned and unchanged across deliveries.

## 6. `entity_events` — behavioral / action history

One row per dated event about an entity. This is how "their behaviors and actions" become temporal risk features.

| Field | Req | Notes |
|---|---|---|
| `subject_ref` | **MUST** | party_ref / provider_ref / claim_id / claimant_key |
| `event_type` | **MUST** | claim_submitted, claim_denied, prior_referral, prior_investigation, license_action, address_change, ownership_change, representation_change, … — your enum, we map |
| `event_date` | **MUST** | Non-negotiable — undated events are unusable under the leakage rail |
| `attributes` | SHOULD | Typed payload (amount, code, counterparty_ref, …) |
| `source` | **SHOULD** | claim system / SIU case / correspondence / note-extraction |
| `is_outcome` | **MUST where applicable** | `true` for investigation/referral/disposition events — these are held out of features for claims predating the event |

## 7. `watchlists` — NICB + custom BOLO

One row per watch-list entry, **with dates**. An entity's presence on a list is only honest signal for claims *after* it was listed.

| Field | Req | Notes |
|---|---|---|
| `watchlist_entry_id` | **MUST** | Stable |
| `list_name` | **MUST** | `nicb` / `bolo` / others |
| `name` | **MUST** | As listed; split person/org fields SHOULD where available |
| `category` / `entity_type` | **SHOULD** | The list's own classification — used as soft evidence, never a hard gate |
| `ein`, `npi`, `bar_number`, `license_number`, `email`, `phone` | **SHOULD** | Any identifier the list carries — each one converts fuzzy matching into an exact join |
| `address_line1/2`, `city`, `state`, `zip` | **SHOULD** | |
| `listed_date` | **MUST** | Temporal rail |
| `removed_date`, `status` | **SHOULD** | Delistings matter |
| `reason` / `source_detail` | SHOULD | Why listed — feeds evidence narration |
| Refresh cadence | — | Tell us how often each list updates; we snapshot every delivery |

## 8. igraph export — your existing entity graph

Trivial to produce (`get_vertex_dataframe()` / `get_edge_dataframe()` → Parquet). This can *substitute* for §3 if your igraph is the system of record for parties.

**Vertices:** `vertex_id` (**MUST** — becomes/matches `party_ref`), all attributes you store (type, names, identifiers, addresses — same fields and levels as §3).

**Edges:** `src_id`, `dst_id` (**MUST**), `edge_type` (**MUST**), `created_date` (SHOULD), `created_by` (**SHOULD** — `fuzzy_match` / `manual` / `system_join`; critical, see below), `confidence` (SHOULD), `claim_id`/`case_number` where the edge derives from one (SHOULD).

**The one declaration we need from your team (MUST, one page of prose is fine):** for each `edge_type`, does it assert **identity** ("these two vertices are the same real-world entity") or **association** ("these two entities are related")? Identity edges created by your ≥90% fuzzy matcher are ingested as *evidence with provenance*, not as ground truth — we re-verify them, which is how your existing false merges get caught instead of inherited. Association edges load directly.

**What you get back:** a score + crosswalk table keyed to your `vertex_id`s (`vertex_id → canonical entity_id → matched reference/watchlist records with provenance → risk score`), loadable straight into your igraph as vertex attributes.

## 9. `outcomes` — ground truth for fine-tuning and the pilot

| Field | Req | Notes |
|---|---|---|
| `subject_ref` | **MUST** | claim_id, provider_ref, or party_ref |
| `disposition` | **MUST** | Mappable to: fraud-confirmed / fraud-suspected / cleared / not-investigated |
| `disposition_date` | **MUST** | Temporal split discipline |
| `referral_date` | **SHOULD** | Trains the investigation-worthiness head separately from the fraud head |
| `investigator` / team | MAY | Inter-reviewer agreement tracking |
| `recovery_amount` | MAY | Dollar-weighted evaluation |

Historical depth: **as far back as you have** — ≥ 24 months strongly preferred; ≥ 300 confirmed outcomes enables supervised fine-tuning (below that, we run rank-ordering from weak/structural signal and say so honestly).

## 10. Pseudonymization & privacy rules (your side, before delivery)

- **Claimants/members and any private individual** (including **witnesses**): replace identity with a stable salted hash (`claimant_key`, `witness_key`). Same person → same key, forever. We never receive the salt. These keys link records *internally only* — never resolved against external data. Witness *linkage* value (the repeat-witness signal) survives pseudonymization completely.
- **Public/professional actors** (providers, attorneys, firms, shops, facilities, employers-as-businesses): send in the clear — resolving them against public reference data is the point.
- **In note text:** member names/identifiers should be masked or replaced with the pseudonymous key if your tooling supports it; professional actors stay in the clear. If masking notes is impractical, say so — deployment is inside your environment either way, and we'll agree the boundary explicitly.
- Never send: SSN, DOB, biometrics, member medical narrative beyond what a claim already carries.

## 11. Quality bar ("current and high quality," made concrete)

| Expectation | Concrete rule |
|---|---|
| Currency | Each table stamped with `extract_date`; watch lists no older than their refresh cadence; igraph export from the same week as the mentions/notes extract |
| ID stability | Same `*_ref` for the same record across deliveries — this is the single most important quality property |
| Fill-rate honesty | A short per-table fill-rate summary (% non-null per column) with each delivery; we gate expectations on it rather than discovering gaps mid-pipeline |
| No pre-cleaning | Raw strings, undeduplicated records, original casing (see §0) |
| Dates | Valid ISO everywhere; undated `entity_events`/`watchlist` rows will be dropped, not guessed |
| Encoding | UTF-8; flag any system exporting cp1252/Latin-1 so we handle it deliberately |
| Deltas | After the first full delivery, incremental extracts (new/changed rows since last `extract_date`) are preferred and match our incremental-resolution design |

## 12. Priority order (if you can't do everything at once)

1. `parties` **or** igraph export + edge-semantics declaration (§3/§8)
2. `mentions` + `notes` access (§4/§5) — the notes-primary core
3. `watchlists` with dates (§7)
4. `claims` (+ `claim_party_links` if not covered by igraph edges) (§1/§3.1)
5. `outcomes` (§9) — before any pilot
6. `entity_events` (§6)
7. `providers` master, `claim_lines` (§2/§1)
8. Future scope, explicitly parked: Markdown documents / ops-reviewed structured extractions from documents — these will enter through the same tables above (`entity_narrative`-style rows, `parties`, `entity_events`) when ready; no new format needed.
