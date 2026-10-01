# Casos de prueba del validator

Estos casos sirven para probar la validación y el comportamiento de las skills. No son artículos aprobados para publicar.

## Caso 1: texto de instructivo sin plantilla aplicada

**Tipo:** Instructivo  
**Estado inicial:** texto libre, sin aplicar la plantilla Instructivo.  
**Objetivo de la prueba:** comprobar que la skill reconoce la plantilla indicada, reorganiza el material en sus secciones y separa los hallazgos de validación del contenido del artículo.

**Entrada de prueba:**

Título: Cómo preparar una cotización de venta de granos  
Categoría: ERP / Agronegocios  
Tipo de plantilla: Instructivo

Para preparar una cotización de venta de granos en Finnegans, se debe indicar quién vende y quién compra, qué grano se ofrece y a qué campaña corresponde. Como ejemplo, Agropecuaria El Ombú SRL quiere cotizar a Molinos del Centro SA la venta de 120 toneladas de soja de la campaña 2025/2026. La mercadería es condición Cámara, con humedad máxima del 14 % e impurezas de hasta el 2,5 %. La entrega se realizará en la planta de recepción de Puerto General San Martín entre el 12 y el 20 de octubre de 2026. El precio acordado es de $320.000 por tonelada, más los impuestos que correspondan. El pago deberá realizarse dentro de las 48 horas de recibida la mercadería y conformado el certificado de descarga. La cotización tendrá vigencia hasta el 2 de octubre de 2026. Si no es posible cumplir con las fechas de entrega indicadas, se debe informar antes de confirmar la operación.

**Criterios esperados:**

- Incluir `instructivo` entre las etiquetas junto con etiquetas temáticas.
- Aplicar la plantilla Instructivo; no presentar el texto libre como si ya estuviera estructurado.
- No inventar ruta, pantallas ni pasos de Finnegans que no estén en la fuente.
- Identificar y generalizar los nombres de empresas y las condiciones comerciales que describen una operación particular.
- Informar datos faltantes y hallazgos fuera del artículo, no crear una sección editorial “Revisión” dentro del contenido.

**Estado esperado:** Pendiente si permanecen datos comerciales particulares o rutas sin confirmar; en caso contrario, Listo con ajustes sugeridos.

## Caso 2: solución con cifras y regla ficticias

**Tipo:** Soluciones  
**Estado inicial:** texto libre, sin plantilla aplicada; las cifras y la regla fiscal son explícitamente ficticias.  
**Objetivo de la prueba:** comprobar que la skill aplica la plantilla de Soluciones, agrega la etiqueta obligatoria `soluciones` y bloquea la publicación de información fiscal inventada.

**Entrada de prueba:**

Título: Cálculo incorrecto de la tasa imponible para vehículos de alta gama  
Categoría: ERP  
Tipo de plantilla: Soluciones  
Etiquetas sugeridas: Impuestos, vehículos, tasa-imponible

Al calcular el impuesto para un vehículo de alta gama valuado en $95.000.000, el sistema determina un importe de $19.000.000, pero para este caso de prueba debería calcular $3.000.000. La regla ficticia usada en la prueba establece un umbral de $80.000.000 y una tasa del 20 % únicamente sobre el importe que excede ese umbral. Por eso, la base alcanzada es de $15.000.000 y el impuesto resultante es de $3.000.000. El error se produce porque la tasa se está aplicando sobre el valor total del vehículo. Hay que revisar la configuración de la fórmula para que tome solo el excedente sobre el umbral y luego volver a calcular el impuesto. Estos valores son inventados para probar la plantilla; no representan una regla fiscal vigente.

**Criterios esperados:**

- Incluir `soluciones` entre las etiquetas junto con `impuestos`, `vehículos` y `tasa-imponible`.
- Proponer un título orientado a la acción y al problema, sin presentar “Error” como etiqueta salvo que forme parte de un mensaje literal del sistema.
- Organizar el artículo con **Consulta**, **Respuesta** y **Pasos a seguir**, en ese orden.
- No inventar la ruta de acceso, los nombres de campos ni pasos detallados que no figuran en la entrada.
- Marcar como bloqueante que las cifras y la regla son ficticias; el borrador solo puede mostrarse como ejemplo de prueba y no aprobarse para publicación.
- Mantener el aviso de no vigencia fuera del artículo publicable, salvo que se conserve como texto de prueba claramente identificado.

**Estado esperado:** Pendiente; las cifras y la regla fiscal ficticias bloquean la publicación.

**Artículo de prueba esperado (no publicar):**

**Título:** Calcular el impuesto para vehículos de alta gama - Aplicar la tasa sobre el excedente  
**Categoría:** ERP  
**Tipo de plantilla:** Soluciones  
**Etiquetas:** impuestos, vehículos, tasa-imponible, soluciones

### Consulta

Al calcular el impuesto para un vehículo valuado en $95.000.000, el sistema determina un importe de $19.000.000. Para este caso de prueba, el importe esperado es de $3.000.000.

Para solucionarlo, revisar la configuración de la fórmula para que aplique la tasa únicamente sobre el importe que excede el umbral.

### Pasos a seguir

**Ruta:** [Indicar la ruta desde donde se accede a la configuración de la fórmula].

1. Revisar la configuración de la fórmula para que aplique la tasa únicamente sobre el importe que excede el umbral.
2. Volver a calcular el impuesto.

**Resultado editorial esperado:** fuera del artículo, informar que la ruta está pendiente y que el ejemplo no se puede publicar porque sus cifras y regla son ficticias y no representan una regla fiscal vigente. No agregar una sección “Respuesta” ni una sección editorial “Revisión” al artículo.

## Caso 3: solución con causa y resolución no confirmadas

**Tipo:** Soluciones  
**Estado inicial:** texto libre con causa parcial, solución tentativa y dudas explícitas sobre el procedimiento.  
**Objetivo de la prueba:** comprobar que el validator mejora título y redacción sin presentar una hipótesis como solución confirmada, conserva los datos pendientes y separa el borrador del diagnóstico editorial.

### Entrada de prueba original

**Título:** problema granos  
**Categoría:** Agronegocios  
**Tipo de plantilla:** Soluciones

Cuando se hace la liquidacion primaria de venta de soja el descuento por calidad a veces no sale. El sistema toma mal los datos y queda cualquier cosa. Esto pasa cuando el operador carga el certificado de calidad después de hacer la liquidación, pero no siempre, depende. Para arreglarlo hay que revisar la tabla de calidad de soja y que tenga cargada la campaña. Luego volver a entrar y hacer lo mismo de nuevo. No se sabe bien si hace falta anular la liquidación o alcanza con actualizar.

### Versión revisada propuesta

**Título:** Revisar el descuento por calidad en liquidaciones primarias de venta de soja  
**Categoría:** Agronegocios  
**Tipo de plantilla:** Soluciones  
**Etiquetas:** soluciones; faltan confirmar las etiquetas temáticas.

#### Consulta

**Ruta:** [Indicar la ruta donde se realiza la liquidación y se carga el certificado de calidad].

Al realizar una liquidación primaria de venta de soja, el descuento por calidad no se aplica correctamente en algunos casos. El comportamiento se observa a veces cuando el certificado de calidad se carga después de hacer la liquidación, pero no ocurre de manera consistente. La causa aún no está confirmada.

#### Pasos a seguir

**Ruta:** [Indicar la ruta desde donde se accede a la solución].

[Pendiente de confirmar: pasos reproducibles para corregir el cálculo y determinar si es necesario anular la liquidación o si alcanza con actualizarla.]

### Hallazgos editoriales registrados

- **Requiere ajuste — Título:** se reemplazó “problema granos” por un título descriptivo centrado en la acción y el contexto.
- **Requiere ajuste — Redacción:** se corrigieron ortografía, concordancia y expresiones vagas; la consulta quedó formulada de manera clara y en presente.
- **Bloqueante — Causa no confirmada:** el texto no demuestra que cargar el certificado después de liquidar cause el comportamiento.
- **Bloqueante — Solución no confirmada:** revisar la tabla de calidad y la campaña es una sugerencia del texto original, no una resolución verificada.
- **Bloqueante — Procedimiento incierto:** no está confirmado si hace falta anular la liquidación o si alcanza con actualizarla.
- **Bloqueante — Rutas:** faltan las rutas exactas de reproducción y de solución.
- **Requiere ajuste — Etiquetas:** falta confirmar el catálogo de etiquetas temáticas; se añadió únicamente la etiqueta obligatoria `soluciones`.

**Estado esperado:** Pendiente; no publicar como solución hasta confirmar causa, procedimiento reproducible y rutas. La revisión editorial no determina cuál es el procedimiento técnicamente correcto.

## Caso 4: instructivo con pasos ambiguos y secuencia dudosa

**Tipo:** Instructivo  
**Estado inicial:** texto informal con pasos en orden posiblemente incorrecto, términos abreviados e indicaciones imprecisas.  
**Objetivo de la prueba:** comprobar que el validator mejora el lenguaje sin inventar una secuencia operativa, reconoce una posible referencia a un mensaje de workflow y separa los hallazgos del artículo.

### Entrada de prueba original

**Título:** Instructivo para hacer una factura  
**Categoría:** ERP  
**Tipo de plantilla:** Instructivo

Para cargar una factura de compra, entrá al sistema y buscá proveedores. Primero guardá la factura y después completá el proveedor y la fecha. Si aparece que falta un workflow, volvé para atrás y fijate en configuración, que ahí están las cosas de administración. Las FC se cargan con la cta cte y el IVA que corresponda. Esto es fácil, pero si no funciona hablá con soporte.

### Versión corregida propuesta

**Título:** Cargar una factura de compra  
**Categoría:** ERP  
**Tipo de plantilla:** Instructivo  
**Etiquetas:** instructivo

#### Descripción inicial

Este artículo explica cómo cargar una factura de compra en el sistema.

#### ¿Para qué sirve?

> Registrar una factura correspondiente a una compra.

#### Antes de empezar

[Indicar qué datos o configuraciones se necesitan antes de cargar la factura.]

#### Modo de uso

**Ruta:** [Indicar la ruta de acceso a la carga de facturas de compra].

1. [Indicar cómo iniciar la carga de una factura de compra.]
2. Completar el proveedor y la fecha en el momento que corresponda según el flujo del sistema.
3. [Indicar cómo registrar la cuenta corriente y el IVA aplicable, si estos datos forman parte de este procedimiento.]
4. [Indicar cómo guardar o confirmar la factura.]

### Hallazgos editoriales registrados

- **Bloqueante — Orden por confirmar:** la instrucción original indica guardar la factura antes de completar el proveedor y la fecha. No se reordenó como si se conociera el flujo real; debe confirmarse la secuencia correcta.
- **Bloqueante — Mensaje/workflow:** “falta un workflow” no está confirmado como texto literal del sistema ni se especifica qué workflow falta. La instrucción de volver atrás y buscar en “configuración” es imprecisa y no debe publicarse como solución.
- **Requiere ajuste — Lenguaje:** se reemplazó el tono coloquial por redacción orientada al usuario. “FC” y “cta cte” requieren escribirse completos o explicarse.
- **Requiere ajuste — Contenido:** se eliminó “Esto es fácil” por no aportar información útil.
- **Bloqueante — Ruta y procedimiento:** faltan la ruta real, la secuencia correcta y los pasos para completar y guardar la factura.
- **Requiere ajuste — Etiquetas:** solo está disponible la etiqueta obligatoria `instructivo`; confirmar si hay etiquetas temáticas controladas.

**Estado esperado:** Pendiente. No publicar hasta confirmar la ruta y el procedimiento correcto. Los hallazgos y los marcadores editoriales permanecen fuera del cuerpo publicable.

## Caso 5: solución basada en un caso particular de cliente

**Tipo:** Soluciones  
**Estado inicial:** descripción de un caso particular, con configuración dependiente del cliente y ruta incompleta.  
**Objetivo de la prueba:** comprobar que el validator generaliza el problema sin publicar detalles del caso, evita presentar una alícuota variable como regla universal y deja explícitos los datos que requieren confirmación.

### Entrada de prueba original

**Título:** Solución de retenciones mal  
**Categoría:** ERP  
**Tipo de plantilla:** Soluciones

Un usuario de una empresa tenía problemas con una retención de Ingresos Brutos y pidió ayuda porque le daba distinto. Se revisó el caso y estaba mal configurado. Para corregirlo, hay que abrir retenciones, elegir la provincia y poner la alícuota nueva. Luego se hizo una prueba y ahora da bien. La persona debe hablar con su responsable porque quizás el dato cambia según el cliente. Esta solución sirve para cuando no coincide, aunque habría que ver cada caso.

### Versión corregida propuesta

**Título:** Revisar una retención de Ingresos Brutos cuyo importe no coincide  
**Categoría:** ERP  
**Tipo de plantilla:** Soluciones  
**Etiquetas:** soluciones, retenciones, ingresos-brutos

#### Consulta

Al calcular una retención de Ingresos Brutos, el importe obtenido no coincide con el esperado.

Para solucionarlo, verificar la configuración de retenciones para la provincia correspondiente y confirmar la alícuota aplicable antes de modificarla.

#### Pasos a seguir

**Ruta:** [Indicar la ruta completa para acceder a la configuración de retenciones].

1. Seleccionar la provincia correspondiente.
2. Confirmar la alícuota aplicable con la persona responsable o la fuente vigente.
3. Actualizar la alícuota únicamente si se verificó que el valor configurado es incorrecto.
4. Realizar un cálculo de prueba y verificar el resultado.

### Hallazgos editoriales registrados

- **Requiere ajuste — Título:** se sustituyó el título vago por uno que describe el problema y el concepto involucrado.
- **Bloqueante — Caso particular:** se generalizó la referencia al usuario y a su empresa; no se deben publicar detalles particulares ni notas internas de revisión.
- **Bloqueante — Dato variable:** la alícuota puede depender del cliente y la provincia. No se debe presentar un valor ni un cambio específico como solución universal.
- **Bloqueante — Ruta:** “abrir retenciones” no es una ruta suficiente para guiar a quien lee.
- **Bloqueante — Procedimiento y evidencia:** confirmar la fuente de la alícuota y documentar cómo comprobar que el cálculo queda correcto en casos aplicables.
- **Etiquetas:** se agregó la etiqueta de tipo obligatoria `soluciones`; las etiquetas temáticas propuestas deben validarse contra el catálogo disponible.

**Estado esperado:** Pendiente hasta confirmar la ruta, la fuente del dato variable y que los pasos sean válidos para una necesidad general. No publicar como solución universal mientras el cambio dependa de cada cliente.
