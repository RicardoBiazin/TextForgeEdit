"""Portugues do Brasil: nos textos deste programa E nos dialogos do Qt.

    .\\.venv\\Scripts\\python.exe tests\\teste_idioma.py

Dois defeitos relatados pelo usuario, e os dois estao guardados aqui:

1. **"A traducao nao esta' em todos os campos."** Os textos DESTE programa
   sempre estiveram em portugues; os dos dialogos PADRAO nao. "Save",
   "Discard", "Cancel", "Open" e os botoes de `QMessageBox` vem do Qt, e sem
   carregar o `qtbase_pt_BR.qm` eles aparecem em ingles no meio de uma janela em
   portugues.

2. **"Falta acentuacao e c-cedilha."** Os textos de interface foram escritos sem
   acento, por habito herdado da convencao ASCII dos comentarios. Comentario e
   log podem ser ASCII; o que o usuario LE, nao.

A varredura do fim e' o que impede a reincidencia: ela falha se alguem
acrescentar um texto de tela com "nao", "voce" ou "codificacao" sem acento.
"""

from __future__ import annotations

import re
import sys

from ajudantes import checa, checa_igual, preparar_qt, pular, resumir, secao

TEM_QT = preparar_qt()

RAIZ = __import__("pathlib").Path(__file__).resolve().parent.parent


def testar_catalogos() -> None:
    secao("Os catalogos do Qt")

    from tfedit import idioma

    pastas = idioma.pastas_de_traducao()
    checa(bool(pastas), f"ha' pasta de traducao: {[str(p) for p in pastas]}")
    achou = any((p / "qtbase_pt_BR.qm").is_file() for p in pastas)
    checa(achou, "*** e o qtbase_pt_BR.qm esta' la': e' ele que traduz os "
                 "botoes dos dialogos padrao ***")


def testar_botoes_padrao() -> None:
    secao("Os botoes dos dialogos padrao")

    from PySide6.QtWidgets import QApplication, QDialogButtonBox

    from tfedit import idioma

    aplicacao = QApplication.instance()
    carregados = idioma.instalar(aplicacao)
    checa("qtbase_pt_BR" in carregados,
          f"o catalogo entra: {carregados}")

    caixa = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save
        | QDialogButtonBox.StandardButton.Discard
        | QDialogButtonBox.StandardButton.Cancel
        | QDialogButtonBox.StandardButton.Open)
    textos = sorted(b.text().replace("&", "") for b in caixa.buttons())
    checa_igual(textos, ["Abrir", "Cancelar", "Descartar", "Salvar"],
                "*** Save/Discard/Cancel/Open saem em portugues -- era isto que "
                "aparecia em ingles no meio da janela ***")

    # O tradutor tem de continuar VIVO. Guardado numa variavel local, o coletor
    # do Python o destroi e os textos voltam ao ingles alguns segundos depois de
    # a janela abrir -- um sintoma que nao aponta para a causa.
    checa(bool(getattr(aplicacao, "_tradutores", None)),
          "*** e a referencia fica guardada na aplicacao, para o coletor nao "
          "levar a traducao embora ***")

    import gc
    gc.collect()
    caixa2 = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    checa_igual(caixa2.buttons()[0].text().replace("&", ""), "Cancelar",
                "e continua valendo depois de uma coleta de lixo")


def testar_locale() -> None:
    secao("A regiao")

    from PySide6.QtCore import QLocale

    padrao = QLocale()
    checa(padrao.language() == QLocale.Language.Portuguese,
          f"o idioma padrao e' portugues ({padrao.name()})")
    checa(padrao.territory() == QLocale.Country.Brazil,
          "e a regiao e' Brasil -- pt_PT tem outra ortografia e outro formato "
          "de numero")


def testar_textos_do_programa() -> None:
    secao("Os textos deste programa")

    from PySide6.QtWidgets import QApplication

    from tfedit.interface.janela_principal import JanelaPrincipal

    QApplication.instance()
    janela = JanelaPrincipal()

    rotulos = []
    for menu in janela.menuBar().actions():
        rotulos.append(menu.text())
        if menu.menu():
            rotulos.extend(a.text() for a in menu.menu().actions() if a.text())
    juntos = " | ".join(rotulos)

    for esperado in ("Pró&xima ocorrência", "Ocorrência &anterior",
                     "&Substituir...", "Salvar &como..."):
        checa(esperado in rotulos, f"menu com acento: {esperado!r}")

    checa("ocorrencia" not in juntos.lower().replace("ocorrência", ""),
          f"*** nenhum item de menu ficou sem acento: {juntos} ***")

    barra = janela.barra_busca
    checa_igual(barra.caixa_maiusculas.toolTip(),
                "Diferenciar maiúsculas de minúsculas", "dica com acento")
    checa_igual(barra.caixa_regex.toolTip(), "Expressão regular",
                "e o c-cedilha e o til aparecem")
    barra.campo.setText("[")
    barra.caixa_regex.setChecked(True)
    barra._procurar(False)
    checa_igual(barra.rotulo.text(), "expressão regular inválida",
                "*** e a mensagem de erro tambem ***")

    checa("licença" in janela.credito.toolTip().lower(),
          f"a dica do rodape: {janela.credito.toolTip()!r}")
    janela.close()


# ---------------------------------------------------------------------------
# A varredura que impede a reincidencia
# ---------------------------------------------------------------------------

#: Palavras que, num texto de TELA, estao necessariamente sem acento.
SEM_ACENTO = re.compile(
    r"\b(nao|voce|codificacao|gravacao|substituicao|substituida|substituidas|"
    r"ocorrencia|ocorrencias|expressao|invalida|invalido|possivel|licenca|"
    r"versao|versoes|memoria|espaco|atomica|temporario|alteracao|alteracoes|"
    r"maiusculas|minusculas|proxima|proximo|indice|conteudo|pendencia|"
    r"criterio|numero|ultima|ultimo|unica|unico|sera|serao|estao|"
    r"linha unica|ate)\b", re.IGNORECASE)

#: Chamadas que desenham texto na tela. So' elas sao varridas.
DESENHAM = ("setText(", "setToolTip(", "setPlaceholderText(", "showMessage(",
            "dizer(", "QMessageBox.about(", "QMessageBox.warning(",
            "QMessageBox.information(", "QMessageBox.question(")

#: Linhas ignoradas de proposito. Comentario, docstring e LOG podem ser ASCII:
#: a convencao do codigo e' essa, e acentua-los criaria ruido em diff sem o
#: usuario ver diferenca. O log so' e' lido por quem investiga um defeito.
IGNORAR = ("#", '"""', "log.", "logging.")

#: `{...}` sai antes da conferencia: dentro de uma f-string ele e' NOME DE
#: VARIAVEL, e nao texto. Sem isto, `{criterio.texto}` e `{VERSAO}` seriam
#: acusados de faltar acento em "criterio" e "versao" -- e a varredura viraria
#: ruido que se aprende a ignorar, que e' pior que nao ter varredura.
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _limpar(texto: str) -> str:
    return PLACEHOLDER.sub(" ", texto)


def testar_varredura_de_acentos() -> None:
    secao("Nenhum texto de tela sem acento (varredura do fonte)")

    suspeitos = []
    varridas = 0
    for arquivo in sorted((RAIZ / "tfedit").rglob("*.py")):
        linhas = arquivo.read_text(encoding="utf-8").splitlines()
        for numero, linha in enumerate(linhas, 1):
            enxuta = linha.lstrip()
            if any(enxuta.startswith(m) or m in enxuta for m in IGNORAR):
                continue
            vizinhas = "\n".join(linhas[max(0, numero - 4):numero + 1])
            if not any(marca in vizinhas for marca in DESENHAM):
                continue
            varridas += 1
            for texto in re.findall(r'"([^"]{5,})"', linha):
                if texto.startswith(("Ctrl", "Shift", "F3", "*.", "<h3>",
                                     "color:", "padding")):
                    continue
                achado = SEM_ACENTO.search(_limpar(texto))
                if achado:
                    suspeitos.append(
                        f"{arquivo.relative_to(RAIZ)}:{numero}: "
                        f"{achado.group(0)!r} em {texto[:55]!r}")

    checa(varridas > 20,
          f"a varredura de fato olhou o codigo ({varridas} linhas de tela)")
    checa(not suspeitos,
          "*** nenhum texto de tela com palavra sem acento ***"
          + ("".join(f"\n         {s}" for s in suspeitos) if suspeitos else ""))


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")
    testar_catalogos()
    testar_botoes_padrao()
    testar_locale()
    testar_textos_do_programa()
    testar_varredura_de_acentos()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
