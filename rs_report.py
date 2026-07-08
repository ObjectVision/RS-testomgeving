"""
rs_report.py -- genereer een HTML-rapport uit een of meer compare.result.json's.

Het oordeel (ok / binnen tolerantie / verschilt) wordt HIER geveld, niet tijdens
de vergelijking: toleranties tunen = alleen rapport opnieuw genereren, geen rerun.
Zelfde filosofie en huisstijl als GeoDMS-Test batch/generic/regression.py.

Gebruik:
    python rs_report.py <compare.result.json> [...] [--tolerances tolerances.json]
                        [--out report.html]

tolerances.json:
    {
      "default": { "cell_pct": 0.0 },
      "rules": [ { "match": "*Landgebruikskaart*", "cell_pct": 0.05 } ]
    }
Eerste passende rule (fnmatch op comparison-naam) wint; anders default.
"""

import argparse
import fnmatch
import html
import json
import os
import re

CSS = """
  body { font-family: "Aptos","Segoe UI Variable","Segoe UI",system-ui,sans-serif;
         color:#1c1c1a; background:#fbfbfa; margin:20px; font-size:13px; }
  h1 { font-size:18px; font-weight:600; margin:0 0 4px 0; }
  .meta { color:#6b6b64; font-size:11.5px; margin-bottom:2px; }
  .summary { margin:14px 0 18px 0; font-size:13px; }
  .summary .pill { margin-right:8px; }
  table.report { border-collapse:separate; border-spacing:0; width:100%; }
  table.report td, table.report th { padding:7px 10px; vertical-align:top;
         border-bottom:1px solid #ececE6; text-align:left; }
  tr.hdr th { border-bottom:1.5px solid #d7d7d0; position:sticky; top:0;
         background:#fbfbfa; font-weight:600; }
  td.name { font-weight:500; max-width:420px; word-break:break-all; }
  td.name .notes { font-weight:400; font-style:italic; color:#a32d2d;
         font-size:11px; margin-top:3px; }
  td.cell { border-left:3px solid transparent; white-space:nowrap; }
  td.cell.ok { background:#d6efce; border-left-color:#2e9e5b; }
  td.cell.fail { background:#ffd1d1; border-left-color:#d6453d; }
  td.cell.warn { background:#ffe4b8; border-left-color:#d98a1f; }
  td.cell.skip { background:#ececE8; border-left-color:#b8b8b0; }
  .pill { display:inline-flex; align-items:center; font-size:11.5px; font-weight:500;
         padding:2px 10px; border-radius:999px; color:#fff; }
  .pill.ok { background:#2e9e5b; } .pill.fail { background:#d6453d; }
  .pill.warn { background:#cf8420; } .pill.skip { background:#9a9a92; }
  .code { color:#a6a69e; font-size:11px; margin-left:7px; }
  .metrics { color:#444441; font-size:12px; white-space:nowrap;
         font-variant-numeric:tabular-nums; }
  .metrics .m { display:block; }
  .metrics .changed { color:#a32d2d; font-weight:500; }
  .thumbs { display:flex; flex-wrap:nowrap; gap:6px; }
  .thumbs a { flex:0 0 auto; text-align:center; }
  .thumbs img { height:150px; border:1px solid #ddddd6;
         background:#fff; image-rendering:pixelated; }
  .thumbs .lbl { display:block; color:#86867e; font-size:10.5px; }
  .links { margin-top:6px; font-size:11px; }
  .links a { color:#9a9a92; text-decoration:none; margin-right:9px; }
  .links a:hover { color:#534ab7; text-decoration:underline; }
"""

DEFAULT_TOLERANCES = {"default": {"cell_pct": 0.0}, "rules": []}


def load_tolerances(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf8") as f:
            return json.load(f)
    return DEFAULT_TOLERANCES


def tolerance_for(name: str, tolerances: dict) -> dict:
    for rule in tolerances.get("rules", []):
        if fnmatch.fnmatch(name, rule.get("match", "")):
            return rule
    return tolerances.get("default", {"cell_pct": 0.0})


def fmt_num(x) -> str:
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15:
            return f"{int(x):,}"
        return f"{x:,.4g}" if abs(x) >= 0.001 or x == 0 else f"{x:.3e}"
    return f"{x:,}"


def judge(comp: dict, tol: dict):
    """(css_class, label, note) voor een comparison, conform verdict-regels:
    nooit een holle OK -- meetfout of structuurverschil is rood, niet stil."""
    if comp.get("compare") == "error":
        return ("fail", "error", "; ".join(comp.get("notes", [])))
    metrics = {m["name"]: m for m in comp.get("metrics", [])}
    if "shape_equal" in metrics and not metrics["shape_equal"].get("value"):
        return ("fail", "shape differs", "")
    if "structure_equal" in metrics and not metrics["structure_equal"].get("value"):
        return ("fail", "structure differs", "")
    if "file_equal" in metrics:
        return ("ok", "identical", "") if metrics["file_equal"].get("value") \
            else ("fail", "output differs", "binary compare")
    if "cells" in metrics:
        m = metrics["cells"]
        n_total, n_diff = m.get("n_total", 0), m.get("n_diff", 0)
        pct = 100.0 * n_diff / n_total if n_total else 0.0
        if n_diff == 0:
            return ("ok", "identical", "")
        if pct <= tol.get("cell_pct", 0.0):
            return ("ok", "within tolerance", f"{pct:.4g}% <= {tol.get('cell_pct')}%")
        return ("fail", "output differs", f"{pct:.4g}% of cells")
    if not comp.get("metrics"):
        return ("warn", "not validated", "no metrics")
    return ("ok", "ok", "")


def metrics_html(comp: dict) -> str:
    parts = []
    for m in comp.get("metrics", []):
        if "n_total" in m:
            n_total, n_diff = m.get("n_total", 0), m.get("n_diff", 0)
            pct = 100.0 * n_diff / n_total if n_total else 0.0
            cls = "m changed" if n_diff else "m"
            parts.append(f'<span class="{cls}">{html.escape(m["name"])}: '
                         f'{fmt_num(n_diff)} / {fmt_num(n_total)} ({pct:.4g}%)</span>')
        elif "value" in m and m["name"] not in ("shape_equal", "structure_equal", "file_equal"):
            parts.append(f'<span class="m">{html.escape(m["name"])}: '
                         f'{fmt_num(m["value"])}</span>')
    return f'<div class="metrics">{"".join(parts)}</div>' if parts else ""


def artifacts_html(comp: dict, base_dir_rel: str) -> tuple:
    """(thumbs_html, links_html); paden relatief t.o.v. de rapportlocatie."""
    thumbs, links = [], []
    labels = {"png_a": "A", "png_b": "B", "png_diff": "diff (rood)"}
    for art in comp.get("artifacts", []):
        path = f"{base_dir_rel}/{art['path']}" if base_dir_rel else art["path"]
        esc = html.escape(path)
        kind = art.get("kind", "")
        if kind in labels:
            thumbs.append(f'<a href="{esc}" target="_blank"><img src="{esc}" '
                          f'title="{labels[kind]}"><span class="lbl">{labels[kind]}</span></a>')
        else:
            links.append(f'<a href="{esc}" target="_blank">{html.escape(kind)}</a>')
    thumbs_html = f'<div class="thumbs">{"".join(thumbs)}</div>' if thumbs else ""
    links_html = f'<div class="links">{"".join(links)}</div>' if links else ""
    return thumbs_html, links_html


VERDICT_ORDER = {"fail": 0, "warn": 1, "ok": 2, "skip": 3}

# Inhoudelijke rapportvolgorde (eerste match wint): (glob op naam, rang).
# Binnen gelijke rang wordt op naam gesorteerd (jaar zit in het pad, dus
# Y2030 komt vanzelf voor Y2040 binnen dezelfde groep).
ORDER_RULES = [
    ("*StandY2030*SubSector_rel*", 0),
    ("*StandY2030*OP_rel*",        1),
    ("*StandY2040*SubSector_rel*", 2),
    ("*StandY2040*OP_rel*",        3),
    ("*StandY2030*/Wonen/*",       4),
    ("*StandY2030*/Werken/*",      5),
    ("*StandY2040*/Wonen/*",       6),
    ("*StandY2040*/Werken/*",      7),
    ("*/PandFootprint/*",          8),  # 2030 vóór 2040 via naam-sortering
]
ORDER_FALLBACK = 99


def content_rank(name: str) -> int:
    for pat, rank in ORDER_RULES:
        if fnmatch.fnmatch(name, pat):
            return rank
    return ORDER_FALLBACK


def render(results: list, tolerances: dict, out_path: str) -> str:
    out_dir = os.path.dirname(os.path.abspath(out_path))
    body_rows, counts = [], {"ok": 0, "fail": 0, "warn": 0}
    header_blocks = []

    for result_fn, doc in results:
        base_dir_rel = os.path.relpath(
            os.path.dirname(os.path.abspath(result_fn)), out_dir).replace("\\", "/")
        if base_dir_rel == ".":
            base_dir_rel = ""
        run_a, run_b = doc.get("run_a", {}), doc.get("run_b", {})
        header_blocks.append(
            f'<h1>{html.escape(doc.get("title", "run comparison"))}</h1>'
            f'<div class="meta">A = {html.escape(run_a.get("name",""))} '
            f'({html.escape(run_a.get("path",""))})</div>'
            f'<div class="meta">B = {html.escape(run_b.get("name",""))} '
            f'({html.escape(run_b.get("path",""))})</div>'
            f'<div class="meta">generated {html.escape(doc.get("generated",""))}</div>')

        rows = []
        for comp in doc.get("comparisons", []):
            tol = tolerance_for(comp["name"], tolerances)
            cls, label, note = judge(comp, tol)
            counts[cls] = counts.get(cls, 0) + 1
            thumbs, links = artifacts_html(comp, base_dir_rel)
            notes = "; ".join(comp.get("notes", []))
            notes_html = f'<div class="notes">{html.escape(notes)}</div>' if notes else ""
            note_html = f'<span class="code">{html.escape(note)}</span>' if note else ""
            rows.append((content_rank(comp["name"]), comp["name"], f"""
<tr>
  <td class="name">{html.escape(comp["name"])}{notes_html}</td>
  <td class="cell {cls}"><span class="pill {cls}">{html.escape(label)}</span>{note_html}</td>
  <td>{metrics_html(comp)}{links}</td>
  <td>{thumbs}</td>
</tr>"""))
        for only, run in ((doc.get("only_in_a", []), "A"), (doc.get("only_in_b", []), "B")):
            for rel in only:
                counts["warn"] += 1
                rows.append((ORDER_FALLBACK, rel, f"""
<tr>
  <td class="name">{html.escape(rel)}</td>
  <td class="cell warn"><span class="pill warn">only in {run}</span></td>
  <td></td><td></td>
</tr>"""))
        rows.sort(key=lambda r: (r[0], r[1]))  # inhoudelijke rang, dan naam (jaar)
        body_rows.extend(r[2] for r in rows)

    summary = (f'<div class="summary">'
               f'<span class="pill fail">{counts["fail"]} differ</span>'
               f'<span class="pill warn">{counts["warn"]} warn</span>'
               f'<span class="pill ok">{counts["ok"]} ok</span></div>')

    doc_html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>RSopen run comparison</title>
<style>{CSS}</style></head>
<body>
{"".join(header_blocks)}
{summary}
<table class="report">
<tr class="hdr"><th>Indicator / bestand</th><th>Verdict</th><th>Metrics</th><th>A | B | verschil</th></tr>
{"".join(body_rows)}
</table>
</body></html>"""
    with open(out_path, "w", encoding="utf8") as f:
        f.write(doc_html)
    print(f"[+] rapport: {out_path}  ({counts['fail']} differ, "
          f"{counts['warn']} warn, {counts['ok']} ok)")
    return out_path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("results", nargs="+", help="compare.result.json bestand(en)")
    ap.add_argument("--tolerances", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tolerances.json"))
    ap.add_argument("--out", default=None,
                    help="default: report.html naast de eerste result.json")
    args = ap.parse_args(argv)

    results = []
    for fn in args.results:
        with open(fn, encoding="utf8") as f:
            results.append((fn, json.load(f)))
    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.results[0])),
                                   "report.html")
    render(results, load_tolerances(args.tolerances), out)


if __name__ == "__main__":
    main()
