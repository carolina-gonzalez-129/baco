---
name: validador
description: Audita y perfecciona artículos de la Base de Conocimiento Finnegans mediante análisis semántico avanzado, pautas editoriales, coherencia técnica y publicación segura.
---

# Validador Editorial y Semántico (Auditoría NLP)

Usa esta skill para auditar cualitativamente, corregir o enriquecer el contenido de un artículo destinado a la Base de Conocimiento. 

> **División de Responsabilidades:** La integridad estructural básica (existencia de título, asignación de categoría, cantidad mínima de tags y longitud mínima de caracteres), así como la sanitización determinista previa (detección de CUITs, direcciones de correo, tickets internos explícitos, URLs de prueba privadas y sintaxis inicial de títulos con "Cómo..." o "Error") son garantizadas previamente por el servidor (`validar_articulo.py`). Esta skill interviene en el **análisis semántico profundo, la coherencia de negocio, la detección de entidades no estructuradas y la excelencia editorial**.

---

## Ejes de Auditoría Semántica

### 1. Publicación Segura y Privacidad (Entidades y Datos No Estructurados)
*(Nota: CUITs, correos electrónicos, URLs internas de prueba y códigos de tickets explícitos ya son filtrados por la capa determinista).*
Evaluar el texto para evitar filtración de información confidencial hacia la base pública:
* **Entidades y nombres propios reales:** Identificar nombres de empresas clientes específicas o personas reales que no responden a patrones sintácticos fijos (ej. *"Molinos Río Verde"*, *"Juan Pérez"*), recomendando su reemplazo por datos ficticios y genéricos (ej. *"Empresa Ejemplo S.A."*).
* **Credenciales contextuales:** Detectar contraseñas, tokens no declarados o parámetros de conexión no detectados por filtros estándar.
* **Internismos contextuales:** Señalar referencias internas a incidentes de desarrollo, parches de base de datos o fallas internas que no posean un código de ticket explícito, transformándolos en explicaciones genéricas orientadas al usuario final.

### 2. Calidad Semántica del Título
*(Nota: Las fórmulas iniciales como "Cómo..." o "Pasos para..." y el control sintáctico de la palabra "Error" sin comillas ya son observados por la capa determinista).*
Auditar el valor comunicativo y pertinencia del título:
* **Acción y Contexto:** Verificar que describa con precisión el proceso o pantalla dentro del ERP Finnegans (ej. *"Configurar alícuotas de retención en comprobantes de venta"* en lugar de títulos vagos como *"Retenciones"*).
* **Relevancia en Soluciones:** Constatar que el título refleje con claridad el síntoma o causa concreta que el usuario experimenta en el sistema.
* **Relevancia en Instructivos:** Asegurar que sintetice de forma directa la operación o funcionalidad a aprender.

### 3. Coherencia Conceptual (Categoría y Módulo ERP)
* Contrastar el texto técnico con la categoría asignada.
* Detectar inconsistencias conceptuales (ej. un procedimiento que explica *Liquidación de Sueldos* clasificado erróneamente en *Facturación*).
* **Advertencia de Permisos/AppBuilder:** Identificar si el procedimiento describe configuraciones avanzadas o personalizaciones que requieran permisos especiales de administrador o uso de AppBuilder, recomendando advertirlo al lector si no está explicitado.

### 4. Coherencia Causa-Efecto y Lógica Técnica
* **Resolución Genuina:** Evaluar si los pasos descriptos en la solución efectivamente resuelven el problema o mensaje planteado en la consulta.
* **Secuencia Lógica:** Verificar que los pasos no presenten saltos temporales ni omitan prerequisitos obvios de navegación en el ERP.
* **Ambigüedades:** Si una instrucción es imprecisa (ej. *"Hacer la configuración habitual"*), señalarla con una propuesta concreta de aclaración.

### 5. Tono Editorial y Estilo Finnegans
* Evaluar ortografía, puntuación y estilo acorde a las [pautas de redacción](references/pautas_base_conocimiento.md).
* Tono profesional, conciso, directo y empático.
* Redacción de acciones operativas en infinitivo.

---

## Formato de Salida

Devolver siempre el dictamen de auditoría estructurado:

```text
Estado: Listo | Listo con ajustes sugeridos | Pendiente
Título: [Título evaluado]
Categoría: [Categoría evaluada]
Tipo de plantilla: instructivo | soluciones

Hallazgos Semánticos y Editoriales:
- Severidad: Bloqueante | Requiere ajuste | Sugerencia
  Eje: Privacidad | Título | Coherencia Técnica | Estilo | Categoría
  Descripción: [Diagnóstico semántico claro del hallazgo]
  Acción recomendada: [Propuesta concreta de corrección]

Versión corregida sugerida: [Solo si el usuario solicitó explícitamente reescribir/rewrite o si el estado es 'Listo con ajustes']
```