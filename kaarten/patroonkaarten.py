"""
patroonkaarten.py: waar legt een RSopen-run zijn nieuwe woningen, en waar is dat patroon vreemd?

De controlewaarden en tabellen van RSopen meten totalen, claims, clustergrootte en afstand tot het bebouwd gebied van
het basisjaar. Een patroon zoals ringen van nieuwe woningen rond kleine losse clusters midden in een polder zien ze
niet, want een boerenerf telt daar als bebouwd gebied. Dit script leest de standkaarten van een run en meet per
zichtjaar, per vak (standaard 10 bij 10 km, op veelvouden daarvan in RD) en per gemeente:

  - de nieuwe modelwoningen van de periode, en welk deel daarvan binnen 250 m, tussen 250 m en 1 km en verder dan
    1 km van een BRT-woonkern ligt;
  - de losse clusters: aaneengesloten cellen wonen of werken uit SubSector_rel (8-buren) waarvan geen cel binnen
    250 m van een woonkern ligt, naar 'met wonen' en 'alleen werken', met hun oppervlak;
  - de ringwoningen: nieuwe modelwoningen van een zichtjaar binnen 350 m van een los cluster van de stand van het
    zichtjaar ervoor (de kiemen), en niet binnen 350 m van een woonkern; voor het eerste zichtjaar zijn de losse
    clusters van de startstand de kiemen (de BAG-nieuwbouw en vergunde panden die het model vooraf in de stand zet);
  - als referentie de BAG-nieuwbouw in de startstand, met dezelfde afstandsbanden en losse clusters.

Daarna krijgt elke tegel (een blok van 2 bij 2 vakken, op elk vak een) en gemeente per zichtjaar een score (het oordeel,
met de drempels uit patroondrempels.json),
en maakt het script een overzichtskaart, detailkaarten van de tegels met de hoogste score, met een tweede run ook
verschilkaarten van dezelfde tegels, en een rapport in markdown en html. Meten en oordelen zijn gescheiden:
patroonmaten.json en kaartdata.npz zijn de meting; patroonoordeel.json, het rapport en de png's zijn het oordeel.
Met --herbeoordeel maakt het script alleen het oordeel opnieuw, uit de meting die al in --out staat.

Gebruik:
    python patroonkaarten.py --run C:\\LocalData\\RSopen_NL2120 --casus WLO_hoog_BAU --zichtjaren Y2040 Y2050 Y2060
        --out C:\\LocalData\\RSopen_toets\\NL2120\\patronen\\slotrun --naam slotrun
        [--suffix Nederland] [--vergelijk <LocalData van een andere run> --naam-vergelijk sept]
        [--buurt C:\\LocalData\\RSbuurt\\Buurtgrid\\Buurt_Nederland.tif] [--buurt-namen <csv>]
        [--drempels patroondrempels.json] [--top 10] [--herbeoordeel]

Verwachte structuur van een run (de LocalData van een run, of een kopie daarvan):
    <run>/BaseData/StandBasisjaar/Wonen/<subsector>_<suffix>[_<hash>].tif
    <run>/BaseData/Grondgebruik/BRT/IsWoonkern_<datum>_<suffix>[_<hash>].tif
    <run>/Allocatie/<casus>/Stand<jaar>/SubSector_rel_<suffix>_SS-<n>.tif
    <run>/Allocatie/<casus>/Stand<jaar>/Landgebruik/JaarVerandering_<suffix>_SS-<n>.tif
    <run>/Allocatie/<casus>/Stand<jaar>/{Wonen,Werken}/<subsector>_<suffix>_SS-<n>.tif
Het SS-nummer en de fingerprint-hash vindt het script zelf. Het leest alleen en schrijft alleen in --out.

Vereist: Python 3.10 of hoger met numpy, scipy, tifffile, imagecodecs en pillow (dezelfde als rs_indicators.py).
"""

import argparse
import csv
import glob
import html
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import tifffile
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from rs_indicators import basisjaar_pad, subsectoren  # noqa: E402

NULL_SS = 255           # SubSector_rel: geen toewijzing
NULL_JAAR = 65535       # JaarVerandering: geen verandering
HASH = r"(?:_[0-9a-f]{8})?"
ACHT_BUREN = np.ones((3, 3), dtype=bool)
KRUIS = ndi.generate_binary_structure(2, 1)
CAT_OVERIG, CAT_WONEN, CAT_WERKEN = 0, 1, 2
CAT_NAAM = {CAT_OVERIG: "overig", CAT_WONEN: "wonen", CAT_WERKEN: "werken"}
STANDAARD_BUURT = r"C:\LocalData\RSbuurt\Buurtgrid\Buurt_Nederland.tif"
RUNS = ("run", "vergelijk")


# ------------------------------------------------------------------ tijd, geheugen, melden

T_START = time.perf_counter()


def meld(tekst):
    print(f"{time.perf_counter() - T_START:7.1f} s  {tekst}", flush=True)


def piekgeheugen_gb():
    """Piek van het werkgeheugen en van het vastgelegde privegeheugen van dit proces, in GB."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return {"werkgeheugen_piek_gb": round(pmc.PeakWorkingSetSize / 2 ** 30, 2),
                    "privegeheugen_piek_gb": round(pmc.PeakPagefileUsage / 2 ** 30, 2)}
    except Exception:
        pass
    try:
        import resource
        return {"werkgeheugen_piek_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2 ** 20, 2)}
    except Exception:
        return {}


# ------------------------------------------------------------------ rasters lezen

class Grid:
    """Het raster van het studiegebied: vorm, linkerbovenhoek in RD en celgrootte."""

    def __init__(self, vorm, geo):
        self.H, self.W = int(vorm[0]), int(vorm[1])
        self.x0, self.y0, self.cel = geo

    def zelfde(self, vorm, geo):
        return (tuple(vorm[:2]) == (self.H, self.W) and geo is not None
                and np.allclose(geo, (self.x0, self.y0, self.cel), atol=1e-3))

    def als_dict(self):
        return {"rijen": self.H, "kolommen": self.W, "x0": self.x0, "y0": self.y0, "cel_m": self.cel}

    def __repr__(self):
        return f"{self.H} x {self.W} cellen van {self.cel:g} m vanaf RD ({self.x0:.0f}, {self.y0:.0f})"


def geo_van(pad, pagina):
    """(x0, y0, cel) van de linkerbovenhoek, uit de GeoTIFF-tags of anders uit de tfw ernaast."""
    sc, tp = pagina.tags.get(33550), pagina.tags.get(33922)
    if sc is not None and tp is not None:
        sx, sy = sc.value[0], sc.value[1]
        t = tp.value
        return (float(t[3] - t[0] * sx), float(t[4] + t[1] * sy), float(sx))
    tfw = os.path.splitext(pad)[0] + ".tfw"
    if os.path.exists(tfw):
        with open(tfw, encoding="ascii", errors="replace") as f:
            a, _d, _b, e, c, fy = [float(x) for x in f.read().split()[:6]]
        return (c - a / 2.0, fy - e / 2.0, a)
    return None


def lees(pad, grid=None):
    with tifffile.TiffFile(pad) as tf:
        pagina = tf.pages[0]
        a = pagina.asarray()
        geo = geo_van(pad, pagina)
    if a.ndim == 3:
        a = a[..., 0]
    if grid is not None and not grid.zelfde(a.shape, geo):
        raise ValueError(f"{pad} staat niet op het raster van het studiegebied ({a.shape}, {geo} tegen {grid})")
    return a, geo


def lees_aantallen(paden, grid):
    """Som van een reeks eenhedenkaarten (float32), NaN en negatief als nul."""
    tot = None
    for p in paden:
        a, _ = lees(p, grid)
        a = np.array(a, dtype=np.float32, copy=True)
        np.nan_to_num(a, copy=False)
        np.maximum(a, 0, out=a)
        if tot is None:
            tot = a
        else:
            tot += a
            del a
    return tot


# ------------------------------------------------------------------ bestanden vinden

def vind_suffix(run):
    fs = glob.glob(os.path.join(run, "BaseData", "StandBasisjaar", "Wonen", "Footprint_*.tif"))
    namen = sorted({re.sub(r"_[0-9a-f]{8}$", "", os.path.splitext(os.path.basename(f))[0][len("Footprint_"):]) for f in fs})
    if len(namen) != 1:
        raise ValueError(f"kan het studiegebied niet bepalen uit {run}/BaseData/StandBasisjaar/Wonen/Footprint_*.tif "
                         f"(gevonden: {namen or 'niets'}); geef --suffix")
    return namen[0]


def standmap(run, casus, jaar):
    return os.path.join(run, "Allocatie", casus, f"Stand{jaar}")


def vind_zichtjaren(run, casus):
    m = os.path.join(run, "Allocatie", casus)
    return sorted(d[len("Stand"):] for d in os.listdir(m)
                  if re.fullmatch(r"StandY\d{4}", d) and os.path.isdir(os.path.join(m, d)))


def ss_nummer(smap, suffix):
    """Het SS-nummer (het aantal subsectoren) in de bestandsnamen van een stand; bij meer dan een het nieuwste."""
    vorm = re.compile(rf"^SubSector_rel_{re.escape(suffix)}{HASH}_SS-(\d+){HASH}\.tif$")
    hits = []
    for p in glob.glob(os.path.join(smap, f"SubSector_rel_{suffix}*_SS-*.tif")):
        m = vorm.match(os.path.basename(p))
        if m:
            hits.append((os.path.getmtime(p), int(m.group(1))))
    if not hits:
        raise FileNotFoundError(f"geen SubSector_rel_{suffix}_SS-<n>.tif in {smap}")
    nummers = sorted({n for _, n in hits})
    if len(nummers) > 1:
        meld(f"let op: meer SS-nummers in {smap} ({nummers}); het nieuwste bestand wint")
    return max(hits)[1]


def stand_pad(smap, deelmap, naam, suffix, n):
    map_ = os.path.join(smap, deelmap) if deelmap else smap
    vorm = re.compile(rf"^{re.escape(naam)}_{re.escape(suffix)}{HASH}_SS-{n}{HASH}\.tif$")
    hits = [p for p in glob.glob(os.path.join(map_, f"{naam}_{suffix}*_SS-{n}*.tif")) if vorm.match(os.path.basename(p))]
    if not hits:
        raise FileNotFoundError(f"geen {naam}_{suffix}_SS-{n}.tif in {map_}")
    return max(hits, key=os.path.getmtime)


def stand_subsectoren(smap, deelmap, suffix, n):
    """De subsectoren van een categorie zoals ze in de stand staan: <naam>_<suffix>_SS-<n>.tif, zonder Footprint."""
    vorm = re.compile(rf"^(.+)_{re.escape(suffix)}{HASH}_SS-{n}{HASH}\.tif$")
    namen = set()
    for p in glob.glob(os.path.join(smap, deelmap, f"*_{suffix}*_SS-{n}*.tif")):
        m = vorm.match(os.path.basename(p))
        if m and m.group(1) != "Footprint":
            namen.add(m.group(1))
    return sorted(namen)


def woonkern_pad(run, suffix):
    map_ = os.path.join(run, "BaseData", "Grondgebruik", "BRT")
    vorm = re.compile(rf"^IsWoonkern_(\d+)_{re.escape(suffix)}{HASH}\.tif$")
    hits = []
    for p in glob.glob(os.path.join(map_, f"IsWoonkern_*_{suffix}*.tif")):
        m = vorm.match(os.path.basename(p))
        if m:
            hits.append((m.group(1), os.path.getmtime(p), p))
    if not hits:
        raise FileNotFoundError(f"geen IsWoonkern_<datum>_{suffix}.tif in {map_}")
    return max(hits)[2]


def xml_info(tif):
    """Een paar regels uit de GeoDMS-metadata naast een tif: versie, sessiestart, runbestand, startjaar."""
    p = os.path.splitext(tif)[0] + ".xml"
    info = {}
    if not os.path.exists(p):
        return info
    with open(p, encoding="utf8", errors="replace") as f:
        tekst = f.read()
    for tag, sleutel in (("GeoDmsVersion", "geodms"), ("SessionStartTime", "sessiestart"), ("RunFile", "runbestand"),
                         ("Model_StartYear", "startjaar"), ("StudyArea", "studiegebied")):
        m = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", tekst, re.S)
        if m:
            info[sleutel] = m.group(1).strip()
    return info


# ------------------------------------------------------------------ gemeenten en tegels

def gemeentenaam(naam):
    """Naam uit de buurtnamen leesbaar maken: _s_Hertogenbosch wordt 's Hertogenbosch, liggende streepjes spaties."""
    n = re.sub(r"^_s_", "'s ", naam)
    return re.sub(r"\s+", " ", n.replace("_", " ")).strip()


def lees_gemeenten(buurt_tif, buurt_csv, grid):
    """Gemeente-index per cel (uint16, 0 = geen gemeente) en de namen, uit het buurtgrid en de buurtnamen."""
    with open(buurt_csv, encoding="utf8", errors="replace", newline="") as f:
        rijen = list(csv.DictReader(f))
    gem_van_buurt = {}
    for r in rijen:
        try:
            gem_van_buurt[int(r["id"])] = gemeentenaam((r.get("Gemeente_name") or "").strip() or "onbekend")
        except (KeyError, ValueError):
            continue
    namen = [""] + sorted(set(gem_van_buurt.values()))
    nr = {g: i for i, g in enumerate(namen)}
    max_id = max(gem_van_buurt)
    lut = np.zeros(max_id + 2, dtype=np.uint16)
    for b, g in gem_van_buurt.items():
        lut[b] = nr[g]
    b, geo = lees(buurt_tif)
    if geo is None:
        raise ValueError(f"{buurt_tif} heeft geen georeferentie")
    if abs(geo[2] - grid.cel) > 1e-6:
        raise ValueError(f"het buurtgrid heeft cellen van {geo[2]} m, het studiegebied van {grid.cel} m")
    r0 = int(round((geo[1] - grid.y0) / grid.cel))
    c0 = int(round((grid.x0 - geo[0]) / grid.cel))
    if r0 < 0 or c0 < 0 or r0 + grid.H > b.shape[0] or c0 + grid.W > b.shape[1]:
        raise ValueError(f"het buurtgrid {buurt_tif} dekt het studiegebied niet")
    b = b[r0:r0 + grid.H, c0:c0 + grid.W]
    gem = lut[np.minimum(b, max_id + 1)]
    return gem, namen


class Tegels:
    """Vaste vierkante tegels op veelvouden van tegel_km in RD-coordinaten; tegelrij 0 is de noordelijkste."""

    def __init__(self, grid, km):
        self.km = int(km)
        T = km * 1000.0
        xs = grid.x0 + (np.arange(grid.W) + 0.5) * grid.cel
        ys = grid.y0 - (np.arange(grid.H) + 0.5) * grid.cel
        ix = np.floor(xs / T).astype(np.int64)
        iy = np.floor(ys / T).astype(np.int64)
        self.ix0, self.iy1 = int(ix.min()), int(iy.max())
        self.nx = int(ix.max()) - self.ix0 + 1
        self.ny = self.iy1 - int(iy.min()) + 1
        self.kol = ix - self.ix0
        self.rij = self.iy1 - iy
        self.n = self.nx * self.ny

    def van(self, r, c):
        return self.rij[r] * self.nx + self.kol[c]

    def rd(self, t):
        tr, tc = divmod(int(t), self.nx)
        return (self.ix0 + tc) * self.km, (self.iy1 - tr) * self.km

    def naam(self, t):
        x, y = self.rd(t)
        return f"x{x:03d}_y{y:03d}"

    def venster(self, t):
        tr, tc = divmod(int(t), self.nx)
        rr = np.flatnonzero(self.rij == tr)
        cc = np.flatnonzero(self.kol == tc)
        return int(rr[0]), int(rr[-1]) + 1, int(cc[0]), int(cc[-1]) + 1


def tegel_gemeenten(gem, tegels, n_gem, ha_cel):
    """Per tegel het landoppervlak (cellen met een gemeente) en de gemeenten, de grootste eerst."""
    land = np.zeros(tegels.n)
    per = [dict() for _ in range(tegels.n)]
    for tr in range(tegels.ny):
        rr = np.flatnonzero(tegels.rij == tr)
        if not len(rr):
            continue
        blok = gem[rr[0]:rr[-1] + 1]
        sleutel = tegels.kol[np.newaxis, :].astype(np.int64) * n_gem + blok
        telling = np.bincount(sleutel[blok > 0], minlength=tegels.nx * n_gem).reshape(tegels.nx, n_gem)
        for tc in range(tegels.nx):
            t = tr * tegels.nx + tc
            land[t] = telling[tc].sum() * ha_cel
            for g in np.flatnonzero(telling[tc]):
                per[t][int(g)] = float(telling[tc, g] * ha_cel)
    return land, [sorted(d, key=lambda g: -d[g]) for d in per], per


# ------------------------------------------------------------------ afstand tot de woonkern

class KernAfstand:
    """Afstand in meter van een cel tot de dichtstbijzijnde cel van de BRT-woonkern (tussen celmiddens, zoals een
    euclidische afstandstransformatie), tot max_m; verder is oneindig. Een KD-boom op de randcellen van de kern is
    exact (de dichtstbijzijnde kerncel van een cel buiten de kern is altijd een randcel) en houdt het geheugen klein."""

    def __init__(self, K, cel, max_m):
        self.K = K.ravel()
        self.ncol = K.shape[1]
        self.cel = cel
        self.max_c = max_m / cel + 1e-6
        rand = K & ~ndi.binary_erosion(K, KRUIS, border_value=1)
        punten = np.argwhere(rand)
        self.boom = cKDTree(punten.astype(np.float64)) if len(punten) else None

    def __call__(self, idx):
        if self.boom is None or len(idx) == 0:
            return np.full(len(idx), np.inf, dtype=np.float32)
        r, c = np.divmod(idx, self.ncol)
        d, _ = self.boom.query(np.column_stack([r, c]).astype(np.float64), distance_upper_bound=self.max_c, workers=-1)
        d = (d * self.cel).astype(np.float32)
        d[self.K[idx]] = 0.0
        return d


# ------------------------------------------------------------------ meten

class Teller:
    """Sommen per eenheid: tegel, gemeente en het hele studiegebied."""

    def __init__(self, tegels, n_gem, ncol, gem):
        self.tegels, self.n_gem, self.ncol, self.gem = tegels, n_gem, ncol, gem.ravel()
        self.maten = {}

    def punten(self, naam, idx, w):
        r, c = np.divmod(idx, self.ncol)
        self.som(naam, self.tegels.van(r, c), self.gem[idx], w)

    def som(self, naam, tegel, gem, w):
        w = np.asarray(w, dtype=np.float64)
        tegel = np.asarray(tegel, dtype=np.int64)
        gem = np.asarray(gem, dtype=np.int64)
        self.maten[naam] = {"vak": np.bincount(tegel, w, self.tegels.n),
                            "gemeente": np.bincount(gem, w, self.n_gem),
                            "nl": float(w.sum())}


def ijk_indexering(SS, W, J, min_aandeel):
    """Welke index van SubSector_rel is wonen en welke werken: per index het aandeel cellen met woningen en met banen
    in de volledige stand van hetzelfde zichtjaar. Geeft een opzoektabel (256) en de tabel voor het rapport."""
    s = SS.ravel()
    n = np.bincount(s, minlength=256)
    nw = np.bincount(s[W.ravel() > 0], minlength=256)
    nj = np.bincount(s[J.ravel() > 0], minlength=256)
    cat = np.zeros(256, dtype=np.int8)
    tabel = []
    for k in np.flatnonzero(n):
        if k == NULL_SS:
            continue
        fw, fj = nw[k] / n[k], nj[k] / n[k]
        if fw >= min_aandeel and fw >= fj:
            cat[k] = CAT_WONEN
        elif fj >= min_aandeel and fj > fw:
            cat[k] = CAT_WERKEN
        tabel.append({"index": int(k), "cellen": int(n[k]), "aandeel_met_woningen": round(float(fw), 4),
                      "aandeel_met_banen": round(float(fj), 4), "categorie": CAT_NAAM[int(cat[k])]})
    return cat, tabel


def losse_clusters(mask, cat_vlak, jv_vlak, jaar_int, eerste_jaar, kern_afstand, P, ncol, gem_vlak, tegels):
    """Aaneengesloten cellen (8-buren) van een masker die los liggen: geen cel binnen kern_nabij_m van een woonkern.
    Per los cluster: of hij wonen heeft, of er modelcellen in zitten (jaar van verandering vanaf het eerste zichtjaar),
    of hij in dit zichtjaar ontstond of groeide, zijn grootte, zwaartepunt, gemeente (de meeste cellen) en tegel
    (die van het zwaartepunt), en zijn cellen."""
    lab, nlab = ndi.label(mask, ACHT_BUREN)
    if nlab == 0:
        return None
    cidx = np.flatnonzero(mask)
    clab = lab.ravel()[cidx]
    del lab
    d = kern_afstand(cidx)
    mind = np.full(nlab + 1, np.inf, dtype=np.float32)
    np.minimum.at(mind, clab, d)
    los = mind > P["kern_nabij_m"]
    los[0] = False
    sel = los[clab]
    cidx, clab = cidx[sel], clab[sel]
    if not len(cidx):
        return None
    ccat, cjv = cat_vlak[cidx], jv_vlak[cidx]
    _, inv = np.unique(clab, return_inverse=True)
    k = int(inv.max()) + 1
    cellen = np.bincount(inv, minlength=k)
    wonen = np.bincount(inv[ccat == CAT_WONEN], minlength=k) > 0
    model = np.bincount(inv[(cjv >= eerste_jaar) & (cjv != NULL_JAAR)], minlength=k) > 0
    nieuw = np.bincount(inv[cjv == jaar_int], minlength=k) > 0
    r, c = np.divmod(cidx, ncol)
    rm = np.bincount(inv, r, k) / cellen
    cm = np.bincount(inv, c, k) / cellen
    g = gem_vlak[cidx].astype(np.int64)
    sleutel = inv.astype(np.int64) * 65536 + g
    u, aantal = np.unique(sleutel, return_counts=True)
    u_inv, u_gem = u // 65536, u % 65536
    volg = np.lexsort((-aantal, u_inv))
    eerste = np.ones(len(volg), dtype=bool)
    eerste[1:] = u_inv[volg][1:] != u_inv[volg][:-1]
    cgem = np.zeros(k, dtype=np.int64)
    cgem[u_inv[volg][eerste]] = u_gem[volg][eerste]
    ctegel = tegels.van(np.clip(np.round(rm).astype(np.int64), 0, len(tegels.rij) - 1),
                        np.clip(np.round(cm).astype(np.int64), 0, len(tegels.kol) - 1))
    return {"cellen_idx": cidx, "cluster_van_cel": inv, "n": k, "cellen": cellen, "wonen": wonen, "model": model,
            "nieuw": nieuw, "rij": rm, "kol": cm, "gemeente": cgem, "vak": ctegel}


def meet_run(run, casus, jaren, suffix, grid, gem, tegels, n_gem, P, label):
    """Alle maten van een run per zichtjaar, plus de gegevens voor de kaarten."""
    ncol = grid.W
    ha_cel = grid.cel ** 2 / 1e4
    eerste_jaar = int(jaren[0][1:])
    wonen = subsectoren(run, suffix, "Wonen")
    if not wonen:
        raise FileNotFoundError(f"geen woonsubsectoren in {run}/BaseData/StandBasisjaar/Wonen")
    basispaden = [basisjaar_pad(run, "Wonen", s, suffix) for s in wonen]
    meld(f"[{label}] basisjaar: {', '.join(os.path.basename(p) for p in basispaden)}")
    W_vorig = lees_aantallen(basispaden, grid)
    w0pos = W_vorig > 0
    kp = woonkern_pad(run, suffix)
    K, _ = lees(kp, grid)
    K = K > 0
    kern_afstand = KernAfstand(K, grid.cel, max(P["kern_ver_m"], P["ring_kernzone_m"]))
    meld(f"[{label}] woonkern {os.path.basename(kp)}: {int(K.sum()) * ha_cel:,.0f} ha")
    gem_vlak = gem.ravel()
    uit = {"pad": os.path.abspath(run), "casus": casus, "label": label, "woonkern": os.path.abspath(kp),
           "basisjaar": [os.path.abspath(p) for p in basispaden], "jaren": {},
           "basisjaar_woningen": float(W_vorig.sum(dtype=np.float64))}
    kaart = {"w0pos": w0pos, "kern": K}
    kiemen = None
    cat = None
    for j, jaar in enumerate(jaren):
        t0 = time.perf_counter()
        jaar_int = int(jaar[1:])
        sm = standmap(run, casus, jaar)
        n = ss_nummer(sm, suffix)
        ss_pad = stand_pad(sm, "", "SubSector_rel", suffix, n)
        SS, _ = lees(ss_pad, grid)
        JV, _ = lees(stand_pad(sm, "Landgebruik", "JaarVerandering", suffix, n), grid)
        W = lees_aantallen([stand_pad(sm, "Wonen", s, suffix, n) for s in wonen], grid)
        if cat is None:
            werken = stand_subsectoren(sm, "Werken", suffix, n)
            if not werken:
                raise FileNotFoundError(f"geen werkenkaarten in {sm}/Werken; zonder die kaarten is SubSector_rel niet te ijken")
            J = lees_aantallen([stand_pad(sm, "Werken", s, suffix, n) for s in werken], grid)
            cat, ijking = ijk_indexering(SS, W, J, P["ijking_min_aandeel"])
            del J
            uit["ijking"] = {"zichtjaar": jaar, "indexen": ijking, "werken": werken, "wonen": wonen}
            uit["ss_nummer"] = n
            uit["xml"] = xml_info(ss_pad)
            meld(f"[{label}] ijking SubSector_rel {jaar}: wonen {[t['index'] for t in ijking if t['categorie'] == 'wonen']}, "
                 f"werken {[t['index'] for t in ijking if t['categorie'] == 'werken']}")
        dw = W - W_vorig
        idx = np.flatnonzero(dw.ravel() > P["toename_min_woningen"])
        val = dw.ravel()[idx].astype(np.float64)
        del dw, W_vorig
        W_vorig = W
        del W
        SSv, JVv = SS.ravel(), JV.ravel()
        cat_vlak = cat[SSv]
        pcat, pjv = cat_vlak[idx], JVv[idx]
        # BAG-nieuwbouw in de startstand: woontoename tot het eerste zichtjaar op een woncel met een label van voor dat jaar
        bag = (pcat == CAT_WONEN) & (pjv < eerste_jaar) if j == 0 else np.zeros(len(idx), dtype=bool)
        d = kern_afstand(idx)
        T = Teller(tegels, n_gem, ncol, gem)
        nabij, ver = P["kern_nabij_m"], P["kern_ver_m"]
        for soort, s in (("model", ~bag), ("bag", bag)):
            if soort == "bag" and j > 0:
                continue
            i_, v_, d_ = idx[s], val[s], d[s]
            T.punten(f"{soort}_nieuw", i_, v_)
            T.punten(f"{soort}_kern", i_, v_ * (d_ <= nabij))
            T.punten(f"{soort}_midden", i_, v_ * ((d_ > nabij) & (d_ <= ver)))
            T.punten(f"{soort}_ver", i_, v_ * (d_ > ver))
        # losse clusters in deze stand (SubSector_rel is cumulatief: alle cellen wonen en werken sinds het basisjaar)
        mask = (cat_vlak > CAT_OVERIG).reshape(SS.shape)
        cl = losse_clusters(mask, cat_vlak, JVv, jaar_int, eerste_jaar, kern_afstand, P, ncol, gem_vlak, tegels)
        if j == 0:
            # de kiemen van de eerste periode: de losse clusters van de startstand
            kiemen = losse_clusters(mask & (JV < eerste_jaar), cat_vlak, JVv, jaar_int, eerste_jaar, kern_afstand, P,
                                    ncol, gem_vlak, tegels)
        werkcellen = np.flatnonzero((cat_vlak == CAT_WERKEN) & (JVv >= eerste_jaar) & (JVv != NULL_JAAR))
        del mask, cat_vlak, SS, JV, SSv, JVv
        leeg = (np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0))
        for soort, keus in (("los_wonen", lambda c: c["wonen"] & c["model"]),
                            ("los_werken", lambda c: ~c["wonen"] & c["model"]),
                            ("los_nieuw_wonen", lambda c: c["wonen"] & c["nieuw"]),
                            ("los_nieuw_werken", lambda c: ~c["wonen"] & c["nieuw"]),
                            ("los_start_wonen", lambda c: c["wonen"] & ~c["model"]),
                            ("los_start_werken", lambda c: ~c["wonen"] & ~c["model"])):
            if cl is None:
                T.som(f"{soort}_n", *leeg)
                T.som(f"{soort}_ha", *leeg)
                continue
            m = keus(cl)
            T.som(f"{soort}_n", cl["vak"][m], cl["gemeente"][m], np.ones(int(m.sum())))
            T.som(f"{soort}_ha", cl["vak"][m], cl["gemeente"][m], cl["cellen"][m] * ha_cel)
        # ringwoningen: modelwoningen van dit zichtjaar bij een kiem, een los cluster van de stand ervoor
        model = ~bag
        i_m, v_m, d_m = idx[model], val[model], d[model]
        ring_w = np.zeros(len(i_m))
        ring_soort = np.zeros(len(i_m), dtype=np.int8)   # 1 kiem met wonen, 2 kiem met alleen werken
        ring_klein = np.zeros(len(i_m), dtype=bool)
        heeft_kiemen = kiemen is not None and kiemen["n"] > 0
        kiem_groei = np.zeros(kiemen["n"]) if heeft_kiemen else None
        buiten = d_m > P["ring_kernzone_m"]
        if heeft_kiemen and buiten.any():
            kr, kc = np.divmod(kiemen["cellen_idx"], ncol)
            boom = cKDTree(np.column_stack([kr, kc]).astype(np.float64))
            q = np.flatnonzero(buiten)
            pr, pc = np.divmod(i_m[q], ncol)
            dd, nn = boom.query(np.column_stack([pr, pc]).astype(np.float64),
                                distance_upper_bound=P["ring_m"] / grid.cel + 1e-6, workers=-1)
            raak = np.isfinite(dd)
            q, nn = q[raak], nn[raak]
            kl = kiemen["cluster_van_cel"][nn]
            ring_w[q] = v_m[q]
            ring_soort[q] = np.where(kiemen["wonen"][kl], 1, 2)
            ring_klein[q] = kiemen["cellen"][kl] * ha_cel < P["kiem_klein_ha"]
            kiem_groei = np.bincount(kl, v_m[q], kiemen["n"])
        T.punten("ring", i_m, ring_w)
        T.punten("ring_wonen", i_m, ring_w * (ring_soort == 1))
        T.punten("ring_werken", i_m, ring_w * (ring_soort == 2))
        T.punten("ring_klein", i_m, ring_w * ring_klein)
        if heeft_kiemen:
            groeide = kiem_groei >= P["aangegroeid_min_woningen"]
            klein = kiemen["cellen"] * ha_cel < P["kiem_klein_ha"]
            for nm, m in (("kiemen_n", np.ones(kiemen["n"], dtype=bool)), ("kiemen_aangegroeid_n", groeide),
                          ("kiemen_aangegroeid_werken_n", groeide & ~kiemen["wonen"]),
                          ("kiemen_aangegroeid_klein_n", groeide & klein)):
                T.som(nm, kiemen["vak"][m], kiemen["gemeente"][m], np.ones(int(m.sum())))
        else:
            groeide = np.zeros(0, dtype=bool)
            for nm in ("kiemen_n", "kiemen_aangegroeid_n", "kiemen_aangegroeid_werken_n", "kiemen_aangegroeid_klein_n"):
                T.som(nm, *leeg)
        # gegevens voor de kaarten
        kmin = P["kaart_min_woningen"]
        kaart[f"{jaar}/model_idx"] = i_m[v_m >= kmin]
        kaart[f"{jaar}/ring_idx"] = i_m[(ring_w >= kmin)]
        if j == 0:
            kaart[f"{jaar}/bag_idx"] = idx[bag & (val >= kmin)]
        kaart[f"{jaar}/werk_idx"] = werkcellen
        if heeft_kiemen:
            kaart[f"{jaar}/kiem_idx"] = kiemen["cellen_idx"]
            kaart[f"{jaar}/kiem_van_cel"] = kiemen["cluster_van_cel"]
            for veld in ("rij", "kol", "cellen", "wonen", "model"):
                kaart[f"{jaar}/kiem_{veld}"] = kiemen[veld]
            kaart[f"{jaar}/kiem_groeide"] = groeide
        uit["jaren"][jaar] = {"ss_nummer": n, "maten": T.maten,
                              "woningen": float(W_vorig.sum(dtype=np.float64)),
                              "losse_clusters": 0 if cl is None else int(cl["n"]),
                              "kiemen": 0 if kiemen is None else int(kiemen["n"])}
        meld(f"[{label}] {jaar}: {v_m.sum():,.0f} nieuwe modelwoningen op {len(i_m):,} cellen, BAG-startstand "
             f"{val[bag].sum():,.0f}, losse clusters {0 if cl is None else cl['n']:,}, kiemen "
             f"{0 if kiemen is None else kiemen['n']:,}, ringwoningen {ring_w.sum():,.0f} ({time.perf_counter() - t0:.1f} s)")
        kiemen = cl
    del W_vorig
    return uit, kaart


# ------------------------------------------------------------------ json en kaartdata

def naar_json(o):
    if isinstance(o, dict):
        return {k: naar_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [naar_json(v) for v in o]
    if isinstance(o, np.ndarray):
        return [round(float(x), 3) for x in o]
    if isinstance(o, np.floating):
        return round(float(o), 3)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, float):
        return round(o, 3)
    return o


def bewaar_kaartdata(pad, kaartdata):
    np.savez_compressed(pad, **kaartdata)


def laad_kaartdata(pad):
    with np.load(pad) as z:
        return {k: z[k] for k in z.files}


# ------------------------------------------------------------------ tegels als blokken van vakken

class Vensters:
    """Tegels van k bij k vakken. Er begint een tegel op elk vak, zodat een plek in k*k tegels valt en een brandhaard
    niet door een tegelgrens gesplitst wordt. Een tegel heet naar zijn linkeronderhoek in RD-kilometers."""

    def __init__(self, vakken, k):
        self.v, self.k = vakken, int(k)
        self.nwx, self.nwy = max(1, vakken.nx - self.k + 1), max(1, vakken.ny - self.k + 1)
        self.n = self.nwx * self.nwy
        self.km = self.k * vakken.km

    def som(self, a):
        A = np.asarray(a, dtype=np.float64).reshape(self.v.ny, self.v.nx)
        S = np.zeros((self.nwy, self.nwx))
        for i in range(self.k):
            for j in range(self.k):
                blok = A[i:i + self.nwy, j:j + self.nwx]
                S[:blok.shape[0], :blok.shape[1]] += blok
        return S.ravel()

    def rc(self, w):
        return divmod(int(w), self.nwx)

    def naam(self, w):
        wr, wc = self.rc(w)
        x = (self.v.ix0 + wc) * self.v.km
        y = (self.v.iy1 - min(wr + self.k - 1, self.v.ny - 1)) * self.v.km
        return f"x{x:03d}_y{y:03d}"

    def vakken(self, w):
        wr, wc = self.rc(w)
        return [r * self.v.nx + c for r in range(wr, min(wr + self.k, self.v.ny)) for c in range(wc, min(wc + self.k, self.v.nx))]

    def venster(self, w):
        vk = self.vakken(w)
        r0, _, c0, _ = self.v.venster(vk[0])
        _, r1, _, c1 = self.v.venster(vk[-1])
        return r0, r1, c0, c1

    def overlapt(self, a, b):
        ar, ac = self.rc(a)
        br, bc = self.rc(b)
        return abs(ar - br) < self.k and abs(ac - bc) < self.k


def vensters_uit(M):
    e = M["eenheden"]["vak"]
    g = M["provenance"]["grid"]
    grid = Grid((g["rijen"], g["kolommen"]), (g["x0"], g["y0"], g["cel_m"]))
    vakken = Tegels(grid, e["km"])
    return grid, vakken, Vensters(vakken, M["eenheden"]["tegel_km"] // e["km"])


def kies_zonder_overlap(V, hoogste, minimum=0.0):
    """Tegels van hoog naar laag, en alleen als ze geen vak delen met een tegel die al gekozen is."""
    gekozen = []
    for w in np.argsort(-np.asarray(hoogste), kind="stable"):
        if hoogste[w] <= minimum:
            break
        if not any(V.overlapt(w, g) for g in gekozen):
            gekozen.append(int(w))
    return gekozen


# ------------------------------------------------------------------ oordelen

def score(maten, eenheid, O):
    """Score per eenheid (of landelijk) voor een zichtjaar: elke term is 1 bij zijn ijkmaat."""
    def a(naam):
        v = maten[naam][eenheid]
        return np.asarray(v, dtype=np.float64) if eenheid != "nl" else float(v)
    return (a("ring") / O["ijkmaat_ringwoningen"] + a("model_ver") / O["ijkmaat_ver_woningen"]
            + a("kiemen_aangegroeid_n") / O["ijkmaat_aangegroeide_kiemen"])


def beoordeel(M, O, V):
    """Scores per vak, tegel en gemeente per zichtjaar; de tegels zonder overlap van hoog naar laag; de gemeenten van
    hoog naar laag; en wat opvallend is (een score vanaf opvallend_score in minstens een zichtjaar)."""
    uit = {"oordeel": {k: v for k, v in O.items() if not k.startswith("_")}, "runs": {}}
    for rn, R in M["runs"].items():
        r = {"vak": {}, "tegel": {}, "gemeente": {}, "nl": {}}
        for jaar, jd in R["jaren"].items():
            m = jd["maten"]
            r["vak"][jaar] = score(m, "vak", O)
            r["tegel"][jaar] = V.som(r["vak"][jaar])
            r["gemeente"][jaar] = score(m, "gemeente", O)
            r["gemeente"][jaar][0] = 0.0          # cellen zonder gemeente
            r["nl"][jaar] = score(m, "nl", O)
        th = np.vstack([r["tegel"][j] for j in R["jaren"]]).max(axis=0)
        gh = np.vstack([r["gemeente"][j] for j in R["jaren"]]).max(axis=0)
        r["tegel_hoogste"], r["gemeente_hoogste"] = th, gh
        r["tegel_volgorde"] = kies_zonder_overlap(V, th)
        r["tegel_opvallend"] = [w for w in r["tegel_volgorde"] if th[w] >= O["opvallend_score"]]
        r["gemeente_volgorde"] = [int(g) for g in np.argsort(-gh, kind="stable") if gh[g] > 0]
        r["gemeente_opvallend"] = [g for g in r["gemeente_volgorde"] if gh[g] >= O["opvallend_score"]]
        uit["runs"][rn] = r
    return uit


# ------------------------------------------------------------------ kaarten

KLEUR = {"buiten": (236, 236, 236), "land": (255, 255, 255), "kern": (210, 210, 210), "basis_kern": (135, 135, 135),
         "basis_buiten": (40, 40, 40), "bag": (125, 85, 40), "werk": (200, 175, 225), "kiem_wonen": (255, 140, 0),
         "kiem_werken": (200, 0, 200), "kiem_werken_start": (120, 70, 120), "grens": (150, 150, 150), "alleen_run": (215, 48, 39),
         "alleen_vgl": (69, 117, 180), "beide": (150, 120, 190), "rooster": (190, 190, 190)}
JAARKLEUREN = [(150, 30, 30), (40, 100, 220), (40, 170, 70), (230, 170, 0), (0, 170, 170), (120, 60, 160),
               (230, 110, 150), (140, 90, 40), (20, 20, 20)]
SCOREKLASSEN = [1, 3, 10, 30, 100, 300]
SCOREKLEUREN = [(255, 255, 204), (255, 237, 160), (254, 217, 118), (254, 178, 76), (253, 141, 60), (240, 59, 32),
                (189, 0, 38)]


def lettertype(n, vet=False):
    from PIL import ImageFont
    for f in (("arialbd.ttf" if vet else "arial.ttf"), ("DejaVuSans-Bold.ttf" if vet else "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(f, n)
        except Exception:
            continue
    return ImageFont.load_default()


def in_venster(idx, ncol, v):
    r0, r1, c0, c1 = v
    r, c = np.divmod(np.asarray(idx, dtype=np.int64), ncol)
    s = (r >= r0) & (r < r1) & (c >= c0) & (c < c1)
    return r[s] - r0, c[s] - c0, s


def kleur(im, idx, ncol, v, rgb):
    rr, cc, _ = in_venster(idx, ncol, v)
    im[rr, cc] = rgb


def basisbeeld(kd, rp, gem, v):
    r0, r1, c0, c1 = v
    g = gem[r0:r1, c0:c1]
    kern = kd[f"{rp}/kern"][r0:r1, c0:c1]
    w0 = kd[f"{rp}/w0pos"][r0:r1, c0:c1]
    im = np.full((r1 - r0, c1 - c0, 3), 255, dtype=np.uint8)
    im[g == 0] = KLEUR["buiten"]
    im[kern] = KLEUR["kern"]
    grens = np.zeros(g.shape, dtype=bool)
    grens[:, :-1] |= g[:, :-1] != g[:, 1:]
    grens[:-1, :] |= g[:-1, :] != g[1:, :]
    im[grens] = KLEUR["grens"]
    im[w0 & kern] = KLEUR["basis_kern"]
    im[w0 & ~kern] = KLEUR["basis_buiten"]
    return im, g


def schrijf_namen(draw, g, gem_namen, schaal, font, min_aandeel=0.01):
    """De gemeentenaam op het punt van de gemeente dat het verst van zijn rand in het venster ligt, binnen het beeld."""
    tel = np.bincount(g.ravel(), minlength=len(gem_namen))
    H, W = g.shape
    for gi in np.flatnonzero(tel):
        if gi == 0 or tel[gi] / g.size < min_aandeel:
            continue
        d = ndi.distance_transform_edt(np.pad(g == gi, 1))[1:-1, 1:-1]
        y, x = np.unravel_index(int(np.argmax(d)), d.shape)
        tekst = gem_namen[gi]
        b = draw.textbbox((0, 0), tekst, font=font)
        bx, by = b[2] - b[0], b[3] - b[1]
        px = min(max((x + 0.5) * schaal - bx / 2, 6), W * schaal - bx - 6)
        py = min(max((y + 0.5) * schaal - by / 2, 6), H * schaal - by - 6)
        draw.text((px, py), tekst, fill=(40, 40, 40), font=font, stroke_width=4, stroke_fill=(255, 255, 255))


def schaalbalk(draw, cel, schaal, hoogte, font, km=2):
    lengte = km * 1000 / cel * schaal
    x0, yb = 20, hoogte - 34
    draw.rectangle([x0 - 8, yb - 34, x0 + lengte + 12, yb + 18], fill=(255, 255, 255))
    draw.rectangle([x0, yb, x0 + lengte, yb + 9], fill=(0, 0, 0))
    draw.text((x0, yb - 30), f"{km} km", fill=(0, 0, 0), font=font)


def wrap(tekst, font, draw, breedte):
    regels, huidig = [], ""
    for w in tekst.split():
        test = (huidig + " " + w).strip()
        if draw.textlength(test, font=font) <= breedte or not huidig:
            huidig = test
        else:
            regels.append(huidig)
            huidig = w
    if huidig:
        regels.append(huidig)
    return regels


def zijpaneel(breedte, hoogte, titel, regels, legenda, fonts):
    from PIL import Image, ImageDraw
    p = Image.new("RGB", (breedte, hoogte), (255, 255, 255))
    d = ImageDraw.Draw(p)
    y = 18
    for t in wrap(titel, fonts["titel"], d, breedte - 36):
        d.text((18, y), t, fill=(0, 0, 0), font=fonts["titel"])
        y += 34
    y += 8
    for r in regels:
        for t in wrap(r, fonts["tekst"], d, breedte - 36):
            d.text((18, y), t, fill=(30, 30, 30), font=fonts["tekst"])
            y += 25
        y += 4
    y += 14
    for rgb, tekst, vorm in legenda:
        if vorm == "vlak":
            d.rectangle([18, y + 2, 42, y + 24], fill=rgb, outline=(0, 0, 0))
        elif vorm == "cirkel_dik":
            d.ellipse([18, y, 44, y + 26], outline=rgb, width=4)
        elif vorm == "cirkel_dun":
            d.ellipse([18, y, 44, y + 26], outline=rgb, width=1)
        elif vorm == "lijn":
            d.line([18, y + 13, 44, y + 13], fill=rgb, width=2)
        for t in wrap(tekst, fonts["tekst"], d, breedte - 76):
            d.text((54, y + 2), t, fill=(0, 0, 0), font=fonts["tekst"])
            y += 25
        y += 9
    return p


def teken_cirkels(draw, kd, rp, jaren, v, schaal, alleen_gegroeid=False):
    """Een cirkel om elke kiem (los cluster van de stand voor een zichtjaar) in het venster: oranje met wonen, paars
    met alleen werken; dik als er in het zichtjaar erna woningen in zijn ring kwamen, dun als niet."""
    r0, r1, c0, c1 = v
    getekend = []
    for jaar in jaren:
        if f"{rp}/{jaar}/kiem_rij" not in kd:
            continue
        rij, kol = kd[f"{rp}/{jaar}/kiem_rij"], kd[f"{rp}/{jaar}/kiem_kol"]
        cellen, wonen, groeide = kd[f"{rp}/{jaar}/kiem_cellen"], kd[f"{rp}/{jaar}/kiem_wonen"], kd[f"{rp}/{jaar}/kiem_groeide"]
        s = (rij >= r0) & (rij < r1) & (kol >= c0) & (kol < c1)
        if alleen_gegroeid:
            s &= groeide
        for i in np.flatnonzero(s):
            x, y = (kol[i] - c0 + 0.5) * schaal, (rij[i] - r0 + 0.5) * schaal
            straal = max(10.0, (math.sqrt(cellen[i] / math.pi) + 3.0) * schaal)
            if any((x - gx) ** 2 + (y - gy) ** 2 < gr ** 2 for gx, gy, gr in getekend):
                continue
            getekend.append((x, y, straal))
            rgb = KLEUR["kiem_wonen"] if wonen[i] else KLEUR["kiem_werken"]
            draw.ellipse([x - straal, y - straal, x + straal, y + straal], outline=rgb, width=4 if groeide[i] else 1)


def plak_paneel(kaart, paneel, pad):
    from PIL import Image, ImageDraw
    geheel = Image.new("RGB", (kaart.size[0] + paneel.size[0], kaart.size[1]), (255, 255, 255))
    geheel.paste(kaart, (0, 0))
    geheel.paste(paneel, (kaart.size[0], 0))
    ImageDraw.Draw(geheel).line([kaart.size[0], 0, kaart.size[0], kaart.size[1]], fill=(160, 160, 160), width=2)
    geheel.save(pad, optimize=True)


def legenda_basis(met_bag):
    l = [(KLEUR["basis_kern"], "woningen in het basisjaar, in een BRT-woonkern", "vlak"),
         (KLEUR["basis_buiten"], "woningen in het basisjaar, buiten een woonkern (erven, linten)", "vlak"),
         (KLEUR["kern"], "BRT-woonkern", "vlak")]
    if met_bag:
        l.append((KLEUR["bag"], "BAG-nieuwbouw in de startstand", "vlak"))
    return l


def teken_detail(kd, M, rn, v, gem, gem_namen, ncol, cel, pad, kop, regels, schaal=2, focus=None):
    """Detailkaart van een venster; met focus (een gemeente-index) is alles buiten die gemeente lichter."""
    from PIL import Image, ImageDraw
    jaren = list(M["runs"][rn]["jaren"])
    im, g = basisbeeld(kd, rn, gem, v)
    kleur(im, kd[f"{rn}/{jaren[-1]}/werk_idx"], ncol, v, KLEUR["werk"])
    met_bag = f"{rn}/{jaren[0]}/bag_idx" in kd
    if met_bag:
        kleur(im, kd[f"{rn}/{jaren[0]}/bag_idx"], ncol, v, KLEUR["bag"])
    for i, jaar in enumerate(jaren):
        kleur(im, kd[f"{rn}/{jaar}/model_idx"], ncol, v, JAARKLEUREN[i % len(JAARKLEUREN)])
    # kiemen zonder nieuwe woningen zichtbaar maken: die van de startstand met wonen oranje, die met alleen werken paars
    if f"{rn}/{jaren[0]}/kiem_idx" in kd:
        cel_w = kd[f"{rn}/{jaren[0]}/kiem_wonen"][kd[f"{rn}/{jaren[0]}/kiem_van_cel"]]
        kleur(im, kd[f"{rn}/{jaren[0]}/kiem_idx"][cel_w], ncol, v, KLEUR["kiem_wonen"])
    for jaar in jaren:
        if f"{rn}/{jaar}/kiem_idx" in kd:
            van = kd[f"{rn}/{jaar}/kiem_van_cel"]
            cel_w = kd[f"{rn}/{jaar}/kiem_wonen"][van]
            cel_m = kd[f"{rn}/{jaar}/kiem_model"][van]
            kleur(im, kd[f"{rn}/{jaar}/kiem_idx"][~cel_w & ~cel_m], ncol, v, KLEUR["kiem_werken_start"])
            kleur(im, kd[f"{rn}/{jaar}/kiem_idx"][~cel_w & cel_m], ncol, v, KLEUR["kiem_werken"])
    if focus is not None:
        buiten = g != focus
        im[buiten] = (im[buiten].astype(np.float32) * 0.4 + 255 * 0.6).astype(np.uint8)
    H, W = im.shape[:2]
    kaart = Image.fromarray(im).resize((W * schaal, H * schaal), Image.NEAREST)
    d = ImageDraw.Draw(kaart)
    teken_cirkels(d, kd, rn, jaren, v, schaal)
    fonts = {"titel": lettertype(28, True), "tekst": lettertype(20), "naam": lettertype(26, True)}
    schrijf_namen(d, g, gem_namen, schaal, fonts["naam"])
    schaalbalk(d, cel, schaal, kaart.size[1], fonts["tekst"])
    legenda = legenda_basis(met_bag)
    for i, jaar in enumerate(jaren):
        legenda.append((JAARKLEUREN[i % len(JAARKLEUREN)], f"nieuwe woningen {jaar[1:]} (model)", "vlak"))
    legenda += [(KLEUR["werk"], "nieuwe werklocaties (model)", "vlak"),
                (KLEUR["kiem_wonen"], "los cluster met wonen (oranje gevuld als het uit de startstand komt), met nieuwe woningen in zijn ring in het zichtjaar erna", "cirkel_dik"),
                (KLEUR["kiem_wonen"], "los cluster met wonen, zonder", "cirkel_dun"),
                (KLEUR["kiem_werken"], "los cluster met alleen werken (paars gevuld, donkerpaars als het alleen uit de startstand komt), met nieuwe woningen in zijn ring", "cirkel_dik"),
                (KLEUR["kiem_werken"], "los cluster met alleen werken, zonder", "cirkel_dun"),
                (KLEUR["grens"], "gemeentegrens", "lijn")]
    plak_paneel(kaart, zijpaneel(560, kaart.size[1], kop, regels, legenda, fonts), pad)


def teken_verschil(kd, M, v, gem, gem_namen, ncol, cel, pad, kop, regels, namen, schaal=2):
    """Verschilkaart van een tegel: de cellen met nieuwe woningen over alle zichtjaren in de ene run, de andere of beide."""
    from PIL import Image, ImageDraw
    im, g = basisbeeld(kd, "run", gem, v)
    r0, r1, c0, c1 = v
    sets = {}
    for rn in RUNS:
        m = np.zeros((r1 - r0, c1 - c0), dtype=bool)
        for jaar in M["runs"][rn]["jaren"]:
            for soort in ("model_idx", "bag_idx"):
                k = f"{rn}/{jaar}/{soort}"
                if k in kd:
                    rr, cc, _ = in_venster(kd[k], ncol, v)
                    m[rr, cc] = True
        sets[rn] = m
    im[sets["run"] & ~sets["vergelijk"]] = KLEUR["alleen_run"]
    im[~sets["run"] & sets["vergelijk"]] = KLEUR["alleen_vgl"]
    im[sets["run"] & sets["vergelijk"]] = KLEUR["beide"]
    H, W = im.shape[:2]
    kaart = Image.fromarray(im).resize((W * schaal, H * schaal), Image.NEAREST)
    d = ImageDraw.Draw(kaart)
    teken_cirkels(d, kd, "run", list(M["runs"]["run"]["jaren"]), v, schaal, alleen_gegroeid=True)
    fonts = {"titel": lettertype(28, True), "tekst": lettertype(20), "naam": lettertype(26, True)}
    schrijf_namen(d, g, gem_namen, schaal, fonts["naam"])
    schaalbalk(d, cel, schaal, kaart.size[1], fonts["tekst"])
    legenda = legenda_basis(False)[:3] + [
        (KLEUR["alleen_run"], f"nieuwe woningen alleen in {namen['run']}", "vlak"),
        (KLEUR["alleen_vgl"], f"nieuwe woningen alleen in {namen['vergelijk']}", "vlak"),
        (KLEUR["beide"], "nieuwe woningen in beide runs", "vlak"),
        (KLEUR["kiem_wonen"], f"los cluster met wonen in {namen['run']}, met nieuwe woningen in zijn ring", "cirkel_dik"),
        (KLEUR["kiem_werken"], f"los cluster met alleen werken in {namen['run']}, met nieuwe woningen in zijn ring", "cirkel_dik"),
        (KLEUR["grens"], "gemeentegrens", "lijn")]
    plak_paneel(kaart, zijpaneel(560, kaart.size[1], kop, regels, legenda, fonts), pad)


def scorekleur(s):
    for grens, rgb in zip(SCOREKLASSEN, SCOREKLEUREN):
        if s < grens:
            return rgb
    return SCOREKLEUREN[-1]


def teken_overzicht(kd, M, B, rn, V, gem, pad, top, titel):
    """Per zichtjaar een paneel van het studiegebied met de score per vak; de tegels met een detailkaart omlijnd en
    genummerd."""
    from PIL import Image, ImageDraw
    vakken = V.v
    H, W = gem.shape
    f = max(1, math.ceil(max(H, W) / 820))
    Hp, Wp = math.ceil(H / f) * f, math.ceil(W / f) * f

    def blok(a):
        b = np.zeros((Hp, Wp), dtype=np.float32)
        b[:H, :W] = a
        return b.reshape(Hp // f, f, Wp // f, f).mean(axis=(1, 3))

    land = blok(gem > 0) > 0.3
    stad = blok(kd[f"{rn}/w0pos"]) > 0.12
    jaren = list(M["runs"][rn]["jaren"])
    fonts = {"titel": lettertype(26, True), "tekst": lettertype(18), "klein": lettertype(15, True)}
    panelen = []
    for jaar in jaren:
        s = B["runs"][rn]["vak"][jaar]
        im = np.full(land.shape + (3,), 245, dtype=np.uint8)
        im[land] = (255, 255, 255)
        laag = np.zeros(land.shape + (3,), dtype=np.float32)
        alfa = np.zeros(land.shape, dtype=np.float32)
        for t in range(vakken.n):
            if s[t] <= 0:
                continue
            r0, r1, c0, c1 = vakken.venster(t)
            laag[r0 // f:math.ceil(r1 / f), c0 // f:math.ceil(c1 / f)] = scorekleur(s[t])
            alfa[r0 // f:math.ceil(r1 / f), c0 // f:math.ceil(c1 / f)] = 0.85
        alfa *= land
        im = (im * (1 - alfa[..., None]) + laag * alfa[..., None]).astype(np.uint8)
        im[stad] = (90, 90, 90)
        p = Image.fromarray(im)
        d = ImageDraw.Draw(p)
        for tc in range(vakken.nx):
            x = np.flatnonzero(vakken.kol == tc)[0] / f
            d.line([x, 0, x, p.size[1]], fill=KLEUR["rooster"], width=1)
        for tr in range(vakken.ny):
            y = np.flatnonzero(vakken.rij == tr)[0] / f
            d.line([0, y, p.size[0], y], fill=KLEUR["rooster"], width=1)
        for nr, w in enumerate(top, start=1):
            r0, r1, c0, c1 = V.venster(w)
            d.rectangle([c0 / f, r0 / f, c1 / f, r1 / f], outline=(0, 0, 0), width=3)
            x, y = (c0 + c1) / 2 / f, (r0 + r1) / 2 / f
            d.ellipse([x - 13, y - 13, x + 13, y + 13], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
            tekst = str(nr)
            b = d.textbbox((0, 0), tekst, font=fonts["klein"])
            d.text((x - (b[2] - b[0]) / 2, y - (b[3] - b[1]) / 2 - 2), tekst, fill=(0, 0, 0), font=fonts["klein"])
        paneel = Image.new("RGB", (p.size[0], p.size[1] + 44), (255, 255, 255))
        ImageDraw.Draw(paneel).text((10, 8), f"{jaar[1:]}", fill=(0, 0, 0), font=fonts["titel"])
        paneel.paste(p, (0, 44))
        panelen.append(paneel)
    breedte = sum(p.size[0] for p in panelen) + 12 * (len(panelen) - 1)
    geheel = Image.new("RGB", (breedte, panelen[0].size[1] + 110), (255, 255, 255))
    x = 0
    for p in panelen:
        geheel.paste(p, (x, 0))
        x += p.size[0] + 12
    d = ImageDraw.Draw(geheel)
    y = panelen[0].size[1] + 12
    d.text((10, y), titel, fill=(0, 0, 0), font=fonts["tekst"])
    y += 34
    x = 10
    grenzen = [0] + SCOREKLASSEN
    for i, rgb in enumerate(SCOREKLEUREN):
        tekst = f"{grenzen[i]:g} tot {grenzen[i + 1]:g}" if i + 1 < len(grenzen) else f"{grenzen[i]:g} en meer"
        d.rectangle([x, y, x + 26, y + 22], fill=rgb, outline=(0, 0, 0))
        d.text((x + 34, y), tekst, fill=(0, 0, 0), font=fonts["tekst"])
        x += 60 + d.textlength(tekst, font=fonts["tekst"])
    d.rectangle([x, y, x + 26, y + 22], fill=(90, 90, 90))
    d.text((x + 34, y), "bebouwd in het basisjaar", fill=(0, 0, 0), font=fonts["tekst"])
    geheel.save(pad, optimize=True)


# ------------------------------------------------------------------ rapport

def fmt(x, dec=0):
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    return f"{x:,.{dec}f}"


def pct(a, b):
    return f"{a / b:.0%}" if b else ""


class Document:
    """Een rapport als lijst van blokken, met nummers voor hoofdstukken, tabellen en figuren en verwijzingen op id
    ({ref:id} in de tekst), dat zowel markdown als html wordt."""

    def __init__(self):
        self.blokken = []
        self.nummers = {}
        self.teller = {"h": 0, "tabel": 0, "figuur": 0}

    def hoofdstuk(self, id_, titel):
        self.teller["h"] += 1
        self.nummers[id_] = f"hoofdstuk {self.teller['h']}"
        self.blokken.append(("h", id_, self.teller["h"], titel))

    def alinea(self, tekst):
        self.blokken.append(("p", tekst))

    def lijst(self, items):
        self.blokken.append(("ul", items))

    def tabel(self, id_, titel, sub, kop, rijen, onderschrift, zichtbaar=None, rechts=None):
        """zichtbaar: zoveel rijen staan open; de volledige tabel staat in het html-rapport in een uitklap eronder."""
        self.teller["tabel"] += 1
        self.nummers[id_] = f"tabel {self.teller['tabel']}"
        self.blokken.append(("tabel", id_, self.teller["tabel"], titel, sub, kop, rijen, onderschrift, zichtbaar, rechts))

    def figuur(self, id_, titel, sub, bestand, onderschrift):
        self.teller["figuur"] += 1
        self.nummers[id_] = f"figuur {self.teller['figuur']}"
        self.blokken.append(("figuur", id_, self.teller["figuur"], titel, sub, bestand, onderschrift))

    def vul(self, tekst):
        return re.sub(r"\{ref:([^}]+)\}", lambda m: self.nummers.get(m.group(1), m.group(1)), tekst)

    def markdown(self, titel, lede, meta):
        uit = [f"# {titel}", "", self.vul(lede), "", self.vul(meta), ""]
        for b in self.blokken:
            if b[0] == "h":
                uit += [f"## {b[2]}. {b[3]}", ""]
            elif b[0] == "p":
                uit += [self.vul(b[1]), ""]
            elif b[0] == "ul":
                uit += [f"- {self.vul(i)}" for i in b[1]] + [""]
            elif b[0] == "tabel":
                _, _, n, t, sub, kop, rijen, onder, zichtbaar, _ = b
                uit += [f"Tabel {n}. {t}", "", f"*{self.vul(sub)}*", ""]
                uit.append("| " + " | ".join(kop) + " |")
                uit.append("|" + "|".join("---" for _ in kop) + "|")
                for r in rijen[:zichtbaar]:
                    uit.append("| " + " | ".join(str(x) for x in r) + " |")
                uit += ["", self.vul(onder), ""]
                if zichtbaar and len(rijen) > zichtbaar:
                    uit += [f"De volledige tabel van {len(rijen)} rijen staat in rapport.html.", ""]
            elif b[0] == "figuur":
                _, _, n, t, sub, best, onder = b
                uit += [f"Figuur {n}. {t}", "", f"*{self.vul(sub)}*", "", f"![Figuur {n}]({best})", "", self.vul(onder), ""]
        return "\n".join(uit)

    def html(self, titel, lede, meta):
        e = html.escape
        toc, body = [], []
        for b in self.blokken:
            if b[0] == "h":
                toc.append(f'<li><a href="#{b[1]}"><span class="n">{b[2]}</span><span>{e(b[3])}</span></a></li>')
                body.append(f'<h2 id="{b[1]}"><span class="n">{b[2]}</span><span>{e(b[3])}</span></h2>')
            elif b[0] == "p":
                body.append(f"<p>{e(self.vul(b[1]))}</p>")
            elif b[0] == "ul":
                body.append("<ul>" + "".join(f"<li>{e(self.vul(i))}</li>" for i in b[1]) + "</ul>")
            elif b[0] == "tabel":
                _, id_, n, t, sub, kop, rijen, onder, zichtbaar, rechts = b
                rechts = rechts if rechts is not None else set(range(1, len(kop)))
                th = "".join(f'<th class="{"r" if i in rechts else ""}">{e(k)}</th>' for i, k in enumerate(kop))

                def tbl(rr):
                    tr = "".join("<tr>" + "".join(f'<td class="{"r" if i in rechts else ""}">{e(str(x))}</td>'
                                                  for i, x in enumerate(r)) + "</tr>" for r in rr)
                    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
                tabel = tbl(rijen[:zichtbaar])
                if zichtbaar and len(rijen) > zichtbaar:
                    tabel += f"<details><summary>Toon alle {len(rijen)} rijen</summary>{tbl(rijen)}</details>"
                body.append(f'<figure class="tab" id="{id_}"><div class="fig-h">Tabel {n}. {e(t)}</div>'
                            f'<div class="fig-s">{e(self.vul(sub))}</div>{tabel}'
                            f'<figcaption>{e(self.vul(onder))}</figcaption></figure>')
            elif b[0] == "figuur":
                _, id_, n, t, sub, best, onder = b
                body.append(f'<figure id="{id_}"><div class="fig-h">Figuur {n}. {e(t)}</div>'
                            f'<div class="fig-s">{e(self.vul(sub))}</div>'
                            f'<div class="beeld"><a href="{e(best)}"><img src="{e(best)}" alt="Figuur {n}. {e(t)}" loading="lazy"></a></div>'
                            f'<figcaption>{e(self.vul(onder))}</figcaption></figure>')
        return f"""<!DOCTYPE html>
<html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(titel)}</title>
<style>
:root{{--ground:#F6F7F4;--surface:#FCFCFA;--surface-2:#EEF1EC;--ink:#1A2126;--ink-2:#4C5860;--muted:#7C8790;--line:#DDE1DC;
 --ui:"Segoe UI",system-ui,sans-serif;--body:"Segoe UI",system-ui,sans-serif;--mono:ui-monospace,Consolas,monospace}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--ground:#141719;--surface:#1B1F22;--surface-2:#22272B;
 --ink:#E9ECE8;--ink-2:#B4BCB6;--muted:#8A9490;--line:#2A3034}}}}
:root[data-theme="dark"]{{--ground:#141719;--surface:#1B1F22;--surface-2:#22272B;--ink:#E9ECE8;--ink-2:#B4BCB6;--muted:#8A9490;--line:#2A3034}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);font-family:var(--body);font-size:16px;line-height:1.55}}
.page{{display:grid;grid-template-columns:1fr;max-width:1180px;margin:0 auto;padding:0 16px 80px}}
@media (min-width:1100px){{.page{{grid-template-columns:220px minmax(0,1fr);column-gap:48px}}}}
nav.toc{{font-family:var(--ui);font-size:13px;color:var(--ink-2);padding-top:32px}}
@media (min-width:1100px){{nav.toc{{position:sticky;top:0;align-self:start;max-height:100vh;overflow:auto;padding-top:56px}}}}
nav.toc ol{{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}}
nav.toc a{{text-decoration:none;color:inherit;display:grid;grid-template-columns:24px 1fr;gap:6px}}
nav.toc .n{{color:var(--muted)}}
main{{min-width:0}}
header.kop{{padding:48px 0 28px;border-bottom:1px solid var(--line);margin-bottom:24px}}
h1{{font-size:clamp(28px,4vw,40px);line-height:1.1;margin:0 0 14px;font-weight:600}}
.lede{{font-size:18px;color:var(--ink-2);margin:0 0 16px}}
.meta{{font-family:var(--ui);font-size:13px;color:var(--muted);overflow-wrap:anywhere}}
h2{{font-size:24px;margin:56px 0 14px;display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:baseline;font-weight:600}}
h2 .n{{font-size:14px;color:var(--muted)}}
p{{margin:0 0 14px}} ul{{padding-left:22px}} li{{margin-bottom:6px}} p,li,figcaption{{overflow-wrap:anywhere}}
figure{{margin:26px 0 34px}}
.fig-h{{font-family:var(--ui);font-weight:600;font-size:15px;margin:0 0 2px}}
.fig-s{{font-family:var(--ui);font-size:13px;color:var(--ink-2);margin:0 0 10px}}
figcaption{{font-family:var(--ui);font-size:13px;color:var(--ink-2);margin-top:8px}}
.beeld{{background:#fff;border:1px solid var(--line);border-radius:4px;padding:6px}}
.beeld img{{display:block;width:100%;height:auto}}
.tw{{overflow-x:auto;border:1px solid var(--line);border-radius:4px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-family:var(--ui);font-size:13px;font-variant-numeric:tabular-nums}}
th,td{{padding:5px 9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{background:var(--surface-2);font-weight:600}}
td.r,th.r{{text-align:right}}
details summary{{cursor:pointer;font-family:var(--ui);font-size:13px;margin:4px 0 8px}}
</style></head><body><div class="page">
<nav class="toc" aria-label="Inhoud"><ol>{''.join(toc)}</ol></nav>
<main><header class="kop"><h1>{e(titel)}</h1><p class="lede">{e(self.vul(lede))}</p><div class="meta">{e(self.vul(meta))}</div></header>
{''.join(body)}
</main></div></body></html>"""


class Maten:
    """Leest een maat per tegel (som van zijn vakken), per gemeente of landelijk uit de meting."""

    def __init__(self, M, V):
        self.M, self.V, self.cache = M, V, {}

    def __call__(self, rn, jaar, naam, eenheid, i=None):
        R = self.M["runs"][rn]
        if jaar not in R["jaren"] or naam not in R["jaren"][jaar]["maten"]:
            return 0.0
        m = R["jaren"][jaar]["maten"][naam]
        if eenheid == "nl":
            return float(m["nl"])
        if eenheid == "tegel":
            k = (rn, jaar, naam)
            if k not in self.cache:
                self.cache[k] = self.V.som(m["vak"])
            return float(self.cache[k][i])
        return float(m[eenheid][i])


def tegel_gemeenten_namen(M, V, w, n=3):
    tel = {}
    for t in V.vakken(w):
        for g, ha in M["eenheden"]["vak"]["gemeenten_ha"][t].items():
            tel[g] = tel.get(g, 0.0) + ha
    namen = sorted(tel, key=lambda g: -tel[g])[:n]
    return ", ".join(namen) if namen else "zee of buiten het studiegebied"


def regels_eenheid(mt, B, rn, eenheid, i, jaren):
    """Per zichtjaar een regel met de score en de maten, voor de zijkant van een kaart en de onderschriften."""
    regels = []
    for jaar in jaren:
        nieuw = mt(rn, jaar, "model_nieuw", eenheid, i)
        ring = mt(rn, jaar, "ring", eenheid, i)
        ver = mt(rn, jaar, "model_ver", eenheid, i)
        kg = mt(rn, jaar, "kiemen_aangegroeid_n", eenheid, i)
        s = B["runs"][rn][eenheid][jaar][i]
        regels.append(f"{jaar[1:]}: score {s:,.0f}; {nieuw:,.0f} nieuwe woningen, waarvan {pct(ring, nieuw) or '0%'} in een "
                      f"ring en {pct(ver, nieuw) or '0%'} verder dan 1 km van een kern; {kg:,.0f} losse clusters aangegroeid.")
    return regels


def opsomming(woorden):
    woorden = list(woorden)
    if not woorden:
        return ""
    return woorden[0] if len(woorden) == 1 else ", ".join(woorden[:-1]) + " en " + woorden[-1]


def gemeentevensters(gem, marge):
    """Per gemeente-index het venster (r0, r1, c0, c1) van zijn cellen plus een marge in cellen."""
    H, W = gem.shape
    uit = {}
    for i, sl in enumerate(ndi.find_objects(gem), start=1):
        if sl is None:
            continue
        uit[i] = (max(sl[0].start - marge, 0), min(sl[0].stop + marge, H), max(sl[1].start - marge, 0), min(sl[1].stop + marge, W))
    return uit


def stijgers(B, jaar, n):
    """De n gemeenten met de grootste stijging van de score van de vergelijkingsrun naar de run in een zichtjaar."""
    d = np.asarray(B["runs"]["run"]["gemeente"][jaar]) - np.asarray(B["runs"]["vergelijk"]["gemeente"][jaar])
    return [(int(g), float(d[g])) for g in np.argsort(-d, kind="stable")[:n] if g > 0 and d[g] >= 0.5]


def zoek_gemeente(naam, gem_namen):
    sleutel = re.sub(r"[\s_\-']+", "", naam).lower()
    for i, g in enumerate(gem_namen):
        if i and re.sub(r"[\s_\-']+", "", g).lower() == sleutel:
            return i
    raise ValueError(f"gemeente {naam} niet gevonden in de buurtnamen")


def maak_rapport(M, B, kd, gem, V, ncol, cel, out, top_n, tijden, extra_gemeenten=()):
    """Kaarten en rapport uit meting en oordeel."""
    kaartmap = os.path.join(out, "kaarten")
    os.makedirs(kaartmap, exist_ok=True)
    O = B["oordeel"]
    P = M["meten"]
    mt = Maten(M, V)
    namen = {rn: M["runs"][rn]["label"] for rn in M["runs"]}
    R = M["runs"]["run"]
    BR = B["runs"]["run"]
    jaren = list(R["jaren"])
    eerste = jaren[0]
    gem_namen = M["eenheden"]["gemeente"]
    met_vgl = "vergelijk" in M["runs"]
    top = BR["tegel_volgorde"][:top_n]
    tl = lambda w: tegel_gemeenten_namen(M, V, w)
    t0 = time.perf_counter()

    # ---- kaarten
    overzicht = os.path.join(kaartmap, "overzicht.png")
    teken_overzicht(kd, M, B, "run", V, gem, overzicht, top,
                    f"Score per vak van {V.v.km} km, {namen['run']}; omlijnd en genummerd de tegels van {V.km} km met een detailkaart")
    details = []
    for nr, w in enumerate(top, start=1):
        pad = os.path.join(kaartmap, f"tegel_{nr:02d}_{V.naam(w)}.png")
        kop = f"{nr}. Tegel {V.naam(w)} ({tl(w)})"
        teken_detail(kd, M, "run", V.venster(w), gem, gem_namen, ncol, cel, pad, kop, regels_eenheid(mt, B, "run", "tegel", w, jaren))
        details.append((nr, w, pad))
        meld(f"kaart {os.path.basename(pad)}")
    gemkaarten = []
    keuze = list(BR["gemeente_volgorde"][:O["top_gemeentekaarten"]])
    for naam in extra_gemeenten:
        g = zoek_gemeente(naam, gem_namen)
        if g not in keuze:
            keuze.append(g)
    if keuze:
        vensters = gemeentevensters(gem, int(round(1000 / cel)))
        for g in keuze:
            if g not in vensters:
                continue
            v = vensters[g]
            schaal = 2 if max(v[1] - v[0], v[3] - v[2]) <= 1400 else 1
            pad = os.path.join(kaartmap, f"gemeente_{re.sub(r'[^A-Za-z0-9]+', '_', gem_namen[g]).strip('_')}.png")
            teken_detail(kd, M, "run", v, gem, gem_namen, ncol, cel, pad, f"Gemeente {gem_namen[g]}",
                         regels_eenheid(mt, B, "run", "gemeente", g, jaren), schaal=schaal, focus=g)
            gemkaarten.append((g, pad))
            meld(f"kaart {os.path.basename(pad)}")
    verschil = []
    if met_vgl:
        jv = [j for j in jaren if j in M["runs"]["vergelijk"]["jaren"]]
        teken_overzicht(kd, M, B, "vergelijk", V, gem, os.path.join(kaartmap, "overzicht_vergelijk.png"), top,
                        f"Score per vak van {V.v.km} km, {namen['vergelijk']}; omlijnd en genummerd dezelfde tegels als bij {namen['run']}")
        for nr, w in enumerate(top, start=1):
            pad = os.path.join(kaartmap, f"verschil_{nr:02d}_{V.naam(w)}.png")
            kop = f"{nr}. Tegel {V.naam(w)} ({tl(w)}): {namen['run']} tegen {namen['vergelijk']}"
            regels = [f"{j[1:]}: score {BR['tegel'][j][w]:,.0f} in {namen['run']}, "
                      f"{B['runs']['vergelijk']['tegel'][j][w]:,.0f} in {namen['vergelijk']}; ringwoningen "
                      f"{mt('run', j, 'ring', 'tegel', w):,.0f} tegen {mt('vergelijk', j, 'ring', 'tegel', w):,.0f}." for j in jv]
            teken_verschil(kd, M, V.venster(w), gem, gem_namen, ncol, cel, pad, kop, regels, namen)
            verschil.append((nr, w, pad))
            meld(f"kaart {os.path.basename(pad)}")
    tijden["kaarten_s"] = round(time.perf_counter() - t0, 1)

    # ---- rapport
    doc = Document()
    rel = lambda p: os.path.relpath(p, out).replace("\\", "/")
    nl = lambda rn, j, k: mt(rn, j, k, "nl")
    min_aandeel = O["aandeel_min_woningen"]

    doc.hoofdstuk("kern", "Kern")
    bn = nl("run", eerste, "bag_nieuw")
    gebied = "Landelijk" if M["provenance"]["suffix"] == "Nederland" else f"In het studiegebied {M['provenance']['suffix'].replace('_', '-')}"
    doc.alinea(f"{gebied} ligt in {opsomming(j[1:] for j in jaren)} "
               f"{opsomming(pct(nl('run', j, 'ring'), nl('run', j, 'model_nieuw')) for j in jaren)} van de nieuwe modelwoningen in een "
               f"ring rond een los cluster van de stand ervoor ({opsomming(fmt(nl('run', j, 'ring')) for j in jaren)} woningen), en "
               f"{opsomming(pct(nl('run', j, 'model_ver'), nl('run', j, 'model_nieuw')) for j in jaren)} verder dan 1 km van een "
               f"BRT-woonkern. Van de BAG-nieuwbouw in de startstand, de referentie, ligt {pct(nl('run', eerste, 'bag_ver'), bn)} verder "
               f"dan 1 km van een woonkern en {pct(nl('run', eerste, 'bag_kern'), bn)} binnen 250 m ({{ref:t-nl}}).")
    doc.alinea(f"In minstens een zichtjaar hebben {len(BR['tegel_opvallend'])} tegels van {V.km} km die elkaar niet overlappen een "
               f"score van {O['opvallend_score']:g} of meer, en {len(BR['gemeente_opvallend'])} gemeenten. De score telt de "
               f"ringwoningen per {O['ijkmaat_ringwoningen']:g}, de nieuwe woningen verder dan 1 km van een woonkern per "
               f"{O['ijkmaat_ver_woningen']:g} en de aangegroeide losse clusters per {O['ijkmaat_aangegroeide_kiemen']:g} "
               f"({{ref:maten}}). Bovenaan staan deze tegels en gemeenten:")
    met_kaart = {g for g, _ in gemkaarten}
    items = []
    for nr, w in enumerate(top[:5], start=1):
        jb = max(jaren, key=lambda j: BR["tegel"][j][w])
        n = mt("run", jb, "model_nieuw", "tegel", w)
        items.append(f"tegel {nr}, {V.naam(w)} ({tl(w)}): score {BR['tegel'][jb][w]:,.0f} in {jb[1:]}, met "
                     f"{fmt(mt('run', jb, 'ring', 'tegel', w))} van de {fmt(n)} nieuwe woningen in een ring "
                     f"({pct(mt('run', jb, 'ring', 'tegel', w), n)}) en {fmt(mt('run', jb, 'kiemen_aangegroeid_n', 'tegel', w))} "
                     f"aangegroeide losse clusters ({{ref:f-tegel-{nr}}});")
    for g in BR["gemeente_volgorde"][:5]:
        jb = max(jaren, key=lambda j: BR["gemeente"][j][g])
        n = mt("run", jb, "model_nieuw", "gemeente", g)
        items.append(f"gemeente {gem_namen[g]}: score {BR['gemeente'][jb][g]:,.0f} in {jb[1:]}, met "
                     f"{fmt(mt('run', jb, 'ring', 'gemeente', g))} van de {fmt(n)} nieuwe woningen in een ring "
                     f"({pct(mt('run', jb, 'ring', 'gemeente', g), n)}) en {pct(mt('run', jb, 'model_ver', 'gemeente', g), n)} "
                     f"verder dan 1 km van een kern" + (f" ({{ref:f-gem-{g}}});" if g in met_kaart else ";"))
    items[-1] = items[-1][:-1] + "."
    doc.lijst(items)
    # naar aandeel: de gemeenten waar het grootste deel van de nieuwbouw in ringen of ver van een kern landt
    aandeel = {}
    for jaar in jaren:
        for g in range(1, len(gem_namen)):
            n = mt("run", jaar, "model_nieuw", "gemeente", g)
            if n >= min_aandeel:
                a = (mt("run", jaar, "ring", "gemeente", g) + mt("run", jaar, "model_ver", "gemeente", g)) / (2 * n)
                if a > aandeel.get(g, (0, ""))[0]:
                    aandeel[g] = (a, jaar)
    beste = sorted(aandeel, key=lambda g: -aandeel[g][0])[:5]
    if beste:
        doc.alinea(f"Naar aandeel, bij gemeenten met minstens {min_aandeel:,.0f} nieuwe woningen in een zichtjaar, legt het model "
                   "het grootste deel van zijn nieuwbouw in ringen en ver van een kern in: " +
                   "; ".join(f"{gem_namen[g]} ({aandeel[g][1][1:]}: {pct(mt('run', aandeel[g][1], 'ring', 'gemeente', g), mt('run', aandeel[g][1], 'model_nieuw', 'gemeente', g))} "
                             f"in een ring, {pct(mt('run', aandeel[g][1], 'model_ver', 'gemeente', g), mt('run', aandeel[g][1], 'model_nieuw', 'gemeente', g))} verder dan 1 km)"
                             for g in beste) + ".")
    for naam in extra_gemeenten:
        g = zoek_gemeente(naam, gem_namen)
        plekken = []
        for jaar in jaren:
            sg = np.asarray(BR["gemeente"][jaar])
            plek = int((sg > sg[g]).sum())          # aantal gemeenten met een hogere score; index 0 heeft score 0
            plekken.append(f"in {jaar[1:]} plek {plek + 1} met score {sg[g]:,.0f}")
        n_gem = len({x for d in M["eenheden"]["vak"]["gemeenten_ha"] for x in d})
        doc.alinea(f"Gevraagd: {gem_namen[g]} staat " + opsomming(plekken) + f" van de {n_gem} gemeenten op het raster"
                   + (f" ({{ref:f-gem-{g}}})." if g in met_kaart else "."))
    if met_vgl:
        jv = [j for j in jaren if j in M["runs"]["vergelijk"]["jaren"]]
        doc.alinea(f"Tegen {namen['vergelijk']} ({{ref:vgl}}): " + "; ".join(
            f"in {j[1:]} {fmt(nl('run', j, 'ring'))} ringwoningen in {namen['run']} tegen {fmt(nl('vergelijk', j, 'ring'))} in "
            f"{namen['vergelijk']}" for j in jv) + ". Het sterkst gestegen is de score in " + "; ".join(
            f"{j[1:]} in " + (opsomming(f"{gem_namen[g]} (+{d:,.0f})" for g, d in stijgers(B, j, 5)) or "geen enkele gemeente")
            for j in jv[1:] or jv) + f" ({{ref:t-vgl-gem}}).")

    # tegels
    doc.hoofdstuk("tegels", "Tegels")
    doc.alinea(f"De maten zijn geteld per vak van {V.v.km} bij {V.v.km} km, op veelvouden van {V.v.km} km in RD-coordinaten. Een "
               f"tegel is een blok van {V.k} bij {V.k} vakken ({V.km} km) en begint op elk vak, zodat een brandhaard niet door een "
               f"tegelgrens gesplitst wordt; de naam {V.naam(top[0]) if top else 'x170_y510'} is de linkeronderhoek in RD-kilometers. "
               "De detailkaarten zijn van de tegels met de hoogste score die geen vak delen met een tegel die hoger staat. "
               "De score per vak staat in {ref:f-overzicht}, die van de tegels in {ref:t-toptegels}.")
    doc.figuur("f-overzicht", "Score per vak en zichtjaar", f"{namen['run']}; kleur is de score van een vak van {V.v.km} km, donkergrijs is bebouwd in het basisjaar",
               rel(overzicht), f"Een vak kleurt naar de som van zijn ringwoningen, verre woningen en aangegroeide losse clusters; een tegel "
               f"van {V.km} km heeft de som van zijn vier vakken. De omlijnde tegels hebben een detailkaart ({{ref:detail}}). Bron: patroonkaarten.py op de standkaarten.")
    kop = ["", "Tegel", "Gemeenten"] + [f"Score {j[1:]}" for j in jaren] + \
          [f"Nieuw {jaren[-1][1:]}", "In een ring", "Verder dan 1 km", "Aangegroeid"]
    rijen = []
    for nr, w in enumerate(BR["tegel_volgorde"][:max(top_n, 20)], start=1):
        j = jaren[-1]
        n = mt("run", j, "model_nieuw", "tegel", w)
        rijen.append([nr, V.naam(w), tl(w)] + [fmt(BR["tegel"][jj][w]) for jj in jaren] +
                     [fmt(n), f"{fmt(mt('run', j, 'ring', 'tegel', w))} ({pct(mt('run', j, 'ring', 'tegel', w), n)})",
                      f"{fmt(mt('run', j, 'model_ver', 'tegel', w))} ({pct(mt('run', j, 'model_ver', 'tegel', w), n)})",
                      fmt(mt("run", j, "kiemen_aangegroeid_n", "tegel", w))])
    doc.tabel("t-toptegels", "Tegels met de hoogste score",
              f"score per zichtjaar; woningen en aangegroeide losse clusters in {jaren[-1][1:]}; volgorde naar de hoogste score over de zichtjaren, zonder overlap",
              kop, rijen, f"Ring: nieuwe modelwoningen binnen {P['ring_m']:g} m van een los cluster van de stand ervoor en niet binnen "
              f"{P['ring_kernzone_m']:g} m van een woonkern. Aangegroeid: losse clusters van de stand ervoor met nieuwe woningen in hun ring. "
              "Bron: patroonmaten.json en patroonoordeel.json.", rechts=set(range(3, len(kop))))

    # gemeenten
    doc.hoofdstuk("gemeenten", "Gemeenten")
    doc.alinea("Dezelfde maten per gemeente, naar de gemeentelijke indeling van het buurtgrid. Een woning telt bij de gemeente "
               "van zijn cel, een los cluster bij de gemeente waarin de meeste van zijn cellen liggen. De BAG-kolommen gelden "
               f"voor de startstand en staan alleen bij {eerste[1:]}.")
    for jaar in jaren:
        kop = ["Gemeente", "Score", "Nieuw", "<250 m", "250 m-1 km", ">1 km", "Ring", "In ring", "Kiemen", "Aangegroeid",
               "Los wonen", "Los werken", "Los ha"]
        if jaar == eerste:
            kop += ["BAG nieuw", "BAG >1 km"]
        sg = np.asarray(BR["gemeente"][jaar])
        rijen = []
        for g in [int(g) for g in np.argsort(-sg, kind="stable") if g > 0 and sg[g] > 0]:
            n = mt("run", jaar, "model_nieuw", "gemeente", g)
            rij = [gem_namen[g], fmt(sg[g], 1), fmt(n),
                   pct(mt("run", jaar, "model_kern", "gemeente", g), n), pct(mt("run", jaar, "model_midden", "gemeente", g), n),
                   pct(mt("run", jaar, "model_ver", "gemeente", g), n), fmt(mt("run", jaar, "ring", "gemeente", g)),
                   pct(mt("run", jaar, "ring", "gemeente", g), n), fmt(mt("run", jaar, "kiemen_n", "gemeente", g)),
                   fmt(mt("run", jaar, "kiemen_aangegroeid_n", "gemeente", g)), fmt(mt("run", jaar, "los_wonen_n", "gemeente", g)),
                   fmt(mt("run", jaar, "los_werken_n", "gemeente", g)),
                   fmt(mt("run", jaar, "los_wonen_ha", "gemeente", g) + mt("run", jaar, "los_werken_ha", "gemeente", g))]
            if jaar == eerste:
                b = mt("run", jaar, "bag_nieuw", "gemeente", g)
                rij += [fmt(b), pct(mt("run", jaar, "bag_ver", "gemeente", g), b)]
            rijen.append(rij)
        tid = "t-topgem" if jaar == jaren[-1] else f"t-gem-{jaar}"
        doc.tabel(tid, f"Gemeenten met de hoogste score, {jaar[1:]}",
                  f"woningen; aandelen van de nieuwe modelwoningen; aantallen losse clusters en hun hectares; de eerste {O['top_gemeenten']} "
                  f"van {len(rijen)} gemeenten met een score",
                  kop, rijen,
                  "Kiemen: losse clusters van de stand ervoor, bij het eerste zichtjaar die van de startstand. Los wonen en los werken: "
                  "losse clusters met modelcellen in de stand van dit zichtjaar. Bron: patroonmaten.json.", zichtbaar=O["top_gemeenten"])

    # detailkaarten
    doc.hoofdstuk("detail", "Detailkaarten")
    doc.alinea("Elke kaart toont een tegel op 25 m: de woningen van het basisjaar (lichter in een woonkern, zwart erbuiten), de "
               "BRT-woonkern, de nieuwe woningen per zichtjaar in een eigen kleur en de losse clusters omcirkeld. Een dikke cirkel is "
               "een los cluster waar in het zichtjaar erna nieuwe woningen in de ring kwamen. Rechts staan de score en de maten per zichtjaar.")
    for nr, w, pad in details:
        doc.figuur(f"f-tegel-{nr}", f"Tegel {nr}, {V.naam(w)} ({tl(w)})", "kleuren en cirkels als in de legenda rechts; schaalbalk 2 km",
                   rel(pad), " ".join(regels_eenheid(mt, B, "run", "tegel", w, jaren)) + " Bron: patroonkaarten.py.")
    if gemkaarten:
        doc.hoofdstuk("gemkaarten", "Gemeenten op de kaart")
        doc.alinea(f"Dezelfde kaarten voor de {O['top_gemeentekaarten']} gemeenten met de hoogste score"
                   + (f" en voor {opsomming(extra_gemeenten)}, op verzoek" if extra_gemeenten else "")
                   + ". De kaart volgt de gemeentegrens met een marge van 1 km; buiten de gemeente is de kaart lichter.")
        for g, pad in gemkaarten:
            doc.figuur(f"f-gem-{g}", f"Gemeente {gem_namen[g]}", "kleuren en cirkels als in de legenda rechts; schaalbalk 2 km",
                       rel(pad), " ".join(regels_eenheid(mt, B, "run", "gemeente", g, jaren)) + " Bron: patroonkaarten.py.")

    # landelijk
    doc.hoofdstuk("landelijk", "Landelijk en de BAG-referentie")

    def rij(label, sleutel, bag=None, p=False):
        w = [pct(nl("run", j, sleutel), nl("run", j, "model_nieuw")) if p else fmt(nl("run", j, sleutel)) for j in jaren]
        bv = ""
        if bag:
            bv = pct(nl("run", eerste, bag), bn) if p else fmt(nl("run", eerste, bag))
        return [label] + w + [bv]
    rijen = [rij("nieuwe woningen", "model_nieuw", "bag_nieuw"),
             rij("binnen 250 m van een woonkern", "model_kern", "bag_kern", True),
             rij("250 m tot 1 km", "model_midden", "bag_midden", True),
             rij("verder dan 1 km", "model_ver", "bag_ver", True),
             rij("in een ring", "ring", None, True),
             rij("ringwoningen", "ring"),
             rij("waarvan rond een los cluster met alleen werken", "ring_werken"),
             rij(f"waarvan rond een los cluster kleiner dan {P['kiem_klein_ha']:g} ha", "ring_klein"),
             rij("kiemen (losse clusters van de stand ervoor)", "kiemen_n"),
             rij("waarvan aangegroeid", "kiemen_aangegroeid_n"),
             rij(f"waarvan aangegroeid en kleiner dan {P['kiem_klein_ha']:g} ha", "kiemen_aangegroeid_klein_n"),
             rij("losse clusters met wonen en modelcellen", "los_wonen_n"),
             rij("losse clusters met alleen werken en modelcellen", "los_werken_n"),
             rij("hectare losse clusters met modelcellen", "los_wonen_ha"),
             rij("losse clusters alleen uit de startstand, met wonen", "los_start_wonen_n"),
             rij("losse clusters alleen uit de startstand, alleen werken", "los_start_werken_n")]
    rijen[13][1:-1] = [fmt(nl("run", j, "los_wonen_ha") + nl("run", j, "los_werken_ha")) for j in jaren]
    doc.tabel("t-nl", "Landelijke maten per zichtjaar",
              "woningen, aandelen van de nieuwe modelwoningen, aantallen clusters en hectares; de BAG-kolom is de nieuwbouw die het model in de startstand zet",
              ["Maat"] + [j[1:] for j in jaren] + [f"BAG-startstand ({eerste[1:]})"], rijen,
              "Bij de BAG bestaan geen ring en geen kiem, want de startstand heeft geen stand ervoor. Bron: patroonmaten.json.")

    # vergelijking
    if met_vgl:
        V2 = M["runs"]["vergelijk"]
        BV = B["runs"]["vergelijk"]
        jv = [j for j in jaren if j in V2["jaren"]]
        doc.hoofdstuk("vgl", f"Vergelijking met {namen['vergelijk']}")
        kop = ["Maat"] + [f"{j[1:]} {namen['run']}" for j in jaren] + [f"{j[1:]} {namen['vergelijk']}" for j in jv]
        rijen = [[label] + [fmt(nl("run", j, s)) for j in jaren] + [fmt(nl("vergelijk", j, s)) for j in jv]
                 for label, s in (("nieuwe woningen", "model_nieuw"), ("verder dan 1 km", "model_ver"), ("ringwoningen", "ring"),
                                  ("kiemen aangegroeid", "kiemen_aangegroeid_n"), ("losse clusters met wonen", "los_wonen_n"))]
        doc.tabel("t-vgl-nl", "Landelijke maten van beide runs", "woningen en aantallen", kop, rijen, "Bron: patroonmaten.json.")
        kop = ["Gemeente"] + [f"{j[1:]} {namen['run']}" for j in jv] + [f"{j[1:]} {namen['vergelijk']}" for j in jv] + \
              [f"Ring {jv[-1][1:]} {namen['run']}", f"Ring {jv[-1][1:]} {namen['vergelijk']}"]
        keus = []
        for j in jv:
            for g, _ in stijgers(B, j, O["top_gemeenten"]):
                if g not in keus:
                    keus.append(g)
        keus.sort(key=lambda g: -max(BR["gemeente"][j][g] - BV["gemeente"][j][g] for j in jv))
        rijen = [[gem_namen[g]] + [fmt(BR["gemeente"][j][g]) for j in jv] + [fmt(BV["gemeente"][j][g]) for j in jv] +
                 [fmt(mt("run", jv[-1], "ring", "gemeente", g)), fmt(mt("vergelijk", jv[-1], "ring", "gemeente", g))]
                 for g in keus[:O["top_gemeenten"]]]
        doc.tabel("t-vgl-gem", f"Gemeenten met de grootste stijging van de score tegen {namen['vergelijk']}",
                  "score per zichtjaar in beide runs en de ringwoningen in het laatste zichtjaar; volgorde naar de grootste stijging in een zichtjaar",
                  kop, rijen, "Bron: patroonoordeel.json en patroonmaten.json.")
        kop = ["", "Tegel", "Gemeenten"] + [f"{j[1:]} {namen['run']}" for j in jaren] + [f"{j[1:]} {namen['vergelijk']}" for j in jv]
        rijen = [[nr, V.naam(w), tl(w)] + [fmt(BR["tegel"][j][w]) for j in jaren] + [fmt(BV["tegel"][j][w]) for j in jv]
                 for nr, w in enumerate(top, start=1)]
        doc.tabel("t-vgl-tegels", "Score van de genummerde tegels in beide runs", "score per zichtjaar", kop, rijen,
                  "Bron: patroonoordeel.json.", rechts=set(range(3, len(kop))))
        doc.figuur("f-overzicht-vgl", f"Score per vak en zichtjaar, {namen['vergelijk']}",
                   "kleur is de score per vak; omlijnd dezelfde tegels als bij de run",
                   rel(os.path.join(kaartmap, "overzicht_vergelijk.png")), "Bron: patroonkaarten.py.")
        for nr, w, pad in verschil:
            doc.figuur(f"f-verschil-{nr}", f"Verschil in tegel {nr}, {V.naam(w)} ({tl(w)})",
                       f"rood alleen in {namen['run']}, blauw alleen in {namen['vergelijk']}, paars in beide; nieuwe woningen over alle zichtjaren",
                       rel(pad), f"De cirkels zijn losse clusters van {namen['run']} met nieuwe woningen in hun ring. Bron: patroonkaarten.py.")

    # leeswijzer
    doc.hoofdstuk("maten", "Wat de maten zijn en hoe je ze leest")
    doc.lijst([
        "Nieuwe woningen: per cel de toename van het aantal woningen (alle woonsubsectoren) tegen de stand ervoor, alleen waar het "
        "aantal groeit; sloop telt niet. Bij het eerste zichtjaar gaat de BAG-nieuwbouw in de startstand eraf: de toename op een "
        "woncel van SubSector_rel met een jaar van verandering van voor het eerste zichtjaar.",
        f"Afstand tot een woonkern: tussen celmiddens tot de dichtstbijzijnde cel van de BRT-woonkern (IsWoonkern), in drie banden: tot "
        f"{P['kern_nabij_m']:g} m, tot {P['kern_ver_m']:g} m en verder.",
        f"Los cluster: aaneengesloten cellen wonen of werken in SubSector_rel (8-buren, cumulatief sinds het basisjaar) waarvan geen cel "
        f"binnen {P['kern_nabij_m']:g} m van een woonkern ligt; met wonen als er een woncel in zit, anders alleen werken; met modelcellen "
        "als een cel een jaar van verandering vanaf het eerste zichtjaar heeft, anders alleen uit de startstand.",
        f"Kiem: een los cluster van de stand van het zichtjaar ervoor, en bij het eerste zichtjaar een los cluster van alleen "
        f"startstandcellen. Ringwoning: een nieuwe modelwoning binnen {P['ring_m']:g} m van een kiem en niet binnen "
        f"{P['ring_kernzone_m']:g} m van een woonkern. Een kiem is aangegroeid bij minstens {P['aangegroeid_min_woningen']:g} "
        "nieuwe woning in zijn ring.",
        f"Score: ringwoningen gedeeld door {O['ijkmaat_ringwoningen']:g}, plus woningen verder dan 1 km gedeeld door "
        f"{O['ijkmaat_ver_woningen']:g}, plus aangegroeide kiemen gedeeld door {O['ijkmaat_aangegroeide_kiemen']:g}; opvallend vanaf "
        f"{O['opvallend_score']:g}. De ijkmaten staan in patroondrempels.json en zijn absoluut, zodat twee runs dezelfde schaal "
        "hebben; een grote gemeente of een tegel met veel nieuwbouw scoort daardoor eerder hoog dan een kleine.",
        "Lezen: een hoge score door ringwoningen met veel aangegroeide kiemen is het patroon van ringen en banden rond erven en "
        "kleine clusters; een hoge score door ringwoningen rond een paar grote kiemen is een uitleg die los van de kern begon en "
        "daarna doorgroeide; een hoge score door verre woningen zonder ringen is bouw ver van elke kern, bijvoorbeeld op een hard "
        "plan. De detailkaart zegt welke van de drie het is.",
    ])
    doc.hoofdstuk("bronnen", "Bronnen en werkwijze")
    prov = M["provenance"]
    items = []
    for rn in M["runs"]:
        Rr = M["runs"][rn]
        x = Rr.get("xml", {})
        items.append(f"{namen[rn]}: {Rr['pad']}, casus {Rr['casus']}, zichtjaren {', '.join(j[1:] for j in Rr['jaren'])}, "
                     f"SS-nummer {Rr.get('ss_nummer')}, woonkern {os.path.basename(Rr['woonkern'])}, basisjaar "
                     f"{', '.join(os.path.basename(p) for p in Rr['basisjaar'])}; GeoDMS {x.get('geodms', 'onbekend')}, sessie "
                     f"{x.get('sessiestart', 'onbekend')}, runbestand {x.get('runbestand', 'onbekend')}.")
    items.append(f"Gemeenten: {prov['buurt']} met {prov['buurt_namen']}.")
    geh = tijden.get("geheugen") or tijden.get("geheugen_na_meten") or {}
    items.append(f"Rekentijd: meting {tijden.get('meten_s', 'niet in deze aanroep')} s, kaarten {tijden.get('kaarten_s')} s; "
                 f"piek werkgeheugen {geh.get('werkgeheugen_piek_gb', '?')} GB, piek privegeheugen {geh.get('privegeheugen_piek_gb', '?')} GB.")
    items.append("Gemeten zijn alle aantallen en aandelen in dit rapport; de score en de drempel voor opvallend zijn een oordeel met "
                 "de ijkmaten uit patroondrempels.json. Niet nagekeken: of een los cluster een boerenerf, een bedrijf of een nieuwe "
                 "wijk is, en of verre bouw op een hard plan ligt; dat laat de detailkaart zien.")
    doc.lijst(items)
    ijk = R.get("ijking", {}).get("indexen", [])
    doc.tabel("t-ijking", "IJking van de indexen van SubSector_rel",
              f"per index het aandeel cellen met woningen en met banen in de stand van {R.get('ijking', {}).get('zichtjaar', '')[1:]}",
              ["Index", "Cellen", "Met woningen", "Met banen", "Telt als"],
              [[t["index"], fmt(t["cellen"]), f"{t['aandeel_met_woningen']:.3f}", f"{t['aandeel_met_banen']:.3f}", t["categorie"]] for t in ijk],
              f"Een index telt als wonen of werken vanaf een aandeel van {P['ijking_min_aandeel']:g}. Bron: de standkaarten van de run.")

    titel = f"Patroonkaarten {namen['run']}"
    lede = (f"Waar de run {namen['run']} ({R['casus']}, {M['provenance']['suffix']}) zijn nieuwe woningen legt in "
            f"{', '.join(j[1:] for j in jaren)}, en waar dat patroon afwijkt: ringen rond losse clusters en bouw ver van een woonkern"
            + (f", naast {namen['vergelijk']}." if met_vgl else "."))
    meta = (f"Gemaakt {datetime.now(timezone.utc).isoformat(timespec='seconds')} met patroonkaarten.py; meting van {prov['gemaakt']}; "
            f"run {R['pad']}" + (f"; vergelijking {M['runs']['vergelijk']['pad']}" if met_vgl else ""))
    with open(os.path.join(out, "rapport.md"), "w", encoding="utf8") as f:
        f.write(doc.markdown(titel, lede, meta))
    with open(os.path.join(out, "rapport.html"), "w", encoding="utf8") as f:
        f.write(doc.html(titel, lede, meta))
    meld(f"rapport {os.path.join(out, 'rapport.html')}")


# ------------------------------------------------------------------ hoofdloop

def main(argv=None):
    ap = argparse.ArgumentParser(description="Ruimtelijke patronen van de woningbouw in een RSopen-run, met kaarten.")
    ap.add_argument("--run", help="LocalData van de run (map met Allocatie en BaseData)")
    ap.add_argument("--casus", default="WLO_hoog_BAU")
    ap.add_argument("--zichtjaren", nargs="*", default=None, help="bijvoorbeeld Y2040 Y2050 Y2060; leeg is alle StandY-mappen")
    ap.add_argument("--suffix", default=None, help="studiegebied in de bestandsnamen (Nederland, Noord_Holland); leeg is uit Footprint_*.tif")
    ap.add_argument("--naam", default=None, help="korte naam van de run in rapport en kaarten")
    ap.add_argument("--vergelijk", default=None, help="LocalData van een tweede run om mee te vergelijken")
    ap.add_argument("--casus-vergelijk", default=None, help="casus van de tweede run; leeg is dezelfde")
    ap.add_argument("--naam-vergelijk", default=None)
    ap.add_argument("--buurt", default=STANDAARD_BUURT, help="buurtgrid (buurtnummer per cel), landelijk of van het studiegebied")
    ap.add_argument("--buurt-namen", default=None, help="csv met id, name, Gemeente_name; leeg is Buurt_namen_<gebied>.csv naast --buurt")
    ap.add_argument("--drempels", default=os.path.join(HIER, "patroondrempels.json"))
    ap.add_argument("--top", type=int, default=None, help="aantal tegels met een detailkaart; leeg is top_tegels uit de drempels")
    ap.add_argument("--gemeenten", nargs="*", default=[], help="gemeenten die hoe dan ook een kaart en een regel in de kern krijgen, zoals Noordoostpolder Dronten")
    ap.add_argument("--out", required=True)
    ap.add_argument("--herbeoordeel", action="store_true", help="alleen oordeel, rapport en kaarten opnieuw, uit de meting in --out")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    with open(args.drempels, encoding="utf8") as f:
        drempels = json.load(f)
    O = {k: v for k, v in drempels["oordeel"].items() if not k.startswith("_")}
    maten_pad = os.path.join(args.out, "patroonmaten.json")
    kaart_pad = os.path.join(args.out, "kaartdata.npz")
    tijden = {}

    if args.herbeoordeel:
        with open(maten_pad, encoding="utf8") as f:
            M = json.load(f)
        t0 = time.perf_counter()
        kd = laad_kaartdata(kaart_pad)
        tijden["kaartdata_laden_s"] = round(time.perf_counter() - t0, 1)
        tijden["meten_s"] = M.get("rekentijd", {}).get("meten_s")
        gem = kd["gem"]
    else:
        if not args.run:
            ap.error("--run is nodig, behalve met --herbeoordeel")
        P = {k: v for k, v in drempels["meten"].items() if not k.startswith("_")}
        if P["tegel_km"] % P["tegel_stap_km"]:
            raise ValueError("tegel_km moet een veelvoud van tegel_stap_km zijn")
        suffix = args.suffix or vind_suffix(args.run)
        jaren = args.zichtjaren or vind_zichtjaren(args.run, args.casus)
        meld(f"run {args.run}, casus {args.casus}, studiegebied {suffix}, zichtjaren {' '.join(jaren)}")
        sm = standmap(args.run, args.casus, jaren[0])
        ss_eerste = stand_pad(sm, "", "SubSector_rel", suffix, ss_nummer(sm, suffix))
        with tifffile.TiffFile(ss_eerste) as tf:
            vorm = tf.pages[0].shape
            geo = geo_van(ss_eerste, tf.pages[0])
        grid = Grid(vorm, geo)
        meld(f"raster: {grid}")
        buurt_namen = args.buurt_namen or os.path.join(os.path.dirname(args.buurt), os.path.basename(args.buurt)
                                                       .replace("Buurt_", "Buurt_namen_").replace(".tif", ".csv"))
        gem, gem_namen = lees_gemeenten(args.buurt, buurt_namen, grid)
        vakken = Tegels(grid, P["tegel_stap_km"])
        land, _, per_vak = tegel_gemeenten(gem, vakken, len(gem_namen), grid.cel ** 2 / 1e4)
        meld(f"gemeenten: {len(gem_namen) - 1}; vakken van {P['tegel_stap_km']} km: {vakken.nx} x {vakken.ny}")
        M = {"provenance": {"tool": "patroonkaarten.py", "gemaakt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            "suffix": suffix, "grid": grid.als_dict(), "buurt": os.path.abspath(args.buurt),
                            "buurt_namen": os.path.abspath(buurt_namen), "drempels": os.path.abspath(args.drempels)},
             "meten": P,
             "eenheden": {"gemeente": gem_namen, "tegel_km": P["tegel_km"],
                          "vak": {"km": vakken.km, "nx": vakken.nx, "ny": vakken.ny,
                                  "namen": [vakken.naam(t) for t in range(vakken.n)], "land_ha": land,
                                  "gemeenten_ha": [{gem_namen[g]: round(ha, 1) for g, ha in d.items()} for d in per_vak]}},
             "runs": {}}
        kd = {"gem": gem}
        for rn, pad, casus, naam in (("run", args.run, args.casus, args.naam or "run"),
                                     ("vergelijk", args.vergelijk, args.casus_vergelijk or args.casus, args.naam_vergelijk or "vergelijking")):
            if not pad:
                continue
            t0 = time.perf_counter()
            if rn == "vergelijk":
                sfx = args.suffix or vind_suffix(pad)
                if sfx != suffix:
                    raise ValueError(f"de tweede run heeft studiegebied {sfx}, de eerste {suffix}")
            jr = jaren if rn == "run" else [j for j in jaren if os.path.isdir(standmap(pad, casus, j))]
            uit, kaart = meet_run(pad, casus, jr, suffix, grid, gem, vakken, len(gem_namen), P, naam)
            M["runs"][rn] = uit
            for k, v in kaart.items():
                kd[f"{rn}/{k}"] = v
            tijden[f"meten_{rn}_s"] = round(time.perf_counter() - t0, 1)
        tijden["meten_s"] = round(sum(v for k, v in tijden.items() if k.startswith("meten_")), 1)
        t0 = time.perf_counter()
        bewaar_kaartdata(kaart_pad, kd)
        tijden["kaartdata_bewaren_s"] = round(time.perf_counter() - t0, 1)
        tijden["geheugen_na_meten"] = piekgeheugen_gb()
        M["rekentijd"] = dict(tijden)
        with open(maten_pad, "w", encoding="utf8") as f:
            json.dump(naar_json(M), f)
        with open(maten_pad, encoding="utf8") as f:
            M = json.load(f)
        meld(f"meting {maten_pad} en {kaart_pad}")

    grid, vakken, V = vensters_uit(M)
    B = beoordeel(M, O, V)
    top_n = args.top if args.top is not None else O["top_tegels"]
    t0 = time.perf_counter()
    maak_rapport(M, B, kd, gem, V, grid.W, grid.cel, args.out, top_n, tijden, args.gemeenten)
    tijden["oordeel_en_rapport_s"] = round(time.perf_counter() - t0, 1)
    tijden["geheugen"] = piekgeheugen_gb()
    tijden["totaal_s"] = round(time.perf_counter() - T_START, 1)
    B["rekentijd"] = tijden
    B["tegels"] = {"namen": [V.naam(w) for w in range(V.n)], "km": V.km}
    B["toptegels"] = [{"nr": nr, "tegel": V.naam(w), "gemeenten": tegel_gemeenten_namen(M, V, w)}
                      for nr, w in enumerate(B["runs"]["run"]["tegel_volgorde"][:top_n], start=1)]
    with open(os.path.join(args.out, "patroonoordeel.json"), "w", encoding="utf8") as f:
        json.dump(naar_json(B), f, indent=1)
    meld(f"klaar; rekentijd {tijden['totaal_s']} s, geheugen {tijden['geheugen']}")


if __name__ == "__main__":
    main()
