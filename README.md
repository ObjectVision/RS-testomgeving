# RS-testomgeving

Test- en versievergelijkomgeving voor [RSopen](https://github.com/ObjectVision/RSopen)
(RuimteScanner, een GeoDMS-model).

Doel van het geheel: **een specifieke revisie van het model uitrekenen en de
resultaten van twee revisies met elkaar vergelijken**, om regressie zichtbaar te
maken (zien we onbedoelde veranderingen, en zo ja hoeveel en zijn ze gewenst?).
Implementeert pbl-nl/model-RSopen#16.

De omgeving bestaat uit de enginetoets (de werkende weg) en twee oudere onderdelen:

```
  [1] revision-runner            [2] commit-vergelijker
  kies commit + GeoDMS-versie -> reken door -> exports  ->  vergelijk twee runs -> rapport
  (main.py / Start.bat)                                     (rs_compare + rs_report + rs_indicators)
```

---

## Enginetoets (`enginetoets\Toets.ps1`)

Status: werkend, gebruikt voor de nachtrun van NL2120 op 6 op 7 oktober 2026. Dit is de uitwerking van
pbl-nl/model-RSopen#16 die onderdeel 1 vervangt: geen wizard maar scripts met standaardwaarden, zodat
ook PBL ze kan draaien.

Een project is een branch van de modelrepo. Per branch is er een baseline (de commit van de laatste
productierun: een git-tag `baseline/<datum>`, het profiel van alle instellingen van die commit, en de
bewaarde uitvoer van zijn toetsrun) en een log. Elke toets rekent een commit door in een eigen
git-worktree met een eigen LocalData, onder het profiel van de baseline plus het testprofiel van de
branch (`enginetoets\profielen\<branch>.csv`: een provincie, een of twee zichtjaren, de varianten), met
de GeoDMS-versie die `Run2120.ps1` van die commit zelf noemt. Onder dat profiel is de allocatie
deterministisch, dus elk verschil is rekenwijze of invoer. Groepen commits worden als ketting
vergeleken: elke groep tegen de toetsrun van de groep ervoor.

```
cd C:\ProjDir\RSopen_NL2120                                   de werkkopie van het model, of geef -Repo
pwsh ..\_Tools\RS-testomgeving\enginetoets\Setup.ps1          staat alles er op deze machine
pwsh ..\_Tools\RS-testomgeving\enginetoets\Baseline.ps1 -Commit <sha> -Omschrijving "de laatste productierun"
pwsh ..\_Tools\RS-testomgeving\enginetoets\Toets.ps1                        HEAD tegen de baseline
pwsh ..\_Tools\RS-testomgeving\enginetoets\Toets.ps1 -Commit <sha> -Van <sha ervoor> -Samenvatting "..."
```

Uitvoer: per branch `C:\LocalData\RSopen_toets\<branch>	oetslog.csv` en `toetslog.html` (alle toetsen
genummerd, met per schakel het rapport eronder), per run `toetsrapport.md` en `.html` in de kopie onder
`C:\ProjDir\RSopen_toets\<branch>_<sha>atch\log`. Het rapport leest in de volgorde: wat zit er in de
commits, hoe anders (koptabel uit Diagnose en per sector het patroon op de kaart), waarom (een paar
zinnen plus de instellingen die verschillen), verder kijken (per tif de celverschillen, alle
controlewaarden, de bestanden per commit, de technische gegevens). Oordelen: IDENTIEK, STAND GELIJK
(alleen een meting anders), VERSCHILT.

| Bestand | Rol |
|---|---|
| `Toets.ps1` | een commit doorrekenen en naast de baseline of een eerdere toetsrun leggen |
| `Baseline.ps1` | een commit tot baseline van een branch maken |
| `Setup.ps1` | zegt of een machine alles heeft (GeoDMS, git, pwsh 7, Python met numpy en tifffile, ConfigSettings, Data) |
| `Profiel.py` | het profiel van een commit dumpen en opleggen op een werkkopie |
| `VergelijkCommits.py` | het statische deel: per commit wat hij raakt (rekenwijze, instellingen, invoer, orkestratie, meting, toelichting) |
| `Toetsrapport.py` | het rapport van twee runs |
| `Toetslog.py` | het log van een branch als pagina |
| `Runinfo.py` | rekentijd en piekgeheugen per stap uit de logs van Run2120.ps1 |
| `profielen\<branch>.csv` | het testprofiel per branch |

Onderdeel 2 (`rs_compare`, `rs_report`, `rs_indicators`) blijft de doorklik wanneer een rapport
VERSCHILT zegt en je wilt zien waar op de kaart.

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
