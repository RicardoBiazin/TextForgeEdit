"""Abas, salvar como, arrastar-e-soltar, busca pela interface e log.

    .\\.venv\\Scripts\\python.exe tests\\teste_janela_principal.py

O que esta suite guarda:

1. **Uma aba por ARQUIVO.** Duas abas do mesmo arquivo produziriam duas versoes
   divergentes, e uma se perderia no primeiro salvamento.
2. **"Salvar como" nao destroi o original** e passa a apontar para o destino.
3. **Fechar aba com pendencia pergunta antes.**
4. **Cada aba tem a propria codificacao e o proprio indice** -- abrir um cp1252
   ao lado de um UTF-8 nao pode misturar os dois.

PULA inteira se o PySide6 nao estiver instalado.
"""

from __future__ import annotations

import pathlib
import sys

from ajudantes import (checa, checa_igual, pasta_temporaria, preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()


def esperar_indice(janela, limite_s: float = 60.0) -> bool:
    """Segura ate' TODAS as abas terminarem a varredura."""
    import time

    from PySide6.QtWidgets import QApplication

    limite = time.monotonic() + limite_s
    while time.monotonic() < limite:
        QApplication.processEvents()
        if all(not aba.indexando_agora for aba in janela.todas_as_abas()):
            for aba in janela.todas_as_abas():
                if aba.indexador is not None:
                    aba.indexador.wait(5_000)
            QApplication.processEvents()
            return True
        time.sleep(0.01)
    return False


def encerrar(janela) -> None:
    """Fecha a janela SEM passar pelo dialogo de "alteracoes nao salvas".

    `janela.close()` com uma aba modificada abre um `QMessageBox` modal -- e em
    modo offscreen nao ha' ninguem para clicar nele, entao a suite trava para
    sempre. Foi o que aconteceu na primeira versao desta suite. As abas sao
    removidas e encerradas direto, que e' o que o teste quer de fato: soltar o
    mmap e ir embora.
    """
    for aba in janela.todas_as_abas():
        janela.abas.removeTab(janela.abas.indexOf(aba))
        aba.encerrar()
    janela.close()


def gerar(pasta, nome: str, linhas: int, eol: bytes = b"\r\n",
          molde: str = "linha {n:08d} conteudo"):
    alvo = pasta / nome
    with open(alvo, "wb", buffering=1024 * 1024) as f:
        for lote in range(0, linhas, 50_000):
            f.write(b"".join(molde.format(n=i).encode() + eol
                             for i in range(lote, min(lote + 50_000, linhas))))
    return alvo


# ===========================================================================


def testar_abas() -> None:
    secao("Varias abas")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        um = gerar(tmp, "um.txt", 2_000)
        dois = gerar(tmp, "dois.txt", 3_000)

        janela = JanelaPrincipal()
        checa(janela.abrir_arquivo(str(um)), "abre o primeiro")
        checa(janela.abrir_arquivo(str(dois)), "abre o segundo")
        esperar_indice(janela)
        checa_igual(janela.abas.count(), 2, "duas abas")
        checa_igual(janela.aba_atual.nome, "dois.txt",
                    "a aba nova fica em foco")

        # Reabrir o mesmo arquivo NAO cria uma segunda aba.
        checa(janela.abrir_arquivo(str(um)), "reabrir o primeiro devolve True")
        checa_igual(janela.abas.count(), 2,
                    "*** mas nao cria aba nova: duas abas do mesmo arquivo "
                    "produziriam duas versoes divergentes ***")
        checa_igual(janela.aba_atual.nome, "um.txt",
                    "e foca a aba que ja' existia")

        # A caixa do caminho nao pode enganar: no Windows o mesmo arquivo chega
        # com caixa diferente pelo Explorer e pela forma curta 8.3.
        janela.abrir_arquivo(str(um).upper())
        checa_igual(janela.abas.count(), 2,
                    "*** nem com o caminho em CAIXA ALTA ***")

        # Cada aba tem o proprio documento e o proprio indice.
        a, b = janela.todas_as_abas()
        checa(a.documento is not b.documento, "documentos independentes")
        checa_igual(a.documento.total_de_linhas, 2_001, "linhas da primeira")
        checa_igual(b.documento.total_de_linhas, 3_001, "e da segunda")

        checa(not a.modificado, "a aba a fechar nao tem pendencia")
        checa(janela.fechar_aba(0), "fecha a primeira")
        checa_igual(janela.abas.count(), 1, "sobra uma")
        encerrar(janela)


def testar_salvar_como() -> None:
    secao("Salvar como")

    from PySide6.QtGui import QTextCursor

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        origem = gerar(tmp, "origem.txt", 1_000)
        intacto = origem.read_bytes()

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(origem))
        esperar_indice(janela)
        aba = janela.aba_atual

        aba.editor.ir_para_linha(5)
        cursor = aba.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        aba.editor.setTextCursor(cursor)
        aba.editor.insertPlainText(" EDITADO")

        destino = tmp / "copia.txt"
        checa(janela._gravar(aba, destino=str(destino)) is True,
              "grava no destino novo")

        checa_igual(origem.read_bytes(), intacto,
                    "*** o arquivo ORIGINAL nao foi tocado ***")
        checa(destino.exists(), "e a copia existe")
        checa(b" EDITADO" in destino.read_bytes(), "com a edicao dentro")
        checa_igual(aba.caminho, destino,
                    "*** e a aba passa a apontar para o destino: salvar de novo "
                    "grava na copia, e nao no original ***")
        checa(not aba.modificado, "sem pendencia depois de gravar")

        # Salvar de novo, com outra edicao, vai para a copia.
        aba.editor.ir_para_linha(9)
        cursor = aba.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        aba.editor.setTextCursor(cursor)
        aba.editor.insertPlainText(" SEGUNDA")
        janela._gravar(aba)
        checa(b" SEGUNDA" in destino.read_bytes(), "a segunda foi para a copia")
        checa_igual(origem.read_bytes(), intacto,
                    "e o original continua intocado")
        encerrar(janela)


def testar_salvar_sem_edicao() -> None:
    secao("Salvar sem editar nao reescreve")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "quieto.txt", 5_000)
        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        aba = janela.aba_atual

        marca = alvo.stat().st_mtime_ns
        checa_igual(aba.salvar(), 0,
                    "salvar sem pendencia devolve 0 bytes escritos")
        checa_igual(alvo.stat().st_mtime_ns, marca,
                    "*** e nao toca no arquivo: reescrever 240 MB a toa mexeria "
                    "ate' na data, e o backup acharia que mudou ***")
        encerrar(janela)


def testar_busca_pela_interface() -> None:
    secao("Localizar e substituir pela barra")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = tmp / "busca.txt"
        alvo.write_bytes(b"primeira com alvo\nsegunda\nterceira com alvo\n")

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        aba = janela.aba_atual

        janela.abrir_busca()
        # `isHidden()`, e nao `isVisible()`: num teste a janela de topo nunca e'
        # exibida, e em Qt um filho de janela nao mostrada NUNCA e' "visivel".
        # A pergunta certa e' se alguem escondeu a barra de proposito.
        checa(not janela.barra_busca.isHidden(), "Ctrl+F abre a barra")
        janela.barra_busca.campo.setText("alvo")
        janela.barra_busca._procurar(False)
        checa_igual(aba.editor.linha_atual_no_documento(), 0,
                    "acha a primeira ocorrencia")
        checa_igual(aba.editor.textCursor().selectedText(), "alvo",
                    "*** e SELECIONA o texto achado ***")

        janela.barra_busca._procurar(False)
        checa_igual(aba.editor.linha_atual_no_documento(), 2,
                    "F3 vai para a seguinte, e nao repete a mesma")

        janela.barra_busca._procurar(False)
        checa_igual(aba.editor.linha_atual_no_documento(), 0,
                    "e da' a volta")

        janela.barra_busca.campo.setText("naoexiste")
        janela.barra_busca._procurar(False)
        checa("não encontrado" in janela.barra_busca.rotulo.text(),
              "o que nao existe e' informado (com acento), e nao ignorado")

        # Substituir a atual so' troca se o selecionado for mesmo a ocorrencia.
        janela.barra_busca.campo.setText("alvo")
        janela.barra_busca.campo_troca.setText("MIRA")
        janela.barra_busca._procurar(False)
        janela.barra_busca._substituir()
        aba.editor.sincronizar()
        conteudo = aba.documento.ler(0, aba.documento.tamanho).decode("utf-8")
        checa("MIRA" in conteudo, "substituir a atual funciona")
        encerrar(janela)


def testar_desfazer_apos_substituir() -> None:
    secao("Ctrl+Z depois de substituir")

    from tfedit import busca
    from tfedit.busca import Criterio
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = tmp / "undo.txt"
        alvo.write_bytes(b"um alvo aqui\ndois alvo la\ntres alvo ali\n")
        antes = alvo.read_bytes()

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        aba = janela.aba_atual

        def conteudo():
            aba.editor.sincronizar()
            return aba.documento.ler(0, aba.documento.tamanho)

        # "Substituir todas" mexe direto na tabela de pecas e RECARREGA a fatia
        # -- e recarregar limpa a pilha do Qt. Era assim que o Ctrl+Z deixava de
        # funcionar: as edicoes existiam na tabela, e ninguem as consultava.
        busca.substituir_todas(aba.documento, Criterio("alvo"),
                               aba.perfil.codec, "MIRA")
        aba.editor.recarregar(aba.editor.linha_atual_no_documento())
        checa(b"MIRA" in conteudo(), "as trocas entraram")
        checa(not aba.editor.document().isUndoAvailable(),
              "a pilha do Qt esta' vazia depois do recarregar")
        checa(aba.editor.pode_desfazer,
              "*** mas o editor sabe que HA' o que desfazer: ele olha as duas "
              "pilhas ***")

        from PySide6.QtCore import Qt as _Qt
        aba.editor.setFocus()
        teclar(aba.editor, _Qt.Key.Key_Z, _Qt.KeyboardModifier.ControlModifier)
        checa_igual(conteudo(), antes,
                    "*** UM Ctrl+Z (a tecla) devolve o arquivo ao original ***")
        aba.editor.redo()
        checa(b"MIRA" in conteudo(), "e Ctrl+Y reaplica")

        # Digitar depois disso continua indo pela pilha do Qt, que e' a mais
        # recente e tem de ser consultada primeiro.
        aba.editor.undo()
        aba.editor.ir_para_linha(0)
        aba.editor.insertPlainText("XYZ ")
        checa(aba.editor.document().isUndoAvailable(),
              "digitar volta a alimentar a pilha do Qt")
        aba.editor.undo()
        checa("XYZ" not in aba.editor.toPlainText(),
              "*** e o Ctrl+Z desfaz a digitacao PRIMEIRO, por ser a mais "
              "recente ***")
        encerrar(janela)


def teclar(widget, tecla, modificador=None) -> None:
    """Envia uma tecla DE VERDADE ao widget, em vez de chamar o metodo.

    E' a diferenca que deixou passar um defeito real: `editor.undo()` funcionava
    e o Ctrl+Z nao. O `QPlainTextEdit` aceita o `ShortcutOverride` das teclas de
    edicao, entao a tecla chega no `keyPressEvent` DELE -- nunca no atalho do
    menu. Testar o metodo nao e' testar a tecla.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.keyClick(widget, tecla,
                   modificador or Qt.KeyboardModifier.NoModifier)


def testar_atalhos_de_busca() -> None:
    secao("Ctrl+F e Ctrl+H, pela TECLA")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = tmp / "atalhos.txt"
        alvo.write_bytes(b"um alvo aqui\ndois alvo la\n")

        janela = JanelaPrincipal()
        janela.show()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        editor = janela.aba_atual.editor
        barra = janela.barra_busca

        checa_igual(QKeySequence(QKeySequence.StandardKey.Replace).toString(),
                    "Ctrl+H", "o padrao de 'substituir' nesta plataforma")
        checa(barra.isHidden(), "a barra comeca escondida")

        # Ctrl+H com o termo VAZIO: o foco vai para o campo de cima, porque nao
        # ha' o que substituir enquanto nao se disser o que procurar.
        editor.setFocus()
        QApplication.processEvents()
        teclar(editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa(not barra.isHidden(),
              "*** Ctrl+H abre a barra -- ele nao existia, e a tecla nao fazia "
              "nada ***")
        checa(barra.campo.hasFocus(),
              "com o termo vazio, o foco comeca no campo de busca")

        # Com o termo preenchido, o Ctrl+H vai direto ao campo de troca.
        barra.hide()
        barra.campo.setText("alvo")
        editor.setFocus()
        QApplication.processEvents()
        teclar(editor, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa(barra.campo_troca.hasFocus(),
              "*** com o termo ja' preenchido, Ctrl+H foca o campo de troca ***")

        # Ctrl+F continua indo para o campo de busca.
        barra.hide()
        editor.setFocus()
        QApplication.processEvents()
        teclar(editor, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa(not barra.isHidden() and barra.campo.hasFocus(),
              "e Ctrl+F seguiu indo para o campo de busca")

        # Enter no campo de troca substitui, em vez de nao fazer nada.
        barra.campo.setText("alvo")
        barra.campo_troca.setText("MIRA")
        barra._procurar(False)
        barra.campo_troca.returnPressed.emit()
        janela.aba_atual.editor.sincronizar()
        conteudo = janela.aba_atual.documento.ler(
            0, janela.aba_atual.documento.tamanho).decode("utf-8")
        checa("MIRA" in conteudo,
              "*** Enter no campo de troca substitui: sem isso o gesto de "
              "'digitei o substituto, agora vai' ficava sem resposta ***")

        nomes = []
        for menu in janela.menuBar().actions():
            if menu.menu() and menu.text().replace("&", "") == "Localizar":
                nomes = [a.text().replace("&", "") for a in menu.menu().actions()
                         if a.text()]
        checa("Substituir..." in nomes,
              f"e ha' item de menu para descobrir o atalho: {nomes}")
        encerrar(janela)


def testar_ctrl_z_em_arquivo_grande() -> None:
    secao("Ctrl+Z (a TECLA) em arquivo grande")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QApplication

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        # Grande o bastante para a fatia DESLIZAR: e' o deslize que limpa a
        # pilha do Qt e leva o desfazer para a tabela de pecas. Num arquivo
        # pequeno o defeito nao aparece.
        alvo = gerar(tmp, "grande.txt", 60_000)

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        aba = janela.aba_atual
        editor = aba.editor
        checa(not editor.isReadOnly(),
              "com o indice completo, o editor sai do somente leitura")

        def linha(n):
            editor.sincronizar()
            return aba.documento.linha(n).decode("utf-8", "replace")

        original = linha(100)
        editor.ir_para_linha(100)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        editor.setTextCursor(cursor)
        editor.insertPlainText(" EDITADO")

        # Deslizar para longe consolida na tabela e ZERA a pilha do Qt.
        editor.ir_para_linha(50_000)
        editor.ir_para_linha(100)
        QApplication.processEvents()
        checa(" EDITADO" in linha(100), "a edicao esta' no documento")
        checa(not editor.document().isUndoAvailable(),
              "*** e a pilha do Qt esta' VAZIA depois do deslize ***")
        checa(aba.documento.pode_desfazer, "mas a tabela de pecas tem o registro")

        editor.setFocus()
        QApplication.processEvents()
        teclar(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa_igual(linha(100), original,
                    "*** apertar Ctrl+Z desfaz -- o QPlainTextEdit fica com a "
                    "tecla antes do menu, e sem interceptar no keyPressEvent "
                    "ele desfazia na pilha vazia dele ***")

        teclar(editor, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa(" EDITADO" in linha(100), "e Ctrl+Y refaz pela mesma via")

        # A tecla tem de continuar valendo para a pilha do Qt tambem, que e' a
        # mais recente: digitar e desfazer na MESMA fatia nao pode regredir.
        editor.ir_para_linha(200)
        antes_200 = linha(200)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        editor.setTextCursor(cursor)
        editor.insertPlainText(" NOVO")
        teclar(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        QApplication.processEvents()
        checa_igual(linha(200), antes_200,
                    "digitar e desfazer na mesma fatia continua indo pela "
                    "pilha do Qt")
        encerrar(janela)


def testar_arrastar_e_soltar() -> None:
    secao("Arrastar-e-soltar")

    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDropEvent

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        um = gerar(tmp, "arrastado.txt", 500)
        dois = gerar(tmp, "outro.txt", 500)

        janela = JanelaPrincipal()
        checa(janela.acceptDrops(), "a janela aceita drop")

        dados = QMimeData()
        dados.setUrls([QUrl.fromLocalFile(str(um)),
                       QUrl.fromLocalFile(str(dois)),
                       QUrl("https://exemplo.invalido/remoto.txt"),
                       QUrl.fromLocalFile(str(tmp))])
        evento = QDropEvent(QPoint(10, 10), Qt.DropAction.CopyAction, dados,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
        janela.dropEvent(evento)
        esperar_indice(janela)

        checa_igual(janela.abas.count(), 2,
                    "*** dois arquivos locais abriram; a URL remota e a PASTA "
                    "foram ignoradas em vez de darem erro ***")
        nomes = sorted(aba.nome for aba in janela.todas_as_abas())
        checa_igual(nomes, ["arrastado.txt", "outro.txt"], "os arquivos certos")
        encerrar(janela)


def testar_codificacoes_lado_a_lado() -> None:
    secao("Cada aba com a propria codificacao")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        utf = tmp / "utf.txt"
        utf.write_bytes("ação\ncoração\n".encode("utf-8"))
        cp = tmp / "cp.txt"
        cp.write_bytes(("ação e coração com muitos acentos ãéíóú çç\n" * 3)
                       .encode("cp1252"))

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(utf))
        janela.abrir_arquivo(str(cp))
        esperar_indice(janela)

        a, b = janela.todas_as_abas()
        checa_igual(a.perfil.codec, "utf-8", "a primeira e' UTF-8")
        checa(b.perfil.codec != "utf-8",
              f"*** e a segunda NAO herdou o codec da primeira "
              f"({b.perfil.codec}) ***")
        encerrar(janela)


def testar_credito_no_rodape() -> None:
    secao("Produzido por e versao, no rodape")

    from tfedit import APP, AUTOR, VERSAO
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        janela = JanelaPrincipal()

        texto = janela.credito.text()
        checa(AUTOR in texto, f"o rodape traz o autor: {texto!r}")
        checa(VERSAO in texto, "e a versao")
        checa("Produzido por" in texto, "com o rotulo pedido")

        dica = janela.credito.toolTip()
        checa(APP in dica and VERSAO in dica, "a dica repete nome e versao")

        # `addPermanentWidget`, e nao `addWidget`: os widgets NAO permanentes
        # dividem espaco com o `showMessage`, e o credito seria coberto ou
        # empurrado a cada "Salvo: arquivo.txt".
        janela.barra.showMessage("uma mensagem temporaria bem longa " * 3)
        checa_igual(janela.credito.text(), texto,
                    "*** e uma mensagem temporaria nao o apaga nem o troca ***")
        janela.barra.clearMessage()

        # Nem e' estado de documento: abrir e fechar a ultima aba deixa os
        # campos do arquivo vazios, e o credito continua.
        alvo = gerar(tmp, "credito.txt", 200)
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        checa(janela.rotulo_posicao.text() != "", "com arquivo aberto ha' posicao")
        janela.fechar_aba(0)
        checa_igual(janela.rotulo_posicao.text(), "",
                    "fechar a ultima aba limpa os campos do documento")
        checa_igual(janela.credito.text(), texto,
                    "*** mas NAO o credito: ele nao e' estado de arquivo "
                    "nenhum ***")

        checa(any(a.text().replace("&", "") == "Ajuda"
                  for a in janela.menuBar().actions()),
              "e existe o menu Ajuda, com o Sobre")
        encerrar(janela)


def testar_log() -> None:
    secao("O log")

    from ajudantes import appdata_temporario

    with appdata_temporario():
        import importlib

        from tfedit import log_interno
        importlib.reload(log_interno)

        log_interno.configurar()
        alvo = log_interno.caminho_do_log()
        log_interno.registrar_partida("0.0.0-teste")
        log = log_interno.obter("tfedit.prova")
        log.info("uma linha de prova")

        for tratador in __import__("logging").getLogger("tfedit").handlers:
            tratador.flush()

        checa(alvo.exists(), f"o log e' criado em {alvo.parent.name}")
        conteudo = alvo.read_text(encoding="utf-8", errors="replace")
        checa("uma linha de prova" in conteudo, "e recebe o que foi registrado")
        checa("0.0.0-teste" in conteudo,
              "*** com a versao na partida: sem ela, um log nao diz de qual "
              "build ele veio ***")

        # A captura de erro nao pode ser instalada duas vezes em cadeia
        # infinita nem derrubar nada.
        log_interno.instalar_captura_de_erros()
        log_interno.instalar_captura_de_erros()
        checa(True, "instalar a captura duas vezes nao quebra")



def testar_rodape_clicavel() -> None:
    secao("*** Linguagem e codificacao no rodape, e clicaveis ***")

    from PySide6.QtCore import Qt

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = tmp / "relatorio.sql"
        alvo.write_bytes("SELECT * FROM tabela;\r\n".encode("utf-8") * 40)

        janela = JanelaPrincipal()
        try:
            checa(janela.abrir_arquivo(str(alvo)), "abre o arquivo")

            # 1. O ESTADO ATUAL aparece nos dois campos.
            checa_igual(janela.rotulo_linguagem.text(), "SQL",
                        "*** o rodape mostra a linguagem ***")
            codec = janela.rotulo_codec.text()
            checa("UTF-8" in codec and "CRLF" in codec,
                  f"*** e a codificacao com o fim de linha: {codec!r} ***")

            # 2. Parecem clicaveis. Um rotulo de barra de status normalmente
            # nao faz nada ao ser clicado; sem a maozinha e a dica, ninguem
            # descobriria que estes fazem.
            for rotulo, nome in ((janela.rotulo_linguagem, "linguagem"),
                                 (janela.rotulo_codec, "codificacao")):
                checa_igual(rotulo.cursor().shape(),
                            Qt.CursorShape.PointingHandCursor,
                            f"o campo de {nome} tem cursor de maozinha")
                checa("lique" in rotulo.toolTip(),
                      f"e a dica convida a clicar: {rotulo.toolTip()!r}")

            # 3. Clicar abre o menu, com o mesmo conteudo do menu da barra.
            menu = janela._menu_no_rodape_linguagem()
            nomes = [a.text() for a in menu.actions()]
            checa(len(nomes) >= 20,
                  f"*** o clique na linguagem abre a lista ({len(nomes)}) ***")
            marcada = [a.text() for a in menu.actions() if a.isChecked()]
            checa_igual(marcada, ["SQL"], "com a atual marcada")
            menu.hide()

            menu = janela._menu_no_rodape_codificacao()
            submenus = sorted(a.menu().title().replace("&", "")
                              for a in menu.actions() if a.menu() is not None)
            checa_igual(submenus, ["Converter para", "Reinterpretar como"],
                        "*** e o clique na codificacao abre os dois verbos ***")
            menu.hide()

            # 4. Trocar PELO RODAPE muda de verdade, e o rotulo acompanha.
            janela._trocar_linguagem("Python")
            checa_igual(janela.rotulo_linguagem.text(), "Python",
                        "*** trocar pelo rodape atualiza o proprio rodape ***")
            checa_igual(janela.aba_atual.nome_da_linguagem, "Python",
                        "e a aba trocou de verdade")

            # 5. Sem arquivo, o menu explica em vez de quebrar.
            janela.fechar_aba(0)
            menu = janela._menu_no_rodape_codificacao()
            acoes = menu.actions()
            checa(len(acoes) == 1 and not acoes[0].isEnabled(),
                  "sem arquivo, o clique abre um menu que so' explica")
            menu.hide()
        finally:
            encerrar(janela)


def testar_menu_do_rodape_nao_trava() -> None:
    secao("*** O menu do rodape nao congela o laco de eventos ***")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "vivo.txt", 200)
        janela = JanelaPrincipal()
        try:
            checa(janela.abrir_arquivo(str(alvo)), "abre o arquivo")

            # `exec()` abre um laco de eventos ANINHADO e so' volta quando o
            # menu fecha. Num editor que indexa em thread e desliza a fatia,
            # congelar o laco principal por um menu de rodape e' pedir
            # problema. Se alguem trocar `popup` por `exec`, a chamada abaixo
            # NUNCA retorna: nao ha' quem feche o menu numa suite, e o runner
            # acusa a suite travada em vez de passar em silencio.
            menu = janela._menu_no_rodape_codificacao()
            checa(menu is not None,
                  "*** o metodo VOLTOU: `popup` e nao `exec` ***")
            checa(bool(menu.actions()),
                  f"e o menu veio preenchido ({len(menu.actions())} itens)")
            menu.hide()
        finally:
            encerrar(janela)



def testar_documento_novo() -> None:
    secao("*** Um documento novo, pronto para digitar ***")

    from tfedit.interface.aba import SemDestino
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        janela = JanelaPrincipal()
        try:
            checa_igual(janela.abas.count(), 0, "a janela comeca vazia")
            checa(janela.novo(), "novo() cria a aba")

            aba = janela.aba_atual
            checa_igual(janela.abas.count(), 1, "uma aba")
            checa_igual(aba.titulo, "Sem título 1", "com o nome provisorio")
            checa(aba.e_rascunho, "e ela se declara rascunho")
            checa(aba.rascunho_intocado, "intocado, porque ninguem digitou")

            # O arquivo de trabalho existe DE VERDADE: e' o que faz o documento
            # novo passar pelo mesmo codigo de um arquivo de 1 GB, em vez de um
            # caminho paralelo "sem arquivo" que iria divergir.
            checa(aba.caminho.is_file(),
                  f"*** ha' um arquivo de trabalho no disco: "
                  f"{aba.caminho.name} ***")
            checa_igual(aba.caminho.stat().st_size, 0, "e ele nasce vazio")
            checa(not aba.editor.isReadOnly(),
                  "*** e da' para digitar na hora ***")

            aba.editor.insertPlainText("primeira linha\n")
            aba.editor.sincronizar()
            checa(aba.modificado, "digitar marca como modificado")
            checa_igual(aba.titulo, "*Sem título 1", "com o asterisco")
            checa(not aba.rascunho_intocado, "e deixa de ser intocado")
        finally:
            encerrar(janela)


def testar_rascunho_nao_grava_escondido() -> None:
    secao("*** Ctrl+S num documento novo PERGUNTA onde salvar ***")

    from tfedit.interface.aba import SemDestino
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        janela = JanelaPrincipal()
        try:
            janela.novo()
            aba = janela.aba_atual
            aba.editor.insertPlainText("texto que nao pode sumir\n")
            aba.editor.sincronizar()

            # Gravar no arquivo de trabalho esconderia o texto numa pasta
            # interna, e a pessoa nunca mais o encontraria. A aba RECUSA, e
            # quem chama e' que pergunta o destino.
            levantou = False
            try:
                aba.salvar()
            except SemDestino:
                levantou = True
            checa(levantou,
                  "*** salvar sem destino e' recusado, e nao gravado numa "
                  "pasta interna ***")

            destino = tmp / "escolhido.txt"
            escritos = aba.salvar(destino)
            checa(escritos > 0, f"salvar com destino grava ({escritos} bytes)")
            checa_igual(destino.read_bytes(), b"texto que nao pode sumir\r\n",
                        "*** e o conteudo chega inteiro ao arquivo ***")
            checa(not aba.e_rascunho,
                  "*** depois de salvo, deixa de ser rascunho ***")
            checa_igual(aba.titulo, "escolhido.txt", "e passa a usar o nome real")
        finally:
            encerrar(janela)


def testar_rascunho_some_do_disco() -> None:
    secao("*** O arquivo de trabalho nao fica para tras ***")

    from tfedit.interface.aba import pasta_de_rascunhos
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        janela = JanelaPrincipal()
        janela.novo()
        aba = janela.aba_atual
        trabalho = aba.caminho
        checa(trabalho.is_file(), "o arquivo de trabalho existe")

        # Fechar a aba leva o arquivo junto. A ordem importa: no Windows o mmap
        # SEGURA o arquivo, e apagar antes de `fechar()` falharia.
        encerrar(janela)
        checa(not trabalho.exists(),
              "*** e some quando a aba fecha ***")

        # E o que sobrou de um fechamento anormal e' varrido -- so' o ANTIGO,
        # porque um rascunho recente pode ser de outra janela aberta agora.
        janela2 = JanelaPrincipal()
        try:
            janela2.novo()
            vivo = janela2.aba_atual.caminho
            velho = pasta_de_rascunhos() / "sem-titulo-9999-1.txt"
            velho.write_bytes(b"")
            import os
            import time
            antigo = time.time() - 30 * 86400
            os.utime(velho, (antigo, antigo))

            from tfedit.interface.aba import limpar_rascunhos_antigos
            limpar_rascunhos_antigos()
            checa(not velho.exists(),
                  "*** um rascunho de 30 dias e' varrido ***")
            checa(vivo.is_file(),
                  "*** e o da janela ABERTA agora nao e' tocado ***")
        finally:
            encerrar(janela2)


def testar_abrir_fecha_o_rascunho_vazio() -> None:
    secao("*** Abrir um arquivo some com o 'Sem titulo' vazio ***")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "real.txt", 50)
        janela = JanelaPrincipal()
        try:
            janela.novo()
            checa_igual(janela.abas.count(), 1, "so' o rascunho")

            checa(janela.abrir_arquivo(str(alvo)), "abre o arquivo")
            nomes = [janela.abas.widget(i).titulo
                     for i in range(janela.abas.count())]
            checa_igual(nomes, ["real.txt"],
                        "*** o rascunho VAZIO saiu: senao o editor acumularia "
                        "uma aba em branco por sessao ***")

            # Mas um rascunho em que alguem DIGITOU e' trabalho, e fica.
            janela.novo()
            janela.aba_atual.editor.insertPlainText("nao me feche")
            janela.aba_atual.editor.sincronizar()
            outro = gerar(tmp, "segundo.txt", 30)
            janela.abrir_arquivo(str(outro))
            nomes = [janela.abas.widget(i).titulo
                     for i in range(janela.abas.count())]
            checa(any("Sem título" in n for n in nomes),
                  f"*** e o rascunho COM texto sobrevive: {nomes} ***")
        finally:
            encerrar(janela)


def testar_menu_tem_novo() -> None:
    secao("O menu Arquivo tem Novo, com Ctrl+N")

    from PySide6.QtGui import QKeySequence
    from tfedit.interface.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal()
    try:
        arquivo = None
        for acao in janela.menuBar().actions():
            if "Arquivo" in acao.text():
                arquivo = acao.menu()
                break
        checa(arquivo is not None, "o menu Arquivo existe")
        if arquivo is None:
            return
        rotulos = [a.text() for a in arquivo.actions()]
        checa(any("Novo" in r for r in rotulos),
              f"*** e tem Novo: {rotulos[:3]} ***")
        novo = next(a for a in arquivo.actions() if "Novo" in a.text())
        checa_igual(novo.shortcut(),
                    QKeySequence(QKeySequence.StandardKey.New),
                    "com o atalho padrao do sistema (Ctrl+N)")
    finally:
        encerrar(janela)



def testar_a_janela_tem_icone() -> None:
    """A JANELA tem icone, e nao so' o arquivo no disco.

    O defeito, que durou treze versoes: o `.ico` estava embutido no .exe pelo
    PyInstaller desde o comeco -- por isso o Explorer sempre mostrou o icone
    certo -- mas `setWindowIcon` NUNCA foi chamado em lugar nenhum. O recurso
    do executavel so' vale para o shell; a janela que o Qt cria nasce sem icone
    ate' alguem dizer qual e'. Barra de titulo e barra de tarefas ficavam com o
    generico, num programa cujo arquivo tinha o icone certo -- e e' exatamente
    esse contraste que fez o defeito passar despercebido tanto tempo.

    Os testes de icone que ja' existiam conferiam o ARQUIVO (`teste_base.py`
    decodifica o .ico e mede os tracos). Nenhum perguntava se a janela usava.
    """
    secao("*** A janela tem icone ***")

    from tfedit import recursos
    from tfedit.interface.janela_principal import JanelaPrincipal

    icone = recursos.icone_do_aplicativo()
    checa(not icone.isNull(),
          "*** o Qt CONSEGUE ler o .ico: se o plugin `qico` faltasse no .exe, "
          "o icone sumiria so' na versao empacotada ***")
    tamanhos = sorted(s.width() for s in icone.availableSizes())
    checa(16 in tamanhos,
          f"*** e enxerga a versao de 16 px, que e' a da barra de titulo: "
          f"{tamanhos} ***")
    checa(256 in tamanhos, "e a de 256, para telas grandes")

    janela = JanelaPrincipal()
    try:
        da_janela = janela.windowIcon()
        checa(not da_janela.isNull(),
              "*** a JANELA tem icone -- durante treze versoes ela nao tinha, "
              "porque `setWindowIcon` nao era chamado em lugar nenhum ***")
        # E' o icone do programa, e nao um qualquer.
        mapa = da_janela.pixmap(32, 32).toImage()
        esperado = icone.pixmap(32, 32).toImage()
        checa(mapa == esperado, "e e' o icone do programa, nao outro")

        opacos = sum(1 for y in range(mapa.height())
                     for x in range(mapa.width())
                     if mapa.pixelColor(x, y).alpha() > 0)
        checa(opacos > 200,
              f"*** com {opacos} pixels desenhados a 32 px: um QIcon que "
              f"carrega mas vem vazio passaria em todo teste acima ***")
    finally:
        encerrar(janela)


def testar_o_app_define_o_icone_e_a_identidade() -> None:
    """O `app.py` faz as duas coisas, e na ORDEM certa.

    `setWindowIcon` sozinho nao basta no Windows: sem o AppUserModelID, a
    barra de tarefas agrupa a janela sob o processo que a criou -- `python.exe`
    quando se roda do fonte -- e mostra o icone do Python por mais correto que
    o `setWindowIcon` esteja. E a identidade tem de ser registrada ANTES da
    primeira janela: ela e' lida na criacao dela.
    """
    secao("*** O app.py define icone e identidade, nessa ordem ***")

    raiz = pathlib.Path(__file__).resolve().parent.parent
    fonte = (raiz / "app.py").read_text(encoding="utf-8")

    checa("setWindowIcon" in fonte, "o app.py define o icone da aplicacao")
    checa("SetCurrentProcessExplicitAppUserModelID" in fonte,
          "*** e registra o AppUserModelID: sem ele a barra de tarefas mostra "
          "o icone do Python ***")

    identidade = fonte.index("_identidade_no_windows()", fonte.index("def main"))
    aplicacao = fonte.index("QApplication(sys.argv)")
    checa(identidade < aplicacao,
          "*** e a identidade vem ANTES da QApplication: depois de a janela "
          "existir, o Windows ja' decidiu sob que icone agrupa-la ***")

def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")
    testar_abas()
    testar_salvar_como()
    testar_salvar_sem_edicao()
    testar_busca_pela_interface()
    testar_desfazer_apos_substituir()
    testar_atalhos_de_busca()
    testar_ctrl_z_em_arquivo_grande()
    testar_arrastar_e_soltar()
    testar_codificacoes_lado_a_lado()
    testar_credito_no_rodape()
    testar_rodape_clicavel()
    testar_menu_do_rodape_nao_trava()
    testar_documento_novo()
    testar_rascunho_nao_grava_escondido()
    testar_rascunho_some_do_disco()
    testar_abrir_fecha_o_rascunho_vazio()
    testar_menu_tem_novo()
    testar_log()
    testar_a_janela_tem_icone()
    testar_o_app_define_o_icone_e_a_identidade()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
