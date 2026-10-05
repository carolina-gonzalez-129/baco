# Casos de prueba para la skill detectar-duplicados

Estos casos de prueba validan que la skill clasifique correctamente los casos ambiguos sin caer en los sesgos de similitud puramente léxica.

---

## Caso 1: Variante Paramétrica (IIBB ARBA vs CABA)

### Entrada:
* **Candidata:**
  * Título: `Configuración del Padrón IIBB ARBA mediante el módulo Deals`
  * Categoría: `Impuestos`
  * Descripción: `Instructivo para importar y configurar las alícuotas del padrón de Ingresos Brutos de Buenos Aires (ARBA) usando Deals.`
* **Referencia en conflicto:**
  * Título: `Configuración del Padrón IIBB CABA mediante el módulo Deals` (ID 6102)
  * Categoría: `Impuestos`
  * Descripción: `Pasos para la configuración y carga de alícuotas del padrón de CABA a través de Deals.`

### Salida esperada:
* **Dictamen:** `Variante paramétrica`
* **Confianza:** `Alta`
* **Análisis:** Aunque la estructura y herramienta (módulo Deals) son idénticas, las jurisdicciones fiscales (ARBA - Provincia de Buenos Aires vs. CABA - Ciudad de Buenos Aires) corresponden a regímenes impositivos independientes con formatos de padrón y normativas dispares.
* **Riesgo:** Unificar o sobrescribir causaría que usuarios de Buenos Aires carguen alícuotas o estructuras no válidas para CABA.
* **Opciones:** Mantener separadas ambas entradas asegurando que la provincia esté claramente identificada en el título.

---

## Caso 2: Duplicado Real por Redacción Alternativa

### Entrada:
* **Candidata:**
  * Título: `Importación de Factura con IA en Bot de compras`
  * Categoría: `Compras`
  * Descripción: `Guía para utilizar la inteligencia artificial del bot de compras al procesar facturas recibidas.`
* **Referencia en conflicto:**
  * Título: `Importación de Facturas con IA en Bot de Compras` (ID 7480)
  * Categoría: `Compras`
  * Descripción: `Instructivo paso a paso para importar comprobantes de proveedores con reconocimiento inteligente en el bot de compras.`

### Salida esperada:
* **Dictamen:** `Duplicado real`
* **Confianza:** `Alta`
* **Análisis:** La intención operativa es indistinguible. Las diferencias son cosméticas (singular vs plural en "Factura(s)" y mayúsculas en "compras").
* **Riesgo:** Dispersión de visitas, canibalización del motor de búsqueda y posible divergencia de documentación si una queda desactualizada.
* **Opciones:** Fusionar conservando la versión con más visitas o mejor redactada, y desestimar la publicación de la entrada candidata.

---

## Caso 3: Flujo Opuesto / Complementario

### Entrada:
* **Candidata:**
  * Título: `Liquidación Secundaria de Venta de Granos: Solución de Errores Comunes`
  * Categoría: `Agro`
  * Descripción: `Explicación de mensajes de error al emitir la liquidación secundaria en ventas de cereales.`
* **Referencia en conflicto:**
  * Título: `Liquidación primaria de compra de granos - error COE - unidad de medida` (ID 6890)
  * Categoría: `Agro`
  * Descripción: `Solución al error de unidad de medida y rechazo de COE en liquidaciones primarias de compra.`

### Salida esperada:
* **Dictamen:** `Flujo complementario`
* **Confianza:** `Alta`
* **Análisis:** Comparten términos del dominio agrícola (*liquidación, granos, errores*), pero una pertenece al circuito de Compras (primaria) y la otra al circuito de Ventas (secundaria).
* **Riesgo:** Si se tratan como duplicados, un usuario que necesita solucionar un rechazo en ventas aplicará validaciones que solo existen en compras.
* **Opciones:** Mantener ambas entradas y sugerir enlaces cruzados si ambas pertenecen a la serie de resolución de errores de granos.
