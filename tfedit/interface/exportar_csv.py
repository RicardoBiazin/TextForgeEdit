"""Escolher separador e codificacao para exportar uma aba da planilha em CSV.

Duas escolhas, e so' duas: o caractere que separa as colunas e a codificacao do
arquivo. Nao ha' prévia aqui -- a prévia da tela de colunas mostra um CSV que ja'
existe, e este dialogo cria um que ainda nao existe.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QVBoxLayout)

from tfedit import conversao, csv_dialeto
from tfedit.interface.separador import OFERECIDOS

#: As codificacoes oferecidas: as quatro primeiras de `conversao.ALVOS`, que sao
#: as que um arquivo de planilha comum precisa. UTF-16 fica de fora de proposito:
#: quase nenhum programa que le CSV aceita.
CODIFICACOES = conversao.ALVOS[:4]


class EscolherExportacao(QDialog):
    """Devolve o separador e a codificacao por `escolhido()`, ou nada se cancelar."""

    def __init__(self, nome_da_aba: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Exportar para CSV")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"Exporta a aba <b>{nome_da_aba}</b>. A planilha aberta não muda: "
            f"o CSV é um arquivo novo."))

        formulario = QFormLayout()
        self.separador = QComboBox()
        for caractere in OFERECIDOS:
            rotulo = csv_dialeto.ROTULO_DO_DELIMITADOR.get(
                caractere, repr(caractere))
            visivel = caractere if caractere.strip() else ""
            self.separador.addItem(f"{rotulo}   {visivel}".rstrip(),
                                   userData=caractere)
        # O ";" padrao: e' o separador do CSV brasileiro, o que o Excel em
        # portugues usa quando a virgula e' o decimal.
        posicao = self.separador.findData(";")
        self.separador.setCurrentIndex(max(posicao, 0))
        formulario.addRow("Separador:", self.separador)

        self.codificacao = QComboBox()
        for alvo in CODIFICACOES:
            self.codificacao.addItem(alvo.rotulo, userData=alvo)
        formulario.addRow("Codificação:", self.codificacao)
        layout.addLayout(formulario)

        self.aviso = QLabel()
        self.aviso.setWordWrap(True)
        layout.addWidget(self.aviso)
        self.codificacao.currentIndexChanged.connect(self._mostrar_aviso)
        self._mostrar_aviso()

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                  | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Exportar")
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def escolhido(self) -> tuple[str, "conversao.Alvo"]:
        return (self.separador.currentData(), self.codificacao.currentData())

    def _mostrar_aviso(self) -> None:
        # ASCII e Latin-1 nao escrevem tudo: a exportacao RECUSA, com o caractere
        # nomeado, e nao troca por "?". Dizer isto antes evita a recusa surpresa.
        alvo = self.codificacao.currentData()
        if alvo.codec == "utf-8":
            self.aviso.setText("UTF-8 escreve qualquer caractere. Use-o se o "
                               "destino aceitar.")
        else:
            self.aviso.setText(
                f"{alvo.rotulo} não escreve todos os caracteres. Se a planilha "
                f"tiver algum que ela não representa, a exportação é recusada e "
                f"mostra qual é -- nada é trocado por “?”.")
