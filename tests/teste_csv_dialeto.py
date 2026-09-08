"""Deteccao de dialeto de CSV, sem Qt.

    .\\.venv\\Scripts\\python.exe tests\\teste_csv_dialeto.py

O teste que importa e' `testar_csv_brasileiro`, e ele tem CONTRAPROVA: o mesmo
arquivo tem mais virgulas que ponto e virgulas. Se alguem trocar a pontuacao
por CONSISTENCIA (a fracao de linhas com a mesma contagem) por uma contagem de
frequencia, a virgula ganha e o teste falha. Sem essa contraprova o teste
passaria com a heuristica trocada, e nao guardaria nada.

`fatias_de_campos` e' o outro ponto: ela existe para a edicao cirurgica de uma
celula, e um erro nela grava por cima do campo errado.
"""

from __future__ import annotations

import sys

from ajudantes import checa, checa_igual, resumir, secao

from tfedit import csv_dialeto as cd


def testar_csv_brasileiro() -> None:
    secao("*** CSV brasileiro: ';' separando, ',' decimal ***")

    # A amostra precisa ter MAIS virgulas que ponto e virgulas, senao a
    # contraprova abaixo nao prova nada -- e' o caso de um export de ERP em
    # pt-BR, onde cada linha traz varios decimais e descricoes com virgula.
    texto = "\n".join([
        "produto;preco;desconto",
        "Parafuso 3,5mm, cabeca chata;1.234,56;10,50",
        "Porca 1/2, galvanizada;12,90;1,20",
        "Arruela lisa, 3/8;0,35;0,05",
        "Bucha 8mm, nylon;3,10;0,40",
        "Prego 17x27, 1kg;28,75;2,80",
        "Abracadeira, aco inox;15,40;1,90",
        "Rebite 4,8mm, aluminio;7,25;0,70",
        "Broca 6mm, widia;22,10;3,30",
    ])

    virgulas = texto.count(",")
    pontos_e_virgulas = texto.count(";")
    checa(virgulas > pontos_e_virgulas,
          f"*** a CONTRAPROVA: ha' {virgulas} vírgulas contra "
          f"{pontos_e_virgulas} ponto e vírgulas -- por FREQUÊNCIA a vírgula "
          f"ganharia ***")

    dialeto = cd.detectar(texto)
    checa_igual(dialeto.delimitador, ";",
                "*** e mesmo assim o delimitador é ';', porque a pontuação é "
                "pela consistência das contagens ***")
    checa_igual(dialeto.colunas, 3, "três colunas")
    checa(dialeto.tem_cabecalho,
          "e a primeira linha é cabeçalho: texto em cima, número embaixo")
    checa(dialeto.confianca >= 70,
          f"com confiança de {dialeto.confianca}")


def testar_desempate_pelo_cabecalho() -> None:
    secao("*** Empate resolvido pela presenca em TODAS as linhas ***")

    # O caso degenerado: dados perfeitamente uniformes, em que ";" e "," sao
    # AMBOS 100% consistentes. Aqui a virgula tem contagem maior (3 contra 2),
    # e o desempate por contagem sozinho escolheria ela -- abrindo a tabela com
    # as colunas partidas no meio dos valores.
    #
    # O que decide e' o CABECALHO: ele tem ";" e nao tem virgula nenhuma.
    texto = "\n".join(
        ["produto;preco;desconto"]
        + [f"Parafuso 3,5mm {i};{i},50;0,{i % 10}0" for i in range(30)])

    linhas = texto.split("\n")
    virgulas = [l.count(",") for l in linhas]
    checa(len(set(virgulas[1:])) == 1 and virgulas[0] == 0,
          f"*** a CONTRAPROVA: nos dados a vírgula é tão uniforme quanto o "
          f"';' ({virgulas[1]} por linha), e some no cabeçalho ***")

    dialeto = cd.detectar(texto)
    checa_igual(dialeto.delimitador, ";",
                "*** e o ';' vence, porque aparece em TODAS as linhas ***")
    checa_igual(dialeto.colunas, 3,
                "três colunas, e não as quatro que a vírgula daria")


def testar_outros_delimitadores() -> None:
    secao("TAB, barra e vírgula")

    for delim, nome in ((",", "vírgula"), ("\t", "TAB"), ("|", "barra")):
        texto = "\n".join(delim.join(f"c{i}" for i in range(4))
                          for _ in range(6))
        dialeto = cd.detectar(texto)
        checa_igual(dialeto.delimitador, delim, f"reconhece {nome}")
        checa_igual(dialeto.colunas, 4, f"com 4 colunas ({nome})")


def testar_delimitador_dentro_de_aspas() -> None:
    secao("Um delimitador entre aspas nao conta")

    texto = "\n".join([
        'nome;observacao;valor',
        'Ana;"mora na rua A; numero 5";10',
        'Bruno;"trabalha das 8; volta as 18";20',
        'Carla;"sem ponto e virgula aqui";30',
    ])
    dialeto = cd.detectar(texto)
    checa_igual(dialeto.colunas, 3,
                "*** três colunas, e não quatro: o ';' dentro das aspas é "
                "conteúdo ***")

    campos = cd.campos_de('Ana;"mora na rua A; numero 5";10', dialeto)
    checa_igual(campos, ["Ana", "mora na rua A; numero 5", "10"],
                "e os campos saem inteiros")


def testar_arquivo_de_uma_coluna() -> None:
    secao("Um arquivo sem delimitador nenhum")

    dialeto = cd.detectar("linha um\nlinha dois\nlinha tres\n")
    checa_igual(dialeto.colunas, 1, "uma coluna")
    checa(dialeto.confianca < 70,
          f"e a confiança fica baixa ({dialeto.confianca}) -- não é tabela")
    checa(not cd.parece_csv("linha um\nlinha dois\n"),
          "`parece_csv` diz que não vale a pena oferecer a grade")


def testar_ida_e_volta_do_registro() -> None:
    secao("campos_de e montar_registro fecham o ciclo")

    dialeto = cd.Dialeto(delimitador=";")
    casos = [
        "a;b;c",
        'a;"b;c";d',
        'a;"diz ""oi""";c',
        ";;",
        "so_um_campo",
        'a;"";c',
    ]
    for registro in casos:
        volta = cd.montar_registro(cd.campos_de(registro, dialeto), dialeto)
        checa_igual(cd.campos_de(volta, dialeto),
                    cd.campos_de(registro, dialeto),
                    f"ida e volta preserva os campos de {registro!r}")


def testar_fatias_de_campos() -> None:
    secao("*** fatias_de_campos: a base da edicao cirurgica ***")

    dialeto = cd.Dialeto(delimitador=";")

    registro = 'a;"b;c";d'
    fatias = cd.fatias_de_campos(registro, dialeto)
    checa_igual(len(fatias), 3, "três campos")
    checa_igual(registro[fatias[0][0]:fatias[0][1]], "a", "o primeiro")
    checa_igual(registro[fatias[1][0]:fatias[1][1]], '"b;c"',
                '*** o segundo sai COM as aspas: a fatia é o texto bruto, e é '
                'isso que permite trocar um campo sem reescrever os outros ***')
    checa_igual(registro[fatias[2][0]:fatias[2][1]], "d", "o terceiro")

    checa_igual(cd.fatias_de_campos("a;b;c", dialeto), [(0, 1), (2, 3), (4, 5)],
                "sem aspas, as fatias são as óbvias")
    checa_igual(cd.fatias_de_campos("", dialeto), [(0, 0)],
                "registro vazio tem um campo vazio")
    checa_igual(cd.fatias_de_campos(";;", dialeto),
                [(0, 0), (1, 1), (2, 2)], "três campos vazios")

    # O que a edicao cirurgica de fato faz: trocar SO' a fatia do campo 0.
    fatias = cd.fatias_de_campos(registro, dialeto)
    ini, fim = fatias[0]
    novo = registro[:ini] + "XX" + registro[fim:]
    checa_igual(novo, 'XX;"b;c";d',
                '*** trocando o campo 0, as aspas do campo 1 sobrevivem ***')


def testar_linha_suspeita() -> None:
    secao("*** Registro que continua na linha seguinte e' SINALIZADO ***")

    dialeto = cd.Dialeto(delimitador=";")
    checa(cd.linha_suspeita('a;"comeca aqui', dialeto),
          "*** aspas desbalanceadas: o registro continua na próxima linha ***")
    checa(not cd.linha_suspeita('a;"fechado";c', dialeto),
          "aspas balanceadas: linha inteira")
    checa(not cd.linha_suspeita('a;"diz ""oi""";c', dialeto),
          "aspas dobradas são literal, e não abertura")
    checa(not cd.linha_suspeita("a;b;c", dialeto), "sem aspas, sem suspeita")


def testar_chave_de_ordenacao() -> None:
    secao("Ordenar numero como numero")

    ponto_e_virgula = cd.Dialeto(delimitador=";")
    virgula = cd.Dialeto(delimitador=",")

    checa(cd.chave_de_ordenacao("10", ponto_e_virgula)
          > cd.chave_de_ordenacao("9", ponto_e_virgula),
          '*** "10" vem depois de "9" -- como texto viria antes ***')
    checa_igual(cd.chave_de_ordenacao("1.234,56", ponto_e_virgula), 1234.56,
                "os dois separadores: o último é o decimal")
    checa_igual(cd.chave_de_ordenacao("1,234.56", virgula), 1234.56,
                "e o inverso também")
    checa_igual(cd.chave_de_ordenacao("12,90", ponto_e_virgula), 12.90,
                "num CSV por ';' a vírgula solta é decimal")
    checa_igual(cd.chave_de_ordenacao("Parafuso", ponto_e_virgula), "Parafuso",
                "texto continua texto")
    checa_igual(cd.chave_de_ordenacao("1.2.3", ponto_e_virgula), "1.2.3",
                "o que tem cara de número mas não é, ordena como texto")


def testar_registro_malformado_nao_perde_a_linha() -> None:
    secao("Aspas desbalanceadas nao descartam a linha")

    dialeto = cd.Dialeto(delimitador=";")
    campos = cd.campos_de('a;"sem fechar;c', dialeto)
    checa(campos, "devolve algo em vez de perder a linha")
    checa("".join(campos).replace(";", "") != "",
          f"e o conteúdo continua visível: {campos}")


def main() -> int:
    testar_csv_brasileiro()
    testar_desempate_pelo_cabecalho()
    testar_outros_delimitadores()
    testar_delimitador_dentro_de_aspas()
    testar_arquivo_de_uma_coluna()
    testar_ida_e_volta_do_registro()
    testar_fatias_de_campos()
    testar_linha_suspeita()
    testar_chave_de_ordenacao()
    testar_registro_malformado_nao_perde_a_linha()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
