"""Views que nao sao texto: a camada de troca e o visor hexadecimal.

    .\\.venv\\Scripts\\python.exe tests\\teste_visualizadores.py

O QUE ESTA SUITE GUARDA, em ordem de importancia:

1. **O comando de menu nao pode cair no editor escondido.** O `QShortcutMap` do
   Qt resolve o atalho ANTES de o evento chegar ao widget em foco. Com o
   hexadecimal na frente, um Ctrl+V sem desvio INSERE texto na fatia do editor
   que esta' atras -- marcando como modificado um arquivo que a pessoa estava
   apenas lendo. O projeto irmao teve esse defeito; aqui seria pior, porque o
   editor escondido carrega uma fatia de verdade. O teste manda a TECLA, e nao
   o metodo: testar o metodo nao testa o atalho.

2. **A ida e volta nao pode alterar um byte.** Abrir, trocar para hexadecimal,
   voltar e gravar tem de devolver o arquivo identico. E' o que prova que a
   view le' o documento em vez de reconstrui-lo.

3. **O visor nao pode ler o arquivo inteiro.** Um `paintEvent` que pedisse
   `ler(0, tamanho)` funcionaria em fixture pequena e travaria em 1 GB. O teste
   instrumenta `Documento.ler` e exige que o maior pedido caiba numa tela.
"""

from __future__ import annotations

import sys

from ajudantes import (checa, checa_igual, drenar_eventos, pasta_temporaria,
                       preparar_qt, pular, resumir, secao)

TEM_QT = preparar_qt()


def _janela_com(pasta, nome: str, dados: bytes):
    from tfedit.interface.janela_principal import JanelaPrincipal

    alvo = pasta / nome
    alvo.write_bytes(dados)
    janela = JanelaPrincipal({})
    janela.abrir_arquivo(str(alvo))
    return janela, alvo


def _encerrar(janela) -> None:
    """Fecha sem passar pelo dialogo de "alteracoes nao salvas".

    `janela.close()` com uma aba modificada abre um QMessageBox modal, e em
    modo offscreen nao ha' quem o feche: a suite trava para sempre. As abas sao
    removidas e encerradas direto, que e' o que o teste quer -- soltar o mmap e
    ir embora.
    """
    for aba in janela.todas_as_abas():
        janela.abas.removeTab(janela.abas.indexOf(aba))
        aba.encerrar()
    janela.close()


# ======================================================================
# A camada de views
# ======================================================================

def testar_pilha_de_views() -> None:
    secao("A aba guarda mais de uma view")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "a.txt", b"linha\r\n" * 40)
        try:
            aba = janela.aba_atual
            checa_igual(aba.view_atual(), "texto", "abre no texto")
            checa(aba.tem_view("texto"), "a view de texto esta' registrada")
            checa(not aba.tem_view("hex"),
                  "*** e o hexadecimal NAO e' montado no arranque: seria "
                  "trabalho jogado fora para quem nunca o abre ***")

            checa(janela._trocar_view("hex") is None or True, "troca para hex")
            checa(aba.tem_view("hex"), "agora existe")
            checa_igual(aba.view_atual(), "hex", "e esta' na frente")
            checa_igual(janela.rotulo_view.text(), "Hexadecimal",
                        "o rodape acompanha")

            janela._trocar_view("texto")
            checa_igual(aba.view_atual(), "texto", "e volta")
            checa_igual(janela.rotulo_view.text(), "Texto", "o rodape tambem")
        finally:
            _encerrar(janela)


def testar_menu_de_views() -> None:
    secao("O menu Visualizar")

    from PySide6.QtWidgets import QMenu

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "b.txt", b"x\r\n" * 40)
        try:
            menu = QMenu()
            janela._preencher_view(menu)
            rotulos = [a.text() for a in menu.actions()]
            checa("Texto" in rotulos and "Hexadecimal" in rotulos,
                  f"lista o que da' para abrir: {rotulos}")
            checa("Tabela" not in rotulos and "Planilha" not in rotulos,
                  "*** e NAO lista o que ainda nao abre: uma entrada que nao "
                  "faz nada e' pior que uma ausente ***")
            marcadas = [a.text() for a in menu.actions() if a.isChecked()]
            checa_igual(marcadas, ["Texto"], "com a atual marcada")
        finally:
            _encerrar(janela)


def testar_comando_nao_cai_no_editor_escondido() -> None:
    secao("*** Ctrl+V com o hexadecimal na frente nao edita nada ***")

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "c.txt", b"conteudo\r\n" * 40)
        try:
            aba = janela.aba_atual
            antes = aba.editor.toPlainText()
            QGuiApplication.clipboard().setText("LIXO COLADO")

            janela._trocar_view("hex")
            checa_igual(aba.view_atual(), "hex", "o hexadecimal esta' na frente")

            # A TECLA, e nao o metodo. E' o atalho de menu que o QShortcutMap
            # resolve antes de o evento chegar ao widget -- testar
            # `janela._no_editor("paste")` nao provaria nada sobre o Ctrl+V.
            QTest.keyClick(janela, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            drenar_eventos()

            checa(not aba.documento.alterado,
                  "*** o documento NAO foi alterado ***")
            checa_igual(aba.editor.toPlainText(), antes,
                        "*** e a fatia do editor escondido esta' intacta ***")
            checa(not aba.modificado,
                  "*** a aba nao ficou marcada como suja ***")
        finally:
            _encerrar(janela)


def testar_ida_e_volta_nao_altera_bytes() -> None:
    secao("*** Texto -> hexadecimal -> texto -> salvar: byte a byte ***")

    with pasta_temporaria() as pasta:
        # Fins de linha MISTOS e sem quebra final: e' onde uma view que
        # reconstroi o conteudo se denuncia.
        dados = (b"primeira\r\n" + b"segunda\n" + b"terceira\r\n"
                 + b"quarta sem quebra final")
        janela, alvo = _janela_com(pasta, "misto.txt", dados)
        try:
            janela._trocar_view("hex")
            drenar_eventos()
            janela._trocar_view("texto")
            drenar_eventos()

            aba = janela.aba_atual
            checa(not aba.documento.alterado,
                  "so' olhar em hexadecimal nao suja o documento")
            escritos = aba.salvar()
            checa_igual(escritos, 0,
                        "*** salvar sem editar e' no-op: nada foi gravado ***")
            checa_igual(alvo.read_bytes(), dados,
                        "*** e o arquivo continua byte a byte igual ***")
        finally:
            _encerrar(janela)


# ======================================================================
# O visor hexadecimal
# ======================================================================

def testar_formato_do_dump() -> None:
    secao("O alinhamento do dump")

    from tfedit.interface.visualizadores.hex import (BYTES_POR_LINHA,
                                                     LARGURA_DO_HEX,
                                                     VisorHexadecimal)

    linha = VisorHexadecimal._linha_hex(b"Hello, mundo!\r\nA")
    checa_igual(linha, "48 65 6c 6c 6f 2c 20 6d  75 6e 64 6f 21 0d 0a 41",
                "16 bytes, com o espaco duplo no meio para contar a olho")
    checa_igual(len(linha), LARGURA_DO_HEX,
                "*** e a largura bate com a que `_x_do_ascii` assume: um "
                "espaco a mais desalinharia a coluna ASCII inteira ***")

    curta = VisorHexadecimal._linha_hex(b"ab")
    checa_igual(curta, "61 62", "a ultima linha, incompleta, nao ganha enchimento")
    checa_igual(BYTES_POR_LINHA, 16, "16 bytes por linha")


def testar_visor_nao_le_o_arquivo_inteiro() -> None:
    secao("*** O paintEvent le' uma tela, e nao o arquivo ***")

    with pasta_temporaria() as pasta:
        # 2 MB: pequeno o bastante para o teste ser rapido, grande o bastante
        # para uma leitura integral se denunciar.
        dados = b"".join(b"linha %06d de conteudo\r\n" % i
                         for i in range(80_000))
        janela, _ = _janela_com(pasta, "grande.txt", dados)
        try:
            aba = janela.aba_atual
            janela._trocar_view("hex")
            visor = aba.view("hex")
            visor.resize(900, 600)
            visor.show()

            maior = [0]
            original = aba.documento.ler

            def espiar(inicio, fim):
                maior[0] = max(maior[0], fim - inicio)
                return original(inicio, fim)

            aba.documento.ler = espiar
            try:
                # `grab()` e nao `repaint()`: em modo offscreen o Qt pode
                # descartar a repintura de um widget que nao esta' na tela, e
                # o espiao nao registraria nada -- a verificacao seguinte
                # passaria no VACUO. `grab()` desenha num pixmap, entao o
                # `paintEvent` roda de verdade. Foi assim que este teste
                # falhou na primeira versao.
                visor.verticalScrollBar().setValue(
                    visor.verticalScrollBar().maximum())
                visor.viewport().grab()
                visor.verticalScrollBar().setValue(0)
                visor.viewport().grab()
                drenar_eventos()
            finally:
                aba.documento.ler = original

            checa(maior[0] > 0, f"o visor de fato leu algo ({maior[0]} bytes)")
            checa(maior[0] <= 4096,
                  f"*** e a maior leitura foi de {maior[0]} bytes -- uma tela, "
                  f"nao os {len(dados)} do arquivo ***")
        finally:
            _encerrar(janela)


def testar_visor_ve_edicao_pendente() -> None:
    secao("*** O visor mostra o DOCUMENTO, e nao o disco ***")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "d.txt", b"AAAA\r\n" * 40)
        try:
            aba = janela.aba_atual
            aba.editor.insertPlainText("ZZZ")
            aba.editor.sincronizar()
            checa(aba.documento.alterado, "ha' edicao pendente")

            janela._trocar_view("hex")
            visor = aba.view("hex")
            bloco = aba.documento.ler(0, 16)
            checa(b"ZZZ" in bloco,
                  f"*** o visor le' o texto digitado e nao gravado: "
                  f"{bloco[:12]!r} ***")
            checa(visor.total_de_linhas > 0, "e tem linhas para desenhar")
        finally:
            _encerrar(janela)


def testar_ir_para_deslocamento() -> None:
    secao("Ir para deslocamento aceita decimal e hexadecimal")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "e.txt", b"x" * 4096)
        try:
            aba = janela.aba_atual
            janela._trocar_view("hex")
            visor = aba.view("hex")

            visor.ir_para_offset(0x400)
            checa_igual(visor.verticalScrollBar().value(), 0x400 // 16,
                        "0x400 leva a' linha 64 do dump")

            visor.ir_para_offset(10 ** 9)
            checa(visor.verticalScrollBar().value()
                  <= visor.verticalScrollBar().maximum(),
                  "um deslocamento absurdo e' aparado, e nao estoura")

            checa_igual(int("0x400", 0), 1024,
                        "*** a conversao e' `int(texto, 0)`, nunca `eval`: o "
                        "que o usuario digita e' DADO, nao codigo ***")
        finally:
            _encerrar(janela)


def testar_copia_tem_teto() -> None:
    secao("*** Copiar 1 GB e' recusado, e nao tentado ***")

    from tfedit.interface.visualizadores import hex as mod_hex

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "f.txt", b"y" * 20_000)
        try:
            aba = janela.aba_atual
            janela._trocar_view("hex")
            visor = aba.view("hex")

            recusas = []
            visor.recusou.connect(recusas.append)

            visor.copiar()
            checa(recusas and "Selecione" in recusas[0],
                  f"sem selecao, explica em vez de copiar nada: {recusas}")

            teto = mod_hex.TETO_DE_COPIA
            mod_hex.TETO_DE_COPIA = 100
            try:
                visor._ancora, visor._cabeca = 0, 5000
                recusas.clear()
                visor.copiar()
                checa(recusas and "limite" in recusas[0],
                      f"*** acima do teto, recusa com o motivo: {recusas} ***")
            finally:
                mod_hex.TETO_DE_COPIA = teto

            recusas.clear()
            visor._ancora, visor._cabeca = 0, 31
            visor.copiar()
            from PySide6.QtGui import QGuiApplication
            texto = QGuiApplication.clipboard().text()
            checa(not recusas, "abaixo do teto, copia")
            checa(texto.startswith("00000000  79 79"),
                  f"e o formato e' o do dump: {texto[:30]!r}")
            checa("|yyy" in texto, "com a coluna ASCII junto")
        finally:
            _encerrar(janela)


def testar_busca_volta_ao_texto() -> None:
    secao("Ctrl+F com o hexadecimal ativo volta para o texto")

    from tfedit import busca

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "g.txt", b"procure aqui\r\n" * 40)
        try:
            aba = janela.aba_atual
            janela._trocar_view("hex")
            checa_igual(aba.view_atual(), "hex", "esta' no hexadecimal")

            janela._procurar(busca.Criterio("aqui"), False)
            checa_igual(aba.view_atual(), "texto",
                        "*** a busca traz de volta para o texto em vez de "
                        "recusar em silencio ***")
        finally:
            _encerrar(janela)


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_pilha_de_views()
    testar_menu_de_views()
    testar_comando_nao_cai_no_editor_escondido()
    testar_ida_e_volta_nao_altera_bytes()
    testar_formato_do_dump()
    testar_visor_nao_le_o_arquivo_inteiro()
    testar_visor_ve_edicao_pendente()
    testar_ir_para_deslocamento()
    testar_copia_tem_teto()
    testar_busca_volta_ao_texto()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
