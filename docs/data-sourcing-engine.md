# OKO Data Sourcing Engine — Requirements, Research, and Design

**Status:** Proposal (research complete, implementation not started)
**Companion doc:** [`product-scope.md`](./product-scope.md) — overall product scope, north star, and roadmap (extends §6 of this doc with M4b–M8).
**Scope:** Real-world entity data acquisition for the OKO fraud-scoring graph — data requirements criteria, source catalog, scraping/ingestion methods and stack, synthetic-overlay strategy, and the user data-loading path.

This document is the design for the layer that sits *upstream* of the existing connector ABCs (`oko/connectors/base.py`). Nothing here changes the model or training pipeline: the sourcing engine's only contract is to produce data that the four connectors can serve to `HeteroGraphBuilder`.

> Research provenance: compiled June 2026 from five parallel research passes (government provider sources; corporate/address/legal-record sources; scraping legality; entity resolution tooling; ingestion stack). Citations inline. Several official .gov pages 403-block automated fetches, so a few details (flagged inline) were verified only via search snapshots of official pages — re-verify before building against them.

---

## 1. Data requirements criteria

A source is admitted into the OKO ingestion catalog only if it passes all seven gates:

| # | Criterion | Requirement |
|---|---|---|
| 1 | **Graph mappability** | Must feed at least one of the four node types (`claim`, `entity`, `address`, `npi`) or a schema edge type. Sources that produce only unlinkable aggregates are rejected. |
| 2 | **Linkage key** | Must carry at least one deterministic key (NPI, EIN, UEI/CAGE, CCN, state registration number, normalized address) **or** enough fields (name + address + state) for probabilistic matching at measured precision ≥ 0.95 against the reference graph. |
| 3 | **Licensing** | Public domain, permissive, or commercially licensed. Hard rejections: share-alike terms (e.g., OpenCorporates free tier), ToS that prohibit database building (e.g., USPS Web Tools), per-source-unauditable licenses (parts of OpenAddresses). |
| 4 | **Access method** | Preference order: **bulk file > official API > scraping**. Scrape-only sources are admitted only when no bulk/API path exists and the scraping rules of engagement (§3.2) can be honored. |
| 5 | **Freshness** | Documented update cadence. Sanctions/exclusion sources (label-bearing) must refresh ≤ monthly; feature sources ≤ quarterly. Every record carries `source`, `snapshot_date`, and a license tag in staging. |
| 6 | **Quality floor** | Known error modes documented before use (e.g., NPPES self-reported fields with a historical ~48% record-inaccuracy finding, [HHS-OIG 2013](https://opedge.com/news_2013-06-07_02/); registered-agent address pollution in SoS data). Sources with undocumentable provenance are rejected. |
| 7 | **Privacy/compliance** | No SSN/DOB ingestion. No biometrics. No DMV data outside licensed DPPA channels (18 U.S.C. §2721(b)(6) permits insurer antifraud use — [Cornell LII](https://www.law.cornell.edu/uscode/text/18/2721)). Output framing: investigative leads for SME review, never automated adverse-action inputs (the FCRA line — see §3.3). |

### Per-node-type minimum data contract

These mirror the connector return shapes the builder already consumes (`fetch_nodes` → `node_id` + numeric attribute columns; `fetch_edges` → `src_id`/`dst_id`):

| Node type | Required | Desired features from sourced data |
|---|---|---|
| `npi` | NPI (10-digit, checksum-valid), enumeration type (1/2) | taxonomy, enumeration/deactivation dates, exclusion flags (LEIE/SAM), enrollment churn (PECOS revalidation), utilization stats (CMS Physician & Other Practitioners), Open Payments totals |
| `entity` | resolved canonical entity id, type (person/org) | legal name, status, incorporation age, officer count, registration state count, sanction flags, `same_as` provenance |
| `address` | canonical address key (ZIP+4/delivery-point or normalized tuple) | geocode, address type (residential/commercial/CMRA/registered-agent), entity density at address |
| `claim` | claim id, claim features, NPI + entity + address references | (claims are client-supplied or synthetic — never scraped) |
| labels | `0 / 1 / NaN` per claim, `sample_weight` | SME decisions (weight 1.0) ≫ exclusion-derived weak labels (weight ≪ 1.0, see §4.3) |

---

## 2. Source catalog

### Tier 1 — free, bulk, deterministic keys (build first)

| Source | Access | Cadence | Key / volume | Feeds |
|---|---|---|---|---|
| **NPPES NPI registry** | Free bulk CSV: monthly full replacement + weekly incrementals + deactivation file ([download.cms.gov](https://download.cms.gov/nppes/NPI_Files.html)); lookup API capped at 1,200 records/query — not a bulk path | Monthly + weekly | NPI; ~8M records, >8 GB uncompressed, 300+ cols. **V2 file format only since 2026-03-03** | `npi` nodes, `entity` (authorized officials, org subparts), `address`, `(entity, has_npi, npi)` |
| **OIG LEIE** | Free full CSV + monthly supplements, no API ([oig.hhs.gov](https://oig.hhs.gov/exclusions/leie-database-supplement-downloads/)) | Monthly (by the 10th) | NPI (sparse, post-2008 only), name/DOB/address; ~70–80K exclusions | weak labels, `npi`/`entity` sanction features |
| **SAM.gov exclusions** | Free API (key required; ~1K req/day non-federal) + public V2 extracts: monthly full + daily deltas ([open.gsa.gov](https://open.gsa.gov/api/exclusions-api/)) | Daily deltas | UEI/CAGE, name/address (no NPI/TIN in public tier) | `entity` sanction features, weak labels |
| **PECOS public enrollment** | Free bulk on data.cms.gov, incl. **reassignment-of-benefits sub-file** ([data.cms.gov](https://data.cms.gov/provider-characteristics/medicare-provider-supplier-enrollment/medicare-fee-for-service-public-provider-enrollment)) | Quarterly | enrollment ID + NPI | **edges**: who bills under whom; facility-ownership companion files → `(entity, associated_with, entity)` |
| **CMS Physician & Other Practitioners** | Free bulk/API on data.cms.gov (no key; 5K rows/req API, full CSV) | Annual (~2-yr lag) | NPI; ~10M rows/yr | `npi` utilization features (≤10-beneficiary rows suppressed; FFS only) |
| **CMS Provider of Services** | Free bulk, data.cms.gov | Quarterly | **CCN** (not NPI — lossy crosswalk) | facility `entity` nodes/features |
| **Open Payments** | Free bulk/API ([openpaymentsdata.cms.gov](https://openpaymentsdata.cms.gov/about/api)) | Annual (June), Jan refresh | NPI since PY2021; ~15M general-payment rows/yr | `npi`/`entity` payment-relationship features |
| **OFAC SDN / Consolidated** | Free bulk XML/CSV ([Sanctions List Service](https://ofac.treasury.gov/sanctions-list-service)) | Irregular, ~weekly | name/alias/address only | `entity` sanction features |
| **FL Sunbiz** | Free bulk via public SFTP (`sftp.floridados.gov`): daily filings + quarterly snapshots ([dos.fl.gov](https://dos.fl.gov/sunbiz/other-services/data-downloads/)) | Daily + quarterly | registration #, FEI/EIN (self-reported), officers, registered agent | `entity`, `address`, officer edges — best-in-class state registry |
| **NY / OH registries** | Free bulk (data.ny.gov Socrata; OH monthly files) — *dataset URLs to verify at build time* | Monthly | registration # | `entity`, `address` |
| **DOT National Address Database** | Free public-domain bulk GIS/text ([transportation.gov](https://www.transportation.gov/gis/national-address-database)) | Recurring compiles | address point; ~50–80M+, **state-voluntary coverage gaps** | canonical `address` backbone |
| **CourtListener / RECAP** | Free API + quarterly bulk dumps ([courtlistener.com](https://www.courtlistener.com/help/api/bulk-data/)) | Quarterly bulk | party names (free text) | `entity` litigation features, weak labels (coverage biased to user-purchased PACER docs) |
| **HHS-OIG MFCU annual reports** | Free Excel downloads ([oig.hhs.gov](https://oig.hhs.gov/fraud/medicaid-fraud-control-units-mfcu/)) | Annual | state-level aggregates (person-level outcomes flow into LEIE) | context features only |

### Tier 2 — paid, high-leverage (budget items, not blockers)

| Source | Why / cost shape |
|---|---|
| **OpenCorporates Enterprise** | Only practical 50-state entity layer (~230M companies, ~380M officers). Free tier is share-alike — **incompatible with a closed product**; paid removes it. Third-party pricing cites £2,250–£12,000/yr tiers (unverified — [licence](https://opencorporates.com/legal/licence)). Defers the 50-state scraping problem entirely. |
| **Geocodio** | Address validation with **permissive storage rights** (2,500 free/day then ~$1/1K — [pricing](https://www.geocod.io/pricing)). Preferred over Smarty (rooftop-geocode storage restrictions) and USPS (ToS prohibits address-database building; legacy Web Tools retired Jan 2026). |
| **Regrid parcels** | ~160M parcels; enables residential-address-billed-as-clinic detection. |
| **PACER (targeted)** | $0.10/page capped $3/doc, waived under $30/quarter — for targeted case pulls via RECAP Fetch, not bulk. |

### Tier 3 — scrape-only (admitted under §3.2 rules)

| Source | Notes |
|---|---|
| **HHS-OIG enforcement actions + CIA list** | HTML + RSS only ([oig.hhs.gov/fraud/enforcement](https://oig.hhs.gov/fraud/enforcement/)). NER required to extract names → weak labels. |
| **DOJ healthcare-fraud press releases** | HTML only; annual takedown pages (e.g., [2025: 324 defendants, $14.6B](https://www.justice.gov/opa/pr/national-health-care-fraud-takedown-results-324-defendants-charged-connection-over-146)). NER → weak labels. |
| **State SoS HTML search (the long tail)** | Most states: free single-record search, no bulk. **Delaware is effectively opaque** (pay-per-lookup, no officer disclosure). Strategy: don't crawl 47 registries — use OpenCorporates for breadth and scrape only states with material claim volume, on demand per resolved entity. |
| **State Medicaid exclusion lists** | ~40 states publish their own lists (LEIE is not a superset); formats vary from CSV to HTML. |

**Out of scope / rejected:** USPS APIs as a canonical address layer (ToS §3 gate), residential proxies (ethics/botnet sourcing — [Krebs](https://krebsonsecurity.com/2025/10/aisuru-botnet-shifts-from-ddos-to-residential-proxies/)), any source requiring login-gated scraping, DMV data outside licensed channels, biometrics.

---

## 3. Methods

### 3.1 Bulk vs API vs scrape — decision framework

**Order of preference: bulk download > official API > scraping.** Bulk files have the best legal posture (explicit authorization), no rate limits, and fit graph rebuilds (full snapshots, versionable, deterministic). APIs add structure and change feeds but form binding clickwrap contracts — read redistribution/retention clauses before keying up. Scraping is the last resort, and for this domain it is mostly unnecessary: nearly every Tier 1 source publishes bulk files precisely so people don't scrape them.

### 3.2 Scraping rules of engagement (legal posture, June 2026)

Settled enough to build on:
- Scraping **publicly accessible, no-login** pages is very likely not a CFAA violation (*Van Buren* 2021 "gates-up-or-down" test; *hiQ v. LinkedIn* 9th Cir. 2022 — [opinion](https://cdn.ca9.uscourts.gov/datastore/opinions/2022/04/18/17-16783.pdf)). hiQ's eventual consent-judgment loss turned on *logged-in* scraping with fake accounts — which we never do.
- **Logged-off scraping isn't ToS "use"** even for an account holder (*Meta v. Bright Data*, N.D. Cal. 2024 — [analysis](https://www.fbm.com/publications/major-decision-affects-law-of-scraping-and-online-data-collection-meta-platforms-v-bright-data/)). Operational rule: never create accounts or click through ToS on properties we scrape.
- Government registries are the lowest-risk target: no ToS contract typically forms, CCPA-style laws exclude government-record data ([CCPA publicly-available exclusion](https://www.truevault.com/learn/what-is-publicly-available-information-under-the-ccpa)), and FOIA/state public-records acts are the formal fallback.

Open questions to track: trespass-to-chattels scope for "sophisticated" evasion (*X Corp. v. Bright Data* trial, 2026) — which is why **we never evade blocks**.

Engine-enforced politeness (not optional, encoded in the scraper base class):
1. Honest `User-Agent` with contact email (`OKO-ingest/<ver> (+mailto:...)`).
2. Respect robots.txt and `Crawl-delay`; default ≤ 1 req/s per host; back off on 429/503; off-peak scheduling.
3. No block evasion, no fingerprint spoofing for .gov sources, no login-gated content, no biometrics.
4. Conditional requests (ETag/Last-Modified) so re-crawls are cheap for the host.

### 3.3 The FCRA guardrail (product-shaping, not just legal hygiene)

Assembling consumer information for third parties for **insurance eligibility** decisions makes you a Consumer Reporting Agency, with accuracy/dispute/permissible-purpose obligations. Fraud *detection* feeding an SME investigator queue is generally outside FCRA; scores that **deny, price, or underwrite** are inside it. OKO's Layer-3 framing (ranked queue + SME accept/reject) is therefore load-bearing: keep scraped-data-derived scores as investigative leads, and get bespoke counsel review before any integration where scores affect claim payment automatically. (CFPB's proposal to sweep data brokers into FCRA was [withdrawn May 2025](https://www.federalregister.gov/documents/2025/05/15/2025-08644/protecting-americans-from-harmful-data-broker-practices-regulation-v-withdrawal-of-proposed-rule), but existing CRA case law against public-records aggregators stands.)

### 3.4 Entity resolution (scraped sources → canonical graph nodes)

**Internal-only machinery**: this pipeline fuses *scraped* sources into the reference graph. It is never run against client data (see §5.1). Five stages; output is the canonical `entity`/`address`/`npi` node sets plus provenance:

1. **Deterministic pass** — union-find on exact NPI (checksum-validated), EIN (where sources expose it: FL Sunbiz FEI, claims data), UEI/CAGE, DEA. These edges are immutable. NPI is the canonical individual key (Type 1) and org key (Type 2 + EIN). LEIE rows without NPI and all of SAM/OFAC fall through to stage 3.
2. **Normalization** — addresses: `libpostal` expand/parse ([repo](https://github.com/openvenues/libpostal), C lib active Dec 2025; install via the `pypostal-multiarch` wheel fork) → USPS Pub-28 casing (`usaddress-scourgify`) → CASS validation (Geocodio batch) → canonical key = delivery-point barcode or `(street, secondary, ZIP+4)` tuple. Org names: `cleanco` suffix-stripping + domain rules ("DBA", "MED CTR"→"MEDICAL CENTER") for a blocking key, never as the stored name. Person names: `probablepeople` + nickname dictionary.
3. **Probabilistic pass** — [Splink](https://github.com/moj-analytical-services/splink) (v4, actively maintained; **dedupe/recordlinkage/py_entitymatching are all stale as of 2026** — last releases 2023–2024) on the DuckDB backend: Fellegi-Sunter with EM training (no labels needed), term-frequency adjustments on names/addresses, multiple OR'd blocking rules (ZIP5+name-metaphone; street-number+surname; cleaned-org-token). Splink handles ~1M records/minute locally; our volumes (NPPES 8M + registries + lists) fit single-machine.
4. **Banding + clustering** — auto-match ≥ ~0.99, auto-reject ≤ ~0.01, route the ambiguous middle band to LLM-assisted review (the 2025–26 best practice: LLM as adjudicator of the FS-score gray zone, not as the matcher — [framework](https://journals.sagepub.com/doi/10.1177/18747655261422068)). Connected-components clustering with density monitoring against over-merging.
5. **Survivorship + provenance** — source-priority per attribute (NPPES wins taxonomy; state registry wins legal name; CASS output wins address), recency tiebreak. Keep `same_as` provenance edges rather than destructive merges so matches are reversible.

Two domain rules that prevent known false-positive factories:
- **Never merge Type 1 (person) NPIs into Type 2 (org) clusters.** A clinician's NPI follows them across employers — model affiliation as *time-bounded* `(entity, has_npi, npi)` / PECOS-reassignment edges. This is exactly the structure the GNN exploits for ring detection.
- **Classify addresses before using them as ring evidence.** Registered-agent and CMRA addresses host thousands of unrelated entities (one CT-Corp address ≠ a fraud ring). The `address` node carries an `address_type` feature (residential / commercial / CMRA / registered-agent, derived from agent-address lists + parcel data), and shared-address edges through agent addresses are either dropped or down-featured.

### 3.5 Ingestion stack (2026)

| Layer | Choice | Rationale / runner-up |
|---|---|---|
| Fetch | `httpx` + `selectolax` (Lexbor) | Most work is bulk files + JSON APIs; selectolax is 5–30× faster than BeautifulSoup. Scrapy only if we ever crawl 100+ linked pages/site; Playwright only for JS-rendered registries (check for the underlying XHR JSON first). `curl_cffi` stays in the toolbox for Cloudflare-fronted commercial sources, never for .gov. |
| Politeness | `tenacity` (retries/backoff), `aiolimiter` (per-host buckets), `hishel` (RFC-9111 caching for httpx) | All actively maintained 2026. |
| EL framework | **`dlt`** | Schema inference/evolution, incremental loading, native SCD2 merge writes straight to DuckDB/Parquet ([docs](https://dlthub.com/docs/general-usage/merge-loading)). Pin versions (1.27.0/.1 were yanked for a merge data-loss bug). Singer/Meltano rejected: unmaintained taps, heavier ops. |
| Staging | **Parquet partitioned by `snapshot_date` + DuckDB** | The 10–100 GB "too big for pandas, too small for Spark" zone; no server; append-only snapshots give time-travel diffs for free. Postgres only if concurrent writers/serving appear. SQLite for pipeline state only. |
| Validation | `pandera` schemas per staged table; `pydantic` models at API boundaries | GX rejected: 107-dep governance tool, overkill. |
| Resolution | Splink (DuckDB backend) + libpostal + Geocodio | §3.4. |
| Orchestration | cron/GitHub Actions schedules now → **Dagster** when it hurts | Dagster's asset model maps 1:1 onto "NPPES table → cleaned Parquet → graph tensors", with monthly partitions matching registry cadence. Airflow rejected for ops overhead at this team size. |
| Proxies | **None.** | Government data is published to be downloaded. Residential proxies rejected on ethics/sourcing grounds. |

Proposed package layout (new code, no changes to `oko/` model/training):

```
oko_ingest/                       # separate package; oko/ stays pure scoring
├── sources/                      # one dlt source per catalog entry
│   ├── nppes.py                  # bulk monthly + weekly incremental merge
│   ├── leie.py / sam.py / ofac.py
│   ├── cms_pecos.py / cms_utilization.py / cms_pos.py / open_payments.py
│   ├── sunbiz.py                 # SFTP daily/quarterly
│   └── scrape/                   # Tier-3: oig_enforcement.py, doj_pr.py (+ shared polite-fetch base)
├── staging/                      # Parquet/DuckDB layout, pandera schemas, snapshot mgmt
├── resolve/                      # splink models, address/name normalization, address_type classifier
├── publish/                      # emits the Reference Graph Snapshot (§5.2)
└── connectors.py                 # DuckDB/Parquet-backed implementations of the four oko ABCs
```

The terminal artifact of ingestion is a **Reference Graph Snapshot**: a versioned directory of Parquet files in the exact node/edge data contract of §5.2, served to the builder by `oko_ingest.connectors` implementations of the existing ABCs. The scoring engine never knows scraping happened.

---

## 4. Overlay strategy: scraped real data × synthetic data

Real claims and SME labels are client-private; scraped data gives us everything *around* the claim. The overlay strategy exploits that asymmetry with three graph modes (a config switch, same builder path):

### 4.1 Mode A — fully synthetic (exists today)

`SyntheticGraphGenerator` as-is: CI, tests, demos. Unchanged.

### 4.2 Mode B — real backbone, synthetic claims ("overlay")

The flagship dev/eval mode. An `OverlayGraphGenerator` (same interface as `SyntheticGraphGenerator`, same connector → builder path):

1. **Backbone from the Reference Graph Snapshot**: real `entity`/`address`/`npi` nodes and real edges (PECOS reassignment, ownership, officer, located_at) for a chosen region/specialty slice. This replaces the synthetic generator's made-up topology with real degree distributions, real address messiness, real org structures — the things synthetic generators systematically get wrong and GNNs systematically overfit to.
2. **Synthetic `claim` nodes** generated against real providers: claims sampled per-NPI calibrated to that NPI's real CMS utilization profile (service mix, volume), wired to real addresses/entities via the schema edges.
3. **Planted fraud patterns on real topology**: the existing planted patterns (shared-address rings, NPI reuse, feature anomalies) get injected by *selecting real structures* — e.g., pick a real address with genuine multi-entity density (post `address_type` filtering) and synthesize a ring's claims through it — rather than fabricating structure. Pattern injection stays parameterized by `synthetic_fraud_ratio` exactly as today.
4. **Leakage control**: any node touching a planted pattern gets its real-world sanction features frozen to pre-injection values, so the model can't read the answer off a LEIE flag we ourselves correlated with the plant.

Why this matters: it upgrades evaluation from "can the GNN find patterns we planted in a graph we invented" to "can it find patterns we planted in the real provider universe" — a much more honest estimate of production lift, while requiring zero client data.

### 4.3 Mode C — weak labels from enforcement data (real backbone, real-ish labels)

LEIE exclusions, SAM exclusions, and NER-extracted DOJ/OIG enforcement names give **positive weak labels** on entities/NPIs. Rules:

- Weak labels enter through the existing `sample_weight` mechanism (`data["claim"].sample_weight`) at a low weight (e.g., 0.1–0.3) so SME labels (1.0) dominate — no architecture change, the loss functions already consume this.
- **Temporal split discipline**: an exclusion dated *T* may only label claims dated before *T* (the exclusion is the outcome, not a feature), and the exclusion flag is removed from that node's features for those examples. Otherwise the model learns "excluded providers are excluded."
- This is positive-unlabeled learning: absence from LEIE is not a negative label. Unlabeled stays `NaN` (the builder already masks on labeled nodes only).

### 4.4 What stays synthetic forever

Claims content, note embeddings (synthetic notes), and ground-truth labels in modes A/B. We never synthesize fake entries in *real* reference data — synthetic nodes are tagged `is_synthetic` in staging so a snapshot can always be cleanly separated back out.

---

## 5. User data loading: how a suite user brings their data and leverages ours

### 5.1 The two-input model — contract, not consultancy

A user of the suite brings **claims + labels** (the private half); OKO ships the **reference graph** (the public half: entities, addresses, NPIs, sanctions, utilization features — the output of this sourcing engine). The join happens at build time, on the user's infrastructure — claims never flow to us.

**Posture decision:** OKO is an ML provider, not a data-onboarding service. We publish a data contract and the client conforms to it; we never run normalization, entity extraction, or ML-based resolution on client data. This is cheap for the client in our core domain because healthcare claims already carry billing/rendering NPIs by regulation — the hard linkage problem is solved by the payment system before the data reaches us. The §3.4 resolution machinery is **internal only**: it builds the reference graph from scraped sources and is never pointed at client data. Client notes participate exclusively as pre-computed embeddings (`note_emb`, via `VectorDBConnector`), which self-supervised pretraining consumes directly — no NER or mention extraction in v1. Verticals without an NPI-equivalent key (auto, P&C) are deferred rather than compensated for with resolution services.

### 5.2 The data contract (file-based, lowest-friction path)

Users who don't want to implement connector ABCs drop Parquet/CSV files in a documented layout — the same layout the Reference Graph Snapshot uses:

```
my_data/
├── nodes/
│   └── claim.parquet            # node_id + numeric feature columns
├── edges/
│   ├── entity__files__claim.parquet        # src_id, dst_id
│   ├── claim__serviced_at__address.parquet
│   └── npi__appears_on__claim.parquet
├── labels/
│   └── claim_labels.parquet     # node_id, label (0/1/NaN), sample_weight
└── embeddings/                  # optional
    └── claim.parquet            # node_id + 768-d note embedding columns
```

Three deterministic rules make the join work, and they are the user's only integration burden — no ML, no judgment calls:
1. **NPIs referenced as raw 10-digit NPIs** — joined exactly against reference `npi` nodes. (Already present on healthcare claims by regulation; this carries most of the linkage.)
2. **Addresses passed through the shipped normalizer CLI** (`oko-ingest normalize-addresses`, the same deterministic libpostal→Pub-28 pipeline used to key reference `address` nodes) so user addresses hash to the same canonical keys.
3. **Entities joined exactly on EIN where available.** No fuzzy matching of client data — if there's no key, there's no link.

Unmatched user references don't fail the build — they become new local nodes with no reference features (the builder already filters edges to known nodes and zero-fills missing features). This graceful degradation is the integration story, not a failure mode: an unlinked claim is still scored from its own features, note embedding, and whatever edges did resolve, and self-supervised pretraining does not depend on complete linkage.

### 5.3 Assembly flow

```
user claims/labels (private)          OKO Reference Graph Snapshot (shipped, versioned)
        │                                           │
        └────────► deterministic join ◄────────────┘        (exact keys only: NPI, canonical address, EIN)
                          │
                  CompositeConnectors                        (reference + user data behind the four ABCs)
                          │
                  HeteroGraphBuilder.build()                 (unchanged)
                          │
                  ScoringPipeline.run()                      (unchanged)
```

Concretely, the suite provides:
- `SnapshotGraphDBConnector` / `SnapshotStructuredDataConnector` — serve reference nodes/edges/features from a snapshot directory.
- `FileGraphDBConnector` / `FileLabelStoreConnector` / `FileVectorDBConnector` — serve the user's dropped files.
- `CompositeConnector` wrappers that union the two per node/edge type, so the builder sees one coherent graph.
- Power users with real infra skip the file layer entirely and subclass the ABCs directly against Neo4j/Snowflake/etc., exactly as the README already documents — the reference snapshot is still consumable beside them via the composite wrappers.

### 5.4 What the user gets from our scraped data, concretely

- **Multi-hop context their claims data doesn't contain**: their claim → real NPI → PECOS reassignment edges → sibling providers → shared real addresses. The GNN's ring detection only works if those hops exist; most claims systems don't carry them.
- **Pre-computed risk features** on reference nodes: exclusion flags and recency, enrollment churn, utilization outlier scores, entity age, address entity-density and `address_type`.
- **Cold-start scoring**: with Mode C weak labels, a user with *zero* SME labels gets a usable initial ranking; their accumulating SME decisions (weight 1.0) then progressively dominate the weak labels through the existing fine-tuning path.
- **Snapshot versioning**: reference snapshots are immutable and dated; a user pins a snapshot version per training run for reproducibility (pairs with `config.seed`).

---

## 6. Build order (proposed)

1. **M1 — Tier 1 bulk ingestion**: NPPES (monthly+weekly merge), LEIE, SAM extracts, PECOS (+reassignment edges), staging + pandera schemas. No scraping at all yet.
2. **M2 — Resolution**: address pipeline (libpostal/Geocodio), Splink models, `address_type` classifier, canonical node publication → first Reference Graph Snapshot.
3. **M3 — User loading path**: file-based data contract, snapshot/file/composite connectors, deterministic `normalize-addresses` CLI. (No client-facing resolution service — see §5.1 posture decision.)
4. **M4 — Overlay generator** (Mode B) + weak-label wiring (Mode C) with temporal-split discipline.
5. **M5 — Tier 3 scrapers** (OIG/DOJ enforcement NER → weak labels) and Tier 2 procurement decisions (OpenCorporates license, Geocodio volume, Regrid) based on M2 coverage gaps.

Open decisions for the team: OpenCorporates Enterprise budget vs. living with FL/NY/OH + on-demand state lookups; whether weak-label weight is a config field (`train.weak_label_weight`) or folded into the label store; counsel review trigger if any client integration moves scores toward claim adjudication (§3.3).
