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
    "tfedit.interface.indexador", "tfedit.interface.aba",
    "tfedit.interface.barra_busca", "tfedit.busca", "tfedit.log_interno",
    "tfedit.idioma", "tfedit.cli", "tfedit.configuracao",
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

    from PySide6.QtWidgets import (QApplication, QDialogButtonBox)

    from tfedit import idioma
    from tfedit.interface.janela_principal import JanelaPrincipal

    aplicacao = QApplication.instance() or QApplication([])

    # A traducao do Qt e' o caso classico de "so' quebra no pacote": os `.qm`
    # entram por `datas` no .spec, e o PyInstaller NAO os inclui sozinho. Rodando
    # do fonte tudo aparece em portugues; no executavel, "Save" e "Cancel"
    # voltariam ao ingles sem ninguem perceber ate' o usuario abrir um dialogo.
    carregados = idioma.instalar(aplicacao)
    if "qtbase_pt_BR" not in carregados:
        print("AUTOVERIFICACAO FALHOU: a traducao pt_BR do Qt nao carregou")
        print("  procurado em:", [str(x) for x in idioma.pastas_de_traducao()])
        return 1
    caixa = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                             | QDialogButtonBox.StandardButton.Cancel)
    botoes = sorted(b.text().replace("&", "") for b in caixa.buttons())
    if botoes != ["Cancelar", "Salvar"]:
        print("AUTOVERIFICACAO FALHOU: os botoes padrao nao sairam em portugues")
        print("  obtido:", botoes)
        return 1

    janela = JanelaPrincipal()          # monta menus, barra e widgets
    janela.close()
    del aplicacao

    # A busca tambem entra na prova de vida: ela e' o unico caminho que
    # decodifica o documento inteiro, e um `exclude` que derrube o `re` ou o
    # codec so' apareceria aqui.
    from tfedit.busca import Criterio, proxima
    from tfedit.original import Original as _O
    from tfedit.pecas import Documento as _D

    pasta2 = pathlib.Path(tempfile.mkdtemp(prefix="tfedit-auto2-"))
    try:
        alvo2 = pasta2 / "busca.txt"
        alvo2.write_bytes("primeira\nsegunda com acao\nterceira\n"
                          .encode("utf-8"))
        orig2 = _O(alvo2)
        orig2.indexar()
        achado = proxima(_D(orig2), Criterio("SEGUNDA"), "utf-8", 0, 0)
        orig2.fechar()
        if achado is None or achado.linha != 1:
            print("AUTOVERIFICACAO FALHOU: a busca nao achou o esperado")
            return 1
    finally:
        import shutil as _sh
        _sh.rmtree(pasta2, ignore_errors=True)

    print(f"autoverificacao OK ({len(OBRIGATORIOS)} modulos, gravacao, "
          f"busca, traducao e janela)")
    return 0


def main() -> int:
    if "--autoverificacao" in sys.argv:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return autoverificacao()

    from PySide6.QtWidgets import QApplication

    from tfedit import APP, VERSAO, cli, configuracao, idioma, log_interno
    from tfedit.interface.janela_principal import JanelaPrincipal

    # O log e a captura de erro entram ANTES de qualquer widget: uma excecao na
    # montagem da janela e' justamente a que nao deixa rastro sem isto.
    log_interno.configurar()
    log_interno.instalar_captura_de_erros()
    log_interno.registrar_partida(VERSAO)

    aplicacao = QApplication(sys.argv)
    aplicacao.setApplicationName(APP)
    aplicacao.setApplicationVersion(VERSAO)
    # A traducao do Qt entra ANTES da primeira janela: os textos ja' montados
    # nao sao retraduzidos sozinhos.
    idioma.instalar(aplicacao)

    pedido = cli.analisar(sys.argv[1:])
    if pedido.ajuda:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, APP, cli.AJUDA.replace(chr(10), "<br>"))
        return 0

    janela = JanelaPrincipal(configuracao.carregar())
    janela.show()
    # Os arquivos da linha de comando entram DEPOIS de a janela aparecer: a
    # janela vazia surge na hora, e cada arquivo entra em seguida com a barra de
    # progresso da indexacao. Abrir antes deixaria o usuario olhando para a area
    # de trabalho sem sinal de vida.
    for caminho in pedido.arquivos:
        janela.abrir_arquivo(caminho)
    if pedido.linha and janela.aba_atual is not None:
        janela.aba_atual.editor.ir_para_linha(pedido.linha - 1)
    for bruto, motivo in pedido.recusados:
        log_interno.obter(__name__).warning("recusado %r: %s", bruto, motivo)
        janela.barra.showMessage(f"Ignorado: {bruto} — {motivo}", 8000)
    return aplicacao.exec()


if __name__ == "__main__":
    sys.exit(main())
