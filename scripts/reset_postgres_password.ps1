$ErrorActionPreference = "Stop"

$serviceName = "postgresql-x64-17"
$pgRoot = "C:\Program Files\PostgreSQL\17"
$dataDir = Join-Path $pgRoot "data"
$pgHba = Join-Path $dataDir "pg_hba.conf"
$backup = "$pgHba.bak_sign_app"
$psql = Join-Path $pgRoot "bin\psql.exe"
$createdb = Join-Path $pgRoot "bin\createdb.exe"

if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from PowerShell opened as Administrator."
}

foreach ($path in @($pgHba, $psql, $createdb)) {
    if (-not (Test-Path $path)) {
        throw "Required file not found: $path"
    }
}

Copy-Item -LiteralPath $pgHba -Destination $backup -Force

try {
    $content = Get-Content -LiteralPath $pgHba
    $updated = foreach ($line in $content) {
        if ($line -match '^\s*host\s+.+\s+127\.0\.0\.1/32\s+\S+') {
            $line -replace '\S+\s*$', 'trust'
        }
        elseif ($line -match '^\s*host\s+.+\s+::1/128\s+\S+') {
            $line -replace '\S+\s*$', 'trust'
        }
        else {
            $line
        }
    }

    Set-Content -LiteralPath $pgHba -Value $updated -Encoding ASCII
    Restart-Service -Name $serviceName
    Start-Sleep -Seconds 3

    & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -w -c "ALTER USER postgres WITH PASSWORD 'postgres';"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not reset postgres password."
    }

    $dbExists = & $psql -h 127.0.0.1 -p 5432 -U postgres -d postgres -w -tAc "SELECT 1 FROM pg_database WHERE datname='sign_app';"
    if (($dbExists | Out-String).Trim() -ne "1") {
        & $createdb -h 127.0.0.1 -p 5432 -U postgres -w sign_app
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create sign_app database."
        }
    }
}
finally {
    Copy-Item -LiteralPath $backup -Destination $pgHba -Force
    Restart-Service -Name $serviceName
}

$env:PGPASSWORD = "postgres"
& $psql -h 127.0.0.1 -p 5432 -U postgres -d sign_app -c "SELECT current_database(), current_user;"
if ($LASTEXITCODE -ne 0) {
    throw "Password was reset, but final connection test failed."
}

Write-Output "PostgreSQL is ready for this project: database=sign_app user=postgres password=postgres"
