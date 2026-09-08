"""Planilhas .xlsx: abrir, editar uma celula e gravar sem estragar o resto.

    .\\.venv\\Scripts\\python.exe tests\\teste_planilha.py

Um .xlsx nao e' texto -- e' um ZIP de XML. A aba que abre uma planilha nao cria
mmap, indice nem tabela de pecas (ver `interface/aba.py`), e a fonte da verdade
e' a `Pasta`, ja' inteira na memoria.

O QUE ESTA SUITE GUARDA:

1. **Abrir e salvar sem editar devolve o arquivo BYTE A BYTE.** E' o mesmo
   principio da gravacao por streaming, um formato acima: o que ninguem tocou
   sai como entrou. Uma planilha regravada do zero perderia formatacao,
   graficos e tabelas dinamicas -- e o Excel costuma abrir assim mesmo, sem
   avisar que o arquivo empobreceu.

2. **Editar uma celula preserva o FORMATO dela.** O atributo `s` de uma celula
   aponta para o estilo (data, moeda, cor). Reescrever a celula sem ele
   transformaria "R$ 1.234,56" num numero solto.

3. **O teto de tamanho e' conferido ANTES de ler.** A pasta inteira vai para a
   memoria; descobrir que ela nao cabia depois de le-la e' o pior momento
   possivel.
"""

from __future__ import annotations

import sys
import zipfile

from ajudantes import (checa, checa_igual, pasta_temporaria, preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()

try:
    import openpyxl
    TEM_OPENPYXL = True
except ImportError:
    TEM_OPENPYXL = False


def _criar(pasta, nome: str = "vendas.xlsx", linhas: int = 20):
    """Uma planilha de duas abas, com uma coluna formatada como moeda."""
    alvo = pasta / nome
    livro = openpyxl.Workbook()
    folha = livro.active
    folha.title = "Vendas"
    folha.append(["produto", "quantidade", "preco"])
    for i in range(linhas):
        folha.append([f"Item {i}", i, i * 1.5])
        # O formato e' o que se perde quando se reescreve a celula inteira.
        folha.cell(row=i + 2, column=3).number_format = 'R$ #,##0.00'
    resumo = livro.create_sheet("Resumo")
    resumo.append(["total", linhas * 10])
    livro.save(alvo)
    return alvo


def _abrir(pasta, alvo):
    from tfedit.interface.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal({})
    janela.abrir_arquivo(str(alvo))
    return janela


def _encerrar(janela) -> None:
    for aba in janela.todas_as_abas():
        janela.abas.removeTab(janela.abas.indexOf(aba))
        aba.encerrar()
    janela.close()


# ======================================================================

def testar_abre_como_planilha() -> None:
    secao("Uma aba de planilha nao tem editor de texto")

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        janela = _abrir(pasta, alvo)
        try:
            aba = janela.aba_atual
            checa(aba.e_planilha, "a aba se declara planilha")
            checa(aba.editor is None,
                  "*** e NAO tem editor: um ZIP nao e' texto ***")
            checa(aba.documento is None and aba.original is None,
                  "*** nem mmap, nem tabela de pecas: nao ha' linhas para "
                  "indexar num pacote ZIP ***")
            checa_igual(aba.view_atual(), "planilha", "abre direto na grade")
            checa_igual([f.nome for f in aba.planilha.folhas],
                        ["Vendas", "Resumo"], "as duas abas da pasta")
        finally:
            _encerrar(janela)


def testar_grade_le_os_valores() -> None:
    secao("A grade mostra o conteudo")

    from PySide6.QtCore import Qt

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        janela = _abrir(pasta, alvo)
        try:
            grade = janela.aba_atual.view("planilha")
            modelo = grade.tabela.model()
            checa_igual(modelo.data(modelo.index(0, 0)), "produto",
                        "A1 tras o cabecalho da planilha")
            checa_igual(modelo.data(modelo.index(1, 0)), "Item 0",
                        "A2 tras o primeiro item")
            checa_igual(
                [modelo.headerData(c, Qt.Orientation.Horizontal)
                 for c in range(3)],
                ["A", "B", "C"], "as colunas sao A, B, C como no Excel")
            checa(modelo.rowCount() > 20,
                  f"e sobram linhas em branco para digitar "
                  f"({modelo.rowCount()})")
        finally:
            _encerrar(janela)


def testar_salvar_sem_editar_e_identico() -> None:
    secao("*** Abrir e salvar sem editar devolve o arquivo INTACTO ***")

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        antes = alvo.read_bytes()
        janela = _abrir(pasta, alvo)
        try:
            aba = janela.aba_atual
            checa(not aba.modificado, "so' abrir nao suja a planilha")
            checa_igual(aba.salvar(), 0,
                        "*** salvar e' no-op quando nada mudou ***")
            checa_igual(alvo.read_bytes(), antes,
                        "*** e o arquivo continua byte a byte igual ***")
        finally:
            _encerrar(janela)


def testar_editar_celula_preserva_o_resto() -> None:
    secao("*** Editar uma celula nao reescreve a planilha ***")

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        antes = alvo.read_bytes()
        janela = _abrir(pasta, alvo)
        try:
            aba = janela.aba_atual
            modelo = aba.view("planilha").tabela.model()

            checa(modelo.setData(modelo.index(1, 0), "TROCADO"),
                  "a celula A2 aceitou o valor")
            checa(aba.modificado, "e a aba ficou marcada como alterada")
            escritos = aba.salvar()
            checa(escritos > 0, f"gravou {escritos} bytes")
            checa(alvo.read_bytes() != antes, "o arquivo mudou")

            livro = openpyxl.load_workbook(alvo)
            folha = livro["Vendas"]
            checa_igual(folha["A2"].value, "TROCADO",
                        "*** o Excel le' o valor novo ***")
            checa_igual(folha["B2"].value, 0,
                        "e a celula vizinha continua a mesma")
            checa_igual(livro.sheetnames, ["Vendas", "Resumo"],
                        "*** a segunda aba sobreviveu ***")
            checa_igual(folha["C2"].number_format, 'R$ #,##0.00',
                        "*** e o FORMATO de moeda da coluna C sobreviveu: "
                        "reescrever a celula sem o atributo de estilo "
                        "transformaria a moeda num numero solto ***")
        finally:
            _encerrar(janela)


def testar_gravacao_e_um_patch_do_zip() -> None:
    secao("*** A gravacao remonta o ZIP, e nao a planilha ***")

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        with zipfile.ZipFile(alvo) as pacote:
            partes_antes = [i.filename for i in pacote.infolist()]

        janela = _abrir(pasta, alvo)
        try:
            aba = janela.aba_atual
            modelo = aba.view("planilha").tabela.model()
            modelo.setData(modelo.index(1, 0), "X")
            aba.salvar()
        finally:
            _encerrar(janela)

        with zipfile.ZipFile(alvo) as pacote:
            partes_depois = [i.filename for i in pacote.infolist()]
        # `calcChain.xml` some de proposito quando uma formula e' tocada; nesta
        # planilha nao ha' formula, entao nada pode ter sumido.
        checa_igual(partes_depois, partes_antes,
                    "*** as partes do pacote continuam as mesmas, e na mesma "
                    "ordem: o Excel espera [Content_Types].xml primeiro ***")


def testar_arquivo_grande_demais_abre_como_texto() -> None:
    secao("*** Acima do teto, abre como arquivo comum -- e nao falha ***")

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        from tfedit.interface.janela_principal import JanelaPrincipal

        # Teto zero: qualquer planilha passa dele. O caminho exercitado e' o
        # mesmo de um .xlsx de 200 MB, sem precisar gerar 200 MB.
        janela = JanelaPrincipal({"limite_planilha_mb": 0})
        try:
            checa(janela.abrir_arquivo(str(alvo)),
                  "o arquivo abre mesmo assim")
            aba = janela.aba_atual
            checa(not aba.e_planilha,
                  "*** acima do teto NAO vira planilha ***")
            checa(aba.documento is not None,
                  "*** e volta para o caminho normal, onde as garantias de "
                  "memoria do editor valem ***")
            checa(getattr(aba, "planilha_grande_demais", 0) > 0,
                  "e a aba registra o motivo")
        finally:
            _encerrar(janela)


def testar_zip_renomeado_e_recusado() -> None:
    secao("*** Um .zip com extensao .xlsx nao vira planilha ***")

    from tfedit.interface.aba import Aba, NaoEPlanilha
    from tfedit.planilha import deteccao

    with pasta_temporaria() as pasta:
        falso = pasta / "mentira.xlsx"
        with zipfile.ZipFile(falso, "w") as pacote:
            pacote.writestr("qualquer.txt", "nao sou uma planilha")

        checa(not deteccao.parece_planilha(falso.read_bytes()),
              "*** a deteccao olha o CONTEUDO, e nao a extensao ***")

        levantou = False
        try:
            Aba(falso, {})
        except NaoEPlanilha:
            levantou = True
        except Exception as exc:                # noqa: BLE001
            checa(False, f"levantou o errado: {exc.__class__.__name__}")
        checa(levantou, "e a aba recusa com um erro proprio, que a janela sabe "
                        "tratar abrindo como arquivo comum")


def testar_menu_so_oferece_a_planilha() -> None:
    secao("O menu Visualizar numa planilha")

    from PySide6.QtWidgets import QMenu

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        janela = _abrir(pasta, alvo)
        try:
            menu = QMenu()
            janela._preencher_view(menu)
            rotulos = [a.text() for a in menu.actions()]
            checa_igual(rotulos, ["Planilha"],
                        "*** so' a grade: as outras views leem da tabela de "
                        "pecas, que aqui nao existe ***")
        finally:
            _encerrar(janela)


def testar_comando_de_texto_nao_quebra() -> None:
    secao("*** Um comando de texto numa planilha explica, e nao levanta ***")

    from tfedit import busca

    with pasta_temporaria() as pasta:
        alvo = _criar(pasta)
        janela = _abrir(pasta, alvo)
        try:
            aba = janela.aba_atual
            # Nenhum destes pode tocar em `aba.editor`, que e' None.
            janela._no_editor("paste")
            janela.ir_para_linha()
            janela._procurar(busca.Criterio("Item"), False)
            janela._mostrar_posicao(1, 2)
            checa(True, "*** colar, ir-para-linha, buscar e a barra de status "
                        "atravessam uma aba sem editor sem levantar ***")
            checa("Célula C2" in janela.rotulo_posicao.text(),
                  f"e a posicao vira a CELULA: "
                  f"{janela.rotulo_posicao.text()!r}")
            checa(not aba.modificado,
                  "*** e nada disso alterou a planilha ***")
        finally:
            _encerrar(janela)


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")
    if not TEM_OPENPYXL:
        return pular("openpyxl nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_abre_como_planilha()
    testar_grade_le_os_valores()
    testar_salvar_sem_editar_e_identico()
    testar_editar_celula_preserva_o_resto()
    testar_gravacao_e_um_patch_do_zip()
    testar_arquivo_grande_demais_abre_como_texto()
    testar_zip_renomeado_e_recusado()
    testar_menu_so_oferece_a_planilha()
    testar_comando_de_texto_nao_quebra()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
