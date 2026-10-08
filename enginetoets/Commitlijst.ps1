# Commitlijst.ps1: de lijst van commits sinds de baseline, gedeeld door Kies.ps1 (console) en Enginetoets.ps1 (venster).
# Dot-sourcen: . (Join-Path $PSScriptRoot 'Commitlijst.ps1')

function Get-Branchnaam([string]$Repo) {
    $naam = (& git -C $Repo rev-parse --abbrev-ref HEAD 2>$null | Select-Object -First 1)
    if (-not $naam -or $naam.Trim() -eq 'HEAD') { return (Split-Path $Repo -Leaf) }
    return $naam.Trim()
}

function Get-Baselinetag([string]$Repo, [string]$Baseline = '') {
    if ($Baseline) { return $Baseline }
    return (& git -C $Repo tag --list 'baseline/*' --sort=-creatordate 2>$null | Select-Object -First 1)
}

function Get-Commitlijst {
    <#
      De commits van de branch zelf (first-parent) sinds de baseline, nieuwste bovenaan, met de baseline als laatste rij.
      Per rij: nr, commit, datum, onderwerp, commits (hoeveel een rij binnenbrengt), raakt (leeg tot Add-Indeling), getoetst
      (nummer en oordeel uit het toetslog van de branch).
    #>
    param([string]$Repo, [string]$BaseSha, [string]$BaseTag, [int]$Aantal = 40, [string]$Toetsmap = 'C:\LocalData\RSopen_toets')
    $project = Get-Branchnaam $Repo
    $getoetst = @{}
    $logCsv = Join-Path (Join-Path $Toetsmap $project) 'toetslog.csv'
    if (Test-Path $logCsv) {
        foreach ($r in Import-Csv $logCsv -Delimiter ';') {
            if ($r.naar) { $getoetst[$r.naar] = "$($r.nr): " + (($r.oordeel -split ':')[0]) }
        }
    }
    $regels = @(& git -C $Repo log --first-parent --format=%h%x09%cs%x09%s -n $Aantal "$BaseSha..HEAD" 2>$null | Where-Object { $_ })
    $regels += (& git -C $Repo log -1 --format=%h%x09%cs%x09%s $BaseSha | Select-Object -First 1)
    $rijen = @()
    for ($i = 0; $i -lt $regels.Count; $i++) {
        $d = $regels[$i] -split "`t", 3
        $sha = $d[0]
        $isBaseline = ($i -eq $regels.Count - 1)
        $ouder = if (-not $isBaseline) { (& git -C $Repo rev-parse --short=8 "$sha^" | Select-Object -First 1).Trim() } else { '' }
        $erin = if ($ouder) { [int](& git -C $Repo rev-list --count --no-merges "$ouder..$sha" | Select-Object -First 1) } else { 0 }
        $rijen += [pscustomobject]@{
            nr        = if ($isBaseline) { '' } else { "$($i + 1)" }
            commit    = $sha
            datum     = $d[1]
            onderwerp = $d[2]
            commits   = if ($isBaseline) { 'baseline' } else { "$erin" }
            raakt     = ''
            getoetst  = if ($getoetst[$sha]) { $getoetst[$sha] } elseif ($isBaseline) { $BaseTag } else { '' }
            ouder     = $ouder
        }
    }
    return $rijen
}

$script:KorteLabels = @{ 'raakt de rekenwijze' = 'rekenwijze'; 'verandert instellingen' = 'instellingen'; 'verandert de invoerkant' = 'invoer';
    'verdeelt het schrijfwerk anders over de rekenstappen' = 'orkestratie'; 'indicatoren en export' = 'indicatoren';
    'alleen indicatoren en export' = 'alleen indicatoren'; 'toelichting' = 'toelichting'; 'alleen toelichting' = 'alleen toelichting';
    'buiten de configuratie' = 'buiten cfg'; 'alleen buiten de configuratie' = 'alleen buiten cfg' }

function Get-Indeling {
    # Wat elke commit raakt, uit VergelijkCommits.py voor de hele reeks in een keer: sha -> labels.
    param([string]$Repo, [string]$Script, [string]$BaseSha)
    $labels = @{}
    $uit = & python (Join-Path $Script 'VergelijkCommits.py') $BaseSha HEAD --repo $Repo --labels 2>$null
    foreach ($l in $uit) {
        $d = $l -split "`t"
        if ($d.Count -ge 4) { $labels[$d[0]] = $d[3] }
    }
    return $labels
}

function Add-Indeling {
    # Vult de kolom raakt: een gewone commit zijn eigen labels, een merge de samenvatting van wat hij binnenbrengt.
    param($Rijen, [string]$Repo, $Labels)
    foreach ($rij in $Rijen) {
        if (-not $rij.ouder) { continue }
        $shas = @(& git -C $Repo log --no-merges --format=%h "$($rij.ouder)..$($rij.commit)" | Where-Object { $_ })
        $verz = [System.Collections.Generic.List[string]]::new()
        foreach ($s in $shas) {
            if (-not $Labels[$s]) { continue }
            foreach ($t in ($Labels[$s] -split ', ')) {
                $k = if ($script:KorteLabels[$t]) { $script:KorteLabels[$t] } else { $t }
                if ($shas.Count -gt 1) { $k = $k -replace '^alleen ', '' }
                if (-not $verz.Contains($k)) { $verz.Add($k) }
            }
        }
        $rij.raakt = $verz -join ', '
    }
}
