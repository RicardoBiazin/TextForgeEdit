"""Procurar no documento inteiro -- e nao so' na fatia que esta' na tela.

A janela viva segura ~5 mil linhas; o arquivo tem milhoes. Uma busca que olhasse
so' o `QPlainTextEdit` acharia apenas o que ja' esta' visivel, o que e' pior que
nao ter busca: daria a impressao de que o resto do arquivo nao tem a palavra.

Entao a busca varre a TABELA DE PECAS, em lotes de linhas, e enxerga tanto o que
esta' no disco quanto o que foi digitado e ainda nao gravado.

DUAS ESCOLHAS QUE VALEM SER ENTENDIDAS:

**Varre por LINHA, decodificando.** Procurar direto nos bytes seria mais rapido,
mas "diferenciar maiusculas" desligado nao funciona em bytes fora do ASCII --
`Ç` e `ç` sao pares diferentes em cada codificacao. Decodificar linha a linha
custa mais e acerta acento, que num editor em portugues nao e' detalhe.

**"Proxima ocorrencia" para na PRIMEIRA.** E' o caso comum, e ele nao paga o
preco de varrer o arquivo inteiro: F3 num arquivo de 1 GB responde no tempo de
achar a proxima linha, nao no de ler 1 GB. So' "substituir todas" percorre tudo,
e ela avisa antes.

O offset de uma ocorrencia e' devolvido em CARACTERES dentro da linha, e nao em
bytes: e' o que a interface usa para posicionar o cursor, e a linha ja' esta'
decodificada de qualquer forma.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterator

#: Quantas linhas sao lidas por vez. Uma travessia de pecas por lote, e nao uma
#: por linha -- o mesmo motivo de `Documento.faixa` existir.
LOTE = 4096


@dataclass(frozen=True)
class Criterio:
    """O que procurar, e como."""

    texto: str
    diferenciar_maiusculas: bool = False
    palavra_inteira: bool = False
    expressao_regular: bool = False

    def compilar(self) -> re.Pattern[str] | None:
        """O padrao pronto, ou None quando o criterio nao da' para compilar."""
        if not self.texto:
            return None
        alvo = self.texto if self.expressao_regular else re.escape(self.texto)
        if self.palavra_inteira:
            # `\b` em volta do padrao INTEIRO, e nao de cada parte: com regex do
            # usuario, embrulhar sem o grupo mudaria o significado da alternancia
            # (`a|b` viraria `\ba|b\b`).
            alvo = rf"\b(?:{alvo})\b"
        marcas = 0 if self.diferenciar_maiusculas else re.IGNORECASE
        try:
            return re.compile(alvo, marcas)
        except re.error:
            return None


@dataclass(frozen=True)
class Achado:
    """Uma ocorrencia. `inicio`/`fim` sao em CARACTERES, dentro da linha."""

    linha: int
    inicio: int
    fim: int
    texto: str          # a linha inteira, ja' decodificada


def _linhas(documento, codec: str, primeira: int, quantas: int) -> list[str]:
    return [bruto.decode(codec, errors="replace")
            for bruto in documento.faixa(primeira, primeira + quantas)]


def procurar(documento, criterio: Criterio, codec: str, *,
             de_linha: int = 0, cancelar: Callable[[], bool] | None = None
             ) -> Iterator[Achado]:
    """Gera as ocorrencias a partir de `de_linha`, para a frente."""
    padrao = criterio.compilar()
    if padrao is None:
        return
    total = documento.total_de_linhas
    n = max(0, de_linha)
    while n < total:
        if cancelar is not None and cancelar():
            return
        linhas = _linhas(documento, codec, n, min(LOTE, total - n))
        if not linhas:
            return
        for deslocamento, texto in enumerate(linhas):
            for achado in padrao.finditer(texto):
                yield Achado(n + deslocamento, achado.start(), achado.end(),
                             texto)
        n += len(linhas)


def proxima(documento, criterio: Criterio, codec: str, linha: int,
            coluna: int, *, para_tras: bool = False,
            cancelar: Callable[[], bool] | None = None) -> Achado | None:
    """A ocorrencia seguinte (ou anterior) a partir do cursor. Da' a volta.

    Dar a volta e' o comportamento de todo editor, e e' o que evita o usuario
    concluir que a palavra nao existe so' porque ele estava depois dela.
    """
    padrao = criterio.compilar()
    if padrao is None:
        return None
    total = documento.total_de_linhas
    if total <= 0:
        return None

    if para_tras:
        achado = _para_tras(documento, padrao, codec, linha, coluna, 0, cancelar)
        if achado is not None:
            return achado
        # Deu a volta: procura do fim ate' a linha do cursor.
        return _para_tras(documento, padrao, codec, total - 1, None, linha,
                          cancelar)

    achado = _para_frente(documento, padrao, codec, linha, coluna, total,
                          cancelar)
    if achado is not None:
        return achado
    return _para_frente(documento, padrao, codec, 0, None,
                        min(linha + 1, total), cancelar)


def _para_frente(documento, padrao, codec: str, de_linha: int,
                 de_coluna: int | None, ate_linha: int, cancelar) -> Achado | None:
    n = max(0, de_linha)
    primeira = True
    while n < ate_linha:
        if cancelar is not None and cancelar():
            return None
        quantas = min(LOTE, ate_linha - n)
        for deslocamento, texto in enumerate(_linhas(documento, codec, n,
                                                     quantas)):
            for achado in padrao.finditer(texto):
                # Na PRIMEIRA linha, so' vale o que vem depois do cursor --
                # senao F3 acharia de novo a ocorrencia em que ele ja' esta'.
                if (primeira and deslocamento == 0 and de_coluna is not None
                        and achado.start() < de_coluna):
                    continue
                return Achado(n + deslocamento, achado.start(), achado.end(),
                              texto)
        primeira = False
        n += quantas
    return None


def _para_tras(documento, padrao, codec: str, de_linha: int,
               de_coluna: int | None, ate_linha: int, cancelar) -> Achado | None:
    n = min(de_linha, documento.total_de_linhas - 1)
    primeira = True
    while n >= ate_linha:
        if cancelar is not None and cancelar():
            return None
        inicio = max(ate_linha, n - LOTE + 1)
        linhas = _linhas(documento, codec, inicio, n - inicio + 1)
        for deslocamento in range(len(linhas) - 1, -1, -1):
            texto = linhas[deslocamento]
            achados = list(padrao.finditer(texto))
            for achado in reversed(achados):
                if (primeira and inicio + deslocamento == de_linha
                        and de_coluna is not None
                        and achado.start() >= de_coluna):
                    continue
                return Achado(inicio + deslocamento, achado.start(),
                              achado.end(), texto)
        primeira = False
        n = inicio - 1
    return None


def contar(documento, criterio: Criterio, codec: str, *, teto: int = 100_000,
           cancelar: Callable[[], bool] | None = None) -> tuple[int, bool]:
    """(quantas ocorrencias, se parou no teto).

    O teto existe porque contar num arquivo de 1 GB e' varre-lo inteiro. Dizer
    "mais de 100.000" e' honesto e instantaneo comparado a travar a interface.
    """
    quantas = 0
    for _ in procurar(documento, criterio, codec, cancelar=cancelar):
        quantas += 1
        if quantas >= teto:
            return quantas, True
    return quantas, False


def substituir_todas(documento, criterio: Criterio, codec: str,
                     substituto: str, *, teto: int = 100_000,
                     cancelar: Callable[[], bool] | None = None) -> int:
    """Troca todas as ocorrencias. Devolve quantas.

    Aplica de TRAS PARA A FRENTE. Substituindo do comeco, cada troca desloca os
    offsets de tudo o que vem depois, e a segunda substituicao ja' cairia no
    lugar errado. De tras para a frente, o que ainda falta trocar nao se mexeu.
    """
    padrao = criterio.compilar()
    if padrao is None:
        return 0

    # Junta tudo antes de aplicar: a lista de ocorrencias e' pequena perto do
    # arquivo, e aplicar durante a varredura mudaria o documento sob os pes de
    # quem esta' lendo.
    achados = []
    for achado in procurar(documento, criterio, codec, cancelar=cancelar):
        achados.append(achado)
        if len(achados) >= teto:
            break
    if not achados:
        return 0

    for achado in reversed(achados):
        if cancelar is not None and cancelar():
            break
        base = documento.offset_da_linha(achado.linha)
        prefixo = achado.texto[:achado.inicio].encode(codec, errors="replace")
        alvo = achado.texto[achado.inicio:achado.fim].encode(codec,
                                                             errors="replace")
        novo = padrao.sub(substituto, achado.texto[achado.inicio:achado.fim],
                          count=1).encode(codec, errors="replace")
        documento.substituir(base + len(prefixo), len(alvo), novo)
    return len(achados)
