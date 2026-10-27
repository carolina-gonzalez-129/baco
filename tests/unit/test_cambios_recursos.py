import pytest
from baco.server.schemas.chat_orquestado import BorradorSesion
from baco.server.schemas.recurso import Recurso
from baco.server.services.orquestador.recursos_service import (
    extraer_recursos_y_texto_limpio,
    eliminar_recurso_borrador,
    sincronizar_orden_recursos_desde_texto,
)


def test_articulo_con_capturas_paso_a_paso_reemplaza_por_marcadores_en_posicion_exacta():
    """Cambio 1: extraer_recursos_y_texto_limpio reemplaza cada etiqueta multimedia
    por [[recurso:<id>]] con id estable y orden según posición en el texto.
    """
    texto_entrada = (
        "### Paso 1: Apertura del período contable\n"
        "Ingresar al menú de contabilidad y seleccionar el ejercicio.\n\n"
        "![Captura del menú principal](https://bc.finneg.com/uploads/menu_contable.png)\n\n"
        "### Paso 2: Validación de asientos pendientes\n"
        "Revisar que no existan asientos en estado borrador.\n\n"
        "![Pantalla de asientos](https://bc.finneg.com/uploads/asientos_pendientes.png)\n\n"
        "### Paso 3: Video demostrativo del cierre\n"
        "Seguir las instrucciones del video a continuación:\n\n"
        "https://www.youtube.com/watch?v=cierre2026\n\n"
        "### Paso 4: Descarga del comprobante\n"
        "[comprobante_cierre.pdf|attachment](https://bc.finneg.com/uploads/comprobante.pdf)"
    )

    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_entrada)

    # 1. Verificar que texto_limpio queda sin marcadores [[recurso:...]]
    assert "[[recurso:" not in texto_limpio

    # 2. Las URLs originales no están en texto_limpio
    assert "https://bc.finneg.com/uploads/menu_contable.png" not in texto_limpio
    assert "https://bc.finneg.com/uploads/asientos_pendientes.png" not in texto_limpio
    assert "https://www.youtube.com/watch?v=cierre2026" not in texto_limpio

    # 3. Cada recurso tiene la posicion del bloque de texto tras el cual va
    bloques = [b.strip() for b in texto_limpio.split("\n\n") if b.strip()]
    idx_p1 = next(i for i, b in enumerate(bloques) if "Paso 1" in b)
    assert recursos["rec_1"].posicion == idx_p1

    idx_p2 = next(i for i, b in enumerate(bloques) if "Paso 2" in b)
    assert recursos["rec_2"].posicion == idx_p2

    # 4. Los recursos tienen IDs estables y orden según aparición
    assert len(recursos) == 4
    assert recursos["rec_1"].orden == 0
    assert recursos["rec_2"].orden == 1
    assert recursos["rec_3"].orden == 2
    assert recursos["rec_4"].orden == 3


def test_eliminar_recurso_sin_renumerar_ids():
    """Al eliminar un recurso, los IDs de los restantes permanecen estables (no se renumeran)."""
    texto = (
        "Paso 1:\n\n"
        "![img1](https://bc.finneg.com/img1.png)\n\n"
        "Paso 2:\n\n"
        "![img2](https://bc.finneg.com/img2.png)\n\n"
        "Paso 3:\n\n"
        "![img3](https://bc.finneg.com/img3.png)"
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto)
    assert set(recursos.keys()) == {"rec_1", "rec_2", "rec_3"}

    # Eliminar rec_2
    nuevos_recursos, eliminado = eliminar_recurso_borrador(recursos, "rec_2")
    assert eliminado is True

    # Los IDs restantes deben ser exactamente rec_1 y rec_3 (NO se renombra rec_3 a rec_2)
    assert set(nuevos_recursos.keys()) == {"rec_1", "rec_3"}
    assert "rec_2" not in nuevos_recursos
    assert nuevos_recursos["rec_1"].id == "rec_1"
    assert nuevos_recursos["rec_3"].id == "rec_3"


def test_reordenar_sin_renumerar_ids_y_orden_dado_por_posicion_en_texto():
    """El orden de los recursos lo da su posición en el texto, conservando sus IDs estables."""
    texto = (
        "![img1](https://bc.finneg.com/img1.png)\n\n"
        "![img2](https://bc.finneg.com/img2.png)\n\n"
        "![img3](https://bc.finneg.com/img3.png)"
    )
    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto)
    assert [r.id for r in sorted(recursos.values(), key=lambda x: x.orden)] == ["rec_1", "rec_2", "rec_3"]

    # Reordenamos el texto moviendo rec_3 al inicio y rec_1 al final
    texto_reordenado = "Inicio con [[recurso:rec_3]] luego [[recurso:rec_2]] y finalmente [[recurso:rec_1]]"
    recursos_ordenados = sincronizar_orden_recursos_desde_texto(texto_reordenado, recursos)

    # Los IDs NO cambian: siguen siendo rec_3, rec_2, rec_1
    assert [r.id for r in recursos_ordenados] == ["rec_3", "rec_2", "rec_1"]
    assert recursos["rec_3"].id == "rec_3"
    assert recursos["rec_3"].orden == 0
    assert recursos["rec_2"].orden == 1
    assert recursos["rec_1"].orden == 2

def test_marcador_escrito_a_mano_por_persona_es_rechazado_sin_borrado_silencioso():
    """Cambio 3: rechaza marcadores escritos a mano por la persona sin borrado silencioso."""
    from pydantic import ValidationError

    # 1. En BorradorSesion: si texto_limpio contiene un marcador no registrado en recursos, falla con ValidationError
    with pytest.raises(ValidationError) as exc_info:
        BorradorSesion(
            modo="nuevo",
            titulo="Instructivo con marcador manual",
            texto_limpio="Paso 1: Abrir ventana.\n\n[[recurso:rec_manual_persona]]\n\nPaso 2: Guardar.",
            recursos={},
        )
    err_str = str(exc_info.value)
    assert "[[recurso:rec_manual_persona]]" in err_str
    assert "no puede ser escrito manualmente" in err_str or "no referencian ningún recurso" in err_str

    # 2. Si hay recursos pero el marcador inventado no existe entre ellos, también es rechazado
    rec_existente = Recurso(id="rec_1", tipo="imagen", nombre="img1.png", orden=0)
    with pytest.raises(ValidationError) as exc_info2:
        BorradorSesion(
            modo="nuevo",
            titulo="Instructivo con recurso válido y otro inventado",
            texto_limpio="[[recurso:rec_1]] y luego [[recurso:rec_fantasma]]",
            recursos={"rec_1": rec_existente},
        )
    err_str2 = str(exc_info2.value)
    assert "[[recurso:rec_fantasma]]" in err_str2


def test_marcador_valido_referenciando_recurso_existente_es_preservado():
    """Cambio 3: cada marcador válido que referencia un recurso existente se convierte en posicion de bloque sin quedar en texto_limpio."""
    r1 = Recurso(id="rec_1", tipo="imagen", nombre="captura.png", referencia="https://bc.finneg.com/c.png", orden=0)
    r2 = Recurso(id="rec_2", tipo="video", nombre="tutorial.mp4", referencia="https://youtube.com/v", orden=1)
    recursos = {"rec_1": r1, "rec_2": r2}

    texto = "Paso 1: Ver captura [[recurso:rec_1]]\n\nPaso 2: Ver video explicativo [[recurso:rec_2]]"
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía con recursos existentes",
        texto_limpio=texto,
        recursos=recursos,
    )

    assert "[[recurso:" not in borrador.texto_limpio
    assert borrador.recursos["rec_1"].posicion == 0
    assert borrador.recursos["rec_2"].posicion == 1
    assert "https://bc.finneg.com/c.png" in borrador.texto_alineado_discourse
    assert "https://youtube.com/v" in borrador.texto_alineado_discourse


def test_borrador_texto_siempre_coincide_con_composicion_de_texto_limpio_y_recursos():
    """Riesgo 4: borrador.texto_alineado_discourse coincide siempre con componer_texto_publicable y es de solo lectura."""
    from baco.server.services.orquestador.recursos_service import componer_texto_publicable

    r1 = Recurso(id="rec_1", tipo="imagen", nombre="captura.png", referencia="https://bc.finneg.com/c.png", orden=0)
    texto = "Configuración del sistema:\n\n[[recurso:rec_1]]\n\nFin del proceso."
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Instructivo",
        texto_limpio=texto,
        recursos={"rec_1": r1},
    )

    # Coincide exactamente con componer_texto_publicable
    assert borrador.texto_alineado_discourse == componer_texto_publicable(borrador.bloques_texto, borrador.recursos)
    assert not hasattr(borrador, "texto")

    # Es propiedad derivada: no se puede reasignar directamente
    with pytest.raises(AttributeError):
        borrador.texto = "Intento de sobreescritura directa"
    with pytest.raises(AttributeError):
        borrador.texto_alineado_discourse = "Intento de sobreescritura directa"

def test_skill_plantillas_rechaza_borrador_con_recursos_o_marcadores():
    """La aplicación de skills y los recursos son mutuamente excluyentes: corta con HTTPException 400 y no llama al modelo."""
    from unittest.mock import MagicMock
    from fastapi import HTTPException
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    texto_original = "Paso 1: Configurar cuenta.\n\nPaso 2: Verificar saldos."
    r1 = Recurso(id="rec_1", tipo="imagen", nombre="img.png", referencia="https://bc.finneg.com/1.png", orden=0)
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Instructivo Contable",
        texto_limpio=texto_original,
        recursos={"rec_1": r1},
        tipo_plantilla="instructivo",
    )

    mock_baco = MagicMock()
    import pytest
    with pytest.raises(HTTPException) as exc:
        ejecutar_skill_plantillas("ses_step5_test", borrador, mock_baco)

    assert exc.value.status_code == 400
    mock_baco.assert_not_called()


def test_skill_plantillas_acepta_texto_puro_sin_recursos():
    """Si el borrador no contiene recursos ni marcadores, la skill procesa el texto puro normalmente."""
    from unittest.mock import MagicMock, patch
    from baco.server.services.agente_service import ejecutar_skill_plantillas

    texto_original = "Paso 1: Configuración inicial.\n\nPaso 2: Finalización del proceso."
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Instructivo Contable",
        texto_limpio=texto_original,
        recursos={},
        tipo_plantilla="instructivo",
    )

    respuesta_buena = "## Instructivo Oficial\n\n### Procedimiento\nPaso 1 y Paso 2 maquetados correctamente."
    mock_baco = MagicMock(return_value=respuesta_buena)

    with patch("baco.server.services.agente_service.actualizar_borrador_texto"):
        resultado = ejecutar_skill_plantillas("ses_retry_ok", borrador, mock_baco)

    assert mock_baco.call_count == 1
    assert resultado == respuesta_buena

def test_componer_texto_publicable_sustituye_marcadores_inline_sin_seccion_final_recursos():
    """Cambio 4: componer_texto_publicable sustituye cada marcador por su Markdown

    en la posición exacta, sin sección ## Recursos al final.
    """
    from baco.server.services.orquestador.recursos_service import (
        componer_texto_publicable,
        extraer_recursos_y_texto_limpio,
    )

    texto_con_pasos = (
        "### Paso 1: Configurar impuestos\n"
        "Acceder al módulo correspondiente.\n\n"
        "![Captura Impuestos](https://bc.finneg.com/impuestos.png)\n\n"
        "### Paso 2: Video demostrativo\n"
        "https://www.youtube.com/watch?v=tutorial_demo\n\n"
        "### Paso 3: Descarga de constancia AFIP\n"
        "[constancia.pdf|attachment](https://bc.finneg.com/constancia.pdf)"
    )

    texto_limpio, recursos = extraer_recursos_y_texto_limpio(texto_con_pasos)

    # Creamos el borrador
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía Fiscal",
        texto_limpio=texto_limpio,
        recursos=recursos,
    )

    publicable = borrador.texto_alineado_discourse

    # 1. NO existe sección ## Recursos al final
    assert "## Recursos" not in publicable

    # 2. Cada recurso está sustituido en su posición exacta junto a su paso
    bloques = [b.strip() for b in publicable.split("\n\n") if b.strip()]

    # Paso 1 contiene la imagen de impuestos
    idx_p1 = next(i for i, b in enumerate(bloques) if "Paso 1" in b)
    assert "![Captura Impuestos](https://bc.finneg.com/impuestos.png)" in bloques[idx_p1] or (
        idx_p1 + 1 < len(bloques) and "![Captura Impuestos](https://bc.finneg.com/impuestos.png)" in bloques[idx_p1 + 1]
    )

    # Paso 2 contiene el video
    idx_p2 = next(i for i, b in enumerate(bloques) if "Paso 2" in b)
    assert "https://www.youtube.com/watch?v=tutorial_demo" in bloques[idx_p2] or (
        idx_p2 + 1 < len(bloques) and "https://www.youtube.com/watch?v=tutorial_demo" in bloques[idx_p2 + 1]
    )

    # Paso 3 contiene el adjunto
    idx_p3 = next(i for i, b in enumerate(bloques) if "Paso 3" in b)
    assert "[constancia.pdf|attachment](https://bc.finneg.com/constancia.pdf)" in bloques[idx_p3] or (
        idx_p3 + 1 < len(bloques) and "[constancia.pdf|attachment](https://bc.finneg.com/constancia.pdf)" in bloques[idx_p3 + 1]
    )

    # 3. Ningún marcador [[recurso:...]] sobrevive en el texto publicable
    assert "[[recurso:" not in publicable
