"""A janela: abas, abrir, salvar, salvar como, localizar e arrastar-e-soltar.

Ela conduz ABAS, e nao arquivos: tudo o que um arquivo aberto precisa mora na
`Aba` (ver `interface/aba.py`). E' o que faz "varias abas" ser uma lista em vez
de uma reescrita.
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QIcon, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (QApplication, QFileDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox,
                               QProgressBar, QStatusBar, QTabWidget,
                               QVBoxLayout, QWidget)

from tfedit import janela as janela_viva
from tfedit import seguranca
from tfedit import (APP, AUTOR, VERSAO, busca, codificacao,
                    configuracao, conversao, linguagens,
                    log_interno, sessao as sessao_mod,
                    tema as tema_mod)
from tfedit.linguagens import registro as registro_de_linguagens
from tfedit.gravacao import FalhaNaTroca, SemEspaco
from tfedit.original import ArquivoMudou
from tfedit.interface.aba import (Aba, NaoEPlanilha, SemDestino,
                                 criar_rascunho, limpar_rascunhos_antigos)
from tfedit.interface import icones
from tfedit.interface.barra_busca import BarraDeBusca

log = log_interno.obter(__name__)

FILTRO = ("Arquivos de texto (*.txt *.log *.csv *.dat *.json *.xml *.sql "
          "*.md);;Planilhas (*.xlsx *.xlsm);;Todos os arquivos (*)")

#: Teto de substituicoes de uma vez, quando a configuracao nao diz outro.
#:
#: Trocar 3 milhoes de ocorrencias uma a uma na tabela de pecas levaria muito
#: tempo com a interface parada; o teto transforma isso num aviso em vez de num
#: travamento.
#:
#: A chave `limite_de_substituicoes` ESTAVA declarada na configuracao e era
#: ignorada: o codigo usava esta constante direto. O usuario podia edita-la e
#: nada acontecia -- o pior tipo de opcao, a que finge existir.
TETO_DE_SUBSTITUICOES = 100_000

#: Comandos do editor que uma view SO' LEITURA sabe atender, e o nome que ela
#: usa. `selectAll` fica DE FORA de proposito: selecionar 1 GB so' teria
#: serventia se o copiar seguinte funcionasse, e ele nao pode (ver o teto de
#: copia do visor hexadecimal). Cair na mensagem "volte para o texto" e' mais
#: honesto que selecionar o arquivo inteiro para depois recusar copiar.
SO_LEITURA_NA_VIEW = {"copy": "copiar"}

#: Comandos de EDICAO que uma view editavel atende, e o nome que ela usa.
#:
#: Sem este mapa, o Ctrl+Z com a grade na frente caia na mensagem "este comando
#: e' do editor de texto" -- inclusive no CSV, onde o desfazer EXISTIA na tabela
#: de pecas e so' nao era alcancado. Reusa os mesmos atalhos em vez de inventar
#: um segundo Ctrl+Z por visualizacao.
EDICAO_NA_VIEW = {"undo": "desfazer", "redo": "refazer"}

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

        #: Quantos documentos novos esta janela ja' criou. Nao volta a zero
        #: ao fechar uma aba: dois "Sem título 1" na mesma janela seriam dois
        #: rascunhos com o mesmo nome, e o usuário não saberia qual é qual.
        self._contador_de_novos = 0

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
        self._montar_barra_de_atalhos()

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
    # Comparar
    # ==================================================================

    def comparar_arquivos(self) -> None:
        """Compara dois arquivos lado a lado, numa janela própria.

        Parte do arquivo da aba atual quando há um: comparar quase sempre é
        "este contra aquele", e obrigar a escolher os dois seria um clique a
        mais em todo uso.
        """
        aba = self.aba_atual
        if aba is not None and aba.e_planilha:
            self.barra.showMessage(
                "Comparar vale para arquivos de texto. Uma planilha é um "
                "pacote ZIP: compare depois de exportar em CSV.", 8000)
            return

        primeiro = None if aba is None or aba.e_rascunho else aba.caminho
        if primeiro is None:
            escolhido, _ = QFileDialog.getOpenFileName(
                self, "Comparar: primeiro arquivo",
                self._pasta_inicial(aba), FILTRO)
            if not escolhido:
                return
            primeiro = pathlib.Path(escolhido)

        segundo, _ = QFileDialog.getOpenFileName(
            self, f"Comparar {primeiro.name} com...",
            self._pasta_inicial(aba), FILTRO)
        if not segundo:
            return
        self.comparar(primeiro, pathlib.Path(segundo))

    def comparar(self, caminho_a, caminho_b) -> bool:
        """O trabalho de comparar. Separado para o teste não abrir diálogo."""
        from tfedit import codificacao, comparacao as nucleo
        from tfedit.interface.comparacao import JanelaDeComparacao
        from tfedit.original import Original
        from tfedit.pecas import Documento

        caminho_a, caminho_b = pathlib.Path(caminho_a), pathlib.Path(caminho_b)
        if Aba.chave_de(caminho_a) == Aba.chave_de(caminho_b):
            self.barra.showMessage(
                "Os dois caminhos são o mesmo arquivo.", 6000)
            return False

        abertos = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            documentos = []
            perfis = []
            for caminho in (caminho_a, caminho_b):
                original = Original(caminho)
                abertos.append(original)
                # O índice INTEIRO, e não só a partida: comparar precisa do
                # total de linhas dos dois lados antes de começar.
                original.indexar()
                documentos.append(Documento(original))
                perfis.append(codificacao.detectar(
                    original.ler(0, codificacao.SONDAGEM)))

            teto = int(self.cfg.get("limite_de_comparacao",
                                    nucleo.TETO_DE_LINHAS))
            comp = nucleo.comparar(documentos[0], documentos[1], teto=teto)
        except nucleo.GrandeDemais as exc:
            for original in abertos:
                original.fechar()
            QMessageBox.warning(self, "Arquivos grandes demais", str(exc))
            return False
        except OSError as exc:
            for original in abertos:
                original.fechar()
            QMessageBox.warning(self, "Não foi possível comparar", str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()

        janela = JanelaDeComparacao(
            comp, documentos[0], documentos[1],
            caminho_a.name, caminho_b.name, perfis[0], perfis[1],
            tema=self.tema, cfg=self.cfg, parent=self)
        # Os mmap morrem com a janela: sem isto os dois arquivos ficariam
        # travados no Windows até o programa fechar.
        janela.destroyed.connect(
            lambda *_: [original.fechar() for original in abertos])
        janela.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        janela.show()
        self._comparacoes = getattr(self, "_comparacoes", [])
        self._comparacoes.append(janela)
        self.barra.showMessage(comp.resumo.descrever(), 8000)
        return True

    # ==================================================================
    # Configurações
    # ==================================================================

    def abrir_configuracoes(self) -> None:
        from tfedit.interface.configuracoes import Configuracoes

        dialogo = Configuracoes(self.cfg, self,
                                botoes_disponiveis=self.botoes_da_barra())
        if dialogo.exec() != Configuracoes.DialogCode.Accepted:
            return

        antes = dict(self.cfg)
        self.cfg = dialogo.valores()
        if not configuracao.gravar(self.cfg):
            QMessageBox.warning(
                self, "Não foi possível salvar as preferências",
                "As mudanças valem para esta sessão, mas não foram gravadas "
                "no disco. Veja o log para o motivo.")
        self.aplicar_configuracao(antes)

    def botoes_da_barra(self) -> tuple:
        """(chave, rótulo) de tudo o que a barra pode mostrar.

        É o que a tela de Configurações lista para marcar e desmarcar. Sai do
        catálogo dos ícones e da tabela de comandos abaixo, e não de uma lista
        escrita à mão: um botão novo aparece na tela sozinho.
        """
        return tuple((chave, icones.CATALOGO[chave][0])
                     for chave in self._comandos_da_barra()
                     if chave in icones.CATALOGO)

    def _comandos_da_barra(self) -> dict:
        """chave -> (o que fazer, dica). A ORDEM aqui é a da tela.

        `comparar` NÃO está aqui ainda: um botão que abre "não implementado"
        é a mesma "opção que finge existir" que a tela de Configurações existe
        para acabar. Ele entra quando a comparação entrar.
        """
        return {
            "novo": (self.novo, "Novo documento (Ctrl+N)"),
            "abrir": (self.abrir, "Abrir arquivo (Ctrl+O)"),
            "salvar": (self.salvar, "Salvar (Ctrl+S)"),
            "salvar_tudo": (self.salvar_tudo, "Salvar tudo (Ctrl+Shift+S)"),
            "desfazer": (lambda: self._no_editor("undo"), "Desfazer (Ctrl+Z)"),
            "refazer": (lambda: self._no_editor("redo"), "Refazer (Ctrl+Y)"),
            "recortar": (lambda: self._no_editor("cut"), "Recortar (Ctrl+X)"),
            "copiar": (lambda: self._no_editor("copy"), "Copiar (Ctrl+C)"),
            "colar": (lambda: self._no_editor("paste"), "Colar (Ctrl+V)"),
            "localizar": (self.abrir_busca, "Localizar (Ctrl+F)"),
            "substituir": (self.abrir_substituir, "Substituir (Ctrl+H)"),
            "visualizar": (self._menu_no_rodape_view,
                           "Trocar a visualização"),
            "formatar": (self.formatar_documento,
                         "Formatar documento (Shift+Alt+F)"),
            "comparar": (self.comparar_arquivos,
                         "Comparar dois arquivos (Ctrl+D)"),
        }

    def _montar_barra_de_atalhos(self) -> None:
        """Constrói a barra a partir da configuração, na ORDEM salva.

        Refeita do zero a cada chamada -- é o que faz a personalização valer na
        hora, sem reiniciar. Uma chave desconhecida é ignorada em silêncio: uma
        configuração de uma versão futura não pode impedir o programa de abrir.
        """
        from PySide6.QtWidgets import QToolBar

        barra = getattr(self, "barra_atalhos", None)
        if barra is None:
            barra = QToolBar("Atalhos", self)
            barra.setObjectName("barra_atalhos")
            barra.setMovable(False)
            barra.setIconSize(QSize(20, 20))
            self.addToolBar(barra)
            self.barra_atalhos = barra
        barra.clear()

        comandos = self._comandos_da_barra()
        cor = self.tema.cor("janela.texto")
        # Os separadores marcam os GRUPOS: arquivo, edição, busca, views. Sem
        # eles treze botões viram uma fileira indistinta.
        grupos = {"desfazer", "recortar", "localizar", "visualizar"}

        escolhidos = [c for c in self.cfg.get("botoes_da_barra", ())
                      if c in comandos]
        primeiro = True
        for chave in escolhidos:
            tratador, dica = comandos[chave]
            if chave in grupos and not primeiro:
                barra.addSeparator()
            acao = QAction(icones.icone(chave, cor) or QIcon(),
                           icones.CATALOGO[chave][0], self)
            acao.setToolTip(dica)
            acao.setStatusTip(dica)
            acao.triggered.connect(tratador)
            barra.addAction(acao)
            primeiro = False

        barra.setVisible(bool(escolhidos)
                         and bool(self.cfg.get("mostrar_barra", True)))

    def aplicar_configuracao(self, antes: dict) -> None:
        """Faz valer AGORA o que a tela mudou.

        Sem isto, trocar o tema ou o número de linha só valeria para os
        arquivos abertos depois -- e a conclusão natural seria que a opção não
        funciona. O que não dá para aplicar (os limites de leitura, já usados
        na abertura) a própria tela avisa.
        """
        if self.cfg.get("tema") != antes.get("tema"):
            self.tema = tema_mod.resolver(str(self.cfg.get("tema", "sistema")))
            for aba in self.todas_as_abas():
                aba.aplicar_tema(self.tema)
                if aba.editor is not None:
                    aba.editor.tema = self.tema
                    aba.editor.aplicar_cores()
                    if getattr(aba.editor, "pintor", None) is not None:
                        aba.editor.pintor.definir_tema(self.tema)
                        aba.editor.pintor.rehighlight()

        for aba in self.todas_as_abas():
            aba.cfg = self.cfg
            if aba.editor is not None:
                aba.editor.aplicar_configuracao(self.cfg)

        # A barra e' refeita do zero: a personalizacao vale na hora, e o
        # tema novo repinta os icones.
        self._montar_barra_de_atalhos()
        self.barra.showMessage("Preferências salvas.", 5000)
        log.info("configuracao aplicada: tema=%s, numero de linha=%s",
                 self.cfg.get("tema"), self.cfg.get("numero_de_linha"))

    # ==================================================================
    # Formatar
    # ==================================================================

    def _ajustar_menu_formatar(self) -> None:
        """Desabilita com o MOTIVO na dica, em vez de falhar depois do clique.

        O usuário escolheu isto: acima do teto o comando aparece desabilitado
        dizendo por quê, e não tenta.
        """
        aba = self.aba_atual
        motivo = self._por_que_nao_formata(aba)
        for acao in self.menu_formatar.actions():
            if acao.isSeparator():
                continue
            acao.setEnabled(motivo is None)
            acao.setToolTip(motivo or "")
        self.menu_formatar.setToolTipsVisible(True)

    def _por_que_nao_formata(self, aba) -> str | None:
        """None quando dá para formatar; senão, a explicação."""
        if aba is None:
            return "Nenhum arquivo aberto."
        if aba.e_planilha:
            return "Uma planilha não é código."
        if aba.indexando_agora:
            return "Aguarde a varredura do arquivo terminar."
        if aba.provedor is None or aba.provedor.formatador() is None:
            nome = aba.nome_da_linguagem if aba.provedor else "Texto"
            return (f"Não há formatador para {nome}. Use o menu Linguagem "
                    f"para escolher outra.")

        teto = seguranca.LIMITE_DE_ENTRADA_MB * 1024 * 1024
        if aba.documento.tamanho > teto:
            # Formatar exige o documento INTEIRO como texto na memória: os
            # formatadores recebem `str` e devolvem `str`, e não existe versão
            # em streaming disso. O teto é o limite honesto dessa técnica.
            return (f"O arquivo tem "
                    f"{aba.documento.tamanho / (1024 * 1024):.0f} MB e o "
                    f"limite para formatar é de "
                    f"{seguranca.LIMITE_DE_ENTRADA_MB} MB — formatar exige o "
                    f"texto inteiro na memória.")
        return None

    def _recusar_formatacao(self, aba) -> bool:
        motivo = self._por_que_nao_formata(aba)
        if motivo is None:
            return False
        self.barra.showMessage(motivo, 8000)
        return True

    def formatar_documento(self) -> None:
        self._formatar(compactando=False)

    def compactar_documento(self) -> None:
        self._formatar(compactando=True)

    def _formatar(self, *, compactando: bool) -> None:
        """Formata o documento inteiro em UMA operação de desfazer.

        O editor só tem a fatia, então o resultado não pode ser aplicado por
        ele: vai direto à tabela de peças.

        E vai APARADO. `_prefixo_comum`/`_sufixo_comum` são os mesmos da janela
        viva, e dão de graça uma propriedade valiosa: reformatar um arquivo que
        já está formatado é **no-op** — não mexe na tabela, não marca a aba
        como suja e não mexe na data do arquivo ao salvar.
        """
        aba = self.aba_atual
        if self._recusar_formatacao(aba):
            return
        aba.sincronizar()

        formatador = aba.provedor.formatador()
        antigos = aba.documento.ler(0, aba.documento.tamanho)
        try:
            texto = antigos.decode(aba.perfil.codec)
        except UnicodeDecodeError as erro:
            self.barra.showMessage(
                f"O arquivo não é texto válido em {aba.perfil.rotulo} "
                f"({erro}). Reinterprete a codificação antes de formatar.",
                8000)
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            opcoes = {"usa_espacos": True,
                      "largura": int(self.cfg.get("tabulacao", 4)),
                      "comprimento_de_linha": 100}
            saida = (formatador.compactar(texto, opcoes) if compactando
                     else formatador.formatar(texto, opcoes))
        except Exception as exc:              # noqa: BLE001 - motor de terceiro
            log.error("formatador de %s falhou: %s", aba.nome_da_linguagem, exc)
            QMessageBox.warning(self, "Não foi possível formatar", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not self._aplicar_saida(aba, saida, antigos):
            return

    def _aplicar_saida(self, aba, saida, antigos: bytes) -> bool:
        from tfedit.formatadores.base import ErroDeSintaxe, Recusa

        if isinstance(saida, ErroDeSintaxe):
            self._mostrar_erro_de_sintaxe(aba, saida)
            return False
        if isinstance(saida, Recusa):
            self.barra.showMessage(saida.descrever(), 8000)
            return False

        try:
            novos = saida.texto.encode(aba.perfil.codec)
        except UnicodeEncodeError as erro:
            self.barra.showMessage(
                f"O texto formatado tem um caractere que não existe em "
                f"{aba.perfil.rotulo} ({erro.object[erro.start]!r}). "
                f"O arquivo não foi alterado.", 8000)
            return False

        inicio = janela_viva._prefixo_comum(antigos, novos)
        fim_antigo, fim_novo = janela_viva._sufixo_comum(antigos, novos, inicio)
        if inicio == fim_antigo == len(antigos):
            self.barra.showMessage("O arquivo já estava formatado.", 5000)
            return False

        with aba.documento.agrupar():
            aba.documento.substituir(inicio, fim_antigo - inicio,
                                     novos[inicio:fim_novo])
        aba.editor.recarregar(aba.editor.linha_atual_no_documento())
        aba.ao_indexar()
        self._atualizar_titulos()
        mudou = fim_antigo - inicio
        self.barra.showMessage(
            f"Formatado: {mudou:,} bytes trocados, num único passo de "
            f"desfazer.".replace(",", "."), 6000)
        return True

    def formatar_selecao(self) -> None:
        """Formata só o trecho selecionado.

        É o caso que encaixa na arquitetura sem ressalva: a seleção está na
        fatia, não passa por teto nenhum e sai pelo caminho normal de edição do
        editor — um `beginEditBlock`, um Ctrl+Z.
        """
        aba = self.aba_atual
        if self._recusar_formatacao(aba):
            return
        cursor = aba.editor.textCursor()
        if not cursor.hasSelection():
            self.barra.showMessage(
                "Selecione o trecho a formatar, ou use Formatar Documento.",
                6000)
            return

        trecho = cursor.selectedText().replace("\u2029", "\n")
        formatador = aba.provedor.formatador()
        saida = formatador.formatar(
            trecho, {"usa_espacos": True,
                     "largura": int(self.cfg.get("tabulacao", 4)),
                     "comprimento_de_linha": 100})
        from tfedit.formatadores.base import Resultado

        if not isinstance(saida, Resultado):
            self.barra.showMessage(saida.descrever(), 8000)
            return
        cursor.beginEditBlock()
        cursor.insertText(saida.texto)
        cursor.endEditBlock()
        self.barra.showMessage("Seleção formatada.", 5000)

    def validar_documento(self) -> None:
        aba = self.aba_atual
        if self._recusar_formatacao(aba):
            return
        aba.sincronizar()
        texto = aba.documento.ler(0, aba.documento.tamanho).decode(
            aba.perfil.codec, errors="replace")
        erro = aba.provedor.formatador().validar(texto)
        if erro is None:
            self.barra.showMessage(
                f"{aba.nome_da_linguagem}: sintaxe válida.", 6000)
            return
        self._mostrar_erro_de_sintaxe(aba, erro)

    def _mostrar_erro_de_sintaxe(self, aba, erro) -> None:
        """Sem painel de problemas: uma caixa que leva ao erro.

        Um painel próprio é outro projeto; o que não pode é o erro sumir num
        rodapé que a pessoa não estava olhando.
        """
        caixa = QMessageBox(self)
        caixa.setIcon(QMessageBox.Icon.Warning)
        caixa.setWindowTitle("Erro de sintaxe")
        caixa.setText(erro.descrever())
        ir = caixa.addButton("Ir para o erro", QMessageBox.ButtonRole.AcceptRole)
        caixa.addButton("Fechar", QMessageBox.ButtonRole.RejectRole)
        caixa.exec()
        if caixa.clickedButton() is ir and getattr(erro, "linha", 0):
            aba.ir_para_linha(max(0, erro.linha - 1))

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
            # "texto" tambem passa pela conferencia: uma aba de planilha nao
            # tem editor, e oferecer "Texto" nela levaria a um widget que nao
            # existe.
            if not self._pode_abrir_view(aba, nome):
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
        if nome == "texto":
            return aba.tem_view("texto")
        if aba.e_planilha:
            return nome == "planilha"
        if nome == "hex":
            return True
        if aba.e_planilha:
            # Numa planilha so' existe a grade: as outras views leem da tabela
            # de pecas, que aqui nao existe.
            return nome == "planilha"
        if nome == "planilha":
            return False
        if nome == "tabela":
            # Enquanto a varredura corre, o total de linhas ainda cresce: a
            # grade abriria mostrando uma fracao do arquivo. E uma coluna so'
            # nao e' tabela.
            return (not aba.indexando_agora
                    and aba.dialeto_csv() is not None)
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

        if nome == "tabela":
            from tfedit.interface.visualizadores.grade_csv import GradeCsv

            dialeto = aba.dialeto_csv()
            if dialeto is None:
                self.barra.showMessage(
                    "Este arquivo não parece uma tabela: não foi possível "
                    "reconhecer um separador de colunas.", 8000)
                return False
            grade = GradeCsv(aba.documento, aba.perfil, dialeto, aba,
                             tema=self.tema, cfg=self.cfg)
            grade.aplicar_tema(self.tema)
            grade.posicao_mudou.connect(self._mostrar_posicao)
            grade.recusou.connect(lambda m: self.barra.showMessage(m, 8000))
            grade.sujou.connect(self._atualizar_titulos)
            aba.registrar_view("tabela", grade)
            self.barra.showMessage(
                f"Tabela: {dialeto.descrever()}.", 8000)
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
        acao("&Novo", QKeySequence.StandardKey.New, self.novo, arquivo)
        acao("&Abrir...", QKeySequence.StandardKey.Open, self.abrir, arquivo)
        acao("&Salvar", QKeySequence.StandardKey.Save, self.salvar, arquivo)
        acao("Salvar &como...", QKeySequence.StandardKey.SaveAs,
             self.salvar_como, arquivo)
        acao("Salvar &tudo", "Ctrl+Shift+S", self.salvar_tudo, arquivo)
        arquivo.addSeparator()
        acao("&Fechar aba", QKeySequence.StandardKey.Close,
             lambda: self.fechar_aba(self.abas.currentIndex()), arquivo)
        arquivo.addSeparator()
        acao("&Configurações...", "Ctrl+,", self.abrir_configuracoes, arquivo)
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

        formatar = self.menuBar().addMenu("&Formatar")
        acao("&Documento", "Shift+Alt+F", self.formatar_documento, formatar)
        acao("Formatar &seleção", "Ctrl+K, Ctrl+F", self.formatar_selecao,
             formatar)
        formatar.addSeparator()
        acao("&Compactar documento", "", self.compactar_documento, formatar)
        acao("&Validar sintaxe", "Ctrl+Shift+V", self.validar_documento,
             formatar)
        formatar.aboutToShow.connect(self._ajustar_menu_formatar)
        self.menu_formatar = formatar

        ferramentas = self.menuBar().addMenu("&Ferramentas")
        acao("&Comparar arquivos...", "Ctrl+D", self.comparar_arquivos,
             ferramentas)

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

    def _pasta_inicial(self, aba=None) -> str:
        """Onde os diálogos de arquivo começam.

        A pasta padrão das Configurações vence; sem ela, a pasta do arquivo
        atual; sem arquivo, o que o sistema escolher.
        """
        pasta = str(self.cfg.get("pasta_padrao", "") or "")
        if pasta and pathlib.Path(pasta).is_dir():
            return pasta
        if aba is not None and not aba.e_rascunho:
            return str(aba.caminho.parent)
        return ""

    def abrir(self) -> None:
        caminhos, _ = QFileDialog.getOpenFileNames(
            self, "Abrir", self._pasta_inicial(self.aba_atual), FILTRO)
        for caminho in caminhos:
            self.abrir_arquivo(caminho)

    def _ligar_aba(self, aba) -> None:
        aba.posicao_mudou.connect(self._mostrar_posicao)
        aba.titulo_mudou.connect(self._atualizar_titulos)
        aba.indexando.connect(self._ao_indexar)
        aba.indexou.connect(self._ao_terminar_indice)

    def novo(self) -> bool:
        """Um documento em branco, pronto para digitar.

        Ele nasce como um ARQUIVO vazio numa pasta interna -- ver
        `aba.criar_rascunho`. Assim o documento novo passa exatamente pelo mesmo
        caminho de um arquivo de 1 GB: mesma tabela de peças, mesmo desfazer,
        mesma gravação.
        """
        self._contador_de_novos += 1
        nome = f"Sem título {self._contador_de_novos}"
        try:
            caminho = criar_rascunho(self._contador_de_novos)
        except OSError as exc:
            log.error("nao foi possivel criar o rascunho: %s", exc)
            QMessageBox.warning(
                self, "Não foi possível criar o documento",
                f"Não deu para criar o arquivo de trabalho: {exc}")
            return False

        aba = Aba(caminho, self.cfg, self, tema=self.tema, sem_titulo=nome)
        self._ligar_aba(aba)
        indice = self.abas.addTab(aba, aba.titulo)
        self.abas.setTabToolTip(
            indice, "Documento novo — ainda não salvo em disco")
        self.abas.setCurrentIndex(indice)
        aba.focar_view_atual()
        self.barra.showMessage(
            f"{nome}: digite à vontade. Ctrl+S pergunta onde salvar.", 6000)
        log.info("documento novo: %s (%s)", nome, caminho)
        return True

    def _fechar_rascunho_intocado(self) -> None:
        """Some com o "Sem título" vazio quando um arquivo de verdade chega.

        Sem isto, abrir um arquivo logo depois de iniciar deixaria a aba em
        branco encostada ali para sempre, e o editor acumularia uma por sessão.
        Só o INTOCADO sai: um rascunho em que alguém digitou é trabalho.
        """
        for aba in list(self.todas_as_abas()):
            if aba.rascunho_intocado and self.abas.count() > 1:
                indice = self.abas.indexOf(aba)
                self.abas.removeTab(indice)
                aba.encerrar()
                aba.deleteLater()

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
        except NaoEPlanilha as exc:
            # A extensao prometia planilha e o conteudo nao e' uma. Abrir como
            # arquivo comum e' melhor que recusar: a pessoa ao menos ve' o que
            # ha' ali dentro.
            log.warning("%s", exc)
            QMessageBox.warning(
                self, "Não é uma planilha",
                f"{exc}<br><br>Ele será aberto como arquivo comum.")
            try:
                aba = Aba(caminho, {**self.cfg, "limite_planilha_mb": 0},
                          self, tema=self.tema)
            except OSError as outro:
                QMessageBox.warning(self, "Não foi possível abrir", str(outro))
                return False
        except OSError as exc:
            log.warning("nao foi possivel abrir %s: %s", caminho, exc)
            QMessageBox.warning(self, "Não foi possível abrir", str(exc))
            return False

        self._ligar_aba(aba)
        configuracao.registrar_recente(self.cfg, caminho)
        indice = self.abas.addTab(aba, aba.titulo)
        self.abas.setTabToolTip(indice, str(aba.caminho))
        self.abas.setCurrentIndex(indice)
        # DEPOIS do `addTab`: a guarda de "mais de uma aba" so' faz sentido com
        # o arquivo novo ja' na janela. Antes disso ha' apenas o rascunho, e
        # fecha-lo deixaria a janela sem aba nenhuma por um instante.
        self._fechar_rascunho_intocado()
        if aba.indexando_agora:
            self.progresso.setRange(0, 100)
            self.progresso.setValue(0)
            self.progresso.show()
            self.barra.showMessage(
                f"{aba.nome}: indexando... dá para ler e rolar; editar libera "
                f"no fim.")
        elif not aba.e_planilha:
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
        if aba.e_planilha:
            # Codificacao e linguagem nao significam nada num pacote ZIP.
            self.rotulo_codec.clear()
            self.rotulo_linguagem.clear()
        else:
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
        if aba is None:
            return False
        if aba.e_rascunho:
            # Ctrl+S num documento novo PERGUNTA onde salvar, em vez de recusar.
            # Gravar no arquivo de trabalho esconderia o texto numa pasta
            # interna, e a pessoa nunca mais o encontraria.
            return self.salvar_como()
        return self._gravar(aba)

    def salvar_como(self) -> bool:
        aba = self.aba_atual
        if aba is None:
            return False
        if aba.indexando_agora:
            self._avisar_indexando()
            return False
        # Num rascunho, o diálogo abre na pasta de documentos com um nome
        # sugerido -- e não na pasta interna onde mora o arquivo de trabalho,
        # que não é lugar para o usuário salvar nada.
        if aba.e_rascunho:
            from PySide6.QtCore import QStandardPaths

            pasta = (self._pasta_inicial()
                     or QStandardPaths.writableLocation(
                         QStandardPaths.StandardLocation.DocumentsLocation)
                     or "")
            partida = str(pathlib.Path(pasta) / f"{aba.nome}.txt")
        else:
            partida = str(aba.caminho)
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Salvar como", partida, FILTRO)
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

        teto = int(self.cfg.get("limite_de_substituicoes",
                                TETO_DE_SUBSTITUICOES))
        quantas, cortou = busca.contar(aba.documento, criterio,
                                       aba.perfil.codec, teto=teto)
        if not quantas:
            self.barra_busca.dizer("não encontrado", erro=True)
            return
        aviso = (f"<b>{quantas:,}</b> ocorrência(s) de "
                 f"<b>{criterio.texto}</b> serão substituídas."
                 .replace(",", "."))
        if cortou:
            aviso += (f"<br><br>O arquivo tem MAIS que isso: só as primeiras "
                      f"{teto:,} serão trocadas nesta "
                      f"passada.".replace(",", "."))
        if QMessageBox.question(
                self, "Substituir todas", aviso + "<br><br>Continuar?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return

        feitas = busca.substituir_todas(aba.documento, criterio,
                                        aba.perfil.codec, troca,
                                        teto=teto)
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
        if aba.e_planilha:
            self.barra.showMessage(
                "Numa planilha, use as teclas de seta ou role até a célula.",
                6000)
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
        if aba.e_planilha:
            self.barra.showMessage(
                f"{o_que} não funciona numa planilha. Use a busca do Excel "
                f"depois de salvar.", 8000)
            return False
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
        if getattr(widget, "editavel", False):
            equivalente = EDICAO_NA_VIEW.get(metodo)
            if equivalente is not None and hasattr(widget, equivalente):
                getattr(widget, equivalente)()
                self._atualizar_titulos()
                self._mostrar_posicao(aba.linha_atual(), 0)
                return

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
        if aba.e_planilha:
            # Numa planilha a posicao e' a CELULA, e nao (linha, coluna) de
            # texto. E nao ha' "editado: X KB": a pasta inteira ja' esta' na
            # memoria por construcao, entao o numero nao diria nada.
            from tfedit.planilha.valores import letra_de_coluna

            self.rotulo_posicao.setText(
                f"Célula {letra_de_coluna(coluna + 1)}{linha + 1}")
            self.rotulo_memoria.clear()
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
