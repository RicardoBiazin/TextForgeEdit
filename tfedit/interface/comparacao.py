"""A janela de comparação: dois painéis alinhados, lado a lado.

Desenha sozinha, num `QAbstractScrollArea`, pelo mesmo motivo do visualizador
hexadecimal: a rolagem é em unidade de LINHA, e não de pixel. Dois arquivos de
um milhão de linhas dariam um intervalo de barra que não cabe no inteiro de 32
bits que o Qt usa.

E lê SOB DEMANDA. A comparação guarda blocos, não linhas alinhadas (ver
`tfedit/comparacao.py`); esta janela pede à tabela de peças só as linhas que
estão na tela, uma leitura por painel e por repintura.

A ROLAGEM É UMA SÓ, e não duas sincronizadas: os dois painéis mostram a mesma
faixa de linhas EXIBIDAS, e é a comparação que diz qual linha de cada arquivo
cai em cada altura. Sincronizar duas barras seria reintroduzir o problema que o
alinhamento já resolveu.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (QAbstractScrollArea, QLabel, QMainWindow,
                               QStatusBar, QToolBar, QWidget)

from tfedit import comparacao as nucleo
from tfedit import log_interno

log = log_interno.obter(__name__)

#: Quanto de folga entre a margem de números e o texto.
FOLGA = 8


class _Paineis(QAbstractScrollArea):
    """Os dois lados. Ver o cabeçalho do módulo."""

    def __init__(self, comp, doc_a, doc_b, perfil_a, perfil_b,
                 tema, cfg, parent=None) -> None:
        super().__init__(parent)
        self.comp = comp
        self.doc_a = doc_a
        self.doc_b = doc_b
        self.perfil_a = perfil_a
        self.perfil_b = perfil_b
        self.tema = tema
        self.cfg = cfg or {}

        fonte = QFont(str(self.cfg.get("fonte", "Consolas")),
                      int(self.cfg.get("fonte_tamanho", 11)))
        fonte.setFixedPitch(True)
        fonte.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(fonte)

        metrica = QFontMetrics(fonte)
        self._largura = metrica.horizontalAdvance("0") or 8
        self._altura = metrica.height() or 12
        self._base = metrica.ascent()
        self._digitos = max(4, len(str(max(comp.total_a, comp.total_b))))

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(
            lambda _v: self.viewport().update())
        self.horizontalScrollBar().valueChanged.connect(
            lambda _v: self.viewport().update())
        self._ajustar()

    # ==================================================================

    def linhas_visiveis(self) -> int:
        return max(1, self.viewport().height() // self._altura)

    def _ajustar(self) -> None:
        barra = self.verticalScrollBar()
        barra.setRange(0, max(0, self.comp.total_exibido
                              - self.linhas_visiveis()))
        barra.setPageStep(self.linhas_visiveis())
        barra.setSingleStep(1)
        self.horizontalScrollBar().setRange(0, 400)
        self.horizontalScrollBar().setSingleStep(self._largura)

    def resizeEvent(self, evento) -> None:                # noqa: N802 - Qt
        QAbstractScrollArea.resizeEvent(self, evento)
        self._ajustar()

    def _cor(self, caminho: str) -> QColor:
        return self.tema.cor(caminho)

    def _cor_do_tipo(self, tipo: str) -> QColor | None:
        """O fundo de cada tipo de linha.

        Usa papéis que JÁ existem nos temas (`editor.ocorrencia` e afins). Um
        papel novo daria cor de emergência num tema do usuário -- `tema.cor` só
        avisa no log quando a chave falta.
        """
        if tipo == nucleo.IGUAL:
            return None
        if tipo == nucleo.ALTERADA:
            return self._cor("editor.ocorrencia_atual")
        if tipo == nucleo.SO_A:
            return self._cor("editor.selecao")
        return self._cor("editor.ocorrencia")

    # ==================================================================

    def paintEvent(self, evento) -> None:                 # noqa: N802 - Qt
        pintor = QPainter(self.viewport())
        pintor.setFont(self.font())
        pintor.fillRect(evento.rect(), self._cor("editor.fundo"))

        primeira = self.verticalScrollBar().value()
        quantas = self.linhas_visiveis() + 1
        pares = self.comp.faixa(primeira, quantas)
        if not pares:
            return

        # UMA leitura por painel, e não uma por linha: `faixa` do documento faz
        # uma travessia só da tabela de peças.
        texto_a = self._ler(self.doc_a, self.perfil_a,
                            [p.linha_a for p in pares])
        texto_b = self._ler(self.doc_b, self.perfil_b,
                            [p.linha_b for p in pares])

        largura = self.viewport().width()
        meio = largura // 2
        margem = (self._digitos + 1) * self._largura
        rolagem = self.horizontalScrollBar().value()

        cor_numero = self._cor("editor.margem_texto")
        cor_texto = self._cor("editor.texto")

        for i, par in enumerate(pares):
            y = i * self._altura
            fundo = self._cor_do_tipo(par.tipo)
            for lado, (inicio, fim) in enumerate(
                    ((0, meio - 2), (meio + 2, largura))):
                numero = par.linha_a if lado == 0 else par.linha_b
                conteudo = texto_a if lado == 0 else texto_b
                if fundo is not None:
                    pintor.fillRect(inicio, y, fim - inicio, self._altura,
                                    fundo)
                if numero is None:
                    continue
                pintor.setPen(cor_numero)
                pintor.drawText(inicio + 2, y + self._base,
                                f"{numero + 1:>{self._digitos}}")
                pintor.setPen(cor_texto)
                pintor.setClipRect(inicio, y, fim - inicio, self._altura)
                pintor.drawText(inicio + margem + FOLGA - rolagem,
                                y + self._base, conteudo.get(numero, ""))
                pintor.setClipping(False)

        # A divisória entre os dois painéis.
        pintor.setPen(self._cor("janela.borda"))
        pintor.drawLine(meio, 0, meio, self.viewport().height())

    def _ler(self, documento, perfil, numeros) -> dict[int, str]:
        """As linhas pedidas, numa leitura só por painel."""
        reais = [n for n in numeros if n is not None]
        if not reais:
            return {}
        inicio, fim = min(reais), max(reais) + 1
        cruas = documento.faixa(inicio, fim)
        codec = perfil.codec if perfil is not None else "utf-8"
        return {inicio + k: bruta.decode(codec, errors="replace")
                for k, bruta in enumerate(cruas)}

    # ==================================================================

    def ir_para(self, linha: int) -> None:
        barra = self.verticalScrollBar()
        barra.setValue(max(0, min(linha, barra.maximum())))

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


class JanelaDeComparacao(QMainWindow):
    """Janela própria, e não uma aba: uma aba pertence a UM arquivo."""

    def __init__(self, comp, doc_a, doc_b, nome_a, nome_b,
                 perfil_a=None, perfil_b=None, *, tema=None, cfg=None,
                 parent=None) -> None:
        super().__init__(parent)
        self.comp = comp
        self.setWindowTitle(f"Comparar: {nome_a} × {nome_b}")
        self.resize(1200, 700)

        self.paineis = _Paineis(comp, doc_a, doc_b, perfil_a, perfil_b,
                                tema, cfg, self)
        self.setCentralWidget(self.paineis)

        barra = QToolBar("Comparação", self)
        barra.setMovable(False)
        anterior = QAction("◀ Diferença anterior", self)
        anterior.setShortcut("Shift+F7")
        anterior.triggered.connect(self.anterior)
        proxima = QAction("Próxima diferença ▶", self)
        proxima.setShortcut("F7")
        proxima.triggered.connect(self.proxima)
        barra.addAction(anterior)
        barra.addAction(proxima)
        barra.addSeparator()
        barra.addWidget(QLabel(f"  {nome_a}   ×   {nome_b}  ", self))
        self.addToolBar(barra)

        self.rodape = QStatusBar(self)
        self.setStatusBar(self.rodape)
        self.rodape.showMessage(comp.resumo.descrever())

    def proxima(self) -> None:
        alvo = self.comp.proxima_diferenca(
            self.paineis.verticalScrollBar().value())
        if alvo is None:
            self.rodape.showMessage(
                "Não há mais diferenças abaixo.", 5000)
            return
        self.paineis.ir_para(alvo)

    def anterior(self) -> None:
        alvo = self.comp.diferenca_anterior(
            self.paineis.verticalScrollBar().value())
        if alvo is None:
            self.rodape.showMessage("Não há diferenças acima.", 5000)
            return
        self.paineis.ir_para(alvo)
