"""Perfil del paciente: de estados fisiológicos a condiciones de la base.

## Por qué esto no pasa por CIE-10

Embarazo, lactancia, insuficiencia renal y hepática **no son diagnósticos**: son
estados del paciente, y buscarlos en un catálogo de enfermedades es modelarlos
mal. Medido sobre MONDO, los cuatro fallan como diagnóstico justamente por eso.

Tratarlos como flags los habilita **sin construir el puente CIE-10**: son 728 de
las 6.522 alertas (11,2 %), disponibles con cuatro mapeos a mano.

El producto de referencia que motivó este trabajo hace lo mismo: embarazo y
lactancia son casillas, no búsqueda de patología.

## La alergia no está acá, y el motivo importa

Un primer intento la incluyó como flag, mapeada a `Drug Hypersensitivity`
(D004342, 1.338 alertas). **Estaba mal y era peligroso.** Ese descriptor
significa "contraindicado en pacientes hipersensibles A ESTE fármaco": es
autorreferencial. Con el flag, declarar alergia a la aspirina marcaba como
contraindicada también la metformina — y de hecho los 1.338 fármacos que lo
tienen. Un producto que marca todo no marca nada.

La alergia se resuelve por fármaco, en `contraindication_checker`. Ver ahí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Cada flag del perfil a los descriptores MeSH que MED-RT usa. Los códigos
# salieron de consultar la base, no de suponerlos.
FLAG_TO_MESH: dict[str, list[str]] = {
    "embarazo": [
        "D011247",  # Pregnancy
        "D011261",  # Pregnancy Trimester, First
        "D011262",  # Pregnancy Trimester, Second
        "D011263",  # Pregnancy Trimester, Third
    ],
    "lactancia": [
        "D007774",  # Lactation
        "D001942",  # Breast Feeding
    ],
    "insuficiencia_renal": [
        "D051437",  # Renal Insufficiency
        "D007674",  # Kidney Diseases
        "D051436",  # Renal Insufficiency, Chronic
    ],
    "insuficiencia_hepatica": [
        "D008107",  # Liver Diseases
        "D017093",  # Liver Failure
        "D048550",  # Hepatic Insufficiency
        "D008103",  # Liver Cirrhosis
    ],
}

# ⚠️ NO hay flag de alergia acá, y es deliberado.
#
# `Drug Hypersensitivity` (D004342) de MED-RT significa "contraindicado en
# pacientes hipersensibles A ESTE fármaco": es autorreferencial y no dice nada
# que el médico no sepa. Usarlo como flag hacía que declarar CUALQUIER alergia
# marcara como contraindicados los 1.338 fármacos que la tienen — probado:
# alergia a aspirina marcaba también la metformina.
#
# La alergia se resuelve comparando el fármaco recetado contra lo que el
# paciente declaró, en `contraindication_checker._match_allergies`. Eso sí es
# específico y sí es accionable.

# Por trimestre. Un fármaco contraindicado en el primer trimestre puede ser
# aceptable en el tercero, así que si sabemos la semana no disparamos los tres.
TRIMESTRE_MESH = {1: "D011261", 2: "D011262", 3: "D011263"}


@dataclass
class PatientProfile:
    """Lo que sabemos del paciente. Todo opcional: sin datos, no hay alertas."""

    sexo: Literal["M", "F", None] = None
    edad: int | None = None
    embarazo: bool = False
    semanas_gestacion: int | None = None
    lactancia: bool = False
    # Ninguna / leve / moderada / grave. Cualquier valor distinto de "ninguna"
    # activa el flag: MED-RT no gradúa, así que graduarlo nosotros sería
    # inventar precisión que el dato no tiene.
    funcion_renal: str | None = None
    funcion_hepatica: str | None = None
    # Fármacos a los que el paciente reaccionó, por nombre.
    alergias: list[str] = field(default_factory=list)
    # Patologías en MeSH, si el llamador ya las tiene en ese vocabulario.
    patologias_mesh: list[str] = field(default_factory=list)
    # Patologías en CIE-10, que es lo que carga un médico. Se traducen con el
    # puente (`condition_xref`), no acá: esta clase no conoce la base.
    patologias_icd10: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """Incoherencias que conviene avisar en vez de resolver en silencio."""
        out = []
        if self.embarazo and self.sexo == "M":
            out.append("Se marcó embarazo con sexo masculino.")
        if self.semanas_gestacion is not None and not self.embarazo:
            out.append("Hay semanas de gestación pero no está marcado el embarazo.")
        if self.semanas_gestacion is not None and not (0 < self.semanas_gestacion <= 45):
            out.append(f"Semanas de gestación fuera de rango: {self.semanas_gestacion}.")
        return out

    def mesh_codes(self) -> set[str]:
        """Los descriptores MeSH que este perfil activa."""
        codes: set[str] = set()

        if self.embarazo:
            if self.semanas_gestacion:
                # Semana -> trimestre. Se suma el genérico igual: la mayoría de
                # las contraindicaciones de MED-RT cuelgan de "Pregnancy" a
                # secas, y perderlas por precisión sería el peor intercambio.
                t = 1 if self.semanas_gestacion <= 13 else 2 if self.semanas_gestacion <= 27 else 3
                codes.add(TRIMESTRE_MESH[t])
            else:
                codes.update(FLAG_TO_MESH["embarazo"])
            codes.add("D011247")

        if self.lactancia:
            codes.update(FLAG_TO_MESH["lactancia"])
        if self.funcion_renal and self.funcion_renal.lower() not in ("", "ninguna", "normal"):
            codes.update(FLAG_TO_MESH["insuficiencia_renal"])
        if self.funcion_hepatica and self.funcion_hepatica.lower() not in ("", "ninguna", "normal"):
            codes.update(FLAG_TO_MESH["insuficiencia_hepatica"])
        codes.update(self.patologias_mesh)
        return codes

    def has_data(self) -> bool:
        # La edad sola ya alcanza: dispara los criterios de prescripción en el
        # anciano aunque no haya ninguna patología cargada.
        return bool(self.mesh_codes() or self.alergias or self.patologias_icd10
                    or self.edad is not None)
