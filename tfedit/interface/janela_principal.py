"""A janela: abrir, editar, salvar. O minimo para o editor ser usavel.

Deliberadamente pequeno nesta etapa. O que existe aqui e' o que prova a
arquitetura de ponta a ponta -- abrir um arquivo grande, digitar dentro dele e
gravar sem carregar nada. Menu completo, pesquisa, abas e sessao vem depois.
"""

from __future__ import annotations

import pathlib

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QStatusBar)

from tfedit import VERSAO, codificacao
from tfedit.gravacao import FalhaNaTroca, SemEspaco, gravar
from tfedit.interface.editor import EditorDeslizante
from tfedit.janela import JanelaViva
from tfedit.original import Original
from tfedit.pecas import Documento

FILTRO = ("Arquivos de texto (*.txt *.log *.csv *.dat *.json *.xml *.sql "
          "*.md);;Todos os arquivos (*)")


class JanelaPrincipal(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.caminho: pathlib.Path | None = None
        self.original: Original | None = None
        self.documento: Documento | None = None
        self.editor: EditorDeslizante | None = None

        self.setWindowTitle(f"TextForgeEdit {VERSAO}")
        self.resize(1100, 760)
        self._montar_menu()

        self.barra = QStatusBar(self)
        self.setStatusBar(self.barra)
        self.rotulo_posicao = QLabel("", self)
        self.rotulo_codec = QLabel("", self)
        self.rotulo_memoria = QLabel("", self)
        for rotulo in (self.rotulo_posicao, self.rotulo_codec,
                       self.rotulo_memoria):
            self.barra.addPermanentWidget(rotulo)
        self.barra.showMessage("Abra um arquivo (Ctrl+O)")

    # ==================================================================
    # Menu
    # ==================================================================

    def _montar_menu(self) -> None:
        arquivo = self.menuBar().addMenu("&Arquivo")
        for rotulo, atalho, tratador in (
                ("&Abrir...", QKeySequence.StandardKey.Open, self.abrir),
                ("&Salvar", QKeySequence.StandardKey.Save, self.salvar),
                ("Sa&ir", QKeySequence.StandardKey.Quit, self.close)):
            acao = QAction(rotulo, self)
            acao.setShortcut(atalho)
            acao.triggered.connect(tratador)
            arquivo.addAction(acao)

        ir = QAction("&Ir para linha...", self)
        ir.setShortcut("Ctrl+G")
        ir.triggered.connect(self.ir_para_linha)
        self.menuBar().addMenu("&Navegar").addAction(ir)

    # ==================================================================
    # Abrir
    # ==================================================================

    def abrir(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(self, "Abrir", "", FILTRO)
        if caminho:
            self.abrir_arquivo(caminho)

    def abrir_arquivo(self, caminho: str) -> bool:
        alvo = pathlib.Path(caminho)
        try:
            original = Original(alvo)
        except OSError as exc:
            QMessageBox.warning(self, "Nao foi possivel abrir", str(exc))
            return False

        perfil = codificacao.detectar(original.ler(0, codificacao.SONDAGEM))
        # A varredura e' sincrona nesta etapa: 240 MB levam ~1 s. Passar para
        # uma thread com progresso e' a proxima melhoria obvia, e a estrutura
        # ja' aceita (`indexar` e' incremental por design).
        self.barra.showMessage(f"Indexando {alvo.name}...")
        self.repaint()
        original.indexar()

        self._fechar_atual()
        self.caminho = alvo
        self.original = original
        self.documento = Documento(original)
        janela = JanelaViva(self.documento, perfil)
        self.editor = EditorDeslizante(janela, self)
        self.editor.posicao_mudou.connect(self._mostrar_posicao)
        self.editor.sujou.connect(self._mostrar_titulo)
        self.setCentralWidget(self.editor)

        mb = original.tamanho / (1024 * 1024)
        self.rotulo_codec.setText(f"{perfil.rotulo}  {perfil.rotulo_eol}")
        self.barra.showMessage(
            f"{alvo.name}: {mb:,.1f} MB, {original.total_de_linhas:,} linhas. "
            f"O arquivo continua no disco.".replace(",", "."), 8000)
        self._mostrar_titulo()
        self._mostrar_posicao(0, 0)
        return True

    def _fechar_atual(self) -> None:
        if self.original is not None:
            self.original.fechar()
        self.original = None
        self.documento = None

    # ==================================================================
    # Salvar
    # ==================================================================

    def salvar(self) -> bool:
        if self.editor is None or self.documento is None or self.caminho is None:
            return False
        self.editor.sincronizar()
        if not self.documento.alterado:
            self.barra.showMessage("Nada a salvar: nenhuma alteracao pendente.",
                                   4000)
            return True

        try:
            escritos = gravar(self.caminho, self.documento,
                              antes_de_trocar=self.original.fechar)
        except SemEspaco as exc:
            QMessageBox.warning(self, "Espaco insuficiente", str(exc))
            return False
        except (FalhaNaTroca, OSError) as exc:
            QMessageBox.warning(self, "Nao foi possivel salvar", str(exc))
            return False

        # O arquivo do disco e' outro: o mmap antigo esta' fechado e os offsets
        # das pecas apontavam para ele. Reabrir e reindexar antes de qualquer
        # leitura e' obrigatorio -- ver `Documento.confirmar_gravacao`.
        novo = Original(self.caminho)
        novo.indexar()
        self.original = novo
        self.documento.confirmar_gravacao(novo)
        self.editor.janela.documento = self.documento
        self.editor.recarregar(self.editor.linha_atual_no_documento())
        self._mostrar_titulo()
        self.barra.showMessage(
            f"Salvo: {self.caminho.name} ({escritos / (1024*1024):,.1f} MB)"
            .replace(",", "."), 4000)
        return True

    # ==================================================================
    # Navegacao e status
    # ==================================================================

    def ir_para_linha(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        if self.editor is None or self.documento is None:
            return
        total = self.documento.total_de_linhas
        numero, ok = QInputDialog.getInt(
            self, "Ir para linha", f"Linha (1 a {total:,}):".replace(",", "."),
            self.editor.linha_atual_no_documento() + 1, 1, total)
        if ok:
            self.editor.ir_para_linha(numero - 1)

    def _mostrar_posicao(self, linha: int, coluna: int) -> None:
        total = self.documento.total_de_linhas if self.documento else 0
        self.rotulo_posicao.setText(
            f"Ln {linha + 1:,} de {total:,}   Col {coluna + 1}"
            .replace(",", "."))
        if self.documento is not None:
            # O numero que justifica o projeto inteiro: quanto do arquivo esta'
            # de fato na memoria.
            vivos = sum(p.tamanho for p in self.documento.blocos()
                        if p.fonte == "adicionado")
            self.rotulo_memoria.setText(f"editado: {vivos / 1024:,.1f} KB"
                                        .replace(",", "."))

    def _mostrar_titulo(self) -> None:
        nome = self.caminho.name if self.caminho else "sem titulo"
        sujo = "*" if (self.documento is not None
                       and (self.documento.alterado
                            or (self.editor is not None
                                and self.editor.document().isModified()))) else ""
        self.setWindowTitle(f"{sujo}{nome} - TextForgeEdit {VERSAO}")

    def closeEvent(self, evento) -> None:                 # noqa: N802 - Qt
        if self.editor is not None:
            self.editor.sincronizar()
        if self.documento is not None and self.documento.alterado:
            resposta = QMessageBox.question(
                self, "Alteracoes nao salvas",
                f"<b>{self.caminho.name if self.caminho else ''}</b> tem "
                f"alteracoes nao salvas.<br><br>Salvar antes de sair?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if resposta == QMessageBox.StandardButton.Cancel:
                evento.ignore()
                return
            if resposta == QMessageBox.StandardButton.Save and not self.salvar():
                evento.ignore()
                return
        self._fechar_atual()
        evento.accept()
