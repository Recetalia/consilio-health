"""Monografías: saneado del HTML de CIMA, agrupado de secciones y clave de composición."""
from __future__ import annotations

from app.services.monografia import agrupar_secciones, clave_composicion, sanitizar_html


def test_sanitizar_quita_estilos_y_conserva_el_texto():
    html = ('<div><p style="margin:0pt"><span style="font-family:Times New Roman">'
            'Hipersensibilidad al <b>paracetamol</b>.</span></p></div>')
    assert sanitizar_html(html) == "<p>Hipersensibilidad al <b>paracetamol</b>.</p>"


def test_sanitizar_elimina_script_estilo_e_imagenes_con_su_contenido():
    html = '<p>Texto</p><script>alert(1)</script><style>p{}</style><img src="x.png"><p>Fin</p>'
    assert sanitizar_html(html) == "<p>Texto</p><p>Fin</p>"


def test_sanitizar_conserva_tablas_con_colspan():
    html = '<table border="1"><tr><td colspan="2" style="x">Dosis</td></tr></table>'
    assert sanitizar_html(html) == '<table><tr><td colspan="2">Dosis</td></tr></table>'


def test_sanitizar_escapa_texto_y_atributos_peligrosos():
    html = '<p onclick="mal()">5 &lt; 10 &amp; más</p><a href="javascript:x">link</a>'
    assert sanitizar_html(html) == "<p>5 &lt; 10 &amp; más</p>link"


def _sec(seccion, titulo, contenido="<p>x</p>"):
    return {"seccion": seccion, "titulo": titulo, "contenido": contenido}


def test_agrupar_deja_solo_las_secciones_de_la_ficha_y_fusiona_subsecciones():
    raw = [
        _sec("1", "NOMBRE DEL MEDICAMENTO"),
        _sec("4.1", "Indicaciones terapéuticas", "<p>Dolor.</p>"),
        _sec("4.2", "Posología y forma de administración", "<p>500 mg.</p>"),
        _sec("4.2.2", "Forma de administración", "<p>Oral.</p>"),
        _sec("4.6", "Fertilidad, embarazo y lactancia", ""),
        _sec("4.6.1", "Embarazo", "<p>Compatible.</p>"),
        _sec("4.6.2", "Lactancia", "<p>Compatible.</p>"),
        _sec("4.7", "Efectos sobre la capacidad para conducir", "<p>No.</p>"),
        _sec("4.8", "Reacciones adversas", "<p>Raras.</p>"),
        _sec("4.9", "Sobredosis", "<p>Hepatotoxicidad.</p>"),
    ]
    out = agrupar_secciones(raw)
    assert [s["seccion"] for s in out] == ["4.1", "4.2", "4.6", "4.8"]
    assert out[1]["html"] == "<p>500 mg.</p><p><b>Forma de administración</b></p><p>Oral.</p>"
    assert out[2]["html"] == ("<p><b>Embarazo</b></p><p>Compatible.</p>"
                              "<p><b>Lactancia</b></p><p>Compatible.</p>")
    assert out[0]["titulo"] == "Indicaciones terapéuticas"


def test_agrupar_omite_secciones_vacias():
    assert agrupar_secciones([_sec("4.3", "Contraindicaciones", "<div> </div>")]) == []


def test_clave_composicion_normaliza_ordena_y_saca_sales():
    assert clave_composicion(["Paracetamol", "Ibuprofeno"]) == "ibuprofeno+paracetamol"
    assert clave_composicion(["ibuprofeno", "PARACETAMOL", "paracetamol"]) == "ibuprofeno+paracetamol"
    assert clave_composicion(["Amoxicilina trihidrato", "ácido clavulánico"]) == \
        clave_composicion(["amoxicilina", "Acido clavulanico"])
    assert clave_composicion(["", "  "]) == ""
