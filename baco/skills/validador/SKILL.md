---
name: validador
description: Audita y perfecciona artículos de la Base de Conocimiento Finnegans mediante análisis semántico avanzado, pautas editoriales, coherencia técnica y publicación segura.
---

# Validador Editorial y Semántico (Auditoría NLP)

Usa esta skill para auditar cualitativamente, corregir o enriquecer el contenido de un artículo destinado a la Base de Conocimiento. 

> **División de Responsabilidades:** La integridad estructural básica (existencia de título, asignación de categoría, cantidad mínima de tags y longitud mínima de caracteres) es validada determinísticamente por el servidor (`validar_articulo.py`). Esta skill interviene en el **análisis semántico profundo, la coherencia de negocio, la privacidad y la excelencia editorial**.

---

## Ejes de Auditoría Semántica

### 1. Publicación Segura y Privacidad (Detección de Datos Sensibles)
Evaluar el texto para evitar filtración de información confidencial hacia la base pública:
* **Entidades y PII:** Identificar nombres de empresas o clientes reales, CUITs reales, nombres de personas o direcciones de correo corporativas específicas, recomendando su reemplazo por datos ficticios y genéricos (ej. *"Empresa Ejemplo S.A."*).
* **Credenciales y URLs internas:** Detectar contraseñas, tokens de API, cadenas de conexión o URLs de entornos de prueba privados.
* **Menciones a tickets o incidentes:** Señalar referencias internas a tickets de soporte (*"Ticket #12345"* o *"bug interno"*), transformándolos en explicaciones genéricas orientadas al usuario final.

### 2. Calidad Semántica del Título
Más allá de la presencia sintáctica del título, auditar su valor comunicativo:
* **Acción y Contexto:** Verificar que describa con precisión el proceso o pantalla dentro del ERP Finnegans (ej. *"Configurar alícuotas de retención en comprobantes de venta"* en lugar de *"Retenciones"*).
* **Verbos en Infinitivo:** Asegurar que los instructivos comiencen con verbos en infinitivo (*"Generar", "Conciliar", "Emitir"*).
* **Claridad en Errores:** En artículos de solución, constatar que el título refleje el síntoma concreto que el usuario experimenta en el sistema.

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