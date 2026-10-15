"""Exporta UMA aba da planilha para CSV, com o separador e a codificacao escolhidos.

Sem Qt: a janela escolhe o separador e o destino, e este modulo so' formata e
grava. Assim o formato e' testavel sem tela.

O que vai para o arquivo e' o que a grade MOSTRA, edicoes ainda nao gravadas
inclusive -- e' o mesmo texto de `Celula.texto`. Uma celula de formula sai pelo
VALOR que o Excel calculou e guardou (`cache`), e nao pela formula: um CSV com
`=SOMA(A1:A3)` seria um arquivo que so' faz sentido dentro de uma planilha.

O .xlsx de origem NAO muda. A exportacao le a aba da pasta aberta e grava um
arquivo novo, com a mesma troca atomica do resto do programa.
"""

from __future__ import annotations

import csv
import io

from tfedit import conversao, gravacao
from tfedit.planilha.pasta import TIPO_FORMULA, Celula, Folha

#: Quebra de linha do Windows, que e' o que o Excel grava. Um CSV com LF abre
#: certo no Excel mas quebra em alguns programas do mesmo Windows.
FIM_DE_LINHA = "\r\n"

#: Caracteres que nao podem ser separador: aspas quebrariam o csv, e quebra de
#: linha faria cada campo virar uma linha.
PROIBIDOS = ('"', "\n", "\r")


def texto_da_celula(celula: Celula) -> str:
    """O que a celula vira no CSV: o valor, nunca a formula."""
    if celula.tipo == TIPO_FORMULA and celula.cache:
        return celula.cache
    return celula.texto


def como_csv(folha: Folha, *, separador: str = ";",
             alvo: "conversao.Alvo | None" = None) -> bytes:
    """A aba inteira em bytes, na codificacao `alvo`.

    Levanta `NaoRepresentavel` quando a codificacao nao escreve algum caractere
    -- e' a mesma recusa da conversao: gravar "?" no lugar seria perder dado sem
    aviso. Levanta `ValueError` para um separador que nao da' para usar.
    """
    if len(separador) != 1 or separador in PROIBIDOS:
        raise ValueError(f"{separador!r} não pode ser separador de colunas")
    alvo = alvo or conversao.ALVOS[0]

    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=separador,
                          lineterminator=FIM_DE_LINHA)
    for linha in range(1, folha.linhas + 1):
        escritor.writerow([texto_da_celula(folha.celula(linha, coluna))
                           for coluna in range(1, folha.colunas + 1)])
    texto = saida.getvalue()

    try:
        corpo = texto.encode(alvo.codec)
    except UnicodeEncodeError as erro:
        # `erro.start` e' indice DENTRO do texto, e nao dentro dos bytes: e'
        # por isso que a linha sai contando as quebras ate' ali.
        caractere = texto[erro.start]
        linha = texto.count("\n", 0, erro.start) + 1
        raise conversao.NaoRepresentavel(caractere, linha,
                                         alvo.rotulo) from erro
    return alvo.bom + corpo


def exportar(folha: Folha, destino, *, separador: str = ";",
             alvo: "conversao.Alvo | None" = None) -> tuple[int, int]:
    """Grava a aba no arquivo `destino`. Devolve (linhas, colunas) exportadas.

    A gravacao e' atomica: uma falha no meio deixa um arquivo anterior do mesmo
    nome exatamente como estava.
    """
    dados = como_csv(folha, separador=separador, alvo=alvo)
    gravacao.gravar_bytes(destino, dados)
    return folha.linhas, folha.colunas
