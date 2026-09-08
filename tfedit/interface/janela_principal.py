"""A janela: abas, abrir, salvar, salvar como, localizar e arrastar-e-soltar.

Ela conduz ABAS, e nao arquivos: tudo o que um arquivo aberto precisa mora na
`Aba` (ver `interface/aba.py`). E' o que faz "varias abas" ser uma lista em vez
de uma reescrita.
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (QFileDialog, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QStatusBar, QTabWidget,
                               QVBoxLayout, QWidget)

from tfedit import (APP, AUTOR, VERSAO, busca, configuracao,
                    linguagens, log_interno, sessao as sessao_mod,
                    tema as tema_mod)
from tfedit.linguagens import registro as registro_de_linguagens
from tfedit.gravacao import FalhaNaTroca, SemEspaco
from tfedit.original import ArquivoMudou
from tfedit.interface.aba import Aba
from tfedit.interface.barra_busca import BarraDeBusca

log = log_interno.obter(__name__)

FILTRO = ("Arquivos de texto (*.txt *.log *.csv *.dat *.json *.xml *.sql "
          "*.md);;Todos os arquivos (*)")

#: Teto de substituicoes de uma vez. Trocar 3 milhoes de ocorrencias uma a uma
#: na tabela de pecas levaria muito tempo com a interface parada; o teto
#: transforma isso num aviso em vez de num travamento.
TETO_DE_SUBSTITUICOES = 100_000


class _Credito(QLabel):
    """O credito do rodape. Clicavel, porque ja' existe onde levar."""

    clicado = Signal()

    def __init__(self, texto: str, dica: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(texto, parent)
        self.setToolTip(dica)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("padding: 0 6px;")

    def mousePressEvent(self, evento) -> None:            # noqa: N802 - Qt
        if evento.button() == Qt.MouseButton.LeftButton:
            self.clicado.emit()
        super().mousePressEvent(evento)


class JanelaPrincipal(QMainWindow):
    def __init__(self, cfg: dict | None = None) -> None:
        super().__init__()
        self.cfg = cfg if cfg is not None else configuracao.carregar()
        self.setWindowTitle(f"TextForgeEdit {VERSAO}")
        self.resize(int(self.cfg.get("janela_largura", 1150)),
                    int(self.cfg.get("janela_altura", 780)))
        if self.cfg.get("janela_maximizada"):
            self.showMaximized()
        self.setAcceptDrops(True)          # arrastar-e-soltar (ver dropEvent)

        self.abas = QTabWidget(self)
        self.abas.setTabsClosable(True)
        self.abas.setMovable(True)
        self.abas.setDocumentMode(True)
        self.abas.tabCloseRequested.connect(self.fechar_aba)
        self.abas.currentChanged.connect(self._ao_trocar_de_aba)

        # O tema e' resolvido UMA vez e emprestado a cada aba: dois temas na
        # mesma janela seria o mesmo texto com duas cores de fundo.
        self.tema = tema_mod.resolver(str(self.cfg.get("tema", "sistema")))

        self.barra_busca = BarraDeBusca(self)
        self.barra_busca.hide()
        self.barra_busca.procurar.connect(self._procurar)
        self.barra_busca.substituir_atual.connect(self._substituir_atual)
        self.barra_busca.substituir_todas.connect(self._substituir_todas)
        self.barra_busca.fechada.connect(self._focar_editor)

        central = QWidget(self)
        pilha = QVBoxLayout(central)
        pilha.setContentsMargins(0, 0, 0, 0)
        pilha.setSpacing(0)
        pilha.addWidget(self.abas, 1)
        pilha.addWidget(self.barra_busca)
        self.setCentralWidget(central)

        self._montar_menu()

        self.barra = QStatusBar(self)
        self.setStatusBar(self.barra)
        self.rotulo_posicao = QLabel("", self)
        self.rotulo_linguagem = QLabel("", self)
        self.rotulo_linguagem.setToolTip(
            "Linguagem do realce. Menu Linguagem para trocar.")
        self.rotulo_codec = QLabel("", self)
        self.rotulo_memoria = QLabel("", self)
        self.progresso = QProgressBar(self)
        self.progresso.setMaximumWidth(160)
        self.progresso.setTextVisible(False)
        self.progresso.hide()
        self.barra.addPermanentWidget(self.progresso)
        for rotulo in (self.rotulo_posicao, self.rotulo_linguagem,
                       self.rotulo_codec, self.rotulo_memoria):
            self.barra.addPermanentWidget(rotulo)

        # `addPermanentWidget`, e nao `addWidget`: a area dos widgets NAO
        # permanentes e' a mesma em que `showMessage()` desenha, e um credito
        # ali seria coberto -- ou empurrado -- a cada "Salvo: arquivo.txt".
        self.credito = _Credito(
            f"Produzido por {AUTOR} · v{VERSAO}",
            f"{APP} {VERSAO}\nProduzido por {AUTOR}.\n"
            f"Clique para ver a licença e as versões.", self)
        self.credito.clicado.connect(self.sobre)
        self.barra.addPermanentWidget(self.credito)
        self.barra.showMessage("Abra um arquivo (Ctrl+O) ou arraste um para cá")

    # ==================================================================
    # Linguagem
    # ==================================================================

    def _montar_menu_linguagem(self) -> None:
        """Monta o menu SÓ quando ele abre.

        Vinte e quatro ações criadas no arranque custariam tempo de abertura
        para um menu que a maioria das sessões nunca usa.
        """
        self.menu_linguagem.clear()
        aba = self.aba_atual
        if aba is None:
            acao = self.menu_linguagem.addAction("(nenhum arquivo aberto)")
            acao.setEnabled(False)
            return

        linguagens.carregar_embutidos()
        atual = aba.provedor.nome if aba.provedor is not None else ""
        grupo = QActionGroup(self.menu_linguagem)
        grupo.setExclusive(True)
        for nome in sorted(registro_de_linguagens.REGISTRO.nomes()):
            acao = self.menu_linguagem.addAction(nome)
            acao.setCheckable(True)
            acao.setChecked(nome == atual)
            acao.triggered.connect(
                lambda _c=False, n=nome: self._trocar_linguagem(n))
            grupo.addAction(acao)

    def _trocar_linguagem(self, nome: str) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        aba.definir_linguagem(registro_de_linguagens.REGISTRO.por_nome(nome))
        self.rotulo_linguagem.setText(aba.nome_da_linguagem)

    # ==================================================================
    # Sessão
    # ==================================================================

    def restaurar_sessao(self) -> int:
        """Reabre as abas da sessão anterior. Devolve quantas voltaram."""
        if not self.cfg.get("restaurar_sessao", True):
            return 0
        guardadas = sessao_mod.ler()
        if not guardadas:
            return 0

        voltaram = 0
        recusadas = []
        for guardada in guardadas:
            if not self.abrir_arquivo(guardada.caminho):
                continue
            aba = self.aba_atual
            voltaram += 1
            if guardada.tem_pendencia:
                # Reaplicar peças que apontam para offsets de um arquivo que
                # mudou escreveria conteúdo certo em LUGAR ERRADO. Recusar e
                # abrir limpo é o lado seguro: perder as edições pendentes é
                # ruim, misturar dois arquivos é pior.
                if not guardada.arquivo_confere():
                    recusadas.append(aba.nome)
                elif aba.documento.aplicar_diario(guardada.diario):
                    aba.editor.recarregar(guardada.linha)
                    aba.titulo_mudou.emit()
            if guardada.linha:
                aba.editor.ir_para_linha(guardada.linha)

        sessao_mod.esquecer()
        if recusadas:
            QMessageBox.warning(
                self, "Alterações não recuperadas",
                "Estes arquivos mudaram no disco desde a última sessão, e as "
                "edições pendentes <b>não</b> foram reaplicadas:<br><br>"
                + "<br>".join(f"• {n}" for n in recusadas)
                + "<br><br>Reaplicá-las escreveria o texto no lugar errado. "
                  "Eles foram abertos como estão no disco.")
        if voltaram:
            log.info("sessão restaurada: %d aba(s)", voltaram)
        return voltaram

    def _guardar_sessao(self) -> None:
        sessao_mod.gravar(sessao_mod.capturar(self.todas_as_abas()))

    # ==================================================================
    # Pedido de outra instância
    # ==================================================================

    def atender_pedido(self, pedido: dict) -> None:
        """Abre o que outra instância mandou e traz a janela para a frente."""
        for caminho in pedido.get("arquivos", []) or []:
            self.abrir_arquivo(str(caminho))
        linha = int(pedido.get("linha", 0) or 0)
        if linha and self.aba_atual is not None:
            self.aba_atual.editor.ir_para_linha(linha - 1)

        # Trazer para a frente: sem isto o usuário clica em "Abrir com", o
        # arquivo abre numa janela que está atrás de tudo, e parece que nada
        # aconteceu.
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    # ==================================================================
    # Menu
    # ==================================================================

    def _montar_menu(self) -> None:
        def acao(rotulo, atalho, tratador, menu):
            item = QAction(rotulo, self)
            if atalho:
                item.setShortcut(atalho)
            item.triggered.connect(tratador)
            menu.addAction(item)
            return item

        arquivo = self.menuBar().addMenu("&Arquivo")
        acao("&Abrir...", QKeySequence.StandardKey.Open, self.abrir, arquivo)
        acao("&Salvar", QKeySequence.StandardKey.Save, self.salvar, arquivo)
        acao("Salvar &como...", QKeySequence.StandardKey.SaveAs,
             self.salvar_como, arquivo)
        acao("Salvar &tudo", "Ctrl+Shift+S", self.salvar_tudo, arquivo)
        arquivo.addSeparator()
        acao("&Fechar aba", QKeySequence.StandardKey.Close,
             lambda: self.fechar_aba(self.abas.currentIndex()), arquivo)
        acao("Sa&ir", QKeySequence.StandardKey.Quit, self.close, arquivo)

        editar = self.menuBar().addMenu("&Editar")
        acao("&Desfazer", QKeySequence.StandardKey.Undo,
             lambda: self._no_editor("undo"), editar)
        acao("&Refazer", QKeySequence.StandardKey.Redo,
             lambda: self._no_editor("redo"), editar)
        editar.addSeparator()
        acao("Recor&tar", QKeySequence.StandardKey.Cut,
             lambda: self._no_editor("cut"), editar)
        acao("&Copiar", QKeySequence.StandardKey.Copy,
             lambda: self._no_editor("copy"), editar)
        acao("C&olar", QKeySequence.StandardKey.Paste,
             lambda: self._no_editor("paste"), editar)

        localizar = self.menuBar().addMenu("&Localizar")
        acao("&Localizar...", QKeySequence.StandardKey.Find,
             self.abrir_busca, localizar)
        acao("&Substituir...", QKeySequence.StandardKey.Replace,
             self.abrir_substituir, localizar)
        acao("Pró&xima ocorrência", "F3",
             lambda: self.barra_busca._procurar(False), localizar)
        acao("Ocorrência &anterior", "Shift+F3",
             lambda: self.barra_busca._procurar(True), localizar)
        localizar.addSeparator()
        acao("&Ir para linha...", "Ctrl+G", self.ir_para_linha, localizar)

        self.menu_linguagem = self.menuBar().addMenu("Lin&guagem")
        self.menu_linguagem.aboutToShow.connect(self._montar_menu_linguagem)

        ajuda = self.menuBar().addMenu("A&juda")
        acao("&Sobre...", "", self.sobre, ajuda)

    # ==================================================================
    # Abas
    # ==================================================================

    @property
    def aba_atual(self) -> Aba | None:
        widget = self.abas.currentWidget()
        return widget if isinstance(widget, Aba) else None

    def todas_as_abas(self) -> list[Aba]:
        return [self.abas.widget(i) for i in range(self.abas.count())
                if isinstance(self.abas.widget(i), Aba)]

    def abrir(self) -> None:
        caminhos, _ = QFileDialog.getOpenFileNames(self, "Abrir", "", FILTRO)
        for caminho in caminhos:
            self.abrir_arquivo(caminho)

    def abrir_arquivo(self, caminho: str) -> bool:
        # Uma aba por ARQUIVO: duas abas do mesmo arquivo produziriam duas
        # versoes divergentes, e uma se perderia no primeiro salvamento.
        chave = Aba.chave_de(caminho)
        for indice, aba in enumerate(self.todas_as_abas()):
            if aba.chave() == chave:
                self.abas.setCurrentIndex(indice)
                self.barra.showMessage(f"{aba.nome} já estava aberto", 4000)
                return True

        try:
            aba = Aba(caminho, self.cfg, self, tema=self.tema)
        except OSError as exc:
            log.warning("nao foi possivel abrir %s: %s", caminho, exc)
            QMessageBox.warning(self, "Não foi possível abrir", str(exc))
            return False

        aba.posicao_mudou.connect(self._mostrar_posicao)
        aba.titulo_mudou.connect(self._atualizar_titulos)
        aba.indexando.connect(self._ao_indexar)
        aba.indexou.connect(self._ao_terminar_indice)

        configuracao.registrar_recente(self.cfg, caminho)
        indice = self.abas.addTab(aba, aba.titulo)
        self.abas.setTabToolTip(indice, str(aba.caminho))
        self.abas.setCurrentIndex(indice)
        if aba.indexando_agora:
            self.progresso.setRange(0, 100)
            self.progresso.setValue(0)
            self.progresso.show()
            self.barra.showMessage(
                f"{aba.nome}: indexando... dá para ler e rolar; editar libera "
                f"no fim.")
        else:
            self._ao_terminar_indice(aba.original.total_de_linhas)
        return True

    def fechar_aba(self, indice: int) -> bool:
        aba = self.abas.widget(indice)
        if not isinstance(aba, Aba):
            return False
        aba.editor.sincronizar()
        if aba.modificado and not self._perguntar_para_fechar(aba):
            return False
        self.abas.removeTab(indice)
        aba.encerrar()
        aba.deleteLater()
        if self.abas.count() == 0:
            # So' os campos do DOCUMENTO sao limpos. O credito fica: ele nao
            # e' estado de arquivo nenhum, e some-lo ao fechar a ultima aba
            # deixaria o rodape vazio sem motivo.
            self.rotulo_posicao.clear()
            self.rotulo_codec.clear()
            self.rotulo_memoria.clear()
            self.setWindowTitle(f"TextForgeEdit {VERSAO}")
            self.barra.showMessage("Abra um arquivo (Ctrl+O) ou arraste "
                                   "um para cá")
        return True

    def _perguntar_para_fechar(self, aba: Aba) -> bool:
        resposta = QMessageBox.question(
            self, "Alterações não salvas",
            f"<b>{aba.nome}</b> tem alterações não salvas.<br><br>"
            f"Salvar antes de fechar?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if resposta == QMessageBox.StandardButton.Cancel:
            return False
        if resposta == QMessageBox.StandardButton.Save:
            return self._gravar(aba)
        return True

    def _ao_trocar_de_aba(self, _indice: int) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        self.rotulo_codec.setText(
            f"{aba.perfil.rotulo}  {aba.perfil.rotulo_eol}")
        self.rotulo_linguagem.setText(aba.nome_da_linguagem)
        self._mostrar_posicao(aba.editor.linha_atual_no_documento(), 0)
        self.progresso.setVisible(aba.indexando_agora)
        self._atualizar_titulos()
        aba.editor.setFocus()

    def _atualizar_titulos(self) -> None:
        for indice, aba in enumerate(self.todas_as_abas()):
            if self.abas.tabText(indice) != aba.titulo:
                self.abas.setTabText(indice, aba.titulo)
        aba = self.aba_atual
        self.setWindowTitle(f"{aba.titulo} - TextForgeEdit {VERSAO}"
                            if aba else f"TextForgeEdit {VERSAO}")

    # ==================================================================
    # Indexacao
    # ==================================================================

    def _ao_indexar(self, varrido: int, total: int) -> None:
        aba = self.aba_atual
        if aba is None or self.sender() is not aba:
            return                       # progresso de uma aba de fundo
        self.progresso.setValue(varrido * 100 // max(1, total))
        aba.editor._ajustar_margem()

    def _ao_terminar_indice(self, total_de_linhas: int) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        self.progresso.setVisible(aba.indexando_agora)
        mb = aba.original.tamanho / (1024 * 1024)
        self.barra.showMessage(
            f"{aba.nome}: {mb:,.1f} MB, {total_de_linhas:,} linhas. "
            f"O arquivo continua no disco.".replace(",", "."), 8000)

    # ==================================================================
    # Gravar
    # ==================================================================

    def salvar(self) -> bool:
        aba = self.aba_atual
        return self._gravar(aba) if aba is not None else False

    def salvar_como(self) -> bool:
        aba = self.aba_atual
        if aba is None:
            return False
        if aba.indexando_agora:
            self._avisar_indexando()
            return False
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar como", str(aba.caminho), FILTRO)
        if not caminho:
            return False
        if Aba.chave_de(caminho) != aba.chave():
            for outra in self.todas_as_abas():
                if outra is not aba and outra.chave() == Aba.chave_de(caminho):
                    QMessageBox.warning(
                        self, "Arquivo já aberto",
                        f"<b>{outra.nome}</b> está aberto em outra aba. "
                        f"Feche-a antes de salvar por cima dela.")
                    return False
        return self._gravar(aba, destino=caminho)

    def salvar_tudo(self) -> bool:
        tudo = True
        for aba in self.todas_as_abas():
            if aba.modificado:
                tudo = self._gravar(aba) and tudo
        return tudo

    def _gravar(self, aba: Aba, destino=None) -> bool:
        if aba.indexando_agora:
            self._avisar_indexando()
            return False
        try:
            escritos = aba.salvar(destino)
        except SemEspaco as exc:
            log.warning("sem espaco para gravar %s: %s", aba.nome, exc)
            QMessageBox.warning(self, "Espaço insuficiente", str(exc))
            return False
        except ArquivoMudou as exc:
            log.warning("alteração externa em %s: %s", aba.nome, exc)
            QMessageBox.warning(
                self, "O arquivo mudou no disco",
                f"{exc}.<br><br>Salvar agora apagaria essa alteração, e o "
                f"resultado poderia misturar os dois textos. Use "
                f"<b>Salvar como</b> para gravar uma cópia com o que você "
                f"editou, ou feche e abra o arquivo de novo para partir da "
                f"versão que está no disco.")
            return False
        except (FalhaNaTroca, OSError) as exc:
            log.error("falha ao gravar %s: %s", aba.nome, exc)
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return False

        self._atualizar_titulos()
        indice = self.abas.indexOf(aba)
        if indice >= 0:
            self.abas.setTabToolTip(indice, str(aba.caminho))
        if escritos:
            self.barra.showMessage(
                f"Salvo: {aba.nome} ({escritos / (1024*1024):,.1f} MB)"
                .replace(",", "."), 4000)
        else:
            self.barra.showMessage("Nada a salvar: nenhuma alteração pendente.",
                                   4000)
        return True

    def _avisar_indexando(self) -> None:
        QMessageBox.information(
            self, "Ainda indexando",
            "A varredura do arquivo não terminou. Salvar agora gravaria "
            "só a parte já conhecida.<br><br>Espere a barra de progresso "
            "sumir.")

    # ==================================================================
    # Localizar e substituir
    # ==================================================================

    def abrir_busca(self) -> None:
        self._abrir_barra(no_substituir=False)

    def abrir_substituir(self) -> None:
        """Ctrl+H. A MESMA barra do Ctrl+F, com o foco no campo de troca."""
        self._abrir_barra(no_substituir=True)

    def _abrir_barra(self, *, no_substituir: bool) -> None:
        aba = self.aba_atual
        selecao = aba.editor.textCursor().selectedText() if aba else ""
        self.barra_busca.focar(selecao, no_substituir=no_substituir)

    def _focar_editor(self) -> None:
        aba = self.aba_atual
        if aba is not None:
            aba.editor.setFocus()

    def _procurar(self, criterio: busca.Criterio, para_tras: bool) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        cursor = aba.editor.textCursor()
        linha = aba.editor.linha_atual_no_documento()
        coluna = cursor.columnNumber()
        # Ao procurar para a frente, comeca DEPOIS da selecao atual: senao F3
        # acharia de novo a ocorrencia que ja' esta' selecionada.
        if not para_tras and cursor.hasSelection():
            coluna = max(coluna, cursor.selectionEnd()
                         - cursor.block().position())

        achado = busca.proxima(aba.documento, criterio, aba.perfil.codec,
                               linha, coluna, para_tras=para_tras)
        if achado is None:
            self.barra_busca.dizer("não encontrado", erro=True)
            return
        self._ir_para_achado(aba, achado)
        self.barra_busca.dizer(f"linha {achado.linha + 1:,}".replace(",", "."))

    def _ir_para_achado(self, aba: Aba, achado: busca.Achado) -> None:
        """Leva o cursor ate' a ocorrencia, deslizando a fatia se preciso."""
        aba.editor.ir_para_linha(achado.linha)
        na_fatia = aba.janela.linha_na_fatia(achado.linha)
        if na_fatia < 0:
            return
        cursor = aba.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.Down,
                            QTextCursor.MoveMode.MoveAnchor, na_fatia)
        cursor.movePosition(QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.MoveAnchor, achado.inicio)
        cursor.movePosition(QTextCursor.MoveOperation.Right,
                            QTextCursor.MoveMode.KeepAnchor,
                            achado.fim - achado.inicio)
        aba.editor.setTextCursor(cursor)
        aba.editor.centerCursor()

    def _substituir_atual(self, criterio: busca.Criterio, troca: str) -> None:
        aba = self.aba_atual
        if aba is None or aba.editor.isReadOnly():
            return
        cursor = aba.editor.textCursor()
        padrao = criterio.compilar()
        if padrao is None:
            return
        # So' troca se o que esta' SELECIONADO for de fato uma ocorrencia --
        # senao "Trocar" apagaria um texto qualquer que o usuario tivesse
        # selecionado por outro motivo.
        if cursor.hasSelection() and padrao.fullmatch(cursor.selectedText()):
            cursor.insertText(padrao.sub(troca, cursor.selectedText(), count=1))
            aba.editor.setTextCursor(cursor)
        self._procurar(criterio, False)

    def _substituir_todas(self, criterio: busca.Criterio, troca: str) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        if aba.indexando_agora:
            self._avisar_indexando()
            return
        aba.editor.sincronizar()

        quantas, cortou = busca.contar(aba.documento, criterio,
                                       aba.perfil.codec,
                                       teto=TETO_DE_SUBSTITUICOES)
        if not quantas:
            self.barra_busca.dizer("não encontrado", erro=True)
            return
        aviso = (f"<b>{quantas:,}</b> ocorrência(s) de "
                 f"<b>{criterio.texto}</b> serão substituídas."
                 .replace(",", "."))
        if cortou:
            aviso += (f"<br><br>O arquivo tem MAIS que isso: só as primeiras "
                      f"{TETO_DE_SUBSTITUICOES:,} serão trocadas nesta "
                      f"passada.".replace(",", "."))
        if QMessageBox.question(
                self, "Substituir todas", aviso + "<br><br>Continuar?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        feitas = busca.substituir_todas(aba.documento, criterio,
                                        aba.perfil.codec, troca,
                                        teto=TETO_DE_SUBSTITUICOES)
        # O documento mudou por baixo da fatia: recarregar e' obrigatorio, senao
        # o editor mostraria o texto de antes das trocas.
        aba.editor.recarregar(aba.editor.linha_atual_no_documento())
        aba.titulo_mudou.emit()
        self.barra_busca.dizer(f"{feitas:,} substituída(s)".replace(",", "."))
        log.info("substituir todas em %s: %d ocorrencia(s)", aba.nome, feitas)

    # ==================================================================
    # Navegacao e status
    # ==================================================================

    def ir_para_linha(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        aba = self.aba_atual
        if aba is None:
            return
        total = aba.documento.total_de_linhas
        numero, ok = QInputDialog.getInt(
            self, "Ir para linha", f"Linha (1 a {total:,}):".replace(",", "."),
            aba.editor.linha_atual_no_documento() + 1, 1, total)
        if ok:
            aba.editor.ir_para_linha(numero - 1)

    def _no_editor(self, metodo: str) -> None:
        aba = self.aba_atual
        if aba is not None:
            getattr(aba.editor, metodo)()

    def _mostrar_posicao(self, linha: int, coluna: int) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        total = aba.documento.total_de_linhas
        self.rotulo_posicao.setText(
            f"Ln {linha + 1:,} de {total:,}   Col {coluna + 1}"
            .replace(",", "."))
        # O numero que justifica o projeto inteiro: quanto do arquivo esta' de
        # fato na memoria.
        vivos = sum(p.tamanho for p in aba.documento.blocos()
                    if p.fonte == "adicionado")
        self.rotulo_memoria.setText(f"editado: {vivos / 1024:,.1f} KB"
                                    .replace(",", "."))

    # ==================================================================
    # Sobre
    # ==================================================================

    def sobre(self) -> None:
        """Quem fez, qual versao, e onde o log fica.

        O caminho do log entra aqui de proposito: quando algo der errado, e' o
        primeiro arquivo a pedir -- e procura-lo em `%APPDATA%` sem saber o nome
        e' pedir demais de quem so' queria editar um texto.
        """
        import sys

        from PySide6.QtCore import qVersion

        QMessageBox.about(
            self, f"Sobre o {APP}",
            f"<h3>{APP} {VERSAO}</h3>"
            f"<p>Editor de texto completo para arquivos grandes: o arquivo "
            f"continua no disco, e só o que você edita ocupa "
            f"memória.</p>"
            f"<p><b>Produzido por {AUTOR}</b><br>"
            f"Licença MIT</p>"
            f"<p style='color:gray'>Python {sys.version.split()[0]} · "
            f"Qt {qVersion()}</p>"
            f"<p style='color:gray'>Log: {log_interno.caminho_do_log()}</p>")

    # ==================================================================
    # Arrastar-e-soltar
    # ==================================================================

    def dragEnterEvent(self, evento) -> None:             # noqa: N802 - Qt
        if evento.mimeData().hasUrls():
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:                  # noqa: N802 - Qt
        """Abre os arquivos soltos na janela.

        So' arquivo LOCAL: uma URL remota exigiria baixar, e este editor nao faz
        rede. Pasta e' ignorada em vez de tentar abrir tudo o que ha' dentro.
        """
        abertos = 0
        for url in evento.mimeData().urls():
            if not url.isLocalFile():
                continue
            caminho = pathlib.Path(url.toLocalFile())
            if caminho.is_file() and self.abrir_arquivo(str(caminho)):
                abertos += 1
        if abertos:
            evento.acceptProposedAction()

    # ==================================================================
    # Fim
    # ==================================================================

    def closeEvent(self, evento) -> None:                 # noqa: N802 - Qt
        # A sessão é capturada ANTES de perguntar sobre pendências: se o
        # usuário cancelar o fechamento, nada se perdeu, e se ele descartar as
        # alterações a sessão guardada ainda registra onde ele estava.
        for aba in self.todas_as_abas():
            aba.editor.sincronizar()
        self._guardar_sessao()

        for aba in self.todas_as_abas():
            if aba.modificado:
                self.abas.setCurrentWidget(aba)
                if not self._perguntar_para_fechar(aba):
                    evento.ignore()
                    return
        for aba in self.todas_as_abas():
            aba.encerrar()
        self.cfg["janela_maximizada"] = self.isMaximized()
        if not self.isMaximized():
            self.cfg["janela_largura"] = self.width()
            self.cfg["janela_altura"] = self.height()
        configuracao.gravar(self.cfg)
        log.info("encerrando")
        evento.accept()
