"""Linha de comando: arquivos, `--linha` e o que é recusado.

    TextForgeEdit arquivo.txt
    TextForgeEdit registro.log --linha 148200
    TextForgeEdit a.txt b.txt c.txt

**Nomes de dispositivo do Windows são RECUSADOS.** `CON`, `NUL`, `PRN`, `AUX`,
`COM1`..`COM9` e `LPT1`..`LPT9` não são arquivos: abrir `CON` lê do console e
abrir `NUL` devolve vazio para sempre. Pior, isso vale mesmo com extensão e em
qualquer pasta -- `C:\\temp\\nul.txt` ainda é o dispositivo. Num editor que mapeia
o arquivo em memória, tentar isso trava ou devolve lixo, e o usuário não
entende por quê.

O parser é escrito à mão, e não com `argparse`, por um motivo prático: o
`argparse` chama `sys.exit()` com mensagem em inglês no `stderr`, que num
programa de janela (`console=False`) não vai para lugar nenhum -- o usuário
veria o programa simplesmente não abrir.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass, field

#: Nomes reservados do Windows. A comparação é pelo nome SEM extensão e sem
#: caixa: `nul`, `NUL.txt` e `Nul.log` são todos o mesmo dispositivo.
DISPOSITIVOS = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)])

AJUDA = """TextForgeEdit -- editor de texto para arquivos grandes.

    TextForgeEdit [arquivo ...] [--linha N] [--coluna N]

    --linha N          põe o cursor na linha N (base 1)
    --coluna N         e na coluna N (base 1)
    --autoverificacao  prova de vida do executável; não abre janela
    --ajuda            mostra isto
"""


@dataclass
class Pedido:
    """O que a linha de comando pediu."""

    arquivos: list[str] = field(default_factory=list)
    linha: int = 0                  # base 1; 0 = não pediram
    coluna: int = 0
    ajuda: bool = False
    autoverificacao: bool = False
    recusados: list[tuple[str, str]] = field(default_factory=list)


def e_dispositivo(caminho: str) -> bool:
    """O caminho aponta para um dispositivo do Windows?"""
    nome = pathlib.PurePath(caminho).name
    # `NUL.txt` também é o dispositivo: o Windows olha só o que vem antes do
    # primeiro ponto.
    return nome.split(".")[0].strip().lower() in DISPOSITIVOS


def analisar(argumentos: list[str]) -> Pedido:
    """Interpreta os argumentos. Nunca levanta -- o que não serve vai em
    `recusados`, para a interface avisar em português."""
    pedido = Pedido()
    esperando = ""

    for bruto in argumentos:
        if esperando:
            if re.fullmatch(r"\d{1,12}", bruto):
                valor = max(1, int(bruto))
                if esperando == "linha":
                    pedido.linha = valor
                else:
                    pedido.coluna = valor
            else:
                pedido.recusados.append(
                    (bruto, f"--{esperando} espera um número"))
            esperando = ""
            continue

        alvo = bruto.lower()
        if alvo in ("--ajuda", "--help", "-h", "/?"):
            pedido.ajuda = True
        elif alvo == "--autoverificacao":
            pedido.autoverificacao = True
        elif alvo in ("--linha", "--line", "-l"):
            esperando = "linha"
        elif alvo in ("--coluna", "--col", "-c"):
            esperando = "coluna"
        elif bruto.startswith("-"):
            pedido.recusados.append((bruto, "opção desconhecida"))
        elif e_dispositivo(bruto):
            pedido.recusados.append(
                (bruto, "é um dispositivo do Windows, e não um arquivo"))
        else:
            pedido.arquivos.append(bruto)

    if esperando:
        pedido.recusados.append((f"--{esperando}", "faltou o número"))
    return pedido
