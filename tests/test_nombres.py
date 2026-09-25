"""El esqueleto junta la grafía castellana y la inglesa de un mismo INN."""
from app.nlp.nombres import skeleton


def test_castellano_e_ingles_caen_en_el_mismo_esqueleto():
    assert skeleton("Domperidona") == skeleton("Domperidone") == "domperidon"
    assert skeleton("diclofenaco") == skeleton("Diclofenac")
    assert skeleton("Disopiramida") == skeleton("Disopyramide")


def test_el_script_sigue_exportando_skeleton():
    import sys
    sys.path.insert(0, "scripts")
    from cross_aemps_interactions import skeleton as s
    assert s is skeleton
