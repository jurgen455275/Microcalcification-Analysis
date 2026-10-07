param(
    [string]$Compiler = "g++"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Source = Join-Path $Repo "src"
$Bin = Join-Path $Repo "bin\windows"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

& $Compiler -std=c++17 -O3 -DNDEBUG (Join-Path $Source "deform_inbreast.cpp") -o (Join-Path $Bin "deform_inbreast.exe")
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de deform_inbreast.exe" }

& $Compiler -std=c++17 -O3 -shared -static -DINBREAST_LIBRARY (Join-Path $Source "deform_inbreast.cpp") -o (Join-Path $Bin "deform_inbreast.dll")
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de deform_inbreast.dll" }

& $Compiler -std=c++17 -O3 -static (Join-Path $Source "deform_inbreast_mejorado.cpp") -o (Join-Path $Bin "deform_inbreast_mejorado.exe")
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de deform_inbreast_mejorado.exe" }

& $Compiler -std=c++17 -O3 -shared -static -DINBREAST_MEJORADO_LIBRARY (Join-Path $Source "deform_inbreast_mejorado.cpp") -o (Join-Path $Bin "deform_inbreast_mejorado.dll")
if ($LASTEXITCODE -ne 0) { throw "Falló la compilación de deform_inbreast_mejorado.dll" }

Write-Host "Binarios generados en $Bin"
