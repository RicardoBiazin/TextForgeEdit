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

Mesma familia do TextForge -- fundo ardosia, barras de texto -- para os dois
programas se reconhecerem como irmaos. O que muda e' a COR do vinco lateral:
laranja-brasa la', AZUL aqui.

TUDO E' GROSSO, e isso NAO e' escolha estetica.

A primeira versao deste icone tinha um vinco de 1 px e tres linhas de texto de
1 px sobre um fundo quase preto. No papel parecia elegante; na barra de tarefas
virou um borrao. Duas licoes ficaram:

  * a 16 px, uma forma de 1 px com 1 px de folga some. As barras ocupam 2 px e
    o vinco ocupa 3, e por isso sao DUAS barras de texto, e nao tres;
  * um retangulo #1E1F22 numa barra de tarefas escura tem quase a mesma cor da
    barra. O que separa o icone do fundo e' o VINCO AZUL, entao ele e' largo.

A pagina do icone de arquivo e' CLARA pelo motivo espelhado: ela vive no
Explorer, onde o fundo e' branco -- e por isso ganha uma borda, senao a
silhueta de documento desaparece no branco.
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
#: distingue os dois de relance, e e' o que separa o icone de uma barra de
#: tarefas escura. Ver o cabecalho.
VINCO = (0x61, 0xAF, 0xEF)
TEXTO = (0xD6, 0xD8, 0xDC)

#: A pagina do icone de arquivo, e a tinta escrita nela. Clara porque o Explorer
#: e' branco atras -- e a borda existe pelo mesmo motivo.
PAGINA = (0xE8, 0xEA, 0xED)
TINTA = (0x2B, 0x2D, 0x31)
BORDA = (0x8A, 0x8F, 0x98)

TAMANHOS = (16, 24, 32, 48, 64, 128, 256)

Imagem = list[list[tuple[int, int, int, int]]]


def _vazia(n: int) -> Imagem:
    return [[(0, 0, 0, 0)] * n for _ in range(n)]


def _barra(px: Imagem, n: int, topo: float, altura: float, esquerda: float,
           direita: float, cor: tuple[int, int, int],
           somente_sobre=None) -> None:
    """Um retangulo em fracoes do tamanho, so' sobre pixel ja' opaco.

    O `somente_sobre` restringe ainda mais: e' o que impede uma barra de texto
    de pintar por cima da dobra do canto.
    """
    y0, y1 = int(topo * n), max(int(topo * n) + 1, int((topo + altura) * n))
    x0, x1 = int(esquerda * n), max(int(esquerda * n) + 1, int(direita * n))
    for y in range(max(0, y0), min(n, y1)):
        for x in range(max(0, x0), min(n, x1)):
            if not px[y][x][3]:
                continue
            if somente_sobre is not None and px[y][x][:3] != somente_sobre:
                continue
            px[y][x] = (*cor, 255)


def desenhar_app(n: int) -> Imagem:
    """O icone do PROGRAMA: quadrado de cantos arredondados."""
    px = _vazia(n)
    raio = max(1, n // 7)

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

    # O vinco LARGO da esquerda: e' ele que separa o icone do fundo escuro.
    _barra(px, n, 0.12, 0.76, 0.12, 0.32, VINCO)
    # DUAS barras grossas, e nao tres finas. Ver o cabecalho.
    _barra(px, n, 0.28, 0.14, 0.40, 0.86, TEXTO)
    _barra(px, n, 0.56, 0.14, 0.40, 0.68, TEXTO)
    return px


def desenhar_arquivo(n: int) -> Imagem:
    """O icone do TIPO DE ARQUIVO: pagina clara com o canto dobrado em azul.

    A dobra e' proporcional e nunca menor que tres pixels: a 16 px uma dobra de
    um pixel some, e o icone vira um retangulo indistinguivel do app.
    """
    px = _vazia(n)
    margem = max(1, n // 10)
    dobra = max(3, n // 4)
    esquerda, direita = margem, n - margem
    topo, base = margem, n - margem

    for y in range(topo, base):
        for x in range(esquerda, direita):
            if (direita - x) + (y - topo) <= dobra:
                continue        # o canto cortado
            na_borda = (x in (esquerda, direita - 1)
                        or y in (topo, base - 1)
                        or (direita - x) + (y - topo) == dobra + 1)
            px[y][x] = (*(BORDA if na_borda else PAGINA), 255)

    # A dobra, em AZUL: e' a marca do editor, e a unica cor do icone.
    for y in range(topo, topo + dobra):
        for x in range(direita - dobra, direita):
            if (direita - x) + (y - topo) > dobra and y - topo < dobra:
                px[y][x] = (*VINCO, 255)

    # Tres barras de tinta, so' sobre o miolo da pagina: `somente_sobre` impede
    # que elas invadam a borda ou a dobra.
    _barra(px, n, 0.40, 0.10, 0.22, 0.74, TINTA, somente_sobre=PAGINA)
    _barra(px, n, 0.58, 0.10, 0.22, 0.60, TINTA, somente_sobre=PAGINA)
    _barra(px, n, 0.76, 0.10, 0.22, 0.70, TINTA, somente_sobre=PAGINA)
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
