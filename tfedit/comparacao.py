"""Comparar dois arquivos sem carregar nenhum dos dois.

TRES DECISOES, e as tres saem da mesma pergunta: o que cabe na memoria.

1. COMPARA-SE O HASH DA LINHA, E NAO A LINHA.

   Um `difflib.SequenceMatcher` alimentado com as linhas guarda todas elas mais
   um dicionario de "linha -> posicoes onde ela aparece". Para um export de
   200 mil linhas isso passa de 100 MB; com o hash de 8 bytes por linha, sao
   1,6 MB.

   O risco de duas linhas DIFERENTES terem o mesmo hash existe e e' desprezivel:
   o `hash()` de CPython para bytes tem 64 bits, e com um milhao de linhas a
   chance de qualquer colisao fica na casa de 3 em 100 milhoes. E' o mesmo
   risco que o `SequenceMatcher` ja' correria sozinho -- ele tambem indexa por
   hash --, so' que aqui ele esta' escrito.

2. O RESULTADO SAO OS BLOCOS, E NAO AS LINHAS ALINHADAS.

   Alinhar 200 mil linhas numa lista de pares custaria outros 100 MB para
   guardar o que a tela nunca vai mostrar de uma vez. O que fica na memoria sao
   os OPCODES do difflib -- proporcionais ao numero de DIFERENCAS, nao ao
   tamanho dos arquivos --, e a linha exibida N e' resolvida na hora por uma
   busca binaria sobre as somas acumuladas.

   Dois arquivos iguais de 1 GB produzem UM bloco.

3. O DIFFLIB SOZINHO NAO SERVE, E ISSO FOI MEDIDO.

   Dois arquivos de 200 mil linhas com UMA mudanca a cada dez -- duas versoes
   de um export, com 10% das linhas alteradas -- passam de DOIS MINUTOS no
   `difflib.SequenceMatcher`. A curva medida nao deixa duvida:

       5 mil linhas   0,24 s
      10 mil linhas   0,96 s      (4x)
      20 mil linhas   4,63 s      (4,8x)
      40 mil linhas  27,94 s      (6x)

   Dobrar o tamanho quintuplica o tempo. Nao e' um teto que resolve: seria
   preciso recusar qualquer arquivo acima de umas 20 mil linhas, e um editor
   feito para arquivo grande recusando comparar 30 mil linhas seria piada.

   A saida e' ANCORAR NAS LINHAS UNICAS, que e' o que o `git` faz no diff de
   paciencia: uma linha que aparece EXATAMENTE UMA VEZ nos dois arquivos so'
   pode corresponder a si mesma. Essas ancoras cortam o problema em pedacos
   pequenos, e o `difflib` so' roda dentro de cada pedaco.

   Sobra um teto, mas agora ele existe para o caso patologico -- um arquivo sem
   nenhuma linha unica --, e nao para o caso comum.

O QUE CONTA COMO LINHA IGUAL: `Documento.faixa` ja' devolve a linha sem o
terminador, entao dois arquivos que diferem SO' no fim de linha (CRLF contra LF)
saem como identicos. E' o que se espera de "comparar arquivos" -- quem quer ver
essa diferenca usa o visualizador hexadecimal.
"""

from __future__ import annotations

import bisect
import difflib
from array import array
from dataclasses import dataclass, field

from tfedit import log_interno

log = log_interno.obter(__name__)

#: Linhas lidas por vez ao levantar os hashes. Mesmo motivo do resto do
#: projeto: uma travessia da tabela de pecas por bloco, e nao por linha.
BLOCO = 4096

#: Teto de linhas por arquivo, quando a configuracao nao diz outro.
TETO_DE_LINHAS = 500_000

#: Um trecho SEM nenhuma linha unica maior que isto vira um bloco so'.
#:
#: E' a valvula do caso patologico: um arquivo em que quase toda linha se
#: repete (uma coluna de zeros, um log de uma mensagem so') nao tem ancora
#: nenhuma, e o `difflib` voltaria a ser quadratico. Perde-se o alinhamento
#: fino DENTRO desse trecho -- ele aparece como "este pedaco mudou" --, o que e'
#: honesto: num trecho de mil linhas iguais entre si, dizer QUAL delas mudou e'
#: uma escolha arbitraria de qualquer jeito.
LIMITE_SEM_ANCORA = 4000

IGUAL = "igual"
ALTERADA = "alterada"
SO_A = "so_a"
SO_B = "so_b"


class GrandeDemais(ValueError):
    """Um dos arquivos passa do teto de linhas para comparar."""


@dataclass(frozen=True)
class Par:
    """Uma linha da tela: o que esta' na esquerda, na direita, e o que houve.

    `linha_a` ou `linha_b` sao None quando aquele lado nao tem linha -- e' o
    espaco em branco que mantem os dois paineis alinhados.
    """

    tipo: str
    linha_a: int | None
    linha_b: int | None


@dataclass
class Resumo:
    iguais: int = 0
    alteradas: int = 0
    so_a: int = 0
    so_b: int = 0

    @property
    def diferencas(self) -> int:
        return self.alteradas + self.so_a + self.so_b

    def descrever(self) -> str:
        if not self.diferencas:
            return "Os dois arquivos são iguais."
        partes = []
        if self.alteradas:
            partes.append(f"{self.alteradas:n} alterada(s)")
        if self.so_a:
            partes.append(f"{self.so_a:n} só à esquerda")
        if self.so_b:
            partes.append(f"{self.so_b:n} só à direita")
        return f"{self.diferencas:n} diferença(s): " + ", ".join(partes)


@dataclass
class Comparacao:
    """O resultado. Guarda BLOCOS, e resolve a linha exibida na hora."""

    opcodes: list[tuple[str, int, int, int, int]]
    resumo: Resumo
    total_a: int
    total_b: int
    #: Soma acumulada de linhas exibidas ate' o fim de cada bloco. E' o que
    #: permite achar o bloco da linha N por busca binaria.
    _acumulado: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        soma = 0
        self._acumulado = []
        for tag, i1, i2, j1, j2 in self.opcodes:
            soma += _altura(tag, i1, i2, j1, j2)
            self._acumulado.append(soma)

    @property
    def total_exibido(self) -> int:
        return self._acumulado[-1] if self._acumulado else 0

    def par(self, linha: int) -> Par | None:
        """O par da linha exibida `linha`, resolvido sem materializar nada."""
        if not 0 <= linha < self.total_exibido:
            return None
        indice = bisect.bisect_right(self._acumulado, linha)
        tag, i1, i2, j1, j2 = self.opcodes[indice]
        antes = self._acumulado[indice - 1] if indice else 0
        k = linha - antes

        if tag == "equal":
            return Par(IGUAL, i1 + k, j1 + k)
        if tag == "delete":
            return Par(SO_A, i1 + k, None)
        if tag == "insert":
            return Par(SO_B, None, j1 + k)
        # "replace": os dois lados lado a lado, e o mais curto ganha vazios.
        a = i1 + k if i1 + k < i2 else None
        b = j1 + k if j1 + k < j2 else None
        return Par(ALTERADA if a is not None and b is not None
                   else (SO_A if a is not None else SO_B), a, b)

    def faixa(self, inicio: int, quantas: int) -> list[Par]:
        return [p for p in (self.par(n) for n in range(inicio, inicio + quantas))
                if p is not None]

    def proxima_diferenca(self, depois_de: int) -> int | None:
        """Primeira linha exibida com diferenca depois de `depois_de`.

        Percorre os BLOCOS, e nao as linhas: num arquivo de um milhao de linhas
        com tres diferencas, sao tres passos.
        """
        antes = 0
        for indice, (tag, i1, i2, j1, j2) in enumerate(self.opcodes):
            fim = self._acumulado[indice]
            if tag != "equal" and fim > depois_de + 1:
                return max(antes, depois_de + 1)
            antes = fim
        return None

    def diferenca_anterior(self, antes_de: int) -> int | None:
        anterior = None
        inicio = 0
        for indice, (tag, i1, i2, j1, j2) in enumerate(self.opcodes):
            if tag != "equal" and inicio < antes_de:
                anterior = inicio
            inicio = self._acumulado[indice]
        return anterior


def _altura(tag: str, i1: int, i2: int, j1: int, j2: int) -> int:
    if tag == "equal":
        return i2 - i1
    if tag == "delete":
        return i2 - i1
    if tag == "insert":
        return j2 - j1
    return max(i2 - i1, j2 - j1)


def _hashes(documento, cancelar=None) -> array:
    """Um hash de 64 bits por linha, em 8 bytes cada.

    `array("q")` e nao lista: uma lista de inteiros do Python custa ~28 bytes
    por elemento mais o ponteiro. Para 500 mil linhas sao 4 MB contra 18 MB.
    """
    total = documento.total_de_linhas
    saida = array("q")
    lido = 0
    while lido < total:
        if cancelar is not None and cancelar():
            break
        for bruta in documento.faixa(lido, lido + BLOCO):
            # `hash()` de bytes e' siphash de 64 bits: rapido e com colisao
            # despresivel nesta escala. Ver o cabecalho.
            saida.append(hash(bruta))
        lido += BLOCO
    return saida


def _unicas_em_comum(a, b, ia: int, fa: int, ib: int, fb: int):
    """Pares (i, j) de linhas que aparecem UMA vez so' nos dois trechos.

    Uma linha unica dos dois lados so' pode corresponder a si mesma -- nao ha'
    ambiguidade a resolver. E' o que torna a ancoragem confiavel, e nao um
    palpite.
    """
    conta_a: dict[int, int] = {}
    onde_a: dict[int, int] = {}
    for i in range(ia, fa):
        h = a[i]
        conta_a[h] = conta_a.get(h, 0) + 1
        onde_a[h] = i

    conta_b: dict[int, int] = {}
    onde_b: dict[int, int] = {}
    for j in range(ib, fb):
        h = b[j]
        conta_b[h] = conta_b.get(h, 0) + 1
        onde_b[h] = j

    pares = [(onde_a[h], onde_b[h]) for h, quantas in conta_a.items()
             if quantas == 1 and conta_b.get(h) == 1]
    pares.sort()
    return pares


def _maior_subsequencia_crescente(pares):
    """A maior cadeia de ancoras que NAO se cruzam.

    Duas ancoras cruzadas descreveriam linhas trocadas de lugar, e um diff por
    blocos nao representa isso: e' preciso escolher uma cadeia coerente, e a
    maior e' a que deixa menos diferenca para relatar. Paciencia, O(n log n).
    """
    if not pares:
        return []
    caudas: list[int] = []        # menor j que termina uma cadeia de tamanho k
    indices: list[int] = []
    anterior = [-1] * len(pares)
    for k, (_, j) in enumerate(pares):
        pos = bisect.bisect_left(caudas, j)
        if pos == len(caudas):
            caudas.append(j)
            indices.append(k)
        else:
            caudas[pos] = j
            indices[pos] = k
        anterior[k] = indices[pos - 1] if pos else -1

    cadeia = []
    k = indices[-1]
    while k != -1:
        cadeia.append(pares[k])
        k = anterior[k]
    cadeia.reverse()
    return cadeia


def _blocos(a, b, ia: int, fa: int, ib: int, fb: int, saida: list) -> None:
    """Alinha [ia,fa) com [ib,fb) e acrescenta opcodes em `saida`."""
    # 1. As pontas iguais saem de graca, e cortam a maior parte do trabalho
    #    quando as diferencas estao no meio.
    while ia < fa and ib < fb and a[ia] == b[ib]:
        ia += 1
        ib += 1
        _somar(saida, "equal", ia - 1, ia, ib - 1, ib)
    fim_a, fim_b = fa, fb
    iguais_no_fim = 0
    while fim_a > ia and fim_b > ib and a[fim_a - 1] == b[fim_b - 1]:
        fim_a -= 1
        fim_b -= 1
        iguais_no_fim += 1

    _miolo(a, b, ia, fim_a, ib, fim_b, saida)

    if iguais_no_fim:
        _somar(saida, "equal", fim_a, fim_a + iguais_no_fim,
               fim_b, fim_b + iguais_no_fim)


def _miolo(a, b, ia: int, fa: int, ib: int, fb: int, saida: list) -> None:
    if ia >= fa and ib >= fb:
        return
    if ia >= fa:
        _somar(saida, "insert", ia, ia, ib, fb)
        return
    if ib >= fb:
        _somar(saida, "delete", ia, fa, ib, ib)
        return

    ancoras = _maior_subsequencia_crescente(
        _unicas_em_comum(a, b, ia, fa, ib, fb))

    if not ancoras:
        # Sem ancora: ou o trecho e' pequeno e o difflib da' conta, ou ele e'
        # grande e vira um bloco so'. Ver LIMITE_SEM_ANCORA.
        if max(fa - ia, fb - ib) > LIMITE_SEM_ANCORA:
            _somar(saida, "replace", ia, fa, ib, fb)
            return
        motor = difflib.SequenceMatcher(a=a[ia:fa], b=b[ib:fb],
                                        autojunk=False)
        for tag, x1, x2, y1, y2 in motor.get_opcodes():
            _somar(saida, tag, ia + x1, ia + x2, ib + y1, ib + y2)
        return

    # Com ancoras: o espaco ENTRE elas e' um problema menor, resolvido igual.
    anterior_a, anterior_b = ia, ib
    for i, j in ancoras:
        _miolo(a, b, anterior_a, i, anterior_b, j, saida)
        _somar(saida, "equal", i, i + 1, j, j + 1)
        anterior_a, anterior_b = i + 1, j + 1
    _miolo(a, b, anterior_a, fa, anterior_b, fb, saida)


def _somar(saida: list, tag: str, i1: int, i2: int, j1: int, j2: int) -> None:
    """Acrescenta um opcode, FUNDINDO com o anterior quando der.

    Sem a fusao, dois arquivos iguais de um milhao de linhas produziriam um
    milhao de blocos de uma linha -- e a busca binaria que resolve a linha
    exibida perderia todo o sentido.
    """
    if i1 == i2 and j1 == j2:
        return
    if saida:
        anterior = saida[-1]
        if (anterior[0] == tag and anterior[2] == i1 and anterior[4] == j1):
            saida[-1] = (tag, anterior[1], i2, anterior[3], j2)
            return
    saida.append((tag, i1, i2, j1, j2))


def comparar(documento_a, documento_b, *, teto: int = TETO_DE_LINHAS,
             cancelar=None) -> Comparacao:
    """Compara dois documentos. Levanta `GrandeDemais` acima do teto."""
    total_a = documento_a.total_de_linhas
    total_b = documento_b.total_de_linhas
    maior = max(total_a, total_b)
    if teto and maior > teto:
        raise GrandeDemais(
            f"O maior dos dois arquivos tem {maior:n} linhas, e o limite para "
            f"comparar é de {teto:n}. Comparar é quadrático no pior caso: "
            f"acima disso a janela ficaria parada por muito tempo.")

    a = _hashes(documento_a, cancelar)
    b = _hashes(documento_b, cancelar)

    # Ancoragem por linhas unicas, e o difflib so' dentro dos pedacos. Ver o
    # cabecalho: o difflib sozinho passa de dois minutos em 200 mil linhas com
    # 10% de mudanca.
    #
    # `autojunk=False` nas chamadas internas tambem nao e' detalhe: ligado, o
    # difflib descarta os elementos que aparecem em mais de 1% de uma sequencia
    # com mais de 200 itens -- e num CSV, onde linha repetida e' normal, isso
    # produz alinhamento sem sentido.
    opcodes: list[tuple[str, int, int, int, int]] = []
    _blocos(a, b, 0, len(a), 0, len(b), opcodes)
    if not opcodes:
        opcodes = [("equal", 0, 0, 0, 0)]

    resumo = Resumo()
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            resumo.iguais += i2 - i1
        elif tag == "delete":
            resumo.so_a += i2 - i1
        elif tag == "insert":
            resumo.so_b += j2 - j1
        else:
            comuns = min(i2 - i1, j2 - j1)
            resumo.alteradas += comuns
            resumo.so_a += (i2 - i1) - comuns
            resumo.so_b += (j2 - j1) - comuns

    log.info("comparados %d e %d linhas: %s (%d bloco(s))",
             total_a, total_b, resumo.descrever(), len(opcodes))
    return Comparacao(opcodes=opcodes, resumo=resumo,
                      total_a=total_a, total_b=total_b)
