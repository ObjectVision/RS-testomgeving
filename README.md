# RS-testomgeving

Test- en versievergelijkomgeving voor [RSopen](https://github.com/ObjectVision/RSopen)
(RuimteScanner, een GeoDMS-model).

Doel van het geheel: **een specifieke revisie van het model uitrekenen en de
resultaten van twee revisies met elkaar vergelijken**, om regressie zichtbaar te
maken (zien we onbedoelde veranderingen, en zo ja hoeveel en zijn ze gewenst?).
Implementeert pbl-nl/model-RSopen#16.

De omgeving bestaat uit twee onderdelen die na elkaar gebruikt worden:

```
  [1] revision-runner            [2] commit-vergelijker
  kies commit + GeoDMS-versie -> reken door -> exports  ->  vergelijk twee runs -> rapport
  (main.py / Start.bat)                                     (rs_compare + rs_report + rs_indicators)
```

---

## Onderdeel 1 — revision-runner (`main.py`)

**Status: in revisie.** Dit deel is ouder en moet weer werkend gemaakt worden
(zie "Openstaand" onderaan). Het idee: via een klein venster kies je een
git-commit (SHA) en een GeoDMS-versie, waarna het die commit cloont, de
modelparameters gelijktrekt en het model doorrekent met `GeoDmsRun.exe`.

Bestanden:

| Bestand | Rol |
|---|---|
| `Start.bat` | startpunt: draait `python main.py` |
| `main.py` | Tkinter-wizard + orchestratie (clone -> laad GeoDMS-modules -> run -> rapport) |
| `git_tools.py` | `git clone` + checkout van een SHA naar de test-map (idempotent: reset+clean bij hergebruik) |
| `experiment_builder.py` | bouwt de GeoDmsRun-commando's; cascade-fallback voor gewijzigde configpaden/nodes |
| `overrides.py` | patcht `SectorAllocRegio` en forceert engine-settings zodat je hetzelfde vergelijkt |
| `config.json` | GeoDMS-versie, default-SHA, repo-URL, SourceData- en test-map |

Aanroep van GeoDMS (per experiment):
```
GeoDmsRun.exe /L<logpad> /<MT1> /<MT2> /<MT3> <cfg> @statistics <result_node>
```

De rapportage van dit onderdeel leunt nu nog op `regression.py`/`profiler.py`
uit de GeoDMS-installatiemap. Het plan is die te vervangen door onderdeel 2
(zie "Openstaand").

---

## Onderdeel 2 — commit-vergelijker (`rs_compare.py`, `rs_report.py`, `rs_indicators.py`)

**Status: werkend.** Vergelijkt **buiten het model om** (Python, op de
geexporteerde bestanden). Bewuste keuze: oude commits kunnen geen nieuwe
meet-API in de config bevatten, maar bestanden vergelijken werkt voor elk
commit-paar. Volgt de scheiding **meting vs. oordeel** uit de GeoDMS-Test
output-standaard: het meten schrijft ruwe getallen (json), het rapport velt het
oordeel op basis van instelbare toleranties. Toleranties bijstellen = alleen het
rapport opnieuw genereren, geen model-rerun.

### Voorwaarden

- Python >= 3.10; `pip install numpy tifffile pillow imagecodecs scipy`
  (voor de render-controle van figuren optioneel: `svglib reportlab pypdfium2`).
- Twee runs die op **hetzelfde grid** staan (zelfde bbox/resolutie). Staan ze dat
  niet (bijv. door een gewijzigde studygebied-bbox tussen commits), dan valt
  `rs_compare` terug op aggregatie naar een gemeenschappelijk 100m-raster — dat
  is een noodgreep met detailverlies; zuiverder is de grids gelijk te trekken.
- Resultaatbestanden krijgen wel een StudyArea-suffix maar **geen** commit-suffix.
  Geef daarom elke run zijn eigen `LocalDataDir`, of kopieer de exports tussen
  runs weg.

### Stap A — `rs_compare.py`: meet de verschillen

Vergelijkt alle bestanden onder twee mappen, gematcht op relatief pad.

```
python rs_compare.py <run_dir_a> <run_dir_b> --out <compare_dir> \
    --name-a pre508 --name-b head \
    [--only "*StandY2040*Noord_Holland*"] [--report]
```

| Type | Vergelijking | Artefacten bij verschil |
|---|---|---|
| `.tif` categoriaal (int) | celgewijs | `_diff.tif`, `_confusion.csv`, `_sample.csv` (top-N met RD-coord.), PNG's A/B/diff |
| `.tif` numeriek (float) | celgewijs + sommen | `_diff.tif` (B-A), `_sample.csv`, PNG's A/B/diff |
| `.csv` | celgewijs (numeriek-tolerant) | - |
| overig | byte-vergelijking | - |

`.xml`/`.tfw`/logs worden genegeerd (`--include-xml` zet xml wel aan). Uitvoer:
`compare.result.json` (schema 2, meting zonder oordeel) + `artifacts/`.

### Stap B — `rs_report.py`: vel het oordeel + HTML

```
python rs_report.py <compare_dir>/compare.result.json [--tolerances tolerances.json] [--out report.html]
```

`tolerances.json`: per bestand/patroon een `cell_pct` (max % afwijkende cellen
dat nog "ok" is). Verdict-regels: identiek of binnen tolerantie = ok; erboven =
"output differs" (rood); shape/structuur/meetfout = rood; alleen in A of B = warn.
Nooit een holle OK. `--report` in stap A draait stap B meteen mee.

### Stap C (optioneel) — `rs_indicators.py`: buurt-niveau indicatoren

Inhoudelijke vergelijking op CBS-buurtniveau (gebaseerd op "Voorstel voor
validatie van Ruimtescanner", Claassens 2026), omgezet van model-vs-observatie
naar run-A-vs-run-B.

```
python rs_indicators.py --run-a <run_a> --run-b <run_b> \
    --name-a pre508 --name-b head \
    --buurt <buurt_grid.tif> [--buurt-namen <buurt.csv>] \
    --zichtjaar Y2040 [--casus WLO_hoog_BAU] [--suffix Noord_Holland] \
    --out <indicatoren_dir>
```

Vereist een **buurt-grid-tif** (buurt-id per cel, zelfde grid als de runs):
exporteer in de GeoDMS-config `/SourceData/RegioIndelingen/Buurt/Per_AdminDomain`.
`--buurt-namen` is een csv met kolommen `id;name;Gemeente_name` (voor labels).

Levert `indicatoren.html` met 12 figuren: woninggroei per buurt (scatter +
Spearman, met outlier-labels), nieuwe wooncellen, verdichtingsaandeel, dichtheid
uitbreiding, verdichtingsintensiteit, in-/uitbreiding-decompositie, Lorenz/Gini,
clustergrootteverdeling, randdichtheid + lintaandeel, leapfrog-afstand tot
bestaand bebouwd, en banengroei + werkcluster-verdeling (werken-spiegel).

De runstructuur die verwacht wordt:
```
<run>/BaseData/StandBasisjaar/{Wonen,Werken}/<subsector>_<suffix>.tif
<run>/Allocatie/<casus>/Stand<zichtjaar>/{Wonen,Werken}/<subsector>_<suffix>_SS-*.tif
```

---

## Voorbeeld-workflow (zoals gebruikt voor #508, Noord-Holland)

1. Run A ("voor"): oude commit uitrekenen naar een eigen `LocalDataDir`.
2. Run B ("na"): huidige commit, eigen `LocalDataDir`.
   (Beide met identieke parameters/scenario, zodat alleen de te onderzoeken
   codewijziging het verschil maakt.)
3. `rs_compare.py A/Allocatie B/Allocatie --out cmp --only "*StandY2040*NH*" --report`
   -> `report.html`.
4. `rs_indicators.py --run-a A --run-b B --buurt buurt.tif --out ind`
   -> `indicatoren.html`.

---

## Openstaand

- Onderdeel 1 (de wizard) weer werkend maken en koppelen aan onderdeel 2:
  na het uitrekenen van een revisie automatisch de exports door `rs_compare` /
  `rs_report` halen, in plaats van de oude `regression.py`/`profiler.py` uit de
  GeoDMS-installatiemap. Orchestratie per (commit, GeoDMS-versie).
- `rs_indicators`: optionele extra indicatoren die een aanvullende GeoDMS-export
  vergen (suitability-verdeling van nieuwe cellen, dorpstoets op
  stedelijkheidsklasse, claimrealisatie per allocatieregio).
