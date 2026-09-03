"""A tabela de pecas: o documento como uma LISTA DE FAIXAS, e nao como texto.

    pecas = [ (ORIGINAL,   0, 4_812_003 bytes, 120_301 linhas),
              (ADICIONADO, 0,        27 bytes,       0 linhas),
              (ORIGINAL, 4_812_050, 8_400_112 bytes, 210_884 linhas) ]

O documento acima tem 13 MB e o que esta' na memoria sao 27 bytes -- o que o
usuario digitou. Todo o resto continua no disco, alcancado pelo mmap de
`original.py`.

E' a estrutura classica de editor de texto (piece table), e ela e' escolhida aqui
por tres propriedades, nesta ordem de importancia:

1. **A memoria acompanha as EDICOES, nao o arquivo.** Digitar num arquivo de
   1 GB custa o tamanho do que foi digitado.
2. **Desfazer sai de graca.** O texto original nunca e' destruido: desfazer e'
   voltar a apontar para ele. Nao ha' copia de estado a guardar.
3. **Gravar e' copiar bytes.** Uma peca ORIGINAL vai do arquivo velho para o novo
   sem nunca virar `str`. Ver `gravacao.py`.

O preco e' que "a posicao 4.000.000" nao e' um indice de lista: achar a peca que
a contem custa uma varredura. Por isso ha' um cursor guardado -- editar e' um
gesto sequencial, e comecar do zero a cada tecla tornaria o custo quadratico.
Esta licao foi paga em outro projeto: uma versao anterior desta ideia, por linha,
levava 32 s para 10 mil edicoes ate' ganhar cursor e compactacao local.

TUDO AQUI E' EM BYTES. Ver o cabecalho de `original.py` para o porque. Quem
converte coluna de tela para offset e' a interface, decodificando so' a linha em
que o cursor esta'.
"""

from __future__ import annotations

from dataclasses import dataclass

from tfedit.original import Original

ORIGINAL = "original"
ADICIONADO = "adicionado"


@dataclass(frozen=True, slots=True)
class Peca:
    """Uma faixa contigua de bytes, de uma das duas fontes.

    `linhas` e' quantas quebras existem DENTRO da faixa. Guardar isso na peca e'
    o que permite responder "em que linha esta' o offset X?" percorrendo as
    pecas -- que sao O(edicoes) -- em vez de varrer os bytes.
    """

    fonte: str
    inicio: int
    tamanho: int
    linhas: int


class ForaDaFaixa(IndexError):
    """Posicao pedida fora do documento."""


@dataclass(slots=True)
class Edicao:
    """Uma operacao, como DADOS -- o bastante para refazer e para desfazer.

    Guardar o que mudou, e nao um instantaneo da lista de pecas, e' o que mantem
    a pilha proporcional ao numero de edicoes. Um instantaneo por operacao ja'
    custou 800 MB num projeto irmao, com 10 mil edicoes -- o custo e' quadratico
    porque cada copia carrega as pecas que as edicoes anteriores criaram.

    `removido` e `inserido` guardam os DOIS lados. Uma substituicao precisa dos
    dois: desfazer tira o que entrou e devolve o que saiu. Uma versao anterior
    guardava o texto que entrou num dicionario indexado por `id()` do objeto --
    id de objeto e' reaproveitado pelo Python depois da coleta, e o dicionario
    era atributo de CLASSE, compartilhado entre todos os documentos abertos.
    """

    tipo: str                 # "inserir" | "remover" | "substituir"
    offset: int
    removido: bytes = b""     # o que saiu do documento
    inserido: bytes = b""     # o que entrou
    #: Edicoes de digitacao seguida sao FUNDIDAS numa so' (ver `_fundir`), para
    #: um Ctrl+Z desfazer a palavra e nao a letra.
    aberta: bool = False


class Documento:
    """O texto editavel. Nao importa Qt -- a interface fala com isto."""

    def __init__(self, original: Original) -> None:
        self.original = original
        self._adicionado = bytearray()
        self._pecas: list[Peca] = []
        self._tamanho = 0
        self._linhas = 0
        self._feitas: list[Edicao] = []
        self._desfeitas: list[Edicao] = []
        #: (indice da peca, offset em que ela comeca) da ultima busca. Ver o
        #: terceiro paragrafo do cabecalho.
        self._cursor: tuple[int, int] | None = None

        if original.tamanho:
            self._pecas.append(Peca(ORIGINAL, 0, original.tamanho,
                                    original.total_de_linhas - 1))
            self._tamanho = original.tamanho
            self._linhas = original.total_de_linhas - 1

    # ==================================================================
    # Medidas
    # ==================================================================

    @property
    def tamanho(self) -> int:
        """Bytes do documento inteiro."""
        return self._tamanho

    @property
    def total_de_linhas(self) -> int:
        """Linhas, contando a ultima mesmo sem quebra final.

        Um arquivo terminado em `\\n` tem uma ultima linha VAZIA -- e' a
        convencao de `split("\\n")`, e e' ela que faz `EOL.join(linhas)`
        reproduzir o arquivo exato sem nenhum caso especial na gravacao.
        """
        self._sincronizar_com_indexacao()
        return self._linhas + 1

    def _sincronizar_com_indexacao(self) -> None:
        """A primeira peca cresce em LINHAS enquanto o indice avanca.

        Enquanto a varredura nao terminou, `original.total_de_linhas` e' parcial.
        Se o documento ainda esta' intacto (uma peca so', o arquivo inteiro), ela
        e' atualizada para a contagem continuar crescendo na tela. Depois da
        primeira edicao a peca ja' foi partida e as contagens sao definitivas --
        e a essa altura a interface ja' esperou a indexacao terminar para deixar
        editar (ver `pode_editar`).
        """
        if (len(self._pecas) == 1 and self._pecas[0].fonte == ORIGINAL
                and self._pecas[0].inicio == 0
                and self._pecas[0].tamanho == self.original.tamanho):
            linhas = self.original.total_de_linhas - 1
            if linhas != self._linhas:
                self._pecas[0] = Peca(ORIGINAL, 0, self._pecas[0].tamanho,
                                      linhas)
                self._linhas = linhas

    @property
    def pode_editar(self) -> bool:
        """Editar exige o indice COMPLETO.

        Partir uma peca no meio precisa saber quantas linhas ficam de cada lado,
        e isso vem de `original.linhas_ate()`, que so' e' confiavel depois da
        varredura. Deixar editar antes daria contagens erradas que so'
        apareceriam muito depois, como linhas fora de lugar na rolagem.
        """
        return self.original.indexacao_completa

    # ==================================================================
    # Localizacao
    # ==================================================================

    def _localizar(self, offset: int) -> tuple[int, int]:
        """(indice da peca, offset em que ela comeca) para `offset`.

        Comeca do cursor guardado quando ele nao passa do alvo. Digitar avanca o
        offset de um em um: sem o atalho, cada tecla varreria a lista inteira.
        """
        if offset < 0 or offset > self._tamanho:
            raise ForaDaFaixa(f"offset {offset} fora de [0, {self._tamanho}]")

        indice, posicao = 0, 0
        if self._cursor is not None and self._cursor[1] <= offset:
            indice, posicao = self._cursor
            if indice > len(self._pecas):
                indice, posicao = 0, 0
        while indice < len(self._pecas):
            tamanho = self._pecas[indice].tamanho
            if posicao <= offset < posicao + tamanho:
                self._cursor = (indice, posicao)
                return indice, posicao
            posicao += tamanho
            indice += 1
        # Offset no fim exato do documento: pertence a "depois da ultima peca".
        self._cursor = (len(self._pecas), self._tamanho)
        return len(self._pecas), self._tamanho

    def _bytes_da_peca(self, peca: Peca, salto: int = 0,
                       quantos: int | None = None) -> bytes:
        inicio = peca.inicio + salto
        fim = inicio + (peca.tamanho - salto if quantos is None else quantos)
        if peca.fonte == ORIGINAL:
            return self.original.ler(inicio, fim)
        return bytes(self._adicionado[inicio:fim])

    def _linhas_da_peca(self, peca: Peca, salto: int, quantos: int) -> int:
        """Quebras dentro de um PEDACO de uma peca."""
        if quantos <= 0:
            return 0
        if peca.fonte == ORIGINAL:
            inicio = peca.inicio + salto
            return self.original.linhas_em(inicio, inicio + quantos)
        inicio = peca.inicio + salto
        return self._adicionado.count(b"\n", inicio, inicio + quantos)

    # ==================================================================
    # Leitura
    # ==================================================================

    def ler(self, inicio: int, fim: int) -> bytes:
        """Bytes de [inicio, fim), atravessando pecas."""
        inicio = max(0, inicio)
        fim = min(fim, self._tamanho)
        if fim <= inicio:
            return b""
        partes: list[bytes] = []
        indice, posicao = self._localizar(inicio)
        while indice < len(self._pecas) and posicao < fim:
            peca = self._pecas[indice]
            salto = max(0, inicio - posicao)
            quantos = min(peca.tamanho - salto, fim - max(posicao, inicio))
            if quantos > 0:
                partes.append(self._bytes_da_peca(peca, salto, quantos))
            posicao += peca.tamanho
            indice += 1
        return b"".join(partes)

    def offset_da_linha(self, n: int) -> int:
        """Offset em bytes onde a linha `n` (base zero) comeca."""
        self._sincronizar_com_indexacao()
        if n <= 0:
            return 0
        restantes = n
        posicao = 0
        for peca in self._pecas:
            if restantes <= peca.linhas:
                return posicao + self._offset_da_quebra(peca, restantes)
            restantes -= peca.linhas
            posicao += peca.tamanho
        return self._tamanho

    def _offset_da_quebra(self, peca: Peca, quantas: int) -> int:
        """Offset, DENTRO da peca, logo depois da `quantas`-esima quebra."""
        if quantas <= 0:
            return 0
        if peca.fonte == ORIGINAL:
            # Salta pelo indice do arquivo em vez de varrer byte a byte.
            antes = self.original.linhas_ate(peca.inicio)
            alvo = self.original.offset_da_linha(antes + quantas)
            return min(alvo - peca.inicio, peca.tamanho)
        posicao = peca.inicio
        limite = peca.inicio + peca.tamanho
        for _ in range(quantas):
            quebra = self._adicionado.find(b"\n", posicao, limite)
            if quebra < 0:
                return peca.tamanho
            posicao = quebra + 1
        return posicao - peca.inicio

    def linha(self, n: int) -> bytes:
        """Os bytes da linha `n`, SEM o terminador."""
        inicio = self.offset_da_linha(n)
        fim = self.offset_da_linha(n + 1)
        if fim <= inicio:
            bruto = self.ler(inicio, self._tamanho)
        else:
            bruto = self.ler(inicio, fim)
        if bruto.endswith(b"\n"):
            bruto = bruto[:-1]
        if bruto.endswith(b"\r"):
            bruto = bruto[:-1]
        return bruto

    def faixa(self, inicio: int, fim: int) -> list[bytes]:
        """Linhas [inicio, fim), numa leitura so'.

        Uma unica travessia de pecas para as ~40 linhas visiveis, e nao uma por
        linha -- e' o que a pintura da tela precisa.
        """
        inicio = max(0, inicio)
        fim = min(fim, self.total_de_linhas)
        if fim <= inicio:
            return []
        a = self.offset_da_linha(inicio)
        b = self.offset_da_linha(fim) if fim < self.total_de_linhas \
            else self._tamanho
        bruto = self.ler(a, b)
        linhas = bruto.split(b"\n")
        if fim < self.total_de_linhas and linhas and linhas[-1] == b"":
            linhas.pop()          # a quebra final pertence a' linha seguinte
        return [ln[:-1] if ln.endswith(b"\r") else ln for ln in linhas]

    def linha_do_offset(self, offset: int) -> int:
        """Em que linha (base zero) cai este offset."""
        offset = max(0, min(offset, self._tamanho))
        linha = 0
        posicao = 0
        for peca in self._pecas:
            if offset < posicao + peca.tamanho:
                return linha + self._linhas_da_peca(peca, 0, offset - posicao)
            linha += peca.linhas
            posicao += peca.tamanho
        return linha

    # ==================================================================
    # Edicao
    # ==================================================================

    @property
    def alterado(self) -> bool:
        return bool(self._feitas)

    @property
    def total_de_edicoes(self) -> int:
        return len(self._feitas)

    def _partir(self, offset: int) -> int:
        """Garante que uma peca COMECE em `offset`. Devolve o indice dela.

        E' a operacao elementar da tabela: inserir e remover sao definidos em
        termos de "parta aqui, parta ali, mexa no meio".
        """
        if offset >= self._tamanho:
            return len(self._pecas)
        indice, posicao = self._localizar(offset)
        salto = offset - posicao
        if salto == 0:
            return indice
        peca = self._pecas[indice]
        antes_de_linhas = self._linhas_da_peca(peca, 0, salto)
        self._pecas[indice:indice + 1] = [
            Peca(peca.fonte, peca.inicio, salto, antes_de_linhas),
            Peca(peca.fonte, peca.inicio + salto, peca.tamanho - salto,
                 peca.linhas - antes_de_linhas),
        ]
        self._cursor = None
        return indice + 1

    def _aplicar_insercao(self, offset: int, dados: bytes) -> None:
        if not dados:
            return
        # Caminho rapido da DIGITACAO SEGUIDA: quando o texto novo continua
        # exatamente onde o anterior parou, a peca cresce em vez de a lista
        # ganhar uma entrada por tecla. Sem isto, digitar um paragrafo criaria
        # centenas de pecas e a tabela ficaria lenta em minutos de uso.
        indice, posicao = self._localizar(offset)
        anterior = indice - 1
        if (offset == posicao and anterior >= 0
                and self._pecas[anterior].fonte == ADICIONADO
                and (self._pecas[anterior].inicio
                     + self._pecas[anterior].tamanho) == len(self._adicionado)):
            velha = self._pecas[anterior]
            self._adicionado.extend(dados)
            self._pecas[anterior] = Peca(
                ADICIONADO, velha.inicio, velha.tamanho + len(dados),
                velha.linhas + dados.count(b"\n"))
        else:
            corte = self._partir(offset)
            inicio = len(self._adicionado)
            self._adicionado.extend(dados)
            self._pecas.insert(corte, Peca(ADICIONADO, inicio, len(dados),
                                           dados.count(b"\n")))
        self._tamanho += len(dados)
        self._linhas += dados.count(b"\n")
        self._cursor = None

    def _aplicar_remocao(self, offset: int, quantos: int) -> bytes:
        if quantos <= 0:
            return b""
        quantos = min(quantos, self._tamanho - offset)
        removidos = self.ler(offset, offset + quantos)
        inicio = self._partir(offset)
        fim = self._partir(offset + quantos)
        del self._pecas[inicio:fim]
        self._tamanho -= quantos
        self._linhas -= removidos.count(b"\n")
        self._cursor = None
        return removidos

    def _registrar(self, edicao: Edicao) -> None:
        self._feitas.append(edicao)
        # Uma edicao nova invalida o que havia para refazer: manter a lista
        # produziria um "refazer" que costura dois futuros diferentes.
        self._desfeitas.clear()

    def _fundir(self, edicao: Edicao) -> bool:
        """Junta esta edicao a' anterior quando as duas sao a mesma digitacao.

        Sem isto, Ctrl+Z desfaria uma LETRA por vez -- ninguem quer isso. A
        regra e' a de qualquer editor: so' funde insercao que continua
        exatamente onde a anterior parou, e a quebra de linha fecha o grupo.
        """
        if not self._feitas:
            return False
        ultima = self._feitas[-1]
        if (not ultima.aberta or ultima.tipo != "inserir"
                or edicao.tipo != "inserir"):
            return False
        if ultima.offset + len(ultima.inserido) != edicao.offset:
            return False
        ultima.inserido += edicao.inserido
        if b"\n" in edicao.inserido:
            ultima.aberta = False
        return True

    def fechar_grupo(self) -> None:
        """Encerra a fusao: a proxima digitacao vira uma edicao nova.

        A interface chama isto quando o cursor se move, quando o foco sai e
        quando o documento e' gravado -- os tres momentos em que "isto ainda e'
        a mesma digitacao" deixa de ser verdade.
        """
        if self._feitas:
            self._feitas[-1].aberta = False

    def inserir(self, offset: int, texto: bytes) -> None:
        """Insere bytes em `offset`."""
        if not texto:
            return
        self._aplicar_insercao(offset, texto)
        nova = Edicao("inserir", offset, inserido=texto,
                      aberta=b"\n" not in texto)
        if not self._fundir(nova):
            self._registrar(nova)

    def remover(self, offset: int, quantos: int) -> bytes:
        """Remove `quantos` bytes a partir de `offset`. Devolve o que saiu."""
        removidos = self._aplicar_remocao(offset, quantos)
        if removidos:
            self._registrar(Edicao("remover", offset, removido=removidos))
        return removidos

    def substituir(self, offset: int, quantos: int, texto: bytes) -> None:
        """Troca uma faixa por outro texto, em UMA operacao de desfazer.

        E' o que digitar por cima de uma selecao faz. Registrar como duas
        operacoes (remover + inserir) faria um Ctrl+Z devolver o texto antigo E
        manter o novo -- um estado que nunca existiu no documento.
        """
        removidos = self._aplicar_remocao(offset, quantos)
        self._aplicar_insercao(offset, texto)
        self._registrar(Edicao("substituir", offset, removido=removidos,
                               inserido=texto))

    # ==================================================================
    # Desfazer / refazer
    # ==================================================================

    @property
    def pode_desfazer(self) -> bool:
        return bool(self._feitas)

    @property
    def pode_refazer(self) -> bool:
        return bool(self._desfeitas)

    def desfazer(self) -> int:
        """Desfaz a ultima edicao. Devolve o offset onde por o cursor."""
        if not self._feitas:
            return -1
        edicao = self._feitas.pop()
        if edicao.inserido:
            self._aplicar_remocao(edicao.offset, len(edicao.inserido))
        if edicao.removido:
            self._aplicar_insercao(edicao.offset, edicao.removido)
        self._desfeitas.append(edicao)
        return edicao.offset

    def refazer(self) -> int:
        """Refaz a ultima operacao desfeita. Devolve o offset do cursor."""
        if not self._desfeitas:
            return -1
        edicao = self._desfeitas.pop()
        if edicao.removido:
            self._aplicar_remocao(edicao.offset, len(edicao.removido))
        if edicao.inserido:
            self._aplicar_insercao(edicao.offset, edicao.inserido)
        self._feitas.append(edicao)
        return edicao.offset

    def confirmar_gravacao(self, original: Original) -> None:
        """O disco passou a ser o que a tela mostra. Recomeca do zero.

        Chamada DEPOIS de a `Original` nova estar aberta sobre o arquivo
        gravado. Sem isto as pecas continuariam apontando para offsets do
        arquivo ANTIGO, e a proxima gravacao montaria o documento a partir do
        lugar errado -- o defeito mais destrutivo que esta estrutura permite.
        """
        self.original = original
        self._adicionado = bytearray()
        self._pecas = ([Peca(ORIGINAL, 0, original.tamanho,
                             original.total_de_linhas - 1)]
                       if original.tamanho else [])
        self._tamanho = original.tamanho
        self._linhas = max(0, original.total_de_linhas - 1)
        self._feitas.clear()
        self._desfeitas.clear()
        self._cursor = None

    # ==================================================================
    # Para o gravador
    # ==================================================================

    def blocos(self):
        """Gera as pecas na ordem do documento, para `gravacao.py`."""
        return list(self._pecas)
