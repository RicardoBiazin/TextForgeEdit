"""Grade de uma planilha .xlsx.

DIFERENTE DAS OUTRAS VIEWS, esta nao le' do `Documento`.

Um `.xlsx` nao e' texto: e' um ZIP de XML. Nao ha' linha, nao ha' fim de linha,
nao ha' codificacao -- e por isso a aba que abre uma planilha nao cria mmap,
indice nem tabela de pecas (ver o cabecalho de `interface/aba.py`). A fonte da
verdade aqui e' a `Pasta`, que ja' esta' inteira na memoria.

Isso NAO e' uma inconsistencia com o resto do projeto; e' a consequencia
honesta de o formato ser outro. O que se preserva e' o principio: **os bytes
que ninguem tocou saem como entraram**. `Pasta.bytes_para_salvar()` de uma
planilha nao alterada devolve o pacote original sem nem recomprimir, e uma
celula editada vira um patch nos bytes daquela celula -- e' o equivalente, aqui,
da peca ORIGINAL que a gravacao por streaming copia byte a byte.

O TETO DE TAMANHO E' CONSEQUENCIA DISSO, e nao descuido: como a pasta inteira
vai para a memoria, a aba confere o tamanho por `stat` antes de ler e recusa
acima de `limite_planilha_mb`. Um .xlsx grande demais abre como arquivo comum,
onde as garantias de memoria do editor voltam a valer.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QHeaderView, QTabBar, QTableView, QVBoxLayout,
                               QWidget)

from tfedit import log_interno
from tfedit.interface.visualizadores.base import VisualizadorDeDocumento
from tfedit.planilha.pasta import TIPO_DATA, TIPO_FORMULA, TIPO_NUMERO

log = log_interno.obter(__name__)

#: Linhas e colunas em branco oferecidas depois do fim dos dados, para dar onde
#: digitar sem precisar de um comando de "inserir linha".
LINHAS_LIVRES = 20
COLUNAS_LIVRES = 4

#: Quantas linhas medir ao ajustar a largura das colunas.
LINHAS_PARA_MEDIR = 200

LARGURA_MINIMA = 60
LARGURA_MAXIMA = 400


class ModeloPlanilha(QAbstractTableModel):
    """Uma aba da pasta. Le' de `Folha`, escreve por `Pasta.definir`."""

    mudou = Signal()

    def __init__(self, pasta, folha, parent=None) -> None:
        super().__init__(parent)
        self.pasta = pasta
        self.folha = folha

    def rowCount(self, pai=QModelIndex()) -> int:         # noqa: N802 - Qt
        return 0 if pai.isValid() else self.folha.linhas + LINHAS_LIVRES

    def columnCount(self, pai=QModelIndex()) -> int:      # noqa: N802 - Qt
        return 0 if pai.isValid() else self.folha.colunas + COLUNAS_LIVRES

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        celula = self.folha.celula(indice.row() + 1, indice.column() + 1)

        if papel in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return celula.texto
        if papel == Qt.ItemDataRole.TextAlignmentRole:
            if celula.tipo in (TIPO_NUMERO, TIPO_DATA):
                return int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter)
        if papel == Qt.ItemDataRole.ToolTipRole:
            return self._dica(celula)
        return None

    @staticmethod
    def _dica(celula) -> str | None:
        """O que a célula esconde: o valor calculado, ou por que está travada."""
        partes = []
        if celula.tipo == TIPO_FORMULA and celula.cache:
            partes.append(f"Valor calculado pelo Excel: {celula.cache}")
        if celula.travada:
            partes.append("Célula somente leitura: fórmula compartilhada ou "
                          "erro do Excel.")
        return "\n".join(partes) or None

    def headerData(self, secao, orientacao,               # noqa: N802 - Qt
                   papel=Qt.ItemDataRole.DisplayRole):
        if papel != Qt.ItemDataRole.DisplayRole:
            return None
        if orientacao == Qt.Orientation.Horizontal:
            from tfedit.planilha.valores import letra_de_coluna

            return letra_de_coluna(secao + 1)
        return str(secao + 1)

    def setData(self, indice, valor,                      # noqa: N802 - Qt
                papel=Qt.ItemDataRole.EditRole) -> bool:
        if not indice.isValid() or papel != Qt.ItemDataRole.EditRole:
            return False
        if self.pasta.definir(self.folha, indice.row() + 1,
                              indice.column() + 1, str(valor)):
            # O `dataChanged` sozinho nao basta quando a edicao AMPLIOU a aba:
            # o modelo passou a ter mais linhas, e a view precisa saber.
            self.layoutChanged.emit()
            self.dataChanged.emit(indice, indice, [papel])
            self.mudou.emit()
            return True
        return False

    def flags(self, indice) -> Qt.ItemFlag:
        base = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if not indice.isValid():
            return Qt.ItemFlag.NoItemFlags
        if self.pasta.somente_leitura:
            return base
        celula = self.folha.celula(indice.row() + 1, indice.column() + 1)
        if celula.travada:
            return base
        return base | Qt.ItemFlag.ItemIsEditable


class GradePlanilha(VisualizadorDeDocumento, QWidget):
    """A grade mais a barra de abas da pasta."""

    # Declarados aqui, e nao no mixin: o PySide6 so' registra `Signal` numa
    # classe que ja' e' QObject. Ver o cabecalho de `base.py`.
    posicao_mudou = Signal(int, int)
    sujou = Signal()
    recusou = Signal(str)

    nome = "planilha"
    editavel = True

    def __init__(self, pasta, parent=None, *, tema=None, cfg=None) -> None:
        QWidget.__init__(self, parent)
        # `documento` e `perfil` sao None: esta view nao le' da tabela de
        # pecas. Ver o cabecalho.
        self.preparar(None, None, tema=tema, cfg=cfg)
        self.pasta = pasta
        self.editavel = not pasta.somente_leitura

        self.tabela = QTableView(self)
        fonte = QFont(str(self.cfg.get("fonte", "Consolas")),
                      int(self.cfg.get("fonte_tamanho", 11)))
        self.tabela.setFont(fonte)
        self.tabela.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerItem)
        self.tabela.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed)
        self.tabela.verticalHeader().setDefaultSectionSize(
            QFontMetrics(fonte).height() + 6)

        # A barra de abas so' aparece quando ha' mais de uma: uma aba unica
        # com uma barra seria ruido.
        self.abas = QTabBar(self)
        self.abas.setExpanding(False)
        self.abas.setDrawBase(False)
        for folha in pasta.folhas:
            self.abas.addTab(folha.nome)
        self.abas.setVisible(len(pasta.folhas) > 1)
        self.abas.currentChanged.connect(self._trocar_de_folha)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tabela, 1)
        layout.addWidget(self.abas)

        self._modelos: dict[int, ModeloPlanilha] = {}
        self._trocar_de_folha(0)

    # ==================================================================
    # Folhas
    # ==================================================================

    def _trocar_de_folha(self, indice: int) -> None:
        if not 0 <= indice < len(self.pasta.folhas):
            return
        modelo = self._modelos.get(indice)
        if modelo is None:
            # Troca o MODELO, e nao a pasta: edicoes feitas em varias abas
            # convivem ate' a gravacao, que e' o que o usuario espera de uma
            # planilha.
            modelo = ModeloPlanilha(self.pasta, self.pasta.folhas[indice], self)
            modelo.mudou.connect(self.sujou)
            self._modelos[indice] = modelo
        self.tabela.setModel(modelo)
        self.tabela.selectionModel().currentChanged.connect(self._ao_mover)
        self._medir_colunas(modelo)

    def _medir_colunas(self, modelo: ModeloPlanilha) -> None:
        metrica = QFontMetrics(self.tabela.font())
        quantas = min(LINHAS_PARA_MEDIR, modelo.folha.linhas)
        for coluna in range(modelo.columnCount()):
            maior = 3
            for linha in range(1, quantas + 1):
                texto = modelo.folha.celula(linha, coluna + 1).texto
                if texto:
                    maior = max(maior, len(texto))
            largura = metrica.horizontalAdvance("0") * (maior + 2)
            self.tabela.setColumnWidth(
                coluna, max(LARGURA_MINIMA, min(LARGURA_MAXIMA, largura)))

    def _ao_mover(self, atual, _anterior) -> None:
        if atual.isValid():
            self.posicao_mudou.emit(atual.row(), atual.column())

    # ==================================================================
    # O contrato da view
    # ==================================================================

    def sincronizar(self) -> bool:
        """Fecha o editor de célula aberto.

        Sem isto, salvar com uma célula em edição gravaria a planilha sem o que
        estava sendo digitado nela.
        """
        if self.tabela.state() == QTableView.State.EditingState:
            self.tabela.closePersistentEditor(self.tabela.currentIndex())
            self.tabela.setState(QTableView.State.NoState)
            return True
        return False

    def linha_atual(self) -> int:
        indice = self.tabela.currentIndex()
        return indice.row() if indice.isValid() else 0

    def ir_para_linha(self, linha: int) -> None:
        modelo = self.tabela.model()
        if modelo is None:
            return
        alvo = max(0, min(linha, modelo.rowCount() - 1))
        indice = modelo.index(alvo, 0)
        if indice.isValid():
            self.tabela.setCurrentIndex(indice)
            self.tabela.scrollTo(indice)

    def aplicar_tema(self, tema) -> None:
        VisualizadorDeDocumento.aplicar_tema(self, tema)
        fundo = self.cor_do_tema("editor.fundo").name()
        texto = self.cor_do_tema("editor.texto").name()
        self.tabela.setStyleSheet(
            f"QTableView {{ background: {fundo}; color: {texto}; "
            f"gridline-color: {self.cor_do_tema('janela.texto_apagado').name()}; "
            f"selection-background-color: "
            f"{self.cor_do_tema('janela.destaque').name()}; }}")

    def desfazer(self) -> None:
        """Ctrl+Z numa planilha volta uma celula.

        A pilha e' da `Pasta`, e nao do Qt: quem sabe o que a celula era antes
        -- inclusive se ela nem existia -- e' o modelo da planilha, nao o
        widget.
        """
        passo = self.pasta.desfazer()
        self._apos_passo(passo, "Não há mais nada para desfazer.")

    def refazer(self) -> None:
        passo = self.pasta.refazer()
        self._apos_passo(passo, "Não há mais nada para refazer.")

    def _apos_passo(self, passo, recusa: str) -> None:
        if passo is None:
            self.recusou.emit(recusa)
            return

        # A aba do passo pode nao ser a que esta' na frente: desfazer tem de
        # levar a pessoa ate' onde a mudanca aconteceu, senao ela ve' o atalho
        # "nao fazer nada".
        indice = self.pasta.folhas.index(passo.folha)
        if self.abas.currentIndex() != indice:
            self.abas.setCurrentIndex(indice)

        modelo = self.tabela.model()
        if modelo is not None:
            modelo.layoutChanged.emit()
            alvo = modelo.index(passo.linha - 1, passo.coluna - 1)
            if alvo.isValid():
                self.tabela.setCurrentIndex(alvo)
                self.tabela.scrollTo(alvo)
        self.sujou.emit()

    def copiar(self) -> None:
        from PySide6.QtGui import QGuiApplication

        indice = self.tabela.currentIndex()
        if indice.isValid():
            QGuiApplication.clipboard().setText(
                str(self.tabela.model().data(indice) or ""))
