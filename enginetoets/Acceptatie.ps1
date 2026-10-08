<#
================================================================================================
 Acceptatie.ps1: de volle run van een kandidaat naast de volle run van de baseline (model-RSopen#16, fase 3)
================================================================================================

 WAT DIT SCRIPT DOET
   De enginetoets (Toets.ps1) meet de rekenwijze onder het bevroren profiel van de baseline. De acceptatie
   is de andere vraag: mag deze commit de nieuwe baseline worden? Daarvoor draait de kandidaat met zijn
   eigen instellingen, over alle zichtjaren en de varianten van de productie, en legt dit script die run
   naast de volle run van de baseline:
   1. Zoekt de volle run van de kandidaat (<LocalDataDir>\<branch>_<sha>_vol, gemaakt met
      Toets.ps1 -EigenInstellingen -Label vol -Testprofiel profielen\<branch>_vol.csv) en die van de
      baseline (<Toetsmap>\<branch>\baseline_<datum>\vol, of <LocalDataDir>\<branch>_<baselinesha>_vol).
   2. Draait batch\ToetsOplevering.ps1 van de kandidaat op beide runs (de normen van de productie, zonder
      trap C), zodat per toets het oordeel aan beide kanten bekend is.
   3. Maakt het rapport met Acceptatierapport.py: instellingen en leveringen, de ketting van
      enginetoetsen uit het log, de koptabel per casus en zichtjaar, de normen naast elkaar; en zet een
      regel ACCEPTATIE in het toetslog van de branch.

 HOE START JE HET (vanuit de werkkopie van het model, of met -Repo)
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Toets.ps1 -Commit <sha> -Label vol -EigenInstellingen -Testprofiel <map>\profielen\<branch>_vol.csv -ZonderVergelijking
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Acceptatie.ps1 -Commit <sha> -Samenvatting "..."
   Is het akkoord:
       pwsh ...\Baseline.ps1 -Commit <sha> -Run <toetsrun> -Vol <volle run> -Omschrijving "..."

 PARAMETERS
   -Commit        De kandidaat; standaard HEAD.
   -Run           De volle run van de kandidaat; standaard <LocalDataDir>\<branch>_<sha>_vol.
   -BaselineRun   De volle run van de baseline; standaard de map vol van de baseline, anders
                  <LocalDataDir>\<branch>_<baselinesha>_vol.
   -Baseline      Tag van de baseline; leeg is de nieuwste.
   -Varianten     Standaard de rij run:Varianten van profielen\<branch>_vol.csv.
   -Samenvatting  Wat er sinds de baseline is veranderd, in een of twee zinnen, voor het log en het rapport.
   -Repo, -Toetsmap, -Werkmap, -Scenario, -Toon   Als bij Toets.ps1.
================================================================================================
#>
[CmdletBinding()]
param(
    [string]   $Commit       = 'HEAD',
    [string]   $Run          = '',
    [string]   $BaselineRun  = '',
    [string]   $Baseline     = '',
    [string[]] $Varianten    = @(),
    [string]   $Samenvatting = '',
    [string]   $Werkmap      = 'C:\ProjDir\RSopen_toets',
    [string]   $Toetsmap     = 'C:\LocalData\RSopen_toets',
    [string]   $Scenario     = 'WLO_hoog',
    [string]   $Repo         = '',
    [switch]   $Toon
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
function Invoke-Python {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Argumenten)
    & python @Argumenten
    if ($LASTEXITCODE -ne 0) { throw "python $($Argumenten[0]) mislukt (exit $LASTEXITCODE)" }
}

$Project = (Invoke-Git rev-parse --abbrev-ref HEAD | Select-Object -First 1).Trim()
if (-not $Project -or $Project -eq 'HEAD') { $Project = Split-Path $Repo -Leaf }
$ProjectMap = Join-Path $Toetsmap $Project
$sha   = (Invoke-Git rev-parse --short=8 $Commit | Select-Object -First 1).Trim()
$datum = (Invoke-Git log -1 --format=%cs $sha | Select-Object -First 1)
$ldDir = $null
foreach ($sleutel in @("HKCU:\Software\ObjectVision\$env:COMPUTERNAME\GeoDMS", 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS')) {
    $ldDir = (Get-ItemProperty $sleutel -ErrorAction SilentlyContinue).LocalDataDir
    if ($ldDir) { break }
}
if (-not $ldDir) { $ldDir = 'C:\LocalData' }

$baseTag = $Baseline
if (-not $baseTag) { $baseTag = (Invoke-Git tag --list 'baseline/*' --sort=-creatordate | Select-Object -First 1) }
if (-not $baseTag) { throw "geen baseline; maak er een met Baseline.ps1" }
$baseMap = Join-Path $ProjectMap ($baseTag -replace '/', '_')
$baseSha = (Invoke-Git rev-parse --short=8 "$baseTag^{commit}" | Select-Object -First 1).Trim()
if (-not $Run) { $Run = Join-Path $ldDir "${Project}_${sha}_vol" }
if (-not $BaselineRun) {
    $BaselineRun = Join-Path $baseMap 'vol'
    if (-not (Test-Path (Join-Path $BaselineRun 'Allocatie'))) { $BaselineRun = Join-Path $ldDir "${Project}_${baseSha}_vol" }
}
foreach ($paar in @(@('kandidaat', $Run), @('baseline', $BaselineRun))) {
    if (-not (Test-Path (Join-Path $paar[1] 'Allocatie'))) { throw "geen volle run van de $($paar[0]) in $($paar[1]); maak hem met Toets.ps1 -EigenInstellingen -Label vol" }
}
$Kopie  = Join-Path $Werkmap "${Project}_${sha}_vol"
$LogDir = Join-Path $Kopie 'batch\log'
if (-not (Test-Path (Join-Path $Kopie 'batch\ToetsOplevering.ps1'))) { throw "de kopie van de kandidaat ($Kopie) heeft geen batch\ToetsOplevering.ps1" }
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

if (-not $Varianten.Count) {
    $vp = Join-Path $PSScriptRoot "profielen\${Project}_vol.csv"
    $rij = if (Test-Path $vp) { Import-Csv $vp -Delimiter ';' | Where-Object { $_.pad -eq 'run:Varianten' } | Select-Object -First 1 } else { $null }
    $Varianten = if ($rij) { @($rij.waarde -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) } else { @('BAU') }
}
$casussen = @($Varianten | ForEach-Object { "${Scenario}_$_" })

Write-Regel "branch    : $Project"
Write-Regel "kandidaat : $sha ($datum), volle run $Run"
Write-Regel "baseline  : $baseTag ($baseSha), volle run $BaselineRun"
Write-Regel "varianten : $($Varianten -join ', ')"

# ---------------------------------------------------------------- de normen van ToetsOplevering op beide runs
$normen = @{}
foreach ($paar in @(@('baseline', $BaselineRun), @('kandidaat', $Run))) {
    $uit = Join-Path $LogDir "normen_$($paar[0]).md"
    Write-Regel "normen    : ToetsOplevering.ps1 van de kandidaat op de $($paar[0])"
    try {
        & (Join-Path $Kopie 'batch\ToetsOplevering.ps1') -LocalData $paar[1] -Cfg (Join-Path $Kopie 'cfg\main.dms') -Scenario $Scenario -Varianten $Varianten -Rapport $uit *> (Join-Path $LogDir "normen_$($paar[0]).log")
    } catch {
        Write-Regel "normen    : ToetsOplevering.ps1 viel om op de $($paar[0]): $($_.Exception.Message)"
    }
    if (Test-Path $uit) { $normen[$paar[0]] = $uit } else { Write-Regel "normen    : geen uitvoer voor de $($paar[0])" }
}

# ---------------------------------------------------------------- het rapport
$rapport = Join-Path $LogDir 'acceptatierapport.md'
$pagina  = Join-Path $LogDir 'acceptatierapport.html'
$logCsv  = Join-Path $ProjectMap 'toetslog.csv'
$argumenten = @('--a', $BaselineRun, '--b', $Run, '--naam-a', $baseSha, '--naam-b', $sha, '--repo', $Repo, '--ref-a', $baseSha, '--ref-b', $sha,
                '--uit', $rapport, '--html', $pagina, '--log', $logCsv)
foreach ($c in $casussen) { $argumenten += @('--casus', $c) }
if ($normen['baseline'])  { $argumenten += @('--normen-a', $normen['baseline']) }
if ($normen['kandidaat']) { $argumenten += @('--normen-b', $normen['kandidaat']) }
if ($Samenvatting) { $argumenten += @('--samenvatting', $Samenvatting) }
Invoke-Python (Join-Path $PSScriptRoot 'Acceptatierapport.py') @argumenten
Write-Regel "rapport   : $rapport"
Invoke-Python (Join-Path $PSScriptRoot 'Toetslog.py') --log $logCsv --uit (Join-Path $ProjectMap 'toetslog.html') --titel "Enginetoets $Project"
if ($Toon) { Start-Process $pagina }
