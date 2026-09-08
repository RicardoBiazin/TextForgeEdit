"""A janela viva e a deteccao de codificacao.

    .\\.venv\\Scripts\\python.exe tests\\teste_janela.py

O que esta suite guarda:

1. **A escrita de volta e' MINIMA.** Corrigir uma virgula numa fatia de 5 mil
   linhas nao pode injetar 250 KB na tabela de pecas. Se este teste quebrar,
   alguem tirou o corte de prefixo/sufixo e a memoria volta a crescer por
   deslize, e nao por edicao.
2. **Deslizar preserva o que foi editado.** Sair da fatia e voltar tem de
   encontrar o texto corrigido -- e nao o original.
3. **Fim de linha e codificacao voltam como estavam**, inclusive nas partes
   fora da janela, que nunca sao decodificadas.

Nada aqui importa Qt: a janela decide o que vai e volta, e o widget so' mostra.
"""

from __future__ import annotations

import codecs
import sys

from ajudantes import checa, checa_igual, pasta_temporaria, resumir, secao

from tfedit import codificacao
from tfedit.gravacao import gravar
from tfedit.janela import JanelaViva, _prefixo_comum, _sufixo_comum
from tfedit.original import Original
from tfedit.pecas import Documento


def abrir(pasta, nome: str, conteudo: bytes):
    alvo = pasta / nome
    alvo.write_bytes(conteudo)
    original = Original(alvo)
    original.indexar()
    perfil = codificacao.detectar(original.ler(0, codificacao.SONDAGEM))
    return alvo, Documento(original), perfil


def gerar(pasta, nome: str, linhas: int, eol: bytes = b"\n"):
    alvo = pasta / nome
    with open(alvo, "wb", buffering=1024 * 1024) as f:
        for lote in range(0, linhas, 50_000):
            f.write(b"".join(f"linha {i:08d} conteudo original".encode() + eol
                             for i in range(lote,
                                            min(lote + 50_000, linhas))))
    return alvo


# ===========================================================================
# Codificacao
# ===========================================================================


def testar_codificacao() -> None:
    secao("Deteccao de codificacao e fim de linha")

    casos = (
        ("UTF-8 com BOM", codecs.BOM_UTF8 + "ação\n".encode("utf-8"),
         "utf-8", codecs.BOM_UTF8),
        ("UTF-8 sem BOM", "ação coração\n".encode("utf-8"), "utf-8", b""),
        ("UTF-16 LE com BOM", codecs.BOM_UTF16_LE + "ação\n".encode("utf-16-le"),
         "utf-16-le", codecs.BOM_UTF16_LE),
        ("ASCII puro", b"apenas ascii\n", "utf-8", b""),
    )
    for rotulo, dados, codec, bom in casos:
        perfil = codificacao.detectar(dados)
        checa_igual(perfil.codec, codec, f"{rotulo}: codec")
        checa_igual(perfil.bom, bom, f"{rotulo}: BOM")

    # UTF-16 sem BOM tem de ser testado ANTES do UTF-8 estrito: aqueles bytes
    # SAO UTF-8 valido, e a ordem inversa classificaria tudo como UTF-8 e o
    # texto sairia intercalado com \x00.
    utf16 = "linha um\nlinha dois\n".encode("utf-16-le")
    perfil = codificacao.detectar(utf16)
    checa_igual(perfil.codec, "utf-16-le",
                "*** UTF-16 sem BOM e' reconhecido, e nao confundido com "
                "UTF-8 (aqueles bytes sao UTF-8 valido) ***")

    cp = "ação e coração com muitos acentos ãéíóú çç\n".encode("cp1252")
    perfil = codificacao.detectar(cp)
    checa(perfil.codec in ("cp1252", "iso-8859-1", "windows-1252"),
          f"cp1252 com acentos e' reconhecido ({perfil.codec}, "
          f"{perfil.como_decidiu})")

    for rotulo, dados, esperado, misto in (
            ("LF", b"a\nb\nc\n", codificacao.LF, False),
            ("CRLF", b"a\r\nb\r\nc\r\n", codificacao.CRLF, False),
            ("misto", b"a\r\nb\nc\r\n", codificacao.CRLF, True)):
        perfil = codificacao.detectar(dados)
        checa_igual(perfil.fim_de_linha, esperado, f"fim de linha: {rotulo}")
        checa_igual(perfil.misto, misto, f"e a mistura: {rotulo}")

    # Um caractere multibyte cortado no fim da SONDAGEM nao torna o arquivo
    # invalido -- ele so' foi partido pela sondagem.
    partido = "ação".encode("utf-8")[:-1]
    perfil = codificacao.detectar(partido)
    checa_igual(perfil.codec, "utf-8",
                "*** multibyte partido pela sondagem nao vira cp1252 ***")

    checa_igual(codificacao.para_lf("a\r\nb\rc\n"), "a\nb\nc\n",
                "para_lf normaliza os tres")
    checa_igual(codificacao.de_lf("a\nb", "\r\n"), "a\r\nb", "de_lf reexpande")


# ===========================================================================
# A janela
# ===========================================================================


def testar_carregar() -> None:
    secao("Carregar a fatia")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "grande.txt", 20_000)
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        janela = JanelaViva(doc, codificacao.detectar(original.ler(0, 4096)),
                            linhas=1_000)

        recorte = janela.carregar(0)
        checa_igual(recorte.primeira_linha, 0, "no comeco, a fatia comeca em 0")
        checa_igual(recorte.quantas_linhas, 1_000, "com o tamanho pedido")
        checa(recorte.texto.startswith("linha 00000000"),
              "e o texto e' o do inicio do arquivo")

        recorte = janela.carregar(10_000)
        checa_igual(recorte.primeira_linha, 9_500,
                    "*** a fatia e' CENTRADA na linha pedida ***")
        checa(recorte.texto.startswith("linha 00009500"), "com o texto certo")
        checa_igual(janela.linha_no_documento(0), 9_500,
                    "traducao fatia -> documento")
        checa_igual(janela.linha_na_fatia(9_600), 100,
                    "e documento -> fatia")
        checa_igual(janela.linha_na_fatia(100), -1,
                    "linha fora da fatia devolve -1")

        janela.carregar(20_000)
        checa(janela.recorte.ultima_linha <= doc.total_de_linhas,
              "a fatia do fim nao passa do fim do arquivo")
        original.fechar()


def testar_escrita_minima() -> None:
    secao("A escrita de volta e' MINIMA")

    checa_igual(_prefixo_comum(b"abcXdef", b"abcYdef"), 3, "prefixo comum")
    checa_igual(_sufixo_comum(b"abcXdef", b"abcYdef", 3), (4, 4), "sufixo comum")
    checa_igual(_sufixo_comum(b"aaaa", b"aa", 0), (2, 0),
                "*** o sufixo nao invade o prefixo (senao a substituicao "
                "removeria bytes demais) ***")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "minima.txt", 5_000)
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        janela = JanelaViva(doc, codificacao.detectar(original.ler(0, 4096)),
                            linhas=2_000)
        recorte = janela.carregar(1_000)
        tamanho_da_fatia = len(recorte.texto)
        checa(tamanho_da_fatia > 40_000,
              f"a fatia tem {tamanho_da_fatia} caracteres")

        # Uma unica letra trocada no meio da fatia.
        novo = recorte.texto.replace("linha 00000500 conteudo original",
                                     "linha 00000500 CONTEUDO EDITADO", 1)
        checa(novo != recorte.texto, "o texto de teste mudou")
        checa(janela.aplicar(novo), "aplicar detecta a mudanca")

        adicionados = sum(p.tamanho for p in doc.blocos()
                          if p.fonte == "adicionado")
        checa(adicionados < 200,
              f"*** a edicao injetou {adicionados} bytes na tabela, e nao os "
              f"{tamanho_da_fatia} da fatia inteira ***")
        checa_igual(doc.linha(500), b"linha 00000500 CONTEUDO EDITADO",
                    "e o documento tem o texto novo")
        checa_igual(doc.linha(499), b"linha 00000499 conteudo original",
                    "com as vizinhas intactas")

        checa(not janela.aplicar(janela.recorte.texto),
              "aplicar sem mudanca nenhuma devolve False")
        original.fechar()


def testar_deslizar() -> None:
    secao("Deslizar preserva o que foi editado")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "deslizar.txt", 30_000)
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        janela = JanelaViva(doc, codificacao.detectar(original.ler(0, 4096)),
                            linhas=2_000)

        recorte = janela.carregar(1_000)
        novo = recorte.texto.replace("linha 00000600 conteudo original",
                                     "PRIMEIRA CORRECAO", 1)
        janela.deslizar(novo, 20_000)
        checa_igual(janela.recorte.primeira_linha, 19_000,
                    "deslizou para a fatia de destino")

        recorte = janela.recorte
        novo = recorte.texto.replace("linha 00019500 conteudo original",
                                     "SEGUNDA CORRECAO", 1)
        janela.deslizar(novo, 600)

        checa_igual(doc.linha(600), b"PRIMEIRA CORRECAO",
                    "*** a primeira correcao sobreviveu ao deslize ***")
        checa_igual(doc.linha(19_500), b"SEGUNDA CORRECAO",
                    "e a segunda tambem")
        checa(janela.recorte.texto.startswith("linha 00000"),
              "e a fatia voltou para o comeco")

        # A regra do deslize: perto da borda desliza, no meio nao. E nas pontas
        # do ARQUIVO nao desliza, porque nao ha' para onde.
        janela.carregar(15_000)
        checa(not janela.precisa_deslizar(15_000), "no meio da fatia, nao desliza")
        checa(janela.precisa_deslizar(14_100), "perto da borda de cima, desliza")
        checa(janela.precisa_deslizar(15_900), "perto da de baixo, tambem")
        janela.carregar(0)
        checa(not janela.precisa_deslizar(10),
              "*** encostado no comeco do arquivo nao desliza: nao ha' para "
              "onde, e insistir recarregaria a fatia a cada seta ***")
        original.fechar()


def testar_ida_e_volta_com_janela() -> None:
    secao("Gravar depois de editar pela janela")

    with pasta_temporaria() as tmp:
        for rotulo, eol in (("LF", b"\n"), ("CRLF", b"\r\n")):
            alvo = gerar(tmp, f"grava_{rotulo}.txt", 3_000, eol)
            antes = alvo.read_bytes()
            original = Original(alvo)
            original.indexar()
            doc = Documento(original)
            perfil = codificacao.detectar(original.ler(0, 4096))
            checa_igual(perfil.fim_de_linha,
                        codificacao.LF if eol == b"\n" else codificacao.CRLF,
                        f"{rotulo}: o fim de linha foi detectado")

            janela = JanelaViva(doc, perfil, linhas=1_000)
            recorte = janela.carregar(0)
            janela.aplicar(recorte.texto.replace(
                "linha 00000010 conteudo original", "EDITADA", 1))
            gravar(alvo, doc, antes_de_trocar=original.fechar)

            depois = alvo.read_bytes()
            checa(b"EDITADA" + eol in depois,
                  f"{rotulo}: a linha editada foi gravada com o EOL certo")
            checa_igual(len(depois.split(eol)), len(antes.split(eol)),
                        f"{rotulo}: e o numero de linhas nao mudou")
            checa(b"linha 00000011 conteudo original" + eol in depois,
                  f"*** {rotulo}: as linhas FORA da janela saem intactas -- "
                  f"elas nunca foram decodificadas ***")

        # Sem nenhuma edicao, gravar continua devolvendo o arquivo identico.
        alvo = gerar(tmp, "intacto.txt", 2_000, b"\r\n")
        antes = alvo.read_bytes()
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        janela = JanelaViva(doc, codificacao.detectar(original.ler(0, 4096)),
                            linhas=500)
        janela.carregar(0)
        janela.deslizar(janela.recorte.texto, 1_500)
        janela.deslizar(janela.recorte.texto, 0)
        gravar(alvo, doc, antes_de_trocar=original.fechar)
        checa_igual(alvo.read_bytes(), antes,
                    "*** carregar e deslizar SEM editar nao altera um byte ***")


def testar_acentos() -> None:
    secao("Acentos atravessam a janela")

    with pasta_temporaria() as tmp:
        conteudo = "ação\ncoração\nnão\n".encode("utf-8")
        alvo, doc, perfil = abrir(tmp, "acentos.txt", conteudo)
        janela = JanelaViva(doc, perfil, linhas=100)
        recorte = janela.carregar(0)
        checa_igual(recorte.texto, "ação\ncoração\nnão\n",
                    "a fatia decodifica os acentos")

        janela.aplicar(recorte.texto.replace("coração", "CORAÇÃO ÊNFASE"))
        gravar(alvo, doc, antes_de_trocar=doc.original.fechar)
        checa_igual(alvo.read_bytes(),
                    "ação\nCORAÇÃO ÊNFASE\nnão\n".encode("utf-8"),
                    "*** e a gravacao devolve os acentos na codificacao do "
                    "arquivo ***")

        conteudo = "ação\ncoracao\n".encode("cp1252")
        alvo, doc, perfil = abrir(tmp, "cp.txt", conteudo)
        # O perfil vem da DETECCAO e so' o codec e' fixado. Fabricar
        # um perfil a mao aqui ja' escondeu um defeito: com
        # `fim_de_linha` errado, gravar reescreve as quebras do trecho
        # editado -- ver o aviso em `JanelaViva._codificar`.
        perfil = codificacao.Perfil(codec="cp1252",
                                    fim_de_linha=perfil.fim_de_linha)
        janela = JanelaViva(doc, perfil, linhas=100)
        recorte = janela.carregar(0)
        janela.aplicar(recorte.texto.replace("coracao", "coração"))
        gravar(alvo, doc, antes_de_trocar=doc.original.fechar)
        checa_igual(alvo.read_bytes(), "ação\ncoração\n".encode("cp1252"),
                    "e num arquivo cp1252 o texto novo sai em cp1252, e nao "
                    "em UTF-8")


# ===========================================================================


def testar_folga_menor_que_a_fatia() -> None:
    secao("*** A margem nunca passa da janela ***")

    from tfedit import janela as janela_mod

    with pasta_temporaria() as pasta:
        alvo = pasta / "muitas.txt"
        alvo.write_bytes(b"".join(b"linha %05d\r\n" % i
                                  for i in range(2000)))
        original = Original(alvo)
        original.indexar()
        try:
            viva = JanelaViva(Documento(original),
                              codificacao.Perfil(codec="utf-8"), linhas=100)
            viva.carregar(1000)

            checa(viva.folga < viva.linhas,
                  f"a folga ({viva.folga}) e' menor que a fatia "
                  f"({viva.linhas})")
            checa(viva.folga * 2 < viva.linhas,
                  "e sobra fatia util entre as duas margens")

            # Com `FOLGA` fixo em 500 numa fatia de 100, a fatia INTEIRA cabia
            # dentro da margem: `precisa_deslizar` respondia sempre que sim, e
            # cada movimento do cursor recarregava. Como recarregar repoe o
            # cursor no comeco da linha, digitar "ação" saia "oãça" -- o
            # sintoma nao parecia de rolagem, e a edicao se perdia.
            checa(viva.folga <= janela_mod.FOLGA,
                  "e nunca passa do teto geral")

            meio = viva.recorte.primeira_linha + viva.linhas // 2
            checa(not viva.precisa_deslizar(meio),
                  f"*** no MEIO da fatia (linha {meio}) nao desliza ***")
            perto = viva.recorte.primeira_linha + 1
            checa(viva.precisa_deslizar(perto),
                  f"mas encostado na borda (linha {perto}) desliza")

            # E a fatia grande continua com a folga cheia.
            grande = JanelaViva(Documento(original),
                                codificacao.Perfil(codec="utf-8"), linhas=5000)
            checa_igual(grande.folga, janela_mod.FOLGA,
                        "numa fatia de 5000 a folga e' a do padrao")
        finally:
            original.fechar()


def main() -> int:
    testar_codificacao()
    testar_carregar()
    testar_escrita_minima()
    testar_deslizar()
    testar_ida_e_volta_com_janela()
    testar_acentos()
    testar_folga_menor_que_a_fatia()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
