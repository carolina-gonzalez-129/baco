# Criterios de desambiguación para la Base de Conocimiento Finnegans

Este documento complementa a la skill `detectar-duplicados` recopilando patrones observados en las publicaciones reales de la Base de Conocimiento de Finnegans (`bc.finneg.com`).

---

## 1. Patrones de "Artículos Gemelos" (Variantes Paramétricas)

En Finnegans, múltiples normativas provinciales o esquemas fiscales comparten el mismo motor de configuración (por ejemplo, el módulo *Deals*, *AppBuilder* o *Padrón de IIBB*). 

### Casos de estudio reales:
* **Entrada A:** `Configuración del Padrón IIBB ARBA mediante el módulo Deals`
* **Entrada B:** `Configuración del Padrón IIBB CABA mediante el módulo Deals`
* **Entrada C:** `Configuración del Padrón IIBB Salta Riesgo Fiscal mediante el módulo Deals`

**Similitud superficial:** Superior al 90% en métricas de Levenshtein o Fuzzy.
**Veredicto:** **Variante paramétrica (NO DUPLICADO)**.
**Razón técnica:** Cada jurisdicción fiscal exige archivos de importación con estructuras de columnas distintas, diferentes códigos de alícuotas y validaciones independientes. Fusionarlos generaría errores de liquidación fiscal en las empresas cliente.

---

## 2. Patrones de Flujos Opuestos o Espejados

El sistema Finnegans opera con circuitos simétricos de compra y venta o de emisión y liquidación.

### Casos de estudio reales:
* **Entrada A:** `Liquidación primaria de compra de granos - error COE - unidad de medida`
* **Entrada B:** `Liquidación Secundaria de Venta de Granos: Solución de Errores Comunes`
* **Entrada C:** `Pago de Facturas de Compra con Facturas de Venta`

**Similitud superficial:** Moderada-alta (comparten términos clave: *Liquidación*, *Granos*, *Facturas*).
**Veredicto:** **Flujo complementario / Opuesto (NO DUPLICADO)**.
**Razón técnica:** La dirección del comprobante (débito/crédito, compras/ventas, primaria/secundaria) define tablas contables y circuitos de autorización totalmente distintos.

---

## 3. Patrones de Duplicados Reales y Canibalización

Suelen originarse cuando distintos analistas o finnencers publican sobre el mismo problema sin revisar el histórico, o cuando se actualiza el sistema.

### Casos de estudio reales:
* **Caso 1:** `Importación de Facturas con IA en Bot de Compras` vs. `Importación de Factura con IA en Bot de compras`
  * **Causa:** Singular vs. plural y cambio menor de mayúsculas.
  * **Veredicto:** **Duplicado real**.
* **Caso 2:** `JasperReports en Windows y Linux – Instalación y Configuración` (publicado dos veces con distinto ID).
  * **Veredicto:** **Duplicado idéntico**.
* **Caso 3:** `Portal Agro - Gestión de Invitados` vs. `App Portal Agro - Gestión de Invitados`.
  * **Causa:** Denominación redundante de la misma aplicación web.
  * **Veredicto:** **Duplicado funcional**.

---

## 4. Matriz de Decisión para el Arbitraje Humano

| Tipo detectado | ¿Comparten objetivo final? | ¿Se pueden unificar sin error? | Acción recomendada al usuario |
| :--- | :---: | :---: | :--- |
| **Duplicado real** | Sí | Sí | **Fusionar:** Mantener el más visitado o actualizado y archivar/redireccionar el otro. |
| **Variante paramétrica** | No (distinto ámbito) | No (provocaría error) | **Mantener ambos:** Verificar que el título distinga explícitamente la jurisdicción o país. |
| **Flujo complementario** | No (distinto rol/paso) | No | **Relacionar:** Mantener ambos e insertar hipervínculos cruzados (*"Ver también..."*). |
| **Subtema jerárquico** | Parcialmente | Depende de la extensión | Si es breve (1 párrafo), integrar en la entrada padre; si es extenso, mantener como sub-artículo. |
