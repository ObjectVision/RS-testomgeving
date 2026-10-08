# RS-testomgeving

Toetsgereedschap voor [RSopen](https://github.com/ObjectVision/RSopen) (RuimteScanner, een GeoDMS-model):
de uitkomsten van commits van een branch naast elkaar leggen zonder de code te lezen, zodat regressie
zichtbaar wordt en een oplevering met een gerust hart de nieuwe baseline kan worden. Uitwerking van
pbl-nl/model-RSopen#16.

Twee mappen:

| Map | Wat | Startpunt |
|---|---|---|
| `enginetoets` | een commit doorrekenen onder het bevroren profiel van de baseline en het verschil met een eerdere run meten: koptabel, patroon per sector, controlewaarden, en een oordeel in het toetslog van de branch | `Enginetoets.cmd` (dubbelklik), of `Toets.ps1` |
| `kaarten` | kaarten en grafieken als een toets VERSCHILT zegt: per kaart de verschilcellen in beeld, en per CBS-buurt waar en in welke vorm de groei landt | `Kaarten.ps1 -Commit <sha> -Van <sha>` |

De scripts staan buiten de modelrepo; alleen de baseline-tag staat in de modelrepo. Ze draaien vanuit de
werkkopie van het model (de map met `cfg\main.dms`), of met `-Repo` naar die werkkopie.

---

## Enginetoets (`enginetoets`)

Een project is een branch van de modelrepo. Per branch is er een baseline (de commit van de laatste
productierun: een git-tag `baseline/<datum>`, het profiel van alle instellingen van die commit, en de
bewaarde uitvoer van zijn toetsrun) en een log. Elke toets rekent een commit door in een eigen
git-worktree met een eigen LocalData, onder het profiel van de baseline plus het testprofiel van de
branch (`enginetoets\profielen\<branch>.csv`: een provincie, een of twee zichtjaren, de varianten), met
de GeoDMS-versie die `Run2120.ps1` van die commit zelf noemt. Onder dat profiel is de allocatie
deterministisch, dus elk verschil is rekenwijze of invoer. Groepen commits worden als ketting
vergeleken: elke groep tegen de toetsrun van de groep ervoor.

```
dubbelklik enginetoets\Enginetoets.cmd                        het venster: de commits sinds de baseline, kies er een of twee, de toets start (geen terminal nodig)
cd C:\ProjDir\RSopen_NL2120                                   de werkkopie van het model, of geef -Repo
pwsh ..\_Tools\RS-testomgeving\enginetoets\Setup.ps1          staat alles er op deze machine
pwsh ..\_Tools\RS-testomgeving\enginetoets\Kies.ps1           dezelfde kiezer in de console
pwsh ..\_Tools\RS-testomgeving\enginetoets\Baseline.ps1 -Commit <sha> -Omschrijving "de laatste productierun"
pwsh ..\_Tools\RS-testomgeving\enginetoets\Toets.ps1                        HEAD tegen de baseline
pwsh ..\_Tools\RS-testomgeving\enginetoets\Toets.ps1 -Commit <sha> -Van <sha ervoor> -Samenvatting "..."
pwsh ..\_Tools\RS-testomgeving\enginetoets\Toets.ps1 -Commit <sha> -Label vol -EigenInstellingen -Testprofiel <map>\profielen\<branch>_vol.csv -ZonderVergelijking
pwsh ..\_Tools\RS-testomgeving\enginetoets\Acceptatie.ps1 -Commit <sha> -Samenvatting "..."    de volle run naast die van de baseline
pwsh ..\_Tools\RS-testomgeving\enginetoets\Baseline.ps1 -Commit <sha> -Run <toetsrun> -Vol <volle run> -Omschrijving "..."   akkoord: nieuwe baseline
pwsh ..\_Tools\RS-testomgeving\kaarten\Kaarten.ps1 -Commit <sha> -Van <sha ervoor>             kaarten en grafieken van het verschil
```

De acceptatie is de andere vraag dan de enginetoets: mag deze commit de nieuwe baseline worden? Daarvoor
draait de kandidaat met zijn eigen instellingen (`-EigenInstellingen`), over alle zichtjaren en de
varianten van de productie (`profielen\<branch>_vol.csv`), en legt `Acceptatie.ps1` die run naast de
volle run van de baseline: de instellingen en leveringen die anders staan, de ketting van enginetoetsen
uit het log, per casus de koptabel van het eindjaar (de andere jaren onder Verder kijken) en de normen
van `batch\ToetsOplevering.ps1` van de kandidaat op beide runs, met wat van PASS naar FAIL ging. Het log
krijgt een regel ACCEPTATIE; het oordeel is aan de lezer.

Uitvoer: per branch `C:\LocalData\RSopen_toets\<branch>\toetslog.csv` en `toetslog.html` (alle toetsen
genummerd, met per schakel het rapport eronder), per run `toetsrapport.md` en `.html` in de kopie onder
`C:\ProjDir\RSopen_toets\<branch>_<sha>\batch\log`. Het rapport leest in de volgorde: wat zit er in de
commits, hoe anders (koptabel uit Diagnose en per sector het patroon op de kaart), waarom (een paar
zinnen plus de instellingen die verschillen), verder kijken (per tif de celverschillen, alle
controlewaarden, de bestanden per commit, de technische gegevens). Oordelen: IDENTIEK, STAND GELIJK
(alleen een meting anders), VERSCHILT.

| Bestand | Rol |
|---|---|
| `Enginetoets.cmd` | dubbelklikken: opent het venster zonder terminal (vraagt PowerShell 7) |
| `Enginetoets.ps1` | het venster: de werkkopie kiezen (onthouden in `%LOCALAPPDATA%\RS-testomgeving`), de commits sinds de baseline (datum, onderwerp, wat hij raakt, al getoetst), een of twee rijen, de samenvatting, Start; de toets draait in een eigen venster met een transcript `toets_<sha>_<tijd>.log` naast het toetslog, en het rapport opent vanzelf |
| `Commitlijst.ps1` | de lijst van commits sinds de baseline, gedeeld door het venster en Kies.ps1 |
| `Kies.ps1` | dezelfde kiezer in de console: een of twee rijen (Out-GridView, anders een nummer) en Toets.ps1 starten; `-Lijst` drukt alleen de lijst af |
| `Toets.ps1` | een commit doorrekenen en naast de baseline of een eerdere toetsrun leggen |
| `Baseline.ps1` | een commit tot baseline van een branch maken; met `-Vol` de volle run erbij als tweede uitvoer |
| `Acceptatie.ps1` | de volle run van een kandidaat naast die van de baseline, met de normen van ToetsOplevering |
| `Acceptatierapport.py` | het acceptatierapport |
| `Setup.ps1` | zegt of een machine alles heeft (GeoDMS, git, pwsh 7, Python met numpy en tifffile, ConfigSettings, Data) |
| `Profiel.py` | het profiel van een commit dumpen en opleggen op een werkkopie |
| `VergelijkCommits.py` | het statische deel: per commit wat hij raakt (rekenwijze, instellingen, invoer, orkestratie, meting, toelichting) |
| `Toetsrapport.py` | het rapport van twee runs |
| `Toetslog.py` | het log van een branch als pagina |
| `Runinfo.py` | rekentijd en piekgeheugen per stap uit de logs van Run2120.ps1 |
| `profielen\<branch>.csv` | het testprofiel per branch |
| `profielen\<branch>_vol.csv` | het profiel van de volle run voor de acceptatie (alleen studiegebied en varianten) |

---

## Kaarten en grafieken (`kaarten`)

De enginetoets zegt of en hoeveel twee commits verschillen. De scripts in `kaarten` laten zien waar en in
welke vorm, buiten het model om, in Python op de weggeschreven bestanden; daardoor werkt hij voor elk paar
runs, ook van commits van voor een wijziging in de meetkant van de configuratie. Hij volgt de scheiding
tussen meten en oordelen: het meten schrijft ruwe getallen (json), het rapport velt het oordeel met
instelbare toleranties, dus toleranties bijstellen is alleen het rapport opnieuw maken.

`Kaarten.ps1` zet beide scripts op twee toetsruns van dezelfde branch (de commit en de baseline, of met
`-Van` een eerdere toetsrun), per casus die beide runs hebben, voor het laatste zichtjaar of `-Zichtjaar`:

```
pwsh ..\_Tools\RS-testomgeving\kaarten\Kaarten.ps1 -Commit a3309144 -Van 3827fbed -Toon
```

Uitvoer onder `C:\LocalData\RSopen_toets\<branch>\kaarten\<A>_<B>\`: `verschilkaarten_<casus>_<jaar>\report.html`
en `buurtindicatoren_<casus>_<jaar>\indicatoren.html`. Het buurtgrid dat de indicatoren nodig hebben (het
buurtnummer per cel op het raster van het studiegebied, met een csv van buurt- en gemeentenamen) maakt
het script eenmalig per branch en studiegebied met GeoDMS uit de kopie van de commit, via een tijdelijk
exportitem dat na afloop weer weg is; het staat onder `<Toetsmap>\<branch>\buurtgrid`.

### `rs_compare.py` en `rs_report.py`: per kaart de verschilcellen

`rs_compare.py` vergelijkt alle bestanden onder twee mappen, gematcht op relatief pad (`--only` beperkt
tot een glob, zoals `Allocatie/<casus>/Stand<jaar>/*`):

| Type | Vergelijking | Artefacten bij verschil |
|---|---|---|
| `.tif` categoriaal (int) | celgewijs | `_diff.tif`, `_confusion.csv` (klasse x klasse), `_sample.csv` (top-N met RD-coordinaten), miniaturen A, B en verschil |
| `.tif` numeriek (float) | celgewijs plus sommen | `_diff.tif` (B min A), `_sample.csv`, miniaturen A, B en verschil |
| `.csv` | celgewijs, numeriek tolerant | geen |
| overig | bytevergelijking | geen |

`.xml`, `.tfw` en logs doen niet mee. Twee runs horen op hetzelfde raster te staan; staan ze dat niet,
dan valt het script terug op een som of modus per 100 meter-cel, met detailverlies. `rs_report.py` velt
het oordeel per bestand (identiek, binnen tolerantie, verschilt; structuurverschil of meetfout is rood,
alleen in A of B is een waarschuwing) met `tolerances.json` (per patroon een `cell_pct`, het aandeel
afwijkende cellen dat nog goed is) en maakt er een pagina van met de miniaturen.

### `rs_indicators.py`: per buurt waar en hoe compact de groei landt

Gebaseerd op het voorstel voor validatie van de RuimteScanner (Object Vision, maart 2026), omgezet van
model tegen waarneming naar run A tegen run B. De vraag per figuur: plaatst run B de groei in dezelfde
buurten, gebruikt hij evenveel ruimte, en bouwt hij even compact? Twaalf figuren in een pagina, met per
figuur een leeswijzer:

1. woninggroei per buurt (punt per buurt, Spearman-rangcorrelatie, de grootste afwijkers gelabeld)
2. nieuwe wooncellen per buurt
3. verdichtingsaandeel per buurt
4. dichtheid van de uitbreidingslocaties (woningen per hectare)
5. verdichtingsintensiteit (woningen per bestaande wooncel)
6. decompositie van de groei in inbreiding en uitbreiding
7. concentratie van de groei (Lorenz-curve en Gini)
8. clustergrootte van de nieuwe woonlocaties (snippers onder 0,4 ha, 0,4 tot 2 ha, 2 ha en meer)
9. vorm van de nieuwe woonlocaties: randdichtheid en lintaandeel
10. afstand van nieuwe wooncellen tot bestaand bebouwd gebied (leapfrog)
11. banengroei per buurt, de spiegel van figuur 1 voor werken
12. clustergrootte van nieuwe werklocaties

Daarboven een tabel met kerncijfers van beide runs en daaronder de vijftien buurten waar de runs het
meest uiteenlopen. De subsectoren komen uit de basisjaarmap van run A, dus een nieuwe subsector doet
vanzelf mee. Bij #847 (a4fb0b15 tegen a3309144, BAU 2040, Noord-Holland) zegt deze pagina wat de
koptabel van de enginetoets niet zegt: het aantal woningen bleef gelijk, maar er kwamen 17.700 nieuwe
wooncellen bij, de dichtheid van de uitbreiding ging van 49 naar 41 woningen per hectare en het aandeel
nieuwe cellen binnen 300 meter van bestaand bebouwd gebied van 86 naar 82 procent.

Voorwaarden: Python 3.10 of hoger met `numpy`, `tifffile`, `pillow`, `imagecodecs` en `scipy`.

| Bestand | Rol |
|---|---|
| `Kaarten.ps1` | twee toetsruns kiezen, het buurtgrid maken als het er nog niet is, en beide scripts per casus draaien |
| `rs_compare.py` | het meten: per bestand de verschillen, met diff-tif, verwarringsmatrix, steekproef en miniaturen |
| `rs_report.py` | het oordeel per bestand met toleranties, als pagina |
| `rs_indicators.py` | de buurtindicatoren, als pagina met twaalf figuren en een json met de kerncijfers |
| `tolerances.json` | de toleranties van rs_report: `default` en `rules` (fnmatch op de bestandsnaam, `cell_pct`) |

---

## Wat er niet meer is

De revision-runner van voor juli 2026 (het Tkinter-venster `main.py` met `Start.bat`, `config.json`,
`git_tools.py`, `experiment_builder.py` en `overrides.py`, dat een commit kloonde en met `regression.py`
uit de GeoDMS-installatie doorrekende) is vervangen door de enginetoets en uit de repo gehaald; hij
staat in de geschiedenis tot en met commit 67e81df.

## Openstaand

- De proef van de enginetoets op een schone machine (Setup.ps1 zegt wat er ontbreekt).
- Het toetsrapport noemt Kaarten.ps1 alleen als opdracht onder Hoe de runs draaiden; de kaarten en grafieken zijn een losse stap.
- Extra buurtindicatoren die een aanvullende GeoDMS-export vergen: de suitability-verdeling van nieuwe
  cellen, een dorpstoets op stedelijkheidsklasse, de claimrealisatie per allocatieregio.
