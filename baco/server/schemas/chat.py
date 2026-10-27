from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator

class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(
        default=None,
        description="ID de la sesión del orquestador. Si la sesión está en estado CONFORMIDAD_USUARIO, se inyecta automáticamente su borrador sanitizado."
    )
    prompt: str = Field(
        ...,
        min_length=1,
        description="Instrucción, pregunta o requerimiento editorial del usuario para el agente.",
        examples=["Pasa este borrador al formato de soluciones con verbos en infinitivo."]
    )
    skill: Optional[Literal["plantillas", "validador"]] = Field(
        default=None,
        description="Skill específica de BACO a ejecutar ('plantillas' o 'validador').",
        examples=["plantillas", "validador"]
    )
    tipo_plantilla: Optional[Literal["instructivo", "soluciones"]] = Field(
        default=None,
        description="Plantilla oficial a aplicar ('instructivo' o 'soluciones'). "
                    "Obligatorio al invocar la skill 'plantillas', ya que BACO no infiere "
                    "la plantilla a partir del contexto; solo aplica la indicada.",
        examples=["soluciones", "instructivo"]
    )
    borrador: Optional[str] = Field(
        default=None,
        description="Texto o contenido actual del borrador en el editor para que BACO lo procese con sus skills.",
        examples=["Consulta: El usuario no puede emitir factura. Causa: Falta punto de venta."]
    )
    titulo: Optional[str] = Field(
        default=None,
        description="Título actual del borrador en el editor (utilizado por 'validador' para auditar su calidad o por 'plantillas' como referencia).",
        examples=["Emitir factura electrónica en módulo de ventas"]
    )
    categoria: Optional[str] = Field(
        default=None,
        description="Categoría o módulo ERP asociado al artículo (ej. 'Ventas', 'Contabilidad'), útil para auditar coherencia conceptual en 'validador'.",
        examples=["Ventas"]
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Lista de etiquetas o tags del artículo, utilizada por 'validador' para auditar coherencia técnica.",
        examples=[["facturacion", "soluciones"]]
    )

    @model_validator(mode="after")
    def validar_tipo_plantilla_no_inferida(self):
        if self.session_id:
            from baco.server.services.orquestador import obtener_borrador_conforme
            borrador_conforme = obtener_borrador_conforme(self.session_id)
            if borrador_conforme is not None:
                if not self.borrador:
                    self.borrador = borrador_conforme.texto_limpio
                if not self.titulo:
                    self.titulo = borrador_conforme.titulo
                if not self.tags:
                    self.tags = borrador_conforme.tags
                if not self.tipo_plantilla and borrador_conforme.tipo_plantilla:
                    self.tipo_plantilla = borrador_conforme.tipo_plantilla
                if not self.categoria and borrador_conforme.categoria_id:
                    self.categoria = str(borrador_conforme.categoria_id)

        if not self.session_id and self.skill == "plantillas" and not self.tipo_plantilla:
            raise ValueError(
                "Para la skill 'plantillas' es obligatorio especificar 'tipo_plantilla' ('instructivo' o 'soluciones'). "
                "BACO no infiere la plantilla a partir del contexto; solo sabe aplicar la indicada."
            )
        return self

    def construir_prompt_sanitizado(self) -> str:
        from baco.server.services.validar_articulo import sanitizar_borrador

        prompt_limpio = sanitizar_borrador(texto=self.prompt)["texto_sanitizado"]

        if not any([self.skill, self.tipo_plantilla, self.borrador, self.titulo, self.categoria, self.tags]):
            return prompt_limpio

        datos_borrador = sanitizar_borrador(
            texto=self.borrador or "",
            titulo=self.titulo or ""
        )
        titulo_limpio = datos_borrador["titulo_sanitizado"] if self.titulo else None
        borrador_limpio = datos_borrador["texto_sanitizado"] if self.borrador else None

        partes = []
        if self.skill:
            partes.append(f"Skill solicitada: {self.skill}")
        if self.tipo_plantilla:
            partes.append(f"Plantilla a aplicar: {self.tipo_plantilla}")
        if self.skill != "plantillas":
            if self.categoria:
                partes.append(f"Categoría / Módulo ERP: {self.categoria}")
            if self.tags:
                partes.append(f"Tags: {', '.join(self.tags)}")
        if titulo_limpio:
            partes.append(f"Título del borrador: {titulo_limpio}")
        if borrador_limpio:
            partes.append(f"Borrador actual del artículo:\n\"\"\"\n{borrador_limpio}\n\"\"\"")
        partes.append(f"Instrucción: {prompt_limpio}")
        return "\n\n".join(partes)


    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "skill": "plantillas",
                    "tipo_plantilla": "soluciones",
                    "prompt": "Adaptá este texto a la estructura oficial de Soluciones con verbos en infinitivo.",
                    "titulo": "Fallo al autorizar comprobante electrónico",
                    "borrador": "Consulta: el usuario no puede autorizar. Respuesta: falta el certificado digital.",
                    "categoria": "Ventas"
                },
                {
                    "skill": "validador",
                    "prompt": "Auditá la calidad semántica, estilo y privacidad de este artículo antes de publicar.",
                    "titulo": "Pasos para solucionar el error de facturacion en Molinos Rio Verde",
                    "borrador": "## Consulta\nEl cliente Molinos Rio Verde nos informa que...",
                    "categoria": "Ventas",
                    "tags": ["facturacion", "soluciones"]
                },
                {
                    "prompt": "¿Cuáles son las secciones obligatorias de un artículo de tipo Soluciones?"
                }
            ]
        }
    )


class ChatResponse(BaseModel):
    response: str = Field(
        ...,
        description="Respuesta textual devuelta por el agente (artículo formateado en markdown según la plantilla elegida, dictamen de validación o respuesta conversacional)."
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "response": "## Consulta\nAl intentar emitir una factura electrónica...\n\n## Respuesta\nEl error se produce debido a...\n\n## Pasos a seguir\n1. Ingresar al módulo de Ventas..."
            }
        }
    )
