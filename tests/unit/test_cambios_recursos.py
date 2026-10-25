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

    # 1. Verificar que texto_limpio tiene los marcadores junto a cada paso
    assert "[[recurso:rec_1]]" in texto_limpio
    assert "[[recurso:rec_2]]" in texto_limpio
    assert "[[recurso:rec_3]]" in texto_limpio
    assert "[[recurso:rec_4]]" in texto_limpio

    # 2. Las URLs originales no están en texto_limpio
    assert "https://bc.finneg.com/uploads/menu_contable.png" not in texto_limpio
    assert "https://bc.finneg.com/uploads/asientos_pendientes.png" not in texto_limpio
    assert "https://www.youtube.com/watch?v=cierre2026" not in texto_limpio

    # 3. Cada marcador está inmediatamente asociado a su paso correspondiente
    bloques = [b.strip() for b in texto_limpio.split("\n\n") if b.strip()]
    idx_p1 = next(i for i, b in enumerate(bloques) if "Paso 1" in b)
    assert "[[recurso:rec_1]]" in bloques[idx_p1] or (idx_p1 + 1 < len(bloques) and "[[recurso:rec_1]]" in bloques[idx_p1 + 1])

    idx_p2 = next(i for i, b in enumerate(bloques) if "Paso 2" in b)
    assert "[[recurso:rec_2]]" in bloques[idx_p2] or (idx_p2 + 1 < len(bloques) and "[[recurso:rec_2]]" in bloques[idx_p2 + 1])

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
    """Cambio 3: cada marcador válido que referencia un recurso existente se preserva intacto."""
    r1 = Recurso(id="rec_1", tipo="imagen", nombre="captura.png", referencia="https://bc.finneg.com/c.png", orden=0)
    r2 = Recurso(id="rec_2", tipo="video", nombre="tutorial.mp4", referencia="https://youtube.com/v", orden=1)
    recursos = {"rec_1": r1, "rec_2": r2}

    texto = "Paso 1: Ver captura [[recurso:rec_1]].\n\nPaso 2: Ver video explicativo [[recurso:rec_2]]."
    borrador = BorradorSesion(
        modo="nuevo",
        titulo="Guía con recursos existentes",
        texto_limpio=texto,
        recursos=recursos,
    )

    # Ambos marcadores deben permanecer exactamente en su lugar (nada de borrado)
    assert borrador.texto_limpio == texto
    assert "[[recurso:rec_1]]" in borrador.texto_limpio
    assert "[[recurso:rec_2]]" in borrador.texto_limpio


def test_borrador_texto_siempre_coincide_con_composicion_de_texto_limpio_y_recursos():
    """Riesgo 4: borrador.texto coincide siempre con componer_texto_publicable y es de solo lectura."""
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
    assert borrador.texto == componer_texto_publicable(borrador.texto_limpio, borrador.recursos)

    # Es propiedad derivada: no se puede reasignar directamente
    with pytest.raises(AttributeError):
        borrador.texto = "Intento de sobreescritura directa"
