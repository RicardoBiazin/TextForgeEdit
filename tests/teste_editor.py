"""O editor deslizante e a janela principal: o caminho de ponta a ponta.

    .\\.venv\\Scripts\\python.exe tests\\teste_editor.py

Esta suite exercita o que as outras duas nao alcancam: o `QPlainTextEdit` de
verdade digitando no arquivo. E' o teste que prova a arquitetura inteira --
abrir, digitar com acento, deslizar para longe, voltar, e gravar.

A verificacao central e' a dos BYTES VIVOS. Num arquivo de 18 MB, digitar duas
frases tem de deixar dezenas de bytes na memoria, e nao megabytes. Se esse numero
crescer, a escrita de volta deixou de ser minima e a janela virou uma forma cara
de carregar o arquivo.

PULA inteira se o PySide6 nao estiver instalado.
"""

from __future__ import annotations

import sys

from ajudantes import (checa, checa_igual, pasta_temporaria, preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()


def esperar_indice(janela, limite_s: float = 60.0) -> bool:
    """Segura ate' a varredura em thread terminar.

    A abertura passou a ser ASSINCRONA: `abrir_arquivo` devolve com o arquivo
    ja' legivel, mas com a contagem de linhas ainda crescendo. Um teste que
    conferisse o total logo depois de abrir mediria o meio da varredura -- e foi
    exatamente o que aconteceu quando a thread entrou.
    """
    import time

    from PySide6.QtWidgets import QApplication

    limite = time.monotonic() + limite_s
    while time.monotonic() < limite:
        QApplication.processEvents()
        if janela.original is None or janela.original.indexacao_completa:
            if janela.indexador is not None:
                janela.indexador.wait(5_000)
            QApplication.processEvents()
            return True
        time.sleep(0.01)
    return False


def gerar(pasta, nome: str, linhas: int, eol: bytes = b"\r\n"):
    alvo = pasta / nome
    with open(alvo, "wb", buffering=1024 * 1024) as f:
        for lote in range(0, linhas, 50_000):
            f.write(b"".join(
                f"linha {i:08d} conteudo original do arquivo".encode() + eol
                for i in range(lote, min(lote + 50_000, linhas))))
    return alvo


def testar_ponta_a_ponta() -> None:
    secao("Abrir, digitar, deslizar, gravar")

    from PySide6.QtGui import QTextCursor

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        LINHAS = 200_000
        alvo = gerar(tmp, "grande.txt", LINHAS)
        tamanho = alvo.stat().st_size

        janela = JanelaPrincipal()
        checa(janela.abrir_arquivo(str(alvo)), "abre o arquivo")
        editor = janela.editor
        checa(editor.isReadOnly() or janela.original.indexacao_completa,
              "*** enquanto indexa, o editor fica somente leitura: editar "
              "antes daria contagem de linha errada ***")
        checa(esperar_indice(janela), "a varredura em thread termina")
        checa(not editor.isReadOnly(),
              "e ai' a edicao libera")
        checa_igual(janela.documento.total_de_linhas, LINHAS + 1,
                    "o total de linhas bate")

        # O widget so' pode ter a FATIA. Se ele tiver o arquivo inteiro, a
        # arquitetura falhou e a memoria vai junto.
        blocos = editor.document().blockCount()
        checa(blocos <= 5_001,
              f"*** o QPlainTextEdit tem {blocos} blocos -- a fatia, e nao as "
              f"{LINHAS + 1} linhas do arquivo ***")

        # Digitar de verdade, pelo caminho de entrada do Qt (com acento).
        editor.ir_para_linha(10)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        editor.setTextCursor(cursor)
        for caractere in " >> EDITADO: ação":
            editor.insertPlainText(caractere)
        editor.sincronizar()
        checa("ação" in janela.documento.linha(10).decode("utf-8", "replace"),
              "*** o texto digitado, com acento, chegou a' tabela de pecas ***")

        # Ir para longe desliza a fatia; editar la' e voltar preserva as duas.
        editor.ir_para_linha(150_000)
        recorte = editor.janela.recorte
        checa(recorte.primeira_linha > 100_000,
              f"deslizou para a fatia {recorte.primeira_linha}.."
              f"{recorte.ultima_linha}")
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock)
        editor.setTextCursor(cursor)
        editor.insertPlainText(" <<SEGUNDA>>")
        editor.sincronizar()
        longe = editor.linha_atual_no_documento()

        editor.ir_para_linha(10)
        checa("ação" in janela.documento.linha(10).decode("utf-8", "replace"),
              "*** a primeira edicao sobreviveu ao deslize de ida e volta ***")

        vivos = sum(p.tamanho for p in janela.documento.blocos()
                    if p.fonte == "adicionado")
        checa(vivos < 5_000,
              f"*** {vivos} bytes vivos na memoria para um arquivo de "
              f"{tamanho // (1024*1024)} MB ***")

        checa(janela.salvar(), "grava")
        disco = alvo.read_bytes()
        linhas = disco.split(b"\r\n")
        checa("ação".encode("utf-8") in linhas[10],
              "o disco tem a primeira edicao")
        checa(b"<<SEGUNDA>>" in linhas[longe], "e a segunda")
        checa_igual(linhas[11], b"linha 00000011 conteudo original do arquivo",
                    "*** a linha vizinha, que nunca foi editada, sai intacta ***")
        checa_igual(len(linhas), LINHAS + 1, "e o numero de linhas nao mudou")
        checa_igual(disco.count(b"\r\n"), LINHAS,
                    "*** o CRLF das 200 mil linhas foi preservado ***")

        checa(not janela.documento.alterado,
              "depois de gravar nao ha' pendencia")
        janela._fechar_atual()


def testar_sem_edicao_nao_grava() -> None:
    secao("Abrir e rolar sem editar nao altera o arquivo")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "intacto.txt", 30_000)
        antes = alvo.read_bytes()

        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        editor = janela.editor
        for linha in (0, 20_000, 5_000, 29_000, 0):
            editor.ir_para_linha(linha)
        editor.sincronizar()

        checa(not janela.documento.alterado,
              "*** rolar por todo o arquivo nao marca nada como alterado ***")
        janela.salvar()
        checa_igual(alvo.read_bytes(), antes,
                    "*** e o arquivo no disco nao mudou um byte ***")
        janela._fechar_atual()


def testar_margem_e_posicao() -> None:
    secao("A margem mostra a linha do DOCUMENTO")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "margem.txt", 100_000)
        janela = JanelaPrincipal()
        janela.abrir_arquivo(str(alvo))
        esperar_indice(janela)
        editor = janela.editor

        editor.ir_para_linha(60_000)
        checa_igual(editor.linha_atual_no_documento(), 60_000,
                    "*** a linha informada e' a do documento, e nao a da fatia "
                    "-- senao a linha 1 apareceria no meio do arquivo ***")
        checa(editor.textCursor().blockNumber() < 5_001,
              "enquanto o bloco dentro do widget e' pequeno")
        checa(editor.largura_da_margem() > 0,
              "e a margem tem largura para o maior numero do arquivo")
        janela._fechar_atual()


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")
    testar_ponta_a_ponta()
    testar_sem_edicao_nao_grava()
    testar_margem_e_posicao()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
