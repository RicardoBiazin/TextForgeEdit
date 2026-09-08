"""Trocar a codificacao de um arquivo grande, sem te-lo inteiro na memoria.

DUAS OPERACOES DIFERENTES, e confundi-las e' o defeito classico daqui:

    REINTERPRETAR  "eu li errado"      -> nenhum byte do disco muda
    CONVERTER      "quero outro forma" -> TODO byte do arquivo e' reescrito

No projeto irmao o usuario relatou exatamente isso -- "a conversao nao esta'
funcionando, ele continua na mesma" -- porque as duas coisas apareciam como um
comando so'. Aqui elas sao dois menus com dois verbos.

POR QUE CONVERTER E' CARO NESTE EDITOR

A gravacao normal (`gravacao.py`) copia cada peca ORIGINAL do mmap para o
arquivo novo COMO BYTES: nao decodifica, nao recodifica. E' o que faz gravar
240 MB com tres paragrafos alterados custar 240 MB de disco e alguns MB de RAM.

Converter destroi essa invariante por definicao: `Ã¡` em ISO-8859-1 e' um byte,
em UTF-8 sao dois. Nao existe conversao que preserve os bytes intactos -- o
arquivo inteiro passa por decodificar e recodificar. Continua sendo O(1) em
MEMORIA, por streaming, mas e' O(n) em TRABALHO, e num arquivo de 1 GB isso se
sente. Por isso a conversao avisa antes e mostra progresso.

O QUE NAO SE FAZ EM SILENCIO

`errors="replace"` seria facil e seria perda de dados. Um `中` convertido para
ISO-8859-1 vira `?`, e o `?` nao volta. Um byte 0x81 num arquivo dito
Windows-1252 nao e' caractere nenhum. Nos dois casos a conversao PARA, o
temporario e' descartado e o arquivo do usuario continua intacto -- com uma
mensagem que diz o caractere e a linha, para a pessoa poder decidir.

O CORTE NO MEIO DE UM CARACTERE

Os blocos tem 4 MB e nao respeitam fronteira de caractere: um `ç` em UTF-8 pode
ter o primeiro byte no fim de um bloco e o segundo no comeco do proximo.
Decodificar bloco a bloco com `bytes.decode` produziria lixo em cada fronteira
-- um defeito que so' aparece em arquivo grande, e sempre a cada 4 MB. Dai' os
codecs INCREMENTAIS: eles guardam a sobra entre chamadas.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Iterator

from tfedit import gravacao, log_interno
from tfedit.pecas import Documento

log = log_interno.obter(__name__)


@dataclass(frozen=True)
class Alvo:
    """Uma codificacao de destino, como ela aparece no menu."""

    rotulo: str
    codec: str
    bom: bytes = b""
    #: Quanto o arquivo pode CRESCER, no pior caso, indo para este formato.
    #: Serve so' para conferir espaco em disco antes de comecar; errar para
    #: mais custa um aviso desnecessario, errar para menos custa um disco cheio
    #: no meio da escrita.
    fator: int = 2

    @property
    def chave(self) -> tuple[str, bytes]:
        return (self.codec, self.bom)


#: A ordem e' a do menu. UTF-8 primeiro porque e' o destino de quase toda
#: conversao real; os UTF-16/32 vao no fim porque quase ninguem quer.
ALVOS: tuple[Alvo, ...] = (
    Alvo("UTF-8", "utf-8", b"", 2),
    Alvo("UTF-8 com BOM", "utf-8", codecs.BOM_UTF8, 2),
    Alvo("Windows-1252", "cp1252", b"", 1),
    Alvo("ISO-8859-1 (Latin-1)", "iso-8859-1", b"", 1),
    Alvo("UTF-16 LE", "utf-16-le", codecs.BOM_UTF16_LE, 4),
    Alvo("UTF-16 BE", "utf-16-be", codecs.BOM_UTF16_BE, 4),
)


class NaoRepresentavel(ValueError):
    """O texto tem caractere que a codificacao de destino nao escreve."""

    def __init__(self, caractere: str, linha: int, rotulo: str) -> None:
        self.caractere = caractere
        self.linha = linha
        self.rotulo = rotulo
        super().__init__(
            f"O caractere {caractere!r} (linha {linha:n}) não existe em "
            f"{rotulo}. Converter assim trocaria esse caractere por "
            f"\"?\" — e não haveria como recuperá-lo depois.")


class OrigemInvalida(ValueError):
    """Os bytes do arquivo nao formam texto na codificacao de origem."""

    def __init__(self, detalhe: str, linha: int, rotulo: str) -> None:
        self.linha = linha
        self.rotulo = rotulo
        super().__init__(
            f"O arquivo tem bytes que não são texto em {rotulo} "
            f"(perto da linha {linha:n}): {detalhe}. Reinterprete o arquivo "
            f"na codificação certa antes de converter.")


def _resumo(erro: UnicodeDecodeError) -> str:
    """O byte problematico, em hexadecimal. `str(erro)` traz offset de BLOCO.

    O offset que o Python poe na mensagem e' relativo ao pedaco que foi passado
    ao codec, e nao ao arquivo -- mostra-lo ao usuario seria pior que nao
    mostrar nada.
    """
    ruim = erro.object[erro.start:erro.end]
    return "byte " + " ".join(f"0x{b:02X}" for b in ruim[:4])


def blocos_convertidos(documento: Documento, codec_de: str, alvo: Alvo,
                       *, rotulo_de: str = "", cancelar=None
                       ) -> Iterator[bytes]:
    """Os bytes do arquivo, relidos em `codec_de` e reescritos em `alvo`.

    Passa por cima de `gravacao.blocos`, que ja' entrega o documento inteiro --
    peca ORIGINAL e texto digitado na mesma sequencia. Assim a conversao nao
    precisa saber que existe tabela de pecas.
    """
    decodificador = codecs.getincrementaldecoder(codec_de)(errors="strict")
    codificador = codecs.getincrementalencoder(alvo.codec)(errors="strict")

    if alvo.bom:
        yield alvo.bom

    linha = 1
    primeiro = True

    for bruto in gravacao.blocos(documento, cancelar):
        if not bruto:
            continue
        try:
            texto = decodificador.decode(bruto)
        except UnicodeDecodeError as erro:
            # `linha` ainda esta' no comeco DESTE bloco -- o bloco todo falhou,
            # e nada dele foi contado. As quebras que vierem antes do byte ruim
            # e' que dizem a linha de verdade; sem elas a mensagem apontaria
            # sempre para o inicio do bloco, o que num arquivo de 240 MB e' uma
            # informacao inutil.
            antes = erro.object[:erro.start]
            raise OrigemInvalida(_resumo(erro), linha + antes.count(b"\n"),
                                 rotulo_de or codec_de) from erro

        if primeiro and texto:
            # O BOM da ORIGEM vira U+FEFF ao decodificar e nao e' conteudo: se
            # ele passasse adiante, o arquivo convertido comecaria com um
            # espaco invisivel -- e com DOIS, quando o destino tambem tem BOM.
            if texto[0] == "﻿":
                texto = texto[1:]
            primeiro = False

        if not texto:
            continue
        try:
            saida = codificador.encode(texto)
        except UnicodeEncodeError as erro:
            raise NaoRepresentavel(erro.object[erro.start:erro.start + 1],
                                   linha + texto.count("\n", 0, erro.start),
                                   alvo.rotulo) from erro
        linha += texto.count("\n")
        if saida:
            yield saida

    # `final=True` fecha os dois lados. E' o que denuncia um caractere CORTADO
    # no fim do arquivo -- sem isto a sobra do decodificador seria descartada em
    # silencio, e o arquivo convertido sairia com um caractere a menos.
    try:
        resto = decodificador.decode(b"", final=True)
    except UnicodeDecodeError as erro:
        raise OrigemInvalida(f"o arquivo termina no meio de um caractere "
                             f"({erro})", linha, rotulo_de or codec_de) from erro
    try:
        final = codificador.encode(resto, final=True)
    except UnicodeEncodeError as erro:
        raise NaoRepresentavel(erro.object[erro.start:erro.start + 1],
                               linha, alvo.rotulo) from erro
    if final:
        yield final


def converter(caminho, documento: Documento, codec_de: str, alvo: Alvo, *,
              rotulo_de: str = "", antes_de_trocar=None, cancelar=None) -> int:
    """Reescreve o arquivo na codificacao `alvo`. Devolve os bytes gravados.

    Levanta `NaoRepresentavel` ou `OrigemInvalida` ANTES de trocar qualquer
    coisa: como toda gravacao daqui, a escrita e' num temporario ao lado, e uma
    falha no meio deixa o arquivo do usuario exatamente como estava.
    """
    def produtor(doc, cancela):
        return blocos_convertidos(doc, codec_de, alvo, rotulo_de=rotulo_de,
                                  cancelar=cancela)

    escritos = gravacao.gravar(
        caminho, documento, antes_de_trocar=antes_de_trocar, cancelar=cancelar,
        produtor=produtor, previsto=documento.tamanho * alvo.fator)
    log.info("convertido %s: %s -> %s (%d bytes)", caminho,
             rotulo_de or codec_de, alvo.rotulo, escritos)
    return escritos


def alvo_de(codec: str, bom: bytes = b"") -> Alvo | None:
    """O `Alvo` que corresponde a um par (codec, BOM), se houver."""
    for alvo in ALVOS:
        if alvo.chave == (codec, bom):
            return alvo
    return None
