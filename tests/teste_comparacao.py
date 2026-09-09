"""Comparar dois arquivos sem carregar nenhum dos dois.

    .\\.venv\\Scripts\\python.exe tests\\teste_comparacao.py

O TESTE CENTRAL É `testar_muitas_diferencas_e_rapido`, e ele guarda a medição
que obrigou a trocar de algoritmo.

Com `difflib.SequenceMatcher` puro, dois arquivos de 200 mil linhas com uma
mudança a cada dez -- duas versões de um export, 10% das linhas alteradas --
passavam de DOIS MINUTOS. A curva medida:

     5 mil linhas   0,24 s
    10 mil linhas   0,96 s      (4x)
    20 mil linhas   4,63 s      (4,8x)
    40 mil linhas  27,94 s      (6x)

Dobrar o tamanho quintuplicava o tempo. A saída foi ancorar nas linhas ÚNICAS,
como o diff de paciência do git: o mesmo caso passou a 0,54 s.

`testar_alinhamento_e_valido` é a outra metade: velocidade sem correção não
vale nada. Ele sorteia milhares de pares e exige que todo bloco marcado como
IGUAL seja mesmo igual, e que os blocos cubram os dois arquivos sem buraco.
"""

from __future__ import annotations

import random
import sys
import time
from array import array

from ajudantes import (checa, checa_igual, memoria_privada_mb,
                       pasta_temporaria, preparar_qt, pular, resumir, secao)

TEM_QT = preparar_qt()

from tfedit import comparacao as C           # noqa: E402 - depois do preparar


def _documento(pasta, nome: str, linhas, eol: bytes = b"\r\n"):
    from tfedit.original import Original
    from tfedit.pecas import Documento

    alvo = pasta / nome
    alvo.write_bytes(eol.join(l.encode("utf-8") for l in linhas) + eol)
    original = Original(alvo)
    original.indexar()
    return original, Documento(original)


# ======================================================================
# O algoritmo
# ======================================================================

def testar_alinhamento_e_valido() -> None:
    secao("*** O alinhamento é válido, e não só rápido ***")

    random.seed(20260909)
    problemas = []
    for _ in range(2000):
        alfabeto = random.randint(1, 6)
        a = array("q", [random.randint(1, alfabeto)
                        for _ in range(random.randint(0, 40))])
        b = array("q", [random.randint(1, alfabeto)
                        for _ in range(random.randint(0, 40))])

        blocos: list = []
        C._blocos(a, b, 0, len(a), 0, len(b), blocos)

        ia = ib = 0
        for tag, i1, i2, j1, j2 in blocos:
            if i1 != ia or j1 != ib:
                problemas.append(f"buraco em {tag} {i1},{j1} após {ia},{ib}")
                break
            if tag == "equal" and list(a[i1:i2]) != list(b[j1:j2]):
                problemas.append("bloco 'igual' que não é igual")
                break
            ia, ib = i2, j2
        else:
            if ia != len(a) or ib != len(b):
                problemas.append(f"não cobriu tudo: {ia}/{len(a)}, "
                                 f"{ib}/{len(b)}")

    checa(not problemas,
          "*** 2000 pares sorteados: todo bloco IGUAL é mesmo igual, e os "
          "blocos cobrem os dois arquivos sem buraco ***"
          + "".join(f"\n         {p}" for p in problemas[:3]))


def testar_muitas_diferencas_e_rapido() -> None:
    secao("*** 10% das linhas mudadas em 200 mil: era mais de 2 min ***")

    with pasta_temporaria() as pasta:
        normais = [f"linha {i:06d} conteudo do registro" for i in range(200_000)]
        mudadas = [f"linha {i:06d} MUDOU neste arquivo" if i % 10 == 0
                   else normais[i] for i in range(200_000)]

        oa, da = _documento(pasta, "a.txt", normais)
        ob, db = _documento(pasta, "b.txt", mudadas)
        try:
            antes = memoria_privada_mb()
            inicio = time.monotonic()
            comp = C.comparar(da, db, teto=0)
            gasto = time.monotonic() - inicio
            pico = memoria_privada_mb() - antes

            checa_igual(comp.resumo.alteradas, 20_000,
                        "as 20 mil linhas alteradas foram achadas")
            checa(gasto < 20,
                  f"*** e em {gasto:.2f} s: com o difflib puro isto passava "
                  f"de 120 s ***")
            checa(pico < 200,
                  f"*** com {pico:.0f} MB, e não os 100+ MB que guardar as "
                  f"linhas custaria ***")
        finally:
            oa.fechar()
            ob.fechar()


def testar_arquivos_iguais_dao_um_bloco() -> None:
    secao("*** Dois arquivos iguais: UM bloco, e nenhuma linha alinhada ***")

    with pasta_temporaria() as pasta:
        linhas = [f"registro {i:06d}" for i in range(100_000)]
        oa, da = _documento(pasta, "x.txt", linhas)
        ob, db = _documento(pasta, "y.txt", linhas)
        try:
            comp = C.comparar(da, db, teto=0)
            checa_igual(comp.resumo.diferencas, 0, "nenhuma diferença")
            checa_igual(len(comp.opcodes), 1,
                        "*** e UM bloco só: guardar 100 mil pares alinhados "
                        "seria guardar o que a tela nunca mostra de uma vez ***")
            checa_igual(comp.total_exibido, 100_001,
                        "mas a tela sabe que há 100 mil linhas para rolar")
            checa("iguais" in comp.resumo.descrever(),
                  f"e o resumo diz isso: {comp.resumo.descrever()!r}")
        finally:
            oa.fechar()
            ob.fechar()


def testar_linhas_repetidas_nao_travam() -> None:
    secao("*** Um arquivo sem linha única não volta a ser quadrático ***")

    with pasta_temporaria() as pasta:
        # Metade das linhas idênticas entre si: não há âncora possível nesses
        # trechos. É o caso patológico que `LIMITE_SEM_ANCORA` contém.
        a = ["REPETIDA" if i % 2 else f"unica {i}" for i in range(60_000)]
        b = ["REPETIDA" if i % 2 else f"unica {i}" for i in range(60_000)]
        b[30_000] = "AQUI MUDOU"

        oa, da = _documento(pasta, "r1.txt", a)
        ob, db = _documento(pasta, "r2.txt", b)
        try:
            inicio = time.monotonic()
            comp = C.comparar(da, db, teto=0)
            gasto = time.monotonic() - inicio
            checa(gasto < 20,
                  f"*** {gasto:.2f} s mesmo com metade das linhas repetidas ***")
            checa(comp.resumo.diferencas >= 1,
                  f"e a diferença foi vista ({comp.resumo.diferencas})")
        finally:
            oa.fechar()
            ob.fechar()


def testar_teto_recusa() -> None:
    secao("*** Acima do teto, RECUSA em vez de travar ***")

    with pasta_temporaria() as pasta:
        oa, da = _documento(pasta, "p.txt", [f"l {i}" for i in range(200)])
        ob, db = _documento(pasta, "q.txt", [f"l {i}" for i in range(200)])
        try:
            levantou = False
            try:
                C.comparar(da, db, teto=50)
            except C.GrandeDemais as exc:
                levantou = True
                checa("limite" in str(exc),
                      f"e a mensagem explica: {str(exc)[:60]}…")
            checa(levantou,
                  "*** acima do teto a comparação NÃO começa: travar a janela "
                  "é pior que dizer que não dá ***")
            comp = C.comparar(da, db, teto=1000)
            checa(comp is not None, "abaixo do teto, compara normalmente")
        finally:
            oa.fechar()
            ob.fechar()


def testar_fim_de_linha_nao_conta() -> None:
    secao("*** CRLF contra LF não é diferença ***")

    with pasta_temporaria() as pasta:
        linhas = [f"linha {i}" for i in range(50)]
        oa, da = _documento(pasta, "crlf.txt", linhas, eol=b"\r\n")
        ob, db = _documento(pasta, "lf.txt", linhas, eol=b"\n")
        try:
            comp = C.comparar(da, db, teto=0)
            checa_igual(comp.resumo.diferencas, 0,
                        "*** os dois são iguais: quem quer ver o terminador "
                        "usa o visualizador hexadecimal ***")
        finally:
            oa.fechar()
            ob.fechar()


# ======================================================================
# A janela
# ======================================================================

def testar_janela_lado_a_lado() -> None:
    secao("*** A janela: alinhamento e leitura sob demanda ***")

    from tfedit import configuracao
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as pasta:
        a = pasta / "antes.csv"
        b = pasta / "depois.csv"
        a.write_bytes(b"nome;valor\r\nAna;100\r\nBruno;200\r\nElena;500\r\n")
        b.write_bytes(b"nome;valor\r\nAna;100\r\nBruno;250\r\nElena;500\r\n")

        janela = JanelaPrincipal(configuracao.padrao())
        try:
            checa(janela.comparar(a, b), "a comparação abriu")
            comparacao = janela._comparacoes[-1]
            comp = comparacao.comp
            checa_igual(comp.resumo.alteradas, 1, "uma linha alterada")

            pares = comp.faixa(0, comp.total_exibido)
            tipos = [p.tipo for p in pares]
            checa_igual(tipos.count(C.ALTERADA), 1,
                        "*** e a tela mostra UMA linha marcada ***")
            checa(all(p.linha_a == p.linha_b for p in pares),
                  "os dois lados ficam alinhados linha a linha")

            # A pintura lê sob demanda: instrumenta `faixa` do documento.
            paineis = comparacao.paineis
            paineis.resize(900, 400)
            paineis.show()
            pedidas = [0]
            original = paineis.doc_a.faixa

            def espiar(x, y):
                resultado = original(x, y)
                pedidas[0] += len(resultado)
                return resultado

            paineis.doc_a.faixa = espiar
            try:
                paineis.viewport().grab()
            finally:
                paineis.doc_a.faixa = original
            checa(0 < pedidas[0] <= 60,
                  f"*** a pintura pediu {pedidas[0]} linhas -- uma tela, e "
                  f"numa leitura só por painel ***")
        finally:
            janela.close()


def testar_mesmo_arquivo_e_recusado() -> None:
    secao("Comparar um arquivo com ele mesmo")

    from tfedit import configuracao
    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as pasta:
        alvo = pasta / "so_um.txt"
        alvo.write_bytes(b"linha\r\n" * 10)
        janela = JanelaPrincipal(configuracao.padrao())
        try:
            checa(not janela.comparar(alvo, alvo),
                  "*** recusado: comparar um arquivo consigo mesmo só "
                  "gastaria dois mmap para dizer 'são iguais' ***")
            checa("mesmo arquivo" in janela.barra.currentMessage(),
                  f"e diz por quê: {janela.barra.currentMessage()!r}")
        finally:
            janela.close()


def testar_botao_da_barra_existe_agora() -> None:
    secao("*** O botão Comparar entra na barra agora que o comando existe ***")

    from tfedit import configuracao
    from tfedit.interface.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(configuracao.padrao())
    try:
        oferecidos = dict(janela.botoes_da_barra())
        checa("comparar" in oferecidos,
              "*** ele passa a ser oferecido na tela de Configurações ***")
        checa("comparar" in configuracao.padrao()["botoes_da_barra"],
              "e volta ao padrão de fábrica, agora que faz alguma coisa")
        rotulos = [a.text() for a in janela.barra_atalhos.actions()
                   if not a.isSeparator()]
        checa("Comparar arquivos" in rotulos,
              f"e aparece na barra: {rotulos[-3:]}")
    finally:
        janela.close()


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_alinhamento_e_valido()
    testar_arquivos_iguais_dao_um_bloco()
    testar_fim_de_linha_nao_conta()
    testar_teto_recusa()
    testar_linhas_repetidas_nao_travam()
    testar_muitas_diferencas_e_rapido()
    testar_janela_lado_a_lado()
    testar_mesmo_arquivo_e_recusado()
    testar_botao_da_barra_existe_agora()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
