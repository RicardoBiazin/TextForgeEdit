"""Os ícones da barra de atalhos, desenhados em código.

POR QUE DESENHADOS, E NAO ARQUIVOS DE IMAGEM

Tres motivos, e o terceiro e' o que decide:

  * o Qt tem pouquissimo icone padrao util para uma barra de editor -- nao ha'
    tesoura, lupa, area de transferencia nem seta de desfazer em
    `QStyle.StandardPixmap`, entao metade da barra ficaria sem simbolo;

  * um PNG embutido tem UMA resolucao. Numa tela 4K com escala de 150% ele
    borra, e teriamos de versionar tres tamanhos de treze icones;

  * **eles seguem o TEMA.** Um icone escuro gravado em arquivo desaparece no
    tema escuro e um claro desaparece no claro. Desenhados, recebem a cor do
    texto da janela e funcionam nos tres temas sem nenhum arquivo a mais.

O DESENHO segue a mesma licao que o icone do programa ensinou: forma GROSSA. A
barra mostra estes simbolos a 16 ou 20 px, e a 16 px um traco de 1 px com folga
de 1 px vira uma mancha cinza. Todas as linhas tem espessura proporcional, e
nenhuma forma tem detalhe menor que um sexto do icone.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

#: Lado do desenho, em pixels. O Qt reduz para o tamanho da barra; desenhar
#: grande e reduzir sai melhor que desenhar em 16 e ampliar.
LADO = 64


def _pintor(cor: QColor) -> tuple[QPixmap, QPainter, QPen]:
    mapa = QPixmap(LADO, LADO)
    mapa.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(mapa)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    caneta = QPen(cor)
    # Espessura proporcional: e' o que mantem o simbolo legivel quando o Qt
    # reduz o desenho para os 16 px da barra.
    caneta.setWidthF(LADO / 12)
    caneta.setCapStyle(Qt.PenCapStyle.RoundCap)
    caneta.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pintor.setPen(caneta)
    return mapa, pintor, caneta


def _fechar(mapa: QPixmap, pintor: QPainter) -> QIcon:
    pintor.end()
    return QIcon(mapa)


# ======================================================================
# Os desenhos
# ======================================================================

def _pagina(pintor: QPainter, esquerda: float, topo: float,
            largura: float, altura: float) -> None:
    """Uma folha com o canto de cima cortado. Base de varios icones."""
    dobra = largura * 0.32
    caminho = QPainterPath()
    caminho.moveTo(esquerda, topo)
    caminho.lineTo(esquerda + largura - dobra, topo)
    caminho.lineTo(esquerda + largura, topo + dobra)
    caminho.lineTo(esquerda + largura, topo + altura)
    caminho.lineTo(esquerda, topo + altura)
    caminho.closeSubpath()
    pintor.drawPath(caminho)


def novo(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    _pagina(pintor, LADO * 0.20, LADO * 0.12, LADO * 0.52, LADO * 0.72)
    # O "+" que diferencia de "abrir": sem ele os dois viram a mesma folha.
    meio = LADO * 0.66
    pintor.drawLine(QPointF(meio - LADO * 0.11, LADO * 0.72),
                    QPointF(meio + LADO * 0.11, LADO * 0.72))
    pintor.drawLine(QPointF(meio, LADO * 0.61), QPointF(meio, LADO * 0.83))
    return _fechar(mapa, pintor)


def abrir(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Pasta: a aba em cima e o corpo embaixo.
    caminho = QPainterPath()
    caminho.moveTo(LADO * 0.14, LADO * 0.78)
    caminho.lineTo(LADO * 0.14, LADO * 0.26)
    caminho.lineTo(LADO * 0.40, LADO * 0.26)
    caminho.lineTo(LADO * 0.48, LADO * 0.36)
    caminho.lineTo(LADO * 0.86, LADO * 0.36)
    caminho.lineTo(LADO * 0.86, LADO * 0.78)
    caminho.closeSubpath()
    pintor.drawPath(caminho)
    return _fechar(mapa, pintor)


def salvar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Uma seta para BAIXO entrando numa bandeja. O disquete nao diz mais nada
    # para quem nunca viu um.
    pintor.drawLine(QPointF(LADO * 0.5, LADO * 0.16),
                    QPointF(LADO * 0.5, LADO * 0.56))
    pintor.drawLine(QPointF(LADO * 0.32, LADO * 0.40),
                    QPointF(LADO * 0.5, LADO * 0.58))
    pintor.drawLine(QPointF(LADO * 0.68, LADO * 0.40),
                    QPointF(LADO * 0.5, LADO * 0.58))
    pintor.drawLine(QPointF(LADO * 0.18, LADO * 0.76),
                    QPointF(LADO * 0.82, LADO * 0.76))
    pintor.drawLine(QPointF(LADO * 0.18, LADO * 0.62),
                    QPointF(LADO * 0.18, LADO * 0.76))
    pintor.drawLine(QPointF(LADO * 0.82, LADO * 0.62),
                    QPointF(LADO * 0.82, LADO * 0.76))
    return _fechar(mapa, pintor)


def salvar_tudo(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # DUAS setas na mesma bandeja: e' o que distingue de "salvar" a 16 px.
    for x in (0.36, 0.64):
        pintor.drawLine(QPointF(LADO * x, LADO * 0.16),
                        QPointF(LADO * x, LADO * 0.52))
        pintor.drawLine(QPointF(LADO * (x - 0.11), LADO * 0.38),
                        QPointF(LADO * x, LADO * 0.54))
        pintor.drawLine(QPointF(LADO * (x + 0.11), LADO * 0.38),
                        QPointF(LADO * x, LADO * 0.54))
    pintor.drawLine(QPointF(LADO * 0.14, LADO * 0.78),
                    QPointF(LADO * 0.86, LADO * 0.78))
    pintor.drawLine(QPointF(LADO * 0.14, LADO * 0.66),
                    QPointF(LADO * 0.14, LADO * 0.78))
    pintor.drawLine(QPointF(LADO * 0.86, LADO * 0.66),
                    QPointF(LADO * 0.86, LADO * 0.78))
    return _fechar(mapa, pintor)


def _seta_curva(pintor: QPainter, para_a_direita: bool) -> None:
    """O arco de desfazer/refazer, com a ponta de seta na extremidade."""
    caminho = QPainterPath()
    if para_a_direita:
        caminho.moveTo(LADO * 0.22, LADO * 0.70)
        caminho.cubicTo(QPointF(LADO * 0.30, LADO * 0.30),
                        QPointF(LADO * 0.72, LADO * 0.28),
                        QPointF(LADO * 0.80, LADO * 0.46))
        ponta = QPointF(LADO * 0.80, LADO * 0.46)
        asas = ((LADO * 0.62, LADO * 0.44), (LADO * 0.80, LADO * 0.26))
    else:
        caminho.moveTo(LADO * 0.78, LADO * 0.70)
        caminho.cubicTo(QPointF(LADO * 0.70, LADO * 0.30),
                        QPointF(LADO * 0.28, LADO * 0.28),
                        QPointF(LADO * 0.20, LADO * 0.46))
        ponta = QPointF(LADO * 0.20, LADO * 0.46)
        asas = ((LADO * 0.38, LADO * 0.44), (LADO * 0.20, LADO * 0.26))
    pintor.drawPath(caminho)
    for x, y in asas:
        pintor.drawLine(ponta, QPointF(x, y))


def desfazer(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    _seta_curva(pintor, para_a_direita=False)
    return _fechar(mapa, pintor)


def refazer(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    _seta_curva(pintor, para_a_direita=True)
    return _fechar(mapa, pintor)


def recortar(cor: QColor) -> QIcon:
    mapa, pintor, caneta = _pintor(cor)
    # Tesoura: as duas laminas cruzadas e os dois aneis.
    pintor.drawLine(QPointF(LADO * 0.28, LADO * 0.16),
                    QPointF(LADO * 0.68, LADO * 0.62))
    pintor.drawLine(QPointF(LADO * 0.72, LADO * 0.16),
                    QPointF(LADO * 0.32, LADO * 0.62))
    raio = LADO * 0.12
    pintor.drawEllipse(QRectF(LADO * 0.16, LADO * 0.62, raio * 2, raio * 2))
    pintor.drawEllipse(QRectF(LADO * 0.60, LADO * 0.62, raio * 2, raio * 2))
    return _fechar(mapa, pintor)


def copiar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Duas folhas deslocadas: a de tras e a da frente.
    _pagina(pintor, LADO * 0.16, LADO * 0.12, LADO * 0.44, LADO * 0.56)
    _pagina(pintor, LADO * 0.36, LADO * 0.30, LADO * 0.46, LADO * 0.58)
    return _fechar(mapa, pintor)


def colar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Prancheta: o corpo e a presilha em cima.
    pintor.drawRoundedRect(
        QRectF(LADO * 0.20, LADO * 0.20, LADO * 0.60, LADO * 0.64),
        LADO * 0.08, LADO * 0.08)
    pintor.drawRoundedRect(
        QRectF(LADO * 0.36, LADO * 0.10, LADO * 0.28, LADO * 0.18),
        LADO * 0.05, LADO * 0.05)
    return _fechar(mapa, pintor)


def _lupa(pintor: QPainter) -> None:
    pintor.drawEllipse(QRectF(LADO * 0.16, LADO * 0.16,
                              LADO * 0.44, LADO * 0.44))
    pintor.drawLine(QPointF(LADO * 0.56, LADO * 0.56),
                    QPointF(LADO * 0.82, LADO * 0.82))


def localizar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    _lupa(pintor)
    return _fechar(mapa, pintor)


def substituir(cor: QColor) -> QIcon:
    mapa, pintor, caneta = _pintor(cor)
    _lupa(pintor)
    # A setinha dentro da lente e' o que diz "trocar", e nao so' "achar".
    caneta.setWidthF(LADO / 16)
    pintor.setPen(caneta)
    pintor.drawLine(QPointF(LADO * 0.26, LADO * 0.38),
                    QPointF(LADO * 0.50, LADO * 0.38))
    pintor.drawLine(QPointF(LADO * 0.42, LADO * 0.30),
                    QPointF(LADO * 0.50, LADO * 0.38))
    pintor.drawLine(QPointF(LADO * 0.42, LADO * 0.46),
                    QPointF(LADO * 0.50, LADO * 0.38))
    return _fechar(mapa, pintor)


def visualizar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Uma grade 2x2: representa "trocar de visualizacao" melhor que um olho,
    # que sugeriria "somente leitura".
    for x in (0.16, 0.54):
        for y in (0.16, 0.54):
            pintor.drawRect(QRectF(LADO * x, LADO * y,
                                   LADO * 0.30, LADO * 0.30))
    return _fechar(mapa, pintor)


def comparar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Duas colunas e as setas entre elas.
    pintor.drawRect(QRectF(LADO * 0.12, LADO * 0.18,
                           LADO * 0.26, LADO * 0.64))
    pintor.drawRect(QRectF(LADO * 0.62, LADO * 0.18,
                           LADO * 0.26, LADO * 0.64))
    pintor.drawLine(QPointF(LADO * 0.42, LADO * 0.40),
                    QPointF(LADO * 0.58, LADO * 0.40))
    pintor.drawLine(QPointF(LADO * 0.42, LADO * 0.60),
                    QPointF(LADO * 0.58, LADO * 0.60))
    return _fechar(mapa, pintor)


def formatar(cor: QColor) -> QIcon:
    mapa, pintor, _ = _pintor(cor)
    # Linhas com recuos diferentes: e' o que "indentar" parece.
    for y, (esq, dir_) in ((0.22, (0.16, 0.84)),
                           (0.42, (0.32, 0.80)),
                           (0.62, (0.32, 0.68)),
                           (0.82, (0.16, 0.76))):
        pintor.drawLine(QPointF(LADO * esq, LADO * y),
                        QPointF(LADO * dir_, LADO * y))
    return _fechar(mapa, pintor)


#: chave -> (rótulo na tela de Configurações, função que desenha).
#:
#: A chave é o que vai para a configuração; mudar uma quebraria a barra de quem
#: já a personalizou, então elas são estáveis.
CATALOGO = {
    "novo": ("Novo", novo),
    "abrir": ("Abrir", abrir),
    "salvar": ("Salvar", salvar),
    "salvar_tudo": ("Salvar tudo", salvar_tudo),
    "desfazer": ("Desfazer", desfazer),
    "refazer": ("Refazer", refazer),
    "recortar": ("Recortar", recortar),
    "copiar": ("Copiar", copiar),
    "colar": ("Colar", colar),
    "localizar": ("Localizar", localizar),
    "substituir": ("Substituir", substituir),
    "visualizar": ("Visualização", visualizar),
    "formatar": ("Formatar documento", formatar),
    "comparar": ("Comparar arquivos", comparar),
}


def icone(chave: str, cor: QColor) -> QIcon | None:
    """O ícone de uma chave do catálogo, na cor pedida."""
    entrada = CATALOGO.get(chave)
    return entrada[1](cor) if entrada else None
