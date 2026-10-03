---
name: detectar_duplicados
description: Arbitra casos ambiguos de duplicación entre entradas de la Base de Conocimiento Finnegans mediante análisis semántico profundo, distinguiendo duplicados reales de variantes paramétricas, flujos opuestos o subtemas para asistir la decisión final del usuario.
---

# Detección y arbitraje de duplicados ambiguos

Usa esta skill cuando la capa de servicios o el usuario identifiquen una entrada candidata con similitud semántica o léxica moderada/alta respecto a una o más entradas existentes en la Base de Conocimiento, y se requiera un dictamen cualitativo sobre su coexistencia.

> **Principio de gobernanza:** El usuario humano tiene siempre el control final. Esta skill no fusiona ni descarta contenido de forma autónoma: proporciona un diagnóstico semántico riguroso, identifica divergencias críticas de negocio y formula opciones de acción claras y accionables para el editor.

---

## Datos obligatorios de entrada

La solicitud debe proporcionar los pares o grupos a comparar:

1. **Entrada en revisión (Candidata):** Título, Categoría, Tipo de plantilla (`instructivo` o `soluciones`) y Contenido o Descripción.
2. **Entrada(s) existente(s) de referencia:** Título, Categoría, Identificador (ID o URL) y Contenido o Resumen.

Si falta el texto o descripción de alguna de las partes, la skill debe evaluar exclusivamente los títulos y metadatos disponibles, explicitando en el dictamen que el análisis se basó en alcance nominal.

---

## Marco de análisis semántico (Lecciones del dominio Finnegans)

El agente no debe guiarse por la mera coincidencia de términos de ERP (*"proceso"*, *"configuración"*, *"granos"*, *"factura"*), sino por la **intención operativa y el impacto en el negocio**. Debe clasificar el caso en una de las siguientes tipologías:

### 1. Duplicado real (Redundancia o canibalización)
* **Criterio:** Ambos artículos persiguen exactamente el mismo objetivo operativo (*Job-To-Be-Done*) y responden a la misma consulta o procedimiento.
* **Variaciones típicas observadas:**
  * Plural vs. singular (*"Importación de Facturas..."* vs. *"Importación de Factura..."*).
  * Variación de canal sin divergencia de procedimiento (*"Portal Agro"* vs. *"App Portal Agro"* cuando la funcionalidad explicada es equivalente).
  * Redacciones alternativas del mismo error por autores distintos (*"No se puede consultar la CPE"* vs. *"Error al validar CPE con certificado"*).
* **Impacto:** Canibaliza el buscador de Discourse y confunde a los usuarios.
* **Recomendación base:** Unificar / Conservar una única versión actualizada.

### 2. Variante paramétrica (Falso duplicado / "Artículos gemelos")
* **Criterio:** Procedimientos cuya estructura técnica, pantallas y botones son 90% idénticos, pero divergen en un parámetro normativo, geográfico o fiscal crítico.
* **Patrones frecuentes:**
  * **Jurisdicciones fiscales:** *ARBA* vs. *CABA* vs. *Formosa* vs. *Salta* en Padrones de IIBB.
  * **Países / Localizaciones:** *Uruguay* vs. *Argentina* vs. *Paraguay* (ej. CAE / CDC).
  * **Entes reguladores:** *ARCA* vs. *SENASA*.
* **Impacto:** Si se trataran como duplicados, el cliente aplicaría una configuración impositiva errónea.
* **Recomendación base:** Mantener separados. Asegurar que el título incluya explícitamente el parámetro discriminante.

### 3. Flujo complementario u opuesto (Mismo dominio, distinta acción)
* **Criterio:** Entradas que comparten la misma entidad de negocio pero representan direcciones opuestas del circuito comercial/contable o distintas etapas cronológicas.
* **Patrones frecuentes:**
  * Compra vs. Venta (*"Factura de Compra"* vs. *"Factura de Venta"*).
  * Emisión vs. Liquidación vs. Cobro/Pago.
  * Primaria vs. Secundaria (*"Liquidación Primaria de Granos"* vs. *"Liquidación Secundaria"*).
  * Alta de maestro vs. Operación transaccional (*"Maestro de Productos"* vs. *"Movimientos de Stock"*).
* **Impacto:** Satisfacen necesidades completamente distintas en momentos diferentes del circuito.
* **Recomendación base:** Mantener separados. Vincular mediante referencias cruzadas si forman parte de la misma cadena de trabajo.

### 4. Relación jerárquica (General vs. Específico)
* **Criterio:** Una entrada describe el marco global de un módulo o pantalla, mientras que la otra aborda un caso de borde, una solapa específica o un código de error particular dentro de dicho flujo.
* **Ejemplo observado:** *"Portal de Impuestos - Carga de Comprobantes"* (general) vs. *"Portal de Impuestos - IVA - Carga de Comprobantes"* (específico).
* **Recomendación base:** Mantener separados si el subtema es extenso; evaluar fusión si el subtema es una nota de un solo párrafo.

---

## Procedimiento de arbitraje

1. **Aislamiento del objetivo de usuario:** Definir qué problema puntual busca resolver el lector en cada texto.
2. **Identificación de la divergencia crítica:** Comprobar si existe un parámetro de exclusión mutua (provincia, circuito de compra/venta, entidad).
3. **Evaluación de riesgo operativo:** Preguntarse: *¿Si un usuario sigue el artículo A para resolver el problema B, genera un error en el sistema o una falla fiscal?*
   * Si la respuesta es **Sí** → Prohibido clasificar como duplicado.
   * Si la respuesta es **No y el resultado es idéntico** → Clasificar como duplicado.
4. **Formulación de alternativas para el usuario:** Brindar opciones concretas (fusionar, mantener con ajuste de título, o relacionar).

---

## Formato de salida

La respuesta debe ser clara, concisa y estructurada exactamente con el siguiente formato para permitir que el usuario tome el control de la acción final:

```text
Dictamen: Duplicado real | Variante paramétrica | Flujo complementario | Subtema jerárquico | Independiente
Confianza: Alta | Media | Baja
Entrada candidata: [Título de la entrada evaluada]
Entrada en conflicto: [Título e ID de la entrada existente]

Análisis de divergencia:
[Explicación concisa en 2 o 3 oraciones de la coincidencia y la diferencia fundamental de negocio o normativa entre ambas].

Riesgo operativo:
[Consecuencia en el sistema o en la gestión del usuario si estos artículos se confunden o unifican].

Opciones para el usuario:
- Opción 1 (Recomendada): [Acción principal sugerida: Fusionar / Mantener ambas / Crear referencia cruzada].
- Opción 2: [Alternativa secundaria: ej. Ajustar el título de la candidata para explicitar la provincia o módulo].
- Opción 3: [Alternativa de descarte o archivo si aplica].
```
