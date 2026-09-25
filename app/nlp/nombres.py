"""Comparación de nombres de fármaco entre castellano e inglés.

Vive en `app/` y no en `scripts/` porque ahora lo usan los dos: el ETL para
cruzar la AEMPS, y la resolución de nombres en tiempo de consulta, que recibe
las sustancias del DNMA en castellano (`diclofenaco`) contra alias en inglés.
"""
from __future__ import annotations

import re
import unicodedata

# Correspondencias sistemáticas entre el INN castellano y el inglés. Se aplican
# a los DOS lados, así que no importa cuál de las dos grafías es la "correcta":
# importa que las dos caigan en la misma.
_SKEL_SUBS = (
    ("ph", "f"), ("th", "t"), ("ch", "c"), ("qu", "c"), ("ou", "u"),
    ("ae", "e"), ("oe", "e"), ("y", "i"), ("k", "c"), ("w", "v"),
)


def skeleton(s: str) -> str:
    """Forma común a la grafía castellana e inglesa de un mismo INN.

    `Domperidona` y `Domperidone` → `domperidon`.
    `Disopiramida` y `Disopyramide` → `disopiramid`.
    """
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z ]+", " ", s).strip()
    for a, b in _SKEL_SUBS:
        s = s.replace(a, b)
    s = re.sub(r"(.)\1+", r"\1", s)
    palabras = []
    for w in s.split():
        w = re.sub(r"e$", "", w)
        w = re.sub(r"[ao]$", "", w)
        if w:
            palabras.append(w)
    return " ".join(palabras)
