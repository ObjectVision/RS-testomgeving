<#
================================================================================================
 Setup.ps1: controleert of deze machine de enginetoets (Toets.ps1 hiernaast) kan draaien
================================================================================================

 WAT DIT SCRIPT DOET
   Loopt na wat Toets.ps1 en Baseline.ps1 nodig hebben en zegt per punt in gewone taal of het er
   staat, en zo niet wat je moet doen. Het verandert niets, op een kopie van ConfigSettings.dms.example
   na wanneer ConfigSettings.dms ontbreekt (met -MaakConfigSettings). Bedoeld om een keer te draaien
   op een machine die de toets nog niet kent, bijvoorbeeld bij PBL, en opnieuw na een installatie.

 HOE START JE HET (vanuit de werkkopie van het model, of met -Repo)
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Setup.ps1
   Exitcode 0 wanneer alles wat het oordeel nodig heeft er staat; 1 wanneer er iets ontbreekt.

 WAT ER NODIG IS
   Voor het oordeel (de hash van de standtifs, de controlewaarden, het statische deel):
     GeoDmsRun.exe van de versie die -Exe van Toets.ps1 noemt, git op het pad, PowerShell 7,
     Python 3.10 of hoger zonder pakketten, de registersleutel LocalDataDir van GeoDMS,
     cfg\main\ConfigSettings.dms, de map Data, en de bronmap achter SourceDataDir.
   Voor de doorklik (celverschillen in het rapport): de Python-pakketten numpy en tifffile.
   Voor de buurtfiguren van RS-testomgeving daarnaast scipy; die staan buiten dit script.
================================================================================================
#>
[CmdletBinding()]
param(
    [string] $Repo = '',
    [string] $Exe = 'C:\Program Files\ObjectVision\GeoDms20.20.0.m\GeoDmsRun.exe',
    [switch] $MaakConfigSettings
)

$ErrorActionPreference = 'Continue'
if (-not $Repo) { $Repo = (Get-Location).Path }
$script:Mis = 0

function Meld([string]$Oordeel, [string]$Wat, [string]$Toelichting) {
    $kleur = switch ($Oordeel) { 'OK' { 'Green' } 'ONTBREEKT' { 'Red' } default { 'Yellow' } }
    Write-Host ("{0,-10} {1,-34} {2}" -f $Oordeel, $Wat, $Toelichting) -ForegroundColor $kleur
    if ($Oordeel -eq 'ONTBREEKT') { $script:Mis++ }
}

function Test-Opdracht([string]$Naam) {
    $c = Get-Command $Naam -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

Write-Host "Setup voor de enginetoets in $Repo" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------- GeoDMS
if (Test-Path $Exe) {
    Meld 'OK' 'GeoDmsRun' $Exe
} else {
    $gevonden = @(Get-ChildItem 'C:\Program Files\ObjectVision' -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'GeoDmsRun.exe') } | Sort-Object Name | Select-Object -Last 3)
    $hint = if ($gevonden) { "niet op $Exe; wel gevonden: " + (($gevonden | ForEach-Object { $_.Name }) -join ', ') + ". Geef die versie mee met -Exe aan Toets.ps1, of installeer de versie uit Run2120.ps1." }
            else { "niet gevonden onder C:\Program Files\ObjectVision. Installeer GeoDMS (de versie uit batch\Run2120.ps1) van https://github.com/ObjectVision/GeoDMS/releases." }
    Meld 'ONTBREEKT' 'GeoDmsRun' $hint
}

$sleutel = Get-ItemProperty 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS' -ErrorAction SilentlyContinue
if ($sleutel -and $sleutel.LocalDataDir) {
    Meld 'OK' 'LocalDataDir (register)' "$($sleutel.LocalDataDir); de toets schrijft daar toets_<sha>_<label>"
} else {
    Meld 'ONTBREEKT' 'LocalDataDir (register)' 'start GeoDmsGui een keer en zet onder Tools, Options de LocalDataDir, bijvoorbeeld C:\LocalData'
}
if ($sleutel -and $sleutel.SourceDataDir) {
    if (Test-Path $sleutel.SourceDataDir) { Meld 'OK' 'SourceDataDir (register)' $sleutel.SourceDataDir }
    else { Meld 'ONTBREEKT' 'SourceDataDir (register)' "$($sleutel.SourceDataDir) bestaat niet; koppel de bronschijf of pas de sleutel aan in GeoDmsGui" }
} else {
    Meld 'ONTBREEKT' 'SourceDataDir (register)' 'zet in GeoDmsGui onder Tools, Options de SourceDataDir naar de map met de RSopen-brondata'
}

# ---------------------------------------------------------------- git, PowerShell, Python
$git = Test-Opdracht 'git'
if ($git) { Meld 'OK' 'git' ((& git --version) -join '') } else { Meld 'ONTBREEKT' 'git' 'installeer Git for Windows (https://git-scm.com) en open daarna een nieuw venster' }

if ($PSVersionTable.PSVersion.Major -ge 7) { Meld 'OK' 'PowerShell' $PSVersionTable.PSVersion.ToString() }
else { Meld 'ONTBREEKT' 'PowerShell' "versie $($PSVersionTable.PSVersion) draait; de scripts vragen PowerShell 7 (pwsh), winget install Microsoft.PowerShell" }

$py = Test-Opdracht 'python'
if ($py) {
    $v = (& python -c "import sys; print(sys.version_info[0], sys.version_info[1])") -split ' '
    if ([int]$v[0] -ge 3 -and [int]$v[1] -ge 10) { Meld 'OK' 'Python' "$($v[0]).$($v[1]) op $py" }
    else { Meld 'ONTBREEKT' 'Python' "versie $($v[0]).$($v[1]); de scripts vragen 3.10 of hoger (https://www.python.org/downloads/)" }
    foreach ($pakket in @('numpy', 'tifffile')) {
        & python -c "import $pakket" 2>$null
        if ($LASTEXITCODE -eq 0) { Meld 'OK' "Python-pakket $pakket" 'voor de doorklik op celniveau' }
        else { Meld 'OPTIONEEL' "Python-pakket $pakket" "niet aanwezig; het oordeel werkt zonder, de doorklik niet. Installeren: python -m pip install $pakket" }
    }
} else {
    Meld 'ONTBREEKT' 'Python' 'niet op het pad; installeer Python 3.10 of hoger (https://www.python.org/downloads/) met "Add to PATH" aangevinkt'
}

# ---------------------------------------------------------------- de werkkopie
$cs = Join-Path $Repo 'cfg\main\ConfigSettings.dms'
if (Test-Path $cs) {
    Meld 'OK' 'cfg\main\ConfigSettings.dms' 'machine-eigen paden aanwezig'
} elseif ($MaakConfigSettings -and (Test-Path "$cs.example")) {
    Copy-Item "$cs.example" $cs
    Meld 'GEMAAKT' 'cfg\main\ConfigSettings.dms' 'gekopieerd van het voorbeeld; loop de paden erin na'
} else {
    Meld 'ONTBREEKT' 'cfg\main\ConfigSettings.dms' 'kopieer ConfigSettings.dms.example naar ConfigSettings.dms en pas de paden aan, of draai dit script met -MaakConfigSettings'
}
if (Test-Path (Join-Path $Repo 'Data')) { Meld 'OK' 'Data' 'de map met de kleine bronnen naast cfg staat er' }
else { Meld 'ONTBREEKT' 'Data' 'de map Data naast cfg ontbreekt (CBS-kerncijfers, SOMERS, classificatietabellen); haal hem van de machine die de productie draait' }
if (Test-Path (Join-Path $Repo 'batch\Run2120.ps1')) { Meld 'OK' 'batch\Run2120.ps1' 'de runner die de toets per kopie aanroept' }
else { Meld 'ONTBREEKT' 'batch\Run2120.ps1' 'deze werkkopie heeft de runner niet; haal een nieuwere stand op' }
if ($git) {
    $vuil = @(& git -C $Repo status --porcelain 2>$null)
    if ($vuil.Count) { Meld 'LET OP' 'werkkopie' "$($vuil.Count) ongecommitte wijzigingen; Toets.ps1 toetst HEAD, met -Werkkopie ook deze wijzigingen" }
    else { Meld 'OK' 'werkkopie' 'schoon' }
    $tags = @(& git -C $Repo tag --list 'baseline/*' 2>$null)
    if ($tags.Count) {
        $nieuwste = @($tags | Sort-Object)[-1]   # @( ) want een enkele tag komt anders als string terug en [-1] is dan een letter
        Meld 'OK' 'baseline' "$($tags.Count) baseline(s), nieuwste $nieuwste"
    }
    else { Meld 'LET OP' 'baseline' 'geen tag baseline/*; haal de tags op met git fetch --tags, of maak de baseline met Baseline.ps1' }
}
$toetsmap = 'C:\LocalData\RSopen_toets'
if (Test-Path $toetsmap) { Meld 'OK' 'toetsmap' "$toetsmap (per branch een map met de baselines en het toetslog)" }
else { Meld 'LET OP' 'toetsmap' "$toetsmap bestaat nog niet; Baseline.ps1 maakt hem, of kopieer de map van de machine met de baseline" }

Write-Host ""
if ($script:Mis -eq 0) { Write-Host "Alles wat het oordeel nodig heeft staat er. Draai de toets vanuit de werkkopie met: pwsh $PSScriptRoot\Toets.ps1" -ForegroundColor Green; exit 0 }
else { Write-Host "$($script:Mis) punt(en) ontbreken; zie de rode regels." -ForegroundColor Red; exit 1 }
