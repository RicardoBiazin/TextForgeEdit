"""Grade de CSV que le' o arquivo SOB DEMANDA.

A grade do TextForge nao serve aqui, e nao e' questao de ajuste: ela carrega o
texto inteiro e o fatia em `registros_crus` -- uma `str` por registro, todas na
memoria ao mesmo tempo. Para 240 MB de CSV isso sao varios GB entre a `str`
completa, a lista de registros e o custo por objeto do Python.

Aqui o modelo NAO tem os dados. `rowCount` e' o total de linhas do indice, e
`data()` le' a linha pedida na hora, por `Documento.faixa()`. O que existe na
memoria e' um punhado de blocos recentes.

O CACHE POR BLOCO, E POR QUE ELE NAO E' OPCIONAL

O `data()` do Qt e' chamado uma vez por celula E POR PAPEL -- texto,
alinhamento, cor, dica. Numa tela de 30 linhas por 8 colunas sao centenas de
chamadas por repintura. Uma `faixa()` por chamada seria uma travessia da tabela
de pecas por celula, e `offset_da_linha` custa O(numero de pecas): num
documento com 10 mil edicoes, cada celula pagaria 10 mil passos.

Com blocos de 256 linhas, a mesma tela custa uma ou duas travessias.

ORDENACAO: A v1 NAO ORDENA, E O CABECALHO NAO FINGE QUE ORDENA

Um `QSortFilterProxyModel` pede `data()` de TODAS as linhas no primeiro clique
no cabecalho. Num CSV de 13 milhoes de linhas sao 13 milhoes de `faixa()`, e a
lista de chaves sozinha passa de meio giga -- com a interface congelada, e tudo
isso disparado por um clique acidental num cabecalho. `chave_de_ordenacao` ja'
esta' portada em `csv_dialeto` para quando isto virar um comando explicito, com
teto, no espirito do `TETO_DE_SUBSTITUICOES`.
"""

from __future__ import annotations

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHeaderView, QTableView

from tfedit import csv_dialeto, log_interno
from tfedit.interface.visualizadores.base import VisualizadorDeDocumento

log = log_interno.obter(__name__)

#: Linhas por bloco do cache. Ver o cabecalho.
BLOCO = 256

#: Quantos blocos ficam na memoria. 8 x 256 = 2048 linhas, o bastante para
#: rolar sem recarregar e pouco o bastante para nao pesar.
MAX_BLOCOS = 8

#: Quantas linhas medir para escolher a largura das colunas. NUNCA
#: `resizeColumnsToContents()`: ele pergunta ao modelo por TODA linha, o que
#: aqui e' ler o arquivo inteiro num clique.
LINHAS_PARA_MEDIR = 200

LARGURA_MINIMA = 60
LARGURA_MAXIMA = 400

#: Quanto esperar antes de recontar as linhas durante a varredura. O indexador
#: emite progresso muitas vezes por segundo, e um `beginInsertRows` por emissao
#: repinta a grade sem parar.
ESPERA_PARA_RECONTAR_MS = 200


class ModeloCsv(QAbstractTableModel):
    """Le' do `Documento` sob demanda. Ver o cabecalho."""

    recusou = Signal(str)
    sujou = Signal()

    def __init__(self, documento, perfil, dialeto, parent=None) -> None:
        super().__init__(parent)
        self.documento = documento
        self.perfil = perfil
        self.dialeto = dialeto
        self._cache: dict[int, list[list[str]]] = {}
        self._ordem: list[int] = []
        self._suspeitas: set[int] = set()
        self._avisou_de_suspeita = False
        self._colunas = max(1, dialeto.colunas)
        self._linhas = self._contar()

    # ==================================================================
    # Forma
    # ==================================================================

    def _contar(self) -> int:
        total = self.documento.total_de_linhas
        # `total_de_linhas` conta a linha VAZIA que vem depois do "\n" final --
        # e' a convencao de `split("\n")`. Sem este desconto, todo CSV
        # bem-formado abriria com uma linha em branco no fim.
        if self.documento.tamanho > 0:
            try:
                if self.documento.ler(self.documento.tamanho - 1,
                                      self.documento.tamanho) in (b"\n", b"\r"):
                    total -= 1
            except Exception:                 # noqa: BLE001 - nunca derrubar
                pass
        if self.dialeto.tem_cabecalho:
            total -= 1
        return max(0, total)

    def rowCount(self, pai=QModelIndex()) -> int:         # noqa: N802 - Qt
        return 0 if pai.isValid() else self._linhas

    def columnCount(self, pai=QModelIndex()) -> int:      # noqa: N802 - Qt
        return 0 if pai.isValid() else self._colunas

    def linha_no_documento(self, linha_da_grade: int) -> int:
        return linha_da_grade + (1 if self.dialeto.tem_cabecalho else 0)

    # ==================================================================
    # Leitura
    # ==================================================================

    def _carregar_bloco(self, indice: int) -> list[list[str]]:
        base = indice * BLOCO
        cruas = self.documento.faixa(base, base + BLOCO)
        bloco = []
        for deslocamento, bruta in enumerate(cruas):
            registro = bruta.decode(self.perfil.codec, errors="replace")
            if csv_dialeto.linha_suspeita(registro, self.dialeto):
                self._suspeitas.add(base + deslocamento)
            bloco.append(csv_dialeto.campos_de(registro, self.dialeto))

        self._cache[indice] = bloco
        self._ordem.append(indice)
        while len(self._ordem) > MAX_BLOCOS:
            self._cache.pop(self._ordem.pop(0), None)

        # Uma linha mais larga que o esperado ALARGA a grade. Nunca estreita:
        # encolher exigiria conhecer a maior linha do arquivo inteiro.
        maior = max((len(campos) for campos in bloco), default=0)
        if maior > self._colunas:
            self.beginInsertColumns(QModelIndex(), self._colunas, maior - 1)
            self._colunas = maior
            self.endInsertColumns()
        return bloco

    def _campos(self, linha_no_documento: int) -> list[str]:
        indice = linha_no_documento // BLOCO
        bloco = self._cache.get(indice)
        if bloco is None:
            bloco = self._carregar_bloco(indice)
        posicao = linha_no_documento % BLOCO
        return bloco[posicao] if posicao < len(bloco) else []

    def registro_cru(self, linha_no_documento: int):
        """A linha inteira, decodificada. `None` quando nao da' para ler.

        O cache guarda os campos ja' repartidos; para mapear uma coluna de
        CARACTERE e' preciso a linha crua, que e' onde as posicoes da busca
        fazem sentido.
        """
        try:
            cruas = self.documento.faixa(linha_no_documento,
                                         linha_no_documento + 1)
        except Exception:                     # noqa: BLE001 - nunca derrubar
            return None
        if not cruas:
            return None
        return cruas[0].decode(self.perfil.codec, errors="replace")

    def _invalidar(self, linha_no_documento: int) -> None:
        indice = linha_no_documento // BLOCO
        if self._cache.pop(indice, None) is not None:
            self._ordem = [i for i in self._ordem if i != indice]

    # ==================================================================
    # Papeis
    # ==================================================================

    def data(self, indice, papel=Qt.ItemDataRole.DisplayRole):
        if not indice.isValid():
            return None
        linha_doc = self.linha_no_documento(indice.row())
        campos = self._campos(linha_doc)
        valor = (campos[indice.column()]
                 if indice.column() < len(campos) else "")

        if papel in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return valor
        if papel == Qt.ItemDataRole.TextAlignmentRole:
            # Coluna numerica a' direita. Sai de graca: o campo ja' esta' em
            # maos, e e' o que torna uma coluna de valores legivel.
            if csv_dialeto.e_numero(valor):
                return int(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            return int(Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter)
        if papel == Qt.ItemDataRole.ToolTipRole and linha_doc in self._suspeitas:
            return ("Esta linha tem aspas sem fechar: o registro provavelmente "
                    "continua na linha seguinte. A grade mostra cada linha "
                    "física como um registro, então ela não pode ser editada "
                    "aqui.")
        return None

    def headerData(self, secao, orientacao,               # noqa: N802 - Qt
                   papel=Qt.ItemDataRole.DisplayRole):
        if papel != Qt.ItemDataRole.DisplayRole:
            return None
        if orientacao == Qt.Orientation.Horizontal:
            if self.dialeto.tem_cabecalho:
                cabecalho = self._campos(0)
                if secao < len(cabecalho) and cabecalho[secao].strip():
                    return cabecalho[secao]
            return f"Coluna {secao + 1}"
        return str(self.linha_no_documento(secao) + 1)

    def flags(self, indice) -> Qt.ItemFlag:
        base = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if not indice.isValid():
            return Qt.ItemFlag.NoItemFlags
        # Editar antes de a varredura acabar daria contagem de linha errada --
        # a mesma regra que o editor de texto segue.
        if not self.documento.pode_editar:
            return base
        if self.linha_no_documento(indice.row()) in self._suspeitas:
            # Nao se corrompe o que nao se consegue analisar. Ver o cabecalho
            # de `csv_dialeto`.
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    # ==================================================================
    # Escrita
    # ==================================================================

    def setData(self, indice, valor,                      # noqa: N802 - Qt
                papel=Qt.ItemDataRole.EditRole) -> bool:
        if papel != Qt.ItemDataRole.EditRole or not indice.isValid():
            return False
        if not self.documento.pode_editar:
            return False

        texto = str(valor)
        if "\n" in texto or "\r" in texto:
            # Um valor com quebra viraria um registro de varias linhas, e a
            # grade trabalha com uma linha = um registro. Aceitar deslocaria a
            # tabela inteira dali para a frente.
            self.recusou.emit(
                "Um valor de célula não pode conter quebra de linha.")
            return False

        linha_doc = self.linha_no_documento(indice.row())
        inicio = self.documento.offset_da_linha(linha_doc)
        fim = self.documento.offset_da_linha(linha_doc + 1)
        bruto = self.documento.ler(inicio, fim)

        # O TERMINADOR VEM DA PROPRIA LINHA, e nao de `perfil.fim_de_linha`.
        # Ha' arquivo com fim de linha MISTO, e reescrever esta linha com o
        # terminador majoritario do arquivo trocaria bytes que ninguem mandou
        # trocar.
        miolo, terminador = bruto, b""
        for candidato in (b"\r\n", b"\n", b"\r"):
            if bruto.endswith(candidato):
                miolo = bruto[:-len(candidato)]
                terminador = candidato
                break

        registro = miolo.decode(self.perfil.codec, errors="replace")
        fatias = csv_dialeto.fatias_de_campos(registro, self.dialeto)
        campo = csv_dialeto.montar_registro([texto], self.dialeto)

        coluna = indice.column()
        if coluna < len(fatias):
            # SO' os bytes deste campo. Reconstruir o registro inteiro com
            # `montar_registro` reescreveria todos os campos com o quoting
            # minimo do modulo `csv` -- tirando aspas legitimas de campos que
            # ninguem tocou, o que e' alteracao silenciosa de conteudo.
            de, ate = fatias[coluna]
            candidato = registro[:de] + campo + registro[ate:]
        else:
            faltam = coluna - len(fatias) + 1
            candidato = registro + self.dialeto.delimitador * faltam + campo

        try:
            dados = candidato.encode(self.perfil.codec)
        except UnicodeEncodeError as erro:
            # `errors="replace"` gravaria "?" sobre um dado que nao volta -- a
            # mesma recusa de `conversao.py`.
            ruim = candidato[erro.start:erro.start + 1]
            self.recusou.emit(
                f"O caractere {ruim!r} não existe em {self.perfil.rotulo}. "
                f"A célula não foi alterada.")
            return False

        with self.documento.agrupar():
            self.documento.substituir(inicio, fim - inicio,
                                      dados + terminador)
        self._invalidar(linha_doc)
        self.dataChanged.emit(indice, indice)
        self.sujou.emit()
        return True

    # ==================================================================
    # A varredura continua
    # ==================================================================

    def recontar(self) -> None:
        novo = self._contar()
        if novo == self._linhas:
            return
        if novo > self._linhas:
            self.beginInsertRows(QModelIndex(), self._linhas, novo - 1)
            self._linhas = novo
            self.endInsertRows()
        else:
            # Encolher (linhas apagadas no modo texto) e' raro, e um reset e'
            # mais barato de acertar que de errar.
            self.beginResetModel()
            self._linhas = novo
            self._cache.clear()
            self._ordem.clear()
            self.endResetModel()

    def esquecer_tudo(self) -> None:
        """O documento mudou por fora: o cache inteiro esta' velho."""
        self.beginResetModel()
        self._cache.clear()
        self._ordem.clear()
        self._suspeitas.clear()
        self._linhas = self._contar()
        self.endResetModel()


class GradeCsv(VisualizadorDeDocumento, QTableView):
    """A grade. Ver o cabecalho do modulo."""

    # Declarados aqui, e nao no mixin: o PySide6 so' registra `Signal` numa
    # classe que ja' e' QObject. Ver o cabecalho de `base.py`.
    posicao_mudou = Signal(int, int)
    sujou = Signal()
    recusou = Signal(str)

    nome = "tabela"
    editavel = True

    def __init__(self, documento, perfil, dialeto, parent=None, *, tema=None,
                 cfg=None) -> None:
        QTableView.__init__(self, parent)
        self.preparar(documento, perfil, tema=tema, cfg=cfg)
        self.dialeto = dialeto

        self.modelo = ModeloCsv(documento, perfil, dialeto, self)
        self.modelo.recusou.connect(self.recusou)
        self.modelo.sujou.connect(self.sujou)
        self.setModel(self.modelo)

        fonte = QFont(str(self.cfg.get("fonte", "Consolas")),
                      int(self.cfg.get("fonte_tamanho", 11)))
        fonte.setFixedPitch(True)
        self.setFont(fonte)

        # Rolagem por ITEM, nunca por pixel: em pixels, 13 milhoes de linhas
        # estouram o inteiro de 32 bits da barra. Mesmo motivo do visor
        # hexadecimal.
        self.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerItem)
        self.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerItem)

        # O cabecalho NAO finge que ordena. Ver o cabecalho do modulo.
        self.setSortingEnabled(False)
        self.horizontalHeader().setSectionsClickable(False)

        vertical = self.verticalHeader()
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        vertical.setDefaultSectionSize(
            QFontMetrics(fonte).height() + 6)
        self._ajustar_cabecalho_vertical()
        self._medir_colunas()

        self.selectionModel().currentChanged.connect(self._ao_mover)

        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.setInterval(ESPERA_PARA_RECONTAR_MS)
        self._relogio.timeout.connect(self.modelo.recontar)

    # ==================================================================
    # Aparencia
    # ==================================================================

    def _ajustar_cabecalho_vertical(self) -> None:
        # Largura calculada dos DIGITOS: o `ResizeToContents` padrao consulta
        # todas as linhas para medir, que aqui e' ler o arquivo inteiro.
        digitos = len(str(max(1, self.documento.total_de_linhas)))
        largura = QFontMetrics(self.font()).horizontalAdvance("0") * digitos
        self.verticalHeader().setFixedWidth(largura + 16)

    def _medir_colunas(self) -> None:
        """Largura pelas primeiras linhas, e nunca pelo arquivo inteiro."""
        metrica = QFontMetrics(self.font())
        larguras = [len(self.modelo.headerData(
            c, Qt.Orientation.Horizontal) or "")
            for c in range(self.modelo.columnCount())]
        quantas = min(LINHAS_PARA_MEDIR, self.modelo.rowCount())
        for linha in range(quantas):
            campos = self.modelo._campos(self.modelo.linha_no_documento(linha))
            for coluna, valor in enumerate(campos[:len(larguras)]):
                larguras[coluna] = max(larguras[coluna], len(valor))
        for coluna, colunas_de_texto in enumerate(larguras):
            largura = metrica.horizontalAdvance("0") * (colunas_de_texto + 2)
            self.setColumnWidth(
                coluna, max(LARGURA_MINIMA, min(LARGURA_MAXIMA, largura)))

    def aplicar_tema(self, tema) -> None:
        VisualizadorDeDocumento.aplicar_tema(self, tema)
        fundo = self.cor_do_tema("editor.fundo").name()
        texto = self.cor_do_tema("editor.texto").name()
        destaque = self.cor_do_tema("janela.destaque").name()
        self.setStyleSheet(
            f"QTableView {{ background: {fundo}; color: {texto}; "
            f"gridline-color: {self.cor_do_tema('janela.texto_apagado').name()}; "
            f"selection-background-color: {destaque}; }}")

    # ==================================================================
    # O contrato da view
    # ==================================================================

    def _ao_mover(self, atual, _anterior) -> None:
        if atual.isValid():
            self.posicao_mudou.emit(
                self.modelo.linha_no_documento(atual.row()),
                atual.column())

    def atualizar(self) -> None:
        if not self._vivo:
            return
        # Estrangulado: o indexador emite progresso muitas vezes por segundo.
        self._relogio.start()

    def sincronizar(self) -> bool:
        """Fecha o editor de celula aberto.

        Sem isto, salvar com uma celula em edicao gravaria o arquivo sem o que
        estava sendo digitado nela.
        """
        if self.state() == QTableView.State.EditingState:
            self.closePersistentEditor(self.currentIndex())
            self.setState(QTableView.State.NoState)
            return True
        return False

    def linha_atual(self) -> int:
        indice = self.currentIndex()
        if not indice.isValid():
            return 0
        return self.modelo.linha_no_documento(indice.row())

    def ir_para_linha(self, linha: int) -> None:
        alvo = max(0, linha - (1 if self.dialeto.tem_cabecalho else 0))
        alvo = min(alvo, max(0, self.modelo.rowCount() - 1))
        indice = self.modelo.index(alvo, 0)
        if indice.isValid():
            self.setCurrentIndex(indice)
            self.scrollTo(indice)

    def ir_para_achado(self, linha: int, coluna_de_caractere: int) -> None:
        """Leva o cursor ate' a CELULA que contem aquele caractere.

        A busca trabalha em (linha, coluna de CARACTERE dentro da linha) -- e' o
        que o `busca.Achado` devolve. Na grade isso nao e' uma coluna: a coluna
        3 de caracteres pode estar no primeiro campo ou no quarto, conforme o
        tamanho dos anteriores. `fatias_de_campos` diz onde cada campo comeca e
        acaba na linha crua, e a ocorrencia cai dentro de exatamente um deles.

        Antes disto, procurar dentro da grade EXPULSAVA o usuario para o modo
        texto: a visualizacao em colunas se perdia justamente na hora em que
        ela mais serve, que e' a de conferir um valor achado.
        """
        self.ir_para_linha(linha)
        indice = self.currentIndex()
        if not indice.isValid():
            return

        registro = self.modelo.registro_cru(linha)
        if registro is None:
            return
        fatias = csv_dialeto.fatias_de_campos(registro, self.dialeto)
        alvo = 0
        for numero, (comeco, fim) in enumerate(fatias):
            if comeco <= coluna_de_caractere < fim:
                alvo = numero
                break
            # Um achado que cai EM CIMA do separador (ou passa do fim da
            # linha) fica no campo anterior, em vez de nao ir a lugar nenhum.
            if coluna_de_caractere >= fim:
                alvo = numero

        alvo = min(alvo, max(0, self.modelo.columnCount() - 1))
        celula = self.modelo.index(indice.row(), alvo)
        if celula.isValid():
            self.setCurrentIndex(celula)
            self.scrollTo(celula)

    def desfazer(self) -> None:
        """Ctrl+Z na grade desfaz na TABELA DE PECAS.

        O desfazer sempre existiu: `setData` grava por `documento.substituir`
        dentro de um `agrupar()`, entao cada celula editada e' uma operacao. O
        que faltava era o comando CHEGAR aqui -- ver `EDICAO_NA_VIEW`.

        O cache tem de ser esquecido inteiro: a operacao desfeita pode ter sido
        num bloco que nao esta' na tela, e um cache parcialmente velho mostraria
        a celula antiga ao rolar ate' la'.
        """
        if not self.documento.pode_desfazer:
            self.recusou.emit("Não há mais nada para desfazer.")
            return
        offset = self.documento.desfazer()
        self._apos_desfazer(offset)

    def refazer(self) -> None:
        if not self.documento.pode_refazer:
            self.recusou.emit("Não há mais nada para refazer.")
            return
        offset = self.documento.refazer()
        self._apos_desfazer(offset)

    def _apos_desfazer(self, offset) -> None:
        self.modelo.esquecer_tudo()
        self.sujou.emit()
        if offset is None:
            return
        try:
            linha_doc = self.documento.linha_do_offset(offset)
        except Exception:                     # noqa: BLE001 - nunca derrubar
            return
        # Leva o cursor ao que acabou de mudar: desfazer uma edicao fora da tela
        # sem mostrar onde deixa a pessoa sem saber se algo aconteceu.
        self.ir_para_linha(linha_doc)

    def encerrar(self) -> None:
        VisualizadorDeDocumento.encerrar(self)
        self._relogio.stop()
