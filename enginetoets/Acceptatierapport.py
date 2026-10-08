"""Het acceptatierapport: de volle run van een kandidaat naast de volle run van de baseline.

Gebruik:
    python Acceptatierapport.py --a <volle run baseline> --b <volle run kandidaat> --uit <rapport.md>
        --repo <pad> --ref-a <baseline> --ref-b <kandidaat> [--naam-a ...] [--naam-b ...]
        [--casus WLO_hoog_BAU ...] [--normen-a <toets_oplevering.md>] [--normen-b <toets_oplevering.md>]
        [--log <toetslog.csv>] [--html <pagina>] [--samenvatting <tekst>]

De enginetoets (Toetsrapport.py) rekent onder het bevroren profiel van de baseline en meet alleen de
rekenwijze. De acceptatie is de andere vraag: mag deze commit de nieuwe baseline worden? Daarvoor draait
de kandidaat met zijn eigen instellingen (Toets.ps1 -EigenInstellingen), over alle zichtjaren en de
varianten van de productie, en legt dit rapport drie dingen naast elkaar:

1. de instellingen en de leveringen die tussen baseline en kandidaat zijn veranderd (uit de configuratie,
   zonder run), zodat de lezer per regel kan zeggen of dat de bedoeling was;
2. de ketting van enginetoetsen tussen baseline en kandidaat uit het toetslog, al gedaan en na te lezen;
3. de volle run naast die van de baseline: per casus en zichtjaar de koptabel, en de normen van
   batch/ToetsOplevering.ps1 van de kandidaat, op beide runs gedraaid, met per toets het oordeel aan
   beide kanten.

Het oordeel in het log heet ACCEPTATIE en zegt hoeveel normen de kandidaat haalt tegenover de baseline
en hoeveel standtifs anders zijn; of het akkoord is, zegt de lezer. Is het akkoord, dan maakt
Baseline.ps1 de kandidaat tot baseline, met deze volle run als tweede uitvoer (-Vol).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from Toetsrapport import (KOPTABEL, HA_PER_CEL, celverschil, enkel, git, kort_casus, kort_tif, naam_controle, nl,  # noqa: E402
                          patroon_per_sector, runmaten, samenvatting_kort, tabel, toetsinfo, toon, toon_verschil,
                          vergelijk_diagnose, vergelijk_tifs)
from VergelijkCommits import AFWEZIG, commits_tussen, lees_parameters, tel_diff, vergelijk_instellingen  # noqa: E402

STORAGEWAARDE = re.compile(r'StorageName\s*=\s*"([^"]*)"')


# ---------------------------------------------------------------- de normen van ToetsOplevering

def lees_normen(pad):
    """De tabel uit toets_oplevering.md: trap, casus, toets, oordeel, gemeten, verwacht per regel."""
    uit = []
    if not pad or not Path(pad).is_file():
        return uit
    for regel in Path(pad).read_text(encoding="utf8", errors="replace").splitlines():
        if not regel.startswith("|"):
            continue
        cellen = [c.strip() for c in regel.strip().strip("|").split("|")]
        if len(cellen) < 6 or cellen[0] in ("trap", "") or set(cellen[0]) <= {"-"}:
            continue
        uit.append({"trap": cellen[0], "casus": cellen[1], "toets": cellen[2], "oordeel": cellen[3], "gemeten": cellen[4], "verwacht": cellen[5]})
    return uit


def normen_naast_elkaar(normen_a, normen_b):
    """Per (casus, toets) het oordeel en de meting aan beide kanten; de toetsen die alleen aan een kant
    bestaan komen er met een leeg vak bij."""
    a = {(n["casus"], n["toets"]): n for n in normen_a}
    b = {(n["casus"], n["toets"]): n for n in normen_b}
    rijen = []
    for sleutel in sorted(set(a) | set(b), key=lambda s: (s[0], s[1])):
        na, nb = a.get(sleutel), b.get(sleutel)
        rijen.append({"casus": sleutel[0], "toets": sleutel[1],
                      "oordeel_a": na["oordeel"] if na else "", "gemeten_a": na["gemeten"] if na else "",
                      "oordeel_b": nb["oordeel"] if nb else "", "gemeten_b": nb["gemeten"] if nb else "",
                      "verwacht": (nb or na or {}).get("verwacht", "")})
    return rijen


def telling(normen):
    """PASS en FAIL geteld; INFO en GEEN DATA tellen niet mee."""
    p = sum(1 for n in normen if n["oordeel"] == "PASS")
    f = sum(1 for n in normen if n["oordeel"] == "FAIL")
    return p, f


# ---------------------------------------------------------------- leveringen en ketting

LEVERING = re.compile(r"(date|datum|jaargang|vintage|bestand|file|levering|year|jaar|versie)", re.IGNORECASE)


def leveringen(echt):
    """De instellingen die een levering aanwijzen (een datum, een jaargang, een bestandsnaam) en anders staan:
    dat is de datakant van de wijziging, leesbaar zonder de code."""
    return [v for v in echt if LEVERING.search(v["pad"].rsplit("/", 1)[-1]) and v["a"] != AFWEZIG and v["b"] != AFWEZIG]


def storageregels(repo, ref_a, ref_b):
    """Hoeveel StorageName-regels in SourceData en PrivData zijn veranderd, en in welke bestanden; de inhoud
    is code (een pad dat naar een parameter verhuist telt ook) en staat in de commits."""
    _, storages = tel_diff(Path(repo), ref_a, ref_b)
    bestanden = sorted({bestand.replace("cfg/main/", "") for teken, bestand, regel in storages
                        if bestand.startswith(("cfg/main/SourceData", "cfg/main/PrivData")) and teken == "+"})
    return bestanden


def is_voorouder(repo, a, b):
    r = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b], capture_output=True)
    return r.returncode == 0


def ketting(logpad, repo, ref_a, ref_b):
    """De regels van het toetslog die tussen baseline en kandidaat liggen: van en naar binnen de reeks."""
    from Toetslog import lees_log
    uit = []
    for r in lees_log(logpad):
        van, naar = r.get("van") or "", r.get("naar") or ""
        if not van or not naar or (r.get("oordeel") or "").startswith(("BASELINE", "ACCEPTATIE")):
            continue
        try:
            if is_voorouder(repo, ref_a, van) and is_voorouder(repo, naar, ref_b):
                uit.append(r)
        except Exception:
            continue
    return uit


# ---------------------------------------------------------------- het rapport

def koptabel(diag, casus, jaar, naam_a, naam_b):
    rijen = []
    per_stem = {}
    for d in diag:
        if d["casus"] != casus:
            continue
        m = re.match(r"(Y\d{4}|Basisjaar)_(.+)", d["naam"])
        if m and m.group(1) == jaar:
            per_stem[m.group(2)] = d
    for stem in KOPTABEL:
        d = per_stem.get(stem)
        if d is None or (d["a"] is None and d["b"] is None):
            continue
        rijen.append([naam_controle(stem), toon(d["a"]), toon(d["b"]), toon_verschil(d["a"], d["b"]) or ("gelijk" if d["gelijk"] else "anders")])
    return tabel(["maat", f"baseline {naam_a}", f"kandidaat {naam_b}", "verschil"], rijen)


def bouw(run_a, run_b, naam_a, naam_b, casussen, repo, ref_a, ref_b, normen_a_pad, normen_b_pad, logpad, samenvatting=""):
    gelijk, anders, alleen_a, alleen_b, ta, tb = vergelijk_tifs(run_a, run_b, casussen)
    diag = []
    for casus in casussen:
        d, _, _ = vergelijk_diagnose(run_a, run_b, casus)
        diag += d
    diag_anders = [d for d in diag if not d["gelijk"]]
    jaren = sorted({r.split("/")[2].replace("Stand", "") for r in (set(ta) | set(tb)) if "/Stand" in r})
    maten_a, maten_b = runmaten(run_a), runmaten(run_b)
    info_a, info_b = toetsinfo(run_a), toetsinfo(run_b)
    datum_a = git(repo, "log", "-1", "--format=%cs", ref_a)
    datum_b = git(repo, "log", "-1", "--format=%cs", ref_b)

    normen_a, normen_b = lees_normen(normen_a_pad), lees_normen(normen_b_pad)
    pa, fa = telling(normen_a)
    pb, fb = telling(normen_b)
    naast = normen_naast_elkaar(normen_a, normen_b)
    verslechterd = [n for n in naast if n["oordeel_a"] == "PASS" and n["oordeel_b"] == "FAIL"]
    verbeterd = [n for n in naast if n["oordeel_a"] == "FAIL" and n["oordeel_b"] == "PASS"]

    params_a, params_b = lees_parameters(Path(repo), ref_a), lees_parameters(Path(repo), ref_b)
    # vergelijk_instellingen geeft de echte verschillen en apart wat alleen van container is gewisseld.
    echt, verplaatst, _, inst_totaal = vergelijk_instellingen(params_a, params_b, {}, {}, False)
    echt = [v for v in echt if v["a"] != v["b"]]   # een omgevingsexpressie tegen zijn uitkomst is geen verschil
    anders_waarde = [v for v in echt if v["a"] != AFWEZIG and v["b"] != AFWEZIG]
    nieuw_inst = [v for v in echt if v["a"] == AFWEZIG]
    weg_inst = [v for v in echt if v["b"] == AFWEZIG]
    lever = leveringen(echt)
    storagebestanden = storageregels(repo, ref_a, ref_b)
    commits = commits_tussen(Path(repo), ref_a, ref_b)
    rekenwijze = [c for c in commits if c["totaal"]["engine"]]
    schakels = ketting(logpad, repo, ref_a, ref_b) if logpad else []

    oordeel = (f"ACCEPTATIE: normen kandidaat {pb} PASS en {fb} FAIL (baseline {pa} PASS en {fa} FAIL); "
               f"{len(anders)} van {len(gelijk) + len(anders)} standtifs anders")
    if verslechterd:
        oordeel += f"; {len(verslechterd)} norm{'en' if len(verslechterd) > 1 else ''} van PASS naar FAIL"

    tekst = samenvatting.strip() or (f"{len(commits)} commits sinds de baseline, waarvan {len(rekenwijze)} de rekenwijze raken; "
                                       f"de ketting van enginetoetsen ertussen staat hieronder.")
    r = [f"# Acceptatie: van {naam_a} ({datum_a}) naar {naam_b} ({datum_b})", "", tekst, ""]
    r.append("De kandidaat rekent hier met zijn eigen instellingen, over alle zichtjaren en de varianten van de productie; "
             "dit is geen enginetoets maar de vraag of de commit de nieuwe baseline mag worden.")
    r.append("")

    # ---- 1. instellingen en leveringen
    r.append("## Instellingen en leveringen")
    r.append("")
    r.append(f"Van de {inst_totaal} instellingen hebben {len(anders_waarde)} een andere waarde, zijn er {len(nieuw_inst)} nieuw in de kandidaat "
             f"(ze houden hun standaardwaarde) en {len(weg_inst)} niet meer in de kandidaat (vast ingebouwd of weggehaald)"
             + (f"; {len(verplaatst)} zijn alleen van container gewisseld" if verplaatst else "") + ". De nieuwe en de verdwenen staan onder Verder kijken.")
    r.append("")
    if anders_waarde:
        r += tabel(["instelling met een andere waarde", f"baseline {naam_a}", f"kandidaat {naam_b}"],
                   [[v["pad"], v["a"][:48], v["b"][:48]] for v in anders_waarde])
    else:
        r.append("Geen instelling die aan beide kanten bestaat heeft een andere waarde.")
    r.append("")
    if lever:
        r.append("Leveringen: instellingen die een datum, jaargang of bestand aanwijzen en anders staan.")
        r.append("")
        r += tabel(["levering", f"baseline {naam_a}", f"kandidaat {naam_b}"], [[v["pad"], v["a"][:48], v["b"][:48]] for v in lever])
    else:
        r.append("Geen levering (datum, jaargang of bestandsnaam onder de instellingen) staat anders.")
    if storagebestanden:
        r.append(f"Daarnaast zijn in {len(storagebestanden)} bronbestanden StorageName-regels veranderd ({', '.join(storagebestanden[:8])}"
                 + (" en meer" if len(storagebestanden) > 8 else "") + "); of dat een andere levering is of een verhuizing van het pad staat in de commits.")
    r.append("")

    # ---- 2. de ketting
    r.append("## De ketting van enginetoetsen")
    r.append("")
    if schakels:
        r += tabel(["nr", "van", "naar", "commits", "oordeel"],
                   [[s.get("nr", ""), s.get("van", ""), s.get("naar", ""), s.get("commits", ""), (s.get("oordeel") or "").split(";")[0]] for s in schakels])
        r.append("")
        r.append("Elke schakel rekent onder het bevroren profiel van de baseline; de rapporten staan op de pagina van het log.")
    else:
        r.append("Geen enginetoetsen in het log tussen baseline en kandidaat.")
    r.append("")

    # ---- 3. de volle run naast de baseline
    r.append("## De volle run naast de baseline")
    r.append("")
    eindjaar = jaren[-1] if jaren else None   # als Y2120
    for casus in casussen:
        if eindjaar:
            r.append(f"### {kort_casus(casus)}, {eindjaar[1:]}")
            r.append("")
            kt = koptabel(diag, casus, eindjaar, naam_a, naam_b)
            r += kt if kt else ["Geen controlewaarden voor dit zichtjaar."]
            r.append("")
    if naast:
        r.append("### Normen van ToetsOplevering")
        r.append("")
        r.append(f"Kandidaat: {pb} PASS, {fb} FAIL. Baseline: {pa} PASS, {fa} FAIL. "
                 + (f"Van PASS naar FAIL: {len(verslechterd)}. " if verslechterd else "Geen norm ging van PASS naar FAIL. ")
                 + (f"Van FAIL naar PASS: {len(verbeterd)}." if verbeterd else ""))
        r.append("")
        r.append("De normen zijn gezet op een landelijke run; in een kleiner studiegebied falen de landelijke totalen en de "
                 "claimrealisatie op het niveau Nederland per constructie, en telt alleen een oordeel dat tussen baseline en kandidaat omslaat.")
        r.append("")
        hard = {"PASS", "FAIL"}
        bijzonder = [n for n in naast if n["oordeel_a"] in hard and n["oordeel_b"] in hard
                     and (n["oordeel_a"] != n["oordeel_b"] or n["oordeel_b"] == "FAIL")]
        alleen_kandidaat = [n for n in naast if n["oordeel_b"] in hard and n["oordeel_a"] not in hard]
        if alleen_kandidaat:
            r.append(f"{len(alleen_kandidaat)} toetsen bestaan alleen voor de kandidaat (nieuwe controles sinds de baseline): "
                     f"{sum(1 for n in alleen_kandidaat if n['oordeel_b'] == 'PASS')} PASS, "
                     f"{sum(1 for n in alleen_kandidaat if n['oordeel_b'] == 'FAIL')} FAIL; zie Alle normen.")
            r.append("")
        if bijzonder:
            r += tabel(["casus", "toets", "baseline", "kandidaat", "verwacht"],
                       [[kort_casus(n["casus"]), n["toets"], f"{n['oordeel_a']} {n['gemeten_a']}".strip(), f"{n['oordeel_b']} {n['gemeten_b']}".strip(), n["verwacht"][:40]]
                        for n in bijzonder])
            r.append("")
            r.append("Alleen de toetsen die aan beide kanten een oordeel hebben en waarvan het oordeel omslaat of op de kandidaat FAIL is; "
                     "de volledige lijst staat onder Verder kijken.")
        else:
            r.append("Van de toetsen die aan beide kanten een oordeel hebben slaat er geen om en faalt er geen op de kandidaat.")
        r.append("")
    else:
        r.append("Geen normen gelezen; geef --normen-a en --normen-b (de uitvoer van ToetsOplevering.ps1 op beide runs).")
        r.append("")

    # ---- Waarom, kort
    r.append("## Waarom")
    r.append("")
    if rekenwijze:
        r.append(f"{len(commits)} commits, {len(rekenwijze)} raken de rekenwijze: " + ", ".join(c["sha"] for c in rekenwijze[:8]) +
                 (" en meer" if len(rekenwijze) > 8 else "") + ". Welke schakel welk verschil bracht staat in de ketting hierboven; "
                 "de instellingen die hier anders staan zijn in de ketting bevroren en tellen alleen in deze volle run mee.")
    elif commits:
        r.append(f"{len(commits)} commits, geen raakt de rekenwijze; elk verschil komt van de instellingen of de leveringen hierboven.")
    r.append("")

    # ---- Verder kijken
    r.append("## Verder kijken")
    r.append("")
    for casus in casussen:
        pats = patroon_per_sector(ta, tb, anders, casus) if anders else []
        if pats:
            r.append(f"### Patroon op de kaart, {kort_casus(casus)}")
            r.append("")
            prijen = []
            for p in pats:
                naam = f"{p['sector']} {p['jaar']}"
                if p.get("gelijk"):
                    prijen.append([naam, "gelijk", "", "", "", ""])
                elif p.get("klassen"):
                    prijen.append([naam, "", "", "", nl(format(p["anders"], ",")) + " (andere klasse)", ""])
                else:
                    v = toon_verschil(p["totaal_a"], p["totaal_b"])
                    prijen.append([naam, f"{nl(format(p['bezet_a'], ','))} cellen bezet",
                                   f"{nl(format(p['erbij'], ','))} ({nl(format(p['erbij'] * HA_PER_CEL, ',.1f'))} ha)",
                                   f"{nl(format(p['weg'], ','))} ({nl(format(p['weg'] * HA_PER_CEL, ',.1f'))} ha)",
                                   nl(format(p["anders"], ",")), (f"{v} {p['eenheid']}" if v != "gelijk" else "gelijk")])
            r += tabel(["kaart", "baseline", "cellen erbij", "cellen weg", "cellen anders", "totaal"], prijen)
            r.append("")
    for casus in casussen:
        for jaar in jaren:
            if jaar == eindjaar:
                continue
            kt = koptabel(diag, casus, jaar, naam_a, naam_b)
            if kt:
                r.append(f"### Koptabel {kort_casus(casus)}, {jaar[1:]}")
                r.append("")
                r += kt
                r.append("")
    if naast:
        r.append("### Alle normen")
        r.append("")
        r += tabel(["casus", "toets", "baseline", "kandidaat", "verwacht"],
                   [[kort_casus(n["casus"]), n["toets"], f"{n['oordeel_a']} {n['gemeten_a']}".strip(), f"{n['oordeel_b']} {n['gemeten_b']}".strip(), n["verwacht"][:40]]
                    for n in naast])
        r.append("")
    if nieuw_inst:
        r.append("### Nieuwe instellingen in de kandidaat")
        r.append("")
        r += tabel(["instelling", "waarde"], [[v["pad"], v["b"][:60]] for v in nieuw_inst])
        r.append("")
    if weg_inst:
        r.append("### Instellingen die de kandidaat niet meer kent")
        r.append("")
        r += tabel(["instelling", "waarde in de baseline"], [[v["pad"], v["a"][:60]] for v in weg_inst])
        r.append("")
    if verplaatst:
        r.append("### Instellingen die alleen van container zijn gewisseld")
        r.append("")
        r += tabel(["was", "is", "waarde"], [[v[0], v[1], str(v[2])[:40]] for v in verplaatst])
        r.append("")
    r.append("### Standtifs die verschillen")
    r.append("")
    r.append(f"{len(gelijk)} byte-gelijk, {len(anders)} anders, {len(alleen_a)} alleen in de baseline, {len(alleen_b)} alleen in de kandidaat.")
    r.append("")
    if anders:
        trijen = []
        for rel in anders:
            cv = celverschil(ta[rel], tb[rel])
            if cv is None:
                trijen.append([kort_tif(rel), "celvergelijking vraagt numpy en tifffile", "", "", "", ""])
            elif "vorm" in cv:
                trijen.append([kort_tif(rel), "andere vorm", cv["vorm"], "", "", ""])
            else:
                trijen.append([kort_tif(rel), nl(format(cv["cellen"], ",")), nl(format(cv["pct"], ".3f")),
                               nl(format(cv["som_a"], ",.0f")), nl(format(cv["som_b"], ",.0f")), nl(format(cv["max_abs"], ",.2f"))])
        r += tabel(["tif", "cellen anders", "procent", "som baseline", "som kandidaat", "grootste celafwijking"], trijen)
        r.append("")
    r.append("### Controlewaarden die verschillen")
    r.append("")
    if diag_anders:
        r += tabel(["controle", f"baseline {naam_a}", f"kandidaat {naam_b}", "verschil"],
                   [[(f"{kort_casus(d['casus'])} " if len(casussen) > 1 else "") + naam_controle(d["naam"]), toon(d["a"]), toon(d["b"]),
                     toon_verschil(d["a"], d["b"]) or "anders"] for d in diag_anders])
    else:
        r.append("Geen.")
    r.append("")
    r.append("### Hoe de runs draaiden")
    r.append("")
    def mt(x, k):
        return nl(format(x[k], ".1f")) if x and x.get(k) is not None else ""
    trijen = [
        ["GeoDMS", info_a.get("geodms", ""), info_b.get("geodms", "")],
        ["instellingen", info_a.get("instellingen", ""), info_b.get("instellingen", "")],
        ["testprofiel", info_a.get("testprofiel", ""), info_b.get("testprofiel", "")],
        ["varianten", info_a.get("varianten", ""), info_b.get("varianten", "")],
        ["zichtjaren", info_a.get("zichtjaren", ""), info_b.get("zichtjaren", "")],
        ["patches", info_a.get("patches", ""), info_b.get("patches", "")],
        ["rekentijd allocatie (min)", mt(maten_a, "alloc_min"), mt(maten_b, "alloc_min")],
        ["rekentijd hele run (min)", mt(maten_a, "totaal_min"), mt(maten_b, "totaal_min")],
        ["piekgeheugen allocatie (GB)", mt(maten_a, "piek_gb"), mt(maten_b, "piek_gb")],
        ["uitvoer", str(run_a), str(run_b)],
    ]
    r += tabel(["", f"baseline {naam_a}", f"kandidaat {naam_b}"], [t for t in trijen if t[1] or t[2]])
    r.append("")

    kern = {"oordeel": oordeel, "tifs_anders": len(anders), "tifs_totaal": len(gelijk) + len(anders),
            "checks_anders": len(diag_anders), "checks_totaal": len(diag), "datum_a": datum_a, "datum_b": datum_b,
            "commits": len(commits), "samenvatting": samenvatting_kort(tekst)}
    return "\n".join(r), kern


def main():
    p = argparse.ArgumentParser(description="Het acceptatierapport: de volle run van een kandidaat naast die van de baseline.")
    p.add_argument("--a", required=True, help="de volle run van de baseline")
    p.add_argument("--b", required=True, help="de volle run van de kandidaat")
    p.add_argument("--uit", required=True)
    p.add_argument("--naam-a", default="baseline")
    p.add_argument("--naam-b", default="kandidaat")
    p.add_argument("--casus", action="append")
    p.add_argument("--repo", required=True)
    p.add_argument("--ref-a", required=True)
    p.add_argument("--ref-b", required=True)
    p.add_argument("--normen-a", help="toets_oplevering.md van ToetsOplevering.ps1 op de baseline-run")
    p.add_argument("--normen-b", help="toets_oplevering.md van ToetsOplevering.ps1 op de kandidaat-run")
    p.add_argument("--log", help="toetslog.csv van de branch: de ketting wordt eruit gelezen en de acceptatie komt erbij")
    p.add_argument("--html")
    p.add_argument("--samenvatting", default="")
    a = p.parse_args()
    sys.stdout.reconfigure(encoding="utf8", errors="replace")
    casussen = a.casus or ["WLO_hoog_BAU"]
    rapport, kern = bouw(a.a, a.b, a.naam_a, a.naam_b, casussen, a.repo, a.ref_a, a.ref_b, a.normen_a, a.normen_b, a.log, a.samenvatting)
    Path(a.uit).parent.mkdir(parents=True, exist_ok=True)
    Path(a.uit).write_text(rapport, encoding="utf8")
    print(kern["oordeel"])
    print(f"rapport: {a.uit}")
    if a.html:
        from Toetslog import rapportpagina
        Path(a.html).write_text(rapportpagina(rapport, f"Acceptatie {a.naam_b}"), encoding="utf8")
    if a.log:
        from Toetslog import schrijf_logregel
        schrijf_logregel(a.log, a.naam_a, kern["datum_a"], a.naam_b, kern["datum_b"], kern["commits"], kern["samenvatting"], kern["oordeel"],
                         kern["tifs_anders"], kern["tifs_totaal"], kern["checks_anders"], kern["checks_totaal"], a.uit)
        print(f"log: {a.log}")


if __name__ == "__main__":
    sys.exit(main())
