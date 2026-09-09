"""Preferências em `%APPDATA%\\TextForgeEdit\\config.json`.

Em `%APPDATA%`, e **não** ao lado do executável: a pasta do programa pode estar
em `Arquivos de Programas`, onde escrever exige privilégio de administrador —
e um editor de texto não deve pedir isso para lembrar o tamanho da fonte.

Três decisões que evitam defeito conhecido:

**Chave nova entra por união com o padrão.** Um `config.json` de uma versão
anterior não tem as chaves que só existem agora. Ler o arquivo por cima do
dicionário padrão faz a versão nova funcionar sem apagar o que o usuário
escolheu — e sem exigir migração.

**Config corrompido não impede abrir.** JSON quebrado (queda de energia no meio
da gravação, edição manual malfeita) volta ao padrão com um aviso no log, em vez
de derrubar o programa. Uma preferência perdida é bem menos grave que um editor
que não abre.

**A gravação é atômica.** Escrever direto por cima deixa o arquivo pela metade
se o programa for encerrado no meio — e um `config.json` truncado é exatamente o
que cai no caso acima na próxima abertura.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

from tfedit import log_interno

log = log_interno.obter(__name__)

APP = "TextForgeEdit"

#: Quantos arquivos recentes lembrar. Uma lista longa demais vira rolagem, e
#: ninguém procura o 40º arquivo aberto.
MAXIMO_DE_RECENTES = 15


def pasta_de_dados() -> pathlib.Path:
    """`%APPDATA%\\TextForgeEdit`, criada se preciso."""
    base = os.environ.get("APPDATA") or os.environ.get("TEMP") or "."
    alvo = pathlib.Path(base) / APP
    try:
        alvo.mkdir(parents=True, exist_ok=True)
    except OSError as erro:
        log.warning("não foi possível criar %s: %s", alvo, erro)
    return alvo


def caminho() -> pathlib.Path:
    return pasta_de_dados() / "config.json"


def padrao() -> dict[str, Any]:
    """A configuração de primeira execução."""
    return {
        # -- aparência ------------------------------------------------------
        # Consolas é a monoespaçada que vem em todo Windows desde o Vista. O
        # `fonte_alternativa` existe para instalações que não a tenham.
        "fonte": "Consolas",
        "fonte_alternativa": "Courier New",
        "fonte_tamanho": 11,
        "tabulacao": 4,
        "quebrar_linha": False,
        # "escuro", "claro", "azul" ou "sistema" (segue o Windows).
        "tema": "sistema",
        "mostrar_numero_de_linha": True,

        # -- janela ---------------------------------------------------------
        "janela_largura": 1150,
        "janela_altura": 780,
        "janela_maximizada": False,

        # -- comportamento --------------------------------------------------
        "restaurar_sessao": True,
        "recentes": [],
        # Onde os diálogos de abrir e salvar começam. Vazio = a pasta do
        # arquivo atual, que é o comportamento do sistema.
        "pasta_padrao": "",

        # -- barra de atalhos -----------------------------------------------
        "mostrar_barra": True,
        # Os botões, NA ORDEM em que aparecem. Marcáveis na tela de
        # Configurações. Uma chave desconhecida aqui é ignorada, e um botão
        # novo do programa só entra na barra de quem pedir -- assim uma
        # atualização não reordena a barra de ninguém.
        "botoes_da_barra": [
            "novo", "abrir", "salvar", "salvar_tudo",
            "desfazer", "refazer",
            "recortar", "copiar", "colar",
            "localizar", "substituir",
            "visualizar", "comparar",
        ],

        # -- limites (ver os cabeçalhos dos módulos citados) -----------------
        # Linhas que a janela viva segura de cada vez. Ver `janela.py`.
        "linhas_da_janela": 5000,
        # Acima disto, "substituir todas" avisa que só troca as primeiras.
        "limite_de_substituicoes": 100000,
        # Segundos sem uso até soltar o mmap do arquivo. Ver `original.py`:
        # enquanto ele está mapeado, nenhum outro programa consegue regravar o
        # arquivo no Windows. Zero desliga a liberação.
        "soltar_arquivo_apos_s": 20,

        # Estas cinco ERAM lidas pelo código e não estavam declaradas aqui.
        # A diferença não é cosmética: uma chave ausente nunca aparece no
        # arquivo de configuração, então não havia como o usuário mudá-la --
        # `tema` inclusive, que a janela lia com um padrão embutido.
        # Acima disto um .xlsx abre como arquivo comum. Ver `interface/aba.py`.
        "limite_planilha_mb": 100,
        # Células lidas de uma planilha antes de ela virar somente leitura.
        "limite_celulas_planilha": 500000,
        # Acima disto o realce de sintaxe desliga: colorir 200 MB pararia a
        # rolagem. Ver `realce/pintor.py`.
        "limite_realce_mb": 8,
        # Uma linha maior que isto não é realçada. Um JSON minificado numa
        # linha só tornaria o regex o gargalo da rolagem.
        "limite_realce_por_linha": 10000,
    }


def pasta_de_temas() -> pathlib.Path:
    """`%APPDATA%\\TextForgeEdit\\temas`: temas do usuario, alem dos embutidos.

    Nao e' criada aqui. Quem le' um tema apenas varre a pasta, e uma pasta
    inexistente devolve lista vazia -- criar diretorio como efeito colateral de
    uma leitura e' surpresa desnecessaria.
    """
    return pasta_de_dados() / "temas"


def carregar() -> dict[str, Any]:
    """Lê o config. Volta ao padrão, com aviso, se ele não servir."""
    valores = padrao()
    alvo = caminho()
    if not alvo.is_file():
        return valores
    try:
        lido = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        log.warning("config ilegível em %s (%s); usando o padrão", alvo, erro)
        return valores
    if not isinstance(lido, dict):
        log.warning("config não é um objeto JSON; usando o padrão")
        return valores

    # União, e não substituição: uma versão nova traz chaves que o arquivo
    # antigo não tem, e uma chave que sumiu do padrão não deve voltar.
    for chave, valor in lido.items():
        if chave in valores and isinstance(valor, type(valores[chave])):
            valores[chave] = valor
        elif chave in valores:
            log.warning("config: %r tem tipo inesperado (%s); mantendo o padrão",
                        chave, type(valor).__name__)
    return valores


def gravar(valores: dict[str, Any]) -> bool:
    """Grava o config de forma atômica. False se não deu (nunca levanta)."""
    alvo = caminho()
    temporario = alvo.with_suffix(".json.novo")
    try:
        temporario.write_text(
            json.dumps(valores, indent=2, ensure_ascii=False),
            encoding="utf-8")
        os.replace(temporario, alvo)
        return True
    except OSError as erro:
        log.warning("não foi possível gravar %s: %s", alvo, erro)
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def registrar_recente(valores: dict[str, Any], arquivo) -> None:
    """Põe o arquivo no topo dos recentes, sem repetir.

    Compara por caminho resolvido em caixa baixa: no Windows o mesmo arquivo
    chega com caixa diferente pelo Explorer e pela forma curta 8.3, e sem isso
    a lista encheria de duplicatas do mesmo arquivo.
    """
    try:
        completo = str(pathlib.Path(arquivo).resolve())
    except OSError:
        completo = str(arquivo)
    chave = completo.lower()

    recentes = [c for c in valores.get("recentes", [])
                if isinstance(c, str) and c.lower() != chave]
    recentes.insert(0, completo)
    valores["recentes"] = recentes[:MAXIMO_DE_RECENTES]


def recentes_existentes(valores: dict[str, Any]) -> list[str]:
    """Os recentes que ainda existem no disco.

    Filtrar na LEITURA, e não na gravação: um arquivo numa unidade de rede
    desconectada não deve sumir da lista para sempre só porque a rede caiu no
    momento em que o programa foi aberto.
    """
    vivos = []
    for item in valores.get("recentes", []):
        try:
            if pathlib.Path(item).is_file():
                vivos.append(item)
        except OSError:
            continue
    return vivos
