# Ejemplo de Instructivo: Unidades de Compra

## Texto original (referencia; no publicar)

**Título:** Unidades Compra  
**Categoría:** ERP  
**Tipo de plantilla:** Instructivo

### Unidades de Stock

**Unidad de Stock principal:** identifica la unidad de medida principal en la que se almacena el stock del producto creado. Las equivalencias de unidades de compras y de ventas, se hacen contra esta unidad de medida. Si el producto lleva stock, es obligatoria la asignación de la unidad principal.

**Unidad de Stock secundaria:** representa una segunda unidad de almacenamiento del stock del producto creado. Este campo no es obligatorio, pero si se asigna alguna unidad secundaria, el sistema exige que al momento de operar con este producto se ingresen tantos los valores transaccionados para la unidad principal como para la unidad secundaria. El uso de la unidad secundaria se recomienda sólo en aquellos casos donde se debe llevar un control de stock por más de una variable para un producto dado, en donde no existe una relación fija de equivalencia entre la unidad principal y la unidad secundaria. Un ejemplo de productos de este tipo son las hormas de quesos, en donde normalmente se desea llevar el control de stock en cantidad de hormas y cantidad de kilos, pero donde no existe una relación entre las mismas; por ejemplo, algunas veces una horma puede pesar 5 kilos y otras 4.5 kilos.

**Relación Unidad Secundaria de Stock:** representa la relación que existe entre la unidad secundaria de stock y la unidad primaria de stock. Al agregarle un valor, en cualquier transacción que exija tanto cantidad de unidad primaria como cantidad de unidad secundaria, si se carga un valor en la unidad primaria de stock, el sistema completa automáticamente la cantidad secundaria de unidad de stock basándose en la “Relación Unidad Secundaria de Stock”. Por ejemplo, si se utiliza un producto que tenga como unidad primaria Kilos y como unidad secundaria Toneladas, si la Relación Unidad Secundaria de Stock es de 0,100 ; entonces esto se traduce como 0, 100 Toneladas cada 1 Kilo (o en su defecto, 1000 Kilos cada 1 Tonelada). Este campo no es obligatorio, pero en el caso de asignarle un valor, es necesario que exista una unidad primaria y secundaria de stock.

### Unidades de Compra

**Unidad de Compra:** define la unidad en la que se compra el producto (kilo, quintal, cabezas, unidades, etc.). La misma debe ser ingresada previamente en el maestro de Unidades.

**Relación de unidad de stock con unidad de compra:** cuando la unidad de compra difiere de la unidad de stock, se utiliza este campo para definir la equivalencia de unidades. Es decir cuántas unidades de stock se encuentran contenidas en una unidad de compras. Por ejemplo, si se lleva el stock en litros, pero se compra en bidones de 20 litros, la relación será: Cantidad Unidades de stock Contenidas en Unidad de Compra = 20. En el caso de que las unidades de stock y de compras sean las mismas, se debe indicar valor 1.

## Ejemplo organizado (salida publicable)

**Título:** Unidades de Compra  
**Categoría:** ERP  
**Tipo de plantilla:** Instructivo  
**Etiquetas:** instructivo

### Descripción inicial

Este instructivo describe cómo se relacionan las unidades de stock y de compra configuradas para un producto.

### ¿Para qué sirve?

> Definir cómo se almacena el stock de un producto y cómo se expresa su compra, para mantener las cantidades relacionadas al operar.

### Antes de empezar

- Verificar que las unidades de medida que se van a utilizar estén creadas en el maestro de Unidades.
- Definir si el producto lleva stock.
- Determinar si se necesita controlar el stock con una unidad secundaria.

### Modo de uso

**Ruta:** [Completar con la ruta del sistema donde se configuran las unidades del producto].

#### Unidades de stock

**Unidad de Stock principal:** identificar la unidad de medida principal en la que se almacena el stock del producto. Las equivalencias de las unidades de compra y venta se calculan en relación con esta unidad. Si el producto lleva stock, asignar una unidad principal.

**Unidad de Stock secundaria:** representa una segunda unidad para controlar el stock. Es opcional. Si se asigna, al operar con el producto se deben ingresar las cantidades correspondientes a las unidades principal y secundaria.

Se recomienda utilizarla cuando se necesita controlar el stock con más de una variable y no existe una equivalencia fija entre ellas. Por ejemplo, se puede controlar un producto por cantidad de hormas y por kilos, aunque el peso de cada horma varíe.

**Relación Unidad Secundaria de Stock:** define la relación entre la unidad secundaria y la principal. Es opcional; para asignarle un valor, deben estar configuradas ambas unidades. Cuando se define esta relación, el sistema completa automáticamente la cantidad secundaria a partir de la cantidad ingresada en la unidad principal.

#### Unidades de compra

**Unidad de Compra:** definir la unidad en la que se compra el producto, por ejemplo, kilos, quintales, cabezas o unidades. La unidad debe existir previamente en el maestro de Unidades.

**Relación de unidad de stock con unidad de compra:** si la unidad de compra es distinta de la unidad de stock, indicar cuántas unidades de stock contiene una unidad de compra. Por ejemplo, si el stock se lleva en litros y se compra en bidones de 20 litros, indicar `20`. Si ambas unidades son iguales, indicar `1`.

### Qué hace y qué no hace

#### Sí hace

- Permite definir una unidad principal para almacenar el stock del producto.
- Permite registrar una unidad secundaria y exigir ambas cantidades al operar con el producto.
- Completa la cantidad de la unidad secundaria cuando se configuró una relación entre las unidades de stock.
- Permite establecer la equivalencia entre la unidad de stock y la unidad de compra.

#### No hace

- Cuando se configura una unidad secundaria, no permite operar ingresando únicamente la cantidad de la unidad principal: también se debe ingresar la cantidad secundaria.

## Notas para revisión (no forman parte del artículo)

- La ruta real de acceso a la configuración no se proporcionó y queda como dato pendiente.
- Se omitió el ejemplo de conversión entre kilos y toneladas porque los valores incluidos en la fuente parecen contradictorios. Confirmar la equivalencia antes de agregar un ejemplo numérico.
- La fuente no proporcionó etiquetas temáticas; se muestra únicamente la etiqueta obligatoria `instructivo`.
