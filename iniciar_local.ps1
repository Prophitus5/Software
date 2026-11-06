$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$tempDir = Join-Path $project '.tmp'
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
$env:TEMP = $tempDir
$env:TMP = $tempDir
$fbHome = 'C:\Program Files\Firebird\Firebird_5_0'
$isql = Join-Path $fbHome 'isql.exe'
$envFile = Join-Path $project '.env'

if (-not (Test-Path -LiteralPath $isql)) {
    throw 'No encuentro Firebird 5 en C:\Program Files\Firebird\Firebird_5_0. Instala Firebird 5 y vuelve a ejecutar este archivo.'
}
if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $project '.env.example') -Destination $envFile
    $secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
    (Get-Content -LiteralPath $envFile -Raw).Replace('change-this-to-a-long-random-value', $secret) | Set-Content -LiteralPath $envFile -NoNewline
    Write-Host 'Se creó .env. Puedes cambiar el correo y la contraseña del usuario dueño antes de presentar.'
}

$settings = @{}
Get-Content -LiteralPath $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') { $settings[$matches[1].Trim()] = $matches[2].Trim() }
}
$dataDir = Join-Path $project 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$dbPath = Join-Path $dataDir 'biblioteca.fdb'
$env:DB_MODE = 'embedded'
$env:DB_HOST = ''
$env:DB_PORT = ''
$env:DB_PATH = $dbPath
$env:DB_USER = if ($settings.DB_USER) { $settings.DB_USER } else { 'SYSDBA' }
$env:DB_PASSWORD = ''
$env:FB_CLIENT_LIBRARY = Join-Path $fbHome 'fbclient.dll'
$env:SECRET_KEY = if ($settings.SECRET_KEY) { $settings.SECRET_KEY } else { 'local-presentation-key-change-before-use' }
$env:OWNER_EMAIL = if ($settings.OWNER_EMAIL) { $settings.OWNER_EMAIL } else { 'dueno@biblioteca.local' }
$env:OWNER_PASSWORD = if ($settings.OWNER_PASSWORD) { $settings.OWNER_PASSWORD } else { 'ChangeMe123!' }
$env:LIBRARIAN_EMAIL = if ($settings.LIBRARIAN_EMAIL) { $settings.LIBRARIAN_EMAIL } else { 'bibliotecario@biblioteca.local' }
$env:LIBRARIAN_PASSWORD = if ($settings.LIBRARIAN_PASSWORD) { $settings.LIBRARIAN_PASSWORD } else { 'Bibliotecario123!' }
$env:FIELD_WORKER_EMAIL = if ($settings.FIELD_WORKER_EMAIL) { $settings.FIELD_WORKER_EMAIL } else { 'reclamador@biblioteca.local' }
$env:FIELD_WORKER_PASSWORD = if ($settings.FIELD_WORKER_PASSWORD) { $settings.FIELD_WORKER_PASSWORD } else { 'Reclamador123!' }
$env:COOKIE_SECURE = 'false'

if (-not (Test-Path -LiteralPath $dbPath)) {
    $sqlPath = Join-Path $env:TEMP 'biblioteca-inicializar.sql'
    $quotedDb = $dbPath.Replace('\','/').Replace("'", "''")
    $dbScripts = @('01_schema.sql','02_generators_triggers.sql','03_seed.sql','04_indexes.sql')
    $sql = "CREATE DATABASE '$quotedDb' DEFAULT CHARACTER SET UTF8;`r`n"
    foreach ($script in $dbScripts) {
        $scriptPath = (Join-Path $project "db\$script").Replace('\','/').Replace("'", "''")
        $sql += "INPUT '$scriptPath';`r`n"
    }
    $sql += 'QUIT;'
    Set-Content -LiteralPath $sqlPath -Value $sql -Encoding Ascii
    & $isql -b -q -i $sqlPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $dbPath)) { throw 'No se pudo crear la base Firebird. Revisa el servicio, usuario y contraseña.' }
    Write-Host "Base de datos creada: $dbPath"
}

$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    python -m venv (Join-Path $project '.venv')
    $python = Join-Path $project '.venv\Scripts\python.exe'
    & $python -m pip install --upgrade pip
    & $python -m pip install -r (Join-Path $project 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de Python.' }
}

Write-Host 'Abriendo el sistema en http://127.0.0.1:8000 (Ctrl+C para detener).'
& $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
