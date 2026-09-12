"""TextForgeEdit -- editor de texto COMPLETO para arquivos grandes.

O TextForge abre um arquivo de 240 MB instantaneamente e, desde a v0.3.0, deixa
editar LINHA A LINHA: F2 abre um campo sobre a linha, Enter confirma. Resolve
corrigir um valor num export, e nao resolve escrever.

Este projeto e' o outro lado: cursor de caractere, digitacao livre, selecao
atravessando linhas -- um editor de texto de verdade -- sobre um arquivo que
continua no disco.

A ideia central e' a mesma nos dois, e e' a unica coisa que precisa ser entendida
antes de mexer em qualquer arquivo daqui:

    O documento NAO e' texto na memoria. E' uma lista de FAIXAS, umas apontando
    para o arquivo no disco e outras para o que foi digitado.

Ver `pecas.py`. A diferenca para o TextForge e' a granularidade: la' a unidade e'
a LINHA, aqui e' o BYTE -- e e' isso que permite o cursor andar caractere a
caractere.

Autor: Ricardo Biazin. Licenca MIT.
"""

from __future__ import annotations

APP = "TextForgeEdit"
APP_ARQUIVO = "TextForgeEdit"

VERSAO = "0.16.1"
AUTOR = "Ricardo Biazin"

__version__ = VERSAO
