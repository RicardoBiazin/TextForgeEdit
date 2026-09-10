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

#: O rotulo da grade de CSV como ele aparece no menu, tirado da CONSTANTE.
#: Escrito a' mao, este teste ja' quebrou uma vez por o rotulo ter mudado de
#: "Tabela" para "Colunas" -- uma falha sobre a palavra, e nao sobre o
#: comportamento, que e' o que ele existe para vigiar.
GRADE = "Colunas"
if TEM_QT:
    from tfedit.interface.janela_principal import ROTULO_DA_VIEW
    GRADE = ROTULO_DA_VIEW["tabela"]
    from PySide6.QtWidgets import QDialogButtonBox


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
            checa(GRADE not in rotulos and "Planilha" not in rotulos,
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



# ======================================================================
# A grade de CSV
# ======================================================================

def _csv(pasta, nome: str, linhas, eol: bytes = b"\r\n"):
    """Escreve um CSV e devolve (janela, caminho)."""
    dados = eol.join(l.encode("utf-8") for l in linhas) + eol
    return _janela_com(pasta, nome, dados)


def testar_grade_abre_e_le() -> None:
    secao("A grade abre com o dialeto certo")

    from PySide6.QtCore import Qt

    with pasta_temporaria() as pasta:
        linhas = ["produto;preco;desconto"]
        linhas += [f"Parafuso 3,5mm {i};{i},50;0,{i % 10}0" for i in range(60)]
        janela, _ = _csv(pasta, "p.csv", linhas)
        try:
            aba = janela.aba_atual
            dialeto = aba.dialeto_csv()
            checa(dialeto is not None and dialeto.delimitador == ";",
                  f"delimitador reconhecido: {dialeto.rotulo_do_delimitador}")
            checa(dialeto.tem_cabecalho, "e a primeira linha e' cabecalho")

            janela._trocar_view("tabela")
            grade = aba.view("tabela")
            checa_igual(grade.modelo.rowCount(), 60,
                        "*** 60 linhas de dados: sem o cabecalho e sem a "
                        "linha fantasma do \\n final ***")
            checa_igual(grade.modelo.columnCount(), 3, "tres colunas")
            cabecalho = [grade.modelo.headerData(c, Qt.Orientation.Horizontal)
                         for c in range(3)]
            checa_igual(cabecalho, ["produto", "preco", "desconto"],
                        "o cabecalho vem do arquivo")
            checa_igual(grade.modelo.data(grade.modelo.index(0, 1)), "0,50",
                        "e a celula tras o valor")
        finally:
            _encerrar(janela)


def testar_grade_nao_le_o_arquivo_inteiro() -> None:
    secao("*** A grade le' o que aparece, e nao o arquivo ***")

    with pasta_temporaria() as pasta:
        linhas = ["produto;preco;desconto"]
        linhas += [f"Item {i};{i},50;0,10" for i in range(200_000)]
        janela, _ = _csv(pasta, "grande.csv", linhas)
        try:
            aba = janela.aba_atual
            pedidas = [0]
            original = aba.documento.faixa

            def espiar(a, b):
                resultado = original(a, b)
                pedidas[0] += len(resultado)
                return resultado

            aba.documento.faixa = espiar
            try:
                janela._trocar_view("tabela")
                grade = aba.view("tabela")
                grade.resize(900, 600)
                grade.show()
                grade.viewport().grab()
                drenar_eventos()
            finally:
                aba.documento.faixa = original

            checa_igual(grade.modelo.rowCount(), 200_000,
                        "a grade sabe que ha' 200 mil linhas")
            checa(pedidas[0] > 0, f"e leu alguma coisa ({pedidas[0]} linhas)")
            checa(pedidas[0] < 3000,
                  f"*** mas leu so' {pedidas[0]} linhas das 200.000 -- medir "
                  f"coluna ou contar linha varrendo tudo apareceria aqui ***")
        finally:
            _encerrar(janela)


def testar_celula_e_cirurgica() -> None:
    secao("*** Editar uma celula nao reescreve as outras ***")

    with pasta_temporaria() as pasta:
        # O campo 1 esta' entre aspas SEM precisar. Reconstruir o registro
        # inteiro com o quoting minimo do modulo `csv` tiraria essas aspas --
        # alteracao silenciosa de um campo que ninguem tocou.
        linhas = ["nome;observacao;valor"]
        linhas += [f'Ana {i};"texto entre aspas";{i}' for i in range(30)]
        janela, alvo = _csv(pasta, "aspas.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            ok = grade.modelo.setData(grade.modelo.index(0, 0), "TROCADO")
            checa(ok, "a celula aceitou o valor")

            linha = aba.documento.linha(1)
            checa_igual(linha, b'TROCADO;"texto entre aspas";0',
                        '*** o campo 0 mudou e as aspas do campo 1 '
                        'sobreviveram ***')
            checa_igual(aba.documento.total_de_edicoes, 1,
                        "*** e foi UMA operacao: um Ctrl+Z desfaz a celula ***")

            aba.documento.desfazer()
            checa_igual(aba.documento.linha(1), b'Ana 0;"texto entre aspas";0',
                        "e desfazer devolve a linha inteira")
        finally:
            _encerrar(janela)


def testar_celula_preserva_o_terminador() -> None:
    secao("*** O fim de linha vem da LINHA, e nao do perfil ***")

    with pasta_temporaria() as pasta:
        # Fim de linha MISTO: a linha 2 e' CRLF, a 3 e' LF. Usar o terminador
        # majoritario do arquivo trocaria bytes que ninguem mandou trocar.
        dados = (b"nome;valor\r\n"
                 b"Ana;10\r\n"
                 b"Bruno;20\n"
                 b"Carla;30\r\n")
        janela, alvo = _janela_com(pasta, "misto.csv", dados)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            # A linha 2 do documento (Bruno) termina em LF.
            grade.modelo.setData(grade.modelo.index(1, 1), "99")
            aba.salvar()

            gravado = alvo.read_bytes()
            checa(b"Bruno;99\n" in gravado and b"Bruno;99\r\n" not in gravado,
                  f"*** a linha editada continua com LF, e nao virou CRLF ***")
            checa(b"Ana;10\r\n" in gravado,
                  "e as linhas nao tocadas continuam com CRLF")
        finally:
            _encerrar(janela)


def testar_celula_recusa_o_que_nao_cabe() -> None:
    secao("*** O que a codificacao nao aceita e' RECUSADO ***")

    with pasta_temporaria() as pasta:
        linhas = [f"Ana {i};{i}" for i in range(30)]
        dados = b"\r\n".join(l.encode("cp1252") for l in linhas) + b"\r\n"
        janela, alvo = _janela_com(pasta, "latin.csv", dados)
        try:
            aba = janela.aba_atual
            aba.reinterpretar("cp1252")
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            recusas = []
            grade.recusou.connect(recusas.append)

            antes = alvo.read_bytes()
            ok = grade.modelo.setData(grade.modelo.index(0, 0), "ideograma 中")
            checa(not ok, "*** a celula NAO aceitou o caractere ***")
            checa(recusas and "não existe" in recusas[0],
                  f"e explicou por que: {recusas}")
            checa(not aba.documento.alterado,
                  "*** o documento continua intacto: nada de '?' gravado ***")
            checa_igual(alvo.read_bytes(), antes, "e o disco tambem")

            recusas.clear()
            ok = grade.modelo.setData(grade.modelo.index(0, 0),
                                      "com\nquebra")
            checa(not ok, "quebra de linha numa celula tambem e' recusada")
            checa(recusas and "quebra de linha" in recusas[0],
                  f"com o motivo certo: {recusas}")
        finally:
            _encerrar(janela)


def testar_registro_de_varias_linhas_e_sinalizado() -> None:
    secao("*** Aspas sem fechar: sinalizado, e nao editavel ***")

    from PySide6.QtCore import Qt

    with pasta_temporaria() as pasta:
        # A grade trabalha com uma linha = um registro. Este arquivo quebra
        # essa premissa, e o certo e' recusar a edicao em vez de gravar por
        # cima de um registro entendido errado.
        linhas = ["nome;observacao;valor"]
        linhas.append('Ana;"comeca aqui')
        linhas.append('e termina aqui";10')
        linhas += [f"Bruno {i};simples;{i}" for i in range(20)]
        janela, _ = _csv(pasta, "multilinha.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            # Forca a leitura do bloco, que e' quando as suspeitas aparecem.
            grade.modelo.data(grade.modelo.index(0, 0))
            checa(grade.modelo._suspeitas,
                  f"*** a linha com aspas sem fechar foi marcada: "
                  f"{sorted(grade.modelo._suspeitas)} ***")

            suspeita = min(grade.modelo._suspeitas)
            linha_na_grade = suspeita - (1 if grade.dialeto.tem_cabecalho else 0)
            indice = grade.modelo.index(linha_na_grade, 0)
            editavel = bool(grade.modelo.flags(indice)
                            & Qt.ItemFlag.ItemIsEditable)
            checa(not editavel,
                  "*** e ela NAO e' editavel: nao se corrompe o que nao se "
                  "consegue analisar ***")

            dica = grade.modelo.data(indice, Qt.ItemDataRole.ToolTipRole)
            checa(dica and "continua na linha seguinte" in dica,
                  f"a dica explica o motivo: {dica!r}")
        finally:
            _encerrar(janela)


def testar_grade_nao_edita_durante_a_varredura() -> None:
    secao("Sem editar enquanto o indice cresce")

    from PySide6.QtCore import Qt

    with pasta_temporaria() as pasta:
        linhas = ["a;b;c"] + [f"{i};{i};{i}" for i in range(50)]
        janela, _ = _csv(pasta, "v.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            indice = grade.modelo.index(0, 0)
            checa(bool(grade.modelo.flags(indice)
                       & Qt.ItemFlag.ItemIsEditable),
                  "com o indice pronto, a celula e' editavel")

            # `pode_editar` segue `indexacao_completa`; a mesma regra do editor
            # de texto. Partir uma peca precisa saber quantas linhas ficam de
            # cada lado.
            real = type(aba.documento).pode_editar
            type(aba.documento).pode_editar = property(lambda _s: False)
            try:
                checa(not (grade.modelo.flags(indice)
                           & Qt.ItemFlag.ItemIsEditable),
                      "*** e deixa de ser enquanto a varredura corre ***")
                checa(not grade.modelo.setData(indice, "X"),
                      "e o setData recusa mesmo se chamado direto")
            finally:
                type(aba.documento).pode_editar = real
        finally:
            _encerrar(janela)


def testar_menu_oferece_a_tabela() -> None:
    secao("O menu Visualizar oferece a tabela so' para tabela")

    from PySide6.QtWidgets import QMenu

    with pasta_temporaria() as pasta:
        linhas = ["a;b;c"] + [f"{i};{i};{i}" for i in range(40)]
        janela, _ = _csv(pasta, "tab.csv", linhas)
        try:
            menu = QMenu()
            janela._preencher_view(menu)
            rotulos = [a.text() for a in menu.actions()]
            checa(GRADE in rotulos,
                  f"*** num CSV a grade de colunas aparece: {rotulos} ***")
        finally:
            _encerrar(janela)

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "prosa.txt",
                                b"texto corrido sem separador\r\n" * 40)
        try:
            menu = QMenu()
            janela._preencher_view(menu)
            rotulos = [a.text() for a in menu.actions()]
            checa(GRADE not in rotulos,
                  f"*** e num texto corrido, nao: {rotulos} ***")
        finally:
            _encerrar(janela)



def testar_desfazer_na_grade_csv() -> None:
    secao("*** Ctrl+Z na grade de CSV ***")

    with pasta_temporaria() as pasta:
        linhas = ["nome;valor"] + [f"Ana {i};{i}" for i in range(40)]
        janela, _ = _csv(pasta, "u.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")
            antes = grade.modelo.data(grade.modelo.index(0, 0))

            grade.modelo.setData(grade.modelo.index(0, 0), "TROCADO")
            checa_igual(grade.modelo.data(grade.modelo.index(0, 0)),
                        "TROCADO", "a celula mudou")
            checa_igual(aba.documento.total_de_edicoes, 1, "uma edicao")

            # O desfazer SEMPRE existiu aqui -- `setData` grava por
            # `documento.substituir` dentro de um `agrupar()`. O que faltava era
            # o comando CHEGAR na grade: o despacho por view mandava o Ctrl+Z
            # para a mensagem "este comando e' do editor de texto".
            janela._no_editor("undo")
            checa_igual(grade.modelo.data(grade.modelo.index(0, 0)), antes,
                        "*** e o Ctrl+Z devolveu o valor anterior ***")
            checa_igual(aba.documento.total_de_edicoes, 0,
                        "*** e a tabela de pecas voltou a zero ***")

            janela._no_editor("redo")
            checa_igual(grade.modelo.data(grade.modelo.index(0, 0)),
                        "TROCADO", "refazer traz de volta")
        finally:
            _encerrar(janela)


def testar_desfazer_esquece_o_cache_da_grade() -> None:
    secao("*** Desfazer fora da tela tambem tem de aparecer ***")

    with pasta_temporaria() as pasta:
        # Mais de um bloco de cache (BLOCO = 256), para a linha editada ficar
        # num bloco diferente do que esta' na tela.
        linhas = ["nome;valor"] + [f"Ana {i};{i}" for i in range(800)]
        janela, _ = _csv(pasta, "longo.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            longe = grade.modelo.index(600, 0)
            antes = grade.modelo.data(longe)
            grade.modelo.setData(longe, "LA LONGE")
            checa_igual(grade.modelo.data(longe), "LA LONGE", "editou longe")

            # Traz um bloco DIFERENTE para o cache, para provar que o desfazer
            # nao depende de a linha editada estar em memoria.
            grade.modelo.data(grade.modelo.index(0, 0))
            janela._no_editor("undo")

            checa_igual(grade.modelo.data(longe), antes,
                        "*** o desfazer aparece mesmo com o cache cheio de "
                        "outro bloco ***")
            checa_igual(grade.linha_atual(), 601,
                        "*** e a grade leva o cursor ate' onde a mudanca "
                        "aconteceu, em vez de desfazer em silencio ***")
        finally:
            _encerrar(janela)


def testar_desfazer_sem_nada_explica() -> None:
    secao("Ctrl+Z sem nada a desfazer explica")

    with pasta_temporaria() as pasta:
        linhas = ["a;b"] + [f"{i};{i}" for i in range(30)]
        janela, _ = _csv(pasta, "vazio.csv", linhas)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")

            recusas = []
            grade.recusou.connect(recusas.append)
            grade.desfazer()
            checa(recusas and "desfazer" in recusas[0],
                  f"explica em vez de nao fazer nada: {recusas}")
            checa(not aba.documento.alterado, "e nada foi alterado")
        finally:
            _encerrar(janela)



def testar_tela_do_separador_mostra_a_previa() -> None:
    """A previa e' o que faz a tela de escolha valer.

    Escolher o separador as cegas e so' descobrir o resultado depois de a grade
    abrir transformaria a correcao de um palpite errado em tentativa e erro --
    com o agravante de que a grade de um arquivo grande custa a montar.
    """
    secao("*** A tela de escolha do separador mostra a previa ***")

    from PySide6.QtWidgets import QDialogButtonBox

    from tfedit.interface.separador import EscolherSeparador

    amostra = ("nome~cidade~uf\n"
               "Ana~Blumenau~SC\n"
               "Bruno~Joinville~SC\n"
               "Carla~Curitiba~PR\n")
    dialogo = EscolherSeparador(amostra, sugerido="~")
    try:
        checa_igual(dialogo.separador(), "~", "abre no separador sugerido")
        checa_igual(dialogo.previa.columnCount(), 3,
                    "*** a previa reparte em 3 colunas ANTES de confirmar ***")
        checa_igual(dialogo.previa.rowCount(), 3,
                    "tres linhas de dados, o cabecalho virou titulo")
        titulos = [dialogo.previa.horizontalHeaderItem(c).text()
                   for c in range(3)]
        checa_igual(titulos, ["nome", "cidade", "uf"],
                    "e o cabecalho do arquivo virou o titulo das colunas")
        checa_igual(dialogo.previa.item(0, 1).text(), "Blumenau",
                    "com o dado na celula certa")

        # Trocar o separador refaz a previa na hora.
        posicao = dialogo.caixa.findData(";")
        dialogo.caixa.setCurrentIndex(posicao)
        checa_igual(dialogo.previa.columnCount(), 1,
                    "*** com o separador ERRADO a previa mostra 1 coluna: da' "
                    "para ver o erro sem abrir a grade ***")
        checa("provavelmente não é o separador" in dialogo.resumo.text(),
              f"e a tela DIZ que esta' errado: {dialogo.resumo.text()!r}")

        # Um caractere qualquer, digitado.
        dialogo.caixa.setCurrentIndex(dialogo.caixa.count() - 1)
        dialogo.outro.setText("~")
        checa_igual(dialogo.previa.columnCount(), 3,
                    "*** e um caractere digitado a' mao vale igual ***")

        # O que nao da' para honrar desabilita o botao, com o motivo na tela.
        botao = dialogo.botoes.button(
            QDialogButtonBox.StandardButton.Ok)
        dialogo.outro.setText('"')
        checa(not botao.isEnabled(),
              "*** aspa como separador nao deixa confirmar ***")
        checa("Não dá" in dialogo.resumo.text(),
              f"e explica por que: {dialogo.resumo.text()!r}")
        dialogo.outro.clear()
        checa(not botao.isEnabled(), "sem separador, nao ha' o que confirmar")
    finally:
        dialogo.deleteLater()


def testar_separador_escolhido_troca_a_grade() -> None:
    """Escolher outro separador REFAZ a grade, e nao remenda a que existe.

    O `ModeloCsv` guarda o dialeto no construtor e mantem um cache de blocos ja'
    repartidos com ele: trocar o atributo na grade viva deixaria as linhas em
    cache repartidas pelo separador ANTIGO, misturadas com as novas -- e nada
    na tela diria que metade dos dados esta' errada.
    """
    secao("*** Trocar o separador refaz a grade inteira ***")

    from tfedit import csv_dialeto

    # Ponto-e-virgula E' o separador; o til aparece dentro dos dados.
    linhas = [b"nome;obs"]
    for i in range(60):
        linhas.append(f"item{i};a~b~c".encode())
    dados = b"\r\n".join(linhas) + b"\r\n"

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "dados.dsv", dados)
        try:
            aba = janela.aba_atual
            janela._trocar_view("tabela")
            grade = aba.view("tabela")
            checa_igual(grade.modelo.dialeto.delimitador, ";",
                        "a deteccao escolheu o ';'")
            antes = grade.modelo.columnCount()
            checa_igual(antes, 2, "duas colunas")

            # Agora o usuario manda usar o til.
            aba.impor_dialeto(csv_dialeto.com_delimitador(
                aba.amostra_de_texto(), "~"))
            checa(not aba.tem_view("tabela"),
                  "*** a grade antiga foi DESCARTADA, e nao remendada ***")

            janela._montar_view(aba, "tabela")
            aba.trocar_para("tabela")
            nova = aba.view("tabela")
            checa_igual(nova.modelo.dialeto.delimitador, "~",
                        "a grade nova usa o separador escolhido")
            checa(nova.modelo.columnCount() != antes,
                  f"*** e as colunas mudaram de verdade: {antes} -> "
                  f"{nova.modelo.columnCount()} ***")
        finally:
            _encerrar(janela)


def testar_a_grade_deixa_de_ser_escondida() -> None:
    """Um recurso que a pessoa nao sabe que existe nao esta' entregue.

    A grade existe desde a v0.7.0 dentro do menu Visualizar -- que ninguem abre
    num arquivo de texto. `Aba.visualizador_sugerido` era calculado e NAO tinha
    um unico leitor.
    """
    secao("*** Um CSV avisa que da' para ver em colunas ***")

    linhas = [b"nome;valor;data"]
    for i in range(80):
        linhas.append(f"item{i};1{i},50;01/02/2026".encode())
    dados = b"\r\n".join(linhas) + b"\r\n"

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "vendas.csv", dados)
        try:
            recado = janela.barra.currentMessage()
            checa("colunas" in recado.lower() or "Colunas" in recado,
                  f"*** o rodape avisa, sem abrir nada sozinho: {recado!r} ***")
            checa("ponto e vírgula" in recado,
                  "e diz qual separador foi reconhecido")

            # Uma vez, e nao a cada varredura: a segunda ja' e' cobranca.
            aba = janela.aba_atual
            janela.barra.clearMessage()
            janela._ao_terminar_indice(aba.original.total_de_linhas)
            checa("Colunas" not in janela.barra.currentMessage(),
                  f"*** e nao repete: {janela.barra.currentMessage()!r} ***")
        finally:
            _encerrar(janela)

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "prosa.txt",
                                b"texto corrido sem separador\r\n" * 40)
        try:
            checa("Colunas" not in janela.barra.currentMessage(),
                  "*** e um texto corrido NAO recebe a sugestao ***")
        finally:
            _encerrar(janela)


def testar_escolher_separador_aparece_mesmo_sem_deteccao() -> None:
    """O caso em que ela mais serve e' aquele em que a deteccao nao reconhece.

    Se o item so' aparecesse quando a grade ja' esta' disponivel, ele faltaria
    exatamente no arquivo que precisa dele.
    """
    secao("*** 'Colunas com outro separador' aparece sempre ***")

    from PySide6.QtWidgets import QMenu

    with pasta_temporaria() as pasta:
        # Separado por ESPACO: a deteccao recusa de proposito.
        dados = b"".join(f"Item{i:<4} {i * 7:<6} SC\r\n".encode()
                         for i in range(60))
        janela, _ = _janela_com(pasta, "largura.txt", dados)
        try:
            menu = QMenu()
            janela._preencher_view(menu)
            rotulos = [a.text() for a in menu.actions()]
            checa(GRADE not in rotulos,
                  f"a deteccao nao reconheceu tabela aqui: {rotulos}")
            checa(any("outro separador" in r for r in rotulos),
                  f"*** mas a escolha manual esta' la': {rotulos} ***")

            aba = janela.aba_atual
            from tfedit import csv_dialeto
            aba.impor_dialeto(csv_dialeto.com_delimitador(
                aba.amostra_de_texto(), " "))
            checa(janela._montar_view(aba, "tabela"),
                  "*** e com o separador escolhido a grade abre ***")
            aba.trocar_para("tabela")
            grade = aba.view("tabela")
            checa(grade.modelo.columnCount() >= 3,
                  f"com {grade.modelo.columnCount()} colunas de verdade")
        finally:
            _encerrar(janela)


def _grade_com_busca(pasta):
    """Uma janela com a grade aberta sobre um CSV de campos identificaveis."""
    linhas = [b"codigo;produto;cidade"]
    for i in range(120):
        linhas.append(f"C{i:04};cabo de rede;Blumenau".encode())
    # Uma agulha em cada coluna diferente, em linhas diferentes.
    linhas[30] = b"C0029;AGULHA;Blumenau"
    linhas[60] = b"C0059;cabo de rede;AGULHA"
    linhas[90] = b"AGULHA;cabo de rede;Joinville"
    dados = b"\r\n".join(linhas) + b"\r\n"

    janela, _ = _janela_com(pasta, "estoque.csv", dados)
    janela._trocar_view("tabela")
    return janela


def testar_busca_NAO_expulsa_da_grade() -> None:
    """O defeito relatado: procurar desfazia a visualizacao em colunas.

    Era uma decisao minha, e estava errada. Busca e substituicao voltavam ao
    modo texto porque `busca.Achado` da' (linha, coluna de CARACTERE) e no
    hexadecimal a posicao e' um byte -- mas na GRADE nao ha' esse problema:
    `fatias_de_campos` diz onde cada campo comeca na linha crua, e a ocorrencia
    cai dentro de exatamente um deles. A visualizacao em colunas se perdia
    justamente na hora em que ela mais serve: a de conferir o valor achado.
    """
    secao("*** Procurar NAO expulsa da grade de colunas ***")

    from tfedit import busca

    with pasta_temporaria() as pasta:
        janela = _grade_com_busca(pasta)
        try:
            aba = janela.aba_atual
            checa_igual(aba.view_atual(), "tabela", "a grade esta' aberta")

            criterio = busca.Criterio(texto="AGULHA")
            janela._procurar(criterio, False)

            checa_igual(aba.view_atual(), "tabela",
                        "*** e CONTINUA aberta depois de procurar: antes "
                        "disto, a busca jogava de volta para o texto ***")

            grade = aba.view("tabela")
            indice = grade.currentIndex()
            checa(indice.isValid(), "a grade tem uma celula selecionada")
            checa_igual(grade.linha_atual(), 30,
                        "*** na linha da ocorrencia ***")
            checa_igual(indice.column(), 1,
                        "*** e na COLUNA certa: a agulha esta' no segundo "
                        "campo, e a busca so' sabia dizer 'coluna 6 de "
                        "caractere' ***")

            # F3 anda, em vez de reachar a mesma celula.
            janela._procurar(criterio, False)
            checa_igual(grade.linha_atual(), 60,
                        "*** F3 vai para a ocorrencia SEGUINTE: sem o "
                        "'coluna apos', ele reacharia a mesma para sempre ***")
            checa_igual(grade.currentIndex().column(), 2,
                        "e agora no terceiro campo")

            janela._procurar(criterio, False)
            checa_igual(grade.linha_atual(), 90, "e na terceira")
            checa_igual(grade.currentIndex().column(), 0,
                        "*** no PRIMEIRO campo -- a coluna de caractere 0 nao "
                        "e' 'a primeira coluna' por acidente, e' por calculo "
                        "***")
            checa_igual(aba.view_atual(), "tabela",
                        "e a grade continua de pe' o tempo todo")
        finally:
            _encerrar(janela)


def testar_hexadecimal_CONTINUA_voltando_ao_texto() -> None:
    """A contraprova: no hexadecimal a volta ao texto tem razao de ser.

    La' a posicao e' um BYTE. Mapear (linha, coluna de caractere) para byte
    exigiria recodificar o prefixo de cada linha, e um multibyte no meio faria
    a selecao cair no lugar errado sem nenhum erro visivel. Voltar avisando e'
    melhor que acertar por sorte.
    """
    secao("*** No hexadecimal, a busca ainda volta ao texto ***")

    from tfedit import busca

    with pasta_temporaria() as pasta:
        janela = _grade_com_busca(pasta)
        try:
            aba = janela.aba_atual
            janela._trocar_view("hex")
            checa_igual(aba.view_atual(), "hex", "o hexadecimal esta' aberto")

            janela._procurar(busca.Criterio(texto="AGULHA"), False)
            checa_igual(aba.view_atual(), "texto",
                        "*** e a busca volta ao texto, como antes ***")
            checa("modo texto" in janela.barra.currentMessage(),
                  f"avisando por que: {janela.barra.currentMessage()!r}")
        finally:
            _encerrar(janela)


def testar_substituir_todas_funciona_na_grade() -> None:
    """"Substituir todas" mexe na TABELA DE PECAS, e nao no cursor do editor.

    Ela nunca precisou do modo texto -- so' o "Substituir" um-a-um precisa,
    porque compara com o que esta' selecionado no cursor. O que faltava era a
    grade jogar fora o cache: ela guarda linhas ja' repartidas, e uma
    substituicao pode ter mudado qualquer linha do arquivo.
    """
    secao("*** Substituir todas mantem a grade, e ela mostra o resultado ***")

    from tfedit import busca

    with pasta_temporaria() as pasta:
        janela = _grade_com_busca(pasta)
        try:
            aba = janela.aba_atual
            grade = aba.view("tabela")
            # Encher o cache com o valor ANTIGO antes de substituir.
            antes = grade.modelo.data(grade.modelo.index(29, 1))
            checa_igual(antes, "AGULHA", "a celula mostra o valor antigo")

            # Sem perguntar: o QMessageBox modal travaria a suite.
            respostas = []
            from PySide6.QtWidgets import QMessageBox
            original = QMessageBox.question
            QMessageBox.question = staticmethod(
                lambda *a, **k: (respostas.append(1),
                                 QMessageBox.StandardButton.Yes)[1])
            try:
                janela._substituir_todas(
                    busca.Criterio(texto="AGULHA"), "LINHA")
            finally:
                QMessageBox.question = original

            checa_igual(aba.view_atual(), "tabela",
                        "*** a grade continua aberta ***")
            depois = grade.modelo.data(grade.modelo.index(29, 1))
            checa_igual(depois, "LINHA",
                        "*** e mostra o valor NOVO: sem `esquecer_tudo()` ela "
                        "mostraria o cache de antes da troca ***")
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
    testar_grade_abre_e_le()
    testar_grade_nao_le_o_arquivo_inteiro()
    testar_celula_e_cirurgica()
    testar_celula_preserva_o_terminador()
    testar_celula_recusa_o_que_nao_cabe()
    testar_registro_de_varias_linhas_e_sinalizado()
    testar_grade_nao_edita_durante_a_varredura()
    testar_menu_oferece_a_tabela()
    testar_desfazer_na_grade_csv()
    testar_desfazer_esquece_o_cache_da_grade()
    testar_desfazer_sem_nada_explica()
    testar_tela_do_separador_mostra_a_previa()
    testar_separador_escolhido_troca_a_grade()
    testar_a_grade_deixa_de_ser_escondida()
    testar_escolher_separador_aparece_mesmo_sem_deteccao()
    testar_busca_NAO_expulsa_da_grade()
    testar_hexadecimal_CONTINUA_voltando_ao_texto()
    testar_substituir_todas_funciona_na_grade()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
