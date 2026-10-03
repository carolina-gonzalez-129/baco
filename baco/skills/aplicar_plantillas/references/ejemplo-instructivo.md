# Ejemplo de Instructivo: Bot de Granos

**Título:** Números de documento en liquidaciones del Bot de Granos  
**Categoría:** Agro  
**Tipo de plantilla:** instructivo  
**Etiquetas:** instructivo, agro, liquidación de granos, traslado de granos, Bot de Granos

Este instructivo describe los datos que el Bot de Granos muestra en el selector de contratos y en la grilla de traslados al procesar liquidaciones primarias y secundarias de granos.

## ¿Para qué sirve?

Al procesar una liquidación en el Bot de Granos:

- El selector de contratos muestra el número de documento del contrato junto al número interno.
- El selector filtra automáticamente los contratos por el grano de la liquidación en curso.
- En la grilla de traslados vinculados al contrato se muestra el CTG de cada carta de porte.
- En la columna **Certificado** se muestra el número interno del certificado junto con su COE (número de comprobante del certificado de depósito).

Esto permite identificar y confirmar los documentos correctos sin abrir otras pantallas del ERP.

## Antes de empezar

- Contar con al menos un contrato de compra o venta de granos cargado en el ERP con su número de documento completo.
- Verificar que el contrato tenga cantidad disponible para fijar o liquidar.

## Modo de uso

**Ruta:** Bot de Granos → Liquidaciones de granos → abrir una liquidación.

### Selector de contratos

Al seleccionar el contrato dentro de una liquidación, cada opción se muestra con este formato:

`[Número interno del contrato] / [Número de documento del contrato]`

**Ejemplo:** `CONT-VTA-GRA 19 / 110032402`

El selector no muestra el nombre del grano en la descripción. En su lugar, filtra automáticamente los contratos disponibles y muestra únicamente los que tienen el mismo producto (grano) que la liquidación en curso y poseen cantidad disponible para fijar o liquidar.

### Grilla de traslados vinculados

Una vez seleccionado el contrato, la grilla que lista los traslados (cartas de porte) asociados incluye estas columnas:

- **CTG:** Código de Trazabilidad de Granos correspondiente a cada traslado.
- **Certificado:** número interno del certificado de depósito seguido del COE del certificado, dato proveniente de la solapa **Información Fiscal** del certificado. Formato: `[Número interno] / [COE]`.

Si el traslado no tiene certificado asignado, la columna **Certificado** queda vacía y no muestra el separador `/`.

El comportamiento es idéntico en liquidaciones primarias y secundarias.

## Qué hace y qué no hace

### Sí hace

- Muestra el número de documento del contrato en el selector para facilitar su identificación sin salir del bot.
- Filtra automáticamente los contratos del selector por el grano de la liquidación en curso.
- Muestra el CTG de cada traslado en la grilla de vinculación.
- Muestra el número interno del certificado junto a su COE en la columna **Certificado**.

### No hace

- No permite editar los traslados desde la grilla de vinculación.
- No muestra el separador `/` ni el COE en traslados que todavía no tienen un certificado asignado.
