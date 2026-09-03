"""Gravar o documento sem nunca te-lo inteiro na memoria.

Uma peca ORIGINAL vai do arquivo velho para o novo como BYTES: nao e'
decodificada, nao e' recodificada, nao vira `str`. So' o que o usuario digitou
passa por codificacao -- e ele ja' esta' em bytes desde que foi digitado.

O pico de memoria e' um bloco, e nao o arquivo. Gravar 240 MB com tres paragrafos
alterados custa 240 MB de DISCO e alguns MB de RAM.

A ORDEM NO WINDOWS NAO E' NEGOCIAVEL, e e' a razao de `antes_de_trocar` existir:

    escrever o temporario   <- com o mmap ABERTO: e' de onde vem cada peca
    fechar o mmap           <- um mmap vivo SEGURA o arquivo
    trocar                  <- ReplaceFileW / os.replace
    reabrir                 <- a `Original` nova, sobre o arquivo gravado

Fechar antes de escrever produz um arquivo vazio. Deixar aberto faz a troca
falhar com acesso negado. As duas falhas ja' aconteceram no projeto irmao.

A troca e' ATOMICA: enquanto o temporario esta' sendo escrito, o arquivo do
usuario continua intacto no lugar. Disco cheio, queda de energia ou cancelamento
no meio nao deixam o arquivo pela metade -- eles deixam o arquivo ORIGINAL.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

from tfedit.pecas import ORIGINAL, Documento

#: Quanto se copia por vez. O bastante para o custo por byte ser o do memcpy.
BLOCO = 4 * 1024 * 1024

#: Folga exigida alem do tamanho do arquivo, para o temporario caber com sobra.
FOLGA = 16 * 1024 * 1024

SUFIXO = ".tfenew"

#: Esperas entre tentativas de troca. Antivirus e indexador do Windows abrem o
#: arquivo por alguns milissegundos logo depois de ele ser escrito, e a troca
#: falha com "acesso negado" que some sozinho.
ESPERAS = (0.0, 0.05, 0.15, 0.40)


class SemEspaco(OSError):
    """Nao ha' espaco para o temporario da troca atomica."""


class FalhaNaTroca(OSError):
    """O temporario foi escrito, mas nao substituiu o destino."""


def espaco_livre(caminho) -> int:
    """Bytes livres na unidade do arquivo. -1 quando nao da' para saber."""
    try:
        alvo = pathlib.Path(caminho)
        pasta = alvo.parent if alvo.parent.exists() else pathlib.Path(".")
        return shutil.disk_usage(pasta).free
    except OSError:
        return -1


def conferir_espaco(caminho, previsto: int) -> None:
    """Levanta `SemEspaco` ANTES de escrever o primeiro byte.

    O temporario nasce na MESMA PASTA do destino -- obrigatorio, porque
    `os.replace` entre volumes falha e e' comum o arquivo estar num mapeamento de
    rede com o %TEMP% em C:. Descobrir que faltou disco depois de escrever
    200 MB e' o pior momento possivel.
    """
    livre = espaco_livre(caminho)
    if livre < 0:
        return
    if livre < previsto + FOLGA:
        faltam = (previsto + FOLGA - livre) // (1024 * 1024)
        raise SemEspaco(
            f"faltam ~{faltam} MB livres em "
            f"{pathlib.Path(caminho).drive or 'disco'}: a gravacao atomica "
            f"escreve um arquivo temporario do mesmo tamanho ao lado do original")


def blocos(documento: Documento, cancelar=None):
    """Gera os bytes do arquivo novo, na ordem das pecas."""
    for peca in documento.blocos():
        if peca.tamanho <= 0:
            continue
        if peca.fonte == ORIGINAL:
            posicao = peca.inicio
            fim = peca.inicio + peca.tamanho
            while posicao < fim:
                if cancelar is not None and cancelar():
                    return
                ate = min(posicao + BLOCO, fim)
                yield documento.original.ler(posicao, ate)
                posicao = ate
        else:
            yield bytes(documento._adicionado[
                peca.inicio:peca.inicio + peca.tamanho])


def gravar(caminho, documento: Documento, *, antes_de_trocar=None,
           cancelar=None) -> int:
    """Grava o documento. Devolve quantos bytes foram escritos."""
    alvo = pathlib.Path(caminho)
    conferir_espaco(alvo, documento.tamanho)
    temporario = alvo.with_name(alvo.name + SUFIXO)
    escritos = 0

    try:
        with open(temporario, "wb") as saida:
            for bloco in blocos(documento, cancelar):
                if bloco:
                    saida.write(bloco)
                    escritos += len(bloco)
            saida.flush()
            # fsync ANTES da troca: sem ele, um desligamento entre o write e o
            # replace pode deixar o temporario vazio E ja' trocado.
            os.fsync(saida.fileno())
    except BaseException:
        # Qualquer falha, inclusive cancelamento, deixa o ORIGINAL intacto --
        # nada foi trocado ainda. O temporario sai para nao deixar um arquivo
        # de 240 MB pela metade ao lado do bom.
        _remover(temporario)
        raise

    try:
        if antes_de_trocar is not None:
            antes_de_trocar()
        _trocar(temporario, alvo)
    finally:
        _remover(temporario)
    return escritos


def _remover(caminho: pathlib.Path) -> None:
    if caminho.exists():
        try:
            caminho.unlink()
        except OSError:
            pass


def _trocar(temporario: pathlib.Path, destino: pathlib.Path) -> None:
    """Substitui o destino pelo temporario, com retry.

    `ReplaceFileW` e' preferido a `os.replace` no Windows: ele PRESERVA dono,
    ACLs, atributos e fluxos alternativos do arquivo original. O `os.replace`
    cria um arquivo novo com as permissoes herdadas da pasta -- num arquivo com
    ACE explicita, salvar mudaria quem pode le-lo.
    """
    ultimo: OSError | None = None
    for espera in ESPERAS:
        if espera:
            time.sleep(espera)
        try:
            if os.name == "nt" and _replace_file_w(temporario, destino):
                return
            os.replace(temporario, destino)
            return
        except OSError as exc:
            ultimo = exc
    raise FalhaNaTroca(
        f"nao foi possivel substituir {destino.name}: {ultimo}. "
        f"O arquivo original NAO foi alterado.") from ultimo


def _replace_file_w(temporario: pathlib.Path, destino: pathlib.Path) -> bool:
    """`ReplaceFileW` do Windows. False quando nao deu (quem chama tenta o resto)."""
    if not destino.exists():
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReplaceFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID]
        kernel32.ReplaceFileW.restype = wintypes.BOOL
        # 0x1 = REPLACEFILE_WRITE_THROUGH
        return bool(kernel32.ReplaceFileW(str(destino), str(temporario), None,
                                          0x1, None, None))
    except (OSError, AttributeError, ImportError):
        return False
