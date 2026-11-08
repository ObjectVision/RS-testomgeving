"""
en_bijgewerkt.py -- meldt Engelse wikipagina's waarvan de Nederlandse bron na de vertaling is gewijzigd.

Elke Engelse pagina van de RSopen-wiki (EN-*.md) begint met een regel als

    This is an English translation of the Dutch page [[Introductie]], which is leading.
    Translated on 8 November 2026 from wiki commit 428045e.

Het script leest die eerste regel, haalt er de Nederlandse pagina (de eerste [[wikilink]]) en de
commit uit, en kijkt in git of de Nederlandse pagina na die commit nog is gewijzigd. Een commit die
de Nederlandse en de Engelse pagina samen wijzigt, telt als een gezamenlijke bijwerking en niet als
achterstand: zo kan een vertaling in dezelfde commit landen als de Nederlandse tekst waarvan ze is
gemaakt. Een wijziging aan de Nederlandse pagina die nog niet is gecommit, meldt het script apart.

Gebruik:
    python en_bijgewerkt.py [<wikimap>]

De wikimap is standaard C:\\ProjDir\\_Tools\\RSopen.wiki. Exitcode 0 als elke Engelse pagina bij
is, 1 als er minstens een achterloopt of een niet-gecommitte bronwijziging heeft, 2 bij een
pagina waarvan de eerste regel, de bron of de commit niet te lezen is.
"""

import re
import subprocess
import sys
from pathlib import Path

STANDAARD_WIKI = Path(r"C:\ProjDir\_Tools\RSopen.wiki")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
COMMIT = re.compile(r"\bcommit ([0-9a-f]{7,40})\b")


def git(wiki, *args):
    """Draai git in de wikimap en geef stdout terug; een fout geeft None."""
    res = subprocess.run(
        ["git", "-c", "core.quotepath=off", "-C", str(wiki), *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    if res.returncode != 0:
        return None
    return res.stdout


def bronbestand(link):
    """Van een wikilink naar de bestandsnaam: het doel na de pipe, spaties als streepjes."""
    doel = link.split("|")[-1].split("#")[0].strip()
    return doel.replace(" ", "-") + ".md"


def bestanden_in_commit(wiki, sha):
    uit = git(wiki, "show", "--name-only", "--format=", "-z", sha)
    return set(filter(None, (uit or "").split("\0")))


def toets_pagina(wiki, en):
    """Geef (status, regels) terug; status is 'bij', 'achter' of 'fout'."""
    eerste = en.read_text(encoding="utf-8-sig").splitlines()[0] if en.stat().st_size else ""
    link = WIKILINK.search(eerste)
    commit = COMMIT.search(eerste)
    if not link or not commit:
        return "fout", ["eerste regel noemt geen [[pagina]] en geen commit: " + eerste[:100]]
    nl = bronbestand(link.group(1))
    if not (wiki / nl).exists():
        return "fout", [f"de Nederlandse bron {nl} bestaat niet"]
    sha = commit.group(1)
    if git(wiki, "rev-parse", "--verify", "--quiet", sha + "^{commit}") is None:
        return "fout", [f"commit {sha} staat niet in deze kloon"]

    regels = []
    log = git(wiki, "log", "--format=%H%x09%h%x09%ad%x09%s", "--date=short", f"{sha}..HEAD", "--", nl) or ""
    for rij in filter(None, log.splitlines()):
        volledig, kort, datum, onderwerp = rij.split("\t", 3)
        if en.name in bestanden_in_commit(wiki, volledig):
            continue  # Nederlandse en Engelse pagina samen bijgewerkt
        regels.append(f"{kort} {datum} {onderwerp}")

    status_nl = (git(wiki, "status", "--porcelain", "--", nl) or "").strip()
    status_en = (git(wiki, "status", "--porcelain", "--", en.name) or "").strip()
    if status_nl:
        extra = "; de Engelse pagina is ook nog niet gecommit" if status_en else ""
        regels.append(f"niet-gecommitte wijziging aan {nl}{extra}")

    return ("achter" if regels else "bij"), [f"bron {nl}, vertaald van {sha}"] + regels


def main():
    wiki = Path(sys.argv[1]) if len(sys.argv) > 1 else STANDAARD_WIKI
    if git(wiki, "rev-parse", "--git-dir") is None:
        print(f"{wiki} is geen git-kloon")
        return 2
    paginas = sorted(wiki.glob("EN-*.md"))
    if not paginas:
        print(f"geen EN-*.md in {wiki}")
        return 2

    telling = {"bij": 0, "achter": 0, "fout": 0}
    for en in paginas:
        status, regels = toets_pagina(wiki, en)
        telling[status] += 1
        label = {"bij": "bij", "achter": "LOOPT ACHTER", "fout": "FOUT"}[status]
        print(f"{en.name}: {label}")
        for regel in regels:
            print(f"    {regel}")

    print(f"\n{len(paginas)} Engelse pagina's: {telling['bij']} bij, "
          f"{telling['achter']} achter, {telling['fout']} niet te toetsen")
    if telling["fout"]:
        return 2
    return 1 if telling["achter"] else 0


if __name__ == "__main__":
    sys.exit(main())
