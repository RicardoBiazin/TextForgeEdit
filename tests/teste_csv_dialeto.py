"""Deteccao de dialeto de CSV, sem Qt.

    .\\.venv\\Scripts\\python.exe tests\\teste_cd.py

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

from ajudantes import (checa, checa_igual, checa_levanta, resumir,
                       secao)

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



def testar_separadores_de_sistemas_legados() -> None:
    """`~`, `^` e `#` sao separadores de verdade, e nao eram considerados.

    Os dois primeiros aparecem em EDI e em extracao de mainframe JUSTAMENTE
    por quase nunca ocorrerem dentro do dado -- e' a mesma razao pela qual sao
    bons separadores e pela qual ninguem pensa neles.
    """
    secao("*** Separadores de sistemas legados: ~ ^ # ***")

    for sep, nome in (("~", "til"), ("^", "circunflexo"), ("#", "cerquilha")):
        texto = (f"nome{sep}valor{sep}data\n"
                 f"Ana{sep}1234{sep}01/02/2026\n"
                 f"Bruno{sep}99{sep}03/02/2026\n"
                 f"Carla{sep}7000{sep}05/02/2026\n")
        d = cd.detectar(texto)
        checa_igual(d.delimitador, sep, f"{nome}: reconhecido como separador")
        checa_igual(d.colunas, 3, f"{nome}: tres colunas")

    # A CONTRAPROVA. Acrescentar candidatos aumenta a chance de o detector ver
    # tabela onde nao ha' -- e um texto em portugues tem til em toda outra
    # palavra. Se este teste falhar, os candidatos novos custaram mais do que
    # renderam.
    prosa = ("Nao ha' irmao que sustente a manha de amanha, e a licao\n"
             "que a criacao nos da' e' a de que a razao tambem tem coracao.\n"
             "Sao tantas as ocasioes que a mao nao alcanca a solucao.\n"
             "A construcao da cancao e' a mesma da oracao: repeticao.\n")
    d = cd.detectar(prosa)
    checa(d.colunas < 2 or d.confianca < 50,
          f"*** e prosa cheia de til NAO vira tabela: {d.delimitador!r}, "
          f"{d.colunas} coluna(s), confianca {d.confianca} ***")


def testar_separador_escolhido_a_mao() -> None:
    """`com_delimitador` obedece, e a deteccao nao tem voto.

    Sem esta porta de saida o programa dizia "nao foi possivel reconhecer um
    separador" e o assunto acabava ali -- inclusive quando a pessoa sabia
    exatamente qual era o separador do proprio arquivo.
    """
    secao("*** O separador escolhido a' mao ***")

    # O caso MEDIDO em que a deteccao nao entrega: colunas separadas por
    # espaco. O espaco esta' fora dos CANDIDATOS de proposito -- se estivesse
    # la', toda prosa em portugues viraria uma tabela de dez colunas. A
    # deteccao esta' certa em recusar, e a escolha manual e' o unico caminho.
    #
    # (A primeira versao deste teste usava um log com horarios, supondo que os
    # dois-pontos ganhariam do ";". Medido: nao ganham -- o desempate por
    # PRESENCA ja' resolve. O caso do espaco e' real.)
    espaco = ("Ana    1234 SC\n"
              "Bruno  99   PR\n"
              "Carla  7000 RS\n"
              "Daniel 55   MG\n")
    automatico = cd.detectar(espaco)
    checa(automatico.colunas < 2 or automatico.confianca < 50,
          f"*** a deteccao RECUSA um arquivo separado por espaco "
          f"({automatico.delimitador!r}, {automatico.colunas} coluna(s), "
          f"confianca {automatico.confianca}) ***")
    escolhido = cd.com_delimitador(espaco, " ")
    checa_igual(escolhido.delimitador, " ", "obedece ao que foi escolhido")
    checa(escolhido.colunas >= 3,
          f"*** e escolhido a' mao ele abre, com {escolhido.colunas} "
          f"colunas: e' por isto que a escolha manual existe ***")
    checa_igual(escolhido.confianca, 100, "sem duvida: quem escolheu sabe")

    # E obedece mesmo quando a deteccao tinha um palpite bom e DIFERENTE.
    log = ("10:00:01;INFO;servidor iniciado\n"
           "10:00:05;WARN;cache frio\n"
           "10:01:00;INFO;42 requisicoes\n"
           "10:02:11;ERRO;tempo esgotado\n")
    checa_igual(cd.detectar(log).delimitador, ";",
                "a deteccao sozinha escolhe o ';' neste log")
    checa_igual(cd.com_delimitador(log, ":").delimitador, ":",
                "*** e a escolha manual nao e' uma sugestao: ela manda ***")

    # Um separador que nao esta' nos CANDIDATOS e nunca estara'.
    unidade = "\x1f"
    exotico = (f"a{unidade}b{unidade}c\n1{unidade}2{unidade}3\n"
               f"4{unidade}5{unidade}6\n")
    d = cd.com_delimitador(exotico, unidade)
    checa_igual(d.colunas, 3,
                "*** ate' o separador de unidade do ASCII serve, escolhido "
                "a' mao ***")

    # Campo entre aspas contendo o separador: contar o caractere na linha
    # crua daria uma coluna a mais.
    citado = 'nome;cidade;uf\nAna;"Sao Jose;SC";SC\nBruno;Blumenau;SC\n'
    d = cd.com_delimitador(citado, ";")
    checa_igual(d.colunas, 3,
                "*** o ';' DENTRO das aspas nao vira coluna: `com_delimitador` "
                "reparte de verdade, nao conta caracteres ***")

    # O que nao da' para honrar recusa, em vez de abrir uma grade errada.
    checa_levanta(ValueError, lambda: cd.com_delimitador(citado, '"'),
                  "aspa como separador e' recusada")
    checa_levanta(ValueError, lambda: cd.com_delimitador(citado, "\n"),
                  "quebra de linha tambem")
    checa_levanta(ValueError, lambda: cd.com_delimitador(citado, ";;"),
                  "e o separador e' UM caractere")


def testar_rotulos_cobrem_todo_candidato() -> None:
    secao("*** Todo separador oferecido tem nome em portugues ***")

    for candidato in cd.CANDIDATOS:
        checa(candidato in cd.ROTULO_DO_DELIMITADOR,
              f"{candidato!r} tem rotulo: "
              f"{cd.ROTULO_DO_DELIMITADOR.get(candidato)}")
    # A tela de escolha oferece os mesmos, mais o espaco.
    from tfedit.interface import separador as tela
    for oferecido in tela.OFERECIDOS:
        checa(oferecido in cd.ROTULO_DO_DELIMITADOR,
              f"*** a caixa de selecao nao mostra {oferecido!r} sem nome ***")


def testar_linha_gigante_nao_trava_a_deteccao() -> None:
    """Uma linha enorme nao pode fazer a deteccao levar minutos.

    REGRESSAO QUE EU INTRODUZI NA v0.14.0. O aviso "parece uma tabela" passou
    a chamar `dialeto_csv()` em TODO arquivo ao fim da varredura; antes, isso
    so' rodava quando alguem abria o menu Visualizar, e um arquivo de uma
    linha so' nunca passava por ali. E o `csv.Sniffer` do Python roda um
    `re.findall` cujo custo explode em linha longa: MEDIDO, um JSON minificado
    de 271 KB numa linha fazia a abertura levar 42 s, e um de 1,7 MB nao
    terminava. O arquivo abria; a janela e' que ficava parada -- e um JSON
    minificado e' exatamente o arquivo que alguem abre para mandar FORMATAR.

    Medido depois do corte: 0,07 s e 0,40 s.
    """
    secao("*** Uma linha gigante nao trava a deteccao de dialeto ***")

    import time

    minificado = "{" + ",".join(f'"c{i}":{i}' for i in range(120_000)) + "}"
    checa(len(minificado) > 1_500_000,
          f"o JSON de teste tem {len(minificado) / 1048576:.1f} MB numa "
          f"linha so'")

    inicio = time.monotonic()
    dialeto = cd.detectar(minificado)
    gasto = time.monotonic() - inicio
    checa(gasto < 2.0,
          f"*** detectar levou {gasto:.2f}s -- antes do corte por linha, um "
          f"arquivo deste tamanho nao terminava ***")

    # A amostra corta a linha, e o corte tem de estar la'.
    linhas = cd._linhas_de_amostra(minificado)
    checa(linhas and len(linhas[0]) == cd.CARACTERES_POR_LINHA_NA_AMOSTRA,
          f"*** a linha da amostra vem truncada em "
          f"{cd.CARACTERES_POR_LINHA_NA_AMOSTRA} caracteres ***")

    # E CORTAR NAO PIORA A DETECCAO: um CSV de verdade com linhas longas
    # continua sendo reconhecido, porque o separador se identifica nos
    # primeiros campos, e nao no fim da linha.
    largo = "\n".join(
        ";".join(f"campo{c}valor{'x' * 200}" for c in range(40))
        for _ in range(10))
    checa(len(largo.split("\n")[0]) > cd.CARACTERES_POR_LINHA_NA_AMOSTRA,
          "a linha deste CSV passa do corte")
    checa_igual(cd.detectar(largo).delimitador, ";",
                "*** e ele continua sendo reconhecido ***")


def testar_uma_linha_so_nao_e_tabela() -> None:
    """Com uma linha apenas, "consistencia entre as linhas" nao diz nada.

    E' o principio do modulo inteiro: o delimitador e' escolhido pela
    consistencia ENTRE AS LINHAS, e nao pela frequencia do caractere. Com uma
    linha so', toda contagem e' trivialmente consistente e qualquer caractere
    frequente ganha -- um JSON minificado saia daqui como "tabela de 393
    colunas, confianca 100" por causa das virgulas, e a janela sugeria abri-lo
    em colunas.
    """
    secao("*** Uma linha so' nao e' tabela ***")

    minificado = "{" + ",".join(f'"c{i}":{i}' for i in range(2_000)) + "}"
    d = cd.detectar(minificado)
    checa(d.colunas < 2 or d.confianca < 50,
          f"*** um JSON minificado NAO vira tabela: {d.delimitador!r}, "
          f"{d.colunas} coluna(s), confianca {d.confianca} ***")
    checa("uma linha" in d.como_decidiu,
          f"e o motivo fica registrado: {d.como_decidiu!r}")

    # DUAS linhas ja' bastam para decidir: o corte e' em "nao ha' o que
    # comparar", e nao em "arquivo pequeno demais".
    duas = "nome;cidade;uf\nAna;Blumenau;SC\n"
    d2 = cd.detectar(duas)
    checa_igual(d2.delimitador, ";",
                "*** com duas linhas a deteccao volta a funcionar ***")
    checa_igual(d2.colunas, 3, "com as tres colunas")

    # E a escolha MANUAL continua valendo numa linha so': quem escolhe sabe.
    escolhido = cd.com_delimitador("a;b;c;d", ";")
    checa_igual(escolhido.colunas, 4,
                "*** e escolhido a' mao, um arquivo de uma linha abre igual: "
                "a duvida era da heuristica, nao do usuario ***")

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
    testar_separadores_de_sistemas_legados()
    testar_separador_escolhido_a_mao()
    testar_rotulos_cobrem_todo_candidato()
    testar_linha_gigante_nao_trava_a_deteccao()
    testar_uma_linha_so_nao_e_tabela()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
