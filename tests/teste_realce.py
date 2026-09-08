"""Realce de sintaxe sobre uma FATIA, e nao sobre o arquivo inteiro.

    .\\.venv\\Scripts\\python.exe tests\\teste_realce.py

O motor de realce veio do TextForge quase intacto -- o `Pintor`, as regras e os
24 provedores de linguagem. O que NAO veio de graca e' o ponto em que os dois
programas diferem:

    no TextForge o `QTextDocument` tem o ARQUIVO;
    aqui ele tem uma FATIA de 5000 linhas tirada do meio de um arquivo de 1 GB.

O `QSyntaxHighlighter` comeca o bloco 0 no contexto inicial da linguagem. No
TextForge isso esta' certo por construcao. Aqui, uma fatia que caia dentro de um
`/* comentario */` aberto 3000 linhas antes seria pintada como CODIGO -- e o
usuario veria cores erradas justamente no trecho que foi ler.

A correcao e' a `pilha_inicial` do `Pintor`, semeada por `simular()` sobre as
linhas anteriores a fatia. `testar_semente_de_contexto` e' o teste central
desta suite: ele nao verifica so' que o realce funciona, verifica que a semente
MUDA o resultado -- sem essa contraprova, o teste passaria com a semente
desligada e nao guardaria nada.
"""

from __future__ import annotations

import sys

from ajudantes import (checa, checa_igual, pasta_temporaria, preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()


def _abrir(pasta, nome: str, texto: str, **cfg):
    """Uma aba pronta sobre um arquivo recem-escrito."""
    from tfedit.interface.aba import Aba

    alvo = pasta / nome
    alvo.write_text(texto, encoding="utf-8")
    return Aba(alvo, {"linhas_da_janela": 100, **cfg})


def _cores_do_bloco(aba, numero: int) -> list[tuple[int, int, str]]:
    """(inicio, tamanho, cor) de cada trecho pintado do bloco."""
    bloco = aba.editor.document().findBlockByNumber(numero)
    return [(f.start, f.length, f.format.foreground().color().name())
            for f in bloco.layout().formats()]


# ======================================================================
# O motor, portado
# ======================================================================

def testar_registro_de_linguagens() -> None:
    secao("Os provedores que vieram do TextForge")

    from tfedit import linguagens
    from tfedit.linguagens.registro import REGISTRO

    quantos = linguagens.carregar_embutidos()
    nomes = REGISTRO.nomes()
    checa(quantos >= 20, f"carregou {quantos} provedores")
    for esperado in ("Python", "JavaScript", "SQL", "XML", "JSON", "CSV"):
        checa(esperado in nomes, f"conhece {esperado}")

    prov = REGISTRO.por_caminho("relatorio.sql")
    checa(prov is not None and prov.nome == "SQL",
          "resolve a linguagem pela extensao (.sql -> SQL)")


def testar_sem_dependencia_do_textforge() -> None:
    secao("O porte nao deixou import pendurado")

    import pathlib
    raiz = pathlib.Path(__file__).resolve().parent.parent / "tfedit"
    pendentes = []
    for arquivo in sorted(raiz.rglob("*.py")):
        for numero, linha in enumerate(
                arquivo.read_text(encoding="utf-8").splitlines(), 1):
            nu = linha.strip()
            if nu.startswith(("import textforge", "from textforge")):
                pendentes.append(f"{arquivo.name}:{numero}: {nu}")

    # Um `import textforge` sobrevivente so' quebraria NA MAQUINA DE QUEM NAO
    # TEM o TextForge instalado ao lado -- aqui ele importaria em silencio.
    checa(not pendentes,
          "*** nenhum modulo ainda importa `textforge` ***"
          + "".join(f"\n         {p}" for p in pendentes))


def testar_temas_embutidos() -> None:
    secao("Os temas")

    from tfedit import recursos, tema

    for nome in ("claro", "escuro"):
        arquivo = recursos.caminho("temas", f"{nome}.json")
        checa(arquivo.is_file(), f"o tema {nome} existe em recursos/")
        t = tema.embutido(nome)
        checa_igual(t.tipo, nome, f"o tema {nome} se declara {nome}")
        # "Emergencia" e' o nome do tema de fallback em codigo. Ver
        # `tema.embutido`: se o JSON some, o programa abre sem realce nenhum.
        checa(t.nome != "Emergencia",
              f"o {nome} veio do JSON, e nao das cores de emergencia")

    cor = tema.embutido("escuro").formato("comentario").foreground().color()
    checa(cor.isValid(), "o papel 'comentario' tem cor no tema escuro")


def testar_spec_leva_os_temas() -> None:
    secao("O .exe leva os temas")

    import pathlib
    spec = (pathlib.Path(__file__).resolve().parent.parent
            / "TextForgeEdit.spec").read_text(encoding="utf-8")
    # Sem esta linha o realce funciona no fonte e some no executavel -- um
    # defeito que so' aparece depois de empacotar.
    checa("tfedit/recursos/temas" in spec,
          "*** o .spec declara tfedit/recursos/temas nos datas ***")


# ======================================================================
# O realce na fatia
# ======================================================================

def testar_realce_basico() -> None:
    secao("Um arquivo Python sai colorido")

    with pasta_temporaria() as pasta:
        aba = _abrir(pasta, "exemplo.py",
                     'def f():\n    return 42  # comentario\n' * 30)
        checa_igual(aba.nome_da_linguagem, "Python",
                    "a aba detectou a linguagem pela extensao")

        cores = _cores_do_bloco(aba, 1)          # a linha do `return`
        checa(len(cores) >= 3,
              f"a linha do return tem varios papeis ({len(cores)})")
        distintas = {c for _, _, c in cores}
        checa(len(distintas) >= 2,
              f"e as cores de fato variam ({len(distintas)} distintas)")


def testar_deteccao_por_conteudo() -> None:
    secao("Um arquivo sem extensao util")

    with pasta_temporaria() as pasta:
        aba = _abrir(pasta, "roteiro", "#!/bin/bash\necho oi\n" * 20)
        checa(aba.nome_da_linguagem in ("Shell", "Texto"),
              f"sem extensao, o palpite veio do conteudo: "
              f"{aba.nome_da_linguagem}")


def testar_semente_de_contexto() -> None:
    secao("*** A fatia que comeca DENTRO de um comentario ***")

    with pasta_temporaria() as pasta:
        linhas = (["int x = 1;"] * 200
                  + ["/* abre o comentario"]
                  + ["ainda dentro do comentario, com int e return"] * 300
                  + ["*/", "int y = 2;"])
        aba = _abrir(pasta, "grande.c", "\n".join(linhas) + "\n")
        checa_igual(aba.nome_da_linguagem, "C", "arquivo .c")

        aba.editor.recarregar(400)              # bem dentro do comentario
        recorte = aba.janela.recorte
        checa(200 < recorte.primeira_linha < 500,
              f"a fatia comeca na linha {recorte.primeira_linha}, longe do "
              f"inicio do arquivo -- e' o caso que interessa")

        anteriores = aba.janela.linhas_antes_da_fatia()
        checa(len(anteriores) == aba.janela.LINHAS_DE_CONTEXTO,
              f"leu {len(anteriores)} linhas de contexto (o teto e' "
              f"{aba.janela.LINHAS_DE_CONTEXTO}, e nao o arquivo inteiro)")

        pintor = aba.editor.pintor
        checa(pintor.pilha_inicial is not None
              and "comentario" in pintor.pilha_inicial[-1],
              f"a semente reconheceu o comentario aberto: "
              f"{pintor.pilha_inicial}")

        cor_comentario = aba.editor.tema.formato(
            "comentario").foreground().color().name()
        com = _cores_do_bloco(aba, 0)
        checa(com and all(c == cor_comentario for _, _, c in com),
              "*** COM a semente, a primeira linha da fatia e' comentario "
              "inteiro ***")

        # A CONTRAPROVA. Sem ela este teste passaria com a semente desligada.
        pintor.pilha_inicial = None
        pintor.rehighlight()
        sem = _cores_do_bloco(aba, 0)
        checa(com != sem,
              "*** e SEM a semente o resultado muda -- a semente esta' "
              "fazendo efeito, e nao acompanhando ***")
        checa(any(c != cor_comentario for _, _, c in sem),
              "sem a semente, o texto do comentario sairia pintado como codigo")


def testar_semente_no_inicio_do_arquivo() -> None:
    secao("A fatia que comeca no byte 0 nao e' semeada")

    with pasta_temporaria() as pasta:
        aba = _abrir(pasta, "curto.py", "x = 1\n" * 10)
        checa_igual(aba.janela.recorte.primeira_linha, 0,
                    "arquivo curto: a fatia e' o arquivo")
        checa_igual(aba.janela.linhas_antes_da_fatia(), [],
                    "nao ha' linhas anteriores para ler")
        checa(aba.editor.pintor.pilha_inicial is None,
              "e a semente fica em None -- o contexto inicial da linguagem "
              "esta' certo aqui")


def testar_deslizar_resemeia() -> None:
    secao("Deslizar recalcula a semente")

    with pasta_temporaria() as pasta:
        linhas = (["/* comeca comentado"] + ["dentro"] * 400
                  + ["*/"] + ["int fora = 1;"] * 200)
        aba = _abrir(pasta, "desliza.c", "\n".join(linhas) + "\n")

        aba.editor.recarregar(200)              # dentro do comentario
        dentro = aba.editor.pintor.pilha_inicial
        checa(dentro is not None and "comentario" in dentro[-1],
              f"na linha 200 a semente diz comentario: {dentro}")

        aba.editor.recarregar(550)              # depois do fechamento
        fora = aba.editor.pintor.pilha_inicial
        checa(fora is None or "comentario" not in fora[-1],
              f"na linha 550 a semente ja' NAO diz comentario: {fora}")


def testar_trocar_de_linguagem() -> None:
    secao("Trocar a linguagem pela mao")

    from tfedit import linguagens
    from tfedit.linguagens.registro import REGISTRO

    linguagens.carregar_embutidos()
    with pasta_temporaria() as pasta:
        aba = _abrir(pasta, "dados.txt", "SELECT * FROM tabela;\n" * 20)
        checa_igual(aba.nome_da_linguagem, "Texto", "abriu como texto")

        aba.definir_linguagem(REGISTRO.por_nome("SQL"))
        checa_igual(aba.nome_da_linguagem, "SQL", "trocou para SQL")
        cores = _cores_do_bloco(aba, 0)
        checa(len({c for _, _, c in cores}) >= 2,
              f"e a linha repintou com mais de uma cor ({len(cores)} trechos)")


def testar_simular_nao_pinta() -> None:
    secao("simular() nao chama setFormat")

    from tfedit import linguagens, tema
    from tfedit.linguagens.registro import REGISTRO
    from tfedit.realce.pintor import Pintor
    from PySide6.QtGui import QTextDocument

    linguagens.carregar_embutidos()
    doc = QTextDocument()
    pintor = Pintor(doc, REGISTRO.por_nome("C"), tema.embutido("escuro"))

    # Fora de `highlightBlock`, `setFormat` e' invalido. Se `simular` o
    # chamasse, isto quebraria ou pintaria o documento errado.
    pilha = pintor.simular(["/* abre", "meio", "ainda"])
    checa(pilha and "comentario" in pilha[-1],
          f"a simulacao seguiu o comentario ate' o fim: {pilha}")
    checa_igual(doc.toPlainText(), "",
              "e o documento continua vazio -- nada foi pintado")

    fechada = pintor.simular(["/* abre", "fecha */", "int x;"])
    checa(fechada and "comentario" not in fechada[-1],
          f"e o fechamento volta ao contexto de codigo: {fechada}")


def testar_linha_gigante() -> None:
    secao("Uma linha gigante nao trava a simulacao")

    from tfedit import linguagens, tema
    from tfedit.linguagens.registro import REGISTRO
    from tfedit.realce.pintor import Pintor
    from PySide6.QtGui import QTextDocument

    linguagens.carregar_embutidos()
    pintor = Pintor(QTextDocument(), REGISTRO.por_nome("JavaScript"),
                    tema.embutido("escuro"))
    gigante = "var x = " + ("'a' + " * 20000) + "'fim';"
    checa(len(gigante) > pintor.limite_por_linha,
          f"a linha de teste ({len(gigante)} caracteres) passa do limite de "
          f"{pintor.limite_por_linha}")

    import time
    inicio = time.monotonic()
    pintor.simular([gigante])
    gasto = time.monotonic() - inicio
    checa(gasto < 1.0,
          f"a simulacao pulou a linha gigante em {gasto * 1000:.0f} ms "
          f"(um JSON minificado nao pode travar a rolagem)")


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_registro_de_linguagens()
    testar_sem_dependencia_do_textforge()
    testar_temas_embutidos()
    testar_spec_leva_os_temas()
    testar_realce_basico()
    testar_deteccao_por_conteudo()
    testar_semente_de_contexto()
    testar_semente_no_inicio_do_arquivo()
    testar_deslizar_resemeia()
    testar_trocar_de_linguagem()
    testar_simular_nao_pinta()
    testar_linha_gigante()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
