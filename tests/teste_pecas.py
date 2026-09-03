"""O nucleo: indice do original, tabela de pecas e gravacao por streaming.

    .\\.venv\\Scripts\\python.exe tests\\teste_pecas.py

Quatro coisas carregam esta suite. Se alguma quebrar, o problema esta' no codigo,
nao no teste:

1. **Sem edicao, gravar devolve o arquivo BYTE A BYTE** -- CRLF, fim de linha
   misto e ausencia de quebra final inclusive. As pecas intocadas sao copiadas
   como bytes, e por isso o gravador nem precisa entende-las.
2. **A memoria acompanha as EDICOES, nao o arquivo.**
3. **Digitacao seguida nao explode a tabela.** Ha' um caminho rapido que faz a
   peca crescer em vez de a lista ganhar uma entrada por tecla; sem ele, digitar
   um paragrafo cria centenas de pecas.
4. **Desfazer devolve o documento IDENTICO.** Inclusive para uma substituicao,
   que e' uma operacao so' e nao duas.

Nada aqui importa Qt: o nucleo e' independente da interface de proposito.
"""

from __future__ import annotations

import sys

from ajudantes import (checa, checa_igual, checa_levanta, memoria_privada_mb,
                       pasta_temporaria, resumir, secao)

from tfedit.gravacao import SemEspaco, conferir_espaco, gravar
from tfedit.original import Original
from tfedit.pecas import ADICIONADO, Documento, ForaDaFaixa


# ===========================================================================
# Ajudantes
# ===========================================================================


def abrir(pasta, nome: str, conteudo: bytes) -> tuple:
    alvo = pasta / nome
    alvo.write_bytes(conteudo)
    original = Original(alvo)
    original.indexar()
    return alvo, Documento(original)


def texto(documento: Documento) -> bytes:
    return documento.ler(0, documento.tamanho)


def gerar(pasta, nome: str, linhas: int) -> "object":
    alvo = pasta / nome
    with open(alvo, "wb", buffering=1024 * 1024) as f:
        for lote in range(0, linhas, 50_000):
            f.write(b"".join(f"registro {i:012d};valor;{i % 97}\n".encode()
                             for i in range(lote, min(lote + 50_000, linhas))))
    return alvo


# ===========================================================================
# 1. O indice do arquivo original
# ===========================================================================


def testar_indice() -> None:
    secao("Indice esparso do arquivo")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "indice.txt", 60_000)
        original = Original(alvo)

        checa(not original.indexacao_completa, "comeca sem indice")
        original.indexar(8192)
        parcial = original.total_de_linhas
        checa(0 < parcial < 60_001,
              f"a varredura incremental para no orcamento ({parcial} linhas)")
        checa(not original.indexacao_completa, "e o indice segue incompleto")

        while not original.indexacao_completa:
            original.indexar(64 * 1024)
        checa_igual(original.total_de_linhas, 60_001,
                    "*** o total bate: 60 mil linhas mais a vazia do fim ***")

        # `offset_da_linha` e `linhas_ate` sao inversos um do outro. E' disso
        # que a tabela de pecas depende para saber quantas linhas ha' dentro de
        # um pedaco do arquivo sem varre-lo.
        for n in (0, 1, 1023, 1024, 1025, 30_000, 59_999):
            offset = original.offset_da_linha(n)
            checa_igual(original.linhas_ate(offset), n,
                        f"linha {n}: offset e contagem sao inversos")

        checa_igual(original.linhas_em(original.offset_da_linha(10),
                                       original.offset_da_linha(25)), 15,
                    "linhas_em conta o intervalo certo")
        checa_igual(original.ler(0, 9), b"registro ", "leitura crua")
        original.fechar()
        original.fechar()
        checa(True, "fechar e' idempotente")


# ===========================================================================
# 2. Requisito central: sem edicao, o arquivo sai identico
# ===========================================================================


CASOS = (
    ("lf", b"a\nb\nc\n"),
    ("sem quebra final", b"a\nb\nc"),
    ("crlf", b"a\r\nb\r\nc\r\n"),
    ("eol misto", b"a\r\nb\nc\r\n"),
    ("linha vazia no meio", b"a\n\nc\n"),
    ("uma linha so", b"linha unica"),
    ("so quebras", b"\n\n\n"),
    ("arquivo vazio", b""),
    ("acentos cp1252", "acao\ncoracao\n".encode("cp1252")),
    ("acentos utf-8", "ação\ncoração\n".encode("utf-8")),
)


def testar_ida_e_volta() -> None:
    secao("Sem edicao, o arquivo sai IDENTICO")

    with pasta_temporaria() as tmp:
        for rotulo, conteudo in CASOS:
            alvo, doc = abrir(tmp, rotulo.replace(" ", "_") + ".txt", conteudo)
            checa(not doc.alterado, f"{rotulo}: abrir nao suja nada")
            checa_igual(texto(doc), conteudo, f"{rotulo}: leitura completa bate")
            gravar(alvo, doc, antes_de_trocar=doc.original.fechar)
            checa_igual(alvo.read_bytes(), conteudo,
                        f"*** {rotulo}: gravar sem editar devolve byte a byte ***")


def testar_leitura_por_linha() -> None:
    secao("Linhas e faixas")

    with pasta_temporaria() as tmp:
        _, doc = abrir(tmp, "linhas.txt", b"zero\num\ndois\ntres\n")
        checa_igual(doc.total_de_linhas, 5,
                    "arquivo terminado em quebra tem uma ultima linha vazia")
        checa_igual(doc.linha(0), b"zero", "primeira linha")
        checa_igual(doc.linha(2), b"dois", "linha do meio")
        checa_igual(doc.linha(4), b"", "a vazia do fim")
        checa_igual(doc.faixa(1, 3), [b"um", b"dois"], "faixa parcial")
        checa_igual(doc.faixa(0, 99), [b"zero", b"um", b"dois", b"tres", b""],
                    "faixa recortada no limite")

        _, doc = abrir(tmp, "crlf2.txt", b"zero\r\num\r\n")
        checa_igual(doc.linha(0), b"zero",
                    "*** o \\r do CRLF nao entra no texto da linha ***")
        checa_igual(doc.faixa(0, 2), [b"zero", b"um"], "nem na faixa")

        _, doc = abrir(tmp, "offsets.txt", b"aa\nbbb\ncccc\n")
        for linha, offset in ((0, 0), (1, 3), (2, 7), (3, 12)):
            checa_igual(doc.offset_da_linha(linha), offset,
                        f"offset da linha {linha}")
            checa_igual(doc.linha_do_offset(offset), linha,
                        f"e o inverso, do offset {offset}")


# ===========================================================================
# 3. Edicao
# ===========================================================================


def testar_edicao() -> None:
    secao("Inserir, remover, substituir")

    with pasta_temporaria() as tmp:
        _, doc = abrir(tmp, "edicao.txt", b"abcdef\n")

        doc.inserir(3, b"XYZ")
        checa_igual(texto(doc), b"abcXYZdef\n", "inserir no meio")
        doc.inserir(0, b">")
        checa_igual(texto(doc), b">abcXYZdef\n", "inserir no comeco")
        doc.inserir(doc.tamanho, b"FIM")
        checa_igual(texto(doc), b">abcXYZdef\nFIM", "inserir no fim")

        removidos = doc.remover(1, 3)
        checa_igual(removidos, b"abc", "remover devolve o que saiu")
        checa_igual(texto(doc), b">XYZdef\nFIM", "e o documento encolhe")

        doc.substituir(1, 3, b"123456")
        checa_igual(texto(doc), b">123456def\nFIM", "substituir troca a faixa")

        checa_levanta(ForaDaFaixa, doc.inserir,
                      "inserir fora do documento levanta em vez de corromper",
                      10_000, b"x")

        # As linhas tem de acompanhar as edicoes.
        _, doc = abrir(tmp, "linhas2.txt", b"a\nb\n")
        checa_igual(doc.total_de_linhas, 3, "3 linhas no inicio")
        doc.inserir(2, b"X\nY\n")
        checa_igual(doc.total_de_linhas, 5, "inserir 2 quebras soma 2 linhas")
        checa_igual(doc.faixa(0, 99), [b"a", b"X", b"Y", b"b", b""],
                    "e as linhas ficam na ordem certa")
        doc.remover(2, 4)
        checa_igual(doc.total_de_linhas, 3, "remover as quebras devolve a conta")


def testar_digitacao_seguida() -> None:
    secao("Digitacao seguida nao explode a tabela")

    with pasta_temporaria() as tmp:
        _, doc = abrir(tmp, "digitar.txt", b"inicio\nfim\n")
        offset = 7
        for letra in b"o rato roeu a roupa do rei de roma":
            doc.inserir(offset, bytes([letra]))
            offset += 1

        pecas = doc.blocos()
        adicionadas = [p for p in pecas if p.fonte == ADICIONADO]
        checa_igual(len(adicionadas), 1,
                    f"*** 34 teclas produziram UMA peca, e nao 34 -- e' o "
                    f"caminho rapido da digitacao seguida (tabela: "
                    f"{len(pecas)} pecas) ***")
        checa(b"o rato roeu a roupa do rei de roma" in texto(doc),
              "e o texto digitado esta' la'")

        checa_igual(doc.total_de_edicoes, 1,
                    "*** e as 34 teclas viraram UMA operacao de desfazer: "
                    "Ctrl+Z desfaz a frase, e nao a letra ***")
        doc.desfazer()
        checa_igual(texto(doc), b"inicio\nfim\n", "e um Ctrl+Z limpa tudo")


def testar_desfazer() -> None:
    secao("Desfazer e refazer")

    with pasta_temporaria() as tmp:
        _, doc = abrir(tmp, "undo.txt", b"um\ndois\ntres\n")
        original = texto(doc)

        doc.inserir(3, b"NOVO ")
        doc.fechar_grupo()
        doc.remover(0, 3)
        doc.fechar_grupo()
        doc.substituir(0, 5, b"TROCADO")
        editado = texto(doc)
        checa(doc.pode_desfazer, "ha' o que desfazer")

        for _ in range(3):
            doc.desfazer()
        checa_igual(texto(doc), original,
                    "*** desfazer tudo devolve o documento IDENTICO ***")
        checa(not doc.alterado, "e ele deixa de estar alterado")
        checa_igual(doc.total_de_linhas, 4, "com a contagem de linhas certa")

        for _ in range(3):
            doc.refazer()
        checa_igual(texto(doc), editado, "refazer tudo volta ao editado")

        # Uma substituicao e' UMA operacao: um Ctrl+Z nao pode deixar o
        # documento num estado que nunca existiu.
        _, doc = abrir(tmp, "sub.txt", b"aaa bbb ccc\n")
        doc.substituir(4, 3, b"XXXXX")
        checa_igual(texto(doc), b"aaa XXXXX ccc\n", "substituiu")
        checa_igual(doc.total_de_edicoes, 1, "e registrou UMA operacao")
        doc.desfazer()
        checa_igual(texto(doc), b"aaa bbb ccc\n",
                    "*** e um Ctrl+Z devolve o original, sem estado "
                    "intermediario ***")

        doc.inserir(0, b"X")
        checa(not doc.pode_refazer,
              "editar depois de desfazer descarta o que havia para refazer")


def testar_gravar_editado() -> None:
    secao("Gravar depois de editar")

    with pasta_temporaria() as tmp:
        alvo, doc = abrir(tmp, "gravar.txt", b"linha um\r\nlinha dois\r\n")
        doc.substituir(6, 2, b"UM")
        gravar(alvo, doc, antes_de_trocar=doc.original.fechar)
        checa_igual(alvo.read_bytes(), b"linha UM\r\nlinha dois\r\n",
                    "*** o CRLF das partes intocadas sobrevive: elas sao "
                    "copiadas como bytes ***")

        # Gravar, reabrir e editar de novo NAO pode reverter a primeira edicao.
        original = Original(alvo)
        original.indexar()
        doc.confirmar_gravacao(original)
        checa(not doc.alterado, "confirmar_gravacao zera as pendencias")
        doc.substituir(16, 4, b"DOIS")
        gravar(alvo, doc, antes_de_trocar=doc.original.fechar)
        checa_igual(alvo.read_bytes(), b"linha UM\r\nlinha DOIS\r\n",
                    "*** a segunda gravacao preserva a primeira edicao ***")

        alvo2 = tmp / "cheio.txt"
        alvo2.write_bytes(b"x\n")
        original2 = Original(alvo2)
        original2.indexar()
        doc2 = Documento(original2)
        checa_levanta(SemEspaco, conferir_espaco,
                      "*** falta de espaco e' avisada ANTES de escrever o "
                      "primeiro byte ***", alvo2, 10 ** 15)
        original2.fechar()


# ===========================================================================
# 4. Memoria
# ===========================================================================


def testar_memoria() -> None:
    secao("A memoria acompanha as EDICOES, e nao o arquivo")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "memoria.txt", 800_000)
        mb = alvo.stat().st_size / (1024 * 1024)
        original = Original(alvo)
        while not original.indexacao_completa:
            original.indexar(8 * 1024 * 1024)

        base = memoria_privada_mb()
        doc = Documento(original)
        checa(doc.pode_editar, "com o indice completo, editar e' permitido")

        for k in range(3_000):
            doc.inserir(doc.offset_da_linha(k * 7), b"# ")
        gasto = memoria_privada_mb() - base
        checa(gasto < 30,
              f"*** 3 mil edicoes num arquivo de {mb:.0f} MB custaram "
              f"{gasto:.1f} MB (teto 30) ***")

        antes = memoria_privada_mb()
        gravar(alvo, doc, antes_de_trocar=original.fechar)
        pico = memoria_privada_mb() - antes
        checa(pico < 40,
              f"*** e gravar {mb:.0f} MB custou {pico:.1f} MB de pico "
              f"(teto 40): as pecas intocadas vao do mmap para o disco sem "
              f"virar str ***")

        conferencia = Original(alvo)
        while not conferencia.indexacao_completa:
            conferencia.indexar(8 * 1024 * 1024)
        doc2 = Documento(conferencia)
        checa_igual(doc2.linha(0), b"# registro 000000000000;valor;0",
                    "a primeira edicao chegou ao disco")
        checa_igual(doc2.linha(7), b"# registro 000000000007;valor;7",
                    "e a segunda tambem")
        checa_igual(doc2.linha(1), b"registro 000000000001;valor;1",
                    "e o que nao foi editado continua igual")
        conferencia.fechar()


def testar_indice_incompleto() -> None:
    secao("Editar so' e' permitido com o indice completo")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "parcial.txt", 40_000)
        original = Original(alvo)
        original.indexar(8192)
        doc = Documento(original)

        checa(not doc.pode_editar,
              "*** com o indice incompleto, editar e' recusado: partir uma "
              "peca precisa saber quantas linhas ficam de cada lado ***")
        parcial = doc.total_de_linhas
        while not original.indexacao_completa:
            original.indexar(64 * 1024)
        checa(doc.total_de_linhas > parcial,
              f"e a contagem CRESCE com a varredura ({parcial} -> "
              f"{doc.total_de_linhas}), para a barra de rolagem se ajustar")
        checa(doc.pode_editar, "terminada a varredura, editar libera")
        checa_igual(doc.total_de_linhas, 40_001, "com o total certo")
        original.fechar()


# ===========================================================================


def main() -> int:
    testar_indice()
    testar_ida_e_volta()
    testar_leitura_por_linha()
    testar_edicao()
    testar_digitacao_seguida()
    testar_desfazer()
    testar_gravar_editado()
    testar_memoria()
    testar_indice_incompleto()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
