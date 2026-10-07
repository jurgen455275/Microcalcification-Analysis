# Resultados incluidos

Esta carpeta contiene la corrida de referencia sobre 410 imágenes. Se versionan los resultados finales para que las métricas del informe puedan comprobarse sin distribuir el dataset.

Los archivos principales son:

- `comparacion_tres_algoritmos.csv` y `.json`: comparación consolidada.
- `verificacion_por_imagen_final.csv`: salida del C++ actual con ground truth combinado.
- `verificacion_cpp_mejorado_por_imagen.csv`: salidas balanced y sensitive.
- `imagenes_con_microcalcificaciones_gt.csv`: inventario de imágenes positivas.
- `acierto_por_cantidad.csv`: aciertos agrupados por cantidad de ROI.
- `froc_inbreast.csv`: salida completa de la referencia Python para nueve valores de k.
- `resumen_por_k.csv` y `resumen_por_k_y_acr.csv`: agregados de la curva FROC.
- `verificacion_microcalcificaciones_inbreast.xlsx`: versión tabular para revisión manual.

`reproducir_todo.ps1` vuelve a generar estos archivos. Los tiempos pueden variar según el procesador y el compilador, pero las matrices de confusión deben coincidir si se usa la misma copia del dataset y las mismas reglas.
