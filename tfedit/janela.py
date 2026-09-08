"""A JANELA VIVA: um trecho do documento que mora num editor Qt de verdade.

O problema: um `QPlainTextEdit` com 1 GB consome varios GB e congela na
montagem do layout. A tabela de pecas resolve a memoria, mas nao da' cursor,
acentuacao nem selecao -- escrever isso a mao e' reimplementar um editor de texto,
e a acentuacao em pt-BR (tecla morta, `inputMethodEvent`) e' facil de errar e
grave quando erra.

A saida e' nao escolher: um editor Qt COMPLETO segurando apenas uma FATIA.

    arquivo de 1 GB
     |
     |-- linhas 0 .. 1.199.999          na tabela de pecas, no disco
     |-- linhas 1.200.000 .. 1.205.000  <- JANELA VIVA, num QTextDocument real
     |-- linhas 1.205.001 .. fim        na tabela de pecas, no disco

Rolar para fora da fatia faz a janela DESLIZAR: o que estava vivo volta para a
tabela de pecas e uma fatia nova e' carregada. A memoria fica limitada ao tamanho
da fatia, e dentro dela tudo o que o Qt sabe fazer funciona.

TRES COISAS QUE ESTE MODULO RESOLVE, E QUE NAO SAO OBVIAS:

1. **A escrita de volta e' MINIMA.** Devolver a fatia inteira criaria uma peca de
   ~250 KB por deslize; cem deslizes com edicao seriam 25 MB de texto na memoria
   para representar meia duzia de correcoes. Aqui o prefixo e o sufixo iguais sao
   descartados, e so' o miolo que mudou de fato entra na tabela.

2. **A fatia comeca e termina em fronteira de LINHA.** Cortar no meio de uma
   linha partiria um caractere multibyte e produziria U+FFFD ao decodificar.

3. **Fim de linha e codificacao voltam como estavam.** Dentro da janela o texto e'
   `str` com `\\n`, que e' o que o Qt usa. Na volta, o `\\n` e' reexpandido para o
   terminador do arquivo e o texto e' recodificado. As partes FORA da janela nunca
   sao tocadas -- continuam sendo os bytes originais.

Este modulo nao importa Qt de proposito: ele decide O QUE vai e volta, e o widget
so' mostra. E' o que permite testar a parte dificil sem tela.
"""

from __future__ import annotations

from dataclasses import dataclass

from tfedit import codificacao
from tfedit.pecas import Documento
from tfedit import log_interno


log = log_interno.obter(__name__)

#: Quantas linhas a janela segura. 5 mil linhas de 80 colunas sao ~400 KB -- um
#: QTextDocument desse tamanho monta em milissegundos, e cobre com folga o que
#: cabe em qualquer tela mais varias paginas de rolagem em cada sentido.
LINHAS_DA_JANELA = 5_000

#: Distancia da borda que dispara o deslize. Sem folga, rolar uma linha para fora
#: recarregaria a janela a cada tecla de seta na fronteira.
FOLGA = 500


@dataclass(frozen=True)
class Recorte:
    """Uma fatia carregada: onde ela comeca e o que ela contem.

    `bytes_originais` sao os bytes EXATOS que a fatia ocupa no documento, e nao
    uma recodificacao do `texto`. A diferenca importa: decodificar e recodificar
    NAO e' garantidamente ida e volta -- um byte invalido vira U+FFFD, e a
    normalizacao de fim de linha apaga a distincao entre CRLF e LF. Comparar
    contra uma recodificacao faria os offsets nao baterem com o arquivo, e a
    substituicao cairia no lugar errado.
    """

    primeira_linha: int
    quantas_linhas: int
    inicio_em_bytes: int
    fim_em_bytes: int
    texto: str
    bytes_originais: bytes = b""

    @property
    def ultima_linha(self) -> int:
        return self.primeira_linha + self.quantas_linhas


class JanelaViva:
    """Conduz a fatia: carrega, escreve de volta e desliza."""

    def __init__(self, documento: Documento, perfil: codificacao.Perfil,
                 linhas: int = LINHAS_DA_JANELA) -> None:
        self.documento = documento
        self.perfil = perfil
        self.linhas = max(1, linhas)
        self.recorte: Recorte | None = None

    # ==================================================================
    # Carregar
    # ==================================================================

    def carregar(self, ao_redor_da_linha: int = 0) -> Recorte:
        """Traz para a memoria a fatia centrada em `ao_redor_da_linha`."""
        total = self.documento.total_de_linhas
        metade = self.linhas // 2
        primeira = max(0, min(ao_redor_da_linha - metade,
                              max(0, total - self.linhas)))
        quantas = min(self.linhas, total - primeira)

        inicio = self.documento.offset_da_linha(primeira)
        fim = (self.documento.offset_da_linha(primeira + quantas)
               if primeira + quantas < total else self.documento.tamanho)
        bruto = self.documento.ler(inicio, fim)
        texto = codificacao.para_lf(self._decodificar(bruto))

        self.recorte = Recorte(primeira, quantas, inicio, fim, texto, bruto)
        return self.recorte

    #: Quantas linhas antes da fatia o realce olha para achar o contexto.
    #:
    #: Um teto, e nao o arquivo inteiro: varrer 500 mil linhas para descobrir a
    #: cor da primeira linha da fatia trocaria uma imprecisao visual por uma
    #: pausa a cada rolagem. Duzentas linhas resolvem o caso comum -- um
    #: comentario de bloco, uma string de varias linhas, um <script> -- e o que
    #: nao couber nelas fica com o contexto inicial da linguagem, que e'
    #: exatamente o comportamento de antes desta funcao existir.
    LINHAS_DE_CONTEXTO = 200

    def linhas_antes_da_fatia(self, quantas: int = LINHAS_DE_CONTEXTO
                              ) -> list[str]:
        """As linhas imediatamente anteriores a fatia, para semear o realce."""
        if self.recorte is None or self.recorte.primeira_linha <= 0:
            return []
        primeira = max(0, self.recorte.primeira_linha - quantas)
        if primeira >= self.recorte.primeira_linha:
            return []
        inicio = self.documento.offset_da_linha(primeira)
        bruto = self.documento.ler(inicio, self.recorte.inicio_em_bytes)
        texto = codificacao.para_lf(self._decodificar(bruto))
        # `split` e nao `splitlines`: um "\x0c" no meio de um log nao pode virar
        # quebra de linha aqui, ou a contagem sairia diferente da do indice.
        linhas = texto.split("\n")
        if linhas and linhas[-1] == "":
            linhas.pop()
        return linhas

    def _decodificar(self, bruto: bytes) -> str:
        # `errors="replace"` porque pintar a tela NUNCA pode levantar: um byte
        # invalido no meio de um log de 1 GB nao pode impedir de ver o resto. A
        # gravacao e' que e' protegida -- ver `perfil.suspeito`.
        return bruto.decode(self.perfil.codec, errors="replace")

    def _codificar(self, texto: str) -> bytes:
        """Texto da fatia de volta a bytes, com o fim de linha do ARQUIVO.

        Dentro da janela o texto tem so' quebras `\\n` -- e' o que o
        `QPlainTextEdit` usa, e nao ha' como pedir a ele que preserve CRLF. Na
        volta, elas sao reexpandidas para o terminador do perfil.

        DUAS CONSEQUENCIAS que precisam estar escritas:

        * O perfil TEM de vir da deteccao. Com `fim_de_linha` errado, o trecho
          reescrito sai com quebras que o arquivo nao tinha -- um teste que
          fabricava o perfil a mao fez exatamente isso, e foi assim que a
          armadilha apareceu.
        * Num arquivo de fim de linha MISTO, as quebras DENTRO do trecho
          alterado viram a dominante. As de fora sobrevivem, porque o corte de
          prefixo e sufixo em `aplicar` nunca chega ate' elas.
        """
        return codificacao.de_lf(texto, self.perfil.fim_de_linha).encode(
            self.perfil.codec, errors="replace")

    # ==================================================================
    # Escrever de volta
    # ==================================================================

    def aplicar(self, texto_atual: str) -> bool:
        """Devolve para a tabela de pecas o que mudou na fatia. False se nada.

        Descarta o prefixo e o sufixo IGUAIS antes de escrever. Sem isso, cada
        deslize com uma virgula corrigida injetaria a fatia inteira na tabela --
        centenas de KB para representar um byte.

        O lado ANTIGO da comparacao sao os bytes REAIS da fatia, e nao uma
        recodificacao do texto decodificado. Foi um teste com um arquivo cp1252
        que pegou a diferenca: recodificar reescreve o fim de linha pelo
        dominante do perfil, entao num arquivo LF com perfil CRLF os
        comprimentos deixam de bater e a substituicao cai no lugar errado. Pelo
        mesmo motivo, num arquivo de fim de linha MISTO as linhas que o usuario
        nao tocou ficam de fora do trecho reescrito -- o corte de prefixo e
        sufixo as protege.
        """
        if self.recorte is None:
            return False
        if texto_atual == self.recorte.texto:
            return False

        antigo = self.recorte.bytes_originais
        novo = self._codificar(texto_atual)

        comeco = _prefixo_comum(antigo, novo)
        fim_a, fim_n = _sufixo_comum(antigo, novo, comeco)

        offset = self.recorte.inicio_em_bytes + comeco
        quantos = fim_a - comeco
        entra = novo[comeco:fim_n]
        if not quantos and not entra:
            return False

        self.documento.substituir(offset, quantos, entra)
        # A fatia continua sendo a mesma faixa de LINHAS, mas os offsets em
        # bytes mudaram. Recarregar do documento mantem tudo coerente e custa
        # uma leitura da fatia -- barato perto de errar o offset seguinte.
        self.carregar(self.recorte.primeira_linha + self.recorte.quantas_linhas
                      // 2)
        return True

    # ==================================================================
    # Deslizar
    # ==================================================================

    def precisa_deslizar(self, linha: int) -> bool:
        """A linha pedida esta' perto demais da borda da fatia?"""
        if self.recorte is None:
            return True
        if linha < 0:
            return False
        no_inicio = self.recorte.primeira_linha
        no_fim = self.recorte.ultima_linha
        total = self.documento.total_de_linhas
        # Sem folga nas pontas do ARQUIVO: quando a fatia ja' encosta no comeco
        # ou no fim, nao ha' para onde deslizar, e insistir recarregaria a mesma
        # fatia a cada movimento do cursor.
        if linha < no_inicio + FOLGA and no_inicio > 0:
            return True
        if linha > no_fim - FOLGA and no_fim < total:
            return True
        return False

    def deslizar(self, texto_atual: str, para_a_linha: int) -> Recorte:
        """Aplica o que mudou e carrega a fatia em volta de `para_a_linha`."""
        self.aplicar(texto_atual)
        return self.carregar(para_a_linha)

    # ==================================================================
    # Traducao de posicao
    # ==================================================================

    def linha_no_documento(self, linha_na_fatia: int) -> int:
        base = self.recorte.primeira_linha if self.recorte else 0
        return base + max(0, linha_na_fatia)

    def linha_na_fatia(self, linha_no_documento: int) -> int:
        """-1 quando a linha esta' fora da fatia carregada."""
        if self.recorte is None:
            return -1
        relativa = linha_no_documento - self.recorte.primeira_linha
        if 0 <= relativa < self.recorte.quantas_linhas:
            return relativa
        return -1


def _prefixo_comum(a: bytes, b: bytes) -> int:
    """Quantos bytes iniciais os dois compartilham."""
    limite = min(len(a), len(b))
    i = 0
    while i < limite and a[i] == b[i]:
        i += 1
    return i


def _sufixo_comum(a: bytes, b: bytes, minimo: int) -> tuple[int, int]:
    """(fim em a, fim em b) recuando enquanto os bytes finais forem iguais.

    `minimo` impede o sufixo de invadir o prefixo ja' contado -- sem ele, dois
    textos como "aaaa" e "aa" reportariam faixas sobrepostas e a substituicao
    removeria bytes demais.
    """
    fim_a, fim_b = len(a), len(b)
    while fim_a > minimo and fim_b > minimo and a[fim_a - 1] == b[fim_b - 1]:
        fim_a -= 1
        fim_b -= 1
    return fim_a, fim_b
