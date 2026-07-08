# RS-testomgeving

Test- en vergelijkomgeving voor [RSopen](https://github.com/ObjectVision/RSopen)
(RuimteScanner). Twee onderdelen:

1. **Run-wizard** (`Start.bat` → `main.py`): cloont een RSopen-commit, patcht
   modelparameters en draait de experimenten via GeoDmsRun.exe.
2. **Commit-vergelijker** (`rs_compare.py` + `rs_report.py`): vergelijkt de
   output-artefacten van twee runs en genereert een HTML-rapport met verdicts,
   diff-kaarten en confusion-matrices. Implementeert pbl-nl/model-RSopen#16.

## Commit-vergelijker

De vergelijking gebeurt **buiten het model** (Python, op geëxporteerde
bestanden). Bewuste keuze: oude commits kunnen geen nieuwe meet-API bevatten,
bestanden vergelijken werkt voor elk commit-paar.

Ontwerp volgt de GeoDMS-Test output-standaard (`batch/TEST_OUTPUT_STANDARD.md`
aldaar): **meting en oordeel gescheiden**. `rs_compare.py` meet en schrijft
`compare.result.json` (schema 2) + diff-artefacten; `rs_report.py` velt het
oordeel op basis van `tolerances.json`. Toleranties bijstellen = alleen het
rapport opnieuw genereren, geen model-rerun.

### Workflow

```
# 1. Draai run A en run B (bijv. twee commits, elk met eigen LocalDataDir
#    of exports tussentijds wegkopiëren -- resultaatbestanden krijgen wel een
#    StudyArea-suffix maar geen commit-suffix!)

# 2. Vergelijk de twee export-mappen
python rs_compare.py C:/LocalData/runs/pre508 C:/LocalData/runs/head ^
    --out C:/LocalData/runs/compare_pre508_head ^
    --name-a pre508 --name-b head --report

# 3. Open C:/LocalData/runs/compare_pre508_head/report.html
#    Tolerantie bijstellen? Pas tolerances.json aan en draai alleen:
python rs_report.py C:/LocalData/runs/compare_pre508_head/compare.result.json
```

### Wat wordt vergeleken

Bestanden worden gematcht op relatief pad (case-insensitive):

| Type | Vergelijking | Artefacten bij verschil |
|---|---|---|
| `.tif` categoriaal (integer) | celgewijs | diff.tif, confusion.csv, sample.csv (top-N met RD-coördinaten), PNG's A/B/diff |
| `.tif` numeriek (float) | celgewijs + sommen | diff.tif (B−A), sample.csv, PNG's A/B/diff |
| `.csv` | celgewijs (numeriek-tolerant) | — |
| overig | byte-vergelijking | — |

`.xml` (audit trails) en logmappen worden standaard genegeerd (`--include-xml`
om aan te zetten). Bestanden die maar in één run voorkomen verschijnen als
warning in het rapport — nooit stil overslaan.

### Verdict-regels (nooit een holle OK)

- identiek → **ok**; binnen `cell_pct`-tolerantie → **ok** (met vermelding)
- boven tolerantie → **output differs** (rood)
- shape/structuur/meetfout → rood, met notitie
- alleen in A of B → **warn**

### Dependencies

```
pip install numpy tifffile pillow
```

Python ≥ 3.10. Geen GDAL-installatie nodig.
