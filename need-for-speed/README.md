# The Need for Speed — companion code & data

Companion materials for **"The Need for Speed: Regulatory Strategies for Fast-Moving AI and Software Medical Devices, and the Rise of the Predetermined Change Control Plan, 2018–2026"** (Bryan Davis, BeneDoc, Inc.).

## Data provenance — everything derives from public FDA sources

- **510(k) clearances** — FDA 510(k) Premarket Notification Database (accessdata.fda.gov)
- **De Novo grants** and **PMA decisions / Summaries of Safety and Effectiveness Data** — FDA public records
- **AI/ML-enabled device list** — FDA, "Artificial Intelligence and Machine Learning (AI/ML)-Enabled Medical Devices"
- **PCCP disclosures** — read from the published 510(k) Summaries, De Novo decision summaries, and PMA SSEDs above

No non-public data is used.

## What's here

```
data/
  pccp_devices.csv          Every PCCP identified in the study (125), keyed to its public FDA
                            submission number: decision year, pathway, device name, product code,
                            whether on FDA's AI/ML list, the two AI flags (ai_ml, ai_cohort — see
                            "Two AI flags" below), use-mode, and a short evidence quote.
  pccp_by_year_cohort.csv   PCCP % of summaries by decision year for each nested cohort
                            (all devices / software+AI / AI) — the series behind Figure 3.
  denovo_pma_pccp.csv       The De Novo and PMA subset, adjudicated separately.
scripts/
  pccp_census.py            Exhaustive scan of every 2023+ 510(k) summary for PCCP language.
  pccp_census_report.py     Merge + AI/non-AI split + headline numbers.
  pccp_readjudicate.py      Earlier AI/software-cohort re-adjudication (superseded by the census).
  nested_cohort_analysis.py Pathway use and review time across the nested device populations.
  pccp_cohort_recompute.py  Reproduces Figure 3 / Table 3 Panel A from pccp_devices.csv + the
                            cohort denominators (the consistent-cohort recompute; see below).
  make_figures.py           Regenerates the three paper figures (self-contained, no data access).
figures/
  fig1_nested_cohorts.png · fig2_review_time_by_pathway.png · fig3_pccp_adoption_over_time.png
```

## Verifying the results without our platform

**`data/pccp_devices.csv` is the reproducible artifact.** Every row is a real FDA submission number (e.g. `K250956`, `DEN190040`, `P240040`) you can look up on accessdata.fda.gov and read the same summary we did. The paper's headline counts fall straight out of it:

- **125 PCCPs** total; by the paper's canonical AI cohort (`ai_cohort`), **66 AI / 59 non-AI (47%)**
- Pathways (all devices): 120 via 510(k), 4 via De Novo, 1 via PMA. AI-cohort PCCPs: 63 via 510(k), 3 via De Novo
- Earliest: `DEN190040` (Caption Guidance, De Novo, Feb 2020)

## Two AI flags (please read — this changed in the current revision)

The device list carries **two** boolean columns, and they are not the same:

- **`ai_ml`** — the large-language-model's read of whether *this plan* governs an AI/ML (or software) algorithm, from the summary text. Marks **78** of the 125.
- **`ai_cohort`** — membership in the study's **canonical AI cohort**: FDA's published AI/ML-enabled device list ∪ a signal-based supplement (see "Cohort definition"). Marks **66** of the 125.

Adoption **rates** in the paper use `ai_cohort` for **both** numerator and denominator, so the AI cohort is defined identically wherever it appears (the pathway/review-time tables and the PCCP tables). An earlier revision mixed the two — counting AI PCCPs by `ai_ml` (78) against a canonical-cohort denominator — which inflated the AI adoption rate. The two flags differ by the ~12 algorithm-driven devices FDA has **not** placed on its AI/ML list (e.g., closed-loop insulin-delivery systems such as MiniMed and Control-IQ): the LLM reads their plans as algorithmic, but they fall outside the AI cohort and are counted among other devices, so the AI-specific rate is conservative.

Headline rate, 2023–2026 (510(k) + De Novo, canonical cohorts): **AI 7.1%** of summaries disclose a PCCP vs **0.64%** of all other devices — roughly **11×** — with the intermediate software+AI cohort at 6.3%.

## How PCCP was measured

Two stages, on the full text of each published summary: (1) a hyphenation- and spacing-tolerant keyword gate for "predetermined change control plan" / "PCCP" (plus a sweep for older formulations, which found none); (2) adjudication by a large language model (Gemini 2.5 Pro) confirming a PCCP only where the *subject* device carried an authorized or submitted plan — excluding guidance citations, predicate-device plans, negations, and prospective intentions — and classifying each as AI/ML or non-AI (the `ai_ml` flag). Because it sees only summary-publishing submissions that name the plan in words, every count is a floor.

## Cohort definition

The AI/software device cohort (`ai_cohort`) is defined by BeneDoc's internal cohort module (`samd_defs`), which is not reproduced here. Its method, summarized: the universe is the union of (1) FDA's published AI/ML-enabled device list and (2) a supplement of clearances matched by any of three signals — product-code text, device-name text, or parsed-summary text — against established software/AI terminology, kept at a confidence tier (FDA-confirmed, or ≥2 independent signals); devices are further tagged SaMD (standalone software) vs SiMD (software embedded in a hardware device). The full description is in the paper's Methods. The published scripts import this module; it is omitted deliberately.

## Reproducibility note (please read)

The scripts query BeneDoc's internal BigQuery tables (`benedoc-prod.benedoc_data.*`) — our OCR-extracted, structured versions of the public FDA PDFs named above — and the cohort module above. They reference internal Google Cloud resource names and a Secret Manager key by name; **no credentials or secret values are included.** The scripts are published for **methodological transparency, not turnkey execution.** To *verify* the findings, use `data/pccp_devices.csv` against the public FDA record. `make_figures.py` is the exception — it is fully self-contained and redraws the figures from values in the paper.

## Citation & contact

Davis B. *The Need for Speed: Regulatory Strategies for Fast-Moving AI and Software Medical Devices, and the Rise of the Predetermined Change Control Plan, 2018–2026.* Preprint (medRxiv, DOI forthcoming).

Competing interest: the author is founder and CEO of BeneDoc, Inc., a medical device regulatory compliance company. The analysis uses only publicly available FDA data. Contact: b@benedoc.co
