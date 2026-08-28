[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Detached
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepositoryRoot

try {
    if (-not (Test-Path -LiteralPath '.env')) {
        throw 'Missing .env. Run: Copy-Item .env.example .env, then review the local settings.'
    }

    if ($Stop) {
        docker compose -f compose.yaml -f compose.dev.yaml down
        exit $LASTEXITCODE
    }

    $Arguments = @('compose', '-f', 'compose.yaml', '-f', 'compose.dev.yaml', 'up', '--build')
    if ($Detached) {
        $Arguments += '-d'
    }
    & docker @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
