"""Escolher à mão o separador de colunas de um CSV/DSV.

A detecção automática acerta na maioria dos arquivos, mas ela é um palpite, e
um palpite tem de ter porta de saída. Sem esta tela o programa dizia *"não foi
possível reconhecer um separador de colunas"* e o assunto acabava ali -- mesmo
quando a pessoa sabia perfeitamente qual era o separador do próprio arquivo.

Três casos reais que só saem daqui:

* um arquivo de **uma coluna só** com um separador que a heurística descarta
  por não estar em coluna nenhuma;
* um export cujo separador não é nenhum dos `CANDIDATOS` (há sistemas que usam
  `\\x1f`, o separador de unidade do ASCII, exatamente por não ocorrer no dado);
* um arquivo separado por **espaço**. O espaço está fora dos `CANDIDATOS` de
  propósito: com ele lá, toda prosa em português viraria uma tabela de dez
  colunas. A detecção acerta em recusar, e esta tela é o único caminho.

Um caso que se supunha estar nesta lista e **não está**: um log com horários
enganando a detecção e fazendo o `:` ganhar do `;`. Medido: não ganha -- o
desempate por *presença* já resolve. O detector é melhor do que parece; o que
faltava era a porta de saída para quando ele não é.

**A prévia é o que faz esta tela valer.** Escolher um separador às cegas e
descobrir o resultado só depois de a grade abrir transformaria a correção de um
palpite errado em tentativa e erro. Aqui as primeiras linhas já aparecem
repartidas enquanto se escolhe, com o número de colunas ao lado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLabel, QLineEdit, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from tfedit import csv_dialeto, log_interno

log = log_interno.obter(__name__)

#: Os separadores oferecidos na caixa, na ordem de utilidade nesta máquina.
#: Os rótulos saem de `csv_dialeto.ROTULO_DO_DELIMITADOR` para não haver duas
#: listas de nomes para os mesmos caracteres.
OFERECIDOS = (";", ",", "\t", "|", ":", "~", "^", "#", " ")

#: Quantas linhas mostrar na prévia. É prévia, não é a grade: ninguém decide
#: qual é o separador do arquivo olhando mais que isto, e cada linha a mais é
#: uma leitura a mais na tabela de peças.
LINHAS_DE_PREVIA = 12

#: Quantas colunas a prévia desenha. Um arquivo de 300 colunas travaria a tela
#: para mostrar o que não cabe: as primeiras já dizem se o corte está certo.
COLUNAS_DE_PREVIA = 20


class EscolherSeparador(QDialog):
    """Devolve um `Dialeto` por `dialeto_escolhido`, ou nada se cancelar.

    Recebe a AMOSTRA já decodificada -- as mesmas linhas que a detecção
    automática usa. Esta tela não toca no documento: quem abre é que lê.
    """

    def __init__(self, amostra: str, parent=None, *,
                 sugerido: str | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Visualizar em colunas")
        self.amostra = amostra
        self.dialeto_escolhido = None

        layout = QVBoxLayout(self)
        explicacao = QLabel(
            "Escolha o caractere que separa as colunas. A prévia abaixo "
            "mostra como o arquivo fica repartido.")
        explicacao.setWordWrap(True)
        layout.addWidget(explicacao)

        formulario = QFormLayout()
        self.caixa = QComboBox()
        for caractere in OFERECIDOS:
            rotulo = csv_dialeto.ROTULO_DO_DELIMITADOR.get(
                caractere, repr(caractere))
            # O caractere aparece junto do nome: "ponto e vírgula" é o nome
            # certo, mas é o `;` que a pessoa procura no próprio arquivo.
            visivel = caractere if caractere.strip() else ""
            self.caixa.addItem(
                f"{rotulo}   {visivel}".rstrip(), userData=caractere)
        self.caixa.addItem("Outro caractere…", userData=None)
        formulario.addRow("Separador:", self.caixa)

        self.outro = QLineEdit()
        self.outro.setMaxLength(1)
        self.outro.setPlaceholderText("um caractere")
        self.outro.setEnabled(False)
        formulario.addRow("Qual:", self.outro)
        layout.addLayout(formulario)

        self.resumo = QLabel()
        self.resumo.setWordWrap(True)
        layout.addWidget(self.resumo)

        self.previa = QTableWidget(0, 0)
        self.previa.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.previa.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection)
        self.previa.verticalHeader().setVisible(False)
        self.previa.setMinimumHeight(240)
        layout.addWidget(self.previa)

        self.botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.botoes.button(
            QDialogButtonBox.StandardButton.Ok).setText("Visualizar")
        self.botoes.button(
            QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        self.botoes.accepted.connect(self.aceitar)
        self.botoes.rejected.connect(self.reject)
        layout.addWidget(self.botoes)

        self.caixa.currentIndexChanged.connect(self._trocou_de_caixa)
        self.outro.textChanged.connect(self.atualizar_previa)

        if sugerido is not None:
            posicao = self.caixa.findData(sugerido)
            if posicao >= 0:
                self.caixa.setCurrentIndex(posicao)
            else:
                self.caixa.setCurrentIndex(self.caixa.count() - 1)
                self.outro.setText(sugerido)
        self._trocou_de_caixa()
        self.resize(680, 460)

    # ------------------------------------------------------------------
    def separador(self) -> str:
        """O caractere escolhido agora. `""` quando ainda não há um."""
        dado = self.caixa.currentData()
        return dado if dado is not None else self.outro.text()

    def _trocou_de_caixa(self) -> None:
        manual = self.caixa.currentData() is None
        self.outro.setEnabled(manual)
        if manual:
            self.outro.setFocus()
        self.atualizar_previa()

    def atualizar_previa(self) -> None:
        caractere = self.separador()
        ok = bool(caractere)
        dialeto = None
        if ok:
            try:
                dialeto = csv_dialeto.com_delimitador(self.amostra, caractere)
            except ValueError as erro:
                # Aspa e quebra de linha não podem ser separador. Dizer por
                # quê, aqui, vale mais que desabilitar o campo sem explicação.
                self.resumo.setText(f"Não dá: {erro}.")
                ok = False

        self.botoes.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(ok)
        if not ok:
            if not caractere:
                self.resumo.setText("Digite o caractere que separa as colunas.")
            self.previa.setRowCount(0)
            self.previa.setColumnCount(0)
            return

        if dialeto.colunas < 2:
            # Não é impedimento: um arquivo de uma coluna é um arquivo
            # legítimo. Mas é quase sempre sinal de separador errado, e vale
            # mais avisar do que abrir uma grade de uma coluna em silêncio.
            self.resumo.setText(
                f"{dialeto.rotulo_do_delimitador}: só 1 coluna. "
                "Este provavelmente não é o separador do arquivo.")
        else:
            self.resumo.setText(f"{dialeto.descrever()}.")
        self._desenhar(dialeto)

    def _desenhar(self, dialeto) -> None:
        linhas = [l for l in self.amostra.splitlines()
                  if l.strip()][:LINHAS_DE_PREVIA]
        registros = [csv_dialeto.campos_de(l, dialeto) for l in linhas]
        colunas = min(max((len(r) for r in registros), default=1),
                      COLUNAS_DE_PREVIA)

        corpo = registros[1:] if dialeto.tem_cabecalho else registros
        self.previa.setRowCount(len(corpo))
        self.previa.setColumnCount(colunas)
        if dialeto.tem_cabecalho and registros:
            cabecalho = registros[0]
            self.previa.setHorizontalHeaderLabels(
                [cabecalho[c] if c < len(cabecalho) else ""
                 for c in range(colunas)])
        else:
            self.previa.setHorizontalHeaderLabels(
                [str(c + 1) for c in range(colunas)])

        for l, registro in enumerate(corpo):
            for c in range(colunas):
                valor = registro[c] if c < len(registro) else ""
                item = QTableWidgetItem(valor)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.previa.setItem(l, c, item)
        # `resizeColumnsToContents` E' PROIBIDO na grade de verdade -- la' ele
        # pergunta ao modelo por toda linha, isto e', le' o arquivo inteiro num
        # clique. Aqui e' seguro: este e' um QTableWidget com no maximo
        # LINHAS_DE_PREVIA linhas ja' carregadas na memoria.
        self.previa.resizeColumnsToContents()

    def aceitar(self) -> None:
        caractere = self.separador()
        if not caractere:
            return
        try:
            self.dialeto_escolhido = csv_dialeto.com_delimitador(
                self.amostra, caractere)
        except ValueError as erro:
            log.info("separador recusado: %s", erro)
            return
        self.accept()
