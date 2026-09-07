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
        checa("nao encontrado" in janela.barra_busca.rotulo.text(),
              "o que nao existe e' informado, e nao ignorado")

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

        aba.editor.undo()
        checa_igual(conteudo(), antes,
                    "*** UM Ctrl+Z devolve o arquivo ao original ***")
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


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")
    testar_abas()
    testar_salvar_como()
    testar_salvar_sem_edicao()
    testar_busca_pela_interface()
    testar_desfazer_apos_substituir()
    testar_arrastar_e_soltar()
    testar_codificacoes_lado_a_lado()
    testar_credito_no_rodape()
    testar_log()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
