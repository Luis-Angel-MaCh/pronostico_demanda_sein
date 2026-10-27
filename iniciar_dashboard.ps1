param(
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPath = Join-Path $projectPath 'scripts\local-dashboard.mjs'
$panelUrl = 'http://localhost:5173/'
$venvPython = Join-Path $projectPath '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $env:LDS_PYTHON = $venvPython }

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$nodePath = if ($nodeCommand) { $nodeCommand.Source } else { $null }

if (-not $nodePath -or -not (Test-Path -LiteralPath $nodePath)) {
    throw 'No se encontro Node.js. Instala Node.js LTS y vuelve a ejecutar la aplicacion.'
}

function Test-PanelReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $panelUrl -TimeoutSec 3
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Test-PanelPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', 5173, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(750, $false)) { return $false }
        $client.EndConnect($pending)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

$ready = Test-PanelReady
$serverProcess = $null

if (-not $ready -and -not (Test-PanelPort)) {
    $serverProcess = Start-Process -FilePath $nodePath `
        -ArgumentList @('--use-system-ca', ('"{0}"' -f $serverPath)) `
        -WorkingDirectory $projectPath `
        -WindowStyle Hidden `
        -PassThru
}

if (-not $ready) {
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Milliseconds 500
        $ready = Test-PanelReady
        if ($ready) { break }
        if ($serverProcess -and $serverProcess.HasExited -and -not (Test-PanelPort)) {
            throw "El servidor termino antes de iniciar. Codigo de salida: $($serverProcess.ExitCode)."
        }
    }

    if (-not $ready) {
        if (Test-PanelPort) {
            throw 'El puerto 5173 esta ocupado por otro proceso, pero el panel no responde.'
        }
        throw 'El servidor no respondio despues de 60 segundos.'
    }
}

if (-not $NoBrowser) {
    Start-Process $panelUrl
}
