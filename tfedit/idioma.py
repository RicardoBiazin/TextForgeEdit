"""Portugues do Brasil nos dialogos do proprio Qt.

Os textos DESTE programa sempre estiveram em portugues. Os dos dialogos padrao
NAO: "Save", "Discard", "Cancel", "Open", "Look in", "File name" e os botoes de
`QMessageBox` vem do Qt, e sem carregar a traducao eles aparecem em ingles no
meio de uma janela em portugues. Foi assim que o usuario encontrou o problema --
"a traducao nao esta' em todos os campos".

O `qtbase_pt_BR.qm` acompanha o PySide6 e cobre os widgets basicos. Ele e'
procurado em dois lugares, e a ordem importa:

  1. ao lado do executavel congelado (`sys._MEIPASS`), onde o PyInstaller o
     coloca -- ver `datas` no `.spec`;
  2. na instalacao do PySide6, que e' onde ele esta' rodando do fonte.

Falhar em carregar NAO e' erro: o programa continua, so' que com os botoes dos
dialogos em ingles. Deixar o editor de fora do ar por causa de traducao seria
desproporcional -- mas o log registra, porque um pacote sem o `.qm` e' um
descuido de empacotamento que precisa aparecer em algum lugar.
"""

from __future__ import annotations

import pathlib
import sys

from tfedit import log_interno

log = log_interno.obter(__name__)

#: Os catalogos do Qt que valem para este programa. `qtbase` cobre QMessageBox,
#: QFileDialog, QLineEdit (menu de contexto) e os botoes padrao -- que e' tudo o
#: que aparece aqui. Os demais (`qtdeclarative`, `designer`) sao de modulos que
#: este projeto nem empacota.
CATALOGOS = ("qtbase_pt_BR", "qt_pt_BR")

IDIOMA = "pt_BR"


def pastas_de_traducao() -> list[pathlib.Path]:
    """Onde procurar os `.qm`, na ordem de preferencia."""
    lugares: list[pathlib.Path] = []

    # Congelado: o PyInstaller extrai os dados em `sys._MEIPASS`.
    base = getattr(sys, "_MEIPASS", "")
    if base:
        lugares.append(pathlib.Path(base) / "traducoes")

    try:
        import PySide6
        lugares.append(pathlib.Path(PySide6.__file__).parent / "translations")
    except ImportError:
        pass

    return [p for p in lugares if p.is_dir()]


def instalar(aplicacao) -> list[str]:
    """Carrega os catalogos em portugues. Devolve os que entraram.

    Os `QTranslator` sao guardados no proprio `QApplication`: sem manter a
    referencia viva, o coletor do Python os destroi e a traducao some -- os
    textos voltam ao ingles alguns segundos depois de a janela abrir, e o
    sintoma nao aponta para a causa.
    """
    from PySide6.QtCore import QLocale, QTranslator

    QLocale.setDefault(QLocale(QLocale.Language.Portuguese,
                               QLocale.Country.Brazil))

    guardados = []
    carregados = []
    for pasta in pastas_de_traducao():
        for catalogo in CATALOGOS:
            if catalogo in carregados:
                continue
            tradutor = QTranslator(aplicacao)
            if tradutor.load(catalogo, str(pasta)):
                aplicacao.installTranslator(tradutor)
                guardados.append(tradutor)
                carregados.append(catalogo)

    # A referencia vive no objeto da aplicacao, e nao numa variavel local.
    aplicacao._tradutores = guardados

    if carregados:
        log.info("traducao %s carregada: %s", IDIOMA, ", ".join(carregados))
    else:
        log.warning("nenhum catalogo de traducao encontrado em %s -- os botoes "
                    "dos dialogos padrao ficarao em ingles",
                    [str(p) for p in pastas_de_traducao()] or "nenhuma pasta")
    return carregados
