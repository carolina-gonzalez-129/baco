"""Tests para los ajustes específicos de PII: emails, credenciales de 3 niveles, URLs y CUITs."""
import pytest
from baco.server.services.validar_articulo import sanitizar_borrador


def test_emails_personales_y_nominales_se_reemplazan():
    texto = "Enviar CV a juan.perez@empresa.com y copia a maria@gmail.com"
    res = sanitizar_borrador(texto=texto)
    assert "juan.perez@empresa.com" not in res["texto_sanitizado"]
    assert "maria@gmail.com" not in res["texto_sanitizado"]
    assert res["detalles"]["emails"] == 2
    assert "dirección de correo personal" in res["aviso_privacidad"]


def test_emails_genericos_y_de_ejemplo_no_se_tocan():
    texto = (
        "Para consultas escribir a soporte@empresa.com, ventas@finnegans.com.ar, "
        "mesa.ayuda@cliente.com o admin@ejemplo.com"
    )
    res = sanitizar_borrador(texto=texto)
    # Ninguno debe ser reemplazado
    assert "soporte@empresa.com" in res["texto_sanitizado"]
    assert "ventas@finnegans.com.ar" in res["texto_sanitizado"]
    assert "mesa.ayuda@cliente.com" in res["texto_sanitizado"]
    assert "admin@ejemplo.com" in res["texto_sanitizado"]
    assert res["detalles"]["emails"] == 0


def test_credenciales_tres_niveles():
    # 1. No se toca (placeholder y descripción)
    t1 = 'Configuración: password: <tu_clave>, secret: xxxx, password: changeme y "la contraseña del usuario".'
    r1 = sanitizar_borrador(texto=t1)
    assert "<tu_clave>" in r1["texto_sanitizado"]
    assert "xxxx" in r1["texto_sanitizado"]
    assert "changeme" in r1["texto_sanitizado"]
    assert r1["detalles"]["descartados_por_placeholder"] >= 3
    assert r1["detalles"]["credenciales_ocultas"] == 0

    # 2. Se oculta (alta entropía y tokens con formato propio)
    t2 = 'Conectar con AWS AKIAIOSFODNN7EXAMPLE, JWT eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeak y password: ClaveSuperDificil123'
    r2 = sanitizar_borrador(texto=t2)
    assert "[TOKEN_OCULTO]" in r2["texto_sanitizado"]
    assert "[CONTRASENA_OCULTA]" in r2["texto_sanitizado"]
    assert "AKIAIOSFODNN7EXAMPLE" not in r2["texto_sanitizado"]
    assert "ClaveSuperDificil123" not in r2["texto_sanitizado"]
    assert r2["detalles"]["credenciales_ocultas"] >= 3

    # 3. Solo aviso (ambiguo, no se reemplaza)
    t3 = 'El usuario tiene password: test y clave: 12345'
    r3 = sanitizar_borrador(texto=t3)
    assert "test" in r3["texto_sanitizado"]
    assert r3["detalles"]["credenciales_ambiguas"] >= 1
    assert "posible(s) contraseña(s)" in r3["aviso_privacidad"]
    assert r3["detalles"]["credenciales_ocultas"] == 0


def test_urls_e_ips_internas_no_se_reemplazan():
    texto = "Ingresar a http://localhost:8080/app o configurar la base en 192.168.1.50 para pruebas internas."
    res = sanitizar_borrador(texto=texto)
    assert "http://localhost:8080/app" in res["texto_sanitizado"]
    assert "192.168.1.50" in res["texto_sanitizado"]
    assert res["detalles"]["urls"] == 0


def test_cuits_prefijo_humano_vs_empresa():
    # 20-30405060-9 -> Persona humana (con dígito verificador válido, se oculta)
    # 30-69843145-4 -> Empresa (no se toca)
    texto = "CUIT persona: 20-30405060-9 y CUIT empresa: 30-69843145-4"
    res = sanitizar_borrador(texto=texto)
    assert "[CUIT_OCULTO]" in res["texto_sanitizado"]
    assert "20-30405060-9" not in res["texto_sanitizado"]
    assert "30-69843145-4" in res["texto_sanitizado"]
    assert res["detalles"]["cuit"] == 1
    assert "CUIT/CUIL personal" in res["aviso_privacidad"]
