"""Roda todas as suites e resume o resultado.

    .venv\\Scripts\\python.exe tests\\rodar_todos.py

Sem pytest, de proposito -- e' o padrao dos projetos desta maquina, e tem a
vantagem de rodar cada suite num processo separado: um travamento de Qt numa
suite nao leva as outras.
"""

from __future__ import annotations

import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

#: Teto por suite. Um limite obrigatorio num projeto de interface: um dialogo
#: modal aberto sem ninguem para clicar bloqueia PARA SEMPRE, e sem o limite a
#: rodada ficaria pendurada em vez de apontar a suite culpada.
LIMITE_POR_SUITE_S = 180

LIMITE_PROPRIO_S: dict[str, int] = {
    # Cria um CSV de 200 mil linhas para provar que a grade nao le tudo.
    "teste_visualizadores.py": 300,
    # Gera dezenas de MB em %TEMP% e mede memoria.
    "teste_pecas.py": 600,
    "teste_sessao.py": 300,
    "teste_janela_principal.py": 400,
}

SUITES = [
    ("teste_base.py",
     "configuracao, linha de comando, soltura do arquivo e assinatura"),
    ("teste_pecas.py",
     "indice do original, tabela de pecas, gravacao por streaming"),
    ("teste_janela.py",
     "deteccao de codificacao, janela viva, escrita de volta minima"),
    ("teste_editor.py",
     "ponta a ponta: abrir, digitar com acento, deslizar, gravar"),
    ("teste_busca.py",
     "localizar e substituir no documento inteiro, fora da fatia"),
    ("teste_sessao.py",
     "sessao pelo diario, assinatura e instancia unica entre processos"),
    ("teste_idioma.py",
     "portugues do Brasil: acentos nos textos e nos dialogos do Qt"),
    ("teste_conversao.py",
     "reinterpretar e converter a codificacao, sem perda silenciosa"),
    ("teste_realce.py",
     "realce de sintaxe na fatia: 24 linguagens e a semente de contexto"),
    ("teste_csv_dialeto.py",
     "dialeto de CSV: delimitador pela consistencia, nao pela frequencia"),
    ("teste_planilha.py",
     "planilha .xlsx: patch nos bytes do ZIP, formato preservado"),
    ("teste_visualizadores.py",
     "views: hexadecimal e grade de CSV sobre a tabela de pecas"),
    ("teste_janela_principal.py",
     "abas, salvar como, arrastar-e-soltar, busca pela barra, log"),
]


def main() -> int:
    total_ok = total_falhas = 0
    quebradas: list[tuple[str, str]] = []

    ambiente = dict(os.environ)
    ambiente.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Sem isto, print de caractere acentuado quebra no console do Windows com
    # UnicodeEncodeError e a suite "falha" por um motivo que nao e' o dela.
    ambiente["PYTHONIOENCODING"] = "utf-8"
    ambiente["PYTHONPATH"] = RAIZ + os.pathsep + ambiente.get("PYTHONPATH", "")

    for arquivo, descricao in SUITES:
        caminho = os.path.join(AQUI, arquivo)
        if not os.path.isfile(caminho):
            print("%-24s AUSENTE  %s" % (arquivo, descricao))
            quebradas.append((arquivo, "arquivo de teste nao encontrado"))
            continue
        limite = LIMITE_PROPRIO_S.get(arquivo, LIMITE_POR_SUITE_S)
        try:
            proc = subprocess.run([sys.executable, "-u", caminho],
                                  capture_output=True, text=True,
                                  errors="replace", env=ambiente, cwd=RAIZ,
                                  timeout=limite)
        except subprocess.TimeoutExpired as expirou:
            parcial = (expirou.stdout or "") + (expirou.stderr or "")
            print("%-24s  TRAVOU apos %ds  [PROBLEMA]  %s"
                  % (arquivo, limite, descricao))
            quebradas.append((arquivo, "A SUITE TRAVOU (dialogo modal?)\n"
                              + parcial))
            continue
        saida = proc.stdout + proc.stderr
        ok = saida.count("\n  OK   ")
        falhas = saida.count("\n  FALHA")
        total_ok += ok
        total_falhas += falhas
        estado = ("pulado" if ("PULADO:" in saida and not ok and not falhas)
                  else ("ok" if proc.returncode == 0 else "PROBLEMA"))
        print("%-24s %3d ok  %d falhas  [%-8s]  %s"
              % (arquivo, ok, falhas, estado, descricao))
        if proc.returncode != 0:
            quebradas.append((arquivo, saida))

    print("-" * 74)
    print("TOTAL: %d verificacoes ok, %d falhas" % (total_ok, total_falhas))
    for arquivo, saida in quebradas:
        print("\n===== saida de %s =====" % arquivo)
        print(saida[-4000:])
    return 1 if (total_falhas or quebradas) else 0


if __name__ == "__main__":
    sys.exit(main())
