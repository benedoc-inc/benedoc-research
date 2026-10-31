"""
PCCP adoption by cohort — the v6 consistent-cohort recompute.

Reproduces the paper's Figure 3 / Table 3 Panel A from the public device list
(`data/pccp_devices.csv`, the numerator) and the cohort denominators.

Key point (why v6 differs from earlier drafts): a device counts as "AI" by the
*canonical AI cohort* — FDA's AI/ML list ∪ a signal-based supplement — for BOTH the
numerator and the denominator (the `ai_cohort` column here). The `ai_ml` column is the
separate LLM read of whether a plan governs an AI/ML algorithm; using it for the
numerator but the canonical cohort for the denominator over-counted the AI rate.
The two columns differ by the ~12 algorithm-driven devices FDA has not placed on its
AI/ML list (e.g., closed-loop insulin systems), which sit in `ai_ml` but not `ai_cohort`.

Reproducibility: numerators come from the public CSV; denominators (the summary-publishing
510(k) + De Novo populations, tagged by the same cohort definition) are queried from
BeneDoc's internal BigQuery mirror of the public FDA records via the internal cohort
module `samd_defs` — omitted here, as in the other scripts. Published for methodological
transparency, not turnkey execution; verify counts directly against `data/pccp_devices.csv`.
"""
import sys
from pathlib import Path

import pandas as pd

# internal cohort module (see README) — same import as the other scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samd_defs import bq_client, samd_universe_sql, SW_PATTERN  # noqa: E402

D = "`benedoc-prod.benedoc_data`"
DATA = Path(__file__).resolve().parents[1] / "data" / "pccp_devices.csv"
client = bq_client()

devices = pd.read_csv(DATA)
print(f"{len(devices)} PCCPs | ai_ml(LLM)={int(devices.ai_ml.sum())} | "
      f"ai_cohort(canonical)={int(devices.ai_cohort.sum())} | non-AI={int((~devices.ai_cohort).sum())}")
print("AI-cohort PCCP by pathway:", devices[devices.ai_cohort].pathway.value_counts().to_dict())

# summary-publishing 510(k)s + De Novo grants, tagged by the canonical cohort
POP = f"""
WITH u AS ({samd_universe_sql(start_year=2010)}),
ai AS (SELECT DISTINCT submission_id FROM u WHERE confidence_tier IN ('confirmed','high')),
sw AS (SELECT product_code FROM {D}.classification
       WHERE REGEXP_CONTAINS(LOWER(COALESCE(device_name,'')||' '||COALESCE(definition,'')), r"{SW_PATTERN}")),
summ AS (SELECT DISTINCT k_number FROM {D}.510k_summary)
SELECT submission_id, yr, is_ai, is_sw FROM (
  SELECT k.submission_id, EXTRACT(YEAR FROM k.decision_date) yr,
    (k.submission_id IN (SELECT submission_id FROM ai)) is_ai,
    (k.submission_id IN (SELECT submission_id FROM ai) OR k.product_code IN (SELECT product_code FROM sw)
       OR REGEXP_CONTAINS(LOWER(COALESCE(k.device_name,'')),r"{SW_PATTERN}")) is_sw
  FROM {D}.510k k
  WHERE k.decision_code LIKE 'SE%' AND EXTRACT(YEAR FROM k.decision_date) BETWEEN 2018 AND 2026
    AND k.submission_id IN (SELECT k_number FROM summ)
  UNION ALL
  SELECT d.submission_id, EXTRACT(YEAR FROM d.decision_date) yr,
    (d.submission_id IN (SELECT submission_id FROM ai)) is_ai,
    (d.submission_id IN (SELECT submission_id FROM ai) OR d.product_code IN (SELECT product_code FROM sw)
       OR REGEXP_CONTAINS(LOWER(COALESCE(d.device_name,'')),r"{SW_PATTERN}")) is_sw
  FROM {D}.denovo d WHERE EXTRACT(YEAR FROM d.decision_date) BETWEEN 2018 AND 2026)
"""
pop = client.query(POP).to_dataframe()
# numerator = the 510(k)+De Novo PCCPs from the public list (PMA sits outside the nested cohorts)
pop["pccp"] = pop.submission_id.isin(set(devices[devices.pathway != "PMA"].submission_id))


def rate(df, mask):
    s = df[mask]
    return round(100 * s.pccp.sum() / len(s), 2) if len(s) else 0.0


print("\nPCCP % of summaries by year (all pathways, canonical cohorts) — Figure 3:")
for yr in range(2018, 2027):
    d = pop[pop.yr == yr]
    print(f"  {yr}: all={rate(d, pd.Series(True, index=d.index)):5.2f}  "
          f"software+AI={rate(d, d.is_sw):5.2f}  AI={rate(d, d.is_ai):5.2f}")

pc = pop[pop.yr.between(2023, 2026)]
print("\nTable 3 Panel A (2023–2026):")
print(f"  AI {rate(pc, pc.is_ai)}%  ·  Software+AI {rate(pc, pc.is_sw)}%  ·  "
      f"All {rate(pc, pd.Series(True, index=pc.index))}%  ·  non-AI {rate(pc, ~pc.is_ai)}%")
print(f"  AI vs non-AI ≈ {pc[pc.is_ai].pccp.mean()/pc[~pc.is_ai].pccp.mean():.0f}×")
