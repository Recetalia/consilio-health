"""Monografías (ficha técnica AEMPS) — piezas puras que comparten el ETL y el runtime.

- `clave_composicion`: la identidad de una monografía es la COMPOSICIÓN (conjunto de principios activos), no
  el producto: la ficha del paracetamol sirve para cualquier paracetamol monodroga. ETL y runtime tienen que
  calcular la misma clave, por eso vive acá.
- `sanitizar_html`: el HTML de CIMA trae estilos inline de Word; se deja sólo estructura de texto. El TEXTO no se
  toca (el aviso legal de la AEMPS no permite transformar los contenidos; quitar formato no lo es).
- `agrupar_secciones`: de la ficha completa se muestran 4.1–4.6 y 4.8, con sus subsecciones fusionadas.
"""
from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

from app.clients.recetalia_db import normalize

SECCIONES = ("4.1", "4.2", "4.3", "4.4", "4.5", "4.6", "4.8")

_PERMITIDAS = {"p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
               "b", "strong", "i", "em", "u", "sub", "sup", "br"}
_VACIAS = {"br"}
_DESCARTAR_CON_CONTENIDO = {"script", "style", "img", "head", "title"}
_ATRIBUTOS = {"colspan", "rowspan"}

# Hidratos: no cambian el principio activo ("amoxicilina trihidrato" = amoxicilina). `normalize` ya saca las sales.
_HIDRATOS = re.compile(r"\b(?:anhidr[oa]|(?:mono|di|tri|tetra|penta|hexa|hepta|hemi|sesqui)?hidrat[oa])\b")


def clave_composicion(nombres) -> str:
    """`["Paracetamol", "Ibuprofeno"]` → `"ibuprofeno+paracetamol"`. Vacío si no queda ningún nombre."""
    partes = set()
    for n in nombres or []:
        base = re.sub(r"\s+", " ", _HIDRATOS.sub(" ", normalize(n or ""))).strip()
        if base:
            partes.add(base)
    return "+".join(sorted(partes))


class _Saneador(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._descartando = 0

    def handle_starttag(self, tag, attrs):
        if tag in _DESCARTAR_CON_CONTENIDO:
            if tag not in ("img",):
                self._descartando += 1
            return
        if self._descartando or tag not in _PERMITIDAS:
            return
        extra = "".join(f' {k}="{escape(v or "", quote=True)}"' for k, v in attrs
                        if k in _ATRIBUTOS and (v or "").isdigit())
        self.out.append(f"<{tag}{extra}>")

    def handle_startendtag(self, tag, attrs):
        if tag in _VACIAS and not self._descartando:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in _DESCARTAR_CON_CONTENIDO and tag != "img":
            self._descartando = max(0, self._descartando - 1)
            return
        if self._descartando or tag not in _PERMITIDAS or tag in _VACIAS:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._descartando:
            self.out.append(escape(data, quote=False))


def sanitizar_html(html: str) -> str:
    p = _Saneador()
    p.feed(html or "")
    p.close()
    texto = "".join(p.out)
    texto = re.sub(r"[ \t\r\n]+", " ", texto)          # el espaciado de Word
    texto = re.sub(r"\s*(</?(?:p|ul|ol|li|table|thead|tbody|tr|td|th)\b[^>]*>)\s*", r"\1", texto)
    texto = re.sub(r"<p>(?:\s|&nbsp;|\xa0)*</p>", "", texto)  # párrafos vacíos
    return texto.strip()


def _vacio(html: str) -> bool:
    return not re.sub(r"<[^>]+>|\s|\xa0", "", html or "")


def agrupar_secciones(raw: list[dict]) -> list[dict]:
    """Lista de CIMA (`seccion`, `titulo`, `contenido`) → secciones de la ficha, saneadas y en orden."""
    grupos: dict[str, dict] = {}
    for s in raw or []:
        num = str(s.get("seccion") or "").strip()
        madre = ".".join(num.split(".")[:2])
        if madre not in SECCIONES:
            continue
        html = sanitizar_html(s.get("contenido") or "")
        g = grupos.setdefault(madre, {"seccion": madre, "titulo": None, "html": ""})
        if num == madre:
            g["titulo"] = (s.get("titulo") or "").strip()
            g["html"] = html + g["html"]
        elif not _vacio(html):
            g["html"] += f"<p><b>{escape((s.get('titulo') or '').strip(), quote=False)}</b></p>{html}"
    out = []
    for madre in SECCIONES:
        g = grupos.get(madre)
        if g and not _vacio(g["html"]):
            g["titulo"] = g["titulo"] or madre
            out.append(g)
    return out
