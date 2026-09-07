r"""TextForgeEdit -- ponto de entrada.

    .venv\Scripts\python.exe app.py [arquivo]
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from tfedit import APP, VERSAO
    from tfedit.interface.janela_principal import JanelaPrincipal

    aplicacao = QApplication(sys.argv)
    aplicacao.setApplicationName(APP)
    aplicacao.setApplicationVersion(VERSAO)

    janela = JanelaPrincipal()
    janela.show()
    # O arquivo da linha de comando e' aberto DEPOIS de a janela aparecer: um
    # arquivo de 1 GB leva alguns segundos para indexar, e abrir antes deixaria
    # o usuario olhando para a area de trabalho sem sinal de vida.
    for argumento in sys.argv[1:]:
        if not argumento.startswith("-"):
            janela.abrir_arquivo(argumento)
            break
    return aplicacao.exec()


if __name__ == "__main__":
    sys.exit(main())
