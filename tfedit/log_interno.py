"""Log em `%APPDATA%\\TextForgeEdit`, e o relatorio de erro nao tratado.

Existe por uma falha concreta: numa sessao de teste o executavel sumiu depois de
gravar um arquivo de 176 MB, e nao houve NADA para consultar -- nem traceback,
nem ultima operacao, nem tamanho do arquivo. Tres tentativas de reproduzir
falharam, e o defeito continua sem causa conhecida. Um programa que mexe em
arquivo do usuario nao pode desaparecer em silencio.

TRES DECISOES:

**O log rotaciona por tamanho.** Um editor aberto o dia inteiro com um `.log`
grande escreveria sem parar; sem teto, o proprio diagnostico viraria o problema.

**Excecao nao tratada vai para o log E para um arquivo separado.** O
`erro.log` guarda o traceback inteiro da ultima vez que o programa quebrou, sem
se misturar ao fluxo normal -- e' o arquivo que se pede ao usuario.

**Nada aqui levanta.** Uma falha ao ESCREVER o log nao pode derrubar o programa:
o diagnostico e' util, o arquivo do usuario e' essencial.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import pathlib
import sys
import traceback

APP = "TextForgeEdit"

#: Teto do arquivo de log, com uma copia anterior guardada. 2 MB cobrem varios
#: dias de uso e cabem num anexo de e-mail.
TETO_BYTES = 2 * 1024 * 1024
COPIAS = 1

_configurado = False


def pasta() -> pathlib.Path:
    """`%APPDATA%\\TextForgeEdit`, criada se preciso. Cai para o TEMP se falhar."""
    base = os.environ.get("APPDATA") or os.environ.get("TEMP") or "."
    alvo = pathlib.Path(base) / APP
    try:
        alvo.mkdir(parents=True, exist_ok=True)
        return alvo
    except OSError:
        import tempfile
        return pathlib.Path(tempfile.gettempdir())


def caminho_do_log() -> pathlib.Path:
    return pasta() / "textforgeedit.log"


def caminho_do_erro() -> pathlib.Path:
    return pasta() / "erro.log"


def configurar(nivel: int = logging.INFO) -> None:
    """Liga o log. Idempotente -- chamar duas vezes nao duplica as linhas."""
    global _configurado
    if _configurado:
        return
    _configurado = True

    raiz = logging.getLogger("tfedit")
    raiz.setLevel(nivel)
    raiz.propagate = False

    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-28s %(message)s")
    try:
        arquivo = logging.handlers.RotatingFileHandler(
            caminho_do_log(), maxBytes=TETO_BYTES, backupCount=COPIAS,
            encoding="utf-8")
        arquivo.setFormatter(formato)
        raiz.addHandler(arquivo)
    except OSError:
        # Pasta sem permissao de escrita. O programa continua -- sem log.
        pass

    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formato)
        raiz.addHandler(console)


def obter(nome: str) -> logging.Logger:
    """O logger de um modulo. `obter(__name__)`, como no resto do projeto."""
    configurar()
    return logging.getLogger(nome if nome.startswith("tfedit")
                             else f"tfedit.{nome}")


def instalar_captura_de_erros() -> None:
    """Manda toda excecao NAO TRATADA para o log e para o `erro.log`.

    Sem isto, um erro dentro de um slot do Qt pode derrubar o programa sem
    deixar rastro: o `stderr` de um executavel de janela nao vai para lugar
    nenhum. Foi exatamente essa cegueira que motivou este modulo.
    """
    log = obter(__name__)
    anterior = sys.excepthook

    def tratar(tipo, valor, tb) -> None:
        if issubclass(tipo, KeyboardInterrupt):
            anterior(tipo, valor, tb)
            return
        texto = "".join(traceback.format_exception(tipo, valor, tb))
        log.critical("EXCECAO NAO TRATADA\n%s", texto)
        try:
            import time
            with open(caminho_do_erro(), "a", encoding="utf-8") as saida:
                saida.write(f"\n{'=' * 70}\n"
                            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"{'=' * 70}\n{texto}")
        except OSError:
            pass
        anterior(tipo, valor, tb)

    sys.excepthook = tratar


def registrar_partida(versao: str) -> None:
    """Primeira linha de cada sessao. E' o que da' contexto ao resto do log."""
    log = obter(__name__)
    log.info("=" * 60)
    log.info("%s %s | Python %s | %s", APP, versao,
             sys.version.split()[0], sys.platform)
    log.info("log em %s", caminho_do_log())
