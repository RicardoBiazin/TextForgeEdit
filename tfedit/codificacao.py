"""Descobrir a codificacao e o fim de linha SEM ler o arquivo inteiro.

Num editor de arquivo grande a deteccao tem de decidir a partir de uma
SONDAGEM -- os primeiros KB. E' o suficiente na pratica: um arquivo nao troca de
codificacao no meio, e o fim de linha dominante aparece nas primeiras linhas.

A cascata, e o motivo de cada degrau:

    1. BOM              e' declaracao explicita; nada mais precisa ser adivinhado
    2. UTF-16 sem BOM   ANTES do UTF-8 estrito, porque aqueles bytes SAO UTF-8
                        valido -- testar na ordem inversa classifica todo UTF-16
                        sem BOM como UTF-8 e o texto vira intercalado com \\x00
    3. UTF-8 estrito    sem `errors=replace`: ou decodifica inteiro, ou nao e'
    4. charset-normalizer  o palpite estatistico, so' com bytes nao-ASCII
                        suficientes -- com poucos ele devolve cp1250 para
                        portugues, e o acento sai errado
    5. cp1252           o padrao do Windows em pt-BR, e o ultimo recurso

Uma leitura que perde caracteres marca o perfil como SUSPEITO. Gravar por cima de
um arquivo que nao foi lido direito grava U+FFFD no lugar dos bytes originais --
destruicao de dados causada pelo proprio editor.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass

#: Quantos bytes bastam para decidir. 64 KB pegam varias linhas de qualquer
#: arquivo real e custam nada num arquivo de 1 GB.
SONDAGEM = 64 * 1024

#: Abaixo disto o charset-normalizer nao e' consultado: com pouca amostra ele
#: erra para o lado errado em portugues.
MINIMO_NAO_ASCII = 16

BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

LF = "\n"
CRLF = "\r\n"
CR = "\r"

ROTULO_EOL = {LF: "LF", CRLF: "CRLF", CR: "CR"}


@dataclass(frozen=True)
class Perfil:
    """O que a sondagem descobriu."""

    codec: str = "utf-8"
    bom: bytes = b""            # os bytes literais, para reescrever iguais
    fim_de_linha: str = CRLF
    misto: bool = False         # ha' mais de um tipo de quebra no arquivo
    suspeito: bool = False      # a decodificacao perdeu caracteres
    como_decidiu: str = ""

    @property
    def rotulo(self) -> str:
        if self.bom == codecs.BOM_UTF8:
            return "UTF-8 BOM"
        return {"utf-8": "UTF-8", "cp1252": "Windows-1252",
                "utf-16-le": "UTF-16 LE", "utf-16-be": "UTF-16 BE",
                "utf-32-le": "UTF-32 LE", "utf-32-be": "UTF-32 BE",
                "iso-8859-1": "ISO-8859-1"}.get(self.codec,
                                                self.codec.upper())

    @property
    def rotulo_eol(self) -> str:
        return ROTULO_EOL.get(self.fim_de_linha, "CRLF") + \
            (" (misto)" if self.misto else "")


def detectar(sonda: bytes, preferida: str = "cp1252") -> Perfil:
    """Decide a codificacao a partir dos primeiros bytes. Nunca levanta."""
    for marca, codec in BOMS:
        if sonda.startswith(marca):
            texto, _ = _decodificar(sonda[len(marca):], codec)
            return Perfil(codec=codec, bom=marca,
                          **_do_texto(texto), como_decidiu="BOM")

    if _parece_utf16(sonda):
        codec = "utf-16-le" if sonda[1:2] == b"\x00" else "utf-16-be"
        texto, trocas = _decodificar(sonda, codec)
        return Perfil(codec=codec, suspeito=trocas > 0, **_do_texto(texto),
                      como_decidiu="UTF-16 sem BOM (bytes nulos alternados)")

    try:
        texto = sonda.decode("utf-8")
    except UnicodeDecodeError as erro:
        # Um caractere multibyte cortado no FIM da sondagem nao torna o arquivo
        # invalido -- ele so' foi partido pela sondagem. Tentar de novo sem a
        # cauda evita classificar um UTF-8 legitimo como cp1252.
        if erro.start >= len(sonda) - 4:
            try:
                texto = sonda[:erro.start].decode("utf-8")
                return Perfil(codec="utf-8", **_do_texto(texto),
                              como_decidiu="UTF-8 estrito (cauda aparada)")
            except UnicodeDecodeError:
                pass
    else:
        return Perfil(codec="utf-8", **_do_texto(texto),
                      como_decidiu="UTF-8 estrito")

    palpite = _palpitar(sonda)
    if palpite:
        texto, trocas = _decodificar(sonda, palpite)
        return Perfil(codec=palpite, suspeito=trocas > 0, **_do_texto(texto),
                      como_decidiu="charset-normalizer")

    texto, trocas = _decodificar(sonda, preferida)
    return Perfil(codec=preferida, suspeito=trocas > 0, **_do_texto(texto),
                  como_decidiu=f"ultimo recurso ({preferida})")


def _parece_utf16(sonda: bytes) -> bool:
    """Bytes nulos alternados sao a assinatura pratica do UTF-16 sem BOM."""
    amostra = sonda[:512]
    if len(amostra) < 8:
        return False
    pares = amostra[:len(amostra) // 2 * 2]
    nulos_impares = sum(1 for i in range(1, len(pares), 2) if pares[i] == 0)
    nulos_pares = sum(1 for i in range(0, len(pares), 2) if pares[i] == 0)
    metade = len(pares) // 2
    return max(nulos_impares, nulos_pares) > metade * 0.7


def _palpitar(sonda: bytes) -> str:
    """O palpite do charset-normalizer, ou "" quando ele nao ajuda."""
    if sum(1 for b in sonda if b >= 0x80) < MINIMO_NAO_ASCII:
        return ""
    try:
        from charset_normalizer import from_bytes
    except ImportError:
        return ""
    try:
        melhor = from_bytes(sonda).best()
    except Exception:               # noqa: BLE001 - biblioteca de terceiros
        return ""
    return (melhor.encoding or "").replace("_", "-") if melhor else ""


def _decodificar(dados: bytes, codec: str) -> tuple[str, int]:
    """Decodifica contando quantos caracteres foram substituidos por U+FFFD."""
    try:
        return dados.decode(codec), 0
    except (UnicodeDecodeError, LookupError):
        texto = dados.decode(codec, errors="replace")
        return texto, texto.count("�")


def _do_texto(texto: str) -> dict:
    """Fim de linha dominante e se ha' mistura."""
    crlf = texto.count(CRLF)
    lf = texto.count(LF) - crlf
    cr = texto.count(CR) - crlf
    tipos = sum(1 for n in (crlf, lf, cr) if n > 0)
    if crlf >= lf and crlf >= cr and crlf:
        dominante = CRLF
    elif lf >= cr and lf:
        dominante = LF
    elif cr:
        dominante = CR
    else:
        dominante = CRLF
    return {"fim_de_linha": dominante, "misto": tipos > 1}


def para_lf(texto: str) -> str:
    """Normaliza para \\n. O editor trabalha so' com \\n internamente."""
    return texto.replace(CRLF, LF).replace(CR, LF)


def de_lf(texto: str, fim_de_linha: str) -> str:
    """Devolve o \\n interno ao terminador do arquivo."""
    if fim_de_linha == LF:
        return texto
    return texto.replace(LF, fim_de_linha)
