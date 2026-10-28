"""A lista de ocorrencias da busca, numa grade embaixo do editor.

"Listar" percorre o DOCUMENTO inteiro -- e nao so' a fatia carregada -- e
mostra cada ocorrencia com a linha, a coluna e um trecho do texto em volta.
Duplo clique (ou Enter) leva ate' ela.

DUAS DECISOES, ambas medidas:

* **A varredura roda aos pedacos, na thread da interface.** Num arquivo de
  45 MB ela leva 0,3 s; num de 1 GB, alguns segundos. Uma thread separada
  leria a tabela de pecas enquanto o usuario edita nela -- e a tabela nao e'
  feita para isso. Pedacos de ~30 ms pelo temporizador mantem a janela
  respondendo sem dividir o documento entre duas threads.
* **A contagem e' do arquivo inteiro; a LISTA tem teto.** Contar custa so' o
  tempo da varredura. Guardar cada ocorrencia custa memoria: 100 mil linhas
  com um trecho de 160 caracteres ja' sao dezenas de MB. Acima do teto a lista
  para de crescer e o cabecalho diz isso, mas o numero total continua certo.

A lista e' um retrato do momento da busca: editar depois pode deslocar as
linhas. "Listar" de novo refaz.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QTableView,
                               QToolButton, QVBoxLayout, QWidget)

from tfedit import busca

#: Quantas ocorrencias a lista guarda. A contagem continua alem disto.
TETO_DA_LISTA = 100_000

#: Quantos caracteres do texto da linha aparecem na grade, em volta do achado.
LARGURA_DO_TRECHO = 160

#: Quanto tempo cada pedaco da varredura pode ocupar a interface.
FATIA_DE_TEMPO_S = 0.03

COLUNAS = ("Linha", "Coluna", "Texto")


def trecho(texto: str, inicio: int, fim: int,
           largura: int = LARGURA_DO_TRECHO) -> str:
    """O pedaco da linha em volta da ocorrencia, com reticencias onde cortou."""
    if len(texto) <= largura:
        return texto
    folga = max(0, (largura - (fim - inicio)) // 2)
    a = max(0, inicio - folga)
    b = min(len(texto), a + largura)
    a = max(0, b - largura)
    return ("…" if a > 0 else "") + texto[a:b] + ("…" if b < len(texto) else "")


class ModeloDeResultados(QAbstractTableModel):
    """As ocorrencias encontradas: (linha, inicio, fim, trecho)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.linhas: list[tuple[int, int, int, str]] = []

    def rowCount(self, pai=QModelIndex()) -> int:         # noqa: N802 - Qt
        return 0 if pai.isValid() else len(self.linhas)

    def columnCount(self, pai=QModelIndex()) -> int:      # noqa: N802 - Qt
        return 0 if pai.isValid() else len(COLUNAS)

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        linha, inicio, _fim, texto = self.linhas[indice.row()]
        if papel == Qt.ItemDataRole.DisplayRole:
            if indice.column() == 0:
                return f"{linha + 1:,}".replace(",", ".")
            if indice.column() == 1:
                return str(inicio + 1)
            return texto
        if (papel == Qt.ItemDataRole.TextAlignmentRole
                and indice.column() in (0, 1)):
            return int(Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter)
        return None

    def headerData(self, secao, orientacao,               # noqa: N802 - Qt
                   papel=Qt.ItemDataRole.DisplayRole):
        if (papel == Qt.ItemDataRole.DisplayRole
                and orientacao == Qt.Orientation.Horizontal):
            return COLUNAS[secao]
        return None

    def limpar(self) -> None:
        self.beginResetModel()
        self.linhas = []
        self.endResetModel()

    def acrescentar(self, novas: list) -> None:
        if not novas:
            return
        primeira = len(self.linhas)
        self.beginInsertRows(QModelIndex(), primeira, primeira + len(novas) - 1)
        self.linhas.extend(novas)
        self.endInsertRows()


class PainelDeResultados(QWidget):
    """Cabecalho com a contagem, a grade, e o botao de fechar."""

    #: (linha, inicio, fim) da ocorrencia escolhida.
    escolhido = Signal(int, int, int)
    #: (ocorrencias, linhas com ocorrencia, se a lista parou no teto).
    terminou = Signal(int, int, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.modelo = ModeloDeResultados(self)

        self.cabecalho = QLabel("", self)
        fechar = QToolButton(self)
        fechar.setText("×")
        fechar.setToolTip("Fechar a lista")
        fechar.setAutoRaise(True)
        fechar.clicked.connect(self.fechar)

        topo = QHBoxLayout()
        topo.setContentsMargins(6, 2, 6, 0)
        topo.addWidget(self.cabecalho, 1)
        topo.addWidget(fechar)

        self.grade = QTableView(self)
        self.grade.setModel(self.modelo)
        self.grade.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.grade.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.grade.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.grade.verticalHeader().setVisible(False)
        # ScrollPerItem e altura fixa: a grade pode ter 100 mil linhas, e medir
        # cada uma para rolar seria o custo que o projeto existe para evitar.
        self.grade.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerItem)
        self.grade.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed)
        cabecalho = self.grade.horizontalHeader()
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        cabecalho.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        cabecalho.setStretchLastSection(True)
        self.grade.setColumnWidth(0, 90)
        self.grade.setColumnWidth(1, 70)
        self.grade.doubleClicked.connect(self._ao_escolher)
        self.grade.activated.connect(self._ao_escolher)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addLayout(topo)
        layout.addWidget(self.grade, 1)

        self._relogio = QTimer(self)
        self._relogio.setInterval(0)
        self._relogio.timeout.connect(self._avancar)
        self._gerador = None
        self._contagem = 0
        self._linhas_com_achado = 0
        self._ultima_linha = -1
        self._cortou = False
        self._texto_procurado = ""

    # ------------------------------------------------------------------
    @property
    def procurando(self) -> bool:
        return self._gerador is not None

    def comecar(self, documento, criterio, codec: str) -> bool:
        """Comeca uma listagem nova. False se o criterio nao compila."""
        self.cancelar()
        if criterio.compilar() is None:
            return False
        self.modelo.limpar()
        self._contagem = 0
        self._linhas_com_achado = 0
        self._ultima_linha = -1
        self._cortou = False
        self._texto_procurado = criterio.texto
        self._gerador = busca.procurar(documento, criterio, codec)
        self.show()
        self._mostrar_cabecalho()
        self._relogio.start()
        return True

    def cancelar(self) -> None:
        self._relogio.stop()
        if self._gerador is not None:
            self._gerador.close()
        self._gerador = None

    def fechar(self) -> None:
        self.cancelar()
        self.hide()

    def executar_tudo(self) -> None:
        """Termina a varredura de uma vez. E' o que os testes usam."""
        while self._gerador is not None:
            self._avancar(sem_limite=True)

    def _avancar(self, sem_limite: bool = False) -> None:
        if self._gerador is None:
            return
        prazo = time.monotonic() + FATIA_DE_TEMPO_S
        novas = []
        terminou = False
        while sem_limite or time.monotonic() < prazo:
            try:
                achado = next(self._gerador)
            except StopIteration:
                terminou = True
                break
            self._contagem += 1
            if achado.linha != self._ultima_linha:
                self._linhas_com_achado += 1
                self._ultima_linha = achado.linha
            if len(self.modelo.linhas) + len(novas) < TETO_DA_LISTA:
                novas.append((achado.linha, achado.inicio, achado.fim,
                              trecho(achado.texto, achado.inicio, achado.fim)))
            else:
                self._cortou = True
            if sem_limite and len(novas) >= 4096:
                break
        self.modelo.acrescentar(novas)
        if terminou:
            self._relogio.stop()
            self._gerador = None
            self.terminou.emit(self._contagem, self._linhas_com_achado,
                               self._cortou)
        self._mostrar_cabecalho()

    def _mostrar_cabecalho(self) -> None:
        def n(valor: int) -> str:
            return f"{valor:,}".replace(",", ".")

        texto = (f"“{self._texto_procurado}”: {n(self._contagem)} "
                 f"ocorrência(s) em {n(self._linhas_com_achado)} linha(s)")
        if self.procurando:
            texto += " — procurando…"
        if self._cortou:
            texto += (f" — a lista mostra as primeiras {n(TETO_DA_LISTA)}; "
                      f"a contagem é do arquivo inteiro")
        self.cabecalho.setText(texto)

    def _ao_escolher(self, indice) -> None:
        if not indice.isValid():
            return
        linha, inicio, fim, _ = self.modelo.linhas[indice.row()]
        self.escolhido.emit(linha, inicio, fim)
