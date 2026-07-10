"""Re-adjudicate the PCCP flag for the software+AI reporting cohort, bypassing the
pipeline's LLM-extraction stage (which systematically misses real PCCPs because its
`pccp` field uses focused element selection and never sees the disclosing passage).

This is a STANDALONE analysis script, deliberately NOT a pipeline step: the pipeline's
`interpret_disclosures` is the very thing under-recalling, so re-running it would
reproduce the miss. Instead we:

  1. Pull every summary artifact for the software+AI ring (the cohort the paper reports).
  2. Download each docling artifact from GCS and reconstruct the FULL text the gate sees
     (text_items + table cells + captions) — no focused subsetting.
  3. Keyword-gate on a hyphen/OCR-tolerant PCCP pattern, then adjudicate each hit with
     gemini-2.5-pro: does the SUBJECT device of THIS submission include an authorized PCCP
     (vs. an incidental guidance citation, a predicate device's PCCP, a negation, or a
     purely future intention)?
  4. Recompute device-level PCCP rates (LOGICAL_OR over a device's artifacts) and diff
     against the current first-party flag.

Every phase caches to analysis/pccp_readjudication/ so reruns are cheap and resumable.

Usage:
    cd benedoc-strategy
    # GEMINI_API_KEY auto-pulled from Secret Manager if unset
    uv run python research/articles/pccp-samd-2025/scripts/pccp_readjudicate.py
    uv run python .../pccp_readjudicate.py --limit 20        # smoke test
    uv run python .../pccp_readjudicate.py --phase recompute  # just redo the report
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
from samd_defs import bq_client, samd_universe_sql, SW_PATTERN  # noqa: E402

DATA = "`benedoc-prod.benedoc_data"
CLASS = f"{DATA}.classification`"
K510 = f"{DATA}.510k`"
DENOVO = f"{DATA}.denovo`"
SUMMARY = f"{DATA}.510k_summary`"

OUTDIR = Path(__file__).resolve().parent.parent / "analysis" / "pccp_readjudication"
ARTIFACT_CACHE = OUTDIR / "artifacts"
CANDIDATES = OUTDIR / "candidates.parquet"
KEYWORD_HITS = OUTDIR / "keyword_hits.parquet"
ADJUDICATIONS = OUTDIR / "adjudications.jsonl"
REPORT = OUTDIR / "pccp_readjudication_report.md"
RESULT = OUTDIR / "pccp_readjudicated.parquet"

# Hyphen/whitespace/OCR-linebreak tolerant. Matches the canonical phrase and the acronym
# (incl. plural). Broad on purpose: this is only a gate — the LLM supplies precision.
PCCP_RE = re.compile(
    r"pre[\s\-]*determined\s+change[\s\-]+control\s+plans?"
    r"|\bPCCPs?\b"
    r"|algorithm\s+change\s+protocol",
    re.IGNORECASE,
)

GEMINI_MODEL = "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# Phase 1 — candidate artifacts for the software+AI ring
# ---------------------------------------------------------------------------
def phase_candidates(ring: str, end_year: int) -> pd.DataFrame:
    client = bq_client()
    sql = f"""
WITH universe AS ({samd_universe_sql(start_year=2010)}),
ai_ids AS (SELECT DISTINCT submission_id FROM universe WHERE confidence_tier IN ('confirmed','high')),
sw_codes AS (
  SELECT product_code FROM {CLASS}
  WHERE REGEXP_CONTAINS(LOWER(COALESCE(device_name,'')||' '||COALESCE(definition,'')), r"{SW_PATTERN}")),
subs AS (
  SELECT submission_id, applicant, product_code, device_name, decision_date FROM {K510}
    WHERE decision_code LIKE 'SE%' AND EXTRACT(YEAR FROM decision_date) BETWEEN 2018 AND {end_year}
  UNION ALL
  SELECT submission_id, applicant, product_code, device_name, decision_date FROM {DENOVO}
    WHERE EXTRACT(YEAR FROM decision_date) BETWEEN 2018 AND {end_year}),
base AS (
  SELECT s.submission_id, s.applicant, s.device_name,
    EXTRACT(YEAR FROM s.decision_date) AS yr,
    (s.submission_id IN (SELECT submission_id FROM ai_ids)) AS is_ai,
    (s.submission_id IN (SELECT submission_id FROM ai_ids)
      OR s.product_code IN (SELECT product_code FROM sw_codes)
      OR REGEXP_CONTAINS(LOWER(COALESCE(s.device_name,'')), r"{SW_PATTERN}")) AS is_sw
  FROM subs s)
SELECT b.submission_id, b.device_name, b.yr, b.is_ai, b.is_sw,
  su.artifact_hash, su.artifact_storage_path,
  COALESCE(su.pccp, FALSE) AS current_pccp,
  (su.artifact_storage_path IS NOT NULL) AS has_artifact
FROM base b
LEFT JOIN {SUMMARY} su ON su.submission_id = b.submission_id
WHERE b.is_sw
"""
    df = client.query(sql).result().to_dataframe()
    if ring == "ai":
        df = df[df.is_ai].copy()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CANDIDATES)
    print(f"[candidates] {df.submission_id.nunique()} devices "
          f"({df[df.is_ai].submission_id.nunique()} AI); "
          f"{df.artifact_storage_path.notna().sum()} artifacts; "
          f"{df.current_pccp.sum()} artifacts currently flagged")
    return df


# ---------------------------------------------------------------------------
# Phase 2 — download artifacts, reconstruct full text, keyword-gate
# ---------------------------------------------------------------------------
def _blob_of(uri: str):
    _, rest = uri.split("gs://", 1)
    bucket, blob = rest.split("/", 1)
    return bucket, blob


def _full_text(doc: dict) -> str:
    parts = [ti.get("text", "") for ti in doc.get("text_items", [])]
    for t in doc.get("tables", []):
        if t.get("caption"):
            parts.append(t["caption"])
        parts.extend(c.get("text", "") for c in t.get("cells", []))
    return "\n".join(p for p in parts if p)


def _fetch_one(gcs: storage.Client, uri: str, dest: Path) -> str:
    if not dest.exists():
        bucket, blob = _blob_of(uri)
        gcs.bucket(bucket).blob(blob).download_to_filename(str(dest))
    return dest.read_text()


def _contexts(text: str, width: int = 320) -> list[str]:
    out = []
    for m in PCCP_RE.finditer(text):
        a, b = max(0, m.start() - width), min(len(text), m.end() + width)
        out.append(text[a:b])
    return out[:8]


def phase_download(df: pd.DataFrame, workers: int) -> pd.DataFrame:
    ARTIFACT_CACHE.mkdir(parents=True, exist_ok=True)
    arts = df[df.artifact_storage_path.notna()].drop_duplicates("artifact_storage_path")
    gcs = storage.Client(project="benedoc-prod")
    rows, done, errs = [], 0, 0

    def work(rec):
        uri = rec.artifact_storage_path
        dest = ARTIFACT_CACHE / (uri.rsplit("/", 1)[-1])
        try:
            doc = json.loads(_fetch_one(gcs, uri, dest))
        except Exception as e:  # network / parse — record and skip
            return {"artifact_storage_path": uri, "error": str(e)[:120]}
        text = _full_text(doc)
        return {"artifact_storage_path": uri, "chars": len(text),
                "keyword_hit": bool(PCCP_RE.search(text)),
                "full_text": text, "contexts": _contexts(text)}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, r): r for r in arts.itertuples(index=False)}
        for f in as_completed(futs):
            r = f.result()
            rows.append(r)
            done += 1
            errs += "error" in r
            if done % 200 == 0:
                print(f"[download] {done}/{len(arts)} ({errs} errors)")

    fetched = pd.DataFrame(rows)
    merged = df.merge(fetched, on="artifact_storage_path", how="left")
    hits = merged[merged.keyword_hit.fillna(False)].copy()
    hits.to_parquet(KEYWORD_HITS)
    print(f"[download] {len(arts)} artifacts, {errs} errors; "
          f"{hits.artifact_hash.nunique()} keyword-hit artifacts "
          f"across {hits.submission_id.nunique()} devices")
    return hits


# ---------------------------------------------------------------------------
# Phase 3 — LLM adjudication (gemini-2.5-pro), cached per artifact_hash
# ---------------------------------------------------------------------------
_PROMPT = """You are auditing an FDA 510(k)/De Novo decision summary to determine whether \
the SUBJECT device of THIS submission includes a Predetermined Change Control Plan (PCCP) — \
an FDA-authorized envelope of pre-approved future modifications.

Device under review: {device}

Answer has_pccp = true ONLY if the SUBJECT device of this submission includes, incorporates, \
or was cleared with an authorized/submitted PCCP.

Answer has_pccp = false if the text only:
  - cites FDA's PCCP guidance or the concept generally, without this device having one;
  - describes a PCCP belonging to a PREDICATE or reference device, not the subject;
  - states that no PCCP was included / not applicable;
  - expresses a purely future or hypothetical intention to maybe submit one later.

Return JSON: {{"has_pccp": bool, "attribution": "subject"|"predicate"|"none"|"incidental"|"future", \
"evidence": "<short verbatim quote grounding the decision>", "confidence": 0.0-1.0}}

SUMMARY TEXT:
{text}
"""


def _gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    out = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=GEMINI_API_KEY", "--project=benedoc-prod"],
        capture_output=True, text=True, check=True)
    return out.stdout.strip()


def phase_adjudicate(hits: pd.DataFrame, workers: int) -> dict:
    from google import genai
    from google.genai import types

    seen = {}
    if ADJUDICATIONS.exists():
        for line in ADJUDICATIONS.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                seen[r["artifact_hash"]] = r

    client = genai.Client(api_key=_gemini_key())
    cfg = types.GenerateContentConfig(
        temperature=0, response_mime_type="application/json")

    per_artifact = hits.drop_duplicates("artifact_hash")
    todo = [r for r in per_artifact.itertuples(index=False) if r.artifact_hash not in seen]
    print(f"[adjudicate] {len(seen)} cached, {len(todo)} to run")

    def work(rec):
        text = (rec.full_text or "")[:45000]
        prompt = _PROMPT.format(device=rec.device_name or "(unknown)", text=text)
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=cfg)
        obj = json.loads(resp.text)
        return {"artifact_hash": rec.artifact_hash, "submission_id": rec.submission_id,
                "has_pccp": bool(obj.get("has_pccp")),
                "attribution": obj.get("attribution"),
                "evidence": (obj.get("evidence") or "")[:400],
                "confidence": obj.get("confidence")}

    with ThreadPoolExecutor(max_workers=workers) as ex, open(ADJUDICATIONS, "a") as fh:
        futs = {ex.submit(work, r): r for r in todo}
        n = 0
        for f in as_completed(futs):
            try:
                r = f.result()
            except Exception as e:
                r = futs[f]
                print(f"  ! {r.artifact_hash} failed: {str(e)[:100]}")
                continue
            seen[r["artifact_hash"]] = r
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            n += 1
            if n % 25 == 0:
                print(f"[adjudicate] {n}/{len(todo)}")
    return seen


# ---------------------------------------------------------------------------
# Phase 4 — recompute device-level PCCP and diff vs current flag
# ---------------------------------------------------------------------------
def phase_recompute(adj: dict):
    cand = pd.read_parquet(CANDIDATES)
    devices = (cand[cand.has_artifact]
               .groupby("submission_id")
               .agg(is_ai=("is_ai", "max"), yr=("yr", "min"),
                    device_name=("device_name", "first"),
                    current_pccp=("current_pccp", "max"))
               .reset_index())

    adf = pd.DataFrame(adj.values()) if adj else pd.DataFrame(
        columns=["submission_id", "has_pccp", "attribution"])
    subj = adf[(adf.has_pccp) & (adf.attribution == "subject")] if len(adf) else adf
    new_true = set(subj.submission_id) if len(subj) else set()
    devices["new_pccp"] = devices.submission_id.isin(new_true)

    def rates(d, label):
        n = len(d)
        old = int(d.current_pccp.sum())
        new = int(d.new_pccp.sum())
        print(f"  {label:14s} summaries={n:5d}  old={old:3d} ({100*old/n:.2f}%)  "
              f"new={new:3d} ({100*new/n:.2f}%)  Δ=+{new-old}")
        return dict(cohort=label, summaries=n, old=old, new=new,
                    old_pct=round(100*old/n, 2), new_pct=round(100*new/n, 2))

    print("\n=== Device-level PCCP: current flag vs re-adjudicated ===")
    summary = [rates(devices, "software+AI"), rates(devices[devices.is_ai], "AI only")]

    ai = devices[devices.is_ai]
    print("\n=== AI ring PCCP by year (% of AI summaries) ===")
    by_year = []
    for y in range(2018, int(ai.yr.max()) + 1):
        d = ai[ai.yr == y]
        if len(d):
            o, nw = int(d.current_pccp.sum()), int(d.new_pccp.sum())
            print(f"  {y}: old {100*o/len(d):5.2f}%  new {100*nw/len(d):5.2f}%  (n={len(d)})")
            by_year.append(dict(year=y, n=len(d), old=o, new=nw))

    recovered = devices[devices.new_pccp & ~devices.current_pccp]
    downgraded = devices[~devices.new_pccp & devices.current_pccp]
    print(f"\nRecovered (missed by pipeline): {len(recovered)}   "
          f"Downgraded (flag but adjudicated false): {len(downgraded)}")

    devices.to_parquet(RESULT)
    lines = ["# PCCP re-adjudication — software+AI cohort\n",
             "Standalone audit bypassing the pipeline's focused-selection PCCP extraction.\n",
             "## Device-level PCCP rate: current flag vs re-adjudicated\n",
             "| cohort | summaries | old n (%) | new n (%) | Δ |",
             "|---|---|---|---|---|"]
    for s in summary:
        lines.append(f"| {s['cohort']} | {s['summaries']} | {s['old']} ({s['old_pct']}%) "
                     f"| {s['new']} ({s['new_pct']}%) | +{s['new']-s['old']} |")
    lines.append("\n## AI ring, PCCP by year (% of AI summaries)\n")
    lines.append("| year | n | old | new |\n|---|---|---|---|")
    for r in by_year:
        lines.append(f"| {r['year']} | {r['n']} | {r['old']} | {r['new']} |")
    lines.append(f"\nRecovered: **{len(recovered)}**  ·  Downgraded: **{len(downgraded)}**\n")
    lines.append("\n### Recovered devices (missed by the pipeline flag)\n")
    for r in recovered.sort_values("yr").itertuples(index=False):
        ev = adj.get(next((h for h, a in adj.items()
                           if a["submission_id"] == r.submission_id), ""), {})
        lines.append(f"- **{r.submission_id}** ({r.yr}) {r.device_name} — "
                     f"_{ev.get('evidence','')}_")
    REPORT.write_text("\n".join(lines))
    print(f"\nWrote {REPORT}\n      {RESULT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ring", choices=["ai", "sw_ai"], default="sw_ai")
    ap.add_argument("--phase", choices=["candidates", "download", "adjudicate", "recompute", "all"],
                    default="all")
    ap.add_argument("--end-year", type=int, default=2025,
                    help="inclusive upper year bound (2025 = paper window; 2026 = incl. YTD)")
    ap.add_argument("--limit", type=int, default=0, help="cap keyword-hit artifacts (smoke test)")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    df = phase_candidates(args.ring, args.end_year) if args.phase in ("candidates", "all") \
        else pd.read_parquet(CANDIDATES)

    if args.phase in ("download", "all"):
        hits = phase_download(df, args.workers)
    elif args.phase in ("adjudicate", "recompute"):
        hits = pd.read_parquet(KEYWORD_HITS)
    else:
        return
    if args.limit:
        keep = hits.drop_duplicates("artifact_hash").head(args.limit).artifact_hash
        hits = hits[hits.artifact_hash.isin(keep)]

    if args.phase in ("adjudicate", "all"):
        adj = phase_adjudicate(hits, args.workers)
    else:
        adj = {}
        if ADJUDICATIONS.exists():
            for line in ADJUDICATIONS.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    adj[r["artifact_hash"]] = r

    if args.phase in ("recompute", "all"):
        phase_recompute(adj)


if __name__ == "__main__":
    main()
