param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,

    [string]$DatabasePath = (Join-Path $env:USERPROFILE '.suryanesia-hris\hris.sqlite3')
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$serverPath = Join-Path $workspaceRoot 'hris_server.py'
$localDatabasePath = [System.IO.Path]::GetFullPath($DatabasePath)
$environmentNames = @(
    'DATABASE_URL',
    'VERCEL',
    'VERCEL_ENV',
    'VERCEL_URL',
    'VERCEL_PROJECT_PRODUCTION_URL',
    'HRIS_HOST',
    'HRIS_PORT',
    'HRIS_DATABASE_PATH',
    'HRIS_DEMO_MODE',
    'HRIS_DEMO_SESSION_SECRET'
)
$previousEnvironment = @{}

foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $versionOutput = & $pythonCommand.Source --version 2>&1
    if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch 'Python (\d+)\.(\d+)') {
        throw 'Python could not be run. Install Python 3.8 or later and reopen PowerShell.'
    }
    $pythonMajor = [int]$Matches[1]
    $pythonMinor = [int]$Matches[2]
    if ($pythonMajor -lt 3 -or ($pythonMajor -eq 3 -and $pythonMinor -lt 8)) {
        throw "Python 3.8 or later is required; found $versionOutput."
    }

    $env:DATABASE_URL = ''
    Remove-Item Env:VERCEL -ErrorAction SilentlyContinue
    Remove-Item Env:VERCEL_ENV -ErrorAction SilentlyContinue
    Remove-Item Env:VERCEL_URL -ErrorAction SilentlyContinue
    Remove-Item Env:VERCEL_PROJECT_PRODUCTION_URL -ErrorAction SilentlyContinue
    $env:HRIS_HOST = '127.0.0.1'
    $env:HRIS_PORT = [string]$Port
    $env:HRIS_DATABASE_PATH = $localDatabasePath
    Remove-Item Env:HRIS_DEMO_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:HRIS_DEMO_SESSION_SECRET -ErrorAction SilentlyContinue

    $dependencyCheck = & $pythonCommand.Source -c "import dotenv; import backend.app.api.responses; import backend.app.database.initialize" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Required Python dependencies or application modules are unavailable. Install the existing requirements.txt in your environment, then retry.`n$dependencyCheck"
    }

    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $Port
    )
    try {
        $listener.Start()
    }
    catch {
        throw "Port $Port is already in use. Stop the local process using that port or retry with: .\scripts\start-local.ps1 -Port <available-port>"
    }
    finally {
        $listener.Stop()
    }

    if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
        throw "Application entrypoint was not found: $serverPath"
    }
    $workspacePrefix = $workspaceRoot.TrimEnd('\') + '\'
    if ($localDatabasePath.StartsWith($workspacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The SQLite database must be outside the served project folder.'
    }

    Write-Host "Using local SQLite database: $localDatabasePath"
    Write-Host 'Preparing local schema and synthetic demo accounts (existing database data is preserved)...'
    & $pythonCommand.Source -c "import hris_server; hris_server.initialize_database()"
    if ($LASTEXITCODE -ne 0) {
        throw "Local database initialization failed with exit code $LASTEXITCODE."
    }

    Write-Host "Starting Employee Hub at http://127.0.0.1:$Port/"
    Write-Host 'Press Ctrl+C to stop the local server.'
    & $pythonCommand.Source $serverPath
    if ($LASTEXITCODE -ne 0) {
        throw "The local server exited with code $LASTEXITCODE."
    }
}
catch {
    Write-Error $_
    exit 1
}
finally {
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
