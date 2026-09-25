"""Evaluador de duplicidad, sin base: productos resueltos + membresías + cupos."""
import pytest

from app.services.duplicity_checker import Producto, cargar_cupos, evaluar

SIN_CUPOS = {"clases": {}, "excepciones": []}
CANON = {1: "Acetaminophen", 2: "Codeine", 3: "Diazepam", 4: "Lorazepam",
         5: "Enalapril", 6: "Insulin glargine", 7: "Insulin aspart",
         8: "Insulin detemir"}
CLASES = {1: [("N02BE", "Anilidas")], 3: [("N05BA", "Benzodiazepinas")],
          4: [("N05BA", "Benzodiazepinas")], 5: [("C09AA", "IECA")],
          6: [("A10AB", "Insulinas")], 7: [("A10AB", "Insulinas")],
          8: [("A10AB", "Insulinas")]}


def P(pid, *pares):
    return Producto(id=pid, sustancias=tuple(n for n, _ in pares),
                    drug_ids=tuple(d for _, d in pares))


def test_misma_sustancia_en_dos_productos_es_capa_1():
    out = evaluar([P("p1", ("paracetamol", 1)), P("p2", ("paracetamol", 1), ("codeina", 2))],
                  CLASES, SIN_CUPOS, CANON)
    [d] = out["duplicities"]
    assert d["layer"] == "substance" and d["severity"] == "major"
    assert d["products"] == ["p1", "p2"] and d["cupo"] == 0
    # la de clase N02BE la explica la de sustancia: no se repite
    assert not [x for x in out["duplicities"] if x["layer"] == "class"]


def test_sustancias_del_mismo_producto_no_se_comparan():
    out = evaluar([P("p1", ("diazepam", 3), ("lorazepam", 4))], CLASES, SIN_CUPOS, CANON)
    assert out["duplicities"] == []


def test_dos_de_la_misma_clase_es_capa_2():
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, SIN_CUPOS, CANON)
    [d] = out["duplicities"]
    assert (d["layer"], d["class_id"], d["count"], d["cupo"]) == ("class", "N05BA", 2, 1)
    assert d["severity"] == "moderate" and d["source"] == "aemps"
    assert d["substances"] == ["diazepam", "lorazepam"]


def test_cupo_curado_suprime_y_lo_dice():
    cupos = {"clases": {"N05BA": {"cupo": 2, "motivo": "m", "referencia": "r",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, cupos, CANON)
    assert out["duplicities"] == []
    [s] = out["duplicities_suppressed"]
    assert s["motivo"] == "m" and s["referencia"] == "r" and s["validado"] is False


def test_clase_desactivada_suprime():
    cupos = {"clases": {"N05BA": {"desactivada": True, "motivo": "amplia",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, cupos, CANON)
    assert out["duplicities"] == [] and out["duplicities_suppressed"][0]["motivo"] == "amplia"


def test_excepcion_por_grupos():
    cupos = {"clases": {}, "excepciones": [{
        "clase": "A10AB", "grupos": [["Insulin glargine"], ["Insulin aspart"]],
        "motivo": "basal + bolo", "referencia": "x", "validado": False}]}
    uno_de_cada = evaluar([P("p1", ("glargina", 6)), P("p2", ("aspart", 7))], CLASES, cupos, CANON)
    assert uno_de_cada["duplicities"] == []
    assert uno_de_cada["duplicities_suppressed"][0]["motivo"] == "basal + bolo"


def test_excepcion_no_aplica_a_dos_del_mismo_grupo():
    # dos insulinas del MISMO grupo (basal): la excepción no cubre esto, alerta normal.
    cupos = {"clases": {}, "excepciones": [{
        "clase": "A10AB", "grupos": [["Insulin glargine", "Insulin detemir"], ["Insulin aspart"]],
        "motivo": "basal + bolo", "referencia": "x", "validado": False}]}
    out = evaluar([P("p1", ("glargina", 6)), P("p2", ("detemir", 8))], CLASES, cupos, CANON)
    [d] = out["duplicities"]
    assert d["layer"] == "class" and d["class_id"] == "A10AB"
    assert out["duplicities_suppressed"] == []


def test_no_resuelto_se_declara():
    out = evaluar([P("p1", ("xx", None)), P("p2", ("diazepam", 3))], CLASES, SIN_CUPOS, CANON)
    assert out["duplicity_not_evaluated"] == ["xx"]


def test_sin_tabla_de_clases_avisa_y_hace_capa_1():
    out = evaluar([P("p1", ("paracetamol", 1)), P("p2", ("paracetamol", 1))], None, SIN_CUPOS, CANON)
    assert out["duplicities"][0]["layer"] == "substance"
    assert out["duplicity_warnings"]


# --- correcciones de revisión -------------------------------------------------

def test_capa1_que_cubre_toda_la_clase_evita_la_alerta_de_capa_2():
    # p1 es un combinado diazepam+lorazepam, p2 sólo diazepam: el diazepam
    # (capa 1) ya cubre a los dos productos de la clase N05BA, no hace falta
    # repetir la alerta de clase.
    out = evaluar([P("p1", ("diazepam", 3), ("lorazepam", 4)), P("p2", ("diazepam", 3))],
                  CLASES, SIN_CUPOS, CANON)
    assert len(out["duplicities"]) == 1
    assert out["duplicities"][0]["layer"] == "substance"
    assert out["duplicities"][0]["products"] == ["p1", "p2"]


def test_ids_de_producto_repetidos_lanza_valueerror():
    with pytest.raises(ValueError, match="id de producto repetido"):
        evaluar([P("p1", ("diazepam", 3)), P("p1", ("lorazepam", 4))], CLASES, SIN_CUPOS, CANON)


def test_products_de_clase_en_orden_de_entrada():
    # did=4 (lorazepam) aparece primero en p1 y p3; did=3 (diazepam) en p2.
    # El orden de los productos en la alerta debe ser el de entrada, no el
    # de primera aparición de cada droga.
    out = evaluar([P("p1", ("lorazepam", 4)), P("p2", ("diazepam", 3)), P("p3", ("lorazepam", 4))],
                  CLASES, SIN_CUPOS, CANON)
    [d] = [x for x in out["duplicities"] if x["layer"] == "class"]
    assert d["products"] == ["p1", "p2", "p3"]


def test_clase_desactivada_suprime_con_cupo_none():
    cupos = {"clases": {"N05BA": {"desactivada": True, "motivo": "amplia",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4))], CLASES, cupos, CANON)
    [s] = out["duplicities_suppressed"]
    assert s["cupo"] is None


def test_cupo_2_con_3_productos_sigue_alertando():
    cupos = {"clases": {"N05BA": {"cupo": 2, "motivo": "m", "referencia": "r",
                                  "validado": False}}, "excepciones": []}
    out = evaluar([P("p1", ("diazepam", 3)), P("p2", ("lorazepam", 4)), P("p3", ("diazepam", 3))],
                  CLASES, cupos, CANON)
    [d] = [x for x in out["duplicities"] if x["layer"] == "class"]
    assert d["count"] == 3 and d["cupo"] == 2
    assert out["duplicities_suppressed"] == []


def test_excepcion_no_cubre_producto_fuera_de_los_grupos():
    # detemir no figura en ningún grupo de la excepción: no se suprime.
    cupos = {"clases": {}, "excepciones": [{
        "clase": "A10AB", "grupos": [["Insulin glargine"], ["Insulin aspart"]],
        "motivo": "basal + bolo", "referencia": "x", "validado": False}]}
    out = evaluar([P("p1", ("glargina", 6)), P("p2", ("aspart", 7)), P("p3", ("detemir", 8))],
                  CLASES, cupos, CANON)
    [d] = [x for x in out["duplicities"] if x["layer"] == "class"]
    assert d["class_id"] == "A10AB"
    assert out["duplicities_suppressed"] == []


def test_cargar_cupos_real_tiene_las_claves_esperadas():
    data = cargar_cupos()
    assert isinstance(data["clases"], dict)
    assert isinstance(data["excepciones"], list)
