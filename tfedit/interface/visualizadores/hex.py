"""Visualizador hexadecimal: offset, bytes e ASCII, sobre arquivo de 1 GB.

    00000000  48 65 6c 6c 6f 2c 20 6d  75 6e 64 6f 21 0d 0a 41  |Hello, mundo!..A|

POR QUE UM QAbstractScrollArea, E NAO UM QTableView VIRTUAL

Um QTableView com modelo virtual pareceria mais barato de escrever, e quebra em
dois pontos que so' aparecem em arquivo grande:

**A barra de rolagem estoura o int32.** Com `ScrollPerPixel`, 1 GB sao 67
milhoes de linhas de 16 bytes; a 16 px por linha, o intervalo da barra passa de
um bilhao, e um pouco acima de 4 GB de arquivo o valor nao cabe mais no inteiro
de 32 bits que o Qt usa. Rolando em unidade de LINHA, o mesmo inteiro aguenta
32 GB de arquivo.

**Sao 17 chamadas por linha visivel, contra 3.** O `data()` do modelo e'
chamado uma vez por celula E por papel -- 16 colunas de byte mais a coluna
ASCII, vezes tres ou quatro papeis. Aqui cada linha e' um `drawText` do offset,
um dos bytes e um do ASCII.

Ha' precedente no projeto: a `Margem` do editor (`interface/editor.py`) ja' e'
um widget com `paintEvent` proprio.

UMA LEITURA POR REPINTURA

O `paintEvent` pede ao documento UM bloco com tudo o que a tela mostra -- cerca
de 1 KB. Uma leitura por linha seriam quarenta travessias da tabela de pecas
para os mesmos 640 bytes, porque `Documento.ler` percorre a lista de pecas a
cada chamada. E' isto que faz o custo por quadro nao depender do tamanho do
arquivo.

O QUE ELE MOSTRA E' O DOCUMENTO, NAO O DISCO

Ele le' do `Documento`, e nao do `Original`: o que foi digitado no modo texto e
ainda nao foi gravado aparece aqui. Se lesse o `Original`, o visor mostraria o
arquivo de antes da edicao e ninguem entenderia por que.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QAbstractScrollArea

from tfedit import log_interno
from tfedit.interface.visualizadores.base import VisualizadorDeDocumento

log = log_interno.obter(__name__)

BYTES_POR_LINHA = 16

#: Espaco a mais no meio da linha. Sem ele nao da' para contar byte a olho.
METADE = BYTES_POR_LINHA // 2

#: Teto do que o Ctrl+C materializa, em bytes do arquivo.
#:
#: A area de transferencia guarda uma `str`: copiar 1 GB construiria alguns GB
#: de texto e anularia o projeto inteiro. Um mega de dump ja' e' muito mais do
#: que alguem cola em algum lugar.
TETO_DE_COPIA = 1 << 20

#: Tabelas prontas. Formatar byte a byte com f-string custa caro num laco que
#: roda a cada quadro.
#: Colunas que a parte hexadecimal ocupa: 3 por byte ("48 "), menos o espaco
#: final, mais o espaco extra do meio. `_x_do_ascii` conta a mesma coisa.
LARGURA_DO_HEX = BYTES_POR_LINHA * 3 - 1 + 1

_HEX = tuple(f"{b:02x}" for b in range(256))
_ASCII = tuple(chr(b) if 32 <= b < 127 else "." for b in range(256))


class VisorHexadecimal(VisualizadorDeDocumento, QAbstractScrollArea):
    """Somente leitura. Ver o cabecalho."""

    # Declarados AQUI, e nao no mixin: o PySide6 so' registra `Signal` numa
    # classe que ja' e' QObject. Ver o cabecalho de `base.py`.
    posicao_mudou = Signal(int, int)
    sujou = Signal()
    recusou = Signal(str)

    nome = "hex"
    editavel = False

    def __init__(self, documento, perfil, parent=None, *, tema=None,
                 cfg=None) -> None:
        QAbstractScrollArea.__init__(self, parent)
        self.preparar(documento, perfil, tema=tema, cfg=cfg)

        fonte = QFont(str(self.cfg.get("fonte", "Consolas")),
                      int(self.cfg.get("fonte_tamanho", 11)))
        fonte.setFixedPitch(True)
        fonte.setStyleHint(QFont.StyleHint.Monospace)
        # A alternativa entra quando a fonte pedida nao existe. Sem passo fixo
        # as colunas do hexadecimal desalinham, e um dump desalinhado nao
        # serve para nada.
        alternativa = str(self.cfg.get("fonte_alternativa", "Courier New"))
        if alternativa:
            fonte.setFamilies([fonte.family(), alternativa])
        self.setFont(fonte)

        # (ancora, cabeca) em offsets de byte. A selecao de um visor
        # hexadecimal e' uma FAIXA de bytes, e nao um retangulo de celulas.
        self._ancora: int | None = None
        self._cabeca: int | None = None
        self._arrastando = False

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self._ao_rolar)
        self._medir()
        self._ajustar_barras()

    # ==================================================================
    # Geometria
    # ==================================================================

    def _medir(self) -> None:
        metrica = QFontMetrics(self.font())
        self._largura = metrica.horizontalAdvance("0") or 8
        self._altura = metrica.height() or 12
        self._base = metrica.ascent()
        # Oito digitos ate' 4 GB; dez acima disso. Um arquivo de 5 GB com
        # offset de 8 digitos mostraria enderecos repetidos.
        self._digitos = 8 if self.documento.tamanho <= 0xFFFFFFFF else 10

    @property
    def total_de_linhas(self) -> int:
        if self.documento.tamanho <= 0:
            return 1
        return (self.documento.tamanho + BYTES_POR_LINHA - 1) // BYTES_POR_LINHA

    def linhas_visiveis(self) -> int:
        return max(1, self.viewport().height() // self._altura)

    def _ajustar_barras(self) -> None:
        barra = self.verticalScrollBar()
        ultima = max(0, self.total_de_linhas - self.linhas_visiveis())
        barra.setRange(0, ultima)
        barra.setPageStep(self.linhas_visiveis())
        # Passo de UMA LINHA, nunca de pixel. Ver o cabecalho.
        barra.setSingleStep(1)

    def _x_dos_bytes(self) -> int:
        return (self._digitos + 2) * self._largura

    def _x_do_ascii(self) -> int:
        # 3 colunas por byte ("48 ") mais o espaco extra do meio.
        return self._x_dos_bytes() + (BYTES_POR_LINHA * 3 + 2) * self._largura

    def _offset_no_ponto(self, ponto: QPoint) -> int | None:
        linha = (self.verticalScrollBar().value()
                 + max(0, ponto.y()) // self._altura)
        x = ponto.x() - self._x_dos_bytes()
        if x < 0:
            return None
        coluna = x // (3 * self._largura)
        if coluna >= METADE:                  # desconta o espaco extra do meio
            coluna = (x - 2 * self._largura) // (3 * self._largura)
        if not 0 <= coluna < BYTES_POR_LINHA:
            return None
        offset = linha * BYTES_POR_LINHA + coluna
        return offset if 0 <= offset < self.documento.tamanho else None

    # ==================================================================
    # Pintura
    # ==================================================================

    def paintEvent(self, evento) -> None:                 # noqa: N802 - Qt
        if not self._vivo:
            # A view pode receber um paintEvent depois de descartada e antes do
            # `deleteLater` -- e nesse instante o mmap ja' pode estar fechado.
            return

        pintor = QPainter(self.viewport())
        pintor.setFont(self.font())
        fundo = self.cor_do_tema("editor.fundo")
        pintor.fillRect(evento.rect(), fundo)

        primeira = self.verticalScrollBar().value()
        quantas = self.linhas_visiveis() + 1
        inicio = primeira * BYTES_POR_LINHA
        fim = min(self.documento.tamanho,
                  (primeira + quantas) * BYTES_POR_LINHA)
        if fim <= inicio:
            return
        # UMA leitura para a tela inteira. Ver o cabecalho.
        bloco = self.documento.ler(inicio, fim)

        cor_offset = self.cor_do_tema("editor.margem_texto")
        cor_texto = self.cor_do_tema("editor.texto")
        cor_apagado = self.cor_do_tema("janela.texto_apagado")
        cor_selecao = self.cor_do_tema("editor.selecao")
        faixa = self.faixa_selecionada()

        for i in range(quantas):
            posicao = i * BYTES_POR_LINHA
            if posicao >= len(bloco):
                break
            y = i * self._altura
            dados = bloco[posicao:posicao + BYTES_POR_LINHA]
            base = inicio + posicao

            if faixa is not None:
                self._pintar_selecao(pintor, y, base, len(dados), faixa,
                                     cor_selecao)

            pintor.setPen(cor_offset)
            pintor.drawText(0, y + self._base,
                            f"{base:0{self._digitos}x}")

            pintor.setPen(cor_texto)
            pintor.drawText(self._x_dos_bytes(), y + self._base,
                            self._linha_hex(dados))

            pintor.setPen(cor_apagado)
            pintor.drawText(self._x_do_ascii(), y + self._base,
                            "|" + "".join(_ASCII[b] for b in dados) + "|")

    @staticmethod
    def _linha_hex(dados: bytes) -> str:
        esquerda = " ".join(_HEX[b] for b in dados[:METADE])
        direita = " ".join(_HEX[b] for b in dados[METADE:])
        if not direita:
            return esquerda
        # DOIS espacos no meio, e a largura fixa da metade esquerda: e' o que
        # mantem a coluna ASCII no mesmo x que `_x_do_ascii` calcula. Um
        # espaco a mais aqui desalinha o dump inteiro em um caractere.
        return f"{esquerda:<{METADE * 3 - 1}}  {direita}"

    def _pintar_selecao(self, pintor, y: int, base: int, quantos: int,
                        faixa: tuple[int, int], cor) -> None:
        de, ate = faixa
        for coluna in range(quantos):
            if not de <= base + coluna < ate:
                continue
            extra = 2 * self._largura if coluna >= METADE else 0
            x = self._x_dos_bytes() + coluna * 3 * self._largura + extra
            pintor.fillRect(x, y, 2 * self._largura, self._altura, cor)
            xa = self._x_do_ascii() + (coluna + 1) * self._largura
            pintor.fillRect(xa, y, self._largura, self._altura, cor)

    # ==================================================================
    # Interacao
    # ==================================================================

    def resizeEvent(self, evento) -> None:                # noqa: N802 - Qt
        QAbstractScrollArea.resizeEvent(self, evento)
        self._ajustar_barras()

    def _ao_rolar(self, _valor: int) -> None:
        self.viewport().update()
        self.posicao_mudou.emit(self.linha_atual(), 0)

    def mousePressEvent(self, evento) -> None:            # noqa: N802 - Qt
        if evento.button() != Qt.MouseButton.LeftButton:
            return
        offset = self._offset_no_ponto(evento.position().toPoint())
        if offset is None:
            return
        self._ancora = self._cabeca = offset
        self._arrastando = True
        self.viewport().update()

    def mouseMoveEvent(self, evento) -> None:             # noqa: N802 - Qt
        if not self._arrastando:
            return
        offset = self._offset_no_ponto(evento.position().toPoint())
        if offset is not None:
            self._cabeca = offset
            self.viewport().update()

    def mouseReleaseEvent(self, evento) -> None:          # noqa: N802 - Qt
        self._arrastando = False

    def keyPressEvent(self, evento) -> None:              # noqa: N802 - Qt
        barra = self.verticalScrollBar()
        tecla = evento.key()
        if tecla == Qt.Key.Key_PageDown:
            barra.setValue(barra.value() + self.linhas_visiveis())
        elif tecla == Qt.Key.Key_PageUp:
            barra.setValue(barra.value() - self.linhas_visiveis())
        elif tecla == Qt.Key.Key_Down:
            barra.setValue(barra.value() + 1)
        elif tecla == Qt.Key.Key_Up:
            barra.setValue(barra.value() - 1)
        elif tecla == Qt.Key.Key_Home:
            barra.setValue(0)
        elif tecla == Qt.Key.Key_End:
            barra.setValue(barra.maximum())
        else:
            QAbstractScrollArea.keyPressEvent(self, evento)

    # ==================================================================
    # Selecao e copia
    # ==================================================================

    def faixa_selecionada(self) -> tuple[int, int] | None:
        if self._ancora is None or self._cabeca is None:
            return None
        de, ate = sorted((self._ancora, self._cabeca))
        return (de, ate + 1)

    def copiar(self) -> None:
        """Copia o DUMP da faixa selecionada, no formato da tela."""
        faixa = self.faixa_selecionada()
        if faixa is None:
            self.recusou.emit("Selecione uma faixa de bytes para copiar.")
            return
        de, ate = faixa
        if ate - de > TETO_DE_COPIA:
            self.recusou.emit(
                f"A seleção tem {(ate - de) / (1024 * 1024):.1f} MB. O limite "
                f"para copiar é de 1 MB — a área de transferência guarda o "
                f"texto inteiro na memória.")
            return

        dados = self.documento.ler(de, ate)
        linhas = []
        for i in range(0, len(dados), BYTES_POR_LINHA):
            pedaco = dados[i:i + BYTES_POR_LINHA]
            linhas.append(
                f"{de + i:0{self._digitos}x}  "
                f"{self._linha_hex(pedaco):<{LARGURA_DO_HEX}}  "
                f"|{''.join(_ASCII[b] for b in pedaco)}|")
        QGuiApplication.clipboard().setText("\n".join(linhas))
        log.info("copiados %d bytes do visor hexadecimal", ate - de)

    # ==================================================================
    # O contrato da view
    # ==================================================================

    def atualizar(self) -> None:
        if not self._vivo:
            return
        self._medir()
        self._ajustar_barras()
        self.viewport().update()

    def linha_atual(self) -> int:
        """A linha do DOCUMENTO, e nao a do dump.

        A barra de status fala em linhas de texto; traduzir aqui e' o que deixa
        o rodape coerente ao trocar de visualizacao.
        """
        offset = self.verticalScrollBar().value() * BYTES_POR_LINHA
        try:
            return self.documento.linha_do_offset(
                min(offset, max(0, self.documento.tamanho - 1)))
        except Exception:                     # noqa: BLE001 - nunca derrubar
            return 0

    def ir_para_linha(self, linha: int) -> None:
        try:
            offset = self.documento.offset_da_linha(max(0, linha))
        except Exception:                     # noqa: BLE001
            return
        self.ir_para_offset(offset)

    def ir_para_offset(self, offset: int) -> None:
        offset = max(0, min(int(offset), max(0, self.documento.tamanho - 1)))
        self.verticalScrollBar().setValue(offset // BYTES_POR_LINHA)
        self._ancora = self._cabeca = offset
        self.viewport().update()

    def aplicar_tema(self, tema) -> None:
        VisualizadorDeDocumento.aplicar_tema(self, tema)
        self.viewport().update()
