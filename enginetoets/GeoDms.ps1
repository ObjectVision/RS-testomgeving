# GeoDms.ps1: welke GeoDmsRun.exe een script gebruikt. Dot-sourcen: . (Join-Path $PSScriptRoot 'GeoDms.ps1')

function Get-GeoDmsInstallaties {
    # Alle GeoDMS-installaties onder Program Files, nieuwste versie eerst (GeoDms20.23.0.m telt als 20.23.0).
    $map = Join-Path $env:ProgramFiles 'ObjectVision'
    @(Get-ChildItem $map -Directory -Filter 'GeoDms*' -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'GeoDmsRun.exe') } |
        ForEach-Object {
            $nr = (($_.Name -replace '^GeoDms', '') -replace '[^0-9.]', '').Trim('.')
            $versie = $null
            if (-not [version]::TryParse($nr, [ref]$versie)) { $versie = [version]'0.0' }
            [pscustomobject]@{ Naam = $_.Name; Versie = $versie; Exe = (Join-Path $_.FullName 'GeoDmsRun.exe') }
        } | Sort-Object Versie -Descending)
}

function Find-GeoDmsRun {
    <#
      De GeoDmsRun.exe voor een run: wat -Exe zegt; anders de versie die batch\Run2120.ps1 van de commit noemt,
      als die op deze machine staat; anders de nieuwste GeoDMS die er staat. De versie hoort niet uit te maken
      voor de toets, zolang beide kanten van een vergelijking met dezelfde versie zijn gerekend; het rapport
      noemt de versie van beide kanten.
    #>
    param([string]$Gevraagd = '', [string]$Runner = '')
    if ($Gevraagd) {
        if (Test-Path $Gevraagd) { return $Gevraagd }
        throw "GeoDmsRun niet gevonden: $Gevraagd"
    }
    if ($Runner -and (Test-Path $Runner)) {
        $m = [regex]::Match((Get-Content $Runner -Raw), '\$Exe\s*=\s*''([^'']+GeoDmsRun\.exe)''')
        if ($m.Success -and (Test-Path $m.Groups[1].Value)) { return $m.Groups[1].Value }
    }
    $nieuwste = @(Get-GeoDmsInstallaties) | Select-Object -First 1
    if ($nieuwste) { return $nieuwste.Exe }
    throw "geen GeoDMS gevonden onder $env:ProgramFiles\ObjectVision; installeer de nieuwste van https://github.com/ObjectVision/GeoDMS/releases"
}
