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
  pccp_devices.csv        Every PCCP identified in the study (125), keyed to its public FDA
                          submission number: decision year, pathway, device name, AI vs non-AI,
                          use-mode, whether on FDA's AI/ML list, and a short evidence quote.
  denovo_pma_pccp.csv     The De Novo and PMA subset, adjudicated separately.
scripts/
  pccp_census.py          Exhaustive scan of every 2023+ 510(k) summary for PCCP language.
  pccp_census_report.py   Merge + AI/non-AI split + headline numbers.
  pccp_readjudicate.py    Earlier AI/software-cohort re-adjudication (superseded by the census).
  nested_cohort_analysis.py  Pathway use and review time across the nested device populations.
```

## Verifying the results without our platform

**`data/pccp_devices.csv` is the reproducible artifact.** Every row is a real FDA submission number (e.g. `K250956`, `DEN190040`, `P240040`) you can look up on accessdata.fda.gov and read the same summary we did. The paper's headline counts fall straight out of it:

- **125 PCCPs** total, **78 AI / 47 non-AI (38%)**
- Pathways: 120 via 510(k), 4 via De Novo, 1 via PMA
- Earliest: `DEN190040` (Caption Guidance, De Novo, Feb 2020)

## How PCCP was measured

Two stages, on the full text of each published summary: (1) a hyphenation- and spacing-tolerant keyword gate for "predetermined change control plan" / "PCCP" (plus a sweep for older formulations, which found none); (2) adjudication by a large language model (Gemini 2.5 Pro) confirming a PCCP only where the *subject* device carried an authorized or submitted plan — excluding guidance citations, predicate-device plans, negations, and prospective intentions — and classifying each as AI/ML or non-AI. Because it sees only summary-publishing submissions that name the plan in words, every count is a floor.

## Cohort definition

The AI/software device cohort is defined by BeneDoc's internal cohort module (`samd_defs`), which is not reproduced here. Its method, summarized: the universe is the union of (1) FDA's published AI/ML-enabled device list and (2) a supplement of clearances matched by any of three signals — product-code text, device-name text, or parsed-summary text — against established software/AI terminology, kept at a confidence tier (FDA-confirmed, or ≥2 independent signals); devices are further tagged SaMD (standalone software) vs SiMD (software embedded in a hardware device). The full description is in the paper's Methods. The published scripts import this module; it is omitted deliberately.

## Reproducibility note (please read)

The scripts query BeneDoc's internal BigQuery tables (`benedoc-prod.benedoc_data.*`) — our OCR-extracted, structured versions of the public FDA PDFs named above — and the cohort module above. They reference internal Google Cloud resource names and a Secret Manager key by name; **no credentials or secret values are included.** The scripts are published for **methodological transparency, not turnkey execution.** To *verify* the findings, use `data/pccp_devices.csv` against the public FDA record.

## Citation & contact

Davis B. *The Need for Speed: Regulatory Strategies for Fast-Moving AI and Software Medical Devices, and the Rise of the Predetermined Change Control Plan, 2018–2026.* Preprint (medRxiv, DOI forthcoming).

Competing interest: the author is founder and CEO of BeneDoc, Inc., a medical device regulatory compliance company. The analysis uses only publicly available FDA data. Contact: b@benedoc.co
