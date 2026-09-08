"""Dialeto de um CSV: delimitador, aspas, cabecalho e numero de colunas.

Porte do `analisadores/de_csv.py` do TextForge, com DUAS diferencas que sao
decisoes deste projeto e nao descuido do porte.

1. `dividir_registros(texto)` NAO veio.

   La' ela existe porque um campo entre aspas pode conter quebra de linha, e
   dividir por "\\n" partiria o registro ao meio deslocando a tabela dali para
   a frente. O problema e' real; a solucao dela nao cabe aqui, porque recebe o
   texto INTEIRO -- e' exatamente a assinatura que este editor existe para nao
   ter. E nao ha' versao barata: saber se a linha N comeca dentro de aspas
   exige varrer do byte 0.

   Entao aqui **uma linha e' um registro**. Isso e' uma limitacao, e ela nao
   pode ser silenciosa: `linha_suspeita()` marca as linhas com aspas
   desbalanceadas, e a grade as mostra em destaque e recusa edita-las. Nao se
   corrompe o que nao se consegue analisar.

2. `fatias_de_campos()` foi ACRESCENTADA.

   Ela diz onde cada campo comeca e acaba DENTRO do registro. E' o que permite
   trocar so' os bytes do campo editado: reconstruir o registro inteiro com
   `montar_registro` reescreveria todos os campos com o quoting minimo do
   modulo `csv`, tirando aspas legitimas de campos que ninguem tocou.

O que ficou igual, e vale repetir porque e' contraintuitivo: a pontuacao do
delimitador e' pela CONSISTENCIA -- a fracao de linhas com a mesma contagem --,
e nao pela frequencia do caractere. Num CSV brasileiro com ";" separando 8
colunas e virgulas decimais nos valores, a virgula aparece MAIS; por frequencia
ela ganharia, por consistencia nao.

Tudo aqui trabalha sobre texto ja' decodificado, com "\\n" como quebra.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass

from tfedit import log_interno

log = log_interno.obter(__name__)

#: Na ordem de utilidade nesta maquina: ";" primeiro porque e' o separador do
#: CSV brasileiro (o Excel em pt-BR usa ";" porque a virgula e' o decimal).
CANDIDATOS = (";", ",", "\t", "|", ":")

#: Quantas linhas olhar para decidir. Mais que isto nao melhora e custa.
LINHAS_DE_AMOSTRA = 50

#: Fracao minima de linhas que precisam concordar na contagem do delimitador.
CONCORDANCIA_MINIMA = 0.8


@dataclass(frozen=True)
class Dialeto:
    delimitador: str = ";"
    aspas: str = '"'
    tem_cabecalho: bool = True
    colunas: int = 0
    confianca: int = 0
    como_decidiu: str = ""

    @property
    def rotulo_do_delimitador(self) -> str:
        return {";": "ponto e vírgula", ",": "vírgula", "\t": "TAB",
                "|": "barra vertical", ":": "dois-pontos"}.get(
                    self.delimitador, repr(self.delimitador))

    def descrever(self) -> str:
        cabecalho = "com cabeçalho" if self.tem_cabecalho else "sem cabeçalho"
        return (f"{self.rotulo_do_delimitador} · {self.colunas} coluna(s) · "
                f"{cabecalho}")


# ======================================================================
# Um registro
# ======================================================================

def campos_de(registro: str, dialeto: Dialeto) -> list[str]:
    """Os campos de UM registro."""
    if not registro:
        return [""]
    leitor = csv.reader(io.StringIO(registro), delimiter=dialeto.delimitador,
                        quotechar=dialeto.aspas)
    try:
        return next(leitor, [])
    except csv.Error:
        # Registro malformado (aspas desbalanceadas). Devolver o texto cru numa
        # coluna e' melhor que perder a linha -- assim o problema fica visivel
        # e a pessoa corrige.
        return [registro]


def montar_registro(campos: list[str], dialeto: Dialeto) -> str:
    """Campos -> texto de um registro, com o quoting minimo necessario."""
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=dialeto.delimitador,
                          quotechar=dialeto.aspas, quoting=csv.QUOTE_MINIMAL,
                          lineterminator="")
    escritor.writerow(campos)
    return saida.getvalue()


def fatias_de_campos(registro: str, dialeto: Dialeto) -> list[tuple[int, int]]:
    """Onde cada campo COMECA e ACABA no registro, em indices de caractere.

    Inclui as aspas quando o campo esta' entre elas: a fatia e' o texto BRUTO
    que representa aquele campo, e nao o valor dele. E' o que permite trocar um
    campo sem tocar nos outros -- ver o cabecalho.

        'a;"b;c";d'  ->  [(0, 1), (2, 7), (8, 9)]
    """
    if not registro:
        return [(0, 0)]

    fatias: list[tuple[int, int]] = []
    inicio = 0
    dentro = False
    i = 0
    while i < len(registro):
        ch = registro[i]
        if ch == dialeto.aspas:
            # Aspas dobradas dentro de um campo citado sao um literal, e nao o
            # fim do campo.
            if dentro and i + 1 < len(registro) \
                    and registro[i + 1] == dialeto.aspas:
                i += 2
                continue
            dentro = not dentro
        elif ch == dialeto.delimitador and not dentro:
            fatias.append((inicio, i))
            inicio = i + 1
        i += 1
    fatias.append((inicio, len(registro)))
    return fatias


def linha_suspeita(linha: str, dialeto: Dialeto) -> bool:
    """A linha tem aspas desbalanceadas?

    Sinal de que o registro continua na linha seguinte -- o caso que este
    modulo NAO analisa (ver o cabecalho). Quem chama marca a linha e recusa
    edita-la, em vez de gravar por cima de um registro que entendeu errado.
    """
    aspas = 0
    i = 0
    while i < len(linha):
        if linha[i] == dialeto.aspas:
            if i + 1 < len(linha) and linha[i + 1] == dialeto.aspas:
                i += 2
                continue
            aspas += 1
        i += 1
    return aspas % 2 == 1


# ======================================================================
# Deteccao
# ======================================================================

def _contar_fora_de_aspas(linha: str, delimitador: str, aspas: str) -> int:
    total = 0
    dentro = False
    i = 0
    while i < len(linha):
        ch = linha[i]
        if ch == aspas:
            if dentro and i + 1 < len(linha) and linha[i + 1] == aspas:
                i += 2
                continue
            dentro = not dentro
        elif ch == delimitador and not dentro:
            total += 1
        i += 1
    return total


def _pontuar(linhas: list[str], delimitador: str,
             aspas: str) -> tuple[int, int, int]:
    """(pontuacao 0..100, contagem modal, presenca 0..100) de um candidato.

    A pontuacao e' a fracao de linhas com a MESMA contagem, e nao a frequencia
    do caractere. Ver o cabecalho do modulo: e' o que distingue um separador de
    um caractere que so' aparece muito.

    A PRESENCA -- em quantas linhas o candidato aparece ao menos uma vez -- e'
    devolvida a parte porque e' o melhor criterio de desempate. Ver `detectar`.
    """
    contagens = [_contar_fora_de_aspas(l, delimitador, aspas) for l in linhas]
    validas = [c for c in contagens if c > 0]
    if not validas:
        return 0, 0, 0

    frequencia: dict[int, int] = {}
    for c in validas:
        frequencia[c] = frequencia.get(c, 0) + 1
    modal, quantas = max(frequencia.items(), key=lambda p: (p[1], p[0]))

    presenca = int(len(validas) / len(linhas) * 100)
    # Exige presenca na maioria das linhas: um delimitador que so' aparece em
    # duas de trinta linhas nao e' o separador do arquivo.
    if presenca < CONCORDANCIA_MINIMA * 100:
        return 0, modal, presenca
    return int(quantas / len(validas) * 100), modal, presenca


def _linhas_de_amostra(texto: str) -> list[str]:
    linhas = []
    for linha in texto.split("\n"):
        if linha.strip():
            linhas.append(linha)
        if len(linhas) >= LINHAS_DE_AMOSTRA:
            break
    return linhas


_NUMERO = re.compile(r"^\s*[-+]?[\d.,]+\s*$")


def e_numero(campo: str) -> bool:
    """O campo e' numerico? Usado no cabecalho e no alinhamento da grade."""
    return bool(campo.strip()) and bool(_NUMERO.match(campo)) and any(
        c.isdigit() for c in campo)


def _tem_cabecalho(registros: list[list[str]]) -> bool:
    """A primeira linha e' cabecalho?

    Duas evidencias: a primeira linha nao tem nenhum campo NUMERICO, e alguma
    linha seguinte tem numero na MESMA coluna. E' a regra que funciona em
    arquivo de dados de verdade, onde o cabecalho e' texto e os dados tem
    numero.
    """
    if len(registros) < 2:
        return False
    primeira = registros[0]
    if not primeira or any(e_numero(c) for c in primeira):
        return False
    for coluna in range(len(primeira)):
        for registro in registros[1:6]:
            if coluna < len(registro) and e_numero(registro[coluna]):
                return True
    # Nenhum numero em lugar nenhum: se a primeira linha tem campos curtos e
    # todos preenchidos, ainda e' provavel que seja cabecalho.
    return all(c.strip() and len(c) < 40 for c in primeira)


def chave_de_ordenacao(campo: str, dialeto: Dialeto) -> float | str:
    """Valor para ORDENAR a coluna. `float` quando o campo e' numero.

    Sem isto a grade ordena como texto e "10" vem antes de "9" -- defeito que
    aparece no primeiro clique num cabecalho de coluna numerica.

    O separador decimal e' DEDUZIDO, e nao adivinhado:

      * os DOIS separadores presentes -> o ULTIMO e' o decimal. "1.234,56" e
        "1,234.56" ficam certos sem precisar saber a regiao.
      * so' um presente -> o delimitador do arquivo decide. Num CSV separado
        por ";" a virgula e' decimal (e' justamente por isso que o Excel em
        pt-BR usa ";"); num separado por "," a virgula nao poderia estar solta
        dentro de um numero, entao o ponto e' que e' o decimal.
    """
    texto = campo.strip()
    if not e_numero(texto):
        return campo
    tem_ponto, tem_virgula = "." in texto, "," in texto
    if tem_ponto and tem_virgula:
        decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
    elif tem_virgula:
        decimal = "," if dialeto.delimitador == ";" else "."
    else:
        decimal = "."
    milhar = "," if decimal == "." else "."
    try:
        return float(texto.replace(milhar, "").replace(decimal, "."))
    except ValueError:
        # "1.2.3" e afins: e' texto com cara de numero. Ordenar como texto e'
        # melhor que descartar a linha.
        return campo


def detectar(texto: str, aspas: str = '"') -> Dialeto:
    """Descobre o dialeto. Nunca levanta -- sempre devolve um palpite usavel.

    `texto` e' uma AMOSTRA (as primeiras dezenas de linhas), nunca o arquivo.
    """
    linhas = _linhas_de_amostra(texto)
    if not linhas:
        return Dialeto(colunas=0, confianca=0, como_decidiu="arquivo vazio")

    melhor = ";"
    melhor_nota = 0
    melhor_contagem = 0
    melhor_presenca = 0
    for candidato in CANDIDATOS:
        nota, contagem, presenca = _pontuar(linhas, candidato, aspas)
        # DESEMPATE, e a ordem importa:
        #
        # 1. presenca -- em quantas linhas o candidato aparece. Um separador de
        #    verdade esta' em TODAS, inclusive no cabecalho. Num export
        #    brasileiro com "produto;preco;desconto" no topo e valores como
        #    "1,50" embaixo, a virgula tem contagem uniforme nos DADOS e some
        #    no cabecalho; o ";" esta' em toda linha. Sem este criterio a
        #    virgula ganhava pelo item 2 e a tabela abria com as colunas
        #    partidas no meio dos valores.
        #
        # 2. contagem -- num arquivo com ";" separando 8 colunas e ":"
        #    aparecendo uma vez por linha num horario, os dois sao
        #    consistentes, mas o de 8 e' o separador.
        atual = (nota, presenca, contagem)
        campeao = (melhor_nota, melhor_presenca, melhor_contagem)
        if atual > campeao:
            melhor = candidato
            melhor_nota, melhor_presenca, melhor_contagem = nota, presenca, contagem

    como = "consistência entre as linhas"
    if melhor_nota == 0:
        # Nenhum candidato convence: pode ser um arquivo de uma coluna so'.
        return Dialeto(delimitador=";", aspas=aspas, tem_cabecalho=False,
                       colunas=1, confianca=20,
                       como_decidiu="nenhum delimitador encontrado")

    # O `Sniffer` roda em paralelo: quando ele CONCORDA, a confianca vai a 100.
    try:
        farejado = csv.Sniffer().sniff("\n".join(linhas[:20]),
                                       delimiters="".join(CANDIDATOS))
        if farejado.delimiter == melhor:
            melhor_nota = 100
            como = "consistência + csv.Sniffer concordam"
    except (csv.Error, TypeError, ValueError):
        # O Sniffer levanta em arquivo de uma linha e em varios casos
        # legitimos. Nao e' erro: a heuristica propria ja' decidiu.
        pass

    parcial = Dialeto(delimitador=melhor, aspas=aspas, tem_cabecalho=False,
                      colunas=melhor_contagem + 1, confianca=melhor_nota,
                      como_decidiu=como)

    # Uma linha = um registro, ver o cabecalho.
    registros = [campos_de(l, parcial) for l in linhas[:10]]
    registros = [r for r in registros if r and any(c.strip() for c in r)]
    colunas = max((len(r) for r in registros), default=melhor_contagem + 1)
    return Dialeto(delimitador=melhor, aspas=aspas,
                   tem_cabecalho=_tem_cabecalho(registros), colunas=colunas,
                   confianca=melhor_nota, como_decidiu=como)


def parece_csv(texto: str) -> bool:
    """Vale a pena oferecer a grade para este conteudo?"""
    dialeto = detectar(texto)
    return dialeto.confianca >= 70 and dialeto.colunas >= 2
