param(
    [string]$Dataset,
    [string]$Python
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
if (-not $Dataset) { $Dataset = Join-Path $Repo "data\INbreast Release 1.0" }
if (-not $Python) {
    $VenvPython = Join-Path $Repo ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $VenvPython) { $VenvPython } else { "python" }
}
$Results = Join-Path $Repo "results"
$Bin = Join-Path $Repo "bin\windows"

foreach ($Required in @("AllDICOMs", "AllXML", "INbreast.csv")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Dataset $Required))) {
        throw "Falta $Required dentro de $Dataset"
    }
}

& (Join-Path $PSScriptRoot "build_cpp.ps1")

& $Python (Join-Path $PSScriptRoot "auditar_anotaciones.py") --dataset $Dataset
if ($LASTEXITCODE -ne 0) { throw "Falló la auditoría de anotaciones" }

& $Python (Join-Path $PSScriptRoot "auditar_dicom_inbreast.py") --dataset $Dataset
if ($LASTEXITCODE -ne 0) { throw "Falló la auditoría DICOM" }

& $Python (Join-Path $PSScriptRoot "validacion_inbreast.py") --dataset $Dataset --output $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la validación Python" }

& $Python (Join-Path $PSScriptRoot "preparar_entregables.py") --dataset $Dataset --results $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la preparación de resúmenes y ejemplos" }

& $Python (Join-Path $PSScriptRoot "verificar_microcalcificaciones.py") `
    --dataset $Dataset `
    --dll (Join-Path $Bin "deform_inbreast.dll") `
    --output (Join-Path $Results "verificacion_por_imagen.csv") `
    --summary (Join-Path $Results "verificacion_resumen.json") `
    --k 70
if ($LASTEXITCODE -ne 0) { throw "Falló la validación del C++ actual" }

& $Python (Join-Path $PSScriptRoot "consolidar_verificacion.py") --dataset $Dataset --results $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la consolidación del ground truth" }

& $Python (Join-Path $PSScriptRoot "validar_cpp_mejorado.py") `
    --dataset $Dataset `
    --dll (Join-Path $Bin "deform_inbreast_mejorado.dll") `
    --results $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la validación del C++ mejorado" }

& $Python (Join-Path $PSScriptRoot "comparar_tres_algoritmos.py") --results $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la comparación de algoritmos" }

& $Python (Join-Path $PSScriptRoot "generar_excel.py") --results $Results
if ($LASTEXITCODE -ne 0) { throw "Falló la generación del libro Excel" }

& $Python (Join-Path $PSScriptRoot "crear_informe_umbral_adaptativo.py")
if ($LASTEXITCODE -ne 0) { throw "Falló la generación del informe" }

Write-Host "Reproducción terminada. Revise results y docs."
