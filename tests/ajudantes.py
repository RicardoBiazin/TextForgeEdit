"""Utilidades comuns as suites de teste.

Trazido do TextForge (mesmo autor, mesma licenca): o formato de saida e o
contrato com o `rodar_todos.py` sao os mesmos, e divergir aqui so' criaria
dois jeitos de escrever a mesma verificacao.

Formato de saida, identico ao do Sincronizador -- o `rodar_todos.py` conta as
ocorrencias de "\\n  OK   " e "\\n  FALHA" na saida de cada suite, entao os
espacos importam:

    checa(cond, "descricao do que foi verificado")

No fim da suite, `resumir()` imprime o total e devolve o codigo de saida.

Importante: `preparar_qt()` define QT_QPA_PLATFORM=offscreen ANTES de importar
PySide6. Se algum modulo importar Qt antes disso, a plataforma ja' esta' escolhida
e o teste abriria janelas de verdade -- por isso toda suite de interface chama
`preparar_qt()` na primeira linha executavel, antes de qualquer outro import do
projeto que arraste Qt.
"""

from __future__ import annotations

import contextlib
import atexit
import os
import pathlib
import shutil
import sys
import tempfile
import uuid
from typing import Iterator

# Deixa `import textforge` funcionar rodando `python tests/teste_x.py` de
# qualquer pasta, sem precisar instalar o pacote nem mexer no PYTHONPATH.
RAIZ = pathlib.Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

falhas: list[str] = []
_total = 0


# O console do Windows costuma ser cp1252, e uma mensagem de teste com um
# caractere de fora dessa tabela -- um ideograma numa suite de CODIFICACAO, por
# exemplo -- derrubava o runner inteiro com UnicodeEncodeError, no meio da
# suite, sem relatorio nenhum. O teste falharia; o runner nao pode.
for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass


def checa(condicao: object, mensagem: str) -> bool:
    """Registra uma verificacao. Devolve o booleano, para poder encadear."""
    global _total
    _total += 1
    ok = bool(condicao)
    print(("  OK   " if ok else "  FALHA") + " " + mensagem)
    if not ok:
        falhas.append(mensagem)
    return ok


def checa_igual(obtido: object, esperado: object, mensagem: str) -> bool:
    """Como `checa`, mas mostra os valores quando falha -- economiza um ciclo
    inteiro de "rodar de novo com print no meio"."""
    ok = obtido == esperado
    if ok:
        return checa(True, mensagem)
    return checa(False, f"{mensagem}\n         esperado: {esperado!r}"
                        f"\n         obtido:   {obtido!r}")


def checa_levanta(excecao: type[BaseException], funcao, mensagem: str,
                  *args, **kwargs) -> bool:
    try:
        funcao(*args, **kwargs)
    except excecao:
        return checa(True, mensagem)
    except BaseException as exc:      # noqa: BLE001 - o teste quer saber qual foi
        return checa(False, f"{mensagem} (levantou {exc.__class__.__name__})")
    return checa(False, f"{mensagem} (nao levantou nada)")


def secao(titulo: str) -> None:
    print(f"\n[{titulo}]")


def resumir() -> int:
    print()
    if falhas:
        print("FALHAS: %d de %d verificacoes" % (len(falhas), _total))
        for f in falhas:
            print("  - " + f.splitlines()[0])
    else:
        print("TODOS OS TESTES PASSARAM (%d verificacoes)" % _total)
    return 1 if falhas else 0


# -- ambiente ---------------------------------------------------------------


def _isolar_appdata() -> None:
    """Aponta %APPDATA% para uma pasta descartavel, para o processo inteiro.

    NAO e' zelo excessivo: ja' aconteceu. Uma suite montou uma janela com
    `{"linhas_da_janela": 100}`, a janela gravou as preferencias ao fechar, e
    isso foi parar no config REAL do usuario -- que passou a abrir todo arquivo
    com uma fatia de 100 linhas. Junto foram caminhos de pasta temporaria para
    a lista de recentes.

    O estrago atravessou processos: `teste_editor.py` comecou a falhar porque
    LIA a preferencia que outra suite tinha escrito. Um teste que suja o
    ambiente do usuario nao e' um teste ruim so' por ser invasivo; ele fica
    NAO DETERMINISTICO, e a falha aparece em outro arquivo.

    Fica aqui, e nao em cada teste, porque toda suite chama `preparar_qt()`
    antes de qualquer coisa -- lembrar caso a caso e' o que falhou antes.
    """
    if os.environ.get("TFEDIT_APPDATA_ISOLADO"):
        return
    pasta = pathlib.Path(tempfile.mkdtemp(prefix="tfedit-appdata-suite-"))
    os.environ["APPDATA"] = str(pasta)
    os.environ["TFEDIT_APPDATA_ISOLADO"] = "1"
    atexit.register(shutil.rmtree, pasta, True)


def _isolar_canal() -> None:
    """Da a este processo um canal de instancia unica so' dele.

    Sem isto a suite usa o canal DE PRODUCAO, e passa a brigar com o programa
    que o usuario pode ter aberto: "entregar devolve False quando nao ha'
    ninguem" falha porque ha' alguem -- a janela de verdade --, e a suite chega
    a mandar pedidos de abrir arquivo para ela.

    Aconteceu, e as duas falhas pareciam regressao do codigo. Mesmo motivo do
    `_isolar_appdata`: teste nao usa recurso de producao.
    """
    from tfedit import instancia_unica

    os.environ.setdefault(
        instancia_unica.VARIAVEL_DO_CANAL,
        f"TextForgeEdit-teste-{os.getpid()}-{uuid.uuid4().hex[:8]}")


def preparar_qt() -> bool:
    """Prepara uma QApplication invisivel. False se PySide6 nao esta' instalado.

    Uma suite que precisa de Qt e nao o encontra deve imprimir PULADO e sair com
    0, nao falhar: assim o runner continua util numa maquina onde o venv ainda
    nao foi montado.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _isolar_appdata()
    _isolar_canal()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return False
    if QApplication.instance() is None:
        QApplication([])
    return True


def pular(motivo: str) -> int:
    print(f"PULADO: {motivo}")
    return 0


@contextlib.contextmanager
def pasta_temporaria(prefixo: str = "tfedit-teste-") -> Iterator[pathlib.Path]:
    """Pasta temporaria apagada no fim, mesmo se o teste estourar."""
    caminho = pathlib.Path(tempfile.mkdtemp(prefix=prefixo))
    try:
        yield caminho
    finally:
        shutil.rmtree(caminho, ignore_errors=True)


@contextlib.contextmanager
def appdata_temporario() -> Iterator[pathlib.Path]:
    """Aponta %APPDATA% para uma pasta descartavel.

    Sem isto os testes de configuracao e de sessao escreveriam no
    %APPDATA%\\TextForge de verdade e apagariam as preferencias do usuario --
    exatamente o tipo de dano colateral que um teste nunca deve causar.
    """
    anterior = os.environ.get("APPDATA")
    with pasta_temporaria("tfedit-appdata-") as pasta:
        os.environ["APPDATA"] = str(pasta)
        try:
            yield pasta
        finally:
            if anterior is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = anterior


def memoria_privada_mb() -> float:
    """Memoria PRIVADA (commit) do processo, em MB. 0.0 quando nao da' para medir.

    Privada, e nao WorkingSet: o working set inclui as paginas de um mmap, e um
    teste de arquivo grande diria que o programa gastou 200 MB quando quem as
    guarda e' o cache do sistema operacional.

    ARMADILHA QUE JA' CUSTOU UMA MEDICAO ERRADA: sem declarar
    `GetCurrentProcess.restype = c_void_p`, o ctypes trata o retorno como C int e
    TRUNCA o pseudo-handle -1 para 32 bits. A chamada falha, a struct fica zerada,
    e a funcao devolve 0.0 -- fazendo qualquer "checa(gasto < teto)" passar sem
    medir nada. O `if not ok: raise` existe para isso nunca mais passar calado.
    """
    if os.name != "nt":
        return 0.0
    import ctypes
    import ctypes.wintypes as wt

    class _Contadores(ctypes.Structure):
        _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t)]

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,
                                           ctypes.POINTER(_Contadores), wt.DWORD]
    psapi.GetProcessMemoryInfo.restype = wt.BOOL

    info = _Contadores()
    info.cb = ctypes.sizeof(info)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                      ctypes.byref(info), info.cb):
        raise OSError("GetProcessMemoryInfo falhou: a medicao de memoria nao "
                      "pode ser silenciosamente zero")
    return info.PagefileUsage / (1024 * 1024)


def drenar_eventos(rodadas: int = 4) -> None:
    """Processa eventos ATE' E INCLUSIVE os DeferredDelete, e coleta o lixo.

    `QApplication.processEvents()` sozinho NAO entrega DeferredDelete -- o objeto
    de `deleteLater()` continua vivo, e um teste de vazamento acusaria codigo
    correto.
    """
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    for _ in range(rodadas):
        QApplication.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()


def escrever_bytes(caminho: pathlib.Path, dados: bytes) -> pathlib.Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(dados)
    return caminho
