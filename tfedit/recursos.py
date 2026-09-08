"""Localiza os arquivos de `tfedit/recursos/` com e sem PyInstaller.

Sem este modulo os temas desaparecem no .exe: o PyInstaller descompacta os
`datas` em `sys._MEIPASS`, que nao e' a pasta do pacote nem a pasta do
executavel. Todo acesso a recurso passa por aqui.
"""

from __future__ import annotations

import pathlib
import sys


def raiz() -> pathlib.Path:
    """Pasta que contem `tfedit/recursos`."""
    interna = getattr(sys, "_MEIPASS", None)
    if interna:
        return pathlib.Path(interna)
    return pathlib.Path(__file__).resolve().parent.parent


def caminho(*partes: str) -> pathlib.Path:
    """Caminho de um recurso embutido, ex.: caminho("temas", "escuro.json")."""
    return raiz().joinpath("tfedit", "recursos", *partes)


def ler_texto(*partes: str) -> str:
    return caminho(*partes).read_text(encoding="utf-8")
