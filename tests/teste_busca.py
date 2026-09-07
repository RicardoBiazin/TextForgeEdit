"""Localizar e substituir no documento INTEIRO.

    .\\.venv\\Scripts\\python.exe tests\\teste_busca.py

O que esta suite guarda:

1. **A busca enxerga o que foi DIGITADO e ainda nao gravado.** Ela varre a tabela
   de pecas, e nao o arquivo do disco -- procurar no disco acharia texto que o
   usuario ja' apagou e nao acharia o que ele acabou de escrever.
2. **Ela enxerga fora da fatia.** A janela viva segura ~5 mil linhas; achar so'
   dentro dela seria pior que nao ter busca, porque daria a impressao de que o
   resto do arquivo nao tem a palavra.
3. **"Substituir todas" aplica de TRAS PARA A FRENTE.** Do comeco, cada troca
   desloca o que vem depois e a segunda substituicao cai no lugar errado.
4. **Dar a volta** no fim do arquivo, como todo editor.

Nao importa Qt.
"""

from __future__ import annotations

import sys

from ajudantes import checa, checa_igual, pasta_temporaria, resumir, secao

from tfedit.busca import (Criterio, contar, procurar, proxima,
                          substituir_todas)
from tfedit.original import Original
from tfedit.pecas import Documento


def abrir(pasta, nome: str, conteudo: bytes) -> Documento:
    alvo = pasta / nome
    alvo.write_bytes(conteudo)
    original = Original(alvo)
    original.indexar()
    return Documento(original)


TEXTO = (b"primeira linha com alvo\n"
         b"segunda linha sem nada\n"
         b"terceira com ALVO em maiuscula\n"
         b"quarta com alvoroco no meio\n"
         b"quinta linha com alvo de novo\n")


def testar_criterio() -> None:
    secao("O criterio")

    checa(Criterio("").compilar() is None, "criterio vazio nao compila")
    checa(Criterio("[", expressao_regular=True).compilar() is None,
          "*** regex invalida devolve None em vez de estourar na cara do "
          "usuario ***")
    checa(Criterio("[a-z]+", expressao_regular=True).compilar() is not None,
          "regex valida compila")

    padrao = Criterio("a|b", palavra_inteira=True,
                      expressao_regular=True).compilar()
    checa(padrao is not None and padrao.pattern == r"\b(?:a|b)\b",
          "*** palavra inteira embrulha o padrao INTEIRO num grupo: sem o "
          "grupo, `a|b` viraria `\\ba|b\\b` e mudaria de significado ***")


def testar_procurar() -> None:
    secao("Procurar")

    with pasta_temporaria() as tmp:
        doc = abrir(tmp, "busca.txt", TEXTO)

        achados = list(procurar(doc, Criterio("alvo"), "utf-8"))
        checa_igual([a.linha for a in achados], [0, 2, 3, 4],
                    "sem diferenciar maiusculas acha ALVO e alvoroco")

        achados = list(procurar(doc, Criterio("alvo",
                                              diferenciar_maiusculas=True),
                                "utf-8"))
        checa_igual([a.linha for a in achados], [0, 3, 4],
                    "diferenciando, ALVO fica de fora")

        achados = list(procurar(doc, Criterio("alvo", palavra_inteira=True),
                                "utf-8"))
        checa_igual([a.linha for a in achados], [0, 2, 4],
                    "*** palavra inteira exclui 'alvoroco' ***")

        achados = list(procurar(doc, Criterio(r"qu\w+",
                                              expressao_regular=True),
                                "utf-8"))
        checa_igual([a.linha for a in achados], [3, 4], "regex")

        achado = achados[0]
        checa_igual(achado.texto[achado.inicio:achado.fim], "quarta",
                    "os offsets apontam para o texto certo")


def testar_proxima_e_volta() -> None:
    secao("Proxima, anterior e a volta")

    with pasta_temporaria() as tmp:
        doc = abrir(tmp, "volta.txt", TEXTO)
        criterio = Criterio("alvo")

        achado = proxima(doc, criterio, "utf-8", 0, 0)
        checa_igual(achado.linha, 0, "a primeira, a partir do inicio")

        achado = proxima(doc, criterio, "utf-8", 0, achado.fim)
        checa_igual(achado.linha, 2,
                    "*** a partir do FIM da ocorrencia atual vem a seguinte, e "
                    "nao a mesma de novo ***")

        achado = proxima(doc, criterio, "utf-8", 4, 30)
        checa_igual(achado.linha, 0,
                    "*** depois da ultima, da' a volta para a primeira ***")

        achado = proxima(doc, criterio, "utf-8", 4, 0, para_tras=True)
        checa_igual(achado.linha, 3, "para tras acha a anterior")

        achado = proxima(doc, criterio, "utf-8", 0, 0, para_tras=True)
        checa_igual(achado.linha, 4,
                    "*** antes da primeira, da' a volta para a ultima ***")

        checa(proxima(doc, Criterio("nao existe"), "utf-8", 0, 0) is None,
              "o que nao existe devolve None")

        quantas, cortou = contar(doc, criterio, "utf-8")
        checa_igual((quantas, cortou), (4, False), "contar")
        quantas, cortou = contar(doc, criterio, "utf-8", teto=2)
        checa_igual((quantas, cortou), (2, True),
                    "*** e o teto e' informado, em vez de varrer 1 GB para "
                    "dizer um numero ***")


def testar_enxerga_o_digitado() -> None:
    secao("A busca enxerga o que ainda nao foi gravado")

    with pasta_temporaria() as tmp:
        doc = abrir(tmp, "vivo.txt", b"linha um\nlinha dois\n")

        doc.inserir(doc.offset_da_linha(1), b"PALAVRANOVA no meio\n")
        achado = proxima(doc, Criterio("PALAVRANOVA"), "utf-8", 0, 0)
        checa(achado is not None and achado.linha == 1,
              "*** acha o texto digitado que ainda nao foi para o disco ***")

        doc.remover(doc.offset_da_linha(0), len(b"linha um\n"))
        checa(proxima(doc, Criterio("linha um"), "utf-8", 0, 0) is None,
              "*** e NAO acha o que foi apagado, embora ele siga no arquivo ***")


def testar_substituir_todas() -> None:
    secao("Substituir todas")

    with pasta_temporaria() as tmp:
        doc = abrir(tmp, "trocar.txt", TEXTO)
        quantas = substituir_todas(doc, Criterio("alvo",
                                                 diferenciar_maiusculas=True),
                                   "utf-8", "MIRA")
        checa_igual(quantas, 3, "trocou as tres ocorrencias exatas")
        saida = doc.ler(0, doc.tamanho).decode("utf-8")
        checa("MIRA" in saida and "MIRAroco" in saida, "o texto novo entrou")
        checa("ALVO" in saida,
              "e a de caixa diferente ficou, como o criterio pedia")
        checa_igual(saida.count("MIRA"), 3, "sem trocar duas vezes o mesmo")

        # O caso que so' aparece quando o substituto tem tamanho DIFERENTE: do
        # comeco para o fim, a primeira troca desloca as demais.
        doc = abrir(tmp, "tamanhos.txt", b"aa X aa X aa X aa\n")
        substituir_todas(doc, Criterio("X"), "utf-8", "LONGO DEMAIS")
        checa_igual(doc.ler(0, doc.tamanho),
                    b"aa LONGO DEMAIS aa LONGO DEMAIS aa LONGO DEMAIS aa\n",
                    "*** com substituto MAIOR, as tres caem no lugar certo -- "
                    "e' o que a aplicacao de tras para a frente garante ***")

        doc = abrir(tmp, "menor.txt", b"aa LONGO aa LONGO aa\n")
        substituir_todas(doc, Criterio("LONGO"), "utf-8", "x")
        checa_igual(doc.ler(0, doc.tamanho), b"aa x aa x aa\n",
                    "e com substituto MENOR tambem")

        doc = abrir(tmp, "vazio.txt", TEXTO)
        checa_igual(substituir_todas(doc, Criterio("nao existe"), "utf-8", "x"),
                    0, "o que nao existe nao troca nada")


def testar_acentos_e_codec() -> None:
    secao("Acentos e codificacao")

    with pasta_temporaria() as tmp:
        doc = abrir(tmp, "acentos.txt",
                    "acao\ncoração\nCORAÇÃO\nnao\n".encode("utf-8"))
        achados = list(procurar(doc, Criterio("coração"), "utf-8"))
        checa_igual([a.linha for a in achados], [1, 2],
                    "*** sem diferenciar maiusculas acha CORAÇÃO tambem -- e' "
                    "por isso que a busca decodifica em vez de comparar bytes ***")

        doc = abrir(tmp, "cp.txt", "ação\ncoracao\n".encode("cp1252"))
        achado = proxima(doc, Criterio("ação"), "cp1252", 0, 0)
        checa(achado is not None and achado.linha == 0,
              "acha acento num arquivo cp1252")

        substituir_todas(doc, Criterio("coracao"), "cp1252", "coração")
        checa_igual(doc.ler(0, doc.tamanho), "ação\ncoração\n".encode("cp1252"),
                    "e o substituto sai na codificacao do arquivo")


def testar_arquivo_grande() -> None:
    secao("Busca fora da fatia carregada")

    with pasta_temporaria() as tmp:
        alvo = tmp / "grande.txt"
        with open(alvo, "wb", buffering=1024 * 1024) as f:
            for lote in range(0, 200_000, 50_000):
                f.write(b"".join(f"linha {i:08d} comum\n".encode()
                                 for i in range(lote, lote + 50_000)))
        # A agulha vai muito depois das ~5 mil linhas de uma fatia.
        original = Original(alvo)
        original.indexar()
        doc = Documento(original)
        doc.inserir(doc.offset_da_linha(150_000), b"AGULHA NO PALHEIRO\n")

        achado = proxima(doc, Criterio("AGULHA"), "utf-8", 0, 0)
        checa(achado is not None and achado.linha == 150_000,
              f"*** acha na linha 150.000, muito alem da fatia de 5 mil "
              f"linhas ({achado.linha if achado else 'nao achou'}) ***")
        original.fechar()


def main() -> int:
    testar_criterio()
    testar_procurar()
    testar_proxima_e_volta()
    testar_enxerga_o_digitado()
    testar_substituir_todas()
    testar_acentos_e_codec()
    testar_arquivo_grande()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
