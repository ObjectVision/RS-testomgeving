<#
================================================================================================
 Toets.ps1: de enginetoets uit model-RSopen#16, een commit doorrekenen onder het profiel van de baseline
================================================================================================

 WAT DIT SCRIPT DOET
   1. Zet de commit in een wegwerpkopie (git worktree) onder -Werkmap, met de machine-eigen
      bestanden erbij die niet in git staan (ConfigSettings.dms, Data, git.txt).
   2. Legt het profiel op: eerst dat van de baseline (alle instellingen zoals ze bij de laatste
      productierun stonden), daarover het testprofiel (een provincie, een of twee zichtjaren, de
      varianten). Zo rekent elke toets van een branch onder dezelfde instellingen en dezelfde data,
      en is elk verschil in de uitkomst een verschil in de rekenwijze.
   3. Toetst of de kopie nog laadt (parse-check), en draait dan Run2120.ps1 van die kopie: basisdata,
      variantdata, allocatie en diagnose, in een eigen LocalData die GeoDMS afleidt uit de mapnaam.
      De GeoDMS-versie is die welke Run2120.ps1 van de commit zelf noemt, tenzij -Exe iets anders zegt.
   4. Legt de uitvoer naast die van een eerdere run met Toetsrapport.py: standaard de baseline, met
      -Van een eerdere toetsrun van dezelfde branch, zodat groepen commits na elkaar te vergelijken zijn.

 EEN BRANCH, EEN LOG
   Een project is een branch (RuimteVoorWoningbouw, NL2120). Alles van een branch staat bij elkaar
   onder <Toetsmap>\<branch>: de baselines, toetslog.csv en de pagina toetslog.html. Vergelijk nooit
   over branches heen; dat geeft alleen verwarring.

 HOE START JE HET
   Dit script staat in RS-testomgeving, buiten de modelrepo. Start het vanuit de werkkopie van het model
   (de map met cfg\main.dms), of geef die werkkopie mee met -Repo. Het testprofiel is profielen\<branch>.csv
   naast dit script, dus NL2120.csv voor de branch NL2120.
   HEAD van de werkkopie tegen de baseline:
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Toets.ps1
   Een commit tegen de toetsrun van een eerdere commit (een ketting van groepen):
       pwsh ...\enginetoets\Toets.ps1 -Commit 964672dd -Van cd761d78
   Een andere werkkopie, met een fix die daar nog niet in zit:
       pwsh ...\enginetoets\Toets.ps1 -Repo C:\ProjDir\RSopen_NL2120 -Patch fix.patch
   Alleen rekenen, nog niet vergelijken (de run voor een baseline, of een groep die later in de ketting komt):
       pwsh ...\enginetoets\Toets.ps1 -Commit cd761d78 -ZonderVergelijking
   Alleen het rapport opnieuw maken van een run die er al staat:
       pwsh ...\enginetoets\Toets.ps1 -Commit 964672dd -Van cd761d78 -AlleenRapport

 PARAMETERS
   -Commit         Commit, tag of branch; standaard HEAD van -Repo.
   -Van            Waartegen vergeleken wordt: een commit waarvan al een toetsrun staat, of een LocalData-map.
                   Leeg is de baseline.
   -Baseline       Tag van de baseline (baseline/<datum>); leeg is de nieuwste. Het profiel en de bewaarde
                   uitvoer staan onder <Toetsmap>\<branch>\baseline_<datum>. Zonder baseline geldt alleen
                   het testprofiel.
   -Testprofiel    Csv met de instellingen van de toets; standaard profielen\<branch>.csv naast dit script.
                   Een rij run:Varianten noemt de varianten die meedraaien.
   -Varianten      De varianten, als het testprofiel ze niet noemt; standaard BAU.
   -Samenvatting   Wat er in de commits tussen -Van en -Commit zit, in een of twee zinnen, voor het log en
                   het rapport. Zonder deze tekst groepeert het rapport de commits op issuenummer.
   -Label          Achtervoegsel voor de mapnaam, zodat een commit meer dan een keer kan draaien.
   -Werkkopie      Neem de ongecommitte wijzigingen van de werkkopie mee (git diff HEAD op cfg en batch).
                   Alleen met -Commit HEAD. De patch komt in batch\log\werkkopie.patch van de kopie.
   -Repo           De werkkopie van het model waar de commit uit komt; standaard de huidige map. Die repo zelf
                   wordt niet aangeraakt, op git worktree add na.
   -Patch          Een patchbestand dat na het uitchecken op de kopie wordt gelegd, bijvoorbeeld een fix die
                   in die branch nog niet is gecommit. Komt in batch\log\patch_extern.patch van de kopie.
   -Exe            GeoDmsRun.exe; leeg is de versie die Run2120.ps1 van de commit zelf als standaard noemt.
   -MetIndicatorBasedata  Draai ook WriteBasedata/Generate_Run4_IndicatorenData, als Run2120.ps1 die kent.
   -ZonderVergelijking    Alleen rekenen; geen rapport en geen logregel.
   -AlleenRapport  Niet rekenen; de kopie en de LocalData van deze commit staan er al.
   -Opnieuw        Vervang een bestaande kopie en LocalData van dezelfde naam.
   -AlleenVoorbereiden    Stop na het profiel en de parse-check.
   -Toon           Open het rapport in de browser zodra het er is.

 UITVOER
   Wegwerpkopie:  <Werkmap>\<branch>_<sha>[_<label>]            (git worktree, weg te halen met git worktree remove)
   LocalData:     <LocalDataDir>\<branch>_<sha>[_<label>]       (de registersleutel LocalDataDir plus de mapnaam)
   Logs:          <kopie>\batch\log: profiel.md, omgeving.csv, profiel_effectief.csv, parse.log,
                  run2120\status.tsv met een log per stap, toetsrapport.md en toetsrapport.html.
   Log:           <Toetsmap>\<branch>\toetslog.csv en toetslog.html (Toetslog.py).
================================================================================================
#>
[CmdletBinding()]
param(
    [string]   $Commit       = 'HEAD',
    [string]   $Van          = '',
    [string]   $Baseline     = '',
    [string]   $Testprofiel  = '',
    [string[]] $Varianten    = @(),
    [string]   $Samenvatting = '',
    [string]   $Label        = '',
    [string]   $Exe          = '',
    [string]   $Werkmap      = 'C:\ProjDir\RSopen_toets',
    [string]   $Toetsmap     = 'C:\LocalData\RSopen_toets',
    [string]   $Scenario     = 'WLO_hoog',
    [string]   $Repo         = '',
    [string]   $Patch        = '',
    [switch]   $MetIndicatorBasedata,
    [switch]   $ZonderVergelijking,
    [switch]   $AlleenRapport,
    [switch]   $Toon,
    [switch]   $Werkkopie,
    [switch]   $Opnieuw,
    [switch]   $AlleenVoorbereiden
)

$ErrorActionPreference = 'Stop'
if (-not $Repo) { $Repo = (Get-Location).Path }
if (-not (Test-Path (Join-Path $Repo 'cfg\main.dms'))) { throw "geen cfg\main.dms in $Repo; start vanuit de werkkopie van het model of geef -Repo" }
if ($Patch -and -not (Test-Path $Patch)) { throw "patch niet gevonden: $Patch" }
$Python = 'python'
$StandaardExe = 'C:\Program Files\ObjectVision\GeoDms20.20.0.m\GeoDmsRun.exe'

function Write-Regel([string]$Tekst) { Write-Host ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $Tekst) }

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    $uit = & git -C $Repo @Argumenten 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Argumenten -join ' '): $uit" }
    return $uit
}

function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    & $Python @Argumenten
    if ($LASTEXITCODE -ne 0) { throw "python $($Argumenten[0]) mislukt (exit $LASTEXITCODE)" }
}

# ---------------------------------------------------------------- 1. de branch, de commit en zijn plek
$Project = (Invoke-Git rev-parse --abbrev-ref HEAD | Select-Object -First 1).Trim()
if (-not $Project -or $Project -eq 'HEAD') { $Project = Split-Path $Repo -Leaf }
$ProjectMap = Join-Path $Toetsmap $Project
# Het testprofiel hoort bij de branch: profielen\<branch>.csv naast dit script.
if (-not $Testprofiel) { $Testprofiel = Join-Path $PSScriptRoot "profielen\$Project.csv" }
if (-not (Test-Path $Testprofiel)) { throw "testprofiel niet gevonden: $Testprofiel; maak profielen\$Project.csv naast Toets.ps1 of geef -Testprofiel" }
$sha       = (Invoke-Git rev-parse --short=8 $Commit | Select-Object -First 1).Trim()
$onderwerp = (Invoke-Git log -1 --format=%s $sha | Select-Object -First 1)
$datum     = (Invoke-Git log -1 --format=%cs $sha | Select-Object -First 1)
$naam      = "${Project}_$sha" + $(if ($Label) { "_$Label" } else { '' })
$Kopie     = Join-Path $Werkmap $naam
$ldDir = $null
foreach ($sleutel in @("HKCU:\Software\ObjectVision\$env:COMPUTERNAME\GeoDMS", 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS')) {
    $ldDir = (Get-ItemProperty $sleutel -ErrorAction SilentlyContinue).LocalDataDir
    if ($ldDir) { break }
}
if (-not $ldDir) { $ldDir = 'C:\LocalData' }
$LocalData = Join-Path $ldDir $naam
$LogDir    = Join-Path $Kopie 'batch\log'

Write-Regel "branch    : $Project"
Write-Regel "commit    : $sha ($datum)  $onderwerp"
Write-Regel "kopie     : $Kopie"
Write-Regel "localdata : $LocalData"

# ---------------------------------------------------------------- 2. de baseline
$baseTag = $Baseline
if (-not $baseTag) {
    # Lange opties: een korte optie kan PowerShell lezen als afkorting van de parameter -Argumenten van Invoke-Git.
    $baseTag = (Invoke-Git tag --list 'baseline/*' --sort=-creatordate | Select-Object -First 1)
}
$baseMap = $null
$baseSha = ''
if ($baseTag) {
    $baseMap = Join-Path $ProjectMap ($baseTag -replace '/', '_')
    if (-not (Test-Path (Join-Path $baseMap 'profiel.csv'))) { throw "baseline $baseTag heeft geen profiel.csv in $baseMap" }
    # De commit achter de tag, niet het tagobject zelf: een geannoteerde tag heeft een eigen sha.
    $baseSha = (Invoke-Git rev-parse --short=8 "$baseTag^{commit}" | Select-Object -First 1).Trim()
    Write-Regel "baseline  : $baseTag ($baseSha)"
} else {
    Write-Regel "baseline  : geen; alleen het testprofiel wordt opgelegd"
}

# ---------------------------------------------------------------- 3. de wegwerpkopie
if (-not $AlleenRapport) {
    if ((Test-Path $Kopie) -or (Test-Path $LocalData)) {
        if (-not $Opnieuw) {
            throw "Er staat al een toets met de naam $naam (kopie of LocalData). Geef -Label voor een tweede, -Opnieuw om te vervangen, of -AlleenRapport."
        }
        Write-Regel "opruimen  : bestaande kopie en LocalData van $naam"
        if (Test-Path $Kopie)     { Invoke-Git worktree remove --force $Kopie | Out-Null }
        if (Test-Path $LocalData) { Remove-Item $LocalData -Recurse -Force }
    }
    Invoke-Git worktree prune | Out-Null
    New-Item -ItemType Directory -Path $Werkmap -Force | Out-Null
    Invoke-Git worktree add --detach $Kopie $sha | Out-Null
    foreach ($p in @('cfg\main\ConfigSettings.dms', 'git.txt')) {
        $bron = Join-Path $Repo $p
        if (Test-Path $bron) { Copy-Item $bron (Join-Path $Kopie $p) -Force }
    }
    if (Test-Path (Join-Path $Repo 'Data')) { Copy-Item (Join-Path $Repo 'Data') (Join-Path $Kopie 'Data') -Recurse -Force }
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-Regel "kopie     : klaar, met ConfigSettings.dms, Data en git.txt uit de werkkopie"
} elseif (-not (Test-Path $LocalData)) {
    throw "-AlleenRapport, maar er is geen LocalData $LocalData"
}
$Runner = Join-Path $Kopie 'batch\Run2120.ps1'
if (-not (Test-Path $Runner)) {
    throw "Deze commit heeft geen batch\Run2120.ps1; de toets kan alleen commits draaien die dat script kennen."
}

if ($Werkkopie -and -not $AlleenRapport) {
    $hoofd = (Invoke-Git rev-parse --short=8 HEAD | Select-Object -First 1).Trim()
    if ($hoofd -ne $sha) { throw "-Werkkopie hoort bij HEAD ($hoofd), niet bij $Commit ($sha)" }
    $werkPatch = Join-Path $LogDir 'werkkopie.patch'
    # Ongecommitte wijzigingen, inclusief nieuwe bestanden die nog niet gestaged zijn: die neemt git diff
    # niet mee, dus eerst met intent-to-add aanmelden en daarna weer loslaten.
    $nieuw = @(Invoke-Git ls-files --others --exclude-standard -- cfg batch | Where-Object { $_ })
    if ($nieuw.Count) { Invoke-Git add --intent-to-add -- @nieuw | Out-Null }
    # Git schrijft de patch zelf; via de PowerShell-pijp wordt hij als tekst herkodeerd en is hij daarna
    # geen geldige patch meer.
    Invoke-Git diff HEAD --binary "--output=$werkPatch" -- cfg batch | Out-Null
    if ($nieuw.Count) { Invoke-Git reset --quiet -- @nieuw | Out-Null }
    if ((Get-Item $werkPatch).Length -gt 0) {
        $uit = & git -C $Kopie apply --whitespace=nowarn $werkPatch 2>&1
        if ($LASTEXITCODE -ne 0) { throw "de werkkopiewijzigingen passen niet op de kopie: $uit" }
        $stat = (& git -C $Kopie diff --stat | Select-Object -Last 1)
        Write-Regel "werkkopie : ongecommitte wijzigingen toegepast ($stat)"
    } else {
        Write-Regel "werkkopie : geen ongecommitte wijzigingen in cfg of batch"
    }
}

if ($Patch -and -not $AlleenRapport) {
    $extern = Join-Path $LogDir 'patch_extern.patch'
    Copy-Item $Patch $extern -Force
    $uit = & git -C $Kopie apply --whitespace=nowarn $extern 2>&1
    if ($LASTEXITCODE -ne 0) { throw "de patch past niet op de kopie: $uit" }
    $stat = (& git -C $Kopie diff --stat | Select-Object -Last 1)
    Write-Regel "patch     : $Patch toegepast ($stat)"
}

# Momentopname van cfg met de patches erop en nog zonder het profiel, zodat het rapport kan zeggen wat
# er ongecommit op de commit lag zonder de overlay van het testprofiel als wijziging te tellen.
$patches = @(Get-ChildItem $LogDir -Filter '*.patch' -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 0 } | ForEach-Object { $_.FullName })
if ($patches.Count -and -not $AlleenRapport) {
    Copy-Item (Join-Path $Kopie 'cfg') (Join-Path $LogDir 'kandidaat\cfg') -Recurse -Force
}

# ---------------------------------------------------------------- 4. GeoDMS en de runner van deze commit
$runnerTekst = Get-Content $Runner -Raw
if (-not $Exe) {
    $m = [regex]::Match($runnerTekst, '\$Exe\s*=\s*''([^'']+GeoDmsRun\.exe)''')
    $Exe = if ($m.Success -and (Test-Path $m.Groups[1].Value)) { $m.Groups[1].Value } else { $StandaardExe }
}
if (-not (Test-Path $Exe)) { throw "GeoDmsRun niet gevonden: $Exe" }
$geodms = Split-Path (Split-Path $Exe -Parent) -Leaf
# Welke parameters kent Run2120.ps1 van deze commit? Een oudere commit kent -ZonderIndicatorBasedata niet.
$blok = [regex]::Match($runnerTekst, 'param\((.*?)\r?\n\)', 'Singleline').Groups[1].Value
$runnerParams = @([regex]::Matches($blok, '\$(\w+)') | ForEach-Object { $_.Groups[1].Value })
Write-Regel "geodms    : $geodms"

# ---------------------------------------------------------------- 5. het profiel opleggen
$profielen = @()
if ($baseMap) { $profielen += (Join-Path $baseMap 'profiel.csv') }
$profielen += $Testprofiel
if (-not $AlleenRapport) {
    Invoke-Python (Join-Path $PSScriptRoot 'Profiel.py') apply @profielen --map $Kopie --verslag (Join-Path $LogDir 'profiel.md')
}
$omgeving = @(Import-Csv (Join-Path $LogDir 'omgeving.csv') -Delimiter ';')
foreach ($r in $omgeving) { Set-Item -Path "Env:\$($r.naam)" -Value $r.waarde }
if (-not $AlleenRapport) {
    # Run2120.ps1 zet deze twee zelf; ze horen in het effectieve profiel zoals de run ze ziet.
    $envArgs = @('--env', 'StandAllocatieOntkoppeld=TRUE', '--env', 'VariantDataOntkoppeld=TRUE')
    foreach ($r in $omgeving) { $envArgs += @('--env', "$($r.naam)=$($r.waarde)") }
    Invoke-Python (Join-Path $PSScriptRoot 'Profiel.py') dump --map $Kopie --uit (Join-Path $LogDir 'profiel_effectief.csv') @envArgs
}

# De varianten: -Varianten, anders de rij run:Varianten van het testprofiel, anders BAU.
if (-not $Varianten.Count) {
    $rij = Import-Csv $Testprofiel -Delimiter ';' | Where-Object { $_.pad -eq 'run:Varianten' } | Select-Object -First 1
    $Varianten = if ($rij) { @($rij.waarde -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) } else { @('BAU') }
}
$casussen = @($Varianten | ForEach-Object { "${Scenario}_$_" })

# ---------------------------------------------------------------- 6. laadt de kopie nog
if (-not $AlleenRapport) {
    $parseLog = Join-Path $LogDir 'parse.log'
    & $Exe "/L$parseLog" (Join-Path $Kopie 'cfg\main.dms') '/ModelParameters/StudyArea' 2>&1 | Out-Null
    $code = $LASTEXITCODE
    $fouten = @(Select-String -Path $parseLog -Pattern '\[E\]' -ErrorAction SilentlyContinue)
    if ($code -ne 0 -or $fouten.Count -gt 0) {
        $fouten | Select-Object -First 10 | ForEach-Object { Write-Host "   $($_.Line)" }
        throw "De kopie laadt niet na het profiel (exit $code, $($fouten.Count) foutregels); zie $parseLog"
    }
    Write-Regel "parse     : de kopie laadt met het profiel"
    if ($AlleenVoorbereiden) {
        Write-Regel "klaar     : alleen voorbereid. Profiel in $LogDir\profiel.md, kopie in $Kopie"
        return
    }
}

# ---------------------------------------------------------------- 7. de run
$prof = Import-Csv (Join-Path $LogDir 'profiel_effectief.csv') -Delimiter ';'
function Get-Getal([string]$pad, [int]$standaard = -1) {
    $r = $prof | Where-Object { $_.pad -eq $pad } | Select-Object -First 1
    if (-not $r) {
        if ($standaard -ge 0) { return $standaard }
        throw "$pad niet in het effectieve profiel"
    }
    return [int](($r.waarde -replace '[^\d]', ''))
}
$eerste  = Get-Getal 'ModelParameters/Model_FirstZichtjaar'
$laatste = Get-Getal 'ModelParameters/Model_FinalYear'
$stap    = Get-Getal 'ModelParameters/Model_ZichtjaarInterval' 10   # ouder dan 1 oktober 2026: altijd tien jaar
$zichtjaren = @(); for ($j = $eerste; $j -le $laatste; $j += $stap) { $zichtjaren += "Y$j" }

if (-not $AlleenRapport) {
    Write-Regel "run       : $Scenario, varianten $($Varianten -join ', '), zichtjaren $($zichtjaren -join ', '), diagnose na elk zichtjaar"
    New-Item -ItemType Directory -Path $LocalData -Force | Out-Null
    @(
        "sleutel`twaarde",
        "project`t$Project", "commit`t$sha", "datum`t$datum", "onderwerp`t$onderwerp",
        "geodms`t$geodms", "testprofiel`t$(Split-Path $Testprofiel -Leaf)", "baseline`t$baseTag",
        "varianten`t$($Varianten -join ',')", "zichtjaren`t$($zichtjaren -join ',')",
        "patches`t$(($patches | ForEach-Object { Split-Path $_ -Leaf }) -join ',')",
        "start`t$(Get-Date -Format 's')"
    ) | Set-Content (Join-Path $LocalData 'toets.tsv') -Encoding UTF8

    $totaal = [Diagnostics.Stopwatch]::StartNew()
    $runArgs = @{ Exe = $Exe; Cfg = (Join-Path $Kopie 'cfg\main.dms'); LocalData = $LocalData; LogDir = (Join-Path $LogDir 'run2120')
                  Scenario = $Scenario; Varianten = $Varianten; DiagnoseNaZichtjaar = $zichtjaren }
    if (-not $MetIndicatorBasedata -and $runnerParams -contains 'ZonderIndicatorBasedata') { $runArgs.ZonderIndicatorBasedata = $true }
    foreach ($k in @($runArgs.Keys)) {
        if ($runnerParams.Count -and $runnerParams -notcontains $k) { Write-Regel "runner    : kent -$k niet, weggelaten"; $runArgs.Remove($k) }
    }
    if ($runnerParams.Count -and ($runnerParams -notcontains 'ZonderIndicatorBasedata') -and ($runnerParams -contains 'SkipBasedata')) {
        # Een runner van voor 1 oktober 2026 draait Run1 tot en met Run3 van de basisdata in een proces en strandt
        # op een lege LocalData: de kolommen van de mmd die Run1 schrijft bestaan in dat proces nog niet
        # (Unknown identifier AfleidingPandType/Results/WP5_rel). Daarom hier elke stap in een eigen proces, en
        # de runner daarna met -SkipBasedata; die slaat dan ook Run4 over, net als de nieuwe runner zonder
        # -MetIndicatorBasedata.
        $runLog = Join-Path $LogDir 'run2120'
        New-Item -ItemType Directory -Path $runLog -Force | Out-Null
        $status = Join-Path $runLog 'status.tsv'
        if (-not (Test-Path $status)) { "tijd`tstap`titem`texit`tseconden" | Set-Content $status -Encoding UTF8 }
        $env:StandAllocatieOntkoppeld = 'TRUE'
        $env:VariantDataOntkoppeld    = 'TRUE'
        foreach ($n in 1..3) {
            $item = "/WriteBasedata/Generate_Run$n"
            $stap = "basedata-run$n"
            $log  = Join-Path $runLog ("{0}_{1}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'), $stap)
            Write-Regel "start     : $stap (eigen proces; de runner van deze commit kent dat nog niet)"
            $sw = [Diagnostics.Stopwatch]::StartNew()
            & $Exe "/L$log" '/S1' '/S2' '/S3' (Join-Path $Kopie 'cfg\main.dms') $item 2>&1 | Out-Null
            $code = $LASTEXITCODE
            $sw.Stop()
            $sec = [math]::Round($sw.Elapsed.TotalSeconds, 1)
            "{0}`t{1}`t{2}`t{3}`t{4}" -f (Get-Date -Format 's'), $stap, $item, $code, $sec | Add-Content $status -Encoding UTF8
            $fouten = @(Select-String -Path $log -Pattern '\[E\]' -ErrorAction SilentlyContinue)
            if ($code -ne 0 -or $fouten.Count -gt 0) {
                $fouten | Select-Object -First 15 | ForEach-Object { Write-Host "   $($_.Line)" }
                throw "Stap $stap mislukt (exit $code, $($fouten.Count) foutregels); zie $log"
            }
            Write-Regel "klaar     : $stap ($([math]::Round($sec / 60, 1)) min)"
        }
        $runArgs.SkipBasedata = $true
    }
    # Valt de runner om (een casus die niet rekent op deze commit), dan is dat een uitkomst en geen reden om
    # zonder rapport te stoppen: wat er wel staat wordt vergeleken en het rapport zegt welke casus ontbreekt.
    $runFout = ''
    try { & $Runner @runArgs } catch { $runFout = $_.Exception.Message; Write-Regel "run       : AFGEBROKEN: $runFout" }
    $totaal.Stop()
    Write-Regel "run       : klaar in $([math]::Round($totaal.Elapsed.TotalMinutes, 1)) min"

    # Rekentijd en piekgeheugen per stap naast de uitvoer, zodat het rapport ze naast die van de andere kant legt.
    Invoke-Python (Join-Path $PSScriptRoot 'Runinfo.py') --status (Join-Path $LogDir 'run2120\status.tsv') --logs (Join-Path $LogDir 'run2120') --uit (Join-Path $LocalData 'run.tsv')

    # Diagnose/GenerateAll is een item: een controle die omvalt neemt alle andere mee en de koptabel blijft
    # leeg. Levert hij voor een zichtjaar te weinig op, vraag de controles dan los; GeoDmsRun werkt ze na
    # elkaar af en gaat na een fout door met de volgende.
    $diagMap = Join-Path $LocalData 'Diagnose'
    foreach ($casus in $casussen) {
        foreach ($y in $zichtjaren) {
            if (-not (Test-Path (Join-Path $LocalData "Allocatie\$casus\Stand$y"))) { continue }   # geen stand, dus ook geen diagnose
            $geschreven = @(Get-ChildItem $diagMap -Filter "${casus}_${y}_*.txt" -ErrorAction SilentlyContinue).Count
            if ($geschreven -ge 10) { continue }
            $namen = @(& $Python (Join-Path $PSScriptRoot 'Profiel.py') namen --map $Kopie --pad 'Diagnose/Checks/name' 2>$null | Where-Object { $_ })
            if (-not $namen.Count) { Write-Regel "diagnose  : GenerateAll liet voor $casus $y $geschreven controlewaarden na en de Checks-tabel is niet te lezen; geen losse ronde"; continue }
            Write-Regel "diagnose  : GenerateAll liet voor $casus $y $geschreven controlewaarden na; de $($namen.Count) controles los opvragen"
            $env:DiagCasus = $casus
            $env:DiagJaar  = "'$y'"
            $env:StandAllocatieOntkoppeld = 'TRUE'
            $env:VariantDataOntkoppeld    = 'TRUE'
            $items = @($namen | ForEach-Object { "/Diagnose/Resultaten/$_/Waarde" })
            $dlog = Join-Path $LogDir "diagnose_los_${casus}_$y.log"
            & $Exe "/L$dlog" '/S1' '/S2' '/S3' (Join-Path $Kopie 'cfg\main.dms') @items 2>&1 | Out-Null
            $nu = @(Get-ChildItem $diagMap -Filter "${casus}_${y}_*.txt" -ErrorAction SilentlyContinue).Count
            $fouten = @(Select-String -Path $dlog -Pattern '\[E\]' -ErrorAction SilentlyContinue).Count
            Write-Regel "diagnose  : $nu controlewaarden voor $casus $y na de losse ronde, $fouten foutregels in $dlog"
        }
    }
    if ($runFout) { Add-Content (Join-Path $LocalData 'toets.tsv') "afgebroken`t$runFout" -Encoding UTF8 }
    Add-Content (Join-Path $LocalData 'toets.tsv') "klaar`t$(Get-Date -Format 's')" -Encoding UTF8
}

if ($ZonderVergelijking) {
    Write-Regel "klaar     : zonder vergelijking. De uitvoer staat in $LocalData"
    return
}

# ---------------------------------------------------------------- 8. het rapport
$vanMap = ''
$naamVan = ''
$refArgs = @()
$patchesVan = @()
if ($Van -and (Test-Path $Van)) {
    $vanMap = $Van
    $naamVan = Split-Path $Van -Leaf
    if ($naamVan -match "^${Project}_([0-9a-f]{7,40})(_|$)") {
        $naamVan = $Matches[1]
        $refArgs = @('--repo', $Repo, '--ref-a', $naamVan, '--ref-b', $sha)
    }
} elseif ($Van) {
    $vanSha = (Invoke-Git rev-parse --short=8 $Van | Select-Object -First 1).Trim()
    $kandidaten = @(Get-ChildItem $ldDir -Directory -Filter "${Project}_${vanSha}*" -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'Allocatie') } | Sort-Object Name)
    if (-not $kandidaten.Count) { throw "geen toetsrun van $vanSha gevonden onder $ldDir (${Project}_$vanSha*); draai die commit eerst met -ZonderVergelijking" }
    $vanMap = $kandidaten[0].FullName
    $naamVan = $vanSha
    $refArgs = @('--repo', $Repo, '--ref-a', $vanSha, '--ref-b', $sha)
} elseif ($baseMap) {
    $vanMap = Join-Path $baseMap 'testprofiel'
    $naamVan = $baseSha
    $refArgs = @('--repo', $Repo, '--ref-a', $baseSha, '--ref-b', $sha)
}
if (-not $vanMap) {
    Write-Regel "rapport   : geen vergelijking, want er is geen baseline en geen -Van. De uitvoer staat in $LocalData"
    return
}
if (-not (Test-Path $vanMap)) { throw "de run om tegen te vergelijken bestaat niet: $vanMap" }
# De patches die op de andere kant lagen, zodat het rapport ze tegen de eigen patches kan wegstrepen.
$kopieVan = Join-Path $Werkmap (Split-Path $vanMap -Leaf)
foreach ($map in @($vanMap, (Join-Path $kopieVan 'batch\log'))) {
    $patchesVan += @(Get-ChildItem $map -Filter '*.patch' -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 0 } | ForEach-Object { $_.FullName })
}
if ($refArgs.Count) {
    if ($patches.Count) {
        $refArgs += @('--kopie-b', (Join-Path $LogDir 'kandidaat'))
        foreach ($pt in $patches) { $refArgs += @('--patch-b', $pt) }
    }
    foreach ($pt in $patchesVan) { $refArgs += @('--patch-a', $pt) }
}
$casusArgs = @(); foreach ($c in $casussen) { $casusArgs += @('--casus', $c) }
$rapport = Join-Path $LogDir 'toetsrapport.md'
$pagina  = Join-Path $LogDir 'toetsrapport.html'
$logCsv  = Join-Path $ProjectMap 'toetslog.csv'
New-Item -ItemType Directory -Path $ProjectMap -Force | Out-Null
$samenvattingArgs = @(); if ($Samenvatting) { $samenvattingArgs = @('--samenvatting', $Samenvatting) }
Invoke-Python (Join-Path $PSScriptRoot 'Toetsrapport.py') --a $vanMap --b $LocalData --naam-a $naamVan --naam-b $sha `
    @casusArgs --uit $rapport --html $pagina --log $logCsv @samenvattingArgs @refArgs
Write-Regel "rapport   : $rapport"
Get-Content $rapport -TotalCount 8 | ForEach-Object { Write-Host "   $_" }
# Het log van alle toetsen van deze branch als pagina, met de rapporten eronder; dat is de pagina om te delen.
Invoke-Python (Join-Path $PSScriptRoot 'Toetslog.py') --log $logCsv --uit (Join-Path $ProjectMap 'toetslog.html') --titel "Enginetoets $Project"
if ($Toon) { Start-Process $pagina }
