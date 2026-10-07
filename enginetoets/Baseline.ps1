<#
================================================================================================
 Baseline.ps1: een commit tot baseline maken voor de enginetoets uit model-RSopen#16
================================================================================================

 WAT DIT SCRIPT DOET
   De baseline van een branch is de commit waar alle toetsen van die branch tegen rekenen: de laatste
   productierun. Een baseline is drie dingen die bij elkaar horen en daarna niet meer veranderen: een
   git-tag baseline/<datum> op de commit, het profiel van die commit (alle instellingen op hun
   productiewaarde, plus de omgevingsvariabelen; elke latere toets rekent onder dit profiel) en de
   bewaarde uitvoer van de toetsrun van die commit onder het testprofiel. Dit script maakt die drie:
   1. Draait de toetsrun van de commit als die er nog niet staat (Toets.ps1 -ZonderVergelijking).
   2. Dumpt het profiel van de commit zoals hij in git staat naar <Toetsmap>\<branch>\baseline_<datum>\profiel.csv.
   3. Kopieert uit de LocalData van de toetsrun de mappen Allocatie, Diagnose en BaseData\StandBasisjaar
      naar ...\baseline_<datum>\testprofiel\, met het effectieve profiel van die run ernaast.
   4. Zet de tag baseline/<datum> op de commit, lokaal, en schrijft een regel BASELINE in het toetslog.

 HOE START JE HET (vanuit de werkkopie van het model, of met -Repo)
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Baseline.ps1 -Commit a4fb0b15 -Omschrijving "de laatste productierun"
   Het script toont wat het gaat doen en vraagt om een ja; -Ja slaat die vraag over.

 PARAMETERS
   -Commit        De commit die baseline wordt; standaard HEAD.
   -Run           De LocalData-map van een toetsrun van die commit die er al staat; leeg laat het script
                  de run zelf maken, met het label baseline.
   -Omschrijving  Waarom deze commit de baseline is, in een zin; komt in het log.
   -Datum         De datum in de tagnaam, standaard de commitdatum (jjjj-mm-dd). Een baseline die al
                  bestaat wordt niet overschreven; kies dan een andere datum of haal de oude eerst weg.
   -Repo, -Testprofiel, -Patch, -Varianten, -Scenario, -MetIndicatorBasedata  Gaan door naar Toets.ps1.
   -Toetsmap      Waar de baselines en het log per branch staan; standaard C:\LocalData\RSopen_toets.
   -Ja            Geen bevestiging vragen.
================================================================================================
#>
[CmdletBinding()]
param(
    [string]   $Commit       = 'HEAD',
    [string]   $Run          = '',
    [string]   $Datum        = '',
    [string]   $Omschrijving = '',
    [string]   $Toetsmap     = 'C:\LocalData\RSopen_toets',
    [string]   $Werkmap      = 'C:\ProjDir\RSopen_toets',
    [string]   $Repo         = '',
    [string]   $Testprofiel  = '',
    [string]   $Patch        = '',
    [string[]] $Varianten    = @(),
    [string]   $Scenario     = 'WLO_hoog',
    [switch]   $MetIndicatorBasedata,
    [switch]   $Ja
)

$ErrorActionPreference = 'Stop'
if (-not $Repo) { $Repo = (Get-Location).Path }
if (-not (Test-Path (Join-Path $Repo 'cfg\main.dms'))) { throw "geen cfg\main.dms in $Repo; start vanuit de werkkopie van het model of geef -Repo" }

function Write-Regel([string]$Tekst) { Write-Host ("{0}  {1}" -f (Get-Date -Format 'HH:mm:ss'), $Tekst) }

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    $uit = & git -C $Repo @Argumenten 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Argumenten -join ' '): $uit" }
    return $uit
}

$Project = (Invoke-Git rev-parse --abbrev-ref HEAD | Select-Object -First 1).Trim()
if (-not $Project -or $Project -eq 'HEAD') { $Project = Split-Path $Repo -Leaf }
$ProjectMap  = Join-Path $Toetsmap $Project
$sha         = (Invoke-Git rev-parse --short=8 $Commit | Select-Object -First 1).Trim()
$onderwerp   = (Invoke-Git log -1 --format=%s $sha | Select-Object -First 1)
$commitDatum = (Invoke-Git log -1 --format=%cs $sha | Select-Object -First 1)
if (-not $Datum) { $Datum = $commitDatum }
$tag = "baseline/$Datum"
$map = Join-Path $ProjectMap ("baseline_$Datum")

if (Invoke-Git tag --list $tag) { throw "tag $tag bestaat al; kies een andere -Datum" }
if (Test-Path $map) { throw "map $map bestaat al; kies een andere -Datum of haal hem eerst weg" }

$ldDir = $null
foreach ($sleutel in @("HKCU:\Software\ObjectVision\$env:COMPUTERNAME\GeoDMS", 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS')) {
    $ldDir = (Get-ItemProperty $sleutel -ErrorAction SilentlyContinue).LocalDataDir
    if ($ldDir) { break }
}
if (-not $ldDir) { $ldDir = 'C:\LocalData' }

Write-Regel "branch    : $Project"
Write-Regel "commit    : $sha ($commitDatum)  $onderwerp"
Write-Regel "tag       : $tag"
Write-Regel "map       : $map"
if ($Run) { Write-Regel "run       : $Run (bestaande toetsrun)" } else { Write-Regel "run       : wordt gemaakt met Toets.ps1 -Label baseline -ZonderVergelijking" }
if ($Omschrijving) { Write-Regel "waarom    : $Omschrijving" }

if (-not $Ja) {
    $antwoord = Read-Host "Dit wordt de baseline van $Project. Doorgaan (ja/nee)"
    if ($antwoord -ne 'ja') { Write-Regel "gestopt   : niets gedaan"; return }
}

# ---------------------------------------------------------------- 1. de toetsrun
if (-not $Run) {
    $Run = Join-Path $ldDir "${Project}_${sha}_baseline"
    if (Test-Path (Join-Path $Run 'Allocatie')) {
        Write-Regel "run       : $Run staat er al en wordt gebruikt"
    } else {
        $toetsArgs = @{ Commit = $sha; Label = 'baseline'; ZonderVergelijking = $true; Repo = $Repo; Scenario = $Scenario; Werkmap = $Werkmap; Toetsmap = $Toetsmap }
        if ($Testprofiel) { $toetsArgs.Testprofiel = $Testprofiel }
        if ($Patch)       { $toetsArgs.Patch = $Patch }
        if ($Varianten.Count) { $toetsArgs.Varianten = $Varianten }
        if ($MetIndicatorBasedata) { $toetsArgs.MetIndicatorBasedata = $true }
        if (Test-Path $Run) { $toetsArgs.Opnieuw = $true }
        & (Join-Path $PSScriptRoot 'Toets.ps1') @toetsArgs
    }
}
if (-not (Test-Path $Run)) { throw "toetsrun niet gevonden: $Run" }
$casussen = @(Get-ChildItem (Join-Path $Run 'Allocatie') -Directory -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
if (-not $casussen.Count) { throw "de toetsrun heeft geen Allocatie\<casus>; is hij wel tot en met de allocatie gekomen?" }
foreach ($casus in $casussen) {
    if (-not (Get-ChildItem (Join-Path $Run "Allocatie\$casus") -Directory -Filter 'StandY*' -ErrorAction SilentlyContinue)) {
        throw "de toetsrun heeft geen StandY-map onder Allocatie\$casus"
    }
}
if (-not (Test-Path (Join-Path $Run 'Diagnose'))) { throw "de toetsrun mist Diagnose; is hij wel tot en met de diagnose gekomen?" }
$kopie = Join-Path $Werkmap (Split-Path $Run -Leaf)

# ---------------------------------------------------------------- 2. profiel, uitvoer, tag, log
New-Item -ItemType Directory -Path $map -Force | Out-Null
& python (Join-Path $PSScriptRoot 'Profiel.py') dump --repo $Repo --ref $sha --uit (Join-Path $map 'profiel.csv')
if ($LASTEXITCODE -ne 0) { throw 'profiel dumpen mislukt' }

$doel = Join-Path $map 'testprofiel'
foreach ($sub in @('Allocatie', 'Diagnose', 'BaseData\StandBasisjaar')) {
    $bron = Join-Path $Run $sub
    if (Test-Path $bron) {
        New-Item -ItemType Directory -Path (Join-Path $doel $sub) -Force | Out-Null
        Copy-Item (Join-Path $bron '*') (Join-Path $doel $sub) -Recurse -Force
        Write-Regel "gekopieerd: $sub"
    }
}
foreach ($bestand in @('run.tsv', 'toets.tsv')) {
    $bron = Join-Path $Run $bestand
    if (Test-Path $bron) { Copy-Item $bron (Join-Path $doel $bestand) -Force }
}
$effectief = Join-Path $kopie 'batch\log\profiel_effectief.csv'
if (Test-Path $effectief) { Copy-Item $effectief (Join-Path $doel 'profiel_effectief.csv') -Force }
# De patches die op de toetsrun lagen gaan mee, zodat een latere toets ze tegen zijn eigen patches kan wegstrepen.
Get-ChildItem (Join-Path $kopie 'batch\log') -Filter '*.patch' -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 0 } |
    ForEach-Object { Copy-Item $_.FullName (Join-Path $doel $_.Name) -Force; Write-Regel "gekopieerd: $($_.Name)" }

@(
    "commit`t$sha",
    "onderwerp`t$onderwerp",
    "datum`t$Datum",
    "commitdatum`t$commitDatum",
    "omschrijving`t$Omschrijving",
    "toetsrun`t$Run",
    "casussen`t$($casussen -join ',')",
    "gemaakt`t$(Get-Date -Format 's')"
) | Set-Content (Join-Path $map 'baseline.tsv') -Encoding UTF8

# Lange opties: een korte optie als -a leest PowerShell als afkorting van de parameter -Argumenten van Invoke-Git.
Invoke-Git tag --annotate $tag $sha --message "Baseline $Datum van $Project voor de enginetoets (#16): $onderwerp" | Out-Null
# Een regel in het toetslog, zodat op de pagina te zien is vanaf welke commit de toetsen rekenen.
$logCsv = Join-Path $ProjectMap 'toetslog.csv'
& python (Join-Path $PSScriptRoot 'Toetslog.py') --log $logCsv --baseline $tag --commit $sha --datum $commitDatum --samenvatting $Omschrijving | Out-Null
& python (Join-Path $PSScriptRoot 'Toetslog.py') --log $logCsv --uit (Join-Path $ProjectMap 'toetslog.html') --titel "Enginetoets $Project" | Out-Null
Write-Regel "klaar     : $tag staat op $sha, profiel en uitvoer in $map. De tag is lokaal; push hem met git push origin $tag als een andere machine hem moet kennen."
