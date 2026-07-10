"""Exhaustive all-510(k) PCCP census, 2023+ — for consistent treatment with the
exhaustive De Novo/PMA scan. The re-adjudication (pccp_readjudicate.py) covered only
the AI/software ring; this scans EVERY 510(k) summary from 2023 on (the period any
PCCP appears outside that ring), so non-AI PCCPs — e.g. antimicrobial-susceptibility
devices using a PCCP for breakpoint/interpretive-criteria updates — are counted too.

Phases (each cached):
  download : pull every 2023+ 510(k) summary artifact, full-text keyword-gate.
  adjudicate: Gemini 2.5 Pro subject-attribution on the gated hits; tag AI-list membership.

Usage:
    cd benedoc-strategy
    uv run python research/articles/pccp-samd-2025/scripts/pccp_census.py --phase download
    uv run python research/articles/pccp-samd-2025/scripts/pccp_census.py --phase adjudicate
"""

import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from google.cloud import storage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from samd_defs import bq_client, AIML_TABLE, DATA  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "analysis" / "pccp_readjudication"
CACHE = BASE / "artifacts"          # reuse the ring cache; add out-of-ring artifacts here
CENSUS_HITS = BASE / "census_hits.parquet"
CENSUS_ADJ = BASE / "census_adjudications.jsonl"
D = DATA[1:-1]

PCCP_RE = re.compile(
    r"pre[\s\-]*determined\s+change[\s\-]*control\s+plans?|\bPCCPs?\b|algorithm\s+change\s+protocol",
    re.IGNORECASE,
)
GEMINI_MODEL = "gemini-2.5-pro"


def phase_download(workers: int) -> pd.DataFrame:
    client = bq_client()
    sql = f"""
    SELECT s.submission_id, EXTRACT(YEAR FROM k.decision_date) AS yr,
           k.device_name, k.product_code, s.artifact_storage_path,
           (f.submission_id IS NOT NULL) AS on_aiml_list
    FROM {D}.510k_summary s
    JOIN {D}.510k k ON k.submission_id = s.submission_id
    LEFT JOIN {AIML_TABLE} f ON f.submission_id = s.submission_id
    WHERE EXTRACT(YEAR FROM k.decision_date) >= 2023
      AND s.artifact_storage_path IS NOT NULL
    """
    df = client.query(sql).result().to_dataframe().drop_duplicates("artifact_storage_path")
    CACHE.mkdir(parents=True, exist_ok=True)
    gcs = storage.Client(project="benedoc-prod")
    print(f"[census] {len(df)} 2023+ 510(k) artifacts to ensure/scan", flush=True)

    def work(r):
        uri = r.artifact_storage_path
        dest = CACHE / uri.rsplit("/", 1)[-1]
        try:
            if not dest.exists():
                b, bl = uri[5:].split("/", 1)
                gcs.bucket(b).blob(bl).download_to_filename(str(dest))
            doc = json.loads(dest.read_text())
        except Exception as e:
            return {"submission_id": r.submission_id, "error": str(e)[:80]}
        txt = "\n".join(
            [x.get("text", "") for x in doc.get("text_items", [])]
            + [c.get("text", "") for t in doc.get("tables", []) for c in t.get("cells", [])]
        )
        if not PCCP_RE.search(txt):
            return None
        return {
            "submission_id": r.submission_id, "yr": int(r.yr),
            "device_name": r.device_name, "product_code": r.product_code,
            "on_aiml_list": bool(r.on_aiml_list), "full_text": txt[:45000],
        }

    hits, done, errs = [], 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(work, r) for r in df.itertuples(index=False)]):
            r = f.result()
            done += 1
            if r is not None:
                if "error" in r:
                    errs += 1
                else:
                    hits.append(r)
            if done % 1000 == 0:
                print(f"[census] scanned {done}/{len(df)}  hits={len(hits)}  errs={errs}", flush=True)
    hd = pd.DataFrame(hits)
    hd.to_parquet(CENSUS_HITS)
    print(f"[census] DONE: {done} scanned, {errs} errors, {len(hd)} PCCP keyword hits", flush=True)
    return hd


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    return subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=GEMINI_API_KEY", "--project=benedoc-prod"],
        capture_output=True, text=True, check=True).stdout.strip()


_PROMPT = """Does the SUBJECT device of THIS FDA 510(k) submission include, incorporate, or \
was it cleared with a Predetermined Change Control Plan (PCCP)? Answer true only for the \
subject device's own authorized PCCP — not an incidental mention, a predicate device's PCCP, \
or a statement that none was included. Also classify whether the PCCP governs an AI/ML or \
software algorithm ("ai_ml") versus a non-algorithmic change such as antimicrobial breakpoint / \
interpretive-criteria or assay-reagent updates ("non_ai"). Device: {dev}.
Return JSON {{"has_pccp":bool,"attribution":"subject|predicate|none|incidental","kind":"ai_ml|non_ai|na","evidence":"<quote>"}}

TEXT:
{txt}"""


def phase_adjudicate(workers: int):
    from google import genai
    from google.genai import types
    hits = pd.read_parquet(CENSUS_HITS)
    seen = {}
    if CENSUS_ADJ.exists():
        for line in CENSUS_ADJ.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                seen[r["submission_id"]] = r
    todo = [r for r in hits.itertuples(index=False) if r.submission_id not in seen]
    print(f"[adjudicate] {len(seen)} cached, {len(todo)} to run", flush=True)
    client = genai.Client(api_key=_gemini_key())
    cfg = types.GenerateContentConfig(temperature=0, response_mime_type="application/json")

    def work(r):
        p = _PROMPT.format(dev=r.device_name or "(unknown)", txt=r.full_text or "")
        obj = json.loads(client.models.generate_content(model=GEMINI_MODEL, contents=p, config=cfg).text)
        return {"submission_id": r.submission_id, "yr": int(r.yr), "device_name": r.device_name,
                "product_code": r.product_code, "on_aiml_list": bool(r.on_aiml_list),
                "has_pccp": bool(obj.get("has_pccp")), "attribution": obj.get("attribution"),
                "kind": obj.get("kind"), "evidence": (obj.get("evidence") or "")[:300]}

    with ThreadPoolExecutor(max_workers=workers) as ex, open(CENSUS_ADJ, "a") as fh:
        n = 0
        for f in as_completed([ex.submit(work, r) for r in todo]):
            try:
                r = f.result()
            except Exception as e:
                print(f"  ! fail: {str(e)[:80]}", flush=True)
                continue
            fh.write(json.dumps(r) + "\n"); fh.flush()
            n += 1
            if n % 25 == 0:
                print(f"[adjudicate] {n}/{len(todo)}", flush=True)
    print(f"[adjudicate] DONE", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["download", "adjudicate"], required=True)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    if args.phase == "download":
        phase_download(args.workers)
    else:
        phase_adjudicate(args.workers)


if __name__ == "__main__":
    main()
