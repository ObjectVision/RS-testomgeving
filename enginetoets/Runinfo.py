"""Rekentijd en piekgeheugen per stap van een toetsrun, als run.tsv naast de uitvoer.

Gebruik:
    python Runinfo.py --status <status.tsv> --logs <logmap> --uit <run.tsv>

Leest status.tsv van Run2120.ps1 (tijd, stap, item, exit, seconden) en haalt per stap uit het laatste
log van die stap de regel met het piekgeheugen van GeoDMS (Highest CommitCharge). Toetsrapport.py zet
daar de regels rekentijd en piekgeheugen van de koptabel uit, zodat een wijziging die de allocatie
twee keer zo traag maakt of het geheugen laat oplopen in dezelfde tabel staat als de uitkomst.
"""

import argparse
import csv
import re
import sys
from pathlib import Path

PIEK = re.compile(r"Highest CommitCharge:\s*(\d+)\[MB\]")


def lees_status(pad):
    with open(pad, newline="", encoding="utf8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def piek_van(logmap, stap):
    logs = sorted(Path(logmap).glob(f"*_{stap}.log"))
    if not logs:
        return ""
    tekst = logs[-1].read_text(encoding="utf8", errors="replace")
    treffers = PIEK.findall(tekst)
    return treffers[-1] if treffers else ""


def main():
    p = argparse.ArgumentParser(description="Rekentijd en piekgeheugen per stap van een toetsrun.")
    p.add_argument("--status", required=True)
    p.add_argument("--logs", required=True)
    p.add_argument("--uit", required=True)
    a = p.parse_args()
    rijen = lees_status(a.status)
    with open(a.uit, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["stap", "seconden", "exit", "piek_MB"])
        for r in rijen:
            w.writerow([r["stap"], r["seconden"].replace(",", "."), r["exit"], piek_van(a.logs, r["stap"])])
    print(f"runinfo: {a.uit} ({len(rijen)} stappen)")


if __name__ == "__main__":
    sys.exit(main())
