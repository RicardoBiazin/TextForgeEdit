"""A tela de Configurações.

DUAS REGRAS que valem para tudo o que entra aqui.

**Nada de opção que não faz nada.** Antes desta tela existir, `tema` era lido
com um padrão embutido e nunca aparecia no arquivo de configuração -- não havia
como mudá-lo. E `limite_de_substituicoes` era o inverso: estava declarado, dava
para editar, e o código usava uma constante. Uma opção que finge existir é pior
que a ausência dela, porque some a chance de a pessoa procurar outro caminho.
`teste_configuracao_da_tela` confere que toda chave mostrada aqui é de fato
lida por alguém.

**O que dá para aplicar na hora, aplica na hora.** Tema, número de linha, fonte
e quebra de linha valem assim que você fecha esta janela, e não só nos arquivos
abertos depois -- do contrário a conclusão natural é que a opção não funciona.
O que não dá (os limites de leitura, que já foram usados na abertura) diz isso
na própria tela.
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from tfedit import log_interno, tema as tema_mod

log = log_interno.obter(__name__)

#: Rótulo de cada tema, na ordem em que aparecem.
TEMAS = (("sistema", "Seguir o Windows"),
         ("escuro", "Escuro"),
         ("claro", "Claro"),
         ("azul", "Azul"))


class Configuracoes(QDialog):
    """Lê e devolve um dicionário de configuração. Não grava sozinha.

    Quem chama é que decide gravar e aplicar -- assim o Cancelar não deixa
    resíduo, e a janela principal continua sendo a única dona da configuração
    viva.
    """

    def __init__(self, cfg: dict, parent=None, *, botoes_disponiveis=()) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.cfg = dict(cfg)
        self._botoes_disponiveis = tuple(botoes_disponiveis)
        self.resize(560, 520)

        abas = QTabWidget(self)
        abas.addTab(self._pagina_geral(), "&Geral")
        abas.addTab(self._pagina_editor(), "&Editor")
        if self._botoes_disponiveis:
            abas.addTab(self._pagina_barra(), "&Barra de atalhos")
        abas.addTab(self._pagina_limites(), "&Limites")

        caixa = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                 | QDialogButtonBox.StandardButton.Cancel)
        caixa.accepted.connect(self.accept)
        caixa.rejected.connect(self.reject)

        fora = QVBoxLayout(self)
        fora.addWidget(abas, 1)
        fora.addWidget(caixa)

    # ==================================================================
    # Páginas
    # ==================================================================

    def _pagina_geral(self) -> QWidget:
        pagina = QWidget(self)
        forma = QFormLayout(pagina)

        self.tema = QComboBox(pagina)
        for chave, rotulo in TEMAS:
            self.tema.addItem(rotulo, chave)
        atual = str(self.cfg.get("tema", "sistema"))
        indice = self.tema.findData(atual)
        self.tema.setCurrentIndex(indice if indice >= 0 else 0)
        forma.addRow("&Tema:", self.tema)

        # A pasta padrão, com um botão de procurar ao lado: digitar caminho à
        # mão é onde nasce a pasta que não existe.
        self.pasta = QLineEdit(str(self.cfg.get("pasta_padrao", "")), pagina)
        self.pasta.setPlaceholderText(
            "vazio: usa a pasta do arquivo aberto")
        procurar = QPushButton("Procurar…", pagina)
        procurar.clicked.connect(self._escolher_pasta)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addWidget(self.pasta, 1)
        linha.addWidget(procurar)
        embrulho = QWidget(pagina)
        embrulho.setLayout(linha)
        forma.addRow("Pasta &padrão:", embrulho)

        self.restaurar = QCheckBox(
            "Reabrir os arquivos da sessão anterior", pagina)
        self.restaurar.setChecked(bool(self.cfg.get("restaurar_sessao", True)))
        forma.addRow("", self.restaurar)

        self.soltar = QSpinBox(pagina)
        self.soltar.setRange(0, 3600)
        self.soltar.setSuffix(" s")
        self.soltar.setSpecialValueText("nunca soltar")
        self.soltar.setValue(int(self.cfg.get("soltar_arquivo_apos_s", 20)))
        self.soltar.setToolTip(
            "Enquanto o arquivo está mapeado, nenhum outro programa consegue\n"
            "regravá-lo no Windows. Passado este tempo sem uso, o TextForgeEdit\n"
            "o devolve ao sistema e remapeia sozinho no próximo acesso.")
        forma.addRow("&Soltar o arquivo após:", self.soltar)
        return pagina

    def _pagina_editor(self) -> QWidget:
        pagina = QWidget(self)
        forma = QFormLayout(pagina)

        self.numero_de_linha = QCheckBox("Sempre exibir", pagina)
        self.numero_de_linha.setChecked(
            bool(self.cfg.get("mostrar_numero_de_linha", True)))
        forma.addRow("&Número de linha:", self.numero_de_linha)

        self.quebrar = QCheckBox("Quebrar linhas longas na largura da janela",
                                 pagina)
        self.quebrar.setChecked(bool(self.cfg.get("quebrar_linha", False)))
        forma.addRow("", self.quebrar)

        self.fonte = QLineEdit(str(self.cfg.get("fonte", "Consolas")), pagina)
        forma.addRow("&Fonte:", self.fonte)

        self.tamanho = QSpinBox(pagina)
        self.tamanho.setRange(6, 48)
        self.tamanho.setSuffix(" pt")
        self.tamanho.setValue(int(self.cfg.get("fonte_tamanho", 11)))
        forma.addRow("Ta&manho:", self.tamanho)

        self.tabulacao = QSpinBox(pagina)
        self.tabulacao.setRange(1, 16)
        self.tabulacao.setValue(int(self.cfg.get("tabulacao", 4)))
        forma.addRow("Tab&ulação:", self.tabulacao)
        return pagina

    def _pagina_barra(self) -> QWidget:
        pagina = QWidget(self)
        fora = QVBoxLayout(pagina)
        fora.addWidget(QLabel(
            "Marque os botões que devem aparecer na barra. A ordem é a da "
            "lista.", pagina))

        escolhidos = list(self.cfg.get("botoes_da_barra", ()))
        self.botoes = QListWidget(pagina)
        # Os ESCOLHIDOS primeiro, na ordem salva; depois o resto. Assim a lista
        # mostra a barra como ela está, e não uma ordem alfabética que não
        # corresponde a nada na tela.
        ordenados = ([b for b in escolhidos if b in
                      dict(self._botoes_disponiveis)]
                     + [c for c, _ in self._botoes_disponiveis
                        if c not in escolhidos])
        rotulos = dict(self._botoes_disponiveis)
        for chave in ordenados:
            item = QListWidgetItem(rotulos.get(chave, chave), self.botoes)
            item.setData(Qt.ItemDataRole.UserRole, chave)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if chave in escolhidos
                               else Qt.CheckState.Unchecked)
        fora.addWidget(self.botoes, 1)

        self.mostrar_barra = QCheckBox("Mostrar a barra de atalhos", pagina)
        self.mostrar_barra.setChecked(bool(self.cfg.get("mostrar_barra", True)))
        fora.addWidget(self.mostrar_barra)
        return pagina

    def _pagina_limites(self) -> QWidget:
        pagina = QWidget(self)
        fora = QVBoxLayout(pagina)

        aviso = QLabel(
            "Estes limites são lidos ao ABRIR um arquivo. Mudá-los vale para "
            "os próximos arquivos abertos, e não para os que já estão nas "
            "abas.", pagina)
        aviso.setWordWrap(True)
        fora.addWidget(aviso)

        grupo = QGroupBox("Leitura", pagina)
        forma = QFormLayout(grupo)

        self.linhas_da_janela = QSpinBox(grupo)
        self.linhas_da_janela.setRange(100, 100_000)
        self.linhas_da_janela.setSingleStep(500)
        self.linhas_da_janela.setValue(
            int(self.cfg.get("linhas_da_janela", 5000)))
        self.linhas_da_janela.setToolTip(
            "Quantas linhas o editor segura de cada vez. É o que permite\n"
            "editar um arquivo de 1 GB: o resto continua no disco.")
        forma.addRow("Linhas na &janela viva:", self.linhas_da_janela)

        self.substituicoes = QSpinBox(grupo)
        self.substituicoes.setRange(100, 10_000_000)
        self.substituicoes.setSingleStep(10_000)
        self.substituicoes.setValue(
            int(self.cfg.get("limite_de_substituicoes", 100_000)))
        forma.addRow("Teto de &substituições:", self.substituicoes)

        self.realce_mb = QSpinBox(grupo)
        self.realce_mb.setRange(0, 512)
        self.realce_mb.setSuffix(" MB")
        self.realce_mb.setSpecialValueText("sempre desligado")
        self.realce_mb.setValue(int(self.cfg.get("limite_realce_mb", 8)))
        forma.addRow("&Realce até:", self.realce_mb)

        self.planilha_mb = QSpinBox(grupo)
        self.planilha_mb.setRange(0, 2048)
        self.planilha_mb.setSuffix(" MB")
        self.planilha_mb.setSpecialValueText("nunca abrir como planilha")
        self.planilha_mb.setValue(int(self.cfg.get("limite_planilha_mb", 100)))
        self.planilha_mb.setToolTip(
            "Uma planilha vai INTEIRA para a memória: acima deste tamanho o\n"
            ".xlsx abre como arquivo comum, onde as garantias de memória do\n"
            "editor voltam a valer.")
        forma.addRow("&Planilha até:", self.planilha_mb)

        fora.addWidget(grupo)
        fora.addStretch(1)
        return pagina

    # ==================================================================

    def _escolher_pasta(self) -> None:
        atual = self.pasta.text().strip()
        escolhida = QFileDialog.getExistingDirectory(
            self, "Pasta padrão", atual if pathlib.Path(atual).is_dir() else "")
        if escolhida:
            self.pasta.setText(escolhida)

    def valores(self) -> dict:
        """A configuração com o que foi escolhido. Não grava nada."""
        novo = dict(self.cfg)
        novo["tema"] = self.tema.currentData()

        # Uma pasta que não existe seria pior que nenhuma: o diálogo abriria
        # num lugar qualquer e a pessoa acharia que a opção não pegou.
        pasta = self.pasta.text().strip()
        if pasta and not pathlib.Path(pasta).is_dir():
            log.warning("pasta padrão %r não existe; guardando vazio", pasta)
            pasta = ""
        novo["pasta_padrao"] = pasta

        novo["restaurar_sessao"] = self.restaurar.isChecked()
        novo["soltar_arquivo_apos_s"] = self.soltar.value()
        novo["mostrar_numero_de_linha"] = self.numero_de_linha.isChecked()
        novo["quebrar_linha"] = self.quebrar.isChecked()
        novo["fonte"] = self.fonte.text().strip() or "Consolas"
        novo["fonte_tamanho"] = self.tamanho.value()
        novo["tabulacao"] = self.tabulacao.value()
        novo["linhas_da_janela"] = self.linhas_da_janela.value()
        novo["limite_de_substituicoes"] = self.substituicoes.value()
        novo["limite_realce_mb"] = self.realce_mb.value()
        novo["limite_planilha_mb"] = self.planilha_mb.value()

        if self._botoes_disponiveis:
            novo["botoes_da_barra"] = [
                self.botoes.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.botoes.count())
                if self.botoes.item(i).checkState() == Qt.CheckState.Checked]
            novo["mostrar_barra"] = self.mostrar_barra.isChecked()
        return novo


def temas_validos() -> list[str]:
    """As chaves de tema que a tela oferece e que de fato carregam."""
    disponiveis = set(tema_mod.disponiveis()) | {"sistema"}
    return [c for c, _ in TEMAS if c in disponiveis]
