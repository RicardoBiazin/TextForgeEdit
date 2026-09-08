"""A janela: abas, abrir, salvar, salvar como, localizar e arrastar-e-soltar.

Ela conduz ABAS, e nao arquivos: tudo o que um arquivo aberto precisa mora na
`Aba` (ver `interface/aba.py`). E' o que faz "varias abas" ser uma lista em vez
de uma reescrita.
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QStatusBar, QTabWidget,
                               QVBoxLayout, QWidget)

from tfedit import (APP, AUTOR, VERSAO, busca, codificacao,
                    configuracao, conversao, linguagens,
                    log_interno, sessao as sessao_mod,
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

#: Comandos do editor que uma view SO' LEITURA sabe atender, e o nome que ela
#: usa. `selectAll` fica DE FORA de proposito: selecionar 1 GB so' teria
#: serventia se o copiar seguinte funcionasse, e ele nao pode (ver o teto de
#: copia do visor hexadecimal). Cair na mensagem "volte para o texto" e' mais
#: honesto que selecionar o arquivo inteiro para depois recusar copiar.
SO_LEITURA_NA_VIEW = {"copy": "copiar"}

#: Como cada view se chama para o usuario.
ROTULO_DA_VIEW = {"texto": "Texto", "hex": "Hexadecimal",
                  "tabela": "Tabela", "planilha": "Planilha"}


class _RotuloClicavel(QLabel):
    """Um campo do rodapé que responde ao clique.

    O rodapé é onde a pessoa JÁ está olhando para saber a codificação e a
    linguagem do arquivo. Obrigá-la a subir até a barra de menus para trocar
    o que está lendo ali é atravessar a janela inteira por uma informação que
    estava debaixo do cursor.

    O cursor de mãozinha e a dica não são enfeite: um rótulo de barra de
    status normalmente não faz nada ao ser clicado, então nada indicaria que
    este faz — o usuário nunca tentaria.
    """

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
        self.rotulo_view = _RotuloClicavel(
            "", "Como o arquivo está sendo mostrado. Clique para trocar.", self)
        self.rotulo_view.clicado.connect(self._menu_no_rodape_view)
        self.rotulo_linguagem = _RotuloClicavel(
            "", "Linguagem do realce. Clique para trocar.", self)
        self.rotulo_linguagem.clicado.connect(self._menu_no_rodape_linguagem)
        self.rotulo_codec = _RotuloClicavel(
            "", "Codificação e fim de linha. Clique para reinterpretar ou "
                "converter.", self)
        self.rotulo_codec.clicado.connect(self._menu_no_rodape_codificacao)
        self.rotulo_memoria = QLabel("", self)
        self.progresso = QProgressBar(self)
        self.progresso.setMaximumWidth(160)
        self.progresso.setTextVisible(False)
        self.progresso.hide()
        self.barra.addPermanentWidget(self.progresso)
        for rotulo in (self.rotulo_posicao, self.rotulo_view,
                       self.rotulo_linguagem, self.rotulo_codec,
                       self.rotulo_memoria):
            self.barra.addPermanentWidget(rotulo)

        # `addPermanentWidget`, e nao `addWidget`: a area dos widgets NAO
        # permanentes e' a mesma em que `showMessage()` desenha, e um credito
        # ali seria coberto -- ou empurrado -- a cada "Salvo: arquivo.txt".
        self.credito = _RotuloClicavel(
            f"Produzido por {AUTOR} · v{VERSAO}",
            f"{APP} {VERSAO}\nProduzido por {AUTOR}.\n"
            f"Clique para ver a licença e as versões.", self)
        self.credito.clicado.connect(self.sobre)
        self.barra.addPermanentWidget(self.credito)
        self.barra.showMessage("Abra um arquivo (Ctrl+O) ou arraste um para cá")

    # ==================================================================
    # Visualização
    # ==================================================================

    def _montar_menu_view(self) -> None:
        self._preencher_view(self.menu_view)

    def _menu_no_rodape_view(self):
        return self._abrir_no_rodape(self.rotulo_view, self._preencher_view)

    def _preencher_view(self, menu) -> None:
        """As visualizações disponíveis para o arquivo desta aba."""
        menu.clear()
        aba = self.aba_atual
        if aba is None:
            acao = menu.addAction("(nenhum arquivo aberto)")
            acao.setEnabled(False)
            return

        atual = aba.view_atual()
        grupo = QActionGroup(menu)
        grupo.setExclusive(True)
        for nome in ("texto", "hex", "tabela", "planilha"):
            if nome != "texto" and not self._pode_abrir_view(aba, nome):
                continue
            acao = menu.addAction(ROTULO_DA_VIEW[nome])
            acao.setCheckable(True)
            acao.setChecked(nome == atual)
            acao.triggered.connect(
                lambda _c=False, n=nome: self._trocar_view(n))
            grupo.addAction(acao)

    def _pode_abrir_view(self, aba, nome: str) -> bool:
        """A view existe nesta compilação e serve para este arquivo?

        O menu não lista o que não abre: uma entrada que não faz nada ao ser
        clicada é pior que uma entrada ausente.
        """
        if nome == "hex":
            return True
        return aba.tem_view(nome)

    def _trocar_view(self, nome: str) -> None:
        aba = self.aba_atual
        if aba is None or aba.view_atual() == nome:
            return
        if not aba.tem_view(nome) and not self._montar_view(aba, nome):
            return
        aba.trocar_para(nome)
        self._atualizar_rotulo_view()
        self._mostrar_posicao(aba.linha_atual(), 0)

    def _montar_view(self, aba, nome: str) -> bool:
        """Cria a view sob demanda. False quando não há como.

        Sob demanda, e não no arranque: montar a grade de um CSV enquanto a
        varredura ainda corre criaria o modelo contra um total de linhas que
        está crescendo, e o visor de um arquivo que ninguém vai abrir em
        hexadecimal é trabalho jogado fora.
        """
        if nome == "hex":
            from tfedit.interface.visualizadores.hex import VisorHexadecimal

            visor = VisorHexadecimal(aba.documento, aba.perfil, aba,
                                     tema=self.tema, cfg=self.cfg)
            visor.posicao_mudou.connect(self._mostrar_posicao)
            visor.recusou.connect(lambda m: self.barra.showMessage(m, 8000))
            aba.registrar_view("hex", visor)
            return True
        return False

    def _atualizar_rotulo_view(self) -> None:
        aba = self.aba_atual
        self.rotulo_view.setText(
            "" if aba is None else ROTULO_DA_VIEW.get(aba.view_atual(), ""))

    # ==================================================================
    # Codificação
    # ==================================================================

    def _montar_menu_codificacao(self) -> None:
        self._preencher_codificacao(self.menu_codificacao)

    def _preencher_codificacao(self, menu) -> None:
        """Dois grupos, com dois verbos, e a diferença escrita no menu.

        Juntar "reinterpretar" e "converter" num comando só foi o defeito
        relatado no editor irmão — a pessoa mandava converter, via o rótulo
        mudar e o arquivo continuar igual, ou o contrário. São operações
        diferentes: uma lê os mesmos bytes de outro jeito, a outra reescreve
        o arquivo inteiro.

        Recebe o menu em vez de usar o da barra porque o rodapé abre o MESMO
        menu ao clique. Duas montagens paralelas divergiriam na primeira
        codificação nova.
        """
        menu.clear()
        aba = self.aba_atual
        if aba is None:
            acao = menu.addAction("(nenhum arquivo aberto)")
            acao.setEnabled(False)
            return

        titulo = menu.addAction(f"Este arquivo está em {aba.perfil.rotulo}")
        titulo.setEnabled(False)
        menu.addSeparator()

        reler = menu.addMenu("&Reinterpretar como")
        reler.setToolTip("Lê os mesmos bytes de outro jeito. O arquivo no "
                         "disco não muda.")
        for alvo in conversao.ALVOS:
            acao = reler.addAction(alvo.rotulo)
            acao.setCheckable(True)
            acao.setChecked((aba.perfil.codec, aba.perfil.bom) == alvo.chave)
            acao.triggered.connect(
                lambda _c=False, a=alvo: self._reinterpretar(a))

        converter = menu.addMenu("&Converter para")
        converter.setToolTip("Reescreve o arquivo inteiro na codificação "
                             "escolhida.")
        for alvo in conversao.ALVOS:
            acao = converter.addAction(alvo.rotulo + "…")
            acao.setEnabled((aba.perfil.codec, aba.perfil.bom) != alvo.chave)
            acao.triggered.connect(
                lambda _c=False, a=alvo: self._converter(a))

    def _reinterpretar(self, alvo) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        try:
            aba.reinterpretar(alvo.codec, alvo.bom)
        except ValueError as exc:
            QMessageBox.warning(self, "Não é possível reinterpretar agora",
                                str(exc))
            return
        self.rotulo_codec.setText(
            f"{aba.perfil.rotulo}  {aba.perfil.rotulo_eol}")
        self.barra.showMessage(
            f"Lendo como {alvo.rotulo}. Nenhum byte do arquivo mudou — "
            f"use Converter para gravar nesta codificação.", 8000)

    def _converter(self, alvo) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        if aba.indexando_agora:
            self._avisar_indexando()
            return

        # O aviso não é cerimônia. A gravação comum copia os trechos intactos
        # byte a byte; converter obriga a decodificar e recodificar TUDO, e
        # num arquivo grande isso demora de verdade.
        mb = aba.original.tamanho / (1024 * 1024)
        aviso = (f"Converter <b>{aba.nome}</b> de {aba.perfil.rotulo} para "
                 f"<b>{alvo.rotulo}</b>.<br><br>"
                 f"Isto reescreve o arquivo inteiro ({mb:,.1f} MB). "
                 f"Diferente de salvar, aqui <b>todos</b> os bytes mudam, e "
                 f"não só os trechos editados.")
        if mb > 50:
            aviso += ("<br><br>Num arquivo deste tamanho a conversão leva "
                      "algum tempo, e a janela fica parada até terminar.")
        if QMessageBox.question(
                self, "Converter a codificação", aviso,
                QMessageBox.StandardButton.Ok
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel
        ) != QMessageBox.StandardButton.Ok:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            escritos = aba.converter_codificacao(alvo)
        except conversao.NaoRepresentavel as exc:
            QMessageBox.warning(
                self, "A conversão perderia caracteres",
                f"{exc}<br><br>O arquivo <b>não</b> foi alterado. "
                f"Para guardar esse texto, escolha uma codificação que o "
                f"aceite — o UTF-8 aceita qualquer caractere.")
            return
        except conversao.OrigemInvalida as exc:
            QMessageBox.warning(
                self, "A codificação de origem não confere",
                f"{exc}<br><br>O arquivo <b>não</b> foi alterado. Use "
                f"<b>Reinterpretar como</b> para dizer qual é a codificação "
                f"real e tente de novo.")
            return
        except SemEspaco as exc:
            QMessageBox.warning(self, "Espaço insuficiente", str(exc))
            return
        except ArquivoMudou as exc:
            QMessageBox.warning(
                self, "O arquivo mudou no disco",
                f"{exc}.<br><br>O arquivo <b>não</b> foi convertido.")
            return
        except (FalhaNaTroca, OSError) as exc:
            log.error("falha ao converter %s: %s", aba.nome, exc)
            QMessageBox.warning(self, "Não foi possível converter", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        self.rotulo_codec.setText(
            f"{aba.perfil.rotulo}  {aba.perfil.rotulo_eol}")
        self._atualizar_titulos()
        self.barra.showMessage(
            f"Convertido para {aba.perfil.rotulo}: {escritos:,} bytes "
            f"gravados em {aba.nome}".replace(",", "."), 8000)

    # ==================================================================
    # Linguagem
    # ==================================================================

    def _montar_menu_linguagem(self) -> None:
        self._preencher_linguagem(self.menu_linguagem)

    def _preencher_linguagem(self, menu) -> None:
        """Monta o menu SÓ quando ele abre.

        Vinte e quatro ações criadas no arranque custariam tempo de abertura
        para um menu que a maioria das sessões nunca usa. Recebe o menu porque
        o rodapé abre o mesmo conteúdo ao clique.
        """
        menu.clear()
        aba = self.aba_atual
        if aba is None:
            acao = menu.addAction("(nenhum arquivo aberto)")
            acao.setEnabled(False)
            return

        linguagens.carregar_embutidos()
        atual = aba.provedor.nome if aba.provedor is not None else ""
        grupo = QActionGroup(menu)
        grupo.setExclusive(True)
        for nome in sorted(registro_de_linguagens.REGISTRO.nomes()):
            acao = menu.addAction(nome)
            acao.setCheckable(True)
            acao.setChecked(nome == atual)
            acao.triggered.connect(
                lambda _c=False, n=nome: self._trocar_linguagem(n))
            grupo.addAction(acao)

    def _abrir_no_rodape(self, rotulo, preencher):
        """Abre um menu ANCORADO no rótulo do rodapé. Devolve o menu.

        Ancorado ACIMA do rótulo, e não sob o cursor: o rodapé fica na borda de
        baixo da tela, e um menu que desce nasce fora do monitor. O Qt corrige
        sozinho, mas empurrando o menu para um canto longe do que foi clicado.

        `popup`, e não `exec`: `exec` abre um laço de eventos aninhado e só
        volta quando o menu fecha. Num editor que indexa em thread e desliza a
        fatia, congelar o laço principal por um menu de rodapé é pedir
        problema — e um `exec` também travaria a suíte, que não tem quem
        feche o menu.

        O menu se destrói ao fechar; guardá-lo em `self` faria o próximo clique
        vazar o anterior.
        """
        menu = QMenu(self)
        preencher(menu)
        menu.aboutToHide.connect(menu.deleteLater)
        ponto = rotulo.mapToGlobal(rotulo.rect().topLeft())
        menu.popup(QPoint(ponto.x(), ponto.y() - menu.sizeHint().height()))
        return menu

    def _menu_no_rodape_codificacao(self):
        return self._abrir_no_rodape(self.rotulo_codec,
                                     self._preencher_codificacao)

    def _menu_no_rodape_linguagem(self):
        return self._abrir_no_rodape(self.rotulo_linguagem,
                                     self._preencher_linguagem)

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
                aba.ir_para_linha(guardada.linha)

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
            self.aba_atual.ir_para_linha(linha - 1)

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

        self.menu_view = self.menuBar().addMenu("&Visualizar")
        self.menu_view.aboutToShow.connect(self._montar_menu_view)

        self.menu_codificacao = self.menuBar().addMenu("&Codificação")
        self.menu_codificacao.aboutToShow.connect(self._montar_menu_codificacao)

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
        aba.sincronizar()
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
            self.rotulo_view.clear()
            self.rotulo_linguagem.clear()
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
        self._atualizar_rotulo_view()
        self._mostrar_posicao(aba.linha_atual(), 0)
        self.progresso.setVisible(aba.indexando_agora)
        self._atualizar_titulos()
        aba.focar_view_atual()

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
        aba.ao_indexar()

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
        # Sem selecao quando a view nao e' o texto: `textCursor()` daria a
        # selecao do editor ESCONDIDO, que nao e' o que esta' na tela.
        selecao = ("" if aba is None or aba.view_atual() != "texto"
                   else aba.editor.textCursor().selectedText())
        self.barra_busca.focar(selecao, no_substituir=no_substituir)

    def _focar_editor(self) -> None:
        aba = self.aba_atual
        if aba is not None:
            aba.focar_view_atual()

    def _procurar(self, criterio: busca.Criterio, para_tras: bool) -> None:
        aba = self.aba_atual
        if aba is None:
            return
        if not self._exigir_modo_texto(aba, "A busca"):
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
        if not self._exigir_modo_texto(aba, "A substituição"):
            return
        aba.sincronizar()

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
        if aba.view_atual() == "hex":
            self._ir_para_deslocamento(aba)
            return
        total = aba.documento.total_de_linhas
        numero, ok = QInputDialog.getInt(
            self, "Ir para linha", f"Linha (1 a {total:,}):".replace(",", "."),
            aba.linha_atual() + 1, 1, total)
        if ok:
            aba.ir_para_linha(numero - 1)

    def _ir_para_deslocamento(self, aba) -> None:
        """No hexadecimal, "ir para" é por byte, e não por linha.

        Reusa o Ctrl+G em vez de inventar um segundo atalho: é o mesmo gesto
        ("me leve a um lugar"), e a unidade certa muda com a visualização.
        """
        from PySide6.QtWidgets import QInputDialog

        texto, ok = QInputDialog.getText(
            self, "Ir para deslocamento",
            f"Deslocamento em bytes (0 a {aba.documento.tamanho:,}), "
            f"decimal ou 0x…:".replace(",", "."))
        if not ok or not texto.strip():
            return
        try:
            # `int(texto, 0)` aceita "1024" e "0x400". NUNCA `eval`: um arquivo
            # aberto -- e o que o usuário digita sobre ele -- é DADO, nunca
            # código. Ver o CLAUDE.md.
            offset = int(texto.strip(), 0)
        except ValueError:
            self.barra.showMessage(
                f"“{texto.strip()}” não é um número. Use 1024 ou 0x400.", 8000)
            return
        if not 0 <= offset <= aba.documento.tamanho:
            self.barra.showMessage(
                f"O deslocamento precisa estar entre 0 e "
                f"{aba.documento.tamanho:,}.".replace(",", "."), 8000)
            return
        aba.view("hex").ir_para_offset(offset)

    def _exigir_modo_texto(self, aba, o_que: str) -> bool:
        """Volta para o texto quando o comando so' existe la'. False se desistiu.

        Busca e substituicao trabalham em (linha, coluna de CARACTERE). Mapear
        isso para faixa de bytes no hexadecimal exigiria recodificar o prefixo
        de cada linha, e `_substituir_todas` mexe direto na tabela de pecas.
        Recusar em silencio seria pior que voltar para o texto avisando.
        """
        view = aba.view_atual()
        if view == "texto":
            return True
        if not aba.trocar_para("texto"):
            return False
        self.barra.showMessage(
            f"{o_que} funciona no modo texto — voltando para ele.", 6000)
        return True

    def _no_editor(self, metodo: str) -> None:
        """Executa o metodo no editor -- ou o equivalente da VIEW ATIVA.

        O `QShortcutMap` do Qt resolve o atalho de menu ANTES de o evento
        chegar ao widget em foco. Sem este desvio, com o hexadecimal na frente,
        o Ctrl+V do menu INSERE texto na fatia do editor escondido -- marcando
        como modificado um arquivo que a pessoa estava apenas lendo -- e o
        Ctrl+C copia a selecao desse editor, que esta' vazia.

        O projeto irmao teve os dois defeitos; aqui seriam piores, porque o
        editor escondido nao esta' vazio: ele carrega uma fatia de verdade.
        """
        aba = self.aba_atual
        if aba is None:
            return
        view = aba.view_atual()
        if view == "texto":
            getattr(aba.editor, metodo)()
            return

        widget = aba.view(view)
        equivalente = SO_LEITURA_NA_VIEW.get(metodo)
        if equivalente is not None and hasattr(widget, equivalente):
            getattr(widget, equivalente)()
            return

        if getattr(widget, "editavel", False):
            self.barra.showMessage(
                "Este comando é do editor de texto. Nesta visualização, edite "
                "clicando na célula.", 6000)
        else:
            self.barra.showMessage(
                f"“{ROTULO_DA_VIEW.get(view, view)}” é somente leitura. Volte "
                f"para o texto para usar este comando.", 6000)

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
            aba.sincronizar()
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
