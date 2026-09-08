"""Gera os dois `.ico` do TextForgeEdit, sem nenhuma dependencia.

    .venv\\Scripts\\python.exe ferramentas\\gerar_icone.py

DOIS icones, e nao um:

    icone.ico          o APLICATIVO -- quadrado cheio, barra de tarefas e .exe
    icone_arquivo.ico  o TIPO DE ARQUIVO -- pagina com canto dobrado

Sao coisas diferentes e o Explorer as mostra em lugares diferentes. Com um
icone so', um `.txt` associado fica com cara de PROGRAMA na pasta -- e' o que o
projeto irmao faz, e confunde: a pessoa ve' o simbolo do editor e nao sabe se
aquilo e' o editor ou um arquivo dele.

Sem Pillow DE PROPOSITO. Os `.ico` sao versionados justamente para o build
funcionar numa maquina que nao tenha Pillow, e um gerador que exigisse Pillow
anularia isso. As duas coisas que ele precisa saber sao simples: um `.ico` e' um
cabecalho mais um DIB de 32 bits, e um `.png` e' uma sequencia de chunks em zlib.

O DESENHO, e por que ele e' assim:

Mesma familia do TextForge -- fundo ardosia, tres linhas de texto -- para os dois
programas se reconhecerem como irmaos. O que muda e' a COR do vinco lateral:
laranja-brasa la', AZUL aqui. Cor separa melhor que forma a 16 px, que e' o
tamanho em que o icone mais aparece.

Tudo e' forma cheia e contraste alto pelo mesmo motivo: a 16 px um detalhe fino
vira sujeira cinza.
"""

from __future__ import annotations

import pathlib
import struct
import sys
import zlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# Paleta: as mesmas cores do tema escuro, para o icone nao destoar da janela.
FUNDO = (0x1E, 0x1F, 0x22)
#: O vinco lateral. AZUL, e nao a brasa laranja do TextForge -- e' o que
#: distingue os dois de relance numa pasta.
VINCO = (0x61, 0xAF, 0xEF)
TEXTO = (0xD6, 0xD8, 0xDC)
DESTAQUE = (0x98, 0xC3, 0x79)

#: Cor da "pagina" na variante de arquivo: mais clara que o fundo do app, para
#: a silhueta de documento aparecer mesmo em cima de uma pasta escura.
PAGINA = (0x2B, 0x2D, 0x31)

TAMANHOS = (16, 24, 32, 48, 64, 128, 256)

Imagem = list[list[tuple[int, int, int, int]]]


def _vazia(n: int) -> Imagem:
    return [[(0, 0, 0, 0)] * n for _ in range(n)]


def _pintar_linhas(px: Imagem, n: int, *, com_vinco: bool) -> None:
    """As tres linhas de texto e o vinco lateral, em fracoes do tamanho."""

    def barra(topo: float, altura: float, esquerda: float, direita: float,
              cor: tuple[int, int, int]) -> None:
        y0, y1 = int(topo * n), max(int(topo * n) + 1, int((topo + altura) * n))
        x0, x1 = int(esquerda * n), max(int(esquerda * n) + 1, int(direita * n))
        for y in range(max(0, y0), min(n, y1)):
            for x in range(max(0, x0), min(n, x1)):
                # So' pinta sobre o que ja' e' opaco: e' o que mantem a barra
                # dentro da silhueta, sem vazar pelo canto arredondado nem pelo
                # canto dobrado da pagina.
                if px[y][x][3]:
                    px[y][x] = (*cor, 255)

    if com_vinco:
        barra(0.16, 0.68, 0.13, 0.22, VINCO)
        esquerda, direita = 0.30, 0.84
    else:
        # Sem o vinco, as linhas comecam mais a' esquerda: numa pagina estreita
        # elas ficariam espremidas contra a borda direita.
        barra(0.20, 0.60, 0.17, 0.24, VINCO)
        esquerda, direita = 0.32, 0.80

    barra(0.26, 0.09, esquerda, direita, TEXTO)
    barra(0.45, 0.09, esquerda, esquerda + (direita - esquerda) * 0.66, TEXTO)
    barra(0.64, 0.09, esquerda, esquerda + (direita - esquerda) * 0.88, DESTAQUE)


def desenhar_app(n: int) -> Imagem:
    """O icone do PROGRAMA: quadrado de cantos arredondados."""
    px = _vazia(n)
    raio = max(1, n // 6)

    def dentro(x: int, y: int) -> bool:
        for cx, cy in ((raio, raio), (n - 1 - raio, raio),
                       (raio, n - 1 - raio), (n - 1 - raio, n - 1 - raio)):
            fora_x = (x < raio and cx == raio) or (x > n - 1 - raio and cx > raio)
            fora_y = (y < raio and cy == raio) or (y > n - 1 - raio and cy > raio)
            if fora_x and fora_y:
                return (x - cx) ** 2 + (y - cy) ** 2 <= raio * raio
        return True

    for y in range(n):
        for x in range(n):
            if dentro(x, y):
                px[y][x] = (*FUNDO, 255)

    _pintar_linhas(px, n, com_vinco=True)
    return px


def desenhar_arquivo(n: int) -> Imagem:
    """O icone do TIPO DE ARQUIVO: pagina com o canto de cima cortado.

    A dobra e' proporcional e nunca menor que dois pixels: a 16 px uma dobra de
    um pixel some, e o icone vira um retangulo indistinguivel do app.
    """
    px = _vazia(n)
    margem = max(1, n // 8)                 # a pagina nao encosta na borda
    dobra = max(2, n // 4)
    esquerda, direita = margem, n - margem
    topo, base = max(0, n // 16), n - max(1, n // 16)

    for y in range(topo, base):
        for x in range(esquerda, direita):
            # O corte diagonal do canto superior direito.
            if (direita - x) + (y - topo) <= dobra:
                continue
            px[y][x] = (*PAGINA, 255)

    # A "aba" da dobra, um tom mais claro, para o canto nao parecer so' cortado.
    for y in range(topo, topo + dobra):
        for x in range(direita - dobra, direita):
            if (direita - x) + (y - topo) > dobra and y - topo < dobra:
                px[y][x] = (0x3A, 0x3D, 0x43, 255)

    _pintar_linhas(px, n, com_vinco=False)
    return px


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------


def _chunk(tipo: bytes, dados: bytes) -> bytes:
    return (struct.pack(">I", len(dados)) + tipo + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))


def png(px: Imagem) -> bytes:
    altura, largura = len(px), len(px[0])
    bruto = bytearray()
    for linha in px:
        bruto.append(0)                 # filtro 0 (None) por linha
        for r, g, b, a in linha:
            bruto += bytes((r, g, b, a))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura,
                                          8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(bruto), 9))
            + _chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# ICO
# ---------------------------------------------------------------------------


def _dib(px: Imagem) -> bytes:
    """BITMAPINFOHEADER + pixels BGRA + mascara AND.

    Duas armadilhas do formato, e as duas fazem o icone sumir se erradas: a
    altura no cabecalho e' o DOBRO (imagem + mascara), e as linhas vao de BAIXO
    para cima.
    """
    altura, largura = len(px), len(px[0])
    cabecalho = struct.pack("<IiiHHIIiiII", 40, largura, altura * 2, 1, 32, 0,
                            0, 0, 0, 0, 0)
    corpo = bytearray()
    for linha in reversed(px):
        for r, g, b, a in linha:
            corpo += bytes((b, g, r, a))
    # Mascara AND zerada (o canal alfa ja' resolve), mas o padding para multiplo
    # de 4 bytes por linha e' obrigatorio.
    bytes_por_linha = ((largura + 31) // 32) * 4
    return bytes(cabecalho) + bytes(corpo) + b"\x00" * (bytes_por_linha * altura)


#: A partir deste tamanho a entrada vai como PNG, e nao como DIB cru. Um 256x256
#: em BGRA sao 256 KB; comprimido, ~1 KB. O Windows aceita entrada PNG desde o
#: Vista, e sem isso o .ico passaria de 370 KB.
TAMANHO_PARA_PNG = 64


def ico(imagens: list[Imagem]) -> bytes:
    entradas = bytearray()
    dados = bytearray()
    deslocamento = 6 + 16 * len(imagens)
    for px in imagens:
        n = len(px)
        bruto = png(px) if n >= TAMANHO_PARA_PNG else _dib(px)
        # 256 e' gravado como 0: o campo de largura/altura tem UM byte so'.
        entradas += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32,
                                len(bruto), deslocamento)
        dados += bruto
        deslocamento += len(bruto)
    return struct.pack("<HHH", 0, 1, len(imagens)) + bytes(entradas) + bytes(dados)


def main() -> int:
    pasta = RAIZ / "tfedit" / "recursos"
    pasta.mkdir(parents=True, exist_ok=True)

    for nome, desenho in (("icone.ico", desenhar_app),
                          ("icone_arquivo.ico", desenhar_arquivo)):
        destino = pasta / nome
        destino.write_bytes(ico([desenho(n) for n in TAMANHOS]))
        print(f"{destino}  ({destino.stat().st_size} bytes, "
              f"{len(TAMANHOS)} tamanhos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
