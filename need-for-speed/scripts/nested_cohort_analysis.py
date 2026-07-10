"""
Nested-cohort pathway analysis for the "moving at the speed of software" article.

Reframes the analysis away from imaging-vs-non-imaging and onto three CONCENTRIC device
populations, viewed through the same regulatory-pathway lens:

    Ring 1  All devices       — every 510(k) (SE) + De Novo grant, 2018-2025
    Ring 2  Software + AI      — software-based devices (software product code OR software
                                 device-name signal) UNION the AI devices  (SaMD ring)
    Ring 3  AI devices         — the canonical AI/ML universe (samd_defs, confirmed+high),
                                 imaging included

AI ⊆ Software+AI ⊆ All. The question is how pathway selection (De Novo / Traditional /
Special 510(k) / PCCP), review time, adoption-over-time, and the company-maturity gradient
SHIFT as you narrow from all devices to the AI subset — and what structural conditions drive
the shift (Special needs a prior own-device clearance; De Novo has no predicate and is slower
by design; PCCP rides on the initial filing and is a floor, summary-only).

Usage:
    cd benedoc-strategy
    uv run python research/articles/pccp-samd-2025/scripts/nested_cohort_analysis.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from samd_defs import bq_client, samd_universe_sql, SW_PATTERN  # noqa: E402

K510 = "`benedoc-prod.benedoc_data.510k`"
DENOVO = "`benedoc-prod.benedoc_data.denovo`"
SUMMARY = "`benedoc-prod.benedoc_data.510k_summary`"
CLASS = "`benedoc-prod.benedoc_data.classification`"
client = bq_client()


def run(label, sql):
    print(f"\n=== {label} ===")
    rows = list(client.query(sql).result())
    if not rows:
        print("(no rows)")
        return []
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(widths[c]) for c in cols))
    return rows


BASE = f"""
WITH universe AS ({samd_universe_sql(start_year=2010)}),
ai_ids AS (SELECT DISTINCT submission_id FROM universe WHERE confidence_tier IN ('confirmed','high')),
sw_codes AS (
  SELECT product_code FROM {CLASS}
  WHERE REGEXP_CONTAINS(LOWER(COALESCE(device_name,'') || ' ' || COALESCE(definition,'')), r"{SW_PATTERN}")
),
summ AS (SELECT k_number, LOGICAL_OR(COALESCE(pccp, FALSE)) pccp FROM {SUMMARY} GROUP BY k_number),
subs AS (
  SELECT submission_id, '510k' AS sub_type, applicant, product_code, device_name,
         clearance_type, date_received, decision_date
  FROM {K510}
  WHERE decision_code LIKE 'SE%' AND EXTRACT(YEAR FROM decision_date) BETWEEN 2018 AND 2025
  UNION ALL
  SELECT submission_id, 'denovo', applicant, product_code, device_name,
         'De Novo', date_received, decision_date
  FROM {DENOVO}
  WHERE EXTRACT(YEAR FROM decision_date) BETWEEN 2018 AND 2025
),
base AS (
  SELECT
    s.submission_id, s.sub_type, s.applicant, s.product_code, s.decision_date,
    EXTRACT(YEAR FROM s.decision_date) AS yr,
    DATE_DIFF(s.decision_date, s.date_received, DAY) AS review_days,
    CASE
      WHEN s.sub_type = 'denovo' THEN 'De Novo'
      WHEN s.clearance_type = 'Special' THEN 'Special 510(k)'
      WHEN s.clearance_type = 'Abbreviated' THEN 'Abbreviated 510(k)'
      ELSE 'Traditional 510(k)'
    END AS strategy,
    (s.submission_id IN (SELECT submission_id FROM ai_ids)) AS is_ai,
    (s.submission_id IN (SELECT submission_id FROM ai_ids)
       OR s.product_code IN (SELECT product_code FROM sw_codes)
       OR REGEXP_CONTAINS(LOWER(COALESCE(s.device_name,'')), r"{SW_PATTERN}")) AS is_sw,
    COALESCE(su.pccp, FALSE) AS pccp,
    (su.k_number IS NOT NULL) AS has_summary
  FROM subs s
  LEFT JOIN summ su ON su.k_number = s.submission_id AND s.sub_type = '510k'
),
ringed AS (
  SELECT b.*, ring,
    ROW_NUMBER() OVER (PARTITION BY ring, applicant ORDER BY decision_date, submission_id) AS seq
  FROM base b, UNNEST(['1 All devices','2 Software+AI','3 AI devices']) AS ring
  WHERE ring = '1 All devices'
     OR (ring = '2 Software+AI' AND b.is_sw)
     OR (ring = '3 AI devices' AND b.is_ai)
)
"""
RD = "review_days BETWEEN 1 AND 1000"


def main():
    run("R1: Pathway mix by cohort ring (the headline comparison)", f"""
        {BASE}
        SELECT ring,
          COUNT(*) n,
          COUNT(DISTINCT applicant) firms,
          ROUND(100.0*COUNTIF(strategy='De Novo')/COUNT(*),2) de_novo_pct,
          ROUND(100.0*COUNTIF(strategy='Traditional 510(k)')/COUNT(*),1) trad_pct,
          ROUND(100.0*COUNTIF(strategy='Special 510(k)')/COUNT(*),1) special_pct,
          ROUND(100.0*COUNTIF(strategy='Abbreviated 510(k)')/COUNT(*),2) abbrev_pct,
          ROUND(100.0*COUNTIF(pccp)/NULLIF(COUNTIF(has_summary),0),2) pccp_pct_of_summ
        FROM ringed GROUP BY ring ORDER BY ring
    """)

    run("R2: Median review days by pathway, per ring (is AI faster/slower within a pathway?)", f"""
        {BASE}
        SELECT ring,
          CAST(ROUND(APPROX_QUANTILES(IF({RD} AND strategy='De Novo',review_days,NULL),100)[OFFSET(50)]) AS INT64) de_novo,
          CAST(ROUND(APPROX_QUANTILES(IF({RD} AND strategy='Traditional 510(k)',review_days,NULL),100)[OFFSET(50)]) AS INT64) traditional,
          CAST(ROUND(APPROX_QUANTILES(IF({RD} AND strategy='Special 510(k)',review_days,NULL),100)[OFFSET(50)]) AS INT64) special
        FROM ringed GROUP BY ring ORDER BY ring
    """)

    run("R3: Use of the Special 510(k) over time, per ring (% of that ring-year)", f"""
        {BASE}
        SELECT yr,
          ROUND(100.0*COUNTIF(ring='1 All devices' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='1 All devices'),0),1) all_special,
          ROUND(100.0*COUNTIF(ring='2 Software+AI' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='2 Software+AI'),0),1) sw_special,
          ROUND(100.0*COUNTIF(ring='3 AI devices' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='3 AI devices'),0),1) ai_special
        FROM ringed GROUP BY yr ORDER BY yr
    """)

    run("R4: PCCP adoption over time, per ring (% of summaries; PCCP is summary-only -> floor)", f"""
        {BASE}
        SELECT yr,
          ROUND(100.0*COUNTIF(ring='1 All devices' AND pccp)/NULLIF(COUNTIF(ring='1 All devices' AND has_summary),0),2) all_pccp,
          ROUND(100.0*COUNTIF(ring='2 Software+AI' AND pccp)/NULLIF(COUNTIF(ring='2 Software+AI' AND has_summary),0),2) sw_pccp,
          ROUND(100.0*COUNTIF(ring='3 AI devices' AND pccp)/NULLIF(COUNTIF(ring='3 AI devices' AND has_summary),0),2) ai_pccp
        FROM ringed GROUP BY yr ORDER BY yr
    """)

    run("R5: Cohort growth — counts per ring per year (AI as rising share of all)", f"""
        {BASE}
        SELECT yr,
          COUNTIF(ring='1 All devices') all_devices,
          COUNTIF(ring='2 Software+AI') software_ai,
          COUNTIF(ring='3 AI devices') ai_devices,
          ROUND(100.0*COUNTIF(ring='3 AI devices')/NULLIF(COUNTIF(ring='1 All devices'),0),1) ai_pct_of_all
        FROM ringed GROUP BY yr ORDER BY yr
    """)

    run("R6: Use of the Special 510(k) by company maturity, per ring (seq within ring)", f"""
        {BASE}
        SELECT
          CASE WHEN seq=1 THEN '1 first' WHEN seq=2 THEN '2 second'
               WHEN seq BETWEEN 3 AND 5 THEN '3 third-fifth' ELSE '4 sixth+' END AS maturity,
          ROUND(100.0*COUNTIF(ring='1 All devices' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='1 All devices'),0),1) all_special,
          ROUND(100.0*COUNTIF(ring='2 Software+AI' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='2 Software+AI'),0),1) sw_special,
          ROUND(100.0*COUNTIF(ring='3 AI devices' AND strategy='Special 510(k)')/NULLIF(COUNTIF(ring='3 AI devices'),0),1) ai_special
        FROM ringed GROUP BY 1 ORDER BY 1
    """)

    print("\n" + "=" * 80)
    print("NOTES")
    print("  Rings: All = 510(k) SE + De Novo 2018-25; Software+AI = software-signal ∪ AI;")
    print("         AI = canonical universe (samd_defs, confirmed+high). AI ⊆ Software+AI ⊆ All.")
    print("  PCCP = first-party flag on summary-publishing 510(k)s only -> FLOOR.")
    print("  Maturity = within-ring per-applicant sequence (string match; no entity resolution).")
    print("=" * 80)


if __name__ == "__main__":
    main()
