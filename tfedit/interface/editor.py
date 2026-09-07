"""O editor: um `QPlainTextEdit` de verdade, mostrando uma FATIA do arquivo.

Tudo o que se espera de um editor -- cursor de caractere, selecao atravessando
linhas, acentuacao com tecla morta, colar, desfazer, arrastar -- vem pronto do
Qt, porque isto E' um QPlainTextEdit. O que este arquivo faz e' manter a ilusao
de que ele contem o arquivo inteiro:

  * a barra de rolagem mede o DOCUMENTO, e nao a fatia;
  * rolar ou mover o cursor para perto da borda DESLIZA a fatia;
  * o numero de linha mostrado e' o do documento, nao o da fatia.

O que fica de fora, e esta' declarado na interface para ninguem descobrir sozinho:
desfazer vale DENTRO da fatia. Ao deslizar, o que foi editado e' consolidado na
tabela de pecas e a pilha do Qt recomeca. Costurar as duas pilhas exigiria
reimplementar o desfazer do Qt -- exatamente o que esta arquitetura evita.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from tfedit.janela import JanelaViva


class Margem(QWidget):
    """A coluna de numeros. Mostra a linha do DOCUMENTO, e nao a da fatia."""

    def __init__(self, editor: "EditorDeslizante") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):                                   # noqa: N802 - Qt
        from PySide6.QtCore import QSize
        return QSize(self.editor.largura_da_margem(), 0)

    def paintEvent(self, evento):                         # noqa: N802 - Qt
        self.editor.pintar_margem(evento)


class EditorDeslizante(QPlainTextEdit):
    """O widget. Fala com a `JanelaViva`, que fala com a tabela de pecas."""

    #: (linha no documento, coluna) -- para a barra de status.
    posicao_mudou = Signal(int, int)
    #: O documento passou a ter alteracoes pendentes.
    sujou = Signal()

    def __init__(self, janela: JanelaViva, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.janela = janela
        self._deslizando = False

        fonte = QFont("Consolas", 11)
        fonte.setFixedPitch(True)
        fonte.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(fonte)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(QFontMetrics(fonte).horizontalAdvance(" ") * 4)

        self.margem = Margem(self)
        self.blockCountChanged.connect(lambda _n: self._ajustar_margem())
        self.updateRequest.connect(self._atualizar_margem)
        self.cursorPositionChanged.connect(self._ao_mover_cursor)
        self.textChanged.connect(self._ao_mudar_texto)
        self._ajustar_margem()

        self.recarregar(0)

    # ==================================================================
    # A fatia
    # ==================================================================

    def recarregar(self, linha_do_documento: int) -> None:
        """Troca o conteudo do widget pela fatia em volta da linha pedida."""
        self._deslizando = True
        try:
            recorte = self.janela.carregar(linha_do_documento)
            self.setPlainText(recorte.texto)
            # A pilha do Qt recomeca: sem isto, um Ctrl+Z logo depois de
            # deslizar apagaria a fatia inteira, que e' o que `setPlainText`
            # registrou como "a edicao anterior".
            self.document().clearUndoRedoStacks()
            self.document().setModified(False)
            alvo = self.janela.linha_na_fatia(linha_do_documento)
            if alvo >= 0:
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                cursor.movePosition(QTextCursor.MoveOperation.Down,
                                    QTextCursor.MoveMode.MoveAnchor, alvo)
                self.setTextCursor(cursor)
                self.centerCursor()
        finally:
            self._deslizando = False
        self._ajustar_margem()

    def sincronizar(self) -> bool:
        """Manda para a tabela de pecas o que foi editado na fatia."""
        if self._deslizando:
            return False
        if not self.document().isModified():
            return False
        mudou = self.janela.aplicar(self.toPlainText())
        self.document().setModified(False)
        return mudou

    def linha_atual_no_documento(self) -> int:
        return self.janela.linha_no_documento(self.textCursor().blockNumber())

    def ir_para_linha(self, linha: int) -> None:
        """`linha` em base zero, no DOCUMENTO. Desliza se preciso."""
        if self.janela.linha_na_fatia(linha) < 0:
            self.sincronizar()
            self.recarregar(linha)
            return
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down,
                            QTextCursor.MoveMode.MoveAnchor,
                            self.janela.linha_na_fatia(linha))
        self.setTextCursor(cursor)
        self.centerCursor()

    def _ao_mover_cursor(self) -> None:
        if self._deslizando:
            return
        linha = self.linha_atual_no_documento()
        self.posicao_mudou.emit(linha, self.textCursor().columnNumber())
        # Mover o cursor fecha o grupo de digitacao na tabela de pecas: teclas
        # seguidas viram uma operacao de desfazer, mas mover o cursor no meio
        # significa que a proxima e' outra coisa.
        self.janela.documento.fechar_grupo()
        if self.janela.precisa_deslizar(linha):
            self.sincronizar()
            self.recarregar(linha)

    def _ao_mudar_texto(self) -> None:
        if not self._deslizando:
            self.sujou.emit()

    # ==================================================================
    # A margem de numeros
    # ==================================================================

    def largura_da_margem(self) -> int:
        total = max(1, self.janela.documento.total_de_linhas)
        digitos = max(4, len(str(total)))
        return 12 + QFontMetrics(self.font()).horizontalAdvance("9") * digitos

    def _ajustar_margem(self) -> None:
        self.setViewportMargins(self.largura_da_margem(), 0, 0, 0)

    def _atualizar_margem(self, rect, dy: int) -> None:
        if dy:
            self.margem.scroll(0, dy)
        else:
            self.margem.update(0, rect.y(), self.margem.width(), rect.height())

    def resizeEvent(self, evento) -> None:                # noqa: N802 - Qt
        super().resizeEvent(evento)
        from PySide6.QtCore import QRect
        area = self.contentsRect()
        self.margem.setGeometry(QRect(area.left(), area.top(),
                                      self.largura_da_margem(), area.height()))

    def pintar_margem(self, evento) -> None:
        pintor = QPainter(self.margem)
        pintor.fillRect(evento.rect(), self.palette().alternateBase())
        bloco = self.firstVisibleBlock()
        topo = round(self.blockBoundingGeometry(bloco)
                     .translated(self.contentOffset()).top())
        altura = round(self.blockBoundingRect(bloco).height())
        atual = self.textCursor().blockNumber()

        while bloco.isValid() and topo <= evento.rect().bottom():
            if bloco.isVisible() and topo + altura >= evento.rect().top():
                # O numero e' o do DOCUMENTO. Mostrar o da fatia faria a linha 1
                # aparecer no meio de um arquivo de 13 milhoes de linhas.
                numero = self.janela.linha_no_documento(bloco.blockNumber()) + 1
                pintor.setPen(self.palette().text().color()
                              if bloco.blockNumber() == atual
                              else self.palette().mid().color())
                pintor.drawText(0, topo, self.margem.width() - 6, altura,
                                int(Qt.AlignmentFlag.AlignRight
                                    | Qt.AlignmentFlag.AlignVCenter),
                                str(numero))
            bloco = bloco.next()
            topo += altura
        pintor.end()
