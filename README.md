# Detección de microcalcificaciones en INbreast

Este repositorio permite reproducir la verificación del ground truth de INbreast, ejecutar el detector Python, compilar y evaluar dos implementaciones C++ y generar la comparación final. El umbral adaptativo es el eje metodológico del proyecto.

## Resultado principal

La auditoría identificó 315 imágenes positivas para presencia de microcalcificaciones: 313 con ROI individuales y 2 anotadas únicamente como cluster. De las 95 imágenes usadas históricamente como negativas, 94 son verificables y una, `20588138`, no tiene XML.

El C++ mejorado incluye dos comparadores experimentales:

- `sensitive` conserva un umbral adaptativo y alcanza 98.41 % de sensibilidad, pero solo 3.16 % de especificidad.
- `balanced` alcanza 82.18 % de precisión y 48.42 % de especificidad, pero utiliza un umbral DoG fijo de 0.10. Por ello se reporta como ablación y no como algoritmo final.

La siguiente versión recomendada debe combinar la normalización por percentiles, el enmascaramiento del fondo y la respuesta multiescala con un umbral adaptativo robusto calculado dentro de la máscara mamaria.

## Contenido

```text
.
├── README.md
├── requirements.txt
├── data/                         # instrucciones; el dataset no se versiona
├── src/
│   ├── deform_inbreast.cpp
│   └── deform_inbreast_mejorado.cpp
├── scripts/
│   ├── build_cpp.ps1
│   ├── reproducir_todo.ps1
│   ├── validacion_inbreast.py
│   ├── preparar_entregables.py
│   ├── verificar_microcalcificaciones.py
│   ├── consolidar_verificacion.py
│   ├── validar_cpp_mejorado.py
│   ├── comparar_tres_algoritmos.py
│   ├── auditar_anotaciones.py
│   ├── auditar_dicom_inbreast.py
│   ├── generar_excel.py
│   └── crear_informe_umbral_adaptativo.py
├── results/                      # resultados finales ya calculados
├── docs/
│   ├── PROTOCOLO-INBREAST-COMPLETO-2026.docx
│   └── informe_tecnico_umbral_adaptativo_inbreast.docx
├── examples/                     # cinco ejemplos visuales
└── bin/windows/                  # destino de compilación
```

## Requisitos

- Windows 10 u 11.
- Python 3.10 o posterior de 64 bits.
- `g++` con soporte C++17. La evaluación original usó MinGW-w64 g++ 15.2.0.
- Aproximadamente 12 GB libres para el dataset, resultados temporales y entorno.

## Instalación

Desde PowerShell, en la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Coloque INbreast según las instrucciones de `data/README.md`. La ruta predeterminada es:

```text
data/INbreast Release 1.0/
```

También puede conservar el dataset fuera del repositorio y pasar su ruta a los scripts.

## Reproducción completa

Con el dataset en la ubicación predeterminada:

```powershell
.\scripts\reproducir_todo.ps1
```

Con el dataset en otra carpeta:

```powershell
.\scripts\reproducir_todo.ps1 -Dataset "D:\datos\INbreast Release 1.0"
```

El proceso compila los C++, audita los XML y DICOM, ejecuta las 410 imágenes, genera las matrices de confusión y actualiza el informe. La corrida completa puede tardar varias horas, especialmente la versión multiescala.

## Ejecución por etapas

### Compilar C++

```powershell
.\scripts\build_cpp.ps1
```

Se generan dos ejecutables y dos DLL en `bin/windows`.

### Auditar las anotaciones

```powershell
python .\scripts\auditar_anotaciones.py --dataset ".\data\INbreast Release 1.0"
```

El resultado esperado es 313 imágenes con ROI individuales, 21 con cluster y 2 solo cluster.

### Ejecutar la referencia Python

```powershell
python .\scripts\validacion_inbreast.py `
  --dataset ".\data\INbreast Release 1.0" `
  --output ".\results"

python .\scripts\preparar_entregables.py `
  --dataset ".\data\INbreast Release 1.0" `
  --results ".\results"
```

### Evaluar el C++ actual

```powershell
python .\scripts\verificar_microcalcificaciones.py `
  --dataset ".\data\INbreast Release 1.0" `
  --dll ".\bin\windows\deform_inbreast.dll" `
  --output ".\results\verificacion_por_imagen.csv" `
  --summary ".\results\verificacion_resumen.json" `
  --k 70

python .\scripts\consolidar_verificacion.py `
  --dataset ".\data\INbreast Release 1.0" `
  --results ".\results"
```

### Evaluar el C++ mejorado

```powershell
python .\scripts\validar_cpp_mejorado.py `
  --dataset ".\data\INbreast Release 1.0" `
  --dll ".\bin\windows\deform_inbreast_mejorado.dll" `
  --results ".\results"
```

### Comparar y generar el informe

```powershell
python .\scripts\comparar_tres_algoritmos.py --results ".\results"
python .\scripts\generar_excel.py --results ".\results"
python .\scripts\crear_informe_umbral_adaptativo.py
```

## Resultados de referencia

| Implementación | TP | TN | FP | FN | Precisión | Sensibilidad | Especificidad | Exactitud balanceada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C++ original equivalente k20 | 312 | 1 | 94 | 3 | 76.85 % | 99.05 % | 1.05 % | 50.05 % |
| Python referencia k70 | 241 | 18 | 77 | 74 | 75.79 % | 76.51 % | 18.95 % | 47.73 % |
| C++ actual k70 | 276 | 8 | 87 | 39 | 76.03 % | 87.62 % | 8.42 % | 48.02 % |
| Mejorado fijo min3 | 226 | 46 | 49 | 89 | 82.18 % | 71.75 % | 48.42 % | 60.08 % |
| Mejorado adaptativo min1 | 310 | 3 | 92 | 5 | 77.11 % | 98.41 % | 3.16 % | 50.79 % |

Los resultados históricos usan 95 negativas operativas, incluyendo la imagen sin XML. Esta decisión se conserva para reproducir exactamente las tablas existentes y se documenta como limitación.

## Archivos principales de resultados

- `results/comparacion_tres_algoritmos.csv` y `.json`: métricas consolidadas.
- `results/verificacion_por_imagen_final.csv`: evaluación del C++ actual por imagen.
- `results/verificacion_cpp_mejorado_por_imagen.csv`: evaluación de los dos modos mejorados.
- `results/imagenes_con_microcalcificaciones_gt.csv`: inventario de imágenes positivas.
- `results/acierto_por_cantidad.csv`: resultados según cantidad de ROI.
- `results/verificacion_microcalcificaciones_inbreast.xlsx`: libro de auditoría.
- `docs/informe_tecnico_umbral_adaptativo_inbreast.docx`: informe técnico final.

## Notas metodológicas

- El C++ original del protocolo no incluye un evaluador masivo. La fila original se obtuvo reproduciendo su comportamiento OpenCV con `k=20`.
- El C++ actual usa componentes conectados y área por número de píxeles; el Python usa `contourArea`. Por eso no existe equivalencia exacta candidato por candidato.
- Las 410 imágenes no contienen `WindowCenter` ni `WindowWidth`. La normalización heredada coloca el fondo crudo cero cerca de 0.5 y puede producir candidatos de borde.
- El nombre histórico de la función de máscara menciona eliminación pectoral, pero la implementación solo selecciona el mayor componente Otsu y aplica cierre morfológico.
- Los parámetros experimentales se calibraron y evaluaron sobre el mismo conjunto. No deben presentarse como una estimación independiente de generalización.

## Antes de publicar

Este repositorio no contiene una licencia de software. Defina la licencia y revise las condiciones de uso de INbreast antes de hacer público el proyecto. No suba los DICOM ni otros datos médicos.
