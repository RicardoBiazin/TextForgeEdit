"""A sessão: quais arquivos estavam abertos e em que linha.

Guardada em `%APPDATA%\\TextForgeEdit\\sessao.json`.

**O que NÃO é guardado: o conteúdo.** Este é o ponto em que a sessão de um
editor de arquivo grande difere da de um editor comum. Um editor normal grava
uma cópia de recuperação do texto não salvo; aqui *todo* arquivo é potencialmente
de 1 GB, e copiá-lo para `%APPDATA%` a cada intervalo transformaria a rede de
segurança no maior custo do programa.

O que se guarda é o **diário de edições**: a lista de peças mais o texto
digitado. Um documento com cinquenta correções cabe em alguns KB, porque as
peças ORIGINAIS são só coordenadas — o conteúdo delas continua no arquivo.

E por isso a sessão carrega a **assinatura** do arquivo. Reaplicar peças que
apontam para offsets de um arquivo que mudou no disco escreveria conteúdo certo
em lugar errado; é o defeito mais destrutivo que esta estrutura permite. Quando a
assinatura não confere, a recuperação é **recusada** e o arquivo abre limpo, com
aviso — perder as edições pendentes é ruim, misturar dois arquivos é pior.
"""

from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import dataclass, field

from tfedit import configuracao, log_interno
from tfedit.original import Assinatura

log = log_interno.obter(__name__)

#: Versão do formato. Um arquivo de sessão de outro formato é ignorado inteiro,
#: em vez de lido pela metade -- meia sessão restaurada é pior que nenhuma.
FORMATO = 1


def caminho() -> pathlib.Path:
    return configuracao.pasta_de_dados() / "sessao.json"


@dataclass
class AbaGuardada:
    """Um arquivo que estava aberto."""

    caminho: str
    linha: int = 0
    #: Diário de edições pendentes. Vazio quando não havia nada por salvar.
    diario: dict = field(default_factory=dict)
    assinatura: dict = field(default_factory=dict)

    @property
    def tem_pendencia(self) -> bool:
        return bool(self.diario.get("pecas"))

    def arquivo_confere(self) -> bool:
        """O arquivo no disco ainda é aquele sobre o qual se editou?"""
        guardada = self.assinatura or {}
        if not guardada:
            return False
        agora = Assinatura.de_caminho(pathlib.Path(self.caminho))
        if agora.tamanho < 0:
            return False
        if int(guardada.get("tamanho", -1)) != agora.tamanho:
            return False
        pontas = str(guardada.get("pontas", ""))
        if pontas and agora.pontas:
            return pontas == agora.pontas
        return int(guardada.get("mtime_ns", -1)) == agora.mtime_ns


def _assinatura_como_dicionario(assinatura: Assinatura) -> dict:
    return {"tamanho": assinatura.tamanho, "mtime_ns": assinatura.mtime_ns,
            "pontas": assinatura.pontas}


def capturar(abas) -> list[AbaGuardada]:
    """Monta o retrato das abas abertas.

    `abas` são objetos com `caminho`, `original`, `documento` e `editor` -- a
    `Aba` da interface. A função não importa Qt de propósito: assim ela é
    testável sem tela.
    """
    guardadas = []
    for aba in abas:
        try:
            documento = aba.documento
            guardada = AbaGuardada(
                caminho=str(aba.caminho),
                linha=int(aba.editor.linha_atual_no_documento()),
                assinatura=_assinatura_como_dicionario(aba.original.assinatura))
            if documento.alterado:
                guardada.diario = documento.diario()
            guardadas.append(guardada)
        except Exception as erro:          # noqa: BLE001 - nunca derrubar
            # Uma aba problemática não pode impedir as outras de serem
            # guardadas: a sessão é conveniência, e falhar nela ao fechar
            # perderia o registro de tudo.
            log.warning("aba não incluída na sessão: %s", erro)
    return guardadas


def gravar(guardadas: list[AbaGuardada]) -> bool:
    """Grava a sessão de forma atômica. False se não deu (nunca levanta)."""
    dados = {
        "formato": FORMATO,
        "quando": time.time(),
        "abas": [
            {"caminho": g.caminho, "linha": g.linha, "diario": g.diario,
             "assinatura": g.assinatura}
            for g in guardadas],
    }
    alvo = caminho()
    temporario = alvo.with_suffix(".json.novo")
    try:
        temporario.write_text(json.dumps(dados, ensure_ascii=False),
                              encoding="utf-8")
        os.replace(temporario, alvo)
        return True
    except OSError as erro:
        log.warning("não foi possível gravar a sessão: %s", erro)
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def ler() -> list[AbaGuardada]:
    """A sessão anterior. Lista vazia quando não há, ou quando não serve."""
    alvo = caminho()
    if not alvo.is_file():
        return []
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        log.warning("sessão ilegível (%s); ignorada", erro)
        return []
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO:
        log.info("sessão de outro formato; ignorada")
        return []

    guardadas = []
    for bruto in dados.get("abas", []):
        if not isinstance(bruto, dict) or not bruto.get("caminho"):
            continue
        # O arquivo pode ter sido apagado, renomeado ou estar numa unidade de
        # rede desconectada. Uma aba que não abre não deve virar erro na
        # partida -- ela simplesmente não volta.
        try:
            if not pathlib.Path(str(bruto["caminho"])).is_file():
                continue
        except OSError:
            continue
        guardadas.append(AbaGuardada(
            caminho=str(bruto["caminho"]),
            linha=int(bruto.get("linha", 0) or 0),
            diario=dict(bruto.get("diario") or {}),
            assinatura=dict(bruto.get("assinatura") or {})))
    return guardadas


def esquecer() -> None:
    """Apaga a sessão. Chamada quando ela já foi restaurada."""
    try:
        caminho().unlink(missing_ok=True)
    except OSError:
        pass
