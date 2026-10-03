---
name: detectar_duplicados
description: Arbitra casos ambiguos de duplicación entre artículos de la Base de Conocimiento Finnegans mediante análisis semántico profundo y conocimiento del dominio ERP.
---

# Arbitraje Semántico de Duplicados (Análisis NLP de Dominio)

Usa esta skill cuando la capa de servicios determinista (búsqueda léxica, similitud de títulos o proximidad vectorial) detecte artículos con similitud moderada/alta que caigan en una **zona de ambigüedad**, requiriendo comprensión contextual del ERP para definir si deben coexistir, unificarse o vincularse.

> **Principio de Gobernanza y Control Humano (HITL):** El usuario siempre toma la decisión final. Esta skill no realiza acciones destructivas ni fusiona artículos por su cuenta: entrega un diagnóstico semántico riguroso, identifica divergencias críticas de negocio y formula alternativas concretas de acción para el editor.

---

## Marco de Análisis Semántico (Dominio ERP Finnegans)

El agente no debe guiarse por la simple presencia de términos comunes del sistema (*"comprobante"*, *"configuración"*, *"granos"*, *"factura"*), sino por la **intención operativa y el impacto en el negocio**. Debe clasificar el caso en una de las siguientes tipologías:

### 1. Duplicado Real (Redundancia o canibalización)
* **Criterio:** Ambos artículos persiguen exactamente el mismo objetivo operativo (*Job-To-Be-Done*) y resuelven el mismo problema o procedimiento con distinto fraseo.
* **Patrones frecuentes:**
  * Plural vs. singular (*"Importación de Facturas"* vs. *"Importación de Factura"*).
  * Variación de canal sin divergencia de procedimiento (*"Portal Agro"* vs. *"App Portal Agro"* cuando la función es idéntica).
  * Redacciones alternativas del mismo mensaje de error por autores distintos.
* **Impacto:** Canibaliza el buscador de Discourse y confunde al usuario.
* **Recomendación base:** Unificar / Conservar una única versión actualizada.

### 2. Variante Paramétrica (Falso duplicado / "Artículos gemelos")
* **Criterio:** Procedimientos cuyas pantallas, botones y secuencia son casi idénticos, pero divergen en un parámetro normativo, impositivo o geográfico excluyente.
* **Patrones frecuentes:**
  * **Jurisdicciones fiscales:** Padrones de Ingresos Brutos (*ARBA* vs. *AGIP/CABA* vs. *Formosa* vs. *Salta*).
  * **Localizaciones / Países:** Tratamiento de comprobantes para *Argentina* vs. *Uruguay* vs. *Paraguay*.
  * **Entes reguladores:** Normativas de *ARCA* vs. *SENASA*.
* **Impacto:** Si se trataran como duplicados, el cliente aplicaría una configuración fiscal errónea con riesgo impositivo directo.
* **Recomendación base:** **Mantener separados**. Asegurar que ambos títulos expliciten claramente el parámetro discriminante.

### 3. Flujo Complementario u Opuesto (Mismo dominio, distinta acción)
* **Criterio:** Artículos que comparten la misma entidad de negocio pero representan direcciones opuestas del circuito operativo o etapas cronológicas distintas.
* **Patrones frecuentes:**
  * Compras vs. Ventas (*"Factura de Compra"* vs. *"Factura de Venta"*).
  * Emisión vs. Cobro / Pago.
  * Primaria vs. Secundaria (*"Liquidación Primaria de Granos"* vs. *"Liquidación Secundaria"*).
  * Configuración de maestro vs. Operación transaccional (*"Maestro de Productos"* vs. *"Ajustes de Stock"*).
* **Impacto:** Responden a perfiles de usuarios y momentos operativos completamente distintos.
* **Recomendación base:** **Mantener separados**. Incluir referencias cruzadas o enlaces sugeridos.

### 4. Relación Jerárquica (General vs. Específico)
* **Criterio:** Un artículo describe el marco general de un módulo, mientras que el otro resuelve un caso de borde, una solapa específica o un error particular dentro de dicho flujo.
* **Ejemplo observado:** *"Portal de Impuestos - Carga de Comprobantes"* (general) vs. *"Portal de Impuestos - IVA - Carga de Comprobantes"* (específico).
* **Recomendación base:** Mantener separados si el subtema es extenso; sugerir incorporación como sección si es un apunte breve.

---

## Procedimiento de Arbitraje

1. **Aislamiento del Objetivo del Lector:** Identificar qué necesidad o problema técnico concreto resuelve cada texto.
2. **Búsqueda de Divergencias Críticas:** Detectar parámetros de exclusión mutua (provincias, circuitos contables, localizaciones).
3. **Evaluación de Riesgo Operativo:** Preguntarse: *¿Si un usuario aplica las instrucciones del artículo A para resolver el problema B, comete un error en el sistema o una infracción normativa?*
   * Si la respuesta es **Sí** → Prohibido clasificar como duplicado (es Variante Paramétrica o Flujo Opuesto).
   * Si la respuesta es **No y el resultado es intercambiable** → Clasificar como Duplicado Real.
4. **Formulación de Opciones Accionables:** Ofrecer alternativas claras y priorizadas para que el editor humano decida.

---

## Formato de Salida

Devolver siempre el dictamen estructurado:

```text
Dictamen: Duplicado real | Variante paramétrica | Flujo complementario | Relación jerárquica | Independiente
Confianza: Alta | Media | Baja
Artículo en revisión: [Título del artículo evaluado]
Artículo de referencia: [Título e ID / URL del artículo existente]

Análisis de Divergencia Semántica:
[Explicación concisa en 2 o 3 oraciones de la coincidencia y la diferencia fundamental de negocio o normativa entre ambos].

Riesgo Operativo:
[Consecuencia técnica o de gestión para el usuario si estos artículos se confunden o unifican indebidamente].

Opciones para el Usuario:
- Opción 1 (Recomendada): [Acción principal sugerida: Mantener separados / Unificar / Referenciar].
- Opción 2: [Alternativa secundaria: ej. Ajustar el título para explicitar provincia o circuito].
- Opción 3: [Acción de descarte o archivo si aplica].
```
