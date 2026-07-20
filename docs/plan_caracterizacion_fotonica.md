# Plan para caracterizacion automatica de dispositivos fotonicos integrados

## Objetivo

Desarrollar en Python un sistema para medir automaticamente espectros de dispositivos fotonicos integrados acoplados mediante grating couplers, partiendo de la informacion del GDS y usando:

- Motores y piezoelectricos Thorlabs para posicionar fibras.
- Camara cenital para ver chip y fibras.
- Laseres sintonizables y power meters controlables por Python.
- Rutinas de alineamiento optico y adquisicion espectral.

La prioridad de diseno es evitar danos mecanicos, especialmente por aproximacion excesiva en `z`.

## Idea general

El programa no deberia empezar como un sistema completamente autonomo. La version mas robusta y sencilla es incremental:

1. Alinear manualmente el primer dispositivo.
2. Usar el GDS o una tabla exportada desde el GDS para conocer offsets entre dispositivos.
3. Moverse automaticamente entre estructuras.
4. Realinear en `x/y` con barridos pequenos y optimizacion local.
5. Medir espectros.
6. Guardar imagenes, posiciones, espectros y estados.
7. Automatizar vision y `z` solo cuando haya calibracion y datos suficientes.

## Arquitectura propuesta

```text
layout/
  Lee GDS, labels, puertos, grating couplers y dispositivos.

motion/
  Controla motores, piezos, limites, homing y movimientos seguros.

vision/
  Captura imagenes, detecta fiduciales, fibras, sombras y grating couplers.

alignment/
  Ejecuta alineamiento grueso, barridos x/y, optimizacion fina y checks de seguridad.

instruments/
  Controla laser, power meter, barridos espectrales y referencias.

runner/
  Ejecuta la cola de dispositivos, mide, guarda resultados y permite reanudar.
```

## Datos de entrada recomendados

Aunque se puede leer directamente el GDS, conviene generar una tabla de medida desde el flujo de layout. Por ejemplo:

```csv
device_id,input_gc_x,input_gc_y,output_gc_x,output_gc_y,polarization,lambda_start_nm,lambda_stop_nm,lambda_step_nm
ring_001,1200.0,500.0,1270.0,500.0,TE,1500,1600,0.02
mzi_001,1500.0,500.0,1570.0,500.0,TE,1500,1600,0.02
```

El GDS deberia incluir labels o una convencion clara para identificar:

- Dispositivo.
- Grating coupler de entrada.
- Grating coupler de salida.
- Polarizacion esperada.
- Rango espectral esperado.

Si el GDS solo contiene geometria sin labels, se puede inferir informacion, pero sera mas fragil.

## Transformacion GDS a chip real

El programa necesita convertir coordenadas del GDS a coordenadas fisicas del montaje.

Flujo minimo:

1. El usuario selecciona o detecta varios fiduciales visibles.
2. Se conocen sus coordenadas en GDS.
3. Se mide su posicion en imagen o en coordenadas de stage.
4. Se ajusta una transformacion afin:

```text
[x_stage, y_stage] = A * [x_gds, y_gds] + b
```

Con tres puntos basta para una transformacion afin basica. Mas puntos permiten ajustar mejor y detectar errores.

## Seguridad en z

Esta es la parte critica. El sistema no debe buscar altura libremente usando solo potencia optica.

### Regla principal

`z` debe estar limitado por una ventana segura:

```text
z_min(x, y) = z_chip(x, y) + margen_seguridad
```

El software nunca debe bajar por debajo de `z_min`.

### Plano del chip

Medir manualmente al menos tres puntos del chip y ajustar un plano:

```text
z_chip(x, y) = ax + by + c
```

Luego se define un margen:

```text
z_seguro = z_chip(x, y) + margen_seguridad
```

El margen debe elegirse experimentalmente y de forma conservadora.

### Movimiento seguro

Para cualquier desplazamiento largo:

1. Subir fibras a altura de viaje.
2. Mover `x/y`.
3. Aproximar en `z` lentamente solo hasta la ventana permitida.
4. Hacer alineamiento fino dentro de esa ventana.

Nunca hacer movimientos laterales grandes cerca del chip.

### Interlocks minimos

- Limites software en `z`.
- Limites hardware si el controlador los soporta.
- Velocidad baja en aproximacion vertical.
- Paso maximo pequeno en `z`.
- Boton o comando de parada de emergencia.
- Retraccion automatica si la camara pierde la fibra o la zona esperada.
- Retraccion automatica si el detector visual marca peligro.
- Log de cada movimiento.

## Uso de la camara para estimar proximidad

La camara cenital puede ayudar a estimar si la fibra esta lejos o cerca usando la posicion relativa entre fibra y sombra.

Con iluminacion lateral fija:

```text
separacion fibra-sombra en pixeles -> altura aproximada sobre el chip
```

Cuando la fibra se acerca al chip, la fibra y su sombra tienden a juntarse en la imagen. Esto se puede calibrar midiendo imagenes a alturas conocidas.

### Uso recomendado

La vision debe actuar como interlock o semaforo:

```text
lejos -> continuar aproximacion
zona trabajo -> permitir alineamiento optico
peligro -> parar y subir
dudoso -> parar y subir
```

No conviene que la vision sea el unico sensor de seguridad hasta haber validado muchas aproximaciones.

## Vision clasica antes de redes neuronales

Antes de entrenar una red neuronal, probar con OpenCV:

- Conversion a gris.
- Filtros y normalizacion.
- Deteccion de bordes.
- Umbral adaptativo.
- Transformada de Hough para lineas.
- Segmentacion simple por contraste.
- Tracking de fibra entre frames.

Objetivo minimo:

```text
imagen -> eje de fibra, eje de sombra, separacion en pixeles, confianza
```

Si OpenCV funciona de forma repetible, no hace falta red neuronal.

## Dataset desde el primer dia

Aunque inicialmente se use OpenCV, conviene guardar datos para poder entrenar modelos despues:

```text
timestamp
imagen
x_stage, y_stage, z_stage
potencia
lambda
device_id
estado_manual: lejos / trabajo / peligro / dudoso
separacion_fibra_sombra_px
comentarios
```

Esto permite entrenar una red con datos reales del montaje, que es mucho mas util que usar imagenes genericas.

## Redes neuronales posibles

Si la vision clasica no es robusta:

### Clasificacion

Entrada: imagen o region de interes.

Salida:

```text
seguro / zona_trabajo / peligro / dudoso
```

Ventaja: facil de etiquetar.

### Deteccion de objetos

Detectar cajas de:

- Fibra.
- Sombra.
- Grating coupler.
- Fiduciales.

Puede hacerse con modelos tipo YOLO.

### Segmentacion

Obtener mascaras pixel a pixel de:

- Fibra.
- Sombra.
- Chip.
- Grating coupler.

Mas preciso, pero requiere mas trabajo de etiquetado.

### Regresion

Predecir directamente:

```text
altura_z_estimada
```

No es lo primero que haria. Es mas peligroso si el modelo se equivoca.

## Regla de seguridad para IA

La red neuronal no debe mandar bajar la fibra. Solo debe bloquear o permitir movimiento dentro de limites ya seguros.

Si la confianza es baja:

```text
parar -> subir -> pedir intervencion
```

## Alineamiento optico

### Version minima

1. Mover al dispositivo segun offset de GDS.
2. Hacer barrido pequeno en `x/y`.
3. Encontrar maximo de potencia.
4. Ajustar con piezos alrededor del maximo.
5. Medir espectro.

### Barrido x/y

Ejemplo:

```text
grid de 5x5 o 7x7
paso inicial: varias micras
medir potencia en cada punto
ir al maximo
repetir con paso menor
```

### Optimizacion fina

Opciones sencillas:

- Coordenada a coordenada.
- Hill climb.
- Nelder-Mead con limites.

Evitar algoritmos complejos al principio.

## Medida espectral

Flujo recomendado:

1. Configurar laser.
2. Configurar power meter.
3. Medir dark si aplica.
4. Medir referencia si aplica.
5. Barrer longitud de onda.
6. Guardar potencia y metadata.
7. Calcular transmision corregida.

Guardar siempre datos crudos y corregidos.

Formato simple:

```csv
device_id,wavelength_nm,power_dbm,power_w,x,y,z,input_fiber_id,output_fiber_id,timestamp
```

## Fases de implementacion

### Fase 0: control manual asistido

Objetivo: controlar instrumentos y guardar datos sin autonomia.

- Controlar motores desde Python.
- Controlar laser y power meter.
- Capturar imagenes de camara.
- Medir un espectro manualmente.
- Guardar metadata completa.

Resultado esperado: una medida manual queda reproducible y registrada.

### Fase 1: medicion automatica desde posicion inicial

Objetivo: automatizar espectros manteniendo alineamiento manual.

- Usuario alinea primer dispositivo.
- Programa barre laser.
- Guarda espectro.
- No mueve `z` automaticamente salvo retraccion segura.

Resultado esperado: espectros fiables de un dispositivo.

### Fase 2: cola de dispositivos con offsets GDS

Objetivo: medir varios dispositivos tras un alineamiento inicial.

- Leer tabla exportada del GDS.
- Mover `x/y` por offsets relativos.
- Antes de cada movimiento largo, subir a altura de viaje.
- Hacer barrido local en `x/y`.
- Medir espectro.

Resultado esperado: medir una fila o matriz de dispositivos.

### Fase 3: plano del chip y limites z

Objetivo: hacer `z` seguro y repetible.

- Medir varios puntos del chip.
- Ajustar plano `z_chip(x, y)`.
- Definir margen de seguridad.
- Bloquear cualquier movimiento que cruce `z_min`.
- Registrar eventos de bloqueo.

Resultado esperado: el software no puede bajar mas de lo permitido.

### Fase 4: vision como interlock

Objetivo: usar camara para detectar proximidad peligrosa.

- Fijar iluminacion lateral.
- Detectar fibra y sombra con OpenCV.
- Medir separacion en pixeles.
- Calibrar separacion contra altura.
- Parar/subir si hay peligro o baja confianza.

Resultado esperado: segunda capa de seguridad independiente de la potencia optica.

### Fase 5: reconocimiento por red neuronal

Objetivo: mejorar robustez si OpenCV no basta.

- Etiquetar imagenes reales.
- Entrenar clasificador o detector.
- Validar con datos no usados en entrenamiento.
- Integrar solo como interlock.

Resultado esperado: deteccion mas robusta de estados visuales.

### Fase 6: autonomia completa parcial

Objetivo: ejecutar una receta de medida completa con supervision.

- Detectar fiduciales.
- Ajustar transformacion GDS-stage.
- Recorrer dispositivos.
- Realinear `x/y`.
- Ajustar `z` solo dentro de ventana segura.
- Medir espectros.
- Reanudar tras fallos.

Resultado esperado: medida semiautomatica robusta de chips completos.

## Pruebas recomendadas

### Sin chip

- Verificar limites de movimiento.
- Verificar parada de emergencia.
- Verificar que movimientos largos suben primero.
- Simular posiciones peligrosas.

### Con muestra sacrificable

- Calibrar plano del chip.
- Probar aproximaciones lentas.
- Registrar imagenes a alturas conocidas.
- Validar detector fibra-sombra.

### Con chip real

- Empezar con `z` manual.
- Automatizar solo `x/y` y espectro.
- Activar interlocks visuales.
- Automatizar pequenos ajustes en `z` al final.

## Riesgos principales

| Riesgo | Mitigacion |
|---|---|
| Choque fibra-chip | Limites `z`, plano del chip, altura de viaje, interlock visual |
| Perdida de alineamiento | Barrido local `x/y`, reintentos, logs |
| GDS mal interpretado | Labels claros, tabla exportada, fiduciales |
| Vision inestable | Iluminacion fija, calibracion, umbral de confianza |
| Red neuronal equivocada | Usarla solo para bloquear/avisar, no para bajar |
| Danos por bug software | Limites hardware, velocidades bajas, boton de emergencia |

## Librerias Python candidatas

- `opencv-python`: vision clasica, bordes, filtros, tracking.
- `numpy`, `scipy`: geometria, optimizacion y procesado numerico.
- `pandas`: tablas de dispositivos y resultados.
- `gdsfactory` o API de KLayout: lectura/exportacion de informacion del GDS.
- `pylablib`, `thorlabs_apt_device` o SDKs Thorlabs: control de movimiento segun hardware concreto.
- `pyvisa`: control de instrumentos por VISA.
- `pytorch`: entrenamiento de modelos de vision si hace falta.
- `ultralytics`: deteccion/segmentacion tipo YOLO si se etiqueta dataset.

Referencias utiles:

- OpenCV: <https://opencv-opencv.mintlify.app/>
- PyTorch transfer learning: <https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html>
- Ultralytics YOLO: <https://docs.ultralytics.com/>
- gdsfactory: <https://gdsfactory.github.io/gdsfactory/>

## Decision minima recomendada

No empezar por IA ni por control autonomo de `z`.

Empezar por:

```text
GDS/CSV -> movimiento x/y seguro -> barrido local x/y -> espectro -> logging completo
```

En paralelo:

```text
guardar imagenes + z conocido + etiqueta manual
```

Con eso se consigue una herramienta util pronto y se construye el dataset necesario para una capa de vision/IA fiable.

## Criterio para automatizar z

Automatizar `z` solo cuando se cumpla todo:

- Plano del chip calibrado y repetible.
- Limites software probados.
- Limites hardware disponibles o mitigacion equivalente.
- Altura de viaje validada.
- Detector visual de proximidad funcionando como interlock.
- Ensayos exitosos con muestra sacrificable.
- Logs suficientes para auditar fallos.

Hasta entonces, `z` debe ser manual, semiautomatico o limitado a una ventana pequena.
