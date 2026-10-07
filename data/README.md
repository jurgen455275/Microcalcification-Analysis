# Datos INbreast

El dataset no se incluye en Git porque ocupa aproximadamente 9 GB y puede estar sujeto a condiciones de distribución.

Coloque el conjunto con esta estructura:

```text
data/
└── INbreast Release 1.0/
    ├── AllDICOMs/
    │   └── *.dcm
    ├── AllXML/
    │   └── *.xml
    ├── INbreast.csv
    └── INbreast.xls
```

La reproducción espera 410 archivos DICOM. La etiqueta de presencia se obtiene de los XML, no únicamente de la hoja de cálculo.

La imagen `20588138` no tiene XML en la copia evaluada. Los resultados históricos la tratan como negativa operativa para mantener la matriz de 410 imágenes, pero una evaluación nueva debe marcarla como ground truth no disponible y reportar también las métricas sobre los 409 casos verificables.
