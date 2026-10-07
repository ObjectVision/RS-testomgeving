"""Het profiel van een run: de stand van alle instellingen als csv, en het opleggen ervan op een werkkopie.

Gebruik:
    python Profiel.py dump  --uit <csv> [--repo <pad>] [--ref <commit>] [--map <werkkopie>] [--env K=V ...]
    python Profiel.py apply <profiel.csv> [<nog een profiel.csv> ...] --map <werkkopie> [--verslag <md>]

Waarvoor: de enginetoets uit model-RSopen#16 vergelijkt twee commits onder dezelfde instellingen en
dezelfde data, zodat elk verschil in de uitkomst van de rekenwijze komt. Dit script legt die
instellingen vast (dump) en legt ze op een wegwerpkopie van een andere commit (apply). Een profiel is
een csv met per instelling het pad onder de hoofdcontainer en de waarde zoals hij in de dms staat;
daar vallen de scalaire parameters onder en de literal-arrays zoals de sectortabel en de kolommen van
VariantK. Een instelling die via een omgevingsvariabele wordt gezet houdt haar expressie en krijgt een
eigen rij env:<naam> met de waarde die de run gebruikte; apply schrijft die rijen naar omgeving.csv
naast het verslag, en het runscript zet ze in de omgeving.

Bij apply wint het laatste profiel: het baselineprofiel eerst, het testprofiel erachter. Een instelling
uit het profiel die de werkkopie niet kent wordt gemeld en overgeslagen; een instelling van de
werkkopie die niet in het profiel staat houdt haar default en wordt als nieuw gemeld, want die hoort
bij de wijziging die getoetst wordt.

De sectortabel is de uitzondering op de regel dat een waarde los te vervangen is: het aantal rijen
staat ook in de range van de unit SectorAllocRegio, en apply zet dat getal mee. Dat is wat overrides.py
in RS-testomgeving met een regex deed, hier voor alle instellingen tegelijk.

Schrijft in bytes terug, zodat de regeleindes CRLF blijven en er geen BOM bij komt.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from VergelijkCommits import (ENVWAARDE, is_instelling, lees_parameters_van, lezer_git, lezer_map, rekenvorm,  # noqa: E402
                              netjes, paar)

SECTORTABEL = "ModelParameters/SectorAllocRegio/Elements/Text"
SECTORRANGE = re.compile(r"(unit\s*<\s*UInt8\s*>\s+SectorAllocRegio\s*:=\s*range\s*\(\s*uint8\s*,\s*0b\s*,\s*)(\d+)(b\s*\))",
                         re.IGNORECASE)
NRATTR = re.compile(r"\bnrAttr\s*:=\s*(\d+)")
LITERAAL = re.compile(r"'[^']*'")


def instellingen(gevonden):
    return {s: w for s, w in gevonden.items() if is_instelling(s)}


def dump(lezer, omgeving, uit):
    """Schrijft alle instellingen als csv; de omgevingsvariabelen als rijen env:<naam> erachter."""
    gevonden, _ = lees_parameters_van(lezer)
    inst = instellingen(gevonden)
    envs = {}
    for pad, w in inst.items():
        m = ENVWAARDE.search(w["waarde"])
        if m:
            envs[m.group(1)] = omgeving.get(m.group(1), m.group(2))
    Path(uit).parent.mkdir(parents=True, exist_ok=True)
    with open(uit, "w", newline="", encoding="utf8") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["pad", "waarde", "type", "bestand"])
        for pad in sorted(inst):
            w = inst[pad]
            wr.writerow([pad, w["waarde"], w["type"], w["bestand"]])
        for naam in sorted(envs):
            wr.writerow([f"env:{naam}", envs[naam], "omgeving", ""])
    return len(inst), len(envs)


VOLLEDIG_VANAF = 100  # een profiel met minder rijen is een overlay zoals het testprofiel, geen volledige stand


def lees_profielen(paden):
    """Voegt profielen samen; een latere rij voor hetzelfde pad wint. Zegt ook of er een volledig
    profiel bij zat, want alleen dan betekent een instelling buiten het profiel iets."""
    profiel, omgeving, volledig, herkomst = {}, {}, False, {}
    for p in paden:
        rijen = 0
        with open(p, newline="", encoding="utf8") as f:
            for rij in csv.DictReader(f, delimiter=";"):
                pad = (rij.get("pad") or "").strip()
                waarde = (rij.get("waarde") or "").strip()
                if pad.startswith("env:"):
                    omgeving[pad[4:]] = waarde
                elif pad.startswith("run:"):
                    continue  # een runparameter voor Toets.ps1 (bijvoorbeeld run:Varianten), geen instelling in cfg
                elif pad:
                    profiel[pad] = waarde
                    herkomst[pad] = str(p)
                    rijen += 1
        volledig = volledig or rijen >= VOLLEDIG_VANAF
    return profiel, omgeving, volledig, herkomst


def sectorrange_bijwerken(tekst, nieuw):
    """Zet de range van SectorAllocRegio op het aantal rijen van de nieuwe tabel."""
    m = NRATTR.search(tekst)
    nr_attr = int(m.group(1)) if m else 6
    literalen = len(LITERAAL.findall(nieuw))
    if literalen % nr_attr:
        raise SystemExit(f"de sectortabel heeft {literalen} literalen en dat is geen veelvoud van nrAttr {nr_attr}")
    rijen = literalen // nr_attr
    tekst, n = SECTORRANGE.subn(lambda r: f"{r.group(1)}{rijen}{r.group(3)}", tekst)
    if n != 1:
        raise SystemExit("de range van SectorAllocRegio is niet gevonden, de sectortabel is niet aangepast")
    return tekst, rijen


def apply(profielen, werkmap, verslag):
    profiel, omgeving, volledig, herkomst = lees_profielen(profielen)
    werkmap = Path(werkmap)
    gevonden, teksten = lees_parameters_van(lezer_map(werkmap))
    huidig = instellingen(gevonden)

    # Wat uit het baselineprofiel komt wordt niet blind opgelegd. Een tabel waarvan de kolomindeling in
    # deze commit anders is (nrAttr verschilt) is structuur die bij de code hoort en geen knop; een _ref
    # noemt een kolom of element in de code en volgt die code; een tekstwaarde die in de code van deze
    # commit nergens meer voorkomt (een optie, een leveringsdatum) is geen geldige stand meer. Die drie
    # blijven op de waarde van de commit en het verslag en het rapport melden het. Het testprofiel (het
    # laatste profiel) is daarvan uitgezonderd: dat zegt expliciet wat de toets wil.
    laatste = str(profielen[-1])
    code = "".join(rekenvorm(t) for t in teksten.values())
    structuur = {pad.rsplit("/", 1)[0] + "/" for pad, nieuw in profiel.items()
                 if pad.endswith("/nrAttr") and pad in huidig and netjes(huidig[pad]["waarde"]) != netjes(nieuw)}

    per_bestand, overschreven, gelijk, onbekend, niet_opgelegd = {}, [], [], [], []
    for pad, nieuw in profiel.items():
        w = huidig.get(pad)
        if w is None:
            onbekend.append(pad)
            continue
        if netjes(w["waarde"]) == netjes(nieuw):
            gelijk.append(pad)
            continue
        if herkomst.get(pad) != laatste:
            if any(pad.startswith(s) for s in structuur):
                niet_opgelegd.append((pad, w["waarde"], nieuw, "de kolomindeling van deze tabel is in deze commit anders"))
                continue
            if pad.endswith("_ref"):
                niet_opgelegd.append((pad, w["waarde"], nieuw, "een _ref volgt de code van de commit"))
                continue
            if nieuw.startswith("'") and nieuw.endswith("'") and nieuw not in code:
                niet_opgelegd.append((pad, w["waarde"], nieuw, "deze waarde komt in de code van deze commit niet meer voor"))
                continue
        per_bestand.setdefault(w["bestand"], []).append((w["span"][0], w["span"][1], nieuw, pad))
        overschreven.append((pad, w["waarde"], nieuw, w["bestand"]))
    nieuw_in_kopie = sorted(set(huidig) - set(profiel)) if volledig else []

    sectorrijen = None
    for bestand, lijst in per_bestand.items():
        tekst = teksten[bestand]
        for start, eind, nieuw, pad in sorted(lijst, reverse=True):
            # Een parameterwaarde begint direct na :=, een array direct na [; de spatie na := blijft.
            vervanging = nieuw if pad.endswith("/Text") or tekst[start - 1] == "[" else " " + nieuw
            tekst = tekst[:start] + vervanging + tekst[eind:]
        if any(pad == SECTORTABEL for _, _, _, pad in lijst):
            tekst, sectorrijen = sectorrange_bijwerken(tekst, profiel[SECTORTABEL])
        (werkmap / bestand).write_bytes(tekst.encode("utf8"))

    verslag = Path(verslag) if verslag else werkmap / "batch" / "log" / "profiel.md"
    verslag.parent.mkdir(parents=True, exist_ok=True)
    with open(verslag.parent / "omgeving.csv", "w", newline="", encoding="utf8") as f:
        wr = csv.writer(f, delimiter=";")
        wr.writerow(["naam", "waarde"])
        for naam in sorted(omgeving):
            wr.writerow([naam, omgeving[naam]])

    r = ["# Profiel opgelegd", ""]
    r.append("Profielen, in volgorde van toepassing (de laatste wint): " + ", ".join(str(p) for p in profielen))
    r.append(f"Werkkopie: {werkmap}")
    r.append("")
    r.append(f"Overschreven {len(overschreven)}, al gelijk {len(gelijk)}, niet opgelegd {len(niet_opgelegd)}, onbekend in de werkkopie {len(onbekend)}, "
             f"nieuw in de werkkopie {len(nieuw_in_kopie)}, omgevingsvariabelen {len(omgeving)}.")
    if sectorrijen is not None:
        r.append(f"De sectortabel is vervangen en de range van SectorAllocRegio staat op {sectorrijen} rijen.")
    if not volledig:
        r.append("Geen volledig profiel opgelegd, alleen een overlay; de overige instellingen staan zoals de commit ze heeft "
                 "en zijn niet tegen een baseline gelegd.")
    r.append("")
    if overschreven:
        r.append("## Overschreven")
        r.append("")
        for pad, oud, nieuw, bestand in overschreven:
            r.append(f"- {pad} ({bestand}): {netjes(oud)[:80]} -> {netjes(nieuw)[:80]}")
        r.append("")
    if niet_opgelegd:
        r.append("## Niet opgelegd")
        r.append("")
        r.append("Deze instellingen staan anders in het profiel, maar blijven op de waarde van de commit; de reden staat erbij.")
        r.append("")
        for pad, oud, nieuw, reden in niet_opgelegd:
            r.append(f"- {pad}: {netjes(nieuw)[:60]} (profiel) blijft {netjes(oud)[:60]}; {reden}")
        r.append("")
    if onbekend:
        r.append("## In het profiel maar niet in de werkkopie")
        r.append("")
        r.append("Deze instellingen bestaan in deze commit niet meer; ze zijn overgeslagen.")
        r.append("")
        for pad in onbekend:
            r.append(f"- {pad}")
        r.append("")
    if nieuw_in_kopie:
        r.append("## In de werkkopie maar niet in het profiel")
        r.append("")
        r.append("Nieuwe instellingen; ze houden hun default en horen bij de wijziging die getoetst wordt.")
        r.append("")
        for pad in nieuw_in_kopie:
            r.append(f"- {pad} = {netjes(huidig[pad]['waarde'])[:100]}")
        r.append("")
    if omgeving:
        r.append("## Omgeving")
        r.append("")
        for naam in sorted(omgeving):
            r.append(f"- {naam} = {omgeving[naam]}")
        r.append("")
    verslag.write_text("\n".join(r), encoding="utf8")
    return verslag, len(overschreven), len(onbekend), len(nieuw_in_kopie), len(niet_opgelegd)


def main():
    p = argparse.ArgumentParser(description="Het profiel van een run: dumpen en opleggen.")
    sub = p.add_subparsers(dest="actie", required=True)
    d = sub.add_parser("dump", help="schrijf de instellingen van een commit of werkkopie als csv")
    d.add_argument("--uit", required=True)
    d.add_argument("--repo", default=str(Path.cwd()), help="werkkopie van het model; standaard de huidige map")
    d.add_argument("--ref")
    d.add_argument("--map")
    d.add_argument("--env", action="append", metavar="K=V")
    a = sub.add_parser("apply", help="leg een of meer profielen op een werkkopie")
    a.add_argument("profielen", nargs="+")
    a.add_argument("--map", required=True)
    a.add_argument("--verslag")
    n = sub.add_parser("namen", help="de literalen van een array in de configuratie, een per regel")
    n.add_argument("--map", required=True)
    n.add_argument("--pad", required=True, help="bijvoorbeeld Diagnose/Checks/name")
    args = p.parse_args()

    sys.stdout.reconfigure(encoding="utf8", errors="replace")
    if args.actie == "namen":
        gevonden, _ = lees_parameters_van(lezer_map(args.map))
        w = gevonden.get(args.pad)
        if w is None:
            raise SystemExit(f"{args.pad} niet gevonden in {args.map}")
        for naam in LITERAAL.findall(w["waarde"]):
            print(naam.strip("'"))
        return
    if args.actie == "dump":
        if bool(args.ref) == bool(args.map):
            raise SystemExit("geef precies een van --ref en --map")
        lezer = lezer_git(Path(args.repo), args.ref) if args.ref else lezer_map(args.map)
        n, e = dump(lezer, paar(args.env), args.uit)
        print(f"profiel: {args.uit} ({n} instellingen, {e} omgevingsvariabelen)")
    else:
        for pr in args.profielen:
            if not Path(pr).is_file():
                raise SystemExit(f"profiel niet gevonden: {pr}")
        verslag, n, onbekend, nieuw, niet = apply(args.profielen, args.map, args.verslag)
        print(f"verslag: {verslag} ({n} overschreven, {niet} niet opgelegd, {onbekend} onbekend, {nieuw} nieuw)")


if __name__ == "__main__":
    sys.exit(main())
