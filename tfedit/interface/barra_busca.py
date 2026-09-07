"""A barra de localizar e substituir, no rodape do editor.

Barra em vez de dialogo modal de proposito: um modal cobre o texto e obriga a
fecha-lo para olhar o resultado. A barra fica visivel enquanto se navega pelas
ocorrencias, que e' o que se faz de fato.

O que ela procura e' o DOCUMENTO inteiro, e nao a fatia carregada -- ver
`tfedit/busca.py`. Achar fora da fatia faz o editor deslizar ate' la'.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QLabel, QLineEdit,
                               QToolButton, QWidget)

from tfedit.busca import Criterio


class BarraDeBusca(QWidget):
    """Localizar, localizar anterior, substituir e substituir todas."""

    procurar = Signal(object, bool)        # (Criterio, para_tras)
    substituir_atual = Signal(object, str)  # (Criterio, substituto)
    substituir_todas = Signal(object, str)
    fechada = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.campo = QLineEdit(self)
        self.campo.setPlaceholderText("Localizar")
        self.campo.setClearButtonEnabled(True)
        self.campo.returnPressed.connect(lambda: self._procurar(False))

        self.campo_troca = QLineEdit(self)
        self.campo_troca.setPlaceholderText("Substituir por")
        self.campo_troca.setClearButtonEnabled(True)

        self.caixa_maiusculas = QCheckBox("Aa", self)
        self.caixa_maiusculas.setToolTip("Diferenciar maiusculas de minusculas")
        self.caixa_palavra = QCheckBox("Palavra", self)
        self.caixa_palavra.setToolTip("Somente palavras inteiras")
        self.caixa_regex = QCheckBox(".*", self)
        self.caixa_regex.setToolTip("Expressao regular")

        self.rotulo = QLabel("", self)

        grade = QGridLayout(self)
        grade.setContentsMargins(6, 4, 6, 4)
        grade.setSpacing(6)
        grade.addWidget(QLabel("Localizar:", self), 0, 0)
        grade.addWidget(self.campo, 0, 1)
        grade.addWidget(self._botao("↑", "Anterior (Shift+F3)",
                                    lambda: self._procurar(True)), 0, 2)
        grade.addWidget(self._botao("↓", "Proxima (F3)",
                                    lambda: self._procurar(False)), 0, 3)
        grade.addWidget(self.caixa_maiusculas, 0, 4)
        grade.addWidget(self.caixa_palavra, 0, 5)
        grade.addWidget(self.caixa_regex, 0, 6)
        grade.addWidget(self.rotulo, 0, 7)
        grade.addWidget(self._botao("×", "Fechar (Esc)", self._fechar),
                        0, 8)

        grade.addWidget(QLabel("Substituir:", self), 1, 0)
        grade.addWidget(self.campo_troca, 1, 1)
        grade.addWidget(self._botao("Trocar", "Substitui a ocorrencia atual",
                                    self._substituir), 1, 2, 1, 2)
        grade.addWidget(self._botao("Trocar todas",
                                    "Substitui em todo o arquivo",
                                    self._substituir_todas), 1, 4, 1, 3)
        grade.setColumnStretch(1, 1)

    def _botao(self, texto: str, dica: str, tratador) -> QToolButton:
        botao = QToolButton(self)
        botao.setText(texto)
        botao.setToolTip(dica)
        botao.setAutoRaise(True)
        botao.clicked.connect(tratador)
        return botao

    # ==================================================================

    def criterio(self) -> Criterio:
        return Criterio(
            texto=self.campo.text(),
            diferenciar_maiusculas=self.caixa_maiusculas.isChecked(),
            palavra_inteira=self.caixa_palavra.isChecked(),
            expressao_regular=self.caixa_regex.isChecked())

    def focar(self, selecao: str = "") -> None:
        """Abre a barra. `selecao` preenche o campo -- o gesto de Ctrl+F."""
        if selecao and "\n" not in selecao:
            self.campo.setText(selecao)
        self.show()
        self.campo.setFocus()
        self.campo.selectAll()

    def dizer(self, mensagem: str, erro: bool = False) -> None:
        self.rotulo.setText(mensagem)
        # Vermelho so' para "nao achei" e regex invalido: o resto e' informacao,
        # e pintar tudo de vermelho faria o usuario parar de ler.
        self.rotulo.setStyleSheet("color: #c0392b;" if erro else "")

    def _procurar(self, para_tras: bool) -> None:
        criterio = self.criterio()
        if not criterio.texto:
            return
        if criterio.compilar() is None:
            self.dizer("expressao regular invalida", erro=True)
            return
        self.procurar.emit(criterio, para_tras)

    def _substituir(self) -> None:
        criterio = self.criterio()
        if criterio.texto and criterio.compilar() is not None:
            self.substituir_atual.emit(criterio, self.campo_troca.text())

    def _substituir_todas(self) -> None:
        criterio = self.criterio()
        if criterio.texto and criterio.compilar() is not None:
            self.substituir_todas.emit(criterio, self.campo_troca.text())

    def _fechar(self) -> None:
        self.hide()
        self.fechada.emit()

    def keyPressEvent(self, evento: QKeyEvent) -> None:   # noqa: N802 - Qt
        """Esc fecha a barra, em vez de subir para a janela."""
        if evento.key() == Qt.Key.Key_Escape:
            self._fechar()
            evento.accept()
            return
        super().keyPressEvent(evento)
