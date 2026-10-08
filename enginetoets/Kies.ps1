<#
================================================================================================
 Kies.ps1: de commitkiezer van de enginetoets (model-RSopen#16, fase 4)
================================================================================================

 WAT DIT SCRIPT DOET
   Toont de commits van de branch sinds de baseline als lijst, nieuwste bovenaan, met per commit de
   datum, het onderwerp, wat hij raakt (rekenwijze, instellingen, invoer, indicatoren, toelichting) en of
   hij al getoetst is (het nummer en het oordeel uit het toetslog). Je kiest een rij, of twee: een rij is
   de commit om te toetsen tegen de baseline, twee rijen zijn van en naar (een groep commits). Daarna
   vraagt het script een samenvatting van wat er in de commits zit en start het Toets.ps1.

 HOE START JE HET (vanuit de werkkopie van het model, of met -Repo)
       pwsh C:\ProjDir\_Tools\RS-testomgeving\enginetoets\Kies.ps1
   Zonder terminal: dubbelklik Enginetoets.cmd in dezelfde map; dat is dezelfde lijst in een venster.
   Alleen de lijst, zonder te kiezen (ook zonder venster te gebruiken):
       pwsh ...\enginetoets\Kies.ps1 -Lijst

 PARAMETERS
   -Aantal        Hoeveel commits terug, standaard 40; de baseline staat er altijd onderaan bij.
   -Lijst         Druk de lijst af en stop.
   -Samenvatting  Als je hem al weet; anders vraagt het script erom.
   -Patch         Gaat door naar Toets.ps1.
   -Ja            Geen bevestiging vragen.
   -Repo, -Baseline, -Toetsmap, -Werkmap   Als bij Toets.ps1.

 De lijst komt in een venster (Out-GridView) waarin je met Ctrl ook een tweede rij kiest; zonder venster
 (geen bureaublad) valt het script terug op een nummer in de console.
================================================================================================
#>
[CmdletBinding()]
param(
    [int]    $Aantal       = 40,
    [switch] $Lijst,
    [string] $Samenvatting = '',
    [string] $Patch        = '',
    [string] $Baseline     = '',
    [string] $Toetsmap     = 'C:\LocalData\RSopen_toets',
    [string] $Werkmap      = 'C:\ProjDir\RSopen_toets',
    [string] $Repo         = '',
    [switch] $Ja
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

. (Join-Path $PSScriptRoot 'Commitlijst.ps1')
$Project = Get-Branchnaam $Repo
$baseTag = Get-Baselinetag $Repo $Baseline
if (-not $baseTag) { throw "geen baseline op $Project; maak er een met Baseline.ps1" }
$baseSha = (Invoke-Git rev-parse --short=8 "$baseTag^{commit}" | Select-Object -First 1).Trim()
$rijen = Get-Commitlijst -Repo $Repo -BaseSha $baseSha -BaseTag $baseTag -Aantal $Aantal -Toetsmap $Toetsmap
Write-Regel "indelen   : $($rijen.Count - 1) commits sinds $baseTag ($baseSha), even geduld"
Add-Indeling -Rijen $rijen -Repo $Repo -Labels (Get-Indeling -Repo $Repo -Script $PSScriptRoot -BaseSha $baseSha)
$getoetst = @{}
foreach ($rij in $rijen) { if ($rij.getoetst -and $rij.commits -ne 'baseline') { $getoetst[$rij.commit] = $rij.getoetst } }
$rijen = @($rijen | Select-Object nr, commit, datum, @{ n = 'onderwerp'; e = { if ($_.onderwerp.Length -gt 72) { $_.onderwerp.Substring(0, 69) + '...' } else { $_.onderwerp } } }, commits, raakt, getoetst)

if ($Lijst) {
    $rijen | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
    return
}

# ---------------------------------------------------------------- kiezen
$keuze = @()
$venster = Get-Command Out-GridView -ErrorAction SilentlyContinue
if ($venster -and -not [Environment]::UserInteractive) { $venster = $null }
if ($venster) {
    $keuze = @($rijen | Where-Object { $_.commits -ne 'baseline' } |
        Out-GridView -Title "Enginetoets $Project : kies de commit om te toetsen (een rij), of van en naar (twee rijen, Ctrl)" -OutputMode Multiple)
} else {
    $rijen | Format-Table -AutoSize -Wrap | Out-String -Width 220 | Write-Host
    $antwoord = Read-Host "Nummer van de commit om te toetsen, of twee nummers (van naar) gescheiden door een spatie; leeg is stoppen"
    foreach ($n in ($antwoord -split '\s+' | Where-Object { $_ })) { $keuze += @($rijen | Where-Object { "$($_.nr)" -eq $n }) }
}
if (-not $keuze.Count) { Write-Regel "gestopt   : niets gekozen"; return }
if ($keuze.Count -gt 2) { throw "kies een of twee rijen, niet $($keuze.Count)" }
$gesorteerd = @($keuze | Sort-Object { [int]$_.nr } -Descending)   # hoogste nummer is de oudste
$naar = $gesorteerd[-1]
$van  = if ($gesorteerd.Count -eq 2) { $gesorteerd[0].commit } else { '' }

Write-Host ""
Write-Regel ("toets     : {0} ({1}) {2}" -f $naar.commit, $naar.datum, $naar.onderwerp)
Write-Regel ("tegen     : {0}" -f $(if ($van) { "de toetsrun van $van" } else { "de baseline $baseTag ($baseSha)" }))
if ($van -and -not $getoetst[$van]) { Write-Regel "let op    : $van is nog niet getoetst; Toets.ps1 heeft zijn run nodig. Draai hem eerst, of kies een getoetste commit als van." }
if (-not $Samenvatting) { $Samenvatting = Read-Host "Wat zit er in deze commits, in een of twee zinnen (leeg mag)" }
if (-not $Ja) {
    $antwoord = Read-Host "Starten (ja/nee)"
    if ($antwoord -ne 'ja') { Write-Regel "gestopt   : niets gedaan"; return }
}
$argumenten = @{ Repo = $Repo; Commit = $naar.commit; Toetsmap = $Toetsmap; Werkmap = $Werkmap }
if ($van)          { $argumenten.Van = $van }
if ($Samenvatting) { $argumenten.Samenvatting = $Samenvatting }
if ($Patch)        { $argumenten.Patch = $Patch }
if ($Baseline)     { $argumenten.Baseline = $Baseline }
& (Join-Path $PSScriptRoot 'Toets.ps1') @argumenten
