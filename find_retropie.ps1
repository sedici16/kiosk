<#
.SYNOPSIS
    Trova l'IP del Raspberry Pi (RetroPie) sulla rete locale e, se richiesto,
    aggiorna retropie.json con l'IP trovato.

.EXAMPLE
    .\find_retropie.ps1
    Cerca il Pi per nome (kiosk-pi.local di default) via mDNS, poi con la
    scansione della subnet se serve, e stampa i candidati trovati.

.EXAMPLE
    .\find_retropie.ps1 -Name il-mio-rasp
    Usa un nome mDNS diverso da quello impostato sul Pi.

.EXAMPLE
    .\find_retropie.ps1 -UpdateConfig
    Cerca il Pi e, se trova UN SOLO candidato, aggiorna retropie.json automaticamente.

.EXAMPLE
    .\find_retropie.ps1 -Ip 192.168.1.42
    Salta la scansione e scrive direttamente questo IP in retropie.json.
#>

param(
    [switch]$UpdateConfig,
    [string]$Ip,
    [string]$Name = "kiosk-pi",
    [int]$TimeoutMs = 300
)

$ErrorActionPreference = "Stop"
$ConfigPath = Join-Path $PSScriptRoot "retropie.json"

function Update-RetropieConfig([string]$NewIp) {
    if (Test-Path $ConfigPath) {
        $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    } else {
        $cfg = [pscustomobject]@{ host = ""; user = "pi"; password = "raspberry"; ports_dir = "/home/pi/RetroPie/roms/ports" }
    }
    $cfg.host = $NewIp
    ($cfg | ConvertTo-Json) | Set-Content -Encoding utf8 $ConfigPath
    Write-Host "retropie.json aggiornato: host = $NewIp" -ForegroundColor Green
}

# --- caso diretto: IP passato a mano -----------------------------------
if ($Ip) {
    Write-Host "Verifico $Ip sulla porta 22..."
    $ok = Test-NetConnection -ComputerName $Ip -Port 22 -WarningAction SilentlyContinue
    if (-not $ok.TcpTestSucceeded) {
        Write-Warning "$Ip non risponde sulla porta 22 (SSH). Aggiorno comunque il config? Premi Ctrl+C per annullare."
    }
    Update-RetropieConfig -NewIp $Ip
    return
}

# --- passo 1: prova mDNS (<Name>.local, poi i nomi di default) -----------
$namesToTry = @("$Name.local", "retropie.local", "raspberrypi.local") | Select-Object -Unique
Write-Host "Provo a risolvere: $($namesToTry -join ', ') (mDNS)..."
$mdnsCandidates = @()
foreach ($name in $namesToTry) {
    try {
        $addrs = [System.Net.Dns]::GetHostAddresses($name) |
            Where-Object { $_.AddressFamily -eq 'InterNetwork' }
        foreach ($a in $addrs) {
            $mdnsCandidates += [pscustomobject]@{ Ip = $a.IPAddressToString; Source = $name }
        }
    } catch { }
}

if ($mdnsCandidates.Count -gt 0) {
    Write-Host "Trovato via mDNS:" -ForegroundColor Green
    $mdnsCandidates | Format-Table -AutoSize
    if ($mdnsCandidates.Count -eq 1 -and $UpdateConfig) {
        Update-RetropieConfig -NewIp $mdnsCandidates[0].Ip
    }
    if (-not $UpdateConfig) {
        Write-Host "`nPer scrivere l'IP in retropie.json: .\find_retropie.ps1 -Ip <indirizzo>"
    }
    return
}
Write-Host "mDNS non ha risposto, scansiono la subnet..."

# --- passo 2: trova la subnet locale (adattatore con gateway attivo) ----
$adapter = Get-NetIPConfiguration | Where-Object {
    $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up'
} | Select-Object -First 1

if (-not $adapter) {
    Write-Error "Nessun adattatore di rete attivo con gateway trovato. Connettiti alla rete della fiera e riprova."
}

$localIp = $adapter.IPv4Address.IPAddress
$prefix = $adapter.IPv4Address.PrefixLength
Write-Host "Rete locale: $localIp/$prefix (adattatore: $($adapter.InterfaceAlias))"

if ($prefix -lt 22) {
    Write-Warning "Subnet molto grande (/$prefix), la scansione userà comunque solo il blocco /24 di $localIp."
}

$octets = $localIp.Split(".")
$base = "$($octets[0]).$($octets[1]).$($octets[2])"

Write-Host "Scansiono $base.1-254 sulla porta 22 (timeout ${TimeoutMs}ms per host)..."

# --- passo 3: scansione parallela con runspace pool ----------------------
$pool = [runspacefactory]::CreateRunspacePool(1, 64)
$pool.Open()
$jobs = @()

$scriptBlock = {
    param($ipAddr, $timeout)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($ipAddr, 22, $null, $null)
        $success = $iar.AsyncWaitHandle.WaitOne($timeout)
        if ($success -and $client.Connected) {
            $banner = $null
            try {
                $client.ReceiveTimeout = 500
                $stream = $client.GetStream()
                $buf = New-Object byte[] 128
                Start-Sleep -Milliseconds 150
                if ($stream.DataAvailable) {
                    $n = $stream.Read($buf, 0, $buf.Length)
                    $banner = [System.Text.Encoding]::ASCII.GetString($buf, 0, $n).Trim()
                }
            } catch { }
            [pscustomobject]@{ Ip = $ipAddr; Banner = $banner }
        }
    } catch { }
    finally { $client.Close() }
}

for ($i = 1; $i -le 254; $i++) {
    $target = "$base.$i"
    $ps = [powershell]::Create()
    $ps.RunspacePool = $pool
    [void]$ps.AddScript($scriptBlock).AddArgument($target).AddArgument($TimeoutMs)
    $jobs += [pscustomobject]@{ Pipe = $ps; Handle = $ps.BeginInvoke() }
}

$results = @()
foreach ($j in $jobs) {
    $out = $j.Pipe.EndInvoke($j.Handle)
    if ($out) { $results += $out }
    $j.Pipe.Dispose()
}
$pool.Close()
$pool.Dispose()

if ($results.Count -eq 0) {
    Write-Warning "Nessun host con porta 22 aperta trovato su $base.0/24."
    return
}

Write-Host "`nHost con SSH (porta 22) aperto:" -ForegroundColor Green
$results | Sort-Object Ip | Format-Table -AutoSize

$piCandidates = $results | Where-Object { $_.Banner -match "Raspbian|Debian|raspberrypi" }
if (-not $piCandidates) { $piCandidates = $results }

if ($piCandidates.Count -eq 1) {
    $found = $piCandidates[0].Ip
    Write-Host "`nCandidato piu' probabile: $found" -ForegroundColor Cyan
    if ($UpdateConfig) {
        Update-RetropieConfig -NewIp $found
    } else {
        Write-Host "Per scrivere l'IP in retropie.json: .\find_retropie.ps1 -Ip $found"
    }
} else {
    Write-Host "`nPiu' di un candidato: scegli l'IP giusto e lancia:"
    Write-Host "  .\find_retropie.ps1 -Ip <indirizzo>"
}
