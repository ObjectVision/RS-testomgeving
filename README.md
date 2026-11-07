# RS-testomgeving

Toetsgereedschap voor [RSopen](https://github.com/ObjectVision/RSopen) (RuimteScanner, een GeoDMS-model):
de uitkomsten van commits van een branch naast elkaar leggen zonder de code te lezen, zodat regressie
zichtbaar wordt en een oplevering met een gerust hart de nieuwe baseline kan worden. Uitwerking van
pbl-nl/model-RSopen#16.

Twee mappen:

| Map | Wat | Startpunt |
|---|---|---|
| `enginetoets` | een commit doorrekenen onder het bevroren profiel van de baseline en het verschil met een eerdere run meten: koptabel, patroon per sector, controlewaarden, en een oordeel in het toetslog van de branch | `Enginetoets.cmd` (dubbelklik), of `Toets.ps1` |
| `kaarten` | kaarten en grafieken als een toets VERSCHILT zegt: per kaart de verschilcellen in beeld, en per CBS-buurt waar en in welke vorm de groei landt; en na elke run de patroonkaarten: waar de nieuwbouw los van de woonkernen landt | `Kaarten.ps1 -Commit <sha> -Van <sha>`, `patroonkaarten.py --run <LocalData>` |

De scripts staan buiten de modelrepo; alleen de baseline-tag staat in de modelrepo. Ze draaien vanuit de
werkkopie van het model (de map met `cfg\main.dms`), of met `-Repo` naar die werkkopie.

---

## Enginetoets (`enginetoets`)

Een project is een branch van de modelrepo. Per branch is er een baseline (de commit van de laatste
productierun: een git-tag `baseline/<datum>`, het profiel van alle instellingen van die commit, en de
bewaarde uitvoer van zijn toetsrun) en een log. Elke toets rekent een commit door in een eigen
git-worktree met een eigen LocalData, onder het profiel van de baseline plus het testprofiel van de
branch (`enginetoets\profielen\<branch>.csv`: een provincie, een of twee zichtjaren, de varianten), met
de GeoDMS-versie die `Run2120.ps1` van die commit noemt, of anders de nieuwste op de machine. Onder dat profiel is de allocatie
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

### `patroonkaarten.py`: waar het patroon vreemd is, na elke run

De controlewaarden van RSopen en de scripts hierboven meten totalen, claims, clustergrootte en de afstand tot het
bebouwd gebied van het basisjaar. Een patroon als ringen en banden van nieuwe woningen rond kleine losse clusters midden
in een polder zien ze niet, want een boerenerf telt daar als bebouwd gebied; zo bleef het patroon in de Noordoostpolder
en Dronten na de slotrun van NL2120 (31 oktober 2026) onopgemerkt tot iemand de kaart bekeek. `patroonkaarten.py` kijkt
daarom na elke run naar de ruimtelijke patronen. Het leest alleen de standkaarten van een run, met of zonder tweede run
ernaast, heeft geen toetsrun en geen GeoDMS nodig, en schrijft alleen in de uitvoermap.

Wat het meet, per zichtjaar, per vak van 10 bij 10 km, per gemeente en voor het hele studiegebied:

| Maat | Wat het is |
|---|---|
| nieuwe woningen | per cel de toename van het aantal woningen (alle woonsubsectoren) tegen de stand van het zichtjaar ervoor, alleen waar het aantal groeit; bij het eerste zichtjaar zonder de BAG-nieuwbouw die het model in de startstand zet (de toename op een woncel van `SubSector_rel` met een jaar van verandering van voor het eerste zichtjaar) |
| afstandsbanden | het deel van de nieuwe woningen tot 250 m, tussen 250 m en 1 km en verder dan 1 km van een cel van de BRT-woonkern (`IsWoonkern`), gemeten tussen celmiddens |
| losse clusters | aaneengesloten cellen wonen of werken uit `SubSector_rel` (8-buren, cumulatief sinds het basisjaar) waarvan geen cel binnen 250 m van een woonkern ligt; met wonen of alleen werken, met oppervlak, en apart de clusters die alleen uit de startstand komen |
| ringwoningen | nieuwe woningen binnen 350 m van een los cluster van de stand ervoor (een kiem) en niet binnen 350 m van een woonkern; bij het eerste zichtjaar zijn de losse clusters van de startstand de kiemen; uitgesplitst naar kiemen met wonen en met alleen werken, en naar kiemen kleiner dan 2 ha |
| aangegroeide kiemen | kiemen met minstens een nieuwe woning in hun ring |
| BAG-referentie | de BAG-nieuwbouw in de startstand met dezelfde afstandsbanden, en de losse clusters die alleen uit de startstand komen |

Welke index van `SubSector_rel` wonen en welke werken is, ijkt het script zelf: per index het aandeel cellen met woningen
en met banen in de stand van het eerste zichtjaar (bij NL2120 0 tot en met 3 wonen met een aandeel van 1,0 en 4 tot en
met 9 werken). Het SS-nummer en de fingerprint-hash in de bestandsnamen vindt het ook zelf; een basisjaar of woonkern met
en zonder hash werkt allebei. Het studiegebied haalt het uit `Footprint_<gebied>.tif`; voor een provincie snijdt het het
landelijke buurtgrid op het raster van de provincie.

Het oordeel staat los van de meting. Elke tegel en gemeente krijgt per zichtjaar een score: de ringwoningen gedeeld door
100, plus de nieuwe woningen verder dan 1 km van een woonkern gedeeld door 250, plus de aangegroeide kiemen gedeeld door 10.
Opvallend is een score vanaf 3. Een tegel is een blok van 2 bij 2 vakken (20 km) en begint op elk vak, zodat een
brandhaard niet door een tegelgrens gesplitst wordt; de detailkaarten zijn van de tegels met de hoogste score die geen
vak delen met een tegel die hoger staat. De ijkmaten, de drempel en de aantallen kaarten staan in `patroondrempels.json`
onder `oordeel`; de maten zelf onder `meten`. Wie alleen het oordeel verandert, draait met `--herbeoordeel` en hoeft niet
opnieuw te meten.

```
python kaarten\patroonkaarten.py --run C:\LocalData\RSopen_NL2120 --casus WLO_hoog_BAU --zichtjaren Y2040 Y2050 Y2060 --naam slotrun --out C:\LocalData\RSopen_toets\NL2120\patronen\slotrun
python kaarten\patroonkaarten.py ... --vergelijk <LocalData van een andere run> --naam-vergelijk sept      een tweede run ernaast
python kaarten\patroonkaarten.py ... --vergelijk <dezelfde LocalData> --casus-vergelijk WLO_hoog_BAU_ref  een andere casus van dezelfde run
python kaarten\patroonkaarten.py ... --gemeenten Noordoostpolder Dronten                                   deze gemeenten krijgen hoe dan ook een kaart en een regel in de kern
python kaarten\patroonkaarten.py --out <dezelfde map> --herbeoordeel                                       alleen oordeel, kaarten en rapport opnieuw
```

Een LocalData waarin een andere sessie of een GeoDMS-proces werkt, lees je niet rechtstreeks: een GeoDMS-proces dat een
bestand wil overschrijven dat dit script openhoudt, valt om. Kijk eerst met `Get-CimInstance Win32_Process` naar de
draaiende `GeoDmsRun`-processen en kopieer anders de standmappen, `BaseData\StandBasisjaar\Wonen` en de
`IsWoonkern`-tif met robocopy naar een eigen map (zonder `Landbouw` en `PandFootprint` is dat ongeveer 400 MB voor drie
landelijke zichtjaren).

Uitvoer in `--out`: `patroonmaten.json` (alle maten per vak, gemeente en zichtjaar, met herkomst), `kaartdata.npz` (de
cellen die de kaarten nodig hebben), `patroonoordeel.json` (scores, volgorde, opvallend, rekentijd), `rapport.html` en
`rapport.md`, en in `kaarten` een overzichtskaart met de score per vak, per tegel bovenaan een detailkaart, per gemeente
bovenaan een kaart, en met een tweede run een overzicht en verschilkaarten van dezelfde tegels.

Rekentijd en geheugen, gemeten op OVSRV08 op 7 november 2026 voor heel Nederland met drie zichtjaren: 53 s in totaal
waarvan 36 s meten, met de bestanden al in de cache; de eerste draai op een koude cache, naast drie GeoDMS-processen, kostte
ruim 3 minuten. Met een tweede run erbij is het 91 s. De piek is 3,9 GB werkgeheugen en 5,4 GB vastgelegd privegeheugen, met een
tweede run 4,2 en 5,7 GB. Het script leest elke tif in zijn geheel (een landelijke kaart van 25 m is 145 miljoen cellen,
582 MB als float32) maar houdt per zichtjaar alleen de cellen met nieuwe woningen en de losse clusters vast; de afstanden
rekent het met een KD-boom op de rand van de woonkern en de kiemen, niet met een afstandstransformatie over het hele
raster. Flevoland alleen kost 9 s. `--herbeoordeel` kost 15 tot 25 s.

Hoe je de uitkomst leest. Het rapport begint met de landelijke aandelen tegen de BAG-referentie, de tegels en gemeenten
met de hoogste score en, met `--gemeenten`, de plek van de gevraagde gemeenten. Een hoge score door ringwoningen met veel
aangegroeide kiemen is het patroon van ringen en banden rond erven en kleine clusters; een hoge score door ringwoningen
rond een paar grote kiemen is een uitleg die los van de kern begon en daarna doorgroeide; een hoge score door verre
woningen zonder ringen is bouw ver van elke kern, bijvoorbeeld op een hard plan. De detailkaart zegt welke van de drie
het is: een dikke cirkel is een los cluster waar in het zichtjaar erna woningen in de ring kwamen, de kleur van een cel
het zichtjaar van zijn nieuwe woningen. De score is absoluut, dus een gemeente met veel nieuwbouw scoort eerder hoog dan
een kleine; daarom geeft het rapport er ook de gemeenten bij met het grootste aandeel van hun nieuwbouw in ringen en ver
van een kern. Met een tweede run staan de gemeenten met de grootste stijging van de score in de kern: dat is wat er tussen
de twee runs veranderde.

Waar een referentie ontbreekt. De BAG-referentie bestaat alleen voor het eerste zichtjaar: de startstand bevat de
BAG-nieuwbouw sinds het basisjaar en de vergunde panden, en daarna is er geen waargenomen nieuwbouw. Voor de ringwoningen
en de aangegroeide kiemen is er geen referentie, want de startstand heeft geen stand ervoor; de ijkmaten van de score zijn
daarom een oordeel en geen norm uit waarneming. De losse clusters van alleen werken hebben als referentie de werkclusters
die alleen uit de startstand komen.

Wat het niet kan. Het weet niet of een los cluster een boerenerf, een bedrijf of een geplande wijk is, en niet of verre
bouw op een hard plan ligt; daarvoor is de kaart. De BRT-woonkern dekt niet elke recente wijk, zodat een cluster tegen
een nieuwe wijk aan als los kan tellen. Sloop en verdichting zonder groei tellen niet mee. Het kijkt alleen naar wonen;
werklocaties komen alleen voor als kiem. En het vergelijkt twee runs alleen op hetzelfde raster.

| Bestand | Rol |
|---|---|
| `Kaarten.ps1` | twee toetsruns kiezen, het buurtgrid maken als het er nog niet is, en beide scripts per casus draaien |
| `rs_compare.py` | het meten: per bestand de verschillen, met diff-tif, verwarringsmatrix, steekproef en miniaturen |
| `rs_report.py` | het oordeel per bestand met toleranties, als pagina |
| `rs_indicators.py` | de buurtindicatoren, als pagina met twaalf figuren en een json met de kerncijfers |
| `tolerances.json` | de toleranties van rs_report: `default` en `rules` (fnmatch op de bestandsnaam, `cell_pct`) |
| `patroonkaarten.py` | de patroonkaarten van een run: meten, oordelen, kaarten en rapport |
| `patroondrempels.json` | de instellingen van patroonkaarten.py: `meten` (afstanden, tegelmaat) en `oordeel` (ijkmaten, drempel, aantallen kaarten) |

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
