"""Legt twee runs van RSopen naast elkaar en zegt of, hoeveel en waarom ze verschillen.

Gebruik:
    python Toetsrapport.py --a <run van> --b <run naar> --uit <rapport.md>
        [--naam-a <sha>] [--naam-b <sha>] [--casus WLO_hoog_BAU ...]
        [--repo <pad> --ref-a <commit> --ref-b <commit>] [--samenvatting <tekst>]
        [--kopie-b <momentopname> --patch-b <patch> ...] [--patch-a <patch> ...]
        [--html <pagina>] [--log <toetslog.csv>]

Een run is een LocalData-map, of de bewaarde uitvoer van een baseline met dezelfde indeling:
Allocatie/<casus>/Stand<jaar>/... met de standtifs, BaseData/StandBasisjaar met de basisjaarstand,
Diagnose/<casus>_<jaar>_<naam>.txt met de controlewaarden, run.tsv (Runinfo.py) met de rekentijd en het
piekgeheugen per stap, en toets.tsv (Toets.ps1) met de GeoDMS-versie en het profiel van de run.

Het rapport gaat van A (van) naar B (naar) en beantwoordt drie vragen, in deze volgorde. Hoe anders:
per casus de koptabel met de maten die ertoe doen en per sector het patroon op de kaart (cellen erbij,
eraf, anders). Waarom: een lezing in een paar zinnen, en de instellingen die verschillen. Verder
kijken: de commits ertussen met wat elk raakt, per tif de celverschillen, alle controlewaarden die
verschillen, de bestanden per commit en de technische gegevens van beide runs. Of het anders is staat
in de titel en in het log, niet nog eens in het rapport.

Een patch die op beide kanten lag (bijvoorbeeld een fix die de branch nog niet heeft maar die nodig is
om een provincie te draaien) valt tegen elkaar weg en staat alleen onder Verder kijken.
"""

import argparse
import csv
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TOL = 1e-6           # relatieve tolerantie waarbinnen twee floats als gelijk tellen
HA_PER_CEL = 0.0625  # een cel van 25 meter

# De koptabel: de controlewaarden uit Diagnose die ertoe doen, in deze volgorde; alleen de rijen die in
# de run voorkomen worden getoond. De absolute normen van de acceptatie staan in batch/ToetsOplevering.ps1.
KOPTABEL = [
    "stand_woningen", "stand_banen",
    "claimreal_NL_woningen", "claimreal_NL_banen", "claimreal_Waterberging",
    "verstedelijking_ha", "inbreiding_fractie",
    "nieuwenatuur_ha", "verdwenennatuur_ha", "waterbergingveen_ha",
    "sloop_nieuwenatuur", "sloop_waterberging",
    "woningwaarde_nieuwbouw", "carbon_flow",
    "plancap_opgelegde_woningen",
]

# Leesbare namen van de controlewaarden; wat hier niet in staat krijgt zijn naam met spaties.
NAMEN = {
    "stand_woningen": "woningen in de stand", "stand_banen": "banen in de stand",
    "claimreal_NL_woningen": "claimrealisatie wonen", "claimreal_NL_banen": "claimrealisatie werken",
    "claimreal_NVM_woningen": "claimrealisatie wonen per NVM-regio", "claimreal_Provincie_banen": "claimrealisatie werken per provincie",
    "claimreal_Waterberging": "claimrealisatie waterberging", "claimreal_landbouw": "claimrealisatie landbouw",
    "claimtoets": "claimtoets wonen per gemeente", "claimtoets_werken": "claimtoets werken per NVM-regio",
    "verstedelijking_ha": "nieuw stedelijk areaal (ha)", "verstedelijking_vruchtbaar_ha": "verstedelijking op vruchtbare grond (ha)",
    "inbreiding_fractie": "aandeel inbreiding",
    "nieuwenatuur_ha": "nieuwe natuur (ha)", "nieuwenatuur_vruchtbaar_ha": "nieuwe natuur op vruchtbare grond (ha)",
    "verdwenennatuur_ha": "verdwenen natuur (ha)",
    "waterbergingveen_ha": "waterberging op veen (ha)", "waterbergingveen_vruchtbaar_ha": "waterberging op vruchtbaar veen (ha)",
    "waterberging_perregio": "waterberging per regio", "waterberging_regios_met_tekort": "waterbergingsregio's met een tekort",
    "sloop_nieuwenatuur": "sloopkosten door nieuwe natuur (euro)", "sloop_waterberging": "sloopkosten door waterberging op veen (euro)",
    "sloop_zonder_masker": "sloop buiten het sloopmasker", "sloop_zondermasker_veen": "sloop buiten het masker, veen",
    "sloop_zondermasker_buiten": "sloop buiten het masker, overig",
    "sloop_opslot_zonder_sloopbedoeling": "sloop op slot zonder sloopbedoeling",
    "uitkoop_nieuwenatuur": "uitkoopkosten door nieuwe natuur (euro)", "uitkoop_waterberging": "uitkoopkosten door waterberging op veen (euro)",
    "exogeen_cellen": "exogeen opgelegde cellen", "nietbouwen_landschap_cellen": "niet bouwen in het landschap (cellen)",
    "woningwaarde_nieuwbouw": "woningwaarde nieuwbouw", "groenwaarde_woningen": "groenwaarde van woningen",
    "groenwaarde_lek_eur": "groenwaarde, lek (euro)", "groenopslag_min": "groenopslag, minimum", "groenopslag_max": "groenopslag, maximum",
    "carbon_flow": "CO2-stroom tegen het basisjaar", "carbon_ongedekt": "CO2 ongedekt, cumulatief",
    "koolstof_vastlegging_keten_min": "koolstofvastlegging keten, minimum", "koolstof_afboeking_keten_max": "koolstofafboeking keten, maximum",
    "koolstof_keten_null_cellen": "koolstofketen, lege cellen",
    "somers_mediaan": "SOMERS-kosten, mediaan", "ijburg2_woningen_groei": "IJburg 2, groei woningen",
    "veenbouwstenen_realisatie": "veenbouwstenen, realisatie", "veenbouwstenen_perbouwsteen": "veenbouwstenen per bouwsteen",
    "veenbouwstenen_perdeelgebied": "veenbouwstenen per deelgebied", "veenbouwstenen_terugkoppeling": "veenbouwstenen, terugkoppeling",
    "veenbouwstenen_waterkaart": "veenbouwstenen, waterkaart",
    "plancap_opgelegde_woningen": "opgelegde planwoningen",
    "basisjaar_woningen": "woningen basisjaar", "basisjaar_banen": "banen basisjaar", "hogegronden_ha": "hoge gronden (ha)",
    "bouwperiode_term": "bouwperiodeterm", "verwerving_nietwoon_mld": "verwervingskosten niet-woon (mld euro)",
    "verblijfsrecreatie_stand_tov_trend": "verblijfsrecreatie, stand tegen trend",
}

# De kaartlagen waarop het patroon per sector wordt gemeten: de som van de subsectortifs per cel.
SECTOREN = {
    "wonen":    ("Wonen",    "woningen"),
    "werken":   ("Werken",   "banen"),
    "landbouw": ("Landbouw", "ha"),       # per gewas een tif met hectare per cel
}
# Klassenkaarten: daar telt het aantal cellen met een andere klasse.
KLASSENKAARTEN = {
    "landgebruikstype": "Landgebruik/Type_",
    "subsector": "SubSector_rel_",
}


# ---------------------------------------------------------------- hulpfuncties

def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True, encoding="utf8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def nl(getal):
    """Nederlandse schrijfwijze: punt als duizendtal, komma als decimaal."""
    return getal.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def enkel(w):
    """Een lijst met een regel (bijvoorbeeld de claimrealisatie van de ene waterbergingsregio in een
    provincie) telt als die ene waarde."""
    if isinstance(w, dict) and len(w) == 1:
        return next(iter(w.values()))
    return w


def toon(w):
    w = enkel(w)
    if w is None:
        return "n.v.t."
    if isinstance(w, float):
        return nl(format(w, ",.4f").rstrip("0").rstrip(".")) if abs(w) < 1e6 else nl(format(w, ",.0f"))
    if isinstance(w, dict):
        return f"lijst van {len(w)}"
    return str(w)[:40]


def toon_verschil(a, b, decimalen=None):
    """Het verschil B min A met teken, en bij grote getallen het percentage."""
    a, b = enkel(a), enkel(b)
    if not (isinstance(a, float) and isinstance(b, float)):
        return ""
    d = b - a
    if abs(d) <= TOL * max(abs(a), abs(b), 1.0):
        return "gelijk"
    teken = "+" if d > 0 else ""
    if decimalen is not None:
        return f"{teken}{nl(format(d, f',.{decimalen}f'))}"
    if abs(a) >= 1:
        p = 100.0 * d / abs(a)
        p_tekst = nl(format(p, ".2g")) if abs(p) < 1 else nl(format(p, ".1f"))
        return f"{teken}{toon(d)} ({teken}{p_tekst} procent)"
    return f"{teken}{nl(format(d, '.6f').rstrip('0').rstrip('.'))}"


def pct(deel, geheel):
    return 100.0 * deel / geheel if geheel else 0.0


def hash_van(pad):
    h = hashlib.sha256()
    with open(pad, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def tabel(kop, rijen):
    if not rijen:
        return []
    breedtes = [max(len(str(r[i])) for r in [kop, *rijen]) for i in range(len(kop))]
    uit = ["| " + " | ".join(str(k).ljust(b) for k, b in zip(kop, breedtes)) + " |",
           "|" + "|".join("-" * (b + 2) for b in breedtes) + "|"]
    for r in rijen:
        uit.append("| " + " | ".join(str(c).ljust(b) for c, b in zip(r, breedtes)) + " |")
    return uit


def naam_controle(stem):
    """Y2040_claimreal_NL_banen -> claimrealisatie werken (2040); Basisjaar_hogegronden_ha -> hoge gronden (ha), basisjaar."""
    m = re.match(r"(Y\d{4}|Basisjaar)_(.+)", stem)
    jaar, kern = (m.group(1), m.group(2)) if m else ("", stem)
    naam = NAMEN.get(kern) or kern.replace("_", " ")
    if jaar.startswith("Y"):
        return f"{naam} ({jaar[1:]})"
    if jaar:
        return f"{naam}, basisjaar"
    return naam


def kort_casus(casus):
    """WLO_hoog_NbSGenuanceerd -> NbSGenuanceerd: het scenario is voor alle casussen gelijk."""
    return casus.split("_")[-1]


def kort_tif(rel):
    """Allocatie/<casus>/StandY2040/Wonen/eengezins_SocialeHuur_Noord_Holland_SS-10.tif -> NbSGenuanceerd 2040 Wonen/eengezins_SocialeHuur"""
    delen = rel.split("/")
    stand = next((d for d in delen if d.startswith("StandY")), None)
    if stand:
        staart = "/".join(delen[delen.index(stand) + 1:])
        kop = f"{kort_casus(delen[1])} {stand.replace('StandY', '')}"
    else:
        staart = rel.replace("BaseData/StandBasisjaar/", "")
        kop = "basisjaar"
    staart = re.sub(r"_(Nederland|[A-Z][a-z]+(?:_[A-Z][a-z]+)*)_SS-\d+\.tif$", "", staart)
    staart = re.sub(r"_(Nederland|[A-Z][a-z]+(?:_[A-Z][a-z]+)*)\.tif$", "", staart)
    return f"{kop} {staart}"


# ---------------------------------------------------------------- de standtifs

def tifs_onder(run, casussen):
    uit = {}
    mappen = [Path("Allocatie") / c for c in casussen] + [Path("BaseData") / "StandBasisjaar"]
    for sub in mappen:
        wortel = Path(run) / sub
        if wortel.is_dir():
            for p in wortel.rglob("*.tif"):
                uit[p.relative_to(run).as_posix()] = p
    return uit


def vergelijk_tifs(run_a, run_b, casussen):
    ta, tb = tifs_onder(run_a, casussen), tifs_onder(run_b, casussen)
    gelijk, anders = [], []
    for rel in sorted(set(ta) & set(tb)):
        (gelijk if hash_van(ta[rel]) == hash_van(tb[rel]) else anders).append(rel)
    return gelijk, anders, sorted(set(ta) - set(tb)), sorted(set(tb) - set(ta)), ta, tb


def lees_raster(pad):
    import tifffile
    return tifffile.imread(str(pad)).astype("float64")


def celverschil(pad_a, pad_b):
    """Per tif die verschilt het aantal afwijkende cellen, de sommen en de grootste celafwijking; None
    als numpy of tifffile ontbreekt."""
    try:
        import numpy as np
        a, b = lees_raster(pad_a), lees_raster(pad_b)
    except ImportError:
        return None
    if a.shape != b.shape:
        return {"vorm": f"{a.shape} tegen {b.shape}"}
    # Nodata is NaN in de float-tifs, en NaN is nooit gelijk aan NaN: zonder deze stap telt elke cel
    # buiten het studiegebied als verschil.
    leeg_a, leeg_b = np.isnan(a), np.isnan(b)
    gelijk = (a == b) | (leeg_a & leeg_b)
    anders = int(np.count_nonzero(~gelijk))
    d = np.where(~gelijk, np.nan_to_num(b) - np.nan_to_num(a), 0.0)
    return {"cellen": anders, "pct": pct(anders, a.size), "som_a": float(np.nansum(a)), "som_b": float(np.nansum(b)),
            "max_abs": float(np.abs(d).max()) if anders else 0.0}


def patroon_per_sector(ta, tb, anders, casus):
    """Per zichtjaar en sector de som van de subsectortifs per cel, en dan: cellen erbij in B, weg in B,
    anders in aantal. Voor de klassenkaarten het aantal cellen met een andere klasse."""
    try:
        import numpy as np
    except ImportError:
        return []
    uit = []
    jaren = sorted({r.split("/")[2] for r in ta if r.startswith(f"Allocatie/{casus}/Stand")})
    for stand in jaren:
        jaar = stand.replace("StandY", "")
        for sleutel, (map_, eenheid) in SECTOREN.items():
            # Alleen de subsectortifs: de map Wonen draagt ook Footprint (woonoppervlak), en die hoort niet in de som.
            rels = [r for r in ta if r.startswith(f"Allocatie/{casus}/{stand}/{map_}/") and r in tb and not Path(r).name.startswith("Footprint")]
            if not rels:
                continue
            rij = {"sector": sleutel, "jaar": jaar, "eenheid": eenheid}
            if not any(r in anders for r in rels):
                rij["gelijk"] = True
                uit.append(rij)
                continue
            som_a = som_b = None
            for r in rels:
                a, b = np.nan_to_num(lees_raster(ta[r])), np.nan_to_num(lees_raster(tb[r]))
                som_a = a if som_a is None else som_a + a
                som_b = b if som_b is None else som_b + b
            bezet_a, bezet_b = som_a > 0, som_b > 0
            rij.update({
                "gelijk": False,
                "erbij": int(np.count_nonzero(bezet_b & ~bezet_a)),
                "weg": int(np.count_nonzero(bezet_a & ~bezet_b)),
                "anders": int(np.count_nonzero(bezet_a & bezet_b & (som_a != som_b))),
                "bezet_a": int(np.count_nonzero(bezet_a)),
                "totaal_a": float(som_a.sum()), "totaal_b": float(som_b.sum()),
            })
            uit.append(rij)
        for sleutel, voorvoegsel in KLASSENKAARTEN.items():
            rels = [r for r in ta if r.startswith(f"Allocatie/{casus}/{stand}/") and r[len(f"Allocatie/{casus}/{stand}/"):].startswith(voorvoegsel) and r in tb]
            if not rels:
                continue
            rij = {"sector": sleutel, "jaar": jaar, "eenheid": "", "klassen": True}
            if not any(r in anders for r in rels):
                rij["gelijk"] = True
            else:
                a, b = lees_raster(ta[rels[0]]), lees_raster(tb[rels[0]])
                leeg = np.isnan(a) & np.isnan(b)
                verschil = ~((a == b) | leeg)
                rij.update({"gelijk": False, "anders": int(np.count_nonzero(verschil)), "bezet_a": int(np.count_nonzero(~np.isnan(a)))})
            uit.append(rij)
    return uit


# ---------------------------------------------------------------- de controlewaarden

def lees_waarde(tekst):
    t = (tekst or "").strip()
    if t == "" or t == "null" or t.startswith("niet_van_toepassing"):
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        pass
    if "|" in t or ";" in t:
        d = {}
        for rij in t.split("|"):
            delen = rij.split(";")
            if len(delen) >= 2:
                try:
                    d[delen[0]] = float(delen[1].replace(",", "."))
                except ValueError:
                    d[delen[0]] = delen[1]
        return d
    return t


def gelijk_genoeg(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= TOL * max(abs(a), abs(b), 1.0)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(gelijk_genoeg(a[k], b[k]) for k in a)
    return a == b


def vergelijk_diagnose(run_a, run_b, casus):
    da, db = Path(run_a) / "Diagnose", Path(run_b) / "Diagnose"
    namen_a = {p.name for p in da.glob(f"{casus}_*.txt")} if da.is_dir() else set()
    namen_b = {p.name for p in db.glob(f"{casus}_*.txt")} if db.is_dir() else set()
    rijen = []
    for naam in sorted(namen_a & namen_b):
        wa = lees_waarde((da / naam).read_text(encoding="utf8", errors="replace"))
        wb = lees_waarde((db / naam).read_text(encoding="utf8", errors="replace"))
        rijen.append({"casus": casus, "naam": naam[len(casus) + 1:-4], "a": wa, "b": wb, "gelijk": gelijk_genoeg(wa, wb)})
    strip = len(casus) + 1
    return rijen, sorted(n[strip:-4] for n in namen_a - namen_b), sorted(n[strip:-4] for n in namen_b - namen_a)


# ---------------------------------------------------------------- run.tsv en toets.tsv: tijd, geheugen, omgeving

def lees_tsv(pad, sleutel):
    if not Path(pad).is_file():
        return {}
    with open(pad, newline="", encoding="utf8-sig" if False else "utf8") as f:
        tekst = f.read().lstrip("﻿")
    return {r[sleutel]: r for r in csv.DictReader(tekst.splitlines(), delimiter="\t") if r.get(sleutel)}


def runmaten(run):
    info = lees_tsv(Path(run) / "run.tsv", "stap")
    if not info:
        return None
    alloc = [r for s, r in info.items() if s.startswith("allocatie-")]
    totaal = sum(float(r["seconden"] or 0) for r in info.values())
    t_alloc = sum(float(r["seconden"] or 0) for r in alloc)
    piek = max((int(r["piek_MB"]) for r in alloc if r.get("piek_MB")), default=None)
    return {"alloc_min": t_alloc / 60.0, "totaal_min": totaal / 60.0, "piek_gb": piek / 1024.0 if piek else None}


def toetsinfo(run):
    """De sleutel-waardeparen uit toets.tsv: geodms, testprofiel, baseline, varianten, zichtjaren, patches."""
    return {k: r["waarde"] for k, r in lees_tsv(Path(run) / "toets.tsv", "sleutel").items()}


# ---------------------------------------------------------------- patches

def patch_inhoud(paden):
    return {Path(p).name: Path(p).read_bytes() for p in (paden or []) if Path(p).is_file()}


# ---------------------------------------------------------------- de samenvatting van de commits

ISSUE = re.compile(r"(?:[\w.-]+/[\w.-]+)?#\d+")


def samenvatting_auto(commits):
    """Zonder meegegeven tekst: de commits gegroepeerd op issuenummer, met het eerste onderwerp als voorbeeld."""
    groepen = {}
    for c in commits:
        tags = ISSUE.findall(c["onderwerp"])
        groepen.setdefault(tags[0] if tags else "", []).append(c)
    delen = []
    for sleutel, lijst in groepen.items():
        eerste = ISSUE.sub("", lijst[0]["onderwerp"]).strip(" :")
        if len(eerste) > 90:
            eerste = eerste[:90].rsplit(" ", 1)[0] + "..."
        if sleutel:
            delen.append(f"{sleutel} ({len(lijst)}): {eerste}" if len(lijst) > 1 else f"{sleutel}: {eerste}")
        else:
            delen.append(f"zonder issue ({len(lijst)}): {eerste}" if len(lijst) > 1 else eerste)
    return "; ".join(delen) + "."


def samenvatting_kort(tekst):
    """De eerste regel of zin, voor de logtabel."""
    eerste = tekst.strip().splitlines()[0] if tekst.strip() else ""
    return eerste if len(eerste) <= 160 else eerste[:157] + "..."


# ---------------------------------------------------------------- de interpretatie

def interpretatie(uitkomst, patronen, maten_a, maten_b, info_a, info_b, commits, verschillen, diag_anders, patch_gelijk, patch_alleen_b):
    """Een lezing in een paar zinnen: wat verschuift, welke commit of instelling dat kan verklaren, en
    wat neveneffect is. Zonder kennis van de bedoeling van de wijziging; het rapport zegt waar te zoeken.
    uitkomst is identiek, stand_gelijk, anders of geen."""
    from VergelijkCommits import kort_bestand
    z = []
    rekenwijze = [c for c in commits if c["totaal"]["engine"]]
    orkestratie = [c for c in commits if c["totaal"]["orkestratie"] and not c["totaal"]["engine"]]
    meting = [c for c in commits if c["totaal"]["meting"]]
    bron = [c for c in commits if c["totaal"]["bron"]]
    overig = [c for c in commits if not any(c["totaal"][k] for k in ("engine", "parameter", "bron", "orkestratie"))]

    def shas(lijst):
        return ", ".join(c["sha"] for c in lijst)

    def met_bestanden(c, klasse):
        namen = sorted({kort_bestand(p) for p, t in c["per_bestand"].items() if t[klasse]})
        return c["sha"] + (" (" + ", ".join(namen[:3]) + ")" if namen else "")

    def ev(lijst, enkel, meer):
        return enkel if len(lijst) == 1 else meer

    if uitkomst == "geen":
        return ["Een van beide kanten heeft geen standtifs; er valt niets te vergelijken."]

    if uitkomst == "identiek":
        z.append("Zelfde stand, zelfde controlewaarden.")
        if rekenwijze:
            z.append(f"De {ev(rekenwijze, 'commit', 'commits')} die de rekenwijze {ev(rekenwijze, 'raakt', 'raken')} ({shas(rekenwijze)}) "
                     f"{ev(rekenwijze, 'heeft', 'hebben')} op dit profiel geen effect; over andere sectoren, varianten en latere zichtjaren zegt dat niets.")
        elif commits:
            z.append("Geen commit raakt de rekenwijze, dus dit was de verwachte uitkomst.")

    elif uitkomst == "stand_gelijk":
        stems = []
        for d in diag_anders:
            n = naam_controle(re.sub(r"^(Y\d{4}|Basisjaar)_", "", d["naam"]))
            if n not in stems:
                stems.append(n)
        namen = ", ".join(stems[:5]) + (" en meer" if len(stems) > 5 else "")
        z.append(f"De stand is gelijk; alleen de meting verschilt: {namen}.")
        if meting:
            z.append(f"Dat komt door {' en '.join(met_bestanden(c, 'meting') for c in meting)}, "
                     f"{ev(meting, 'die', 'die')} de indicatoren en de export {ev(meting, 'raakt', 'raken')} en de allocatie niet.")
        elif rekenwijze:
            z.append(f"Geen commit raakt de meting; {shas(rekenwijze)} {ev(rekenwijze, 'raakt', 'raken')} de rekenwijze en "
                     f"{ev(rekenwijze, 'heeft', 'hebben')} kennelijk alleen iets veranderd wat deze controlewaarden meten.")
        elif commits:
            z.append("Geen commit raakt de meting of de rekenwijze; kijk naar de omgeving van de run (brondata op schijf, GeoDMS-versie).")

    else:
        # Wat verschuift, per casus.
        klasse_tekst = {"landgebruikstype": "een ander landgebruikstype", "subsector": "een andere subsector"}
        for casus, pats in patronen.items():
            delen = []
            bewogen_hier = set()
            for sleutel in dict.fromkeys(p["sector"] for p in pats):
                rijen = [p for p in pats if p["sector"] == sleutel and not p.get("gelijk")]
                if not rijen:
                    continue
                bewogen_hier.add(sleutel)
                if rijen[0].get("klassen"):
                    cellen = ", ".join(f"{nl(format(p['anders'], ','))} cellen in {p['jaar']}" for p in rijen)
                    delen.append(f"{cellen} krijgen {klasse_tekst.get(sleutel, 'een andere ' + sleutel)}")
                    continue
                aandeel = max(pct(p["erbij"] + p["weg"] + p["anders"], p["bezet_a"]) for p in rijen)
                totalen = ", ".join((f"{v} {p['eenheid']}" if (v := toon_verschil(p['totaal_a'], p['totaal_b'], 0)) != "gelijk" else "totaal gelijk")
                                    + f" in {p['jaar']}" for p in rijen)
                delen.append(f"{sleutel} verschuift op {nl(format(aandeel, '.2f'))} procent van zijn cellen ({totalen})")
            stil = [s for s in dict.fromkeys(p["sector"] for p in pats) if s not in bewogen_hier]
            kop = f"{kort_casus(casus)}: " if len(patronen) > 1 else ""
            if delen:
                zin = "; ".join(delen) + "."
                zin = zin[0].upper() + zin[1:]
                z.append(kop + zin + (f" Gelijk gebleven: {', '.join(stil)}." if stil else ""))
            elif pats:
                z.append(kop + "de stand is gelijk.")
        # Wat het kan verklaren.
        oorzaak = []
        if rekenwijze:
            oorzaak.append(" en ".join(met_bestanden(c, "engine") for c in rekenwijze[:4]) +
                           (f" en {len(rekenwijze) - 4} andere commits die de rekenwijze raken (zie Verder kijken)" if len(rekenwijze) > 4 else ""))
        if verschillen:
            oorzaak.append("de instellingen " + ", ".join(v["pad"].split("/")[-1] for v in verschillen[:4]) + (" en meer" if len(verschillen) > 4 else ""))
        if bron:
            oorzaak.append("een andere invoer in " + shas(bron))
        if oorzaak:
            z.append("Oorzaak: " + "; ".join(oorzaak) + ".")
        elif orkestratie:
            z.append(f"Geen commit raakt de rekenwijze of de instellingen; wel verdeelt {shas(orkestratie)} het schrijfwerk anders over de rekenstappen. "
                     "Dat hoort de uitkomst niet te veranderen, maar het is de enige kandidaat.")
        elif commits:
            z.append("Geen commit raakt de rekenwijze, de instellingen of de invoer; het verschil is uit de configuratie niet te verklaren. "
                     "Kijk naar de omgeving: GeoDMS-versie en brondata op schijf.")
        # Op welke sector is de wijziging gericht? De sectornaam in het pad van een instelling of een engine-
        # bestand zegt dat (ModelParameters/Wonen/..., Templates/Allocatie/IterSubsector_T_Wonen.dms).
        paden = [v["pad"] for v in verschillen] + [p for c in rekenwijze for p in c["engine"]]
        treffers = {s: sum(map_.lower() in pad.lower() for pad in paden) for s, (map_, _) in SECTOREN.items()}
        gericht = {s for s, n in treffers.items() if n}
        bewogen = {p["sector"] for pats in patronen.values() for p in pats if not p.get("gelijk") and p["sector"] in SECTOREN}
        neven = sorted(bewogen - gericht)
        if len(gericht) == 1 and neven and gericht & bewogen:
            z.append(f"De wijziging mikt op {next(iter(gericht))}; {', '.join(neven)} schuift mee door verdringing.")
        elif len(gericht) > 1 and gericht & bewogen:
            z.append("De code raakt " + ", ".join(sorted(gericht, key=lambda s: -treffers[s])) +
                     (f"; {', '.join(neven)} schuift mee door verdringing." if neven else "."))
        if overig and oorzaak:
            z.append(f"De overige {ev(overig, 'commit', 'commits')} ({shas(overig)}) {ev(overig, 'raakt', 'raken')} alleen indicatoren, export of toelichting.")
        if orkestratie and oorzaak:
            z.append(f"{shas(orkestratie)} verdeelt alleen het schrijfwerk anders over de rekenstappen; dat hoort de uitkomst niet te veranderen.")

    if info_a.get("geodms") and info_b.get("geodms") and info_a["geodms"] != info_b["geodms"]:
        z.append(f"Let op: de twee kanten draaiden op verschillende GeoDMS-versies ({info_a['geodms']} tegen {info_b['geodms']}); "
                 "een deel van het verschil kan daarvandaan komen.")
    if patch_gelijk:
        z.append("Op beide kanten lag dezelfde patch (" + ", ".join(patch_gelijk) + "); die valt tegen elkaar weg.")
    if patch_alleen_b:
        z.append("Op B lag bovendien ongecommit werk (" + ", ".join(patch_alleen_b) + "); zie Verder kijken.")
    # Rekentijd en geheugen zijn op een gedeelde machine ruis; alleen een groot verschil is een zin waard.
    if maten_a and maten_b:
        a, b = maten_a.get("alloc_min"), maten_b.get("alloc_min")
        if a and b and abs(b - a) > 0.25 * a and abs(b - a) > 1.0:
            z.append(f"De allocatie duurde {nl(format(b, '.1f'))} in plaats van {nl(format(a, '.1f'))} minuten; op een gedeelde machine "
                     "is pas een verdubbeling een signaal.")
        a, b = maten_a.get("piek_gb"), maten_b.get("piek_gb")
        if a and b and abs(b - a) > 0.25 * a:
            z.append(f"Het piekgeheugen van de allocatie was {nl(format(b, '.1f'))} in plaats van {nl(format(a, '.1f'))} GB.")
    return z


# ---------------------------------------------------------------- het rapport

def bouw(run_a, run_b, naam_a, naam_b, casussen, repo, ref_a, ref_b, kopie_b=None, patches_b=None, patches_a=None, samenvatting=""):
    # Een casus die aan een kant geen stand heeft (de run viel daar om) telt niet mee in de vergelijking;
    # het oordeel zegt dat hij ontbreekt, want anders leest elke tif van die casus als een verschil.
    ontbreekt = []
    for casus in list(casussen):
        heeft_a = (Path(run_a) / "Allocatie" / casus).is_dir() and any((Path(run_a) / "Allocatie" / casus).rglob("*.tif"))
        heeft_b = (Path(run_b) / "Allocatie" / casus).is_dir() and any((Path(run_b) / "Allocatie" / casus).rglob("*.tif"))
        if heeft_a != heeft_b:
            ontbreekt.append(f"{kort_casus(casus)} niet gerekend in {'B' if heeft_a else 'A'}")
            casussen = [c for c in casussen if c != casus]
        elif not heeft_a:
            ontbreekt.append(f"{kort_casus(casus)} aan beide kanten niet gerekend")
            casussen = [c for c in casussen if c != casus]
    gelijk, anders, alleen_a, alleen_b, ta, tb = vergelijk_tifs(run_a, run_b, casussen)
    diag, diag_alleen_a, diag_alleen_b = [], [], []
    for casus in casussen:
        d, da, db = vergelijk_diagnose(run_a, run_b, casus)
        diag += d
        diag_alleen_a += [f"{kort_casus(casus)} {n}" for n in da]
        diag_alleen_b += [f"{kort_casus(casus)} {n}" for n in db]
    diag_anders = [d for d in diag if not d["gelijk"]]
    maten_a, maten_b = runmaten(run_a), runmaten(run_b)
    info_a, info_b = toetsinfo(run_a), toetsinfo(run_b)

    datum_a = git(repo, "log", "-1", "--format=%cs", ref_a) if repo and ref_a else ""
    datum_b = git(repo, "log", "-1", "--format=%cs", ref_b) if repo and ref_b else ""

    # Patches: wat op beide kanten lag valt weg, wat alleen op B lag is ongecommit werk.
    inhoud_a, inhoud_b = patch_inhoud(patches_a), patch_inhoud(patches_b)
    patch_gelijk = sorted(n for n in inhoud_b if n in inhoud_a and inhoud_a[n] == inhoud_b[n])
    patch_alleen_b = sorted(n for n in inhoud_b if n not in patch_gelijk)
    patches_b_los = [p for p in (patches_b or []) if Path(p).name in patch_alleen_b]

    # Het oordeel, voor de titel en het log.
    stand_gelijk = bool(ta and tb) and not anders and not alleen_a and not alleen_b
    if not ta or not tb:
        uitkomst, oordeel = "geen", "GEEN OORDEEL: een van beide runs heeft geen standtifs"
    elif stand_gelijk and not diag_anders:
        uitkomst, oordeel = "identiek", f"IDENTIEK: {len(gelijk)} standtifs byte-gelijk, {len(diag)} controlewaarden gelijk"
    elif stand_gelijk:
        uitkomst, oordeel = "stand_gelijk", f"STAND GELIJK: {len(gelijk)} standtifs byte-gelijk, {len(diag_anders)} van {len(diag)} controlewaarden anders"
    else:
        uitkomst = "anders"
        oordeel = (f"VERSCHILT: {len(anders)} van {len(gelijk) + len(anders)} standtifs anders, {len(diag_anders)} van {len(diag)} controlewaarden anders"
                   + (f", {len(alleen_a)} tifs alleen in A, {len(alleen_b)} alleen in B" if alleen_a or alleen_b else ""))
    if ontbreekt:
        oordeel += "; " + ", ".join(ontbreekt)

    # De commits en de instellingen tussen A en B.
    commits, verschillen, details_patch = [], [], []
    if repo and ref_a and ref_b:
        from VergelijkCommits import bouw_rapport_werkkopie, commits_tussen, lees_parameters, vergelijk_instellingen
        pa, pb = lees_parameters(Path(repo), ref_a), lees_parameters(Path(repo), ref_b)
        verschillen, verplaatst, rekenitems, inst_totaal = vergelijk_instellingen(pa, pb, {}, {}, False)
        commits = commits_tussen(Path(repo), ref_a, ref_b)
        if kopie_b and patches_b_los:
            ongecommit, _ = bouw_rapport_werkkopie(Path(repo), ref_b, kopie_b, patches_b_los, {}, False)
            details_patch = ongecommit.splitlines()[2:]
    tekst_samenvatting = samenvatting.strip() if samenvatting else (samenvatting_auto(commits) if commits else "")

    r = [f"# Van {naam_a}" + (f" ({datum_a})" if datum_a else "") + f" naar {naam_b}" + (f" ({datum_b})" if datum_b else ""), ""]
    if samenvatting.strip():
        r.append(tekst_samenvatting)   # een meegegeven tekst is compleet; het aantal commits staat in het log
    elif commits:
        r.append(f"{len(commits)} {'commit' if len(commits) == 1 else 'commits'}. {tekst_samenvatting}")
    elif repo and ref_a and ref_b:
        r.append("Geen commits tussen A en B.")
    r.append("")

    # ---- Hoe anders
    r.append("## Hoe anders")
    r.append("")
    patronen = {}
    for casus in casussen:
        if len(casussen) > 1:
            r.append(f"### {kort_casus(casus)}")
            r.append("")
        per_naam = {}
        for d in diag:
            if d["casus"] != casus:
                continue
            m = re.match(r"(Y\d{4}|Basisjaar)_(.+)", d["naam"])
            if m:
                per_naam.setdefault(m.group(2), []).append(d)
        rijen = []
        for stem in KOPTABEL:
            for d in per_naam.get(stem, []):
                if d["a"] is None and d["b"] is None:
                    continue  # niet van toepassing in dit profiel; een rij n.v.t. zegt niets
                rijen.append([naam_controle(d["naam"]), toon(d["a"]), toon(d["b"]), toon_verschil(d["a"], d["b"]) or ("gelijk" if d["gelijk"] else "anders")])
        if rijen:
            r += tabel(["maat", f"van {naam_a}", f"naar {naam_b}", "verschil"], rijen)
        else:
            r.append("Geen controlewaarden voor deze casus; draai de diagnose mee.")
        r.append("")
        pats = patroon_per_sector(ta, tb, anders, casus) if anders else []
        patronen[casus] = pats
        if pats:
            prijen = []
            for p in pats:
                naam = f"{p['sector']} {p['jaar']}"
                if p.get("gelijk"):
                    prijen.append([naam, "gelijk", "", "", "", ""])
                elif p.get("klassen"):
                    prijen.append([naam, "", "", "", nl(format(p["anders"], ",")) + " (andere klasse)", ""])
                else:
                    prijen.append([naam, f"{nl(format(p['bezet_a'], ','))} cellen bezet",
                                   f"{nl(format(p['erbij'], ','))} ({nl(format(p['erbij'] * HA_PER_CEL, ',.1f'))} ha)",
                                   f"{nl(format(p['weg'], ','))} ({nl(format(p['weg'] * HA_PER_CEL, ',.1f'))} ha)",
                                   nl(format(p["anders"], ",")),
                                   (f"{v} {p['eenheid']}" if (v := toon_verschil(p["totaal_a"], p["totaal_b"])) != "gelijk" else "gelijk")])
            r.append("Patroon op de kaart, per sector de som van de subsectoren per cel:")
            r.append("")
            r += tabel(["kaart", "van", "cellen erbij", "cellen weg", "cellen anders", "totaal"], prijen)
            r.append("")

    # ---- Waarom
    r.append("## Waarom")
    r.append("")
    if repo and ref_a and ref_b:
        # Elke zin een eigen alinea; aaneengesloten regels worden in de html een blok tekst.
        for zin in interpretatie(uitkomst, patronen, maten_a, maten_b, info_a, info_b, commits, verschillen, diag_anders, patch_gelijk, patch_alleen_b):
            r += [zin, ""]
        if verschillen:
            r.append("Instellingen die verschillen:")
            r.append("")
            r += tabel(["instelling", f"van {naam_a}", f"naar {naam_b}"], [[v["pad"], v["a"][:48], v["b"][:48]] for v in verschillen])
            r.append("")
    else:
        r.append("Geen commits opgegeven; de verklaring staat niet in dit rapport.")
        r.append("")

    # ---- Verder kijken
    r.append("## Verder kijken")
    r.append("")
    if commits:
        from VergelijkCommits import kort_bestand
        r.append("### Commits")
        r.append("")
        for c in commits:
            regel = f"- {c['sha']} ({c['datum']}) {c['onderwerp']}: {', '.join(c['labels']) or 'leeg'}"
            geraakt = c["engine"] + sorted(p for p, t in c["per_bestand"].items() if t["orkestratie"])
            if geraakt:
                regel += " (" + ", ".join(kort_bestand(p) for p in geraakt[:4]) + ")"
            r.append(regel)
        r.append("")

    r.append("### Standtifs die verschillen")
    r.append("")
    r.append(f"{len(gelijk)} byte-gelijk, {len(anders)} anders, {len(alleen_a)} alleen in A, {len(alleen_b)} alleen in B.")
    r.append("")
    if anders:
        trijen = []
        for rel in anders:
            cv = celverschil(ta[rel], tb[rel])
            if cv is None:
                trijen.append([kort_tif(rel), "doorklik vraagt numpy en tifffile", "", "", "", ""])
            elif "vorm" in cv:
                trijen.append([kort_tif(rel), "andere vorm", cv["vorm"], "", "", ""])
            else:
                trijen.append([kort_tif(rel), nl(format(cv["cellen"], ",")), nl(format(cv["pct"], ".3f")),
                               nl(format(cv["som_a"], ",.0f")), nl(format(cv["som_b"], ",.0f")), nl(format(cv["max_abs"], ",.2f"))])
        r += tabel(["tif", "cellen anders", "procent", "som A", "som B", "grootste celafwijking"], trijen)
        r.append("")
    for rel in alleen_a:
        r.append(f"- alleen in A: {kort_tif(rel)}")
    for rel in alleen_b:
        r.append(f"- alleen in B: {kort_tif(rel)}")
    if alleen_a or alleen_b:
        r.append("")

    r.append("### Controlewaarden die verschillen")
    r.append("")
    nvt = sum(1 for d in diag if d["a"] is None and d["b"] is None)
    if not diag:
        r.append("Geen controlewaarden in beide runs; draai de diagnose mee.")
    elif not diag_anders:
        r.append(f"Geen; {len(diag) - nvt} controlewaarden gelijk en {nvt} niet van toepassing in dit profiel.")
    else:
        r += tabel(["controle", f"van {naam_a}", f"naar {naam_b}", "verschil"],
                   [[(f"{kort_casus(d['casus'])} " if len(casussen) > 1 else "") + naam_controle(d["naam"]), toon(d["a"]), toon(d["b"]),
                     toon_verschil(d["a"], d["b"]) or "anders"] for d in diag_anders])
        r.append("")
        r.append(f"Daarnaast {len(diag) - len(diag_anders) - nvt} controlewaarden gelijk en {nvt} niet van toepassing in dit profiel.")
    if diag_alleen_a or diag_alleen_b:
        r.append(f"Alleen in A: {', '.join(diag_alleen_a) or 'geen'}. Alleen in B: {', '.join(diag_alleen_b) or 'geen'}.")
    r.append("")

    if commits:
        r.append("### Bestanden per commit")
        r.append("")
        volgorde = ("engine", "orkestratie", "parameter", "bron", "meting", "toelichting", "buiten")
        brijen = []
        for c in commits:
            for pad, t in sorted(c["per_bestand"].items()):
                klasse = next((k for k in volgorde if t[k]), "")
                brijen.append([c["sha"], pad, klasse, sum(t.values())])
        r += tabel(["commit", "bestand", "klasse", "regels"], brijen)
        r.append("")
    if details_patch:
        r.append("### Wat er ongecommit bovenop B lag")
        r.append("")
        r += details_patch
        r.append("")

    r.append("### Technisch")
    r.append("")
    def mt(x, k):
        return nl(format(x[k], ".1f")) if x and x.get(k) is not None else ""
    trijen = [
        ["GeoDMS", info_a.get("geodms", ""), info_b.get("geodms", "")],
        ["testprofiel", info_a.get("testprofiel", ""), info_b.get("testprofiel", "")],
        ["baseline", info_a.get("baseline", ""), info_b.get("baseline", "")],
        ["varianten", info_a.get("varianten", ""), info_b.get("varianten", "")],
        ["zichtjaren", info_a.get("zichtjaren", ""), info_b.get("zichtjaren", "")],
        ["patches", info_a.get("patches", ""), info_b.get("patches", "")],
        ["rekentijd allocatie (min)", mt(maten_a, "alloc_min"), mt(maten_b, "alloc_min")],
        ["rekentijd hele toets (min)", mt(maten_a, "totaal_min"), mt(maten_b, "totaal_min")],
        ["piekgeheugen allocatie (GB)", mt(maten_a, "piek_gb"), mt(maten_b, "piek_gb")],
        ["uitvoer", str(run_a), str(run_b)],
    ]
    r += tabel(["", f"van {naam_a}", f"naar {naam_b}"], [t for t in trijen if t[1] or t[2]])
    r.append("")

    kern = {"oordeel": oordeel, "tifs_anders": len(anders), "tifs_totaal": len(gelijk) + len(anders),
            "checks_anders": len(diag_anders), "checks_totaal": len(diag), "datum_a": datum_a, "datum_b": datum_b,
            "commits": len(commits), "samenvatting": samenvatting_kort(tekst_samenvatting)}
    return "\n".join(r), kern


def main():
    p = argparse.ArgumentParser(description="Legt twee runs van RSopen naast elkaar.")
    p.add_argument("--a", required=True, help="de run van (A)")
    p.add_argument("--b", required=True, help="de run naar (B)")
    p.add_argument("--uit", required=True)
    p.add_argument("--naam-a", default="A")
    p.add_argument("--naam-b", default="B")
    p.add_argument("--casus", action="append", help="casus, meerdere keren toegestaan; standaard WLO_hoog_BAU")
    p.add_argument("--repo")
    p.add_argument("--ref-a")
    p.add_argument("--ref-b")
    p.add_argument("--samenvatting", default="", help="wat er in de commits tussen A en B zit, in een of twee zinnen")
    p.add_argument("--kopie-b", help="momentopname van B met de patches erop, van voor het profiel")
    p.add_argument("--patch-b", action="append", help="patch die op B lag; meerdere keren toegestaan")
    p.add_argument("--patch-a", action="append", help="patch die op A lag; valt weg als hij ook op B ligt")
    p.add_argument("--html", help="schrijf het rapport ook als pagina")
    p.add_argument("--log", help="csv waar deze toets als regel bij komt (zie Toetslog.py)")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf8", errors="replace")
    casussen = a.casus or ["WLO_hoog_BAU"]
    rapport, kern = bouw(a.a, a.b, a.naam_a, a.naam_b, casussen, a.repo, a.ref_a, a.ref_b, a.kopie_b, a.patch_b, a.patch_a, a.samenvatting)
    Path(a.uit).parent.mkdir(parents=True, exist_ok=True)
    Path(a.uit).write_text(rapport, encoding="utf8")
    print(kern["oordeel"])
    print(f"rapport: {a.uit}")
    if a.html:
        from Toetslog import rapportpagina
        Path(a.html).write_text(rapportpagina(rapport, f"Van {a.naam_a} naar {a.naam_b}"), encoding="utf8")
        print(f"pagina: {a.html}")
    if a.log:
        from Toetslog import schrijf_logregel
        schrijf_logregel(a.log, a.naam_a, kern["datum_a"], a.naam_b, kern["datum_b"], kern["commits"], kern["samenvatting"], kern["oordeel"],
                         kern["tifs_anders"], kern["tifs_totaal"], kern["checks_anders"], kern["checks_totaal"], a.uit)
        print(f"log: {a.log}")


if __name__ == "__main__":
    sys.exit(main())
