"""
rs_indicators.py -- buurt-niveau vergelijkingsindicatoren voor twee RSopen-runs.

Gebaseerd op "Voorstel voor validatie van Ruimtescanner" (Claassens, maart 2026),
omgebouwd van model-vs-observatie naar run-A-vs-run-B. Beantwoordt per indicator:
plaatst run B de woninggroei in dezelfde buurten, gebruikt hij vergelijkbare
hoeveelheid ruimte, en bouwt hij even compact?

Vereist dat beide runs op HETZELFDE grid staan (zelfde bbox/resolutie).

Gebruik:
    python rs_indicators.py --run-a C:/LocalData/RSopen_pre508 --run-b C:/LocalData/RSopen_NL2120
        --buurt C:/LocalData/RS_compare/Buurt_per_AdminDomain_Noord_Holland.tif
        [--buurt-namen buurtnamen.csv] [--zichtjaar Y2040] [--suffix Noord_Holland]
        [--casus WLO_hoog_BAU] --out C:/LocalData/RS_compare/indicatoren

Verwachte run-structuur (ontkoppelde bestanden):
    <run>/BaseData/StandBasisjaar/Wonen/<subsector>_<suffix>.tif
    <run>/Allocatie/<casus>/Stand<zichtjaar>/Wonen/<subsector>_<suffix>_SS-*.tif
"""

import argparse
import csv
import glob
import html
import json
import os

import numpy as np
import tifffile

CELL = 25.0       # celgrootte in meter
CELL_HA = 0.0625  # 25m-cel in hectare

WONEN_SUBSECTOREN = ["eengezins_SocialeHuur", "eengezins_VrijeSector",
                     "meergezins_SocialeHuur", "meergezins_VrijeSector"]
WERKEN_SUBSECTOREN = ["Detailhandel", "Logistiek", "Nijverheid",
                      "Ov_consumentendiensten", "Overheid_kw_diensten",
                      "Zak_dienstverlening"]


# ------------------------------------------------------------------ inlezen

def read_tif(path):
    with tifffile.TiffFile(path) as tf:
        page = tf.pages[0]
        arr = page.asarray()
        scale = page.tags.get(33550)
        tie = page.tags.get(33922)
        geo = None
        if scale is not None and tie is not None:
            tp = tie.value
            geo = (scale.value[0], scale.value[1],
                   tp[3] - tp[0] * scale.value[0], tp[4] + tp[1] * scale.value[1])
    return arr, geo


def find_one(pattern):
    hits = sorted(glob.glob(pattern))
    if not hits:
        raise FileNotFoundError(f"geen bestand voor patroon: {pattern}")
    return hits[-1]  # hoogste SS-suffix = laatste sequence


def load_stand(run_dir, casus, stand, suffix, categorie, subsectoren, ref_geo=None):
    """Som eenheden over de subsectoren; stand = 'basisjaar' of bijv. 'Y2040';
    categorie = 'Wonen' of 'Werken'."""
    total = None
    for ss in subsectoren:
        if stand == "basisjaar":
            pat = os.path.join(run_dir, "BaseData", "StandBasisjaar", categorie,
                               f"{ss}_{suffix}.tif")
        else:
            pat = os.path.join(run_dir, "Allocatie", casus, f"Stand{stand}",
                               categorie, f"{ss}_{suffix}_SS-*.tif")
        arr, geo = read_tif(find_one(pat))
        arr = np.nan_to_num(arr.astype(np.float64))
        if ref_geo is not None and geo is not None and not np.allclose(geo, ref_geo):
            raise ValueError(f"grid van {pat} wijkt af van referentie: {geo} vs {ref_geo}\n"
                             f"-> runs staan niet op hetzelfde grid; eerst gelijk trekken.")
        total = arr if total is None else total + arr
    return total, geo


# ------------------------------------------------------------ buurt-aggregatie

def buurt_sums(values, buurt, n_buurt):
    """Som van celwaarden per buurt (buurt = int-grid, negatief/null = geen buurt)."""
    sel = buurt >= 0
    return np.bincount(buurt[sel], weights=values[sel], minlength=n_buurt)


def spearman(a, b):
    def rank(x):
        order = np.argsort(x, kind="stable")
        ranks = np.empty(len(x))
        ranks[order] = np.arange(len(x), dtype=np.float64)
        # ties: gemiddelde rang
        uniq, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
        csum = np.concatenate([[0], np.cumsum(cnt)])
        avg = (csum[:-1] + csum[1:] - 1) / 2.0
        return avg[inv]
    ra, rb = rank(a), rank(b)
    ra -= ra.mean(); rb -= rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / denom) if denom else float("nan")


def gini_lorenz(x):
    """Gini + lorenz-punten (cum. aandeel buurten, cum. aandeel groei) voor x >= 0."""
    x = np.clip(x, 0, None)
    x = np.sort(x)[::-1]  # grootste eerst (concentratie-perspectief)
    tot = x.sum()
    if tot <= 0:
        return float("nan"), [(0, 0), (1, 1)]
    cum = np.cumsum(x) / tot
    n = len(x)
    fr = np.arange(1, n + 1) / n
    gini = float(1 - 2 * np.trapezoid(np.concatenate([[0], 1 - cum[::-1]]),
                                      np.concatenate([[0], fr])))
    step = max(1, n // 200)
    pts = [(0.0, 0.0)] + [(float(fr[i]), float(cum[i])) for i in range(0, n, step)] + [(1.0, 1.0)]
    return gini, pts


# ------------------------------------------------------------------ SVG-plots

SVG_W, SVG_H, MARG = 420, 420, 48


def _axes(title, xlab, ylab, xmax, ymax):
    return (f'<text x="{SVG_W/2}" y="16" text-anchor="middle" font-size="13" '
            f'font-weight="600">{html.escape(title)}</text>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{SVG_W-10}" y2="{SVG_H-MARG}" stroke="#888"/>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{MARG}" y2="24" stroke="#888"/>'
            f'<text x="{SVG_W/2}" y="{SVG_H-8}" text-anchor="middle" font-size="11">{html.escape(xlab)}</text>'
            f'<text x="12" y="{SVG_H/2}" text-anchor="middle" font-size="11" '
            f'transform="rotate(-90 12 {SVG_H/2})">{html.escape(ylab)}</text>'
            f'<text x="{MARG}" y="{SVG_H-MARG+14}" font-size="10" text-anchor="middle">0</text>'
            f'<text x="{SVG_W-14}" y="{SVG_H-MARG+14}" font-size="10" text-anchor="end">{xmax:,.0f}</text>'
            f'<text x="{MARG-4}" y="28" font-size="10" text-anchor="end">{ymax:,.0f}</text>')


def svg_scatter(title, xlab, ylab, x, y, vmax=None, include_zero=False,
                labels=None, label_top=8):
    """Scatter met 45-gradenlijn; labels = buurtnamen, waarvan de label_top
    grootste afwijkers van de diagonaal een tekstlabel krijgen (anti-overlap)."""
    if vmax is None:
        vmax = max(float(np.max(x, initial=0)), float(np.max(y, initial=0)), 1.0)
    def px(v): return MARG + (min(v, vmax) / vmax) * (SVG_W - MARG - 10)
    def py(v): return (SVG_H - MARG) - (min(v, vmax) / vmax) * (SVG_H - MARG - 24)
    pts = "".join(f'<circle cx="{px(a):.1f}" cy="{py(b):.1f}" r="2.4" '
                  f'fill="#534ab7" fill-opacity="0.45"/>'
                  for a, b in zip(x, y) if include_zero or a > 0 or b > 0)
    diag = (f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(vmax)}" y2="{py(vmax)}" '
            f'stroke="#d6453d" stroke-dasharray="5,4"/>')
    txt = ""
    TOP_GUARD = 34  # geen labels in de titelstrook bovenaan
    if labels is not None and len(x):
        order = np.argsort(-np.abs(np.asarray(x) - np.asarray(y)))
        placed = []
        for i in order:
            if len(placed) >= label_top or np.abs(x[i] - y[i]) <= 0:
                break
            cx, cy = px(x[i]), py(y[i])
            # label boven de punt, maar onder de punt als dat in de titelstrook zou vallen
            ly = cy - 4 if cy - 4 >= TOP_GUARD else cy + 13
            if any(abs(ly - qy) < 12 and abs(cx - qx) < 130 for qx, qy in placed):
                continue  # zou over een eerder label vallen
            placed.append((cx, ly))
            anchor = "end" if cx > SVG_W * 0.55 else "start"
            dx = -5 if anchor == "end" else 5
            txt += (f'<text x="{cx+dx:.0f}" y="{ly:.0f}" font-size="9.5" '
                    f'fill="#444" text-anchor="{anchor}">{html.escape(str(labels[i]))}</text>')
    return (f'<svg width="{SVG_W}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'{_axes(title, xlab, ylab, vmax, vmax)}{diag}{pts}{txt}</svg>')


def svg_stacked_bars(title, ylab, labels, verdicht, uitbreid):
    """Twee gestapelde balken (per run): verdichting + uitbreiding; legenda rechts naast de balken."""
    vmax = max(v + u for v, u in zip(verdicht, uitbreid)) or 1.0
    def py(v): return (SVG_H - MARG) - (v / vmax) * (SVG_H - MARG - 44)
    bw = 90
    bars_end = MARG + 40 + len(labels) * 150
    total_w = bars_end + 260
    body = ""
    for i, (lab, v, u) in enumerate(zip(labels, verdicht, uitbreid)):
        cx = MARG + 40 + i * 150
        body += (f'<rect x="{cx}" y="{py(v)}" width="{bw}" height="{py(0)-py(v):.1f}" fill="#d98a1f"/>'
                 f'<rect x="{cx}" y="{py(v+u)}" width="{bw}" height="{py(v)-py(v+u):.1f}" fill="#534ab7"/>'
                 f'<text x="{cx+bw/2}" y="{SVG_H-MARG+16}" text-anchor="middle" font-size="12">{html.escape(lab)}</text>'
                 f'<text x="{cx+bw/2}" y="{py(v+u)-6}" text-anchor="middle" font-size="11">{v+u:,.0f}</text>')
    legend = (f'<rect x="{bars_end+30}" y="{SVG_H/2-24}" width="12" height="12" fill="#d98a1f"/>'
              f'<text x="{bars_end+48}" y="{SVG_H/2-14}" font-size="11">verdichting (bestaande wooncellen)</text>'
              f'<rect x="{bars_end+30}" y="{SVG_H/2-2}" width="12" height="12" fill="#534ab7"/>'
              f'<text x="{bars_end+48}" y="{SVG_H/2+8}" font-size="11">uitbreiding (nieuwe wooncellen)</text>')
    return (f'<svg width="{total_w}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{(bars_end+MARG)/2}" y="16" text-anchor="middle" font-size="13" font-weight="600">{html.escape(title)}</text>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{bars_end}" y2="{SVG_H-MARG}" stroke="#888"/>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{MARG}" y2="30" stroke="#888"/>'
            f'<text x="12" y="{SVG_H/2}" text-anchor="middle" font-size="11" transform="rotate(-90 12 {SVG_H/2})">{html.escape(ylab)}</text>'
            f'<text x="{MARG-4}" y="34" font-size="10" text-anchor="end">{vmax:,.0f}</text>'
            f'{legend}{body}</svg>')


CLUSTER_KLASSEN = [("< 0,4 ha (snippers)", 0, 0.4), ("0,4 – 2 ha", 0.4, 2.0), ("≥ 2 ha", 2.0, float("inf"))]


def cluster_sizes(mask):
    """Groottes (ha) van aaneengesloten (8-connectiviteit) TRUE-clusters."""
    from scipy import ndimage
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return np.array([])
    return np.bincount(lab.ravel())[1:] * CELL_HA


def svg_cluster_bars(title, label_a, sizes_a, label_b, sizes_b, ylab="aandeel nieuw areaal"):
    """Aandeel van het nieuwe areaal per clustergrootteklasse, A naast B."""
    def shares(sizes):
        tot = sizes.sum() or 1.0
        return [sizes[(sizes >= lo) & (sizes < hi)].sum() / tot for _, lo, hi in CLUSTER_KLASSEN], tot
    sh_a, tot_a = shares(sizes_a)
    sh_b, tot_b = shares(sizes_b)
    vmax = max(max(sh_a), max(sh_b), 0.01)
    def py(v): return (SVG_H - MARG) - (v / vmax) * (SVG_H - MARG - 44)
    bw, gap, x0 = 52, 150, MARG + 40
    body = ""
    for i, (klasse, _, _) in enumerate(CLUSTER_KLASSEN):
        xa = x0 + i * gap
        body += (f'<rect x="{xa}" y="{py(sh_a[i])}" width="{bw}" height="{py(0)-py(sh_a[i]):.1f}" fill="#d98a1f"/>'
                 f'<rect x="{xa+bw+4}" y="{py(sh_b[i])}" width="{bw}" height="{py(0)-py(sh_b[i]):.1f}" fill="#534ab7"/>'
                 f'<text x="{xa+bw+2}" y="{SVG_H-MARG+16}" text-anchor="middle" font-size="11">{html.escape(klasse)}</text>'
                 f'<text x="{xa+bw/2}" y="{py(sh_a[i])-4}" text-anchor="middle" font-size="10">{sh_a[i]:.0%}</text>'
                 f'<text x="{xa+bw*1.5+4}" y="{py(sh_b[i])-4}" text-anchor="middle" font-size="10">{sh_b[i]:.0%}</text>')
    bars_end = x0 + len(CLUSTER_KLASSEN) * gap
    legend = (f'<rect x="{bars_end+20}" y="{SVG_H/2-24}" width="12" height="12" fill="#d98a1f"/>'
              f'<text x="{bars_end+38}" y="{SVG_H/2-14}" font-size="11">{html.escape(label_a)} ({len(sizes_a):,} clusters)</text>'
              f'<rect x="{bars_end+20}" y="{SVG_H/2-2}" width="12" height="12" fill="#534ab7"/>'
              f'<text x="{bars_end+38}" y="{SVG_H/2+8}" font-size="11">{html.escape(label_b)} ({len(sizes_b):,} clusters)</text>')
    total_w = bars_end + 280
    return (f'<svg width="{total_w}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{(bars_end+MARG)/2}" y="16" text-anchor="middle" font-size="13" font-weight="600">{html.escape(title)}</text>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{bars_end}" y2="{SVG_H-MARG}" stroke="#888"/>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{MARG}" y2="30" stroke="#888"/>'
            f'<text x="12" y="{SVG_H/2}" text-anchor="middle" font-size="11" transform="rotate(-90 12 {SVG_H/2})">{html.escape(ylab)}</text>'
            f'{legend}{body}</svg>')


def svg_metric_bars(title, metrics, label_a, label_b):
    """metrics: list van (naam, waarde_a, waarde_b, fmt). Elke metriek eigen
    paneel met op-max-genormaliseerde A/B-balken; waardelabels erboven."""
    n = len(metrics)
    panel_w = 210
    total_w = MARG + n * panel_w + 200
    bw = 46
    def py(frac): return (SVG_H - MARG) - frac * (SVG_H - MARG - 40)
    body = ""
    for i, (naam, va, vb, fmt) in enumerate(metrics):
        vmax = max(va, vb, 1e-9)
        x0 = MARG + 30 + i * panel_w
        for j, (val, col) in enumerate([(va, "#d98a1f"), (vb, "#534ab7")]):
            bx = x0 + j * (bw + 8)
            body += (f'<rect x="{bx}" y="{py(val/vmax):.1f}" width="{bw}" '
                     f'height="{py(0)-py(val/vmax):.1f}" fill="{col}"/>'
                     f'<text x="{bx+bw/2}" y="{py(val/vmax)-4:.1f}" text-anchor="middle" '
                     f'font-size="10">{val:{fmt}}</text>')
        body += (f'<text x="{x0+bw+4}" y="{SVG_H-MARG+16}" text-anchor="middle" '
                 f'font-size="11">{html.escape(naam)}</text>')
    lx = MARG + 30 + n * panel_w + 10
    legend = (f'<rect x="{lx}" y="{SVG_H/2-24}" width="12" height="12" fill="#d98a1f"/>'
              f'<text x="{lx+18}" y="{SVG_H/2-14}" font-size="11">{html.escape(label_a)}</text>'
              f'<rect x="{lx}" y="{SVG_H/2-2}" width="12" height="12" fill="#534ab7"/>'
              f'<text x="{lx+18}" y="{SVG_H/2+8}" font-size="11">{html.escape(label_b)}</text>')
    return (f'<svg width="{total_w}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'<text x="{total_w/2}" y="16" text-anchor="middle" font-size="13" font-weight="600">{html.escape(title)}</text>'
            f'<line x1="{MARG}" y1="{SVG_H-MARG}" x2="{MARG+n*panel_w}" y2="{SVG_H-MARG}" stroke="#888"/>'
            f'{legend}{body}</svg>')


def edge_density(mask):
    """Randdichtheid (m rand per ha) van een binair patroon: hoeveel van het
    oppervlak grenst aan niet-patroon. Hoog = versnipperd/lint, laag = compact.
    Rand = 25m x aantal 4-buur-paren waar precies een van beide cellen TRUE is."""
    a = mask.astype(np.int8)
    n_edges = int(np.sum(a[:, :-1] != a[:, 1:]) + np.sum(a[:-1, :] != a[1:, :]))
    area_ha = mask.sum() * CELL_HA
    return (n_edges * CELL / area_ha) if area_ha else float("nan")


def lint_share(mask):
    """Aandeel van het patroon-areaal in 'linten': aaneengesloten clusters die
    langgerekt en smal zijn (elongatie >= 3 en gemiddelde breedte <= 2 cellen).
    Grootte alleen vangt geen linten; een 2ha-sliert langs een weg passeert de
    groottedrempel maar is precies het te vermijden patroon."""
    from scipy import ndimage
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    if n == 0:
        return 0.0
    tot = mask.sum()
    lint_cells = 0
    for i in range(1, n + 1):
        rows, cols = np.nonzero(lab == i)
        area = len(rows)
        if area < 4:
            continue
        pts = np.stack([rows, cols], axis=1).astype(np.float64)
        cov = np.cov(pts.T)
        ev = np.sort(np.linalg.eigvalsh(cov))[::-1]
        elong = np.sqrt(ev[0] / ev[1]) if ev[1] > 1e-9 else float("inf")
        # bounding-box-lengte als proxy voor breedte: area / langste as
        span = max(rows.max() - rows.min(), cols.max() - cols.min()) + 1
        breedte = area / span
        if elong >= 3 and breedte <= 2.0:
            lint_cells += area
    return lint_cells / tot if tot else 0.0


def afstand_tot_bestaand(nieuw_mask, bestaand_mask):
    """Afstand (m) van elke nieuwe cel tot dichtstbijzijnde bestaand-bebouwde cel.
    Vangt 'leapfrog': compacte maar vrij-in-het-veld liggende ontwikkeling die de
    clustermaten niet zien."""
    from scipy import ndimage
    dist = ndimage.distance_transform_edt(~bestaand_mask) * CELL
    return dist[nieuw_mask]


def svg_ecdf(title, xlab, curves, xmax):
    """curves: list van (label, kleur, waarden-array). ECDF-lijnen."""
    def px(v): return MARG + (min(v, xmax) / xmax) * (SVG_W - MARG - 10)
    def py(v): return (SVG_H - MARG) - v * (SVG_H - MARG - 24)
    body = ""
    legend_y = SVG_H - MARG - 40  # rechtsonder, waar de ECDF-curve al plat ligt
    for label, color, vals in curves:
        if len(vals) == 0:
            continue
        sv = np.sort(vals)
        step = max(1, len(sv) // 300)
        pts = [(0, 0)] + [(float(sv[i]), (i + 1) / len(sv)) for i in range(0, len(sv), step)] + [(float(sv[-1]), 1.0)]
        d = "M" + " L".join(f"{px(a):.1f},{py(b):.1f}" for a, b in pts)
        body += f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>'
        body += (f'<rect x="{SVG_W-170}" y="{legend_y-9}" width="12" height="3" fill="{color}"/>'
                 f'<text x="{SVG_W-152}" y="{legend_y-4}" font-size="11">{html.escape(label)}</text>')
        legend_y += 16
    return (f'<svg width="{SVG_W}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'{_axes(title, xlab, "cum. aandeel nieuwe cellen", xmax, 1)}{body}</svg>')


def svg_lorenz(title, curves):
    """curves: list van (label, kleur, punten)."""
    def px(v): return MARG + v * (SVG_W - MARG - 10)
    def py(v): return (SVG_H - MARG) - v * (SVG_H - MARG - 24)
    body = (f'<line x1="{px(0)}" y1="{py(0)}" x2="{px(1)}" y2="{py(1)}" '
            f'stroke="#bbb" stroke-dasharray="5,4"/>')
    legend_y = 40
    for label, color, pts in curves:
        d = "M" + " L".join(f"{px(a):.1f},{py(b):.1f}" for a, b in pts)
        body += f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>'
        body += (f'<rect x="{SVG_W-170}" y="{legend_y-9}" width="12" height="3" fill="{color}"/>'
                 f'<text x="{SVG_W-152}" y="{legend_y-4}" font-size="11">{html.escape(label)}</text>')
        legend_y += 16
    return (f'<svg width="{SVG_W}" height="{SVG_H}" xmlns="http://www.w3.org/2000/svg">'
            f'{_axes(title, "cum. aandeel buurten (grootste groei eerst)", "cum. aandeel woninggroei", 1, 1)}'
            f'{body}</svg>')


# ------------------------------------------------------------------ hoofdloop

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--run-a", required=True)
    ap.add_argument("--run-b", required=True)
    ap.add_argument("--name-a", default="A")
    ap.add_argument("--name-b", default="B")
    ap.add_argument("--buurt", required=True, help="tif met buurt-id per cel (zelfde grid)")
    ap.add_argument("--buurt-namen", default=None, help="csv met buurtnamen (rijnr = id)")
    ap.add_argument("--zichtjaar", default="Y2040")
    ap.add_argument("--casus", default="WLO_hoog_BAU")
    ap.add_argument("--suffix", default="Noord_Holland")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)

    buurt, geo_ref = read_tif(args.buurt)
    if np.issubdtype(buurt.dtype, np.unsignedinteger):
        null = np.iinfo(buurt.dtype).max
        buurt = np.where(buurt == null, -1, buurt.astype(np.int64))
    else:
        buurt = buurt.astype(np.int64)
    n_buurt = int(buurt.max()) + 1

    namen = None
    if args.buurt_namen and os.path.exists(args.buurt_namen):
        with open(args.buurt_namen, encoding="utf8", errors="replace") as f:
            head = f.read(2048); f.seek(0)
            rows = list(csv.reader(f, delimiter=";" if head.count(";") > head.count(",") else ","))
        def clean(v):
            return v.strip().strip("'\"").replace("_", " ")
        hdr = [clean(h).lower() for h in rows[0]]
        i_id = hdr.index("id") if "id" in hdr else 0
        i_nm = hdr.index("name") if "name" in hdr else 1
        i_gm = next((i for i, h in enumerate(hdr) if "gemeente" in h), None)
        namen = {}
        for r in rows[1:]:
            if len(r) <= max(i_id, i_nm):
                continue
            try:
                bid = int(clean(r[i_id]))
            except ValueError:
                continue
            nm = clean(r[i_nm])
            if i_gm is not None and len(r) > i_gm and clean(r[i_gm]):
                nm = f"{nm} ({clean(r[i_gm])})"
            namen[bid] = nm

    def buurt_label(i):
        return namen.get(i, f"buurt {i}") if namen else f"buurt {i}"

    runs = {}
    for tag, rdir, label in (("a", args.run_a, args.name_a), ("b", args.run_b, args.name_b)):
        w0, geo = load_stand(rdir, args.casus, "basisjaar", args.suffix, "Wonen", WONEN_SUBSECTOREN, geo_ref)
        w1, _ = load_stand(rdir, args.casus, args.zichtjaar, args.suffix, "Wonen", WONEN_SUBSECTOREN, geo_ref)
        if w0.shape != buurt.shape:
            raise ValueError(f"buurt-grid {buurt.shape} != stand-grid {w0.shape}")
        # werken: banen per subsector; optioneel (kan ontbreken als sector uit staat)
        try:
            j0, _ = load_stand(rdir, args.casus, "basisjaar", args.suffix, "Werken", WERKEN_SUBSECTOREN, geo_ref)
            j1, _ = load_stand(rdir, args.casus, args.zichtjaar, args.suffix, "Werken", WERKEN_SUBSECTOREN, geo_ref)
        except FileNotFoundError:
            j0 = j1 = None
        woon0 = w0 > 0
        nieuw_cel = (w1 > 0) & ~woon0
        groei = np.clip(w1 - w0, 0, None)
        verdicht_cel = woon0 & (groei > 0)
        werk0 = (j0 > 0) if j0 is not None else np.zeros_like(woon0)
        bestaand0 = woon0 | werk0  # bestaand bebouwd basisjaar (voor leapfrog-afstand)
        rec = {
            "label": label,
            "dW": buurt_sums(w1 - w0, buurt, n_buurt),
            "groei_verdicht": buurt_sums(np.where(woon0, groei, 0), buurt, n_buurt),
            "groei_uitbreid": buurt_sums(np.where(nieuw_cel, w1, 0), buurt, n_buurt),
            "n_nieuwe_cellen": buurt_sums(nieuw_cel.astype(np.float64), buurt, n_buurt),
            "n_verdicht_cellen": buurt_sums(verdicht_cel.astype(np.float64), buurt, n_buurt),
            "n_wooncellen_0": buurt_sums(woon0.astype(np.float64), buurt, n_buurt),
            "n_wooncellen_1": buurt_sums((w1 > 0).astype(np.float64), buurt, n_buurt),
            "tot_w0": float(w0.sum()), "tot_w1": float(w1.sum()),
            "nieuw_mask": nieuw_cel,
            "bestaand0_mask": bestaand0,
        }
        if j0 is not None:
            nieuw_werk = (j1 > 0) & ~werk0
            rec.update({
                "heeft_werken": True,
                "dJ": buurt_sums(j1 - j0, buurt, n_buurt),
                "n_nieuwe_werkcellen": buurt_sums(nieuw_werk.astype(np.float64), buurt, n_buurt),
                "nieuw_werk_mask": nieuw_werk,
                "tot_j0": float(j0.sum()), "tot_j1": float(j1.sum()),
            })
        else:
            rec["heeft_werken"] = False
        runs[tag] = rec

    A, B = runs["a"], runs["b"]
    actief = (np.abs(A["dW"]) + np.abs(B["dW"])) > 0
    dA, dB = A["dW"][actief], B["dW"][actief]

    rho = spearman(dA, dB)
    mae = float(np.mean(np.abs(dA - dB)))
    gini_a, lor_a = gini_lorenz(A["dW"])
    gini_b, lor_b = gini_lorenz(B["dW"])

    def dichtheid_nieuw(r):
        cells = r["n_nieuwe_cellen"].sum()
        return (r["groei_uitbreid"].sum() / (cells * CELL_HA)) if cells else float("nan")

    def verdichtingsaandeel(r):
        tot = r["groei_verdicht"].sum() + r["groei_uitbreid"].sum()
        return r["groei_verdicht"].sum() / tot if tot else float("nan")

    summary = [
        ("Totaal woningen basisjaar",       A["tot_w0"], B["tot_w0"], ",.0f"),
        (f"Totaal woningen {args.zichtjaar}", A["tot_w1"], B["tot_w1"], ",.0f"),
        ("Woninggroei (som buurten)",        A["dW"].sum(), B["dW"].sum(), ",.0f"),
        ("Nieuwe wooncellen (uitbreiding)",  A["n_nieuwe_cellen"].sum(), B["n_nieuwe_cellen"].sum(), ",.0f"),
        ("Ruimtegebruik uitbreiding (ha)",   A["n_nieuwe_cellen"].sum()*CELL_HA, B["n_nieuwe_cellen"].sum()*CELL_HA, ",.0f"),
        ("Dichtheid uitbreiding (won/ha)",   dichtheid_nieuw(A), dichtheid_nieuw(B), ".1f"),
        ("Verdichtingsaandeel groei",        verdichtingsaandeel(A), verdichtingsaandeel(B), ".1%"),
        ("Gini-coefficient woninggroei",     gini_a, gini_b, ".3f"),
    ]

    # top-afwijkende buurten
    delta = A["dW"] - B["dW"]
    top = np.argsort(-np.abs(delta))[:15]

    rows_html = "".join(
        f"<tr><td>{html.escape(buurt_label(i))}</td>"
        f"<td style='text-align:right'>{A['dW'][i]:,.0f}</td>"
        f"<td style='text-align:right'>{B['dW'][i]:,.0f}</td>"
        f"<td style='text-align:right'>{delta[i]:+,.0f}</td></tr>"
        for i in top if abs(delta[i]) > 0)

    MIN_CELLS = 4  # ratio-figuren: minimaal aantal cellen per buurt tegen kleine-noemer-ruis
    LA, LB = A["label"], B["label"]

    def labels_for(sel_bool):
        return [buurt_label(i) for i in np.where(sel_bool)[0]]

    lab_actief = labels_for(actief)
    figs = []

    figs.append(("Figuur 1 — Woninggroei per buurt",
                 f"Plaatst run B ({LB}) de woninggroei in dezelfde buurten als run A ({LA})? "
                 f"Elke punt is een buurt; x = groei in {LA}, y = groei in {LB}. Op de rode diagonaal geven beide runs "
                 f"de buurt evenveel groei. Lees: een punt rechtsonder is een buurt waar {LA} veel bouwt en {LB} weinig. "
                 f"Gelabeld: de grootste afwijkers.",
                 svg_scatter(f"Woninggroei per buurt, {args.zichtjaar}",
                             LA, LB, dA, dB, labels=lab_actief)))

    figs.append(("Figuur 2 — Nieuwe wooncellen per buurt",
                 f"Ruimtegebruik van de uitbreiding: aantal 25m-cellen dat per buurt nieuw woongebied wordt. "
                 f"Boven de diagonaal = {LB} gebruikt in die buurt meer ruimte voor wonen dan {LA}. "
                 f"Lees: een punt op (40, 90) is een buurt met 40 nieuwe wooncellen (2,5 ha) in {LA} en 90 (5,6 ha) in {LB}.",
                 svg_scatter("Nieuwe wooncellen per buurt", LA, LB,
                             A["n_nieuwe_cellen"][actief], B["n_nieuwe_cellen"][actief],
                             labels=lab_actief)))

    tot_a = A["groei_verdicht"] + A["groei_uitbreid"]
    tot_b = B["groei_verdicht"] + B["groei_uitbreid"]
    sel3 = (tot_a >= 10) & (tot_b >= 10)
    va = np.where(tot_a > 0, A["groei_verdicht"] / np.maximum(tot_a, 1e-9), 0)[sel3]
    vb = np.where(tot_b > 0, B["groei_verdicht"] / np.maximum(tot_b, 1e-9), 0)[sel3]
    figs.append(("Figuur 3 — Verdichtingsaandeel per buurt",
                 f"Aandeel van de woninggroei dat binnen bestaande wooncellen landt (0 = alles op nieuwe locaties, "
                 f"1 = alles verdichting). x = {LA}, y = {LB}. Alleen buurten met ≥10 woningen groei in beide runs "
                 f"(n={int(sel3.sum()):,}). Lees: een punt op (0,2; 0,8) is een buurt waar {LA} vooral uitbreidt en {LB} vooral verdicht.",
                 svg_scatter("Verdichtingsaandeel", LA, LB,
                             va, vb, vmax=1.0, include_zero=True, labels=labels_for(sel3))))

    sel4 = (A["n_nieuwe_cellen"] >= MIN_CELLS) & (B["n_nieuwe_cellen"] >= MIN_CELLS)
    da_ = (A["groei_uitbreid"] / np.maximum(A["n_nieuwe_cellen"], 1) / CELL_HA)[sel4]
    db_ = (B["groei_uitbreid"] / np.maximum(B["n_nieuwe_cellen"], 1) / CELL_HA)[sel4]
    v99 = float(np.percentile(np.concatenate([da_, db_]), 99)) if da_.size else 1.0
    figs.append(("Figuur 4 — Dichtheid van uitbreidingslocaties per buurt",
                 f"Woningen per hectare op de nieuwe woonlocaties: bouwt {LB} uitbreidingen even compact als {LA}? "
                 f"Alleen buurten met ≥{MIN_CELLS} nieuwe cellen in beide runs (n={int(sel4.sum()):,}; assen afgekapt op p99). "
                 f"Lees: een punt op (30, 60) is een buurt waar {LB} de uitbreiding twee keer zo dicht bebouwt als {LA}.",
                 svg_scatter("Dichtheid uitbreiding (won/ha)", LA, LB,
                             da_, db_, vmax=v99, labels=labels_for(sel4))))

    sel5 = (A["n_verdicht_cellen"] >= MIN_CELLS) & (B["n_verdicht_cellen"] >= MIN_CELLS)
    ia = (A["groei_verdicht"] / np.maximum(A["n_verdicht_cellen"], 1))[sel5]
    ib = (B["groei_verdicht"] / np.maximum(B["n_verdicht_cellen"], 1))[sel5]
    v99i = float(np.percentile(np.concatenate([ia, ib]), 99)) if ia.size else 1.0
    figs.append(("Figuur 5 — Verdichtingsintensiteit per buurt",
                 f"Waar verdicht wordt: hoeveel woningen komen er gemiddeld bij per bestaande wooncel? "
                 f"x = {LA}, y = {LB}; alleen buurten met ≥{MIN_CELLS} verdichtende cellen in beide runs "
                 f"(n={int(sel5.sum()):,}; assen afgekapt op p99).",
                 svg_scatter("Verdichtingsintensiteit (won/cel)", LA, LB,
                             ia, ib, vmax=v99i, labels=labels_for(sel5))))

    figs.append(("Figuur 6 — Decompositie van de woninggroei",
                 f"Totale woninggroei opgesplitst in verdichting (binnen bestaande wooncellen) en uitbreiding "
                 f"(op nieuwe woonlocaties). Vergelijkbare verhouding = de nieuwe engine verandert de inbreiding/"
                 f"uitbreiding-balans niet.",
                 svg_stacked_bars("Inbreiding vs uitbreiding", "woningen",
                                  [LA, LB],
                                  [A["groei_verdicht"].sum(), B["groei_verdicht"].sum()],
                                  [A["groei_uitbreid"].sum(), B["groei_uitbreid"].sum()])))

    figs.append(("Figuur 7 — Concentratie van woninggroei (Lorenz)",
                 f"Buurten gesorteerd op groei (grootste eerst); de curve toont welk cumulatief aandeel van de totale "
                 f"groei in welk aandeel van de buurten landt. Hogere curve / hogere Gini = groei sterker geconcentreerd "
                 f"in minder buurten.",
                 svg_lorenz("Concentratie van woninggroei",
                            [(f"{LA} (Gini {gini_a:.3f})", "#d98a1f", lor_a),
                             (f"{LB} (Gini {gini_b:.3f})", "#534ab7", lor_b)])))

    sizes_a = cluster_sizes(A["nieuw_mask"])
    sizes_b = cluster_sizes(B["nieuw_mask"])
    figs.append(("Figuur 8 — Clustergrootte van nieuwe woonlocaties",
                 f"Aaneengesloten groepen nieuwe wooncellen (8-buur), ingedeeld naar omvang. Dit meet het directe doel "
                 f"van de wijziging: de nieuwe engine wijst clusters kleiner dan de minimale groepsgrootte "
                 f"(0,4 ha binnen woonkernen, 2 ha daarbuiten) af. Verwachting: {LA} heeft veel snippers "
                 f"(< 0,4 ha), {LB} vrijwel geen. Balken tonen het aandeel van het totale nieuwe woonareaal per klasse; "
                 f"tussen haakjes het totale aantal clusters per run.",
                 svg_cluster_bars("Nieuw woonareaal naar clustergrootte",
                                  LA, sizes_a, LB, sizes_b)))

    # Figuur 9: randdichtheid + lintaandeel (vorm, niet alleen grootte)
    ed_a, ed_b = edge_density(A["nieuw_mask"]), edge_density(B["nieuw_mask"])
    lint_a, lint_b = lint_share(A["nieuw_mask"]), lint_share(B["nieuw_mask"])
    figs.append(("Figuur 9 — Vorm van de nieuwe woonlocaties (randdichtheid & linten)",
                 f"Grootte alleen vangt geen linten: een smalle sliep van 2 ha langs een weg passeert de "
                 f"groottedrempel maar is precies het te vermijden patroon. Randdichtheid = meter rand per hectare nieuw "
                 f"woongebied (hoog = versnipperd/lint, laag = compact blok). Lintaandeel = deel van het nieuwe "
                 f"woonareaal in langgerekte, smalle clusters (elongatie ≥ 3 én breedte ≤ 2 cellen). "
                 f"Verwachting: {LB} lager op beide.",
                 svg_metric_bars("Vorm van nieuwe woonlocaties",
                                 [("Randdichtheid (m/ha)", ed_a, ed_b, ",.0f"),
                                  ("Lintaandeel", lint_a, lint_b, ".1%")],
                                 LA, LB)))

    # Figuur 10: afstand nieuwe cellen tot bestaand bebouwd (leapfrog)
    dist_a = afstand_tot_bestaand(A["nieuw_mask"], A["bestaand0_mask"])
    dist_b = afstand_tot_bestaand(B["nieuw_mask"], B["bestaand0_mask"])
    xmax_d = float(np.percentile(np.concatenate([dist_a, dist_b]), 98)) if len(dist_a) else 1000.0
    figs.append(("Figuur 10 — Aansluiting op bestaand bebouwd gebied (leapfrog)",
                 f"Afstand van elke nieuwe wooncel tot het dichtstbijzijnde in het basisjaar bebouwde (wonen óf werken) "
                 f"gebied. Curve verder naar links = nieuwe ontwikkeling sluit dichter aan op bestaand weefsel; "
                 f"een staart naar rechts = losse ontwikkeling in het veld ('leapfrog'). "
                 f"Lees op x=300m af welk aandeel binnen 300 m van bestaand bebouwd ligt.",
                 svg_ecdf("Afstand nieuwe wooncel tot bestaand bebouwd", "afstand (m)",
                          [(LA, "#d98a1f", dist_a), (LB, "#534ab7", dist_b)], xmax_d)))

    # Figuur 11: werken-spiegelset (alleen als werken meedraait)
    if A.get("heeft_werken") and B.get("heeft_werken"):
        actief_w = (np.abs(A["dJ"]) + np.abs(B["dJ"])) > 0
        jA, jB = A["dJ"][actief_w], B["dJ"][actief_w]
        rho_w = spearman(jA, jB)
        wsizes_a = cluster_sizes(A["nieuw_werk_mask"])
        wsizes_b = cluster_sizes(B["nieuw_werk_mask"])
        figs.append((f"Figuur 11 — Banengroei per buurt (Spearman {rho_w:.3f})",
                     f"Spiegel van figuur 1 voor werken: wonen en werken concurreren om dezelfde cellen, dus een "
                     f"wijziging aan de wonen-kant kan de banenallocatie verschuiven. x = banengroei {LA}, y = {LB}.",
                     svg_scatter(f"Banengroei per buurt, {args.zichtjaar}",
                                 LA, LB, jA, jB, labels=labels_for(actief_w))))
        figs.append(("Figuur 12 — Clustergrootte van nieuwe werklocaties",
                     f"Spiegel van figuur 8 voor werken: doet de clustering hetzelfde bij bedrijventerreinen "
                     f"als bij wonen?",
                     svg_cluster_bars("Nieuw werkareaal naar clustergrootte",
                                      LA, wsizes_a, LB, wsizes_b,
                                      ylab="aandeel nieuw werkareaal")))

    figs_html = "".join(
        f'<div class="fig"><h3>{html.escape(t)}</h3><div class="figcap">{html.escape(cap)}</div>{svg}</div>'
        for t, cap, svg in figs)

    def klasse_counts(sizes):
        return [int(((sizes >= lo) & (sizes < hi)).sum()) for _, lo, hi in CLUSTER_KLASSEN]
    ka, kb = klasse_counts(sizes_a), klasse_counts(sizes_b)
    summary.append(("Nieuwe woonclusters totaal", float(len(sizes_a)), float(len(sizes_b)), ",.0f"))
    summary.append(("waarvan snippers < 0,4 ha", float(ka[0]), float(kb[0]), ",.0f"))
    summary.append(("Mediane clustergrootte (ha)",
                    float(np.median(sizes_a)) if len(sizes_a) else 0.0,
                    float(np.median(sizes_b)) if len(sizes_b) else 0.0, ".2f"))
    summary.append(("Randdichtheid nieuw woongebied (m/ha)", ed_a, ed_b, ",.0f"))
    summary.append(("Lintaandeel nieuw woongebied", lint_a, lint_b, ".1%"))
    summary.append(("Nieuwe wooncellen binnen 300m bestaand",
                    float(np.mean(dist_a <= 300)) if len(dist_a) else 0.0,
                    float(np.mean(dist_b <= 300)) if len(dist_b) else 0.0, ".1%"))
    if A.get("heeft_werken"):
        summary.append((f"Totaal banen {args.zichtjaar}", A["tot_j1"], B["tot_j1"], ",.0f"))

    summ_html = "".join(
        f"<tr><td>{html.escape(nm)}</td>"
        f"<td style='text-align:right'>{va:{fmt}}</td>"
        f"<td style='text-align:right'>{vb:{fmt}}</td></tr>"
        for nm, va, vb, fmt in summary)

    doc = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Buurt-indicatoren A vs B</title>
<style>
 body {{ font-family:"Aptos","Segoe UI",system-ui,sans-serif; color:#1c1c1a; background:#fbfbfa; margin:24px; font-size:13px; }}
 h1 {{ font-size:18px; }} h2 {{ font-size:14px; margin-top:26px; }}
 table {{ border-collapse:collapse; margin-top:8px; }}
 td, th {{ padding:5px 12px; border-bottom:1px solid #ececE6; text-align:left; font-variant-numeric:tabular-nums; }}
 .plots {{ display:flex; flex-wrap:wrap; gap:18px; margin-top:12px; }}
 .fig {{ margin-top:22px; }}
 .fig h3 {{ font-size:13.5px; margin:0 0 2px 0; }}
 .figcap {{ color:#6b6b64; font-size:11.5px; max-width:640px; margin-bottom:6px; }}
 .kpi {{ color:#444; margin:4px 0; }}
</style></head><body>
<h1>Buurt-indicatoren: {html.escape(A['label'])} (A) vs {html.escape(B['label'])} (B)</h1>
<div class="kpi">Studiegebied {html.escape(args.suffix.replace('_', '-'))} &middot;
 zichtjaar {html.escape(args.zichtjaar)} &middot; casus {html.escape(args.casus)} &middot;
 {int(actief.sum()):,} buurten met woninggroei in A of B.</div>
<div class="kpi"><b>Spearman-rangcorrelatie woninggroei per buurt: {rho:.3f}</b> &middot;
 MAE: {mae:,.1f} woningen/buurt</div>
<h2>Kerncijfers</h2>
<table><tr><th></th><th>A: {html.escape(A['label'])}</th><th>B: {html.escape(B['label'])}</th></tr>
{summ_html}</table>
<h2>Figuren</h2>
{figs_html}
<h2>Grootste verschillen per buurt (top 15)</h2>
<div class="figcap">&Delta;W = verandering van het aantal woningen tussen basisjaar en {html.escape(args.zichtjaar)}
 (nieuwbouw minus sloop/verdringing), gesommeerd per buurt. De tabel toont de buurten waar de twee runs
 het meest uiteenlopen; negatief verschil = run B ({html.escape(B['label'])}) plaatst daar meer groei dan run A.</div>
<table><tr><th>Buurt (gemeente)</th><th>&Delta;W A: {html.escape(A['label'])}</th>
<th>&Delta;W B: {html.escape(B['label'])}</th><th>A &minus; B</th></tr>
{rows_html}</table>
</body></html>"""

    out_fn = os.path.join(args.out, "indicatoren.html")
    with open(out_fn, "w", encoding="utf8") as f:
        f.write(doc)
    with open(os.path.join(args.out, "indicatoren.json"), "w", encoding="utf8") as f:
        json.dump({"spearman": rho, "mae": mae,
                   "summary": [(n, a, b) for n, a, b, _ in summary]}, f, indent=1)
    print(f"[+] {out_fn}  (rho={rho:.3f}, gini A={gini_a:.3f} B={gini_b:.3f})")


if __name__ == "__main__":
    main()
