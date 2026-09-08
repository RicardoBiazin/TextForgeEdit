"""O arquivo do disco: mmap somente leitura, mais um indice esparso de linhas.

Esta e' a metade IMUTAVEL do editor. Ela nunca muda: toda edicao vive na tabela
de pecas (`pecas.py`), que aponta para faixas de bytes daqui. Manter o original
intocado e' o que permite abrir 1 GB instantaneamente, desfazer sem guardar
copias e gravar copiando bytes em vez de reconstruir texto.

DUAS DECISOES QUE DEFINEM O RESTO DO PROJETO:

**Trabalhamos em BYTES, nao em caracteres.** Saber que a posicao 4.000.000 e' o
caractere 3.812.577 exigiria decodificar tudo o que vem antes -- ou seja,
carregar o arquivo, que e' exatamente o que este editor existe para evitar. Toda
posicao interna e' um offset em bytes; a decodificacao acontece LINHA A LINHA, no
momento de desenhar, e uma linha e' curta. A interface converte coluna para
offset decodificando so' a linha em que o cursor esta'.

**O indice e' ESPARSO e INCREMENTAL.** Guardar o offset de cada linha de um
arquivo de 13 milhoes de linhas custaria ~100 MB so' de lista Python. Guardando
um a cada `PASSO`, sao ~13 mil entradas (~100 KB), e achar a linha n custa um
salto mais uma varredura de no maximo `PASSO` linhas -- imperceptivel. E a
varredura e' incremental para a abertura ser instantanea: quem chama avanca um
pedaco por vez e a interface ja' mostra o comeco do arquivo.

**O MAPEAMENTO E' SOLTO QUANDO OCIOSO, e isso e' um par com a ASSINATURA.**
Medido nesta maquina: enquanto o mmap existe, NENHUM outro programa consegue
regravar o arquivo no Windows -- nem truncar (`open("wb")` da' "Invalid
argument") nem substituir por renomeacao (`os.replace` da' "Acesso negado").
Isso protege o documento, e ao mesmo tempo IMPEDE um rotacionador de log ou um
`git checkout` de tocar num arquivo que esta' so' aberto para leitura.

Soltar o mapeamento devolve o arquivo ao resto do sistema -- e reintroduz o
risco que a trava evitava: se ele mudar enquanto estamos desmapeados, os offsets
das pecas ORIGINAIS passam a apontar para outro conteudo, e gravar produziria uma
mistura. Por isso a assinatura (tamanho, data e um hash das pontas) e' tirada na
abertura e CONFERIDA em toda remapeamento e antes de gravar. As duas coisas nao
se separam: soltar sem conferir seria trocar uma limitacao por corrupcao.
"""

from __future__ import annotations

import hashlib
import mmap
import os
import pathlib
import time
from dataclasses import dataclass
from typing import Callable

#: Uma entrada de indice a cada N linhas. Ver a segunda decisao no cabecalho.
PASSO = 1024

#: Quanto se varre do mmap por vez ao indexar. Grande o bastante para o custo por
#: byte ser o do memchr, pequeno o bastante para o cancelamento responder rapido.
BLOCO = 4 * 1024 * 1024

QUEBRA = 0x0A          # \n

#: Quanto se le' de CADA PONTA para a assinatura. 1 MB de cada lado custa
#: milissegundos num SSD e pega toda reescrita real: um log ganha linhas no fim,
#: um export e' regerado do zero e o cabecalho muda.
AMOSTRA = 1024 * 1024

#: Segundos sem leitura ate' soltar o mapeamento. Ver o cabecalho.
OCIOSO_PADRAO = 20.0


class ArquivoMudou(OSError):
    """O arquivo no disco deixou de ser o que foi aberto."""


@dataclass(frozen=True)
class Assinatura:
    """Como o arquivo estava num instante.

    O hash e' das PONTAS, e nao do arquivo inteiro: ler 1 GB para conferir se
    ele mudou custaria mais que a propria gravacao. Nao e' garantia
    criptografica -- e nao precisa ser. O que se quer e' nao sobrescrever
    alteracao alheia em silencio, e uma mudanca que preserve tamanho, data E as
    duas pontas e' um caso que nenhuma heuristica barata pega.
    """

    tamanho: int = -1
    mtime_ns: int = 0
    pontas: str = ""

    @classmethod
    def de_caminho(cls, caminho: pathlib.Path) -> "Assinatura":
        try:
            info = caminho.stat()
        except OSError:
            return cls()
        resumo = hashlib.sha256()
        resumo.update(str(info.st_size).encode())
        try:
            with open(caminho, "rb") as f:
                resumo.update(f.read(AMOSTRA))
                if info.st_size > AMOSTRA * 2:
                    f.seek(info.st_size - AMOSTRA)
                    resumo.update(f.read(AMOSTRA))
        except OSError:
            return cls(tamanho=info.st_size, mtime_ns=info.st_mtime_ns)
        return cls(info.st_size, info.st_mtime_ns, resumo.hexdigest())

    def combina_com(self, outra: "Assinatura") -> bool:
        if self.tamanho != outra.tamanho:
            return False
        if self.pontas and outra.pontas:
            return self.pontas == outra.pontas
        return self.mtime_ns == outra.mtime_ns


class Original:
    """O arquivo mapeado em memoria, com o indice de inicios de linha.

    Sobre DUAS THREADS: a varredura pode rodar numa thread de disco enquanto a
    interface le'. E' seguro pelo mesmo motivo que no TextForge -- `_marcadores`
    so' CRESCE por `append`, e `_quebras`/`_varrido` sao inteiros cuja leitura
    defasada custa, no maximo, uma linha a menos na barra de rolagem por um
    instante. O que NAO e' seguro e' fechar o mmap com alguem lendo dele; por
    isso `fechar()` e' chamado pelo dono do ciclo de vida, nunca pelo worker.
    """

    def __init__(self, caminho: str | os.PathLike[str]) -> None:
        self.caminho = pathlib.Path(caminho)
        self._arquivo = open(self.caminho, "rb")
        self.tamanho = os.fstat(self._arquivo.fileno()).st_size
        # mmap de tamanho zero levanta ValueError no Windows.
        self._mapa: mmap.mmap | None = None
        if self.tamanho:
            self._mapa = mmap.mmap(self._arquivo.fileno(), 0,
                                   access=mmap.ACCESS_READ)

        #: marcadores[k] = offset onde comeca a linha k * PASSO.
        self._marcadores: list[int] = [0]
        self._quebras = 0        # quantos \n ja' foram contados
        self._varrido = 0        # ate' que offset o indice esta' construido
        self._fechado = False

        self.assinatura = Assinatura.de_caminho(self.caminho)
        self.ocioso_apos = OCIOSO_PADRAO
        self._ultimo_uso = time.monotonic()
        self._solto = False       # desmapeado por ociosidade, mas ainda vivo

    # ==================================================================
    # Ciclo de vida
    # ==================================================================

    def fechar(self) -> None:
        """Solta o mmap. Idempotente.

        OBRIGATORIO antes de trocar o arquivo no disco: no Windows um mmap vivo
        SEGURA o arquivo, e `os.replace`/`ReplaceFileW` falham com acesso negado.
        """
        if self._fechado:
            return
        self._fechado = True
        if self._mapa is not None:
            self._mapa.close()
            self._mapa = None
        if not self._solto:
            self._arquivo.close()

    def __enter__(self) -> "Original":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.fechar()

    # ==================================================================
    # Leitura crua
    # ==================================================================

    # -- soltar e retomar o mapeamento --------------------------------------

    @property
    def solto(self) -> bool:
        """O arquivo esta' desmapeado (e livre para outros programas)?"""
        return self._solto

    def soltar_se_ocioso(self, agora: float | None = None) -> bool:
        """Desmapeia se ninguem leu nos ultimos `ocioso_apos` segundos.

        Devolve True se soltou agora. Chamado por um temporizador da interface;
        o proximo acesso remapeia sozinho.
        """
        if (self._fechado or self._solto or self._mapa is None
                or self.ocioso_apos <= 0):
            return False
        agora = time.monotonic() if agora is None else agora
        if agora - self._ultimo_uso < self.ocioso_apos:
            return False
        self._mapa.close()
        self._mapa = None
        self._arquivo.close()
        self._solto = True
        return True

    def retomar(self) -> None:
        """Remapeia, conferindo que o arquivo continua o mesmo.

        Levanta `ArquivoMudou` quando nao continua. Remapear em silencio seria
        pior que falhar: os offsets das pecas passariam a apontar para outro
        conteudo, e a proxima gravacao misturaria os dois arquivos.
        """
        if self._fechado or not self._solto:
            return
        agora = Assinatura.de_caminho(self.caminho)
        if not self.assinatura.combina_com(agora):
            raise ArquivoMudou(
                f"{self.caminho.name} foi alterado por outro programa "
                f"enquanto estava aberto")
        self._arquivo = open(self.caminho, "rb")
        self.tamanho = os.fstat(self._arquivo.fileno()).st_size
        self._mapa = (mmap.mmap(self._arquivo.fileno(), 0,
                                access=mmap.ACCESS_READ)
                      if self.tamanho else None)
        self._solto = False

    def conferir_no_disco(self) -> None:
        """Levanta `ArquivoMudou` se o arquivo nao for mais o que abrimos.

        Chamada ANTES de gravar. Com o mapeamento vivo a resposta e' sempre
        "nao mudou" -- o Windows nao deixa outro programa regravar -- mas depois
        de uma soltada por ociosidade a janela existe, e e' justamente ai' que
        conferir importa.
        """
        agora = Assinatura.de_caminho(self.caminho)
        if not self.assinatura.combina_com(agora):
            raise ArquivoMudou(
                f"{self.caminho.name} foi alterado por outro programa "
                f"enquanto estava aberto")

    def _usar(self) -> None:
        """Marca uso e remapeia se preciso. Todo acesso passa por aqui."""
        self._ultimo_uso = time.monotonic()
        if self._solto:
            self.retomar()

    # -- leitura crua -------------------------------------------------------

    def ler(self, inicio: int, fim: int) -> bytes:
        """Bytes de [inicio, fim). Recortado nos limites."""
        self._usar()
        if self._mapa is None:
            return b""
        inicio = max(0, min(inicio, self.tamanho))
        fim = max(inicio, min(fim, self.tamanho))
        return self._mapa[inicio:fim]

    def achar(self, alvo: bytes, inicio: int, fim: int) -> int:
        """`mmap.find`, recortado. -1 quando nao ha'."""
        self._usar()
        if self._mapa is None:
            return -1
        return self._mapa.find(alvo, max(0, inicio), min(fim, self.tamanho))

    # ==================================================================
    # Indexacao
    # ==================================================================

    @property
    def indexacao_completa(self) -> bool:
        return self._varrido >= self.tamanho

    @property
    def progresso(self) -> tuple[int, int]:
        return self._varrido, self.tamanho

    @property
    def total_de_linhas(self) -> int:
        """Linhas CONHECIDAS ate' agora -- cresce durante a varredura.

        E' esse crescimento que faz a barra de rolagem se ajustar sozinha em vez
        de o usuario esperar por um arquivo de 1 GB antes de ver a primeira
        linha.
        """
        return self._quebras + 1

    def indexar(self, orcamento: int | None = None,
                cancelar: Callable[[], bool] | None = None) -> bool:
        """Avanca o indice. True quando o arquivo inteiro foi varrido."""
        self._usar()
        if self._mapa is None or self.indexacao_completa:
            self._varrido = self.tamanho
            return True

        restante = self.tamanho if orcamento is None else orcamento
        while restante > 0 and self._varrido < self.tamanho:
            if cancelar is not None and cancelar():
                return False
            fim = min(self._varrido + min(BLOCO, restante), self.tamanho)
            posicao = self._varrido
            while True:
                quebra = self._mapa.find(b"\n", posicao, fim)
                if quebra < 0:
                    break
                self._quebras += 1
                # A linha que COMECA depois desta quebra e' a de numero
                # `_quebras`. Guarda-se o marcador quando ela e' multipla do
                # passo.
                if self._quebras % PASSO == 0:
                    self._marcadores.append(quebra + 1)
                posicao = quebra + 1
            restante -= fim - self._varrido
            self._varrido = fim
        return self.indexacao_completa

    # ==================================================================
    # Linhas
    # ==================================================================

    def offset_da_linha(self, n: int) -> int:
        """Offset onde a linha `n` (base zero) comeca. `tamanho` se ela nao existe."""
        self._usar()
        if self._mapa is None or n <= 0:
            return 0
        marcador = min(n // PASSO, len(self._marcadores) - 1)
        posicao = self._marcadores[marcador]
        faltam = n - marcador * PASSO
        while faltam > 0:
            quebra = self._mapa.find(b"\n", posicao, self.tamanho)
            if quebra < 0:
                return self.tamanho
            posicao = quebra + 1
            faltam -= 1
        return posicao

    def linhas_ate(self, offset: int) -> int:
        """Quantas quebras de linha existem em [0, offset).

        E' o que permite a tabela de pecas saber quantas linhas ha' dentro de um
        pedaco do arquivo sem varre-lo: `linhas_em(a, b)` e' a diferenca entre
        duas chamadas destas, e cada uma custa um salto no indice mais no maximo
        `PASSO` linhas de varredura.
        """
        self._usar()
        if self._mapa is None or offset <= 0:
            return 0
        offset = min(offset, self.tamanho)
        # Maior marcador cujo offset nao passa de `offset`. Busca binaria, e nao
        # varredura: a lista tem milhares de entradas num arquivo grande.
        baixo, alto = 0, len(self._marcadores) - 1
        while baixo < alto:
            meio = (baixo + alto + 1) // 2
            if self._marcadores[meio] <= offset:
                baixo = meio
            else:
                alto = meio - 1
        contagem = baixo * PASSO
        posicao = self._marcadores[baixo]
        while True:
            quebra = self._mapa.find(b"\n", posicao, offset)
            if quebra < 0:
                return contagem
            contagem += 1
            posicao = quebra + 1

    def linhas_em(self, inicio: int, fim: int) -> int:
        """Quebras de linha dentro de [inicio, fim)."""
        if fim <= inicio:
            return 0
        return self.linhas_ate(fim) - self.linhas_ate(inicio)
