<#
================================================================================================
 Kaarten.ps1: kaarten en grafieken van het verschil tussen twee toetsruns (RS-testomgeving, map kaarten)
================================================================================================

 WAT DIT SCRIPT DOET
   De enginetoets zegt of en hoeveel twee commits verschillen; dit script laat zien waar en in welke
   vorm, in kaarten en grafieken. Het legt twee toetsruns van dezelfde branch naast elkaar met de twee
   scripts in deze map:
     rs_compare.py + rs_report.py   per kaart van het zichtjaar de verschilcellen (diff-tif, verwarringsmatrix,
                                    steekproef met coordinaten, miniaturen A, B en verschil) in een pagina;
     rs_indicators.py               per CBS-buurt waar de woning- en banengroei landt en hoe compact: twaalf
                                    figuren (groei per buurt, nieuwe cellen, verdichting, dichtheid, Lorenz,
                                    clustergrootte, randdichtheid en linten, afstand tot bestaand bebouwd).
   Het buurtgrid dat rs_indicators nodig heeft (het buurtnummer per cel, op het raster van het
   studiegebied) maakt dit script eenmalig per branch en studiegebied met GeoDMS uit de kopie van de
   commit, en bewaart het onder <Toetsmap>\<branch>\buurtgrid.

 HOE START JE HET (vanuit de werkkopie van het model, of met -Repo)
       pwsh C:\ProjDir\_Tools\RS-testomgeving\kaarten\Kaarten.ps1 -Commit a3309144 -Van 3827fbed
   Zonder -Van is de andere kant de baseline van de branch. Beide commits moeten een toetsrun hebben
   (Toets.ps1), want dit script rekent niets door.

 PARAMETERS
   -Commit      De commit (B); standaard HEAD van -Repo.
   -Van         De commit om tegen te vergelijken (A); leeg is de baseline.
   -Baseline    Tag van de baseline; leeg is de nieuwste.
   -Casus       Een casus (WLO_hoog_BAU); leeg is elke casus die beide runs hebben.
   -Zichtjaar   Y2040; leeg is het laatste zichtjaar van de run van B.
   -Exe         GeoDmsRun.exe voor het buurtgrid; leeg is de versie uit Run2120.ps1 van de kopie.
   -Toon        Open de pagina's in de browser.
   -Repo, -Werkmap, -Toetsmap   Als bij Toets.ps1.

 UITVOER
   <Toetsmap>\<branch>\kaarten\<A>_<B>\verschilkaarten_<casus>_<jaar>\report.html
   <Toetsmap>\<branch>\kaarten\<A>_<B>\buurtindicatoren_<casus>_<jaar>\indicatoren.html
================================================================================================
#>
[CmdletBinding()]
param(
    [string] $Commit    = 'HEAD',
    [string] $Van       = '',
    [string] $Baseline  = '',
    [string] $Casus     = '',
    [string] $Zichtjaar = '',
    [string] $Exe       = '',
    [string] $Repo      = '',
    [string] $Werkmap   = 'C:\ProjDir\RSopen_toets',
    [string] $Toetsmap  = 'C:\LocalData\RSopen_toets',
    [switch] $Toon
)

$ErrorActionPreference = 'Stop'
if (-not $Repo) { $Repo = (Get-Location).Path }
if (-not (Test-Path (Join-Path $Repo 'cfg\main.dms'))) { throw "geen cfg\main.dms in $Repo; start vanuit de werkkopie van het model of geef -Repo" }
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

# ---------------------------------------------------------------- de branch, de runs
$Project = (Invoke-Git rev-parse --abbrev-ref HEAD | Select-Object -First 1).Trim()
if (-not $Project -or $Project -eq 'HEAD') { $Project = Split-Path $Repo -Leaf }
$ProjectMap = Join-Path $Toetsmap $Project
$ldDir = $null
foreach ($sleutel in @("HKCU:\Software\ObjectVision\$env:COMPUTERNAME\GeoDMS", 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS')) {
    $ldDir = (Get-ItemProperty $sleutel -ErrorAction SilentlyContinue).LocalDataDir
    if ($ldDir) { break }
}
if (-not $ldDir) { $ldDir = 'C:\LocalData' }

function Find-Toetsrun([string]$Sha) {
    # De LocalData van een toetsrun, zoals Toets.ps1 hem voor -Van zoekt: <ldDir>\<branch>_<sha>[_label] met Allocatie erin.
    $k = @(Get-ChildItem $ldDir -Directory -Filter "${Project}_${Sha}*" -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'Allocatie') })
    if (-not $k.Count) { throw "geen toetsrun van $Sha onder $ldDir (${Project}_${Sha}*); draai die commit eerst met Toets.ps1" }
    # De kale naam eerst, dan _baseline; een volle run (_vol, eigen instellingen) alleen als er niets anders is.
    $k = @($k | Sort-Object { if ($_.Name -eq "${Project}_$Sha") { 0 } elseif ($_.Name -like '*_baseline') { 1 } elseif ($_.Name -like '*_vol') { 3 } else { 2 } }, Name)
    return $k[0].FullName
}

$sha  = (Invoke-Git rev-parse --short=8 $Commit | Select-Object -First 1).Trim()
$runB = Find-Toetsrun $sha
if ($Van) {
    $vanSha = (Invoke-Git rev-parse --short=8 $Van | Select-Object -First 1).Trim()
    $runA = Find-Toetsrun $vanSha
} else {
    $baseTag = if ($Baseline) { $Baseline } else { (Invoke-Git tag --list 'baseline/*' --sort=-creatordate | Select-Object -First 1) }
    if (-not $baseTag) { throw "geen baseline op $Project en geen -Van" }
    $vanSha = (Invoke-Git rev-parse --short=8 "$baseTag^{commit}" | Select-Object -First 1).Trim()
    $runA = Join-Path (Join-Path $ProjectMap ($baseTag -replace '/', '_')) 'testprofiel'
    if (-not (Test-Path (Join-Path $runA 'Allocatie'))) { throw "de bewaarde uitvoer van de baseline ontbreekt: $runA" }
}
Write-Regel "A         : $vanSha  $runA"
Write-Regel "B         : $sha  $runB"

# Het studiegebied staat in de bestandsnamen van de stand: Footprint_<StudyArea>.tif.
$footprint = @(Get-ChildItem (Join-Path $runB 'BaseData\StandBasisjaar\Wonen') -Filter 'Footprint_*.tif' -ErrorAction SilentlyContinue)
if (-not $footprint.Count) { throw "geen BaseData\StandBasisjaar\Wonen\Footprint_<studiegebied>.tif in $runB" }
$suffix = $footprint[0].BaseName.Substring('Footprint_'.Length)

$casussen = if ($Casus) { @($Casus) } else {
    $a = @(Get-ChildItem (Join-Path $runA 'Allocatie') -Directory | ForEach-Object { $_.Name })
    @(Get-ChildItem (Join-Path $runB 'Allocatie') -Directory | Where-Object { $a -contains $_.Name } | ForEach-Object { $_.Name })
}
if (-not $casussen.Count) { throw "geen casus die beide runs hebben" }

# ---------------------------------------------------------------- het buurtgrid, eenmalig per branch en studiegebied
$buurtMap  = Join-Path $ProjectMap 'buurtgrid'
$buurtTif  = Join-Path $buurtMap "Buurt_$suffix.tif"
$buurtCsv  = Join-Path $buurtMap "Buurt_namen_$suffix.csv"
if (-not (Test-Path $buurtTif)) {
    $kopie = Join-Path $Werkmap (Split-Path $runB -Leaf)
    if (-not (Test-Path (Join-Path $kopie 'cfg\main.dms'))) { throw "het buurtgrid $buurtTif bestaat nog niet en de kopie $kopie is er niet om het mee te maken; draai Toets.ps1 -Commit $sha opnieuw" }
    if (-not $Exe) {
        $runner = Join-Path $kopie 'batch\Run2120.ps1'
        $m = if (Test-Path $runner) { [regex]::Match((Get-Content $runner -Raw), '\$Exe\s*=\s*''([^'']+GeoDmsRun\.exe)''') } else { $null }
        $Exe = if ($m -and $m.Success -and (Test-Path $m.Groups[1].Value)) { $m.Groups[1].Value } else { $StandaardExe }
    }
    if (-not (Test-Path $Exe)) { throw "GeoDmsRun niet gevonden: $Exe" }
    Write-Regel "buurtgrid : maken met $(Split-Path (Split-Path $Exe -Parent) -Leaf) uit $kopie"
    $dmsPad  = Join-Path $kopie 'cfg\main\Buurtgrid.dms'
    $mainPad = Join-Path $kopie 'cfg\main.dms'
    $mainOud = [System.IO.File]::ReadAllBytes($mainPad)
    $dms = @'
container Buurtgrid
:	Descr = "Tijdelijk exportitem van RS-testomgeving (kaarten\Kaarten.ps1): het CBS-buurtgrid en de buurtnamen van het studiegebied voor rs_indicators.py. Staat niet in de modelrepo."
{
	attribute<UInt32> Buurt (/Geography/AdminDomain) := /SourceData/RegioIndelingen/Buurt/Per_AdminDomain
	,	StorageName = "='%LocalDataProjDir%/Buurtgrid/Buurt_'+/ModelParameters/StudyArea+'.tif'"
	,	StorageType = "gdalwrite.grid";

	container Namen
	:	StorageName = "='%LocalDataProjDir%/Buurtgrid/Buurt_namen_'+/ModelParameters/StudyArea+'.csv'"
	,	StorageType = "gdalwrite.vect"
	{
		attribute<UInt32> id            (/SourceData/RegioIndelingen/Buurt) := id(/SourceData/RegioIndelingen/Buurt);
		attribute<String> name          (/SourceData/RegioIndelingen/Buurt) := /SourceData/RegioIndelingen/Buurt/name;
		attribute<String> Gemeente_name (/SourceData/RegioIndelingen/Buurt) := /SourceData/RegioIndelingen/Gemeente/name[point_in_polygon(centroid_or_mid(/SourceData/RegioIndelingen/Buurt/geometry), /SourceData/RegioIndelingen/Gemeente/geometry)];
	}
}
'@
    try {
        [System.IO.File]::WriteAllBytes($dmsPad, [System.Text.Encoding]::UTF8.GetBytes(($dms -replace "`r?`n", "`r`n")))
        $main = [System.Text.Encoding]::UTF8.GetString($mainOud)
        if ($main -notmatch 'Buurtgrid\.dms') {
            $main = $main -replace '(\t#include <WriteVariantData\.dms>\r?\n)', "`$1`t#include <Buurtgrid.dms>`r`n"
            if ($main -notmatch 'Buurtgrid\.dms') { throw "geen #include <WriteVariantData.dms> in $mainPad om bij aan te haken" }
            [System.IO.File]::WriteAllBytes($mainPad, [System.Text.Encoding]::UTF8.GetBytes($main))
        }
        New-Item -ItemType Directory -Path $buurtMap -Force | Out-Null
        $log = Join-Path $buurtMap "geodms_$suffix.log"
        & $Exe "/L$log" $mainPad '/Buurtgrid/Buurt' '/Buurtgrid/Namen' 2>&1 | Out-Null
        $code = $LASTEXITCODE
        $bron = Join-Path $runB 'Buurtgrid'
        if ($code -ne 0 -or -not (Test-Path (Join-Path $bron "Buurt_$suffix.tif"))) { throw "GeoDmsRun gaf exit $code zonder buurtgrid; zie $log" }
        foreach ($f in @("Buurt_$suffix.tif", "Buurt_$suffix.tfw", "Buurt_namen_$suffix.csv")) { Copy-Item (Join-Path $bron $f) $buurtMap -Force }
        Remove-Item $bron -Recurse -Force
    } finally {
        [System.IO.File]::WriteAllBytes($mainPad, $mainOud)
        Remove-Item $dmsPad -Force -ErrorAction SilentlyContinue
    }
    Write-Regel "buurtgrid : $buurtTif"
}

# ---------------------------------------------------------------- kaarten en indicatoren per casus
$uitMap = Join-Path (Join-Path $ProjectMap 'kaarten') "${vanSha}_$sha"
New-Item -ItemType Directory -Path $uitMap -Force | Out-Null
$paginas = @()
foreach ($c in $casussen) {
    $jaar = $Zichtjaar
    if (-not $jaar) {
        $jaren = @(Get-ChildItem (Join-Path $runB "Allocatie\$c") -Directory -Filter 'StandY*' | ForEach-Object { $_.Name.Substring(5) } | Sort-Object)
        if (-not $jaren.Count) { Write-Regel "overslaan : $c heeft geen StandY-map in B"; continue }
        $jaar = $jaren[-1]
    }
    if (-not (Test-Path (Join-Path $runA "Allocatie\$c\Stand$jaar"))) { Write-Regel "overslaan : $c $jaar ontbreekt in A"; continue }
    Write-Regel "kaarten   : $c $jaar"
    $kaarten = Join-Path $uitMap "verschilkaarten_${c}_$jaar"
    Invoke-Python (Join-Path $PSScriptRoot 'rs_compare.py') $runA $runB --out $kaarten --name-a $vanSha --name-b $sha --only "Allocatie/$c/Stand$jaar/*" --report
    $paginas += (Join-Path $kaarten 'report.html')
    Write-Regel "buurten   : $c $jaar"
    $indic = Join-Path $uitMap "buurtindicatoren_${c}_$jaar"
    Invoke-Python (Join-Path $PSScriptRoot 'rs_indicators.py') --run-a $runA --run-b $runB --name-a $vanSha --name-b $sha `
        --buurt $buurtTif --buurt-namen $buurtCsv --zichtjaar $jaar --casus $c --suffix $suffix --out $indic
    $paginas += (Join-Path $indic 'indicatoren.html')
}
if (-not $paginas.Count) { throw "niets vergeleken; geen casus met een zichtjaar aan beide kanten" }
Write-Regel "klaar     : $uitMap"
foreach ($p in $paginas) { Write-Host "   $p" }
if ($Toon) { foreach ($p in $paginas) { Start-Process $p } }
