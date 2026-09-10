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


def icone_do_aplicativo():
    """O icone da JANELA e da barra de tarefas. `QIcon` vazio se faltar.

    O `.ico` esta' embutido no .exe pelo PyInstaller (`icon=` no .spec) desde
    sempre -- e' por isso que o Explorer sempre mostrou o icone certo. Mas o
    recurso do executavel so' vale para o SHELL: a janela que o Qt cria nao
    tem icone nenhum ate' alguem chamar `setWindowIcon`, e ninguem chamava. O
    resultado era o icone generico do Qt na barra de titulo e na barra de
    tarefas, num programa cujo arquivo no disco tinha o icone certo.

    Nunca levanta: um icone que falta e' um programa feio, e nao um programa
    que nao abre.
    """
    from PySide6.QtGui import QIcon

    alvo = caminho("icone.ico")
    if not alvo.exists():
        return QIcon()
    return QIcon(str(alvo))


def ler_texto(*partes: str) -> str:
    return caminho(*partes).read_text(encoding="utf-8")
