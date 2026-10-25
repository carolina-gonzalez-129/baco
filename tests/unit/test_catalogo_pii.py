"""Tests para el catálogo de PII y autosanitización en validar_articulo."""
import pytest
from baco.server.services.validar_articulo import sanitizar_borrador


def test_autosanitizacion_cbu_valido():
    # CBU sintético válido de 22 dígitos: banco 072 (07201994 Santander), cuenta 30000000123450
    # Bloque 1: 0720199 (dv1 = 4)
    # Bloque 2: 3000000012345 (dv2 = 0)
    cbu_valido = "0720199430000000123450"
    texto = f"El número de cuenta del proveedor es CBU {cbu_valido} para transferencias."
    res = sanitizar_borrador(texto=texto)
    assert "[CBU_OCULTO]" in res["texto_sanitizado"]
    assert cbu_valido not in res["texto_sanitizado"]
    assert res["detalles"]["cbu"] == 1
    assert "CBU/CVU bancario" in res["aviso_privacidad"]
    # No expone el CBU en el mensaje de aviso
    assert cbu_valido not in res["aviso_privacidad"]


def test_autosanitizacion_tarjeta_con_luhn_y_prefijo():
    # Tarjeta Visa de 16 dígitos válida por Luhn
    # 4000 1234 5678 9010 (Luhn válido)
    # Digitos: 4 0 0 0  1 2 3 4  5 6 7 8  9 0 1 0
    # Impares de der a izq: (1)*2=2, (9)*2=9, (7)*2=5, (5)*2=1, (3)*2=6, (1)*2=2, (0)*2=0, (4)*2=8
    # Suma impares = 2+9+5+1+6+2+0+8 = 33
    # Pares: 0 + 0 + 8 + 6 + 4 + 2 + 0 + 0 = 20 -> 33+20 = 53 (no da 10)
    # Construyamos una Visa 16 sintética con Luhn exacto: 4532 0151 1283 0366
    pan_visa = "4532-0151-1283-0366"
    texto = f"El pago se realizó con tarjeta {pan_visa} correctamente."
    res = sanitizar_borrador(texto=texto)
    assert "[TARJETA_OCULTA]" in res["texto_sanitizado"]
    assert pan_visa not in res["texto_sanitizado"]
    assert res["detalles"]["tarjeta"] == 1
    assert "número de tarjeta" in res["aviso_privacidad"]
    assert pan_visa not in res["aviso_privacidad"]


def test_autosanitizacion_dni_con_contexto():
    texto = "Presentar DNI: 35.123.456 o documento nro 28123456 en mesa de entrada."
    res = sanitizar_borrador(texto=texto)
    assert "DNI: [DOCUMENTO_OCULTO]" in res["texto_sanitizado"]
    assert "documento nro [DOCUMENTO_OCULTO]" in res["texto_sanitizado"]
    assert "35.123.456" not in res["texto_sanitizado"]
    assert "28123456" not in res["texto_sanitizado"]
    assert res["detalles"]["dni"] == 2
    assert "documento de identidad (DNI)" in res["aviso_privacidad"]
    assert "35.123.456" not in res["aviso_privacidad"]


def test_autosanitizacion_cvv_con_contexto():
    texto = "Completar con código de seguridad: 789 y CVV 1234 para validar."
    res = sanitizar_borrador(texto=texto)
    assert "código de seguridad: [CVV_OCULTO]" in res["texto_sanitizado"]
    assert "CVV [CVV_OCULTO]" in res["texto_sanitizado"]
    assert "789" not in res["texto_sanitizado"]
    assert "1234" not in res["texto_sanitizado"]
    assert res["detalles"]["cvv"] == 2
    assert "código de seguridad (CVV)" in res["aviso_privacidad"]


def test_autosanitizacion_credenciales_tokens_y_passwords():
    texto = (
        'Configuración: password: MiClaveSecreta123, '
        'usar token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 '
        'y AWS_KEY AKIAIOSFODNN7EXAMPLE para el bucket.'
    )
    res = sanitizar_borrador(texto=texto)
    assert "password: [CONTRASENA_OCULTA]" in res["texto_sanitizado"]
    assert "Bearer [TOKEN_OCULTO]" in res["texto_sanitizado"]
    assert "[TOKEN_OCULTO]" in res["texto_sanitizado"]
    assert "MiClaveSecreta123" not in res["texto_sanitizado"]
    assert "AKIAIOSFODNN7EXAMPLE" not in res["texto_sanitizado"]
    assert res["detalles"]["credenciales_ocultas"] >= 3
    assert "credencial/token secreto" in res["aviso_privacidad"]
    assert "MiClaveSecreta123" not in res["aviso_privacidad"]


def test_idempotencia_sanitizacion():
    texto_original = "Titular DNI: 30.123.456 con tarjeta 4532 0151 1283 0366 y password: MiClaveSuperSegura123"
    paso1 = sanitizar_borrador(texto=texto_original)["texto_sanitizado"]
    paso2 = sanitizar_borrador(texto=paso1)["texto_sanitizado"]
    assert paso1 == paso2
    assert "[CONTRASENA_OCULTA]" in paso1
    # El paso 2 ya no encuentra nada que sanitizar ni ambiguo
    detalles_paso2 = sanitizar_borrador(texto=paso1)["detalles"]
    assert sum(detalles_paso2.values()) == 0


def test_autosanitizacion_cuil_contextual():
    texto = "Dar de alta al empleado con CUIL: 20-30405060-9 en el módulo de sueldos."
    res = sanitizar_borrador(texto=texto)
    assert "CUIL: [CUIT_OCULTO]" in res["texto_sanitizado"]
    assert "20-30405060-9" not in res["texto_sanitizado"]
    assert res["detalles"]["cuit"] == 1
    assert "CUIT/CUIL personal" in res["aviso_privacidad"]
    assert "preservarte" in res["aviso_privacidad"]


def test_autosanitizacion_cuil_sin_guiones_contextual():
    texto = "Cargar en el formulario el CUIL 23400112940 para la autorización."
    res = sanitizar_borrador(texto=texto)
    assert "CUIL [CUIT_OCULTO]" in res["texto_sanitizado"]
    assert "23400112940" not in res["texto_sanitizado"]
    assert res["detalles"]["cuit"] == 1
    assert "preservarte" in res["aviso_privacidad"]
