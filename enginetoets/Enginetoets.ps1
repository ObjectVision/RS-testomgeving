<#
================================================================================================
 Enginetoets.ps1: het venster van de enginetoets (model-RSopen#16)
================================================================================================

 WAT DIT SCRIPT DOET
   Dubbelklik Enginetoets.cmd en dit venster opent, zonder terminal. Het toont de commits van de branch
   sinds de baseline (datum, onderwerp, wat de commit raakt, al getoetst). Je kiest een rij (die commit
   wordt getoetst tegen de baseline) of twee rijen (van en naar), zegt in een zin wat er in de commits
   zit en klikt op Start. De toets zelf (Toets.ps1) draait in een eigen venster dat zijn voortgang
   toont; dit venster mag dan dicht. Als de toets klaar is opent het rapport vanzelf.

 WERKKOPIE
   Het venster zoekt werkkopieen van het model in de map boven RS-testomgeving (elke map met
   cfg\main.dms) en onthoudt de laatst gekozen in %LOCALAPPDATA%\RS-testomgeving\enginetoets.json.

 PARAMETERS
   -Repo       De werkkopie om mee te beginnen; anders de onthouden, anders de eerste gevonden.
   -Aantal     Hoeveel commits terug, standaard 60; de baseline staat er altijd onderaan bij.
   -Toetsmap, -Werkmap   Als bij Toets.ps1.
   -Opdracht   Intern: zo start het venster de toets (een json met de keuze; Toets.ps1 draait met een
               transcript naast het toetslog).
   -Proef      Voor een test: laad de lijst, bewaar een schermafdruk (png) en sluit het venster.
================================================================================================
#>
[CmdletBinding()]
param(
    [string] $Repo     = '',
    [int]    $Aantal   = 60,
    [string] $Toetsmap = 'C:\LocalData\RSopen_toets',
    [string] $Werkmap  = 'C:\ProjDir\RSopen_toets',
    [string] $Opdracht = '',
    [string] $Proef    = ''
)

$ErrorActionPreference = 'Stop'
$Script = $PSScriptRoot

# ---------------------------------------------------------------- de toets zelf, in een eigen venster
if ($Opdracht) {
    $o = Get-Content $Opdracht -Raw -Encoding UTF8 | ConvertFrom-Json
    try { $Host.UI.RawUI.WindowTitle = "Enginetoets $($o.project): $($o.commit)" } catch { }
    Start-Transcript -Path $o.transcript | Out-Null
    $code = 0
    try {
        $arg = @{ Repo = $o.repo; Commit = $o.commit; Toetsmap = $o.toetsmap; Werkmap = $o.werkmap; Toon = $true }
        if ($o.van)          { $arg.Van = $o.van }
        if ($o.samenvatting) { $arg.Samenvatting = $o.samenvatting }
        if ($o.opnieuw)      { $arg.Opnieuw = $true }
        & (Join-Path $Script 'Toets.ps1') @arg
    } catch {
        $code = 1
        Write-Host ''
        Write-Host "MISLUKT: $_" -ForegroundColor Red
        Write-Host "Het hele verslag staat in $($o.transcript)"
    } finally {
        Stop-Transcript | Out-Null
    }
    if ($code -and -not [Console]::IsInputRedirected) {
        Write-Host 'Druk op een toets om dit venster te sluiten'
        [void][Console]::ReadKey($true)
    }
    exit $code
}

# ---------------------------------------------------------------- het venster
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try { [System.Windows.Forms.Application]::SetHighDpiMode([System.Windows.Forms.HighDpiMode]::SystemAware) | Out-Null } catch { }
[System.Windows.Forms.Application]::EnableVisualStyles()
. (Join-Path $Script 'Commitlijst.ps1')

$S = @{ repo = ''; rijen = $null; project = ''; tag = ''; baseSha = ''; ldDir = ''
        laden = $false; sync = $null; ps = $null; rs = $null; handle = $null; rijenGetoond = $false
        proces = $null; transcript = '' }
$instellingenPad = Join-Path $env:LOCALAPPDATA 'RS-testomgeving\enginetoets.json'

function Get-Instellingen {
    if (Test-Path $instellingenPad) { try { return (Get-Content $instellingenPad -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { } }
    return $null
}
function Save-Instellingen([string]$Werkkopie) {
    New-Item -ItemType Directory -Path (Split-Path $instellingenPad -Parent) -Force | Out-Null
    @{ werkkopie = $Werkkopie } | ConvertTo-Json | Set-Content $instellingenPad -Encoding UTF8
}
function Get-Werkkopieen {
    # Elke map met cfg\main.dms naast de map van RS-testomgeving (C:\ProjDir\_Tools\RS-testomgeving geeft C:\ProjDir).
    $boven = Split-Path (Split-Path (Split-Path $Script -Parent) -Parent) -Parent
    $lijst = [System.Collections.Generic.List[string]]::new()
    foreach ($m in (@($boven, 'C:\ProjDir') | Select-Object -Unique)) {
        if (-not $m -or -not (Test-Path $m)) { continue }
        foreach ($d in (Get-ChildItem $m -Directory -ErrorAction SilentlyContinue)) {
            if ((Test-Path (Join-Path $d.FullName 'cfg\main.dms')) -and -not $lijst.Contains($d.FullName)) { $lijst.Add($d.FullName) }
        }
    }
    return $lijst
}
function Get-LocalDataDir {
    foreach ($sleutel in @("HKCU:\Software\ObjectVision\$env:COMPUTERNAME\GeoDMS", 'HKCU:\Software\ObjectVision\OVSRV08\GeoDMS')) {
        $d = (Get-ItemProperty $sleutel -ErrorAction SilentlyContinue).LocalDataDir
        if ($d) { return $d }
    }
    return 'C:\LocalData'
}
function Test-Toetsrun([string]$Sha) {
    # Staat er een toetsrun van deze commit, zoals Toets.ps1 hem voor -Van zoekt?
    if (-not $Sha -or -not $S.project) { return $false }
    $k = @(Get-ChildItem $S.ldDir -Directory -Filter "$($S.project)_$Sha*" -ErrorAction SilentlyContinue | Where-Object { Test-Path (Join-Path $_.FullName 'Allocatie') })
    return ($k.Count -gt 0)
}
function Get-Testprofieltekst([string]$Project) {
    $pad = Join-Path $Script "profielen\$Project.csv"
    if (-not (Test-Path $pad)) { return "Geen testprofiel profielen\$Project.csv; maak dat eerst naast Toets.ps1." }
    $w = @{}
    foreach ($r in (Import-Csv $pad -Delimiter ';')) { $w[$r.pad] = $r.waarde }
    $delen = @()
    if ($w['ModelParameters/StudyArea']) { $delen += ($w['ModelParameters/StudyArea'] -replace "'", '') }
    $j1 = "$($w['ModelParameters/Model_FirstZichtjaar'])" -replace '\[.*', ''
    $j2 = "$($w['ModelParameters/Model_FinalYear'])" -replace '\[.*', ''
    if ($j1 -and $j2 -and $j1 -ne $j2) { $delen += "zichtjaren $j1 tot $j2" } elseif ($j1) { $delen += "zichtjaar $j1" }
    if ($w['run:Varianten']) { $delen += ('varianten ' + (($w['run:Varianten'] -split ',') -join ' en ')) }
    return "Testprofiel $Project.csv: " + ($delen -join ', ') + '.'
}
function P([int]$l, [int]$t, [int]$r, [int]$b) { return (New-Object System.Windows.Forms.Padding($l, $t, $r, $b)) }

# ---- opbouw
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Enginetoets'
$form.StartPosition = 'CenterScreen'
$form.Size = New-Object System.Drawing.Size(1200, 780)
$form.MinimumSize = New-Object System.Drawing.Size(900, 560)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9.75)

$lay = New-Object System.Windows.Forms.TableLayoutPanel
$lay.Dock = 'Fill'; $lay.ColumnCount = 1; $lay.RowCount = 7
$lay.Padding = P 12 10 12 8
[void]$lay.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
foreach ($soort in @('auto', 'auto', 'rest', 'auto', 'auto', 'auto', 'auto')) {
    if ($soort -eq 'rest') { [void]$lay.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, 100))) }
    else                   { [void]$lay.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize))) }
}
$form.Controls.Add($lay)

# rij 0: de werkkopie
$kop = New-Object System.Windows.Forms.FlowLayoutPanel
$kop.AutoSize = $true; $kop.Dock = 'Fill'; $kop.WrapContents = $false; $kop.Margin = P 0 0 0 2
$lblWerk = New-Object System.Windows.Forms.Label
$lblWerk.Text = 'Werkkopie van het model'; $lblWerk.AutoSize = $true; $lblWerk.Margin = P 0 8 8 0
$cmbWerk = New-Object System.Windows.Forms.ComboBox
$cmbWerk.Width = 520; $cmbWerk.DropDownStyle = 'DropDown'; $cmbWerk.Margin = P 0 4 8 0
$btnBlader = New-Object System.Windows.Forms.Button
$btnBlader.Text = 'Bladeren...'; $btnBlader.AutoSize = $true; $btnBlader.Margin = P 0 2 4 0
$btnVervers = New-Object System.Windows.Forms.Button
$btnVervers.Text = 'Lijst verversen'; $btnVervers.AutoSize = $true; $btnVervers.Margin = P 0 2 4 0
$btnUitleg = New-Object System.Windows.Forms.Button
$btnUitleg.Text = 'Uitleg'; $btnUitleg.AutoSize = $true; $btnUitleg.Margin = P 0 2 0 0
$kop.Controls.AddRange(@($lblWerk, $cmbWerk, $btnBlader, $btnVervers, $btnUitleg))
$lay.Controls.Add($kop, 0, 0)

# rij 1: de branch, de baseline en het testprofiel
$lblBranch = New-Object System.Windows.Forms.Label
$lblBranch.AutoSize = $true; $lblBranch.Dock = 'Fill'; $lblBranch.Margin = P 0 0 0 6
$lblBranch.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 80)
$lay.Controls.Add($lblBranch, 0, 1)

# rij 2: de lijst
$grid = New-Object System.Windows.Forms.DataGridView
$grid.Dock = 'Fill'; $grid.ReadOnly = $true; $grid.AllowUserToAddRows = $false; $grid.AllowUserToDeleteRows = $false
$grid.AllowUserToResizeRows = $false; $grid.RowHeadersVisible = $false; $grid.SelectionMode = 'FullRowSelect'
$grid.MultiSelect = $true; $grid.AutoGenerateColumns = $false; $grid.AllowUserToOrderColumns = $false
$grid.BackgroundColor = [System.Drawing.SystemColors]::Window; $grid.BorderStyle = 'FixedSingle'
$grid.ColumnHeadersHeightSizeMode = 'AutoSize'; $grid.ShowCellToolTips = $true; $grid.Margin = P 0 0 0 6
$grid.DefaultCellStyle.SelectionBackColor = [System.Drawing.Color]::FromArgb(204, 228, 247)
$grid.DefaultCellStyle.SelectionForeColor = [System.Drawing.Color]::Black
$grid.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9.75, [System.Drawing.FontStyle]::Bold)
function Add-Kolom([string]$Naam, [string]$Kop, [int]$Breedte, [switch]$Rechts, [switch]$Vul) {
    $c = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
    $c.Name = $Naam; $c.HeaderText = $Kop; $c.Width = $Breedte; $c.ReadOnly = $true; $c.SortMode = 'NotSortable'
    if ($Vul)    { $c.AutoSizeMode = 'Fill'; $c.MinimumWidth = $Breedte }
    if ($Rechts) { $c.DefaultCellStyle.Alignment = 'MiddleRight'; $c.HeaderCell.Style.Alignment = 'MiddleRight' }
    [void]$grid.Columns.Add($c)
}
Add-Kolom 'nr'        'nr'        44  -Rechts
Add-Kolom 'commit'    'commit'    88
Add-Kolom 'datum'     'datum'     96
Add-Kolom 'onderwerp' 'onderwerp' 300 -Vul
Add-Kolom 'commits'   'commits'   66  -Rechts
Add-Kolom 'raakt'     'raakt'     330
Add-Kolom 'getoetst'  'getoetst'  140
$lay.Controls.Add($grid, 0, 2)

# rij 3: wat de keuze betekent
$lblKeuze = New-Object System.Windows.Forms.Label
$lblKeuze.AutoSize = $true; $lblKeuze.Dock = 'Fill'; $lblKeuze.Margin = P 0 0 0 8
$lay.Controls.Add($lblKeuze, 0, 3)

# rij 4 en 5: de samenvatting
$lblSamen = New-Object System.Windows.Forms.Label
$lblSamen.Text = 'Wat zit er in deze commits, in een of twee zinnen (mag leeg; dan groepeert het rapport de commits op issuenummer)'
$lblSamen.AutoSize = $true; $lblSamen.Dock = 'Fill'; $lblSamen.Margin = P 0 0 0 2
$lay.Controls.Add($lblSamen, 0, 4)
$txtSamenvatting = New-Object System.Windows.Forms.TextBox
$txtSamenvatting.Multiline = $true; $txtSamenvatting.Height = 54; $txtSamenvatting.Dock = 'Fill'; $txtSamenvatting.ScrollBars = 'Vertical'
$txtSamenvatting.Margin = P 0 0 0 8
$lay.Controls.Add($txtSamenvatting, 0, 5)

# rij 6: status en knoppen
$voet = New-Object System.Windows.Forms.TableLayoutPanel
$voet.AutoSize = $true; $voet.Dock = 'Fill'; $voet.ColumnCount = 2; $voet.RowCount = 1; $voet.Margin = P 0 0 0 0
[void]$voet.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$voet.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::AutoSize)))
$lblStatus = New-Object System.Windows.Forms.Label
$lblStatus.AutoSize = $true; $lblStatus.Dock = 'Fill'; $lblStatus.Margin = P 0 8 12 0
$knoppen = New-Object System.Windows.Forms.FlowLayoutPanel
$knoppen.AutoSize = $true; $knoppen.WrapContents = $false; $knoppen.Margin = P 0 0 0 0
$btnStart = New-Object System.Windows.Forms.Button
$btnStart.Text = 'Start toets'; $btnStart.AutoSize = $true; $btnStart.Enabled = $false; $btnStart.Margin = P 0 0 6 0
$btnStart.Padding = P 8 2 8 2
$btnLog = New-Object System.Windows.Forms.Button
$btnLog.Text = 'Toetslog openen'; $btnLog.AutoSize = $true; $btnLog.Margin = P 0 0 6 0
$btnSluit = New-Object System.Windows.Forms.Button
$btnSluit.Text = 'Sluiten'; $btnSluit.AutoSize = $true; $btnSluit.Margin = P 0 0 0 0
$knoppen.Controls.AddRange(@($btnStart, $btnLog, $btnSluit))
$voet.Controls.Add($lblStatus, 0, 0)
$voet.Controls.Add($knoppen, 1, 0)
$lay.Controls.Add($voet, 0, 6)

function Set-Status([string]$Tekst, [bool]$Fout = $false) {
    $lblStatus.Text = $Tekst
    $lblStatus.ForeColor = if ($Fout) { [System.Drawing.Color]::FromArgb(170, 30, 30) } else { [System.Drawing.SystemColors]::ControlText }
}

# ---- de lijst tonen
function Set-Oordeelkleur($r) {
    $t = [string]$r.Cells['getoetst'].Value
    $kleur = $null
    if     ($t -match 'IDENTIEK')     { $kleur = [System.Drawing.Color]::FromArgb(0, 110, 60) }
    elseif ($t -match 'STAND GELIJK') { $kleur = [System.Drawing.Color]::FromArgb(40, 90, 160) }
    elseif ($t -match 'VERSCHILT')    { $kleur = [System.Drawing.Color]::FromArgb(180, 80, 0) }
    if ($kleur) { $r.Cells['getoetst'].Style.ForeColor = $kleur }
}
function Show-Rijen {
    $grid.SuspendLayout()
    $grid.Rows.Clear()
    foreach ($rij in $S.rijen) {
        $i = $grid.Rows.Add(@([string]$rij.nr, [string]$rij.commit, [string]$rij.datum, [string]$rij.onderwerp, [string]$rij.commits, [string]$rij.raakt, [string]$rij.getoetst))
        $r = $grid.Rows[$i]
        $r.Tag = $rij
        if ($rij.commits -eq 'baseline') {
            $r.DefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(236, 236, 236)
            $r.DefaultCellStyle.ForeColor = [System.Drawing.Color]::FromArgb(90, 90, 90)
        }
        Set-Oordeelkleur $r
    }
    $grid.ClearSelection()
    $grid.ResumeLayout()
}
function Show-Raakt {
    for ($i = 0; $i -lt $grid.Rows.Count; $i++) { $grid.Rows[$i].Cells['raakt'].Value = [string]$grid.Rows[$i].Tag.raakt }
}
function Receive-Rijen {
    $S.rijen = $S.sync.rijen; $S.project = $S.sync.project; $S.tag = $S.sync.tag; $S.baseSha = $S.sync.baseSha
    $lblBranch.Text = "Branch $($S.project). Baseline $($S.tag) ($($S.baseSha)). " + (Get-Testprofieltekst $S.project)
    Show-Rijen
    $S.rijenGetoond = $true
    Set-Status 'Wat elke commit raakt wordt nog bepaald, even geduld.'
}

# ---- de lijst ophalen, buiten het venster om zodat het niet bevriest
$laadBlok = {
    param($Script, $Repo, $Toetsmap, $Aantal)
    try {
        . (Join-Path $Script 'Commitlijst.ps1')
        $sync.project = Get-Branchnaam $Repo
        $sync.tag = Get-Baselinetag $Repo
        if (-not $sync.tag) { throw "Geen baseline op branch $($sync.project); maak er een met Baseline.ps1." }
        $sync.baseSha = (& git -C $Repo rev-parse --short=8 "$($sync.tag)^{commit}" | Select-Object -First 1).Trim()
        $sync.rijen = Get-Commitlijst -Repo $Repo -BaseSha $sync.baseSha -BaseTag $sync.tag -Aantal $Aantal -Toetsmap $Toetsmap
        $sync.fase = 'rijen'
        Add-Indeling -Rijen $sync.rijen -Repo $Repo -Labels (Get-Indeling -Repo $Repo -Script $Script -BaseSha $sync.baseSha)
    } catch { $sync.fout = "$_" }
    $sync.fase = 'klaar'
}
function Start-Laden {
    if ($S.laden) { Set-Status 'De vorige lijst wordt nog opgehaald; druk straks op Lijst verversen.'; return }
    $repo = $cmbWerk.Text.Trim()
    if (-not $repo -or -not (Test-Path (Join-Path $repo 'cfg\main.dms'))) { Set-Status "Geen cfg\main.dms in '$repo'; kies de werkkopie van het model." $true; return }
    Save-Instellingen $repo
    $S.repo = $repo; $S.rijen = $null; $S.rijenGetoond = $false; $S.project = ''; $S.tag = ''; $S.ldDir = Get-LocalDataDir
    $grid.Rows.Clear(); $lblBranch.Text = ''
    $S.sync = [hashtable]::Synchronized(@{ fase = ''; fout = ''; rijen = $null; project = ''; tag = ''; baseSha = '' })
    $S.rs = [runspacefactory]::CreateRunspace(); $S.rs.Open()
    $S.rs.SessionStateProxy.SetVariable('sync', $S.sync)
    $S.ps = [powershell]::Create(); $S.ps.Runspace = $S.rs
    [void]$S.ps.AddScript($laadBlok.ToString()).AddParameters(@{ Script = $Script; Repo = $repo; Toetsmap = $Toetsmap; Aantal = $Aantal })
    $S.handle = $S.ps.BeginInvoke()
    $S.laden = $true
    Set-Status "Commits ophalen uit $repo, even geduld."
    Update-Keuze
}
function Stop-Laden {
    $S.laden = $false
    try { if ($S.ps) { $S.ps.Dispose() }; if ($S.rs) { $S.rs.Dispose() } } catch { }
    $S.ps = $null; $S.rs = $null
}

# ---- de keuze
function Get-Keuze {
    $k = @{ naar = $null; van = $null; tekst = ''; ok = $false }
    if (-not $S.rijen) { return $k }
    $sel = @($grid.SelectedRows | Sort-Object Index)
    if ($sel.Count -eq 0) { $k.tekst = 'Kies een rij om die commit tegen de baseline te toetsen, of twee rijen (met Ctrl) voor van en naar.'; return $k }
    if ($sel.Count -gt 2) { $k.tekst = "Kies een of twee rijen, niet $($sel.Count)."; return $k }
    $naar = $sel[0].Tag
    if ($naar.commits -eq 'baseline') { $k.tekst = 'De baseline zelf wordt niet getoetst; kies een commit erboven.'; return $k }
    $k.naar = $naar
    $van = if ($sel.Count -eq 2 -and $sel[1].Tag.commits -ne 'baseline') { $sel[1].Tag } else { $null }
    if ($van) {
        if (-not (Test-Toetsrun $van.commit)) {
            $k.tekst = "$($van.commit) is nog niet getoetst, dus er is geen run om tegen te vergelijken. Toets $($van.commit) eerst (als enige rij), of kies een getoetste commit als van."
            return $k
        }
        $n = (& git -C $S.repo rev-list --count --no-merges "$($van.commit)..$($naar.commit)" 2>$null | Select-Object -First 1)
        $k.van = $van
        $k.tekst = "Toets $($naar.commit) ($($naar.datum)) tegen de toetsrun van $($van.commit) ($($van.datum)); daar zitten $n commits tussen."
    } else {
        $k.tekst = "Toets $($naar.commit) ($($naar.datum)) tegen de baseline $($S.tag)."
    }
    if ($naar.getoetst) { $k.tekst += " Deze commit is al getoetst als nr $($naar.getoetst -replace ':.*', ''); starten rekent hem opnieuw." }
    elseif (Test-Toetsrun $naar.commit) { $k.tekst += " Van deze commit staat al een run; starten rekent hem opnieuw." }
    $k.ok = $true
    return $k
}
function Update-Keuze {
    $k = Get-Keuze
    $lblKeuze.Text = $k.tekst
    $btnStart.Enabled = ($k.ok -and -not $S.proces)
}

# ---- de toets starten
function Start-Toets {
    $k = Get-Keuze
    if (-not $k.ok) { return }
    $opnieuw = (Test-Toetsrun $k.naar.commit) -or (Test-Path (Join-Path $Werkmap "$($S.project)_$($k.naar.commit)"))
    if ($opnieuw) {
        $a = [System.Windows.Forms.MessageBox]::Show($form, "Van $($k.naar.commit) staat al een toetsrun. Opnieuw rekenen en die run vervangen?", 'Enginetoets', 'YesNo', 'Question')
        if ($a -ne 'Yes') { return }
    }
    $samenvatting = ($txtSamenvatting.Text.Trim() -replace '\s+', ' ')
    if (-not $samenvatting) {
        $a = [System.Windows.Forms.MessageBox]::Show($form, 'Zonder samenvatting groepeert het rapport de commits op issuenummer. Toch starten?', 'Enginetoets', 'YesNo', 'Question')
        if ($a -ne 'Yes') { return }
    }
    $map = Join-Path $Toetsmap $S.project
    New-Item -ItemType Directory -Path $map -Force | Out-Null
    $stempel = Get-Date -Format 'yyyyMMdd_HHmm'
    $opdrachtPad = Join-Path $map "opdracht_$($k.naar.commit)_$stempel.json"
    $transcript  = Join-Path $map "toets_$($k.naar.commit)_$stempel.log"
    $o = [ordered]@{
        project = $S.project; repo = $S.repo; commit = $k.naar.commit
        van = $(if ($k.van) { $k.van.commit } else { '' }); samenvatting = $samenvatting
        toetsmap = $Toetsmap; werkmap = $Werkmap; opnieuw = $opnieuw; transcript = $transcript
    }
    $o | ConvertTo-Json | Set-Content $opdrachtPad -Encoding UTF8
    $argumenten = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"{0}"' -f (Join-Path $Script 'Enginetoets.ps1')), '-Opdracht', ('"{0}"' -f $opdrachtPad))
    $S.proces = Start-Process pwsh -ArgumentList $argumenten -WindowStyle Normal -PassThru
    $S.transcript = $transcript
    Set-Status ("Toets van {0} gestart om {1} in een eigen venster. Dit venster mag dicht; het rapport opent vanzelf als de toets klaar is (reken op een half uur tot een uur)." -f $k.naar.commit, (Get-Date -Format 'HH:mm'))
    Update-Keuze
}
function Receive-Toets {
    $code = $S.proces.ExitCode
    $commit = ''
    if ($S.transcript -match 'toets_([0-9a-f]+)_') { $commit = $Matches[1] }
    $S.proces = $null
    if ($code -eq 0) {
        $oordeel = ''
        $logCsv = Join-Path (Join-Path $Toetsmap $S.project) 'toetslog.csv'
        if (Test-Path $logCsv) { $laatste = @(Import-Csv $logCsv -Delimiter ';')[-1]; if ($laatste) { $oordeel = " Oordeel: $($laatste.oordeel)." } }
        Start-Laden
        [System.Windows.Forms.MessageBox]::Show($form, "De toets van $commit is klaar.$oordeel Het rapport staat in de browser en in het toetslog.", 'Enginetoets', 'OK', 'Information') | Out-Null
    } else {
        $staart = ''
        if (Test-Path $S.transcript) { $staart = ((Get-Content $S.transcript -Tail 12) -join "`n") }
        Start-Laden
        Set-Status "De toets van $commit is mislukt; het verslag staat in $($S.transcript)" $true
        [System.Windows.Forms.MessageBox]::Show($form, "De toets van $commit is mislukt.`n`n$staart`n`nHet hele verslag staat in $($S.transcript)", 'Enginetoets', 'OK', 'Warning') | Out-Null
    }
}

# ---- de klok: kijkt of de lijst er is en of de toets klaar is
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 400
$timer.add_Tick({
    if ($S.laden) {
        $f = $S.sync.fase
        if ($f -eq 'rijen' -and -not $S.rijenGetoond) { Receive-Rijen }
        if ($f -eq 'klaar') {
            if (-not $S.rijenGetoond -and $S.sync.rijen) { Receive-Rijen }
            if ($S.rijenGetoond) { Show-Raakt }
            Stop-Laden
            if ($S.sync.fout) { Set-Status $S.sync.fout $true }
            else {
                $n = @($S.rijen | Where-Object { $_.commits -ne 'baseline' }).Count
                $m = @($S.rijen | Where-Object { $_.commits -ne 'baseline' -and $_.getoetst }).Count
                Set-Status "$n commits sinds de baseline, $m ervan getoetst."
            }
            Update-Keuze
        }
    }
    if ($S.proces -and $S.proces.HasExited) { Receive-Toets }
})

# ---- de knoppen
$grid.add_SelectionChanged({ Update-Keuze })
$btnStart.add_Click({ Start-Toets })
$btnVervers.add_Click({ Start-Laden })
$btnSluit.add_Click({ $form.Close() })
$btnUitleg.add_Click({ Start-Process 'https://github.com/ObjectVision/RSopen/wiki/Enginetoets' })
$btnLog.add_Click({
    $pad = Join-Path (Join-Path $Toetsmap $S.project) 'toetslog.html'
    if ($S.project -and (Test-Path $pad)) { Start-Process $pad }
    else { [System.Windows.Forms.MessageBox]::Show($form, 'Er is nog geen toetslog voor deze branch.', 'Enginetoets', 'OK', 'Information') | Out-Null }
})
$btnBlader.add_Click({
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    $d.Description = 'Kies de werkkopie van het model (de map met cfg\main.dms)'
    $d.UseDescriptionForTitle = $true
    if ($cmbWerk.Text -and (Test-Path $cmbWerk.Text)) { $d.SelectedPath = $cmbWerk.Text }
    if ($d.ShowDialog($form) -eq 'OK') {
        if (-not $cmbWerk.Items.Contains($d.SelectedPath)) { [void]$cmbWerk.Items.Add($d.SelectedPath) }
        $cmbWerk.Text = $d.SelectedPath
        Start-Laden
    }
})
$form.add_FormClosing({ $timer.Stop(); Stop-Laden })

# ---- de werkkopie: -Repo, anders de onthouden, anders de eerste gevonden
foreach ($w in (Get-Werkkopieen)) { [void]$cmbWerk.Items.Add($w) }
$keuze = $Repo
if (-not $keuze) { $i = Get-Instellingen; if ($i -and $i.werkkopie -and (Test-Path (Join-Path $i.werkkopie 'cfg\main.dms'))) { $keuze = $i.werkkopie } }
if (-not $keuze -and $cmbWerk.Items.Count) { $keuze = $cmbWerk.Items[0] }
if ($keuze -and -not $cmbWerk.Items.Contains($keuze)) { [void]$cmbWerk.Items.Add($keuze) }
$cmbWerk.Text = $keuze
$cmbWerk.add_SelectedIndexChanged({ Start-Laden })
Start-Laden
$timer.Start()

if ($Proef) {
    $form.Show()
    $t0 = Get-Date
    while ($S.laden -and ((Get-Date) - $t0).TotalSeconds -lt 300) { [System.Windows.Forms.Application]::DoEvents(); Start-Sleep -Milliseconds 100 }
    if ($grid.Rows.Count -gt 3) { $grid.ClearSelection(); $grid.Rows[1].Selected = $true; $grid.Rows[3].Selected = $true }
    $txtSamenvatting.Text = 'Een proefzin voor de schermafdruk.'
    [System.Windows.Forms.Application]::DoEvents()
    $bmp = New-Object System.Drawing.Bitmap($form.Width, $form.Height)
    $form.DrawToBitmap($bmp, (New-Object System.Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
    $bmp.Save($Proef, [System.Drawing.Imaging.ImageFormat]::Png)
    "branch : $($lblBranch.Text)"
    "status : $($lblStatus.Text)"
    "keuze  : $($lblKeuze.Text)"
    "rijen  : $($grid.Rows.Count), start $($btnStart.Enabled)"
    $form.Close()
    return
}
[void]$form.ShowDialog()
