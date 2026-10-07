"""Vergelijkt twee commits van deze configuratie en zegt wat er is veranderd, zonder te rekenen.

Gebruik:
    python VergelijkCommits.py <commit A> <commit B> [opties]

Opties:
    --repo <pad>       werkkopie van het model waarin beide commits staan; default de huidige map
    --env-a k=v        omgevingsvariabele waarmee run A draaide; meerdere keren toegestaan
    --env-b k=v        idem voor run B
    --md <pad>         schrijf het rapport als markdown; default naar het scherm
    --csv <pad>        schrijf de parametertabel als csv
    --alles            toon ook de parameters die gelijk zijn gebleven

Waarvoor: een run kost uren, dus je wilt weten wat er te verwachten valt voordat je er twee start.
Dit script leest beide commits als tekst en deelt elke gewijzigde regel in bij brondata, parameter,
engine of meting. Die vier vragen elk ander bewijs. Een parameterwijziging staat hieronder als tabel
met oude en nieuwe waarde en is daarmee al verklaard; alleen een engine-wijziging vraagt om een run om
haar effect te kennen. Eerste trap van model-RSopen#16: pas wanneer het gemeten verschil groter is dan
wat deze tabel verklaart, is bisecten de moeite waard, en dan staan de kandidaat-commits er al bij.

De parameterstand staat maar deels in de commit. Acht parameters krijgen hun waarde via
replace_value(expand(., '%env:X%'), ...) pas van het batchscript dat de run start, en een diff van de
twee commits kan die per definitie niet tonen. Met --env-a en --env-b geef je beide omgevingen mee,
zodat de tabel de werkelijke stand van beide runs geeft en niet alleen de default uit de tekst.

Leest de commits via `git show` en raakt de werkkopie niet aan, dus het kan naast een lopende run.
"""

import argparse
import bisect
import csv
import re
import subprocess
import sys
from pathlib import Path

HOOFDBESTAND = "cfg/main.dms"

KOP = re.compile(r"(?:container|template|unit\s*<[^>]*>)\s+([A-Za-z_]\w*)", re.IGNORECASE)
PARAM = re.compile(r"\bparameter\s*<\s*([^>]+?)\s*>\s+([A-Za-z_]\w*)\s*:=", re.IGNORECASE)
# Een literal-array als instelling: de sectortabel SectorAllocRegio/Elements/Text, de kolommen van
# VariantK en het productieprofiel van de preflight zijn allemaal van deze vorm, en een wijziging erin
# stuurt de uitkomst net zo hard als een scalaire parameter.
ARRAY = re.compile(r"\battribute\s*<\s*([^>]+?)\s*>\s+([A-Za-z_]\w*)\s*(?:\([^)]*\))?\s*:\s*\[", re.IGNORECASE)
INCLUDE = re.compile(r"#include\s*<([^>]+)>", re.IGNORECASE)
ENVWAARDE = re.compile(
    r"replace_value\s*\(\s*expand\s*\(\s*\.\s*,\s*'%env:(\w+)%'\s*\)\s*,\s*'env:\1'\s*,\s*'([^']*)'\s*\)",
    re.IGNORECASE,
)

# Welke klasse hoort bij een gewijzigde regel. De regel zelf wint van het bestand: een parameterregel
# in een sjabloonbestand is een parameterwijziging, en een StorageName in een parameterbestand wijst
# naar een levering. Pas als de regel niets prijsgeeft beslist het pad.
# De meetkant: Diagnose, de indicatoren en hun sjablonen, de export en de preflight. De allocatie leest
# niets uit /Indicatoren (de twee verwijzingen in Templates/Allocatie en VariantData_T zijn Descr-tekst),
# dus een wijziging hier verandert de controlewaarden en de export, maar niet de stand.
METINGPADEN = (
    "cfg/main/Diagnose",
    "cfg/main/Indicatoren",
    "cfg/main/Templates/Indicatoren",
    "cfg/main/PostAllocAnalyses",
    "cfg/main/ExportSettings.dms",
    "cfg/main/Preflight",
)
BRONPADEN = ("cfg/main/SourceData", "cfg/main/PrivData")
PARAMPADEN = ("cfg/main/ModelParameters", "cfg/main/VariantParameters")
# De Write*-bestanden zeggen welke rekenstap wat wegschrijft (lijsten van ExplicitSuppliers); de rekenregels staan elders.
ORKESTRATIEPADEN = ("cfg/main/WriteBasedata.dms", "cfg/main/WriteVariantData.dms", "cfg/main/WritePrivData.dms")

KLASSEN = ("bron", "parameter", "engine", "orkestratie", "meting", "toelichting", "buiten")
TOELICHTING = re.compile(r"[,:]?\s*(?:Descr|Source)\s*=\s*$", re.IGNORECASE)


def git(repo, *args):
    r = subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True,
                       encoding="utf8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def toon(repo, ref, pad):
    """De inhoud van een bestand op een commit, of None als het daar niet bestaat."""
    try:
        return git(repo, "show", f"{ref}:{pad}")
    except RuntimeError:
        return None


def ontleed_tekst(tekst):
    """Geeft een masker met alleen code, plus de posities van de stringliteralen.

    Het masker is even lang als de tekst; elk teken dat in een string of een commentaar staat is
    vervangen door een spatie. Zo blijven de indices gelijk aan die van het origineel en struikelt
    geen regex over een puntkomma in een Descr of een accolade in een commentaar. Dat is geen
    theoretisch geval: Diagnose.dms heeft alleen al 87 regels met een puntkomma in een string.
    """
    masker, strings, commentaren = [], [], []
    i, n = 0, len(tekst)
    while i < n:
        c = tekst[i]
        d = tekst[i + 1] if i + 1 < n else ""
        if c == "/" and d == "/":
            j = tekst.find("\n", i)
            j = n if j < 0 else j
            commentaren.append((i, j))
        elif c == "/" and d == "*":
            j = tekst.find("*/", i + 2)
            j = n if j < 0 else j + 2
            commentaren.append((i, j))
        elif c in "'\"":
            j = tekst.find(c, i + 1)
            j = n if j < 0 else j + 1
            strings.append((i, j))
        else:
            masker.append(c)
            i += 1
            continue
        masker.append(" " * (j - i))
        i = j
    return "".join(masker), strings, commentaren


def containertijdlijn(masker):
    """Per structuurteken de containerstapel die daarna geldt, zodat elk item zijn pad kent."""
    tijdlijn = [(0, ())]
    stapel, grens = [], -1
    for m in re.finditer(r"[{};]", masker):
        pos, teken = m.start(), m.group()
        if teken == "{":
            treffers = KOP.findall(masker[grens + 1:pos])
            stapel.append(treffers[-1] if treffers else "?")
        elif teken == "}" and stapel:
            stapel.pop()
        grens = pos
        tijdlijn.append((pos + 1, tuple(stapel)))
    return tijdlijn, [t[0] for t in tijdlijn]


def pad_op(tijdlijn, sleutels, pos):
    i = bisect.bisect_right(sleutels, pos) - 1
    return tijdlijn[max(i, 0)][1]


def eerste_komma(masker, start, eind):
    """De komma die de waarde van de eigenschappen scheidt, op haakjesdiepte nul."""
    diepte = 0
    for i in range(start, eind):
        c = masker[i]
        if c in "([":
            diepte += 1
        elif c in ")]":
            diepte -= 1
        elif c == "," and diepte == 0:
            return i
    return eind


def eigenschap(tekst, masker, strings, start, eind, naam):
    m = re.search(rf"\b{naam}\s*=", masker[start:eind], re.IGNORECASE)
    if not m:
        return None
    p = start + m.end()
    for s, e in strings:
        if s >= eind:
            break
        if s >= p:
            return tekst[s + 1:e - 1]
    return None


def netjes(s):
    return re.sub(r"\s+", " ", s).strip()


def zonder_commentaar(tekst, commentaren, start, eind):
    """De oorspronkelijke tekst van een span, met het commentaar eruit geknipt.

    Nodig omdat het commentaar achter een waarde voor de puntkomma staat en anders in de tabel
    terechtkomt: de waarde van PlancapStartStateFileName sleepte zo zijn hele toelichting mee.
    """
    stukken, cursor = [], start
    for s, e in commentaren:
        if e <= start or s >= eind:
            continue
        stukken.append(tekst[cursor:max(s, cursor)])
        cursor = max(cursor, e)
    stukken.append(tekst[cursor:eind])
    return netjes("".join(stukken))


def rekenvorm(tekst):
    """De vorm van een bestand die de uitkomst bepaalt: zonder commentaar, Descr en Source.

    Twee versies met dezelfde rekenvorm rekenen hetzelfde, hoe groot de diff ook is. Dat scheelt een
    run: een commit die alleen toelichting verzet, zoals het anonimiseren van persoonsnamen, kan de
    allocatie niet verplaatsen en hoeft dus ook geen kandidaat te zijn om op te bisecten.
    """
    masker, strings, commentaren = ontleed_tekst(tekst)
    weg = list(commentaren)
    i = 0
    while i < len(strings):
        s, e = strings[i]
        # De hele eigenschap moet weg, inclusief de komma en de naam ervoor: een verwijderde Descr
        # laat anders ", Descr =" achter als verschil en verandert de rekenvorm alsnog.
        venster_start = max(0, s - 60)
        m = TOELICHTING.search(masker[venster_start:s])
        if not m:
            i += 1
            continue
        # Een Source staat vaak als losse regels naast elkaar; aangrenzende literalen horen erbij.
        while i + 1 < len(strings) and not masker[e:strings[i + 1][0]].strip():
            i += 1
            e = strings[i][1]
        weg.append((venster_start + m.start(), e))
        i += 1
    stukken, cursor = [], 0
    for s, e in sorted(weg):
        stukken.append(tekst[cursor:max(s, cursor)])
        cursor = max(cursor, e)
    stukken.append(tekst[cursor:])
    # Zonder BOM en zonder witruimte: GeoDMS leest 'x:=' en 'x :=' als hetzelfde, en een commit die
    # alleen regeleindes, inspringing of een BOM verzet (zoals #801) rekent hetzelfde.
    return re.sub(r"\s+", "", "".join(stukken).lstrip("﻿"))


def lezer_git(repo, ref):
    """Een lezer die bestanden van een commit geeft; None als het bestand daar niet bestaat."""
    return lambda pad: toon(repo, ref, pad)


def lezer_map(werkmap):
    """Een lezer die bestanden van een werkkopie geeft, in bytes gedecodeerd zodat de posities van
    de waarden exact kloppen met wat Profiel.py later terugschrijft; de regeleindes blijven CRLF."""
    def lees(pad):
        p = Path(werkmap) / pad
        return p.read_bytes().decode("utf8") if p.is_file() else None
    return lees


def lees_bestand(lezer, pad, prefix, gevonden, teksten, bezocht):
    """Leest een dms-bestand en volgt zijn includes, met de containerstapel mee.

    Van elke parameter en elke literal-array onthoudt hij naast de waarde ook de positie ervan in
    de tekst (span), zodat een profiel de waarde kan terugschrijven zonder het bestand te ontleden.
    """
    if (pad, prefix) in bezocht:
        return
    bezocht.add((pad, prefix))
    tekst = lezer(pad)
    if tekst is None:
        return
    teksten[pad] = tekst
    masker, strings, commentaren = ontleed_tekst(tekst)
    tijdlijn, sleutels = containertijdlijn(masker)

    for m in PARAM.finditer(masker):
        eind = masker.find(";", m.end())
        eind = len(masker) if eind < 0 else eind
        komma = eerste_komma(masker, m.end(), eind)
        sleutel = "/".join(prefix + pad_op(tijdlijn, sleutels, m.start()) + (m.group(2),))
        gevonden[sleutel] = {
            "type": netjes(m.group(1)),
            "waarde": zonder_commentaar(tekst, commentaren, m.end(), komma),
            "descr": eigenschap(tekst, masker, strings, komma, eind, "Descr"),
            "bestand": pad,
            "regel": tekst.count("\n", 0, m.start()) + 1,
            "span": (m.end(), komma),
        }

    for m in ARRAY.finditer(masker):
        eind = masker.find("]", m.end())
        if eind < 0:
            continue
        sleutel = "/".join(prefix + pad_op(tijdlijn, sleutels, m.start()) + (m.group(2),))
        gevonden[sleutel] = {
            "type": "array<" + netjes(m.group(1)) + ">",
            "waarde": zonder_commentaar(tekst, commentaren, m.end(), eind),
            "descr": None,
            "bestand": pad,
            "regel": tekst.count("\n", 0, m.start()) + 1,
            "span": (m.end(), eind),
        }

    basis = Path(pad)
    map_van_includes = basis.parent / basis.stem
    for m in INCLUDE.finditer(masker):
        kind = (map_van_includes / m.group(1).strip()).as_posix()
        lees_bestand(lezer, kind, prefix + pad_op(tijdlijn, sleutels, m.start()), gevonden, teksten, bezocht)


def lees_parameters_van(lezer):
    """Alle parameters en literal-arrays die een lezer geeft, met hun pad zonder de hoofdcontainer,
    plus de teksten van de gelezen bestanden.

    Die hoofdcontainer niet hardcoderen: hij heet op de ene commit RSopen en op de andere
    RSopen_NL2120, en met een vaste naam lijkt na zo'n hernoeming elke instelling nieuw.
    """
    gevonden, teksten = {}, {}
    lees_bestand(lezer, HOOFDBESTAND, (), gevonden, teksten, set())
    wortels = {s.split("/", 1)[0] for s in gevonden}
    if len(wortels) == 1:
        n = len(wortels.pop()) + 1
        gevonden = {s[n:]: w for s, w in gevonden.items() if len(s) > n}
    return gevonden, teksten


def lees_parameters(repo, ref):
    return lees_parameters_van(lezer_git(repo, ref))[0]


def effectief(waarde, omgeving):
    """De waarde die de run werkelijk gebruikt, met de omgevingsvariabele erin verwerkt."""
    m = ENVWAARDE.search(waarde or "")
    if not m:
        return waarde, ""
    naam, default = m.group(1), m.group(2)
    if naam in omgeving:
        return omgeving[naam], f"env:{naam}"
    return default, f"env:{naam} niet gezet"


def klasse_van(pad, regel):
    """De klasse van een gewijzigde regel; het pad beslist, de inhoud corrigeert.

    Een parameterregel telt alleen als instelling wanneer hij onder ModelParameters of
    VariantParameters staat. Elders is parameter<> gewoon de vorm waarin een rekenitem van een enkele
    waarde wordt opgeschreven, bijvoorbeeld een bestandsnaam of een som in een sjabloon; dat is
    rekenwerk en geen knop waar iemand aan draait.

    Een regel in WriteBasedata, WriteVariantData of WritePrivData is orkestratie: hij verdeelt het
    schrijfwerk over de rekenstappen en hoort de uitkomst niet te veranderen, maar hij kan het wel
    wanneer een stap daardoor iets anders wegschrijft of leest. Daarom apart van de rekenwijze.
    """
    inhoud = regel[1:]
    if not pad.startswith("cfg/"):
        return "buiten"
    if pad.startswith(ORKESTRATIEPADEN):
        return "orkestratie"
    if pad.startswith(PARAMPADEN):
        return "parameter"
    # Eerst de meetkant: een StorageName in een indicator of export is een schrijver, geen invoer.
    if pad.startswith(METINGPADEN):
        return "meting"
    if "StorageName" in inhoud or "StorageType" in inhoud:
        return "bron"
    if pad.startswith(BRONPADEN):
        return "bron"
    if pad.startswith("cfg/"):
        return "engine"
    return "buiten"


def is_instelling(sleutel):
    return sleutel.startswith(("ModelParameters/", "VariantParameters/"))


DIFFKOP = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')


def tel_diff_tekst(uitvoer):
    """Per bestand het aantal gewijzigde regels per klasse uit een unified diff, plus de gewijzigde storageregels.

    De bestandsnaam komt van de `diff --git`-regel en niet van `+++ b/`, want bij een verwijderd
    bestand staat daar /dev/null en zouden de regels op het vorige bestand worden bijgeteld.
    Contextregels beginnen met een spatie en tellen niet mee, dus een patch met context geeft
    dezelfde telling als een diff zonder.
    """
    per_bestand, storages, huidig = {}, [], None
    for regel in uitvoer.splitlines():
        kop = DIFFKOP.match(regel)
        if kop:
            huidig = kop.group(2) if kop.group(2) != "dev/null" else kop.group(1)
            per_bestand.setdefault(huidig, dict.fromkeys(KLASSEN, 0))
        elif huidig and regel[:1] in "+-" and not regel.startswith(("+++", "---")):
            if not regel[1:].strip():
                continue
            klasse = klasse_van(huidig, regel)
            per_bestand[huidig][klasse] += 1
            if "StorageName" in regel and huidig.startswith("cfg/"):
                storages.append((regel[0], huidig, netjes(regel[1:])))
    return {p: t for p, t in per_bestand.items() if sum(t.values())}, storages


def tel_diff(repo, ref_a, ref_b):
    return tel_diff_tekst(git(repo, "diff", "--unified=0", "--no-color", f"{ref_a}..{ref_b}"))


def verfijn(lezer_a, lezer_b, per_bestand):
    """Schuift bestanden waarvan alleen de toelichting veranderde naar de klasse toelichting.

    Een dms-bestand waarvan de rekenvorm aan beide kanten gelijk is rekent hetzelfde, ook al telt de
    diff honderden regels. Zonder deze stap belandt een commit die Descr-teksten herschrijft in de
    lijst met kandidaten om op te bisecten, en dat is een uur rekenen voor niets. De kanten zijn
    lezers (lezer_git of lezer_map), zodat dit ook werkt voor een patch op een kopie.
    """
    for pad, tellingen in per_bestand.items():
        if pad.endswith(".example"):
            per_bestand[pad] = dict.fromkeys(KLASSEN, 0) | {"buiten": sum(tellingen.values())}
            continue
        if not (pad.startswith("cfg/") and pad.endswith(".dms")):
            continue
        a, b = lezer_a(pad), lezer_b(pad)
        if a is None or b is None:
            continue
        if rekenvorm(a) == rekenvorm(b):
            per_bestand[pad] = dict.fromkeys(KLASSEN, 0) | {"toelichting": sum(tellingen.values())}
    return per_bestand


OORDELEN = (
    ("engine",      "raakt de rekenwijze"),
    ("orkestratie", "verdeelt het schrijfwerk anders over de rekenstappen"),
    ("parameter",   "verandert instellingen"),
    ("bron",        "verandert de invoerkant"),
    ("meting",      "indicatoren en export"),
    ("toelichting", "toelichting"),
    ("buiten",      "buiten de configuratie"),
)


def kort_bestand(pad):
    """Een leesbare naam voor een configuratiebestand: Grondproductiekosten/T.dms heet Grondproductiekosten."""
    p = Path(pad)
    return p.parent.name if p.stem == "T" else p.stem


def commits_tussen(repo, ref_a, ref_b):
    """Elke commit tussen A en B met een oordeel in gewone taal over wat hij raakt.

    Per commit de diff tegen zijn eerste ouder, ingedeeld zoals tel_diff en met de rekenvorm verfijnd,
    zodat een commit die alleen Descr-tekst herschrijft "alleen toelichting" heet en een commit in een
    indicatorsjabloon "alleen indicatoren en export". Mergecommits blijven weg: hun inhoud staat al bij de
    commits die ze samenvoegen.
    """
    uit = []
    regels = git(repo, "log", "--no-merges", "--reverse", "--format=%h%x09%cs%x09%s", f"{ref_a}..{ref_b}").splitlines()
    for regel in regels:
        if not regel.strip():
            continue
        sha, datum, onderwerp = regel.split("\t", 2)
        per_bestand, _ = tel_diff_tekst(git(repo, "diff", "--unified=0", "--no-color", f"{sha}^..{sha}"))
        per_bestand = verfijn(lezer_git(repo, f"{sha}^"), lezer_git(repo, sha), per_bestand)
        totaal = tel_totaal(per_bestand)
        labels = [tekst for klasse, tekst in OORDELEN if totaal[klasse]]
        if len(labels) == 1 and labels[0] in ("indicatoren en export", "toelichting", "buiten de configuratie"):
            labels = ["alleen " + labels[0]]
        engine = sorted((p for p, t in per_bestand.items() if t["engine"]), key=lambda p: -per_bestand[p]["engine"])
        instellingen = sorted(p for p, t in per_bestand.items() if t["parameter"])
        uit.append({"sha": sha, "datum": datum, "onderwerp": onderwerp, "labels": labels, "totaal": totaal,
                    "engine": engine, "instellingen": instellingen, "per_bestand": per_bestand})
    return uit


def commits_per_bestand(repo, ref_a, ref_b, pad):
    uitvoer = git(repo, "log", "--oneline", "--no-decorate", f"{ref_a}..{ref_b}", "--", pad)
    return [r for r in uitvoer.splitlines() if r.strip()]


def tabel(kop, rijen):
    if not rijen:
        return []
    breedtes = [max(len(str(r[i])) for r in [kop, *rijen]) for i in range(len(kop))]
    streep = "|" + "|".join("-" * (b + 2) for b in breedtes) + "|"
    regels = ["| " + " | ".join(str(k).ljust(b) for k, b in zip(kop, breedtes)) + " |", streep]
    for r in rijen:
        regels.append("| " + " | ".join(str(c).ljust(b) for c, b in zip(r, breedtes)) + " |")
    return regels


def kort(tekst, lengte=110):
    """De eerste zin, afgekapt. Geen unicode-beletselteken: de Windows-console maakt daar een vraagteken van."""
    if not tekst:
        return ""
    eerste = netjes(tekst).split(". ")[0]
    return eerste if len(eerste) <= lengte else eerste[:lengte - 3] + "..."


def meervoud(aantal, enkel, meer):
    return f"{aantal} {enkel if aantal == 1 else meer}"


AFWEZIG = "(bestaat niet)"


def scheid_verplaatsingen(verschillen):
    """Haalt de instellingen eruit die alleen van container zijn gewisseld.

    Een instelling die van ModelParameters/Advanced naar ModelParameters/Koolstof verhuist staat
    anders twee keer in de tabel, als verdwenen en als nieuw, terwijl er niets aan de waarde
    verandert. Over een reeks van honderd commits verdrinkt de echte wijziging daarin.
    """
    weg = {}
    for v in verschillen:
        if v["b"] == AFWEZIG:
            weg.setdefault((v["pad"].rsplit("/", 1)[-1], v["a"]), []).append(v)
    echt, verplaatst, gebruikt = [], [], set()
    for v in verschillen:
        if v["a"] == AFWEZIG:
            kandidaten = weg.get((v["pad"].rsplit("/", 1)[-1], v["b"]), [])
            vrij = [k for k in kandidaten if id(k) not in gebruikt]
            if vrij:
                gebruikt.add(id(vrij[0]))
                verplaatst.append((vrij[0]["pad"], v["pad"], v["b"]))
                continue
        echt.append(v)
    return [v for v in echt if id(v) not in gebruikt], verplaatst


def vergelijk_instellingen(params_a, params_b, env_a, env_b, alles):
    """De instellingentabel: per instelling de effectieve waarde aan beide kanten, en wat er afwijkt."""
    verschillen, rekenitems, gelijk = [], 0, 0
    for sleutel in sorted(set(params_a) | set(params_b)):
        ia, ib = params_a.get(sleutel), params_b.get(sleutel)
        wa, bron_a = effectief(ia["waarde"], env_a) if ia else (AFWEZIG, "")
        wb, bron_b = effectief(ib["waarde"], env_b) if ib else (AFWEZIG, "")
        anders = wa != wb or bron_a != bron_b
        if not is_instelling(sleutel):
            rekenitems += 1 if anders else 0
            continue
        if not anders:
            gelijk += 1
            if not alles:
                continue
        verschillen.append({
            "pad": sleutel, "a": wa, "b": wb, "bron_a": bron_a, "bron_b": bron_b,
            "descr": (ib or ia).get("descr"), "type": (ib or ia).get("type"),
        })
    instellingen_totaal = sum(1 for s in params_b if is_instelling(s))
    instellingen_totaal = sum(1 for s in params_b if is_instelling(s))
    verschillen, verplaatst = scheid_verplaatsingen(verschillen)
    return verschillen, verplaatst, rekenitems, instellingen_totaal


def tel_totaal(per_bestand):
    totaal = dict.fromkeys(KLASSEN, 0)
    for tellingen in per_bestand.values():
        for k, v in tellingen.items():
            totaal[k] += v
    return totaal


def render(kop, per_bestand, storages, verschillen, verplaatst, rekenitems, instellingen_totaal, a_kort, b_kort, herkomst):
    """Het rapport als markdown. kop zijn de regels boven de klassentabel; herkomst(pad) geeft per
    bestand de regels die zeggen waar de wijziging vandaan komt: de commits, of dat hij ongecommit is."""
    totaal = tel_totaal(per_bestand)
    r = list(kop)
    r += tabel(["klasse", "regels", "wat het betekent"], [
        ["bron", totaal["bron"], "de invoerkant; een andere levering of een andere manier om haar te lezen"],
        ["parameter", totaal["parameter"], "een andere instelling; leesbaar, zie de tabel hieronder"],
        ["engine", totaal["engine"], "een andere rekenwijze; alleen te kennen uit een run"],
        ["orkestratie", totaal["orkestratie"], "welke rekenstap wat wegschrijft; hoort de uitkomst niet te raken"],
        ["meting", totaal["meting"], "een andere rapportage; raakt de allocatie niet"],
        ["toelichting", totaal["toelichting"], "alleen Descr, Source of commentaar; de rekenvorm is gelijk"],
        ["buiten", totaal["buiten"], "buiten cfg, raakt het model niet"],
    ])
    r.append("")

    r.append("## Advies")
    r.append("")
    if totaal["engine"] == 0 and not verschillen and totaal["bron"] == 0 and totaal["orkestratie"] == 0:
        r.append("Geen wijziging die de uitkomst kan raken. Een run is niet nodig.")
    elif totaal["engine"] == 0 and not verschillen and totaal["bron"] == 0:
        r.append("Alleen de verdeling van het schrijfwerk over de rekenstappen is anders (WriteBasedata, WriteVariantData "
                 "of WritePrivData). Dat hoort de uitkomst niet te raken; een run bevestigt het.")
    elif totaal["engine"] == 0:
        r.append("Geen engine-wijziging. Een verschil in de uitkomst moet volledig te verklaren zijn uit de "
                 "parameters en de leveringen hieronder. Meet je meer, dan klopt er iets niet aan deze indeling "
                 "en is dat zelf het nieuws.")
    else:
        r.append(f"{meervoud(totaal['engine'], 'engine-regel', 'engine-regels')} in "
                 f"{meervoud(sum(1 for t in per_bestand.values() if t['engine']), 'bestand', 'bestanden')}. "
                 "Een run is nodig om het effect te kennen. Bisecten heeft pas zin wanneer het gemeten verschil "
                 "groter is dan wat de tabellen hieronder verklaren; de kandidaat-commits staan er dan al bij.")
    r.append("")

    r.append("## Instellingen")
    r.append("")
    if not verschillen:
        r.append(f"Geen van de {instellingen_totaal} instellingen onder ModelParameters en VariantParameters heeft "
                 "een andere waarde, omgevingsvariabelen meegerekend.")
    else:
        rijen = []
        for v in verschillen:
            a = kort(v["a"], 58) + (f" [{v['bron_a']}]" if v["bron_a"] else "")
            b = kort(v["b"], 58) + (f" [{v['bron_b']}]" if v["bron_b"] else "")
            rijen.append([v["pad"], a, b, kort(v["descr"], 80)])
        r += tabel(["instelling", f"A {a_kort}", f"B {b_kort}", "waarvoor"], rijen)
        r.append("")
        r.append(f"{len(verschillen)} van {instellingen_totaal} instellingen wijkt af; de rest is gelijk.")
    if verplaatst:
        r.append("")
        r.append(f"{meervoud(len(verplaatst), 'instelling is', 'instellingen zijn')} alleen van container "
                 "gewisseld, met dezelfde waarde:")
        for oud, nieuw, waarde in verplaatst:
            r.append(f"  {oud} -> {nieuw} ({kort(waarde, 40)})")
    if rekenitems:
        r.append("")
        r.append(f"Daarnaast {meervoud(rekenitems, 'rekenitem', 'rekenitems')} van een enkele waarde gewijzigd "
                 "buiten ModelParameters en VariantParameters. Dat zijn geen knoppen maar rekenwerk; ze zitten in "
                 "de tellingen hieronder.")
    r.append("")

    if storages:
        r.append("## Leveringen")
        r.append("")
        r.append("Gewijzigde StorageName-regels. Een ander pad of een andere vintage is de invoerkant en vraagt "
                 "geen oordeel over de rekenwijze, alleen de bevestiging dat de levering klopt.")
        r.append("")
        for teken, pad, regel in storages:
            r.append(f"  {teken} {pad}: {kort(regel, 150)}")
        r.append("")

    volgorde = {"engine": 0, "orkestratie": 1, "bron": 2, "parameter": 3, "meting": 4, "toelichting": 5, "buiten": 6}
    for klasse in ("engine", "orkestratie", "bron", "meting"):
        bestanden = sorted((p for p, t in per_bestand.items() if t[klasse]),
                           key=lambda p: -per_bestand[p][klasse])
        if not bestanden:
            continue
        titels = {"engine": "Rekenwijze, alleen te kennen uit een run",
                  "orkestratie": "Verdeling van het schrijfwerk over de rekenstappen",
                  "bron": "Brondata en leveringen",
                  "meting": "Meting en rapportage, raakt de allocatie niet"}
        r.append(f"## {titels[klasse]}")
        r.append("")
        for pad in bestanden:
            tellingen = per_bestand[pad]
            mix = ", ".join(f"{v} {k}" for k, v in sorted(tellingen.items(), key=lambda kv: volgorde[kv[0]]) if v)
            r.append(f"### {pad}")
            r.append(f"{mix}")
            for regel in herkomst(pad):
                r.append(f"  {regel}")
            r.append("")
    return "\n".join(r)


def bouw_rapport(repo, ref_a, ref_b, env_a, env_b, alles):
    a_kort = git(repo, "rev-parse", "--short", ref_a).strip()
    b_kort = git(repo, "rev-parse", "--short", ref_b).strip()
    onderwerp_a = git(repo, "log", "-1", "--format=%s", ref_a).strip()
    onderwerp_b = git(repo, "log", "-1", "--format=%s", ref_b).strip()
    tussen = [r for r in git(repo, "log", "--oneline", "--no-decorate", f"{ref_a}..{ref_b}").splitlines() if r.strip()]

    params_a, params_b = lees_parameters(repo, ref_a), lees_parameters(repo, ref_b)
    per_bestand, storages = tel_diff(repo, ref_a, ref_b)
    per_bestand = verfijn(lezer_git(repo, ref_a), lezer_git(repo, ref_b), per_bestand)
    verschillen, verplaatst, rekenitems, instellingen_totaal = vergelijk_instellingen(params_a, params_b, env_a, env_b, alles)

    kop = [f"# Verschil tussen {a_kort} en {b_kort}", "",
           f"A {a_kort}  {onderwerp_a}", f"B {b_kort}  {onderwerp_b}", "",
           f"{meervoud(len(tussen), 'commit', 'commits')} ertussen, "
           f"{meervoud(len(per_bestand), 'bestand', 'bestanden')} gewijzigd.", ""]
    rapport = render(kop, per_bestand, storages, verschillen, verplaatst, rekenitems, instellingen_totaal, a_kort, b_kort,
                     lambda pad: commits_per_bestand(repo, ref_a, ref_b, pad))
    return rapport, verschillen


def bouw_rapport_werkkopie(repo, ref, kopie, patchpaden, env, alles):
    """Hetzelfde rapport voor wat er ongecommit bovenop een commit ligt: de patches die Toets.ps1 op de
    wegwerpkopie legde, met een momentopname van die kopie van voor het profiel als B-kant voor de
    instellingen en de rekenvorm. Zonder dit zegt het statische deel bij -Werkkopie "0 commits
    ertussen" terwijl de wijziging die getoetst wordt juist in de patch zit."""
    ref_kort = git(repo, "rev-parse", "--short", ref).strip()
    onderwerp = git(repo, "log", "-1", "--format=%s", ref).strip()
    patch = "\n".join(Path(p).read_bytes().decode("utf8", errors="replace") for p in patchpaden)
    params_a = lees_parameters(repo, ref)
    params_b, _ = lees_parameters_van(lezer_map(kopie))
    per_bestand, storages = tel_diff_tekst(patch)
    per_bestand = verfijn(lezer_git(repo, ref), lezer_map(kopie), per_bestand)
    verschillen, verplaatst, rekenitems, instellingen_totaal = vergelijk_instellingen(params_a, params_b, env, env, alles)

    kop = [f"# Ongecommit bovenop {ref_kort}", "",
           f"A {ref_kort}  {onderwerp}", f"B dezelfde commit met de patch erop, momentopname {kopie}", "",
           f"{meervoud(len(per_bestand), 'bestand', 'bestanden')} gewijzigd in "
           + ", ".join(Path(p).name for p in patchpaden) + ".", ""]
    rapport = render(kop, per_bestand, storages, verschillen, verplaatst, rekenitems, instellingen_totaal, ref_kort, "patch",
                     lambda pad: ["  ongecommit, in de patch"])
    return rapport, verschillen


def schrijf_csv(pad, verschillen, a_kort, b_kort):
    with open(pad, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["parameter", f"waarde_{a_kort}", f"bron_{a_kort}", f"waarde_{b_kort}", f"bron_{b_kort}", "descr"])
        for v in verschillen:
            w.writerow([v["pad"], v["a"], v["bron_a"], v["b"], v["bron_b"], netjes(v["descr"] or "")])


def paar(waarden):
    uit = {}
    for w in waarden or []:
        if "=" not in w:
            raise SystemExit(f"omgevingsvariabele zonder isteken: {w}")
        k, v = w.split("=", 1)
        uit[k.strip()] = v.strip()
    return uit


def main():
    p = argparse.ArgumentParser(description="Vergelijkt twee commits van de configuratie zonder te rekenen.")
    p.add_argument("ref_a")
    p.add_argument("ref_b")
    p.add_argument("--repo", default=str(Path.cwd()))
    p.add_argument("--env-a", action="append", metavar="K=V")
    p.add_argument("--env-b", action="append", metavar="K=V")
    p.add_argument("--md")
    p.add_argument("--csv")
    p.add_argument("--alles", action="store_true")
    a = p.parse_args()

    # De Descr's staan vol accenten; zonder dit maakt de Windows-console er vraagtekens van.
    sys.stdout.reconfigure(encoding="utf8", errors="replace")

    repo = Path(a.repo)
    rapport, verschillen = bouw_rapport(repo, a.ref_a, a.ref_b, paar(a.env_a), paar(a.env_b), a.alles)

    if a.md:
        Path(a.md).write_text(rapport, encoding="utf8")
        print(f"rapport: {a.md}")
    else:
        print(rapport)
    if a.csv:
        schrijf_csv(a.csv, verschillen,
                    git(repo, "rev-parse", "--short", a.ref_a).strip(),
                    git(repo, "rev-parse", "--short", a.ref_b).strip())
        print(f"parametertabel: {a.csv}")


if __name__ == "__main__":
    sys.exit(main())
