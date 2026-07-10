"""Merge the exhaustive census (all 2023+ 510(k)) + De Novo/PMA into one complete
all-pathway PCCP census, split AI vs non-AI. Answers: does the census add real PCCPs
the AI-ring re-adjudication missed, and does "PCCP is AI-specific" survive?
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from samd_defs import bq_client, DATA  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "analysis" / "pccp_readjudication"
D = DATA[1:-1]


def load_jsonl(p):
    return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]


def main():
    adj = pd.DataFrame(load_jsonl(BASE / "census_adjudications.jsonl"))
    conf = adj[(adj.has_pccp) & (adj.attribution == "subject")].drop_duplicates("submission_id").copy()
    print(f"Census: {len(adj)} adjudicated → {len(conf)} confirmed subject PCCPs (510k, 2023+)")

    # AI vs non-AI: prefer on_aiml_list, else the model's kind
    conf["ai"] = conf.on_aiml_list | (conf.kind == "ai_ml")
    print("\n=== 510(k) 2023+ confirmed PCCPs: AI vs non-AI ===")
    print(f"  AI/ML:  {int(conf.ai.sum())}")
    print(f"  non-AI: {int((~conf.ai).sum())}")
    print("\n  non-AI by product area (evidence sample):")
    for r in conf[~conf.ai].sort_values("yr").itertuples(index=False):
        print(f"    {r.yr} {r.submission_id} [{r.product_code}] {str(r.device_name)[:38]:38s} {str(r.evidence)[:60]}")

    print("\n=== by year (510k 2023+) ===")
    print(conf.groupby(["yr", "ai"]).size().unstack(fill_value=0).to_string())

    # How many are NEW vs the ring re-adjudication?
    ring_adj = pd.DataFrame(load_jsonl(BASE / "adjudications.jsonl"))
    ring_pccp = set(ring_adj[(ring_adj.has_pccp) & (ring_adj.attribution == "subject")].submission_id)
    census_pccp = set(conf.submission_id)
    new = census_pccp - ring_pccp
    print(f"\n=== census vs ring re-adjudication ===")
    print(f"  in ring re-adj: {len(census_pccp & ring_pccp)}")
    print(f"  NEW from census (not in ring): {len(new)}  of which AI={int(conf[conf.submission_id.isin(new)].ai.sum())}, non-AI={int((~conf[conf.submission_id.isin(new)].ai).sum())}")

    # Complete all-pathway count (510k census + De Novo/PMA)
    dnpma = pd.read_csv(BASE / "denovo_pma_pccp.csv")
    print(f"\n=== COMPLETE all-pathway PCCP census (2018+) ===")
    ai_510k = len(conf[conf.ai]) + len(ring_pccp - census_pccp)  # 2023+ AI + pre-2023 ring AI not re-scanned
    print(f"  510(k) AI PCCP (2023+ census AI):        {int(conf.ai.sum())}")
    print(f"  510(k) non-AI PCCP (2023+ census):       {int((~conf.ai).sum())}")
    print(f"  De Novo/PMA (all AI):                    {len(dnpma)}")
    print(f"  pre-2023 ring AI PCCPs (2020-2022):      {len(ring_pccp - census_pccp)}")

    conf.to_parquet(BASE / "census_confirmed.parquet")
    print(f"\nwrote {BASE/'census_confirmed.parquet'}")


if __name__ == "__main__":
    main()
