r"""TextForgeEdit -- ponto de entrada.

    .venv\Scripts\python.exe app.py [arquivo]
    TextForgeEdit.exe --autoverificacao
"""

from __future__ import annotations

import sys

#: Modulos que TEM de estar no pacote. Alguns sao import tardio e por isso
#: invisiveis para a analise estatica do PyInstaller; outros poderiam ser
#: derrubados por um `exclude` agressivo no .spec. Excludes quebram o programa
#: SO' EM TEMPO DE EXECUCAO -- sem esta checagem, "os excludes quebraram o app"
#: chegaria como relatorio de bug do usuario em vez de falha de build.
OBRIGATORIOS = (
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "PySide6.QtNetwork",       # QLocalServer: instancia unica e "Abrir com"
    "charset_normalizer",      # deteccao de codificacao (import tardio)
    "mmap", "codecs", "shutil", "ctypes",
    "tfedit.original", "tfedit.pecas", "tfedit.gravacao",
    "tfedit.janela", "tfedit.codificacao",
    "tfedit.interface.editor", "tfedit.interface.janela_principal",
    "tfedit.interface.indexador",
)


def autoverificacao() -> int:
    """Prova que o executavel gerado funciona. Roda no fim do build."""
    import importlib
    import tempfile

    faltando = []
    for nome in OBRIGATORIOS:
        try:
            importlib.import_module(nome)
        except ImportError as exc:
            faltando.append(f"{nome} ({exc})")
    if faltando:
        print("AUTOVERIFICACAO FALHOU: modulos ausentes")
        for nome in faltando:
            print("  -", nome)
        return 1

    # Uma prova de vida de ponta a ponta: cria um arquivo, edita e grava. Se
    # algum `exclude` tiver derrubado uma dependencia do nucleo, e' aqui que
    # aparece -- e nao na maquina do usuario.
    import pathlib

    from tfedit.gravacao import gravar
    from tfedit.original import Original
    from tfedit.pecas import Documento

    pasta = pathlib.Path(tempfile.mkdtemp(prefix="tfedit-auto-"))
    try:
        alvo = pasta / "prova.txt"
        alvo.write_bytes(b"linha um\r\nlinha dois\r\n")
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        doc.substituir(6, 2, b"UM")
        gravar(alvo, doc, antes_de_trocar=original.fechar)
        if alvo.read_bytes() != b"linha UM\r\nlinha dois\r\n":
            print("AUTOVERIFICACAO FALHOU: a gravacao nao produziu o esperado")
            print("  obtido:", alvo.read_bytes())
            return 1
    finally:
        import shutil
        shutil.rmtree(pasta, ignore_errors=True)

    from PySide6.QtWidgets import QApplication

    from tfedit.interface.janela_principal import JanelaPrincipal

    aplicacao = QApplication.instance() or QApplication([])
    janela = JanelaPrincipal()          # monta menus, barra e widgets
    janela.close()
    del aplicacao

    print(f"autoverificacao OK ({len(OBRIGATORIOS)} modulos, gravacao e "
          f"janela)")
    return 0


def main() -> int:
    if "--autoverificacao" in sys.argv:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return autoverificacao()

    from PySide6.QtWidgets import QApplication

    from tfedit import APP, VERSAO
    from tfedit.interface.janela_principal import JanelaPrincipal

    aplicacao = QApplication(sys.argv)
    aplicacao.setApplicationName(APP)
    aplicacao.setApplicationVersion(VERSAO)

    janela = JanelaPrincipal()
    janela.show()
    # O arquivo da linha de comando e' aberto DEPOIS de a janela aparecer: a
    # janela vazia surge na hora, e o arquivo entra em seguida com a barra de
    # progresso da indexacao. Abrir antes deixaria o usuario olhando para a area
    # de trabalho sem sinal de vida.
    for argumento in sys.argv[1:]:
        if not argumento.startswith("-"):
            janela.abrir_arquivo(argumento)
            break
    return aplicacao.exec()


if __name__ == "__main__":
    sys.exit(main())
