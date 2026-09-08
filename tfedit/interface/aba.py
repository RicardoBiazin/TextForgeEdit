"""Uma aba: um arquivo aberto, com tudo o que ele precisa.

Cada aba e' dona de quatro objetos que so' fazem sentido juntos:

    Original      o mmap e o indice esparso do arquivo no disco
    Documento     a tabela de pecas -- o disco mais o que foi digitado
    JanelaViva    a fatia que esta' no editor
    Indexador     a thread que varre o arquivo

Juntar isso numa classe, em vez de deixar na janela principal, e' o que torna
"varias abas" uma lista em vez de uma reescrita: a janela passa a conduzir abas,
e nao arquivos.

DOIS CAMINHOS DE CONSTRUCAO, e o segundo nao e' um caso especial mal resolvido:

Um `.xlsx` NAO E' TEXTO. Nao tem linhas, nao tem fim de linha, nao tem
codificacao -- e' um ZIP de XML. O mmap, o indice esparso e a tabela de pecas
nao se aplicam a ele, e indexar 100 MB de ZIP contando "\n" seria trabalho
jogado fora para produzir um numero sem sentido.

Entao a planilha nao cria nada disso: `original`, `documento`, `janela` e
`editor` ficam None, e a unica view registrada e' a grade. E' o mesmo desenho
do projeto irmao, onde `Documento.abrir()` ramifica por modo.

REGRA DE IDENTIDADE: uma aba por ARQUIVO, comparada por caminho resolvido e em
caixa baixa. Duas abas do mesmo arquivo produziriam duas versoes divergentes, e
uma delas se perderia no primeiro salvamento -- no Windows o mesmo arquivo chega
com caixa diferente pelo Explorer, pela forma curta 8.3 e por caminho relativo.
"""

from __future__ import annotations

import pathlib
from dataclasses import replace

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from tfedit import (codificacao, conversao, linguagens,
                    log_interno)
from tfedit.linguagens import registro as registro_de_linguagens
from tfedit.gravacao import gravar, gravar_bytes
from tfedit.interface.editor import EditorDeslizante
from tfedit.interface.indexador import PARTIDA, Indexador
from tfedit.janela import JanelaViva
from tfedit.original import ArquivoMudou, Original
from tfedit.pecas import Documento

log = log_interno.obter(__name__)

#: Extensoes que fazem a aba TENTAR abrir como planilha. O conteudo e' que
#: decide de fato -- um .zip renomeado nao passa por `parece_planilha`.
EXTENSOES_DE_PLANILHA = frozenset({".xlsx", ".xlsm"})


class NaoEPlanilha(ValueError):
    """A extensao prometia planilha e o conteudo nao e' uma."""


class Aba(QWidget):
    """Um arquivo aberto e o editor dele."""

    #: (linha no documento, coluna) -- para a barra de status.
    posicao_mudou = Signal(int, int)
    #: o titulo (nome ou asterisco) precisa ser redesenhado.
    titulo_mudou = Signal()
    #: (bytes varridos, bytes totais)
    indexando = Signal(int, int)
    #: total de linhas, quando a varredura termina
    indexou = Signal(int)

    def __init__(self, caminho, cfg: dict | None = None,
                 parent: QWidget | None = None, *, tema=None) -> None:
        super().__init__(parent)
        self.cfg = cfg or {}
        self.caminho = pathlib.Path(caminho)
        self.tema = tema
        self.planilha = None
        self._dialeto = None

        if self._parece_planilha():
            self._montar_planilha()
            return

        self.original = Original(self.caminho)
        self.original.ocioso_apos = float(
            self.cfg.get("soltar_arquivo_apos_s", 20))
        self.perfil = codificacao.detectar(
            self.original.ler(0, codificacao.SONDAGEM))
        # Um primeiro pedaco SINCRONO, so' o bastante para a fatia inicial
        # existir. Sem ele a aba abriria vazia e so' encheria no primeiro sinal
        # de progresso.
        self.original.indexar(PARTIDA)

        self.documento = Documento(self.original)
        self.janela = JanelaViva(
            self.documento, self.perfil,
            linhas=int(self.cfg.get("linhas_da_janela", 5000)))
        self.provedor = self._resolver_linguagem()
        self.editor = EditorDeslizante(self.janela, self, cfg=self.cfg,
                                       tema=tema, provedor=self.provedor)
        self.editor.posicao_mudou.connect(self.posicao_mudou)
        self.editor.sujou.connect(self.titulo_mudou)
        self.editor.conteudo_voltou.connect(self.titulo_mudou)

        # UMA PILHA, e nao o editor como filho unico.
        #
        # O hexadecimal, a grade de CSV e a planilha sao views do MESMO
        # documento, e trocar entre elas nao pode reconstruir a aba: o mmap, o
        # indice e a tabela de pecas sao caros e sao os mesmos. A pilha guarda
        # todas e mostra uma. Ver `trocar_para`, onde mora o cuidado.
        self.pilha = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.pilha)
        self.pilha.addWidget(self.editor)
        self._views: dict[str, QWidget] = {"texto": self.editor}

        # O que a LINGUAGEM sugere para este arquivo ("tabela" para .csv). E' so'
        # uma sugestao: quem abre a view e' o usuario. Abrir a grade sozinho no
        # arranque montaria o modelo contra um `total_de_linhas` que ainda esta'
        # crescendo na thread de varredura.
        # Descoberto sob demanda pelo menu Visualizar, e esquecido quando a
        # codificacao muda -- o dialeto foi lido com o codec antigo.
        self._dialeto = None
        self.visualizador_sugerido = (
            self.provedor.visualizador_preferido()
            if self.provedor is not None else "texto")

        self.indexador: Indexador | None = None
        if self.original.indexacao_completa:
            self.indexou.emit(self.original.total_de_linhas)
        else:
            # Ler ja'; editar quando a varredura acabar -- partir uma peca
            # precisa saber quantas linhas ficam de cada lado.
            self.editor.setReadOnly(True)
            self.indexador = Indexador(self.original, self)
            self.indexador.progresso.connect(self.indexando)
            self.indexador.concluido.connect(self._ao_terminar_indice)
            self.indexador.falhou.connect(self._ao_falhar_indice)
            self.indexador.start()

        # Enquanto o mmap existe, NENHUM outro programa consegue regravar o
        # arquivo no Windows -- nem um rotacionador de log, nem um `git
        # checkout`. O temporizador devolve o arquivo ao sistema quando ninguem
        # esta' lendo; o proximo acesso remapeia sozinho, conferindo a
        # assinatura. Ver o cabecalho de `original.py`.
        self._relogio = QTimer(self)
        self._relogio.setInterval(5_000)
        self._relogio.timeout.connect(self._soltar_se_ocioso)
        if self.original.ocioso_apos > 0:
            self._relogio.start()

        log.info("aberto %s (%d bytes, %s, %s)", self.caminho,
                 self.original.tamanho, self.perfil.rotulo,
                 self.perfil.rotulo_eol)

    # ==================================================================
    # Planilha
    # ==================================================================

    def _parece_planilha(self) -> bool:
        """Vale a pena tentar abrir como planilha?

        A extensao decide se tentamos; o CONTEUDO decide se conseguimos. E o
        tamanho e' conferido por `stat`, ANTES de ler um byte: a leitura de uma
        planilha traz o arquivo inteiro para a memoria, e descobrir que ele nao
        cabia depois de le-lo e' o pior momento possivel.
        """
        if self.caminho.suffix.lower() not in EXTENSOES_DE_PLANILHA:
            return False
        teto = int(self.cfg.get("limite_planilha_mb", 100)) * 1024 * 1024
        try:
            tamanho = self.caminho.stat().st_size
        except OSError:
            return False
        if tamanho > teto:
            log.info("%s tem %.1f MB e passa do limite de planilha (%d MB); "
                     "abrindo como arquivo comum", self.nome,
                     tamanho / (1024 * 1024), teto // (1024 * 1024))
            self.planilha_grande_demais = tamanho
            return False
        return True

    def _montar_planilha(self) -> None:
        """Abre como planilha. Levanta `NaoEPlanilha` quando nao da'."""
        from tfedit.planilha import deteccao, leitor

        dados = self.caminho.read_bytes()
        if not deteccao.parece_planilha(dados):
            raise NaoEPlanilha(
                f"{self.nome} tem extensão de planilha, mas o conteúdo não é "
                f"um pacote .xlsx válido.")

        self.planilha = leitor.abrir(self.caminho, self.cfg, dados)
        self.original = None
        self.documento = None
        self.janela = None
        self.editor = None
        self.perfil = None
        self.provedor = None
        self.visualizador_sugerido = "planilha"
        self.indexador = None

        from tfedit.interface.visualizadores.planilha import GradePlanilha

        grade = GradePlanilha(self.planilha, self, tema=self.tema,
                              cfg=self.cfg)
        grade.sujou.connect(self.titulo_mudou)
        self.pilha = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.pilha)
        self.pilha.addWidget(grade)
        # Sem a view "texto": mostrar um ZIP decodificado como texto seria
        # rabisco, e um comando de edicao caindo nele nao teria significado.
        self._views: dict[str, QWidget] = {"planilha": grade}

        log.info("aberta planilha %s (%d bytes, %d aba(s)%s)", self.caminho,
                 len(self.planilha.bytes_originais), len(self.planilha.folhas),
                 ", somente leitura" if self.planilha.somente_leitura else "")

    @property
    def e_planilha(self) -> bool:
        return self.planilha is not None

    def _soltar_se_ocioso(self) -> None:
        # Enquanto a varredura corre, o worker esta' lendo do mmap: fecha-lo
        # levantaria na thread de disco.
        if self.indexando_agora:
            return
        if self.original.soltar_se_ocioso():
            log.info("%s: arquivo solto por ociosidade (livre para outros "
                     "programas)", self.nome)

    # ==================================================================
    # Identidade
    # ==================================================================

    @property
    def nome(self) -> str:
        return self.caminho.name

    def chave(self) -> str:
        """Identidade para "ja' existe aba deste arquivo?". Ver o cabecalho."""
        try:
            return str(self.caminho.resolve()).lower()
        except OSError:
            return str(self.caminho).lower()

    @staticmethod
    def chave_de(caminho) -> str:
        try:
            return str(pathlib.Path(caminho).resolve()).lower()
        except OSError:
            return str(caminho).lower()

    @property
    def modificado(self) -> bool:
        if self.e_planilha:
            return self.planilha.alterado
        return self.documento.alterado or self.editor.sujo

    @property
    def titulo(self) -> str:
        return ("*" if self.modificado else "") + self.nome

    # ==================================================================
    # Indexacao
    # ==================================================================

    def _ao_terminar_indice(self, total: int) -> None:
        self.editor.setReadOnly(False)
        self.editor._ajustar_margem()
        log.info("indice completo: %s, %d linhas", self.nome, total)
        self.indexou.emit(total)

    def _ao_falhar_indice(self, erro: str) -> None:
        log.error("indexacao de %s falhou: %s", self.nome, erro)
        self.indexou.emit(self.original.total_de_linhas)

    @property
    def indexando_agora(self) -> bool:
        if self.e_planilha:
            return False
        return not self.original.indexacao_completa

    # ==================================================================
    # Gravar
    # ==================================================================

    def salvar(self, destino=None) -> int:
        """Grava. `destino` diferente do atual faz "Salvar como".

        Devolve quantos bytes foram escritos. Levanta o que `gravacao.gravar`
        levantar -- quem chama e' que sabe como avisar o usuario.
        """
        self.sincronizar()
        alvo = pathlib.Path(destino) if destino else self.caminho
        if self.e_planilha:
            return self._salvar_planilha(alvo)
        mesmo_arquivo = self.chave_de(alvo) == self.chave()

        if mesmo_arquivo and not self.documento.alterado:
            # Regravar por regravar num arquivo de 240 MB custa minutos de
            # escrita e ainda mexe na data -- backup e sincronizador passam a
            # achar que o arquivo mudou. Salvar sem edicao e' um no-op honesto.
            log.info("nada a gravar em %s", alvo)
            return 0

        # Depois de uma soltada por ociosidade o arquivo ficou livre para
        # outros programas -- e' exatamente ai' que conferir importa. Com o
        # mapeamento vivo a resposta e' sempre "nao mudou", e conferir custa
        # dois MB de leitura, entao nao ha' motivo para pular.
        if mesmo_arquivo:
            self.original.conferir_no_disco()

        escritos = gravar(alvo, self.documento,
                          antes_de_trocar=self.original.fechar)

        # O arquivo do disco e' outro: o mmap antigo esta' fechado e as pecas
        # apontavam para ele. Reabrir e reindexar antes de qualquer leitura e'
        # obrigatorio -- ver `Documento.confirmar_gravacao`.
        novo = Original(alvo)
        novo.indexar()
        self.original = novo
        self.caminho = alvo
        self.documento.confirmar_gravacao(novo)
        self.janela.documento = self.documento
        self.editor.recarregar(self.editor.linha_atual_no_documento())
        self.titulo_mudou.emit()
        log.info("gravado %s (%d bytes)", alvo, escritos)
        return escritos

    # ==================================================================
    # Views
    # ==================================================================

    def registrar_view(self, nome: str, widget: QWidget) -> None:
        self.remover_view(nome)
        self._views[nome] = widget
        self.pilha.addWidget(widget)

    def remover_view(self, nome: str) -> None:
        """Descarta uma view alternativa. "texto" nunca sai.

        A view e' DESCARTADA, e nao guardada de lado: ela le' do documento a
        cada desenho, mas pode ter estado proprio (o dialeto do CSV, a largura
        das colunas) que envelhece quando o documento muda por baixo. Montar de
        novo custa pouco; mostrar dado velho custa caro.
        """
        if nome == "texto":
            return
        widget = self._views.pop(nome, None)
        if widget is None:
            return
        widget.encerrar()
        self.pilha.removeWidget(widget)
        widget.setParent(None)
        widget.deleteLater()

    def tem_view(self, nome: str) -> bool:
        return nome in self._views

    def view(self, nome: str) -> QWidget | None:
        return self._views.get(nome)

    def view_atual(self) -> str:
        atual = self.pilha.currentWidget()
        for nome, widget in self._views.items():
            if widget is atual:
                return nome
        return "texto"

    def trocar_para(self, nome: str) -> bool:
        """Mostra outra view. A ORDEM DAQUI NAO E' NEGOCIAVEL.

        O editor continua VIVO e com a fatia carregada atras da pilha. Duas
        coisas seguem disso:

        SAINDO do texto, a fatia pode ter o que acabou de ser digitado e ainda
        nao foi para a tabela de pecas. A view le' do documento -- sem
        sincronizar, ela mostraria o arquivo de antes da ultima tecla.

        VOLTANDO para o texto, a view pode ter editado o documento (uma celula
        da grade). A fatia no QPlainTextEdit e' anterior a essa edicao. Sem
        recarregar, o texto velho aparece, o usuario digita uma letra, a fatia
        fica suja e o conteudo ANTERIOR a edicao da grade volta ao documento.
        """
        widget = self._views.get(nome)
        if widget is None:
            return False
        atual = self.view_atual()
        if atual == nome:
            return True

        self.sincronizar()
        self.pilha.setCurrentWidget(widget)
        if nome == "texto":
            self.editor.recarregar(self.editor.linha_atual_no_documento())
        else:
            widget.atualizar()
        widget.setFocus()
        log.info("%s: view %s -> %s", self.nome, atual, nome)
        return True

    def focar_view_atual(self) -> None:
        self.pilha.currentWidget().setFocus()

    def sincronizar(self) -> bool:
        """Leva ao documento o que estiver pendente na VIEW ATIVA."""
        atual = self.view_atual()
        if atual == "texto":
            return self.editor.sincronizar()
        return self._views[atual].sincronizar()

    def view_atual(self) -> str:
        atual = self.pilha.currentWidget()
        for nome, widget in self._views.items():
            if widget is atual:
                return nome
        return next(iter(self._views), "texto")

    def linha_atual(self) -> int:
        atual = self.view_atual()
        if atual == "texto":
            return self.editor.linha_atual_no_documento()
        return self._views[atual].linha_atual()

    def total_de_linhas(self) -> int:
        """Para os dialogos que perguntam "linha 1 a quantas?"."""
        if self.e_planilha:
            return 0
        return self.documento.total_de_linhas

    def ir_para_linha(self, linha: int) -> None:
        atual = self.view_atual()
        if atual == "texto":
            self.editor.ir_para_linha(linha)
        else:
            self._views[atual].ir_para_linha(linha)

    def aplicar_tema(self, tema) -> None:
        for nome, widget in self._views.items():
            if nome != "texto":
                widget.aplicar_tema(tema)

    def ao_indexar(self) -> None:
        """O total de linhas cresceu. Quem depende dele precisa saber."""
        for nome, widget in self._views.items():
            if nome != "texto":
                widget.atualizar()

    def dialeto_csv(self):
        """O dialeto deste arquivo, ou None quando nao parece tabela.

        A AMOSTRA e' curta de proposito: 200 linhas dizem tanto quanto o
        arquivo inteiro sobre qual e' o separador, e este metodo e' chamado
        toda vez que o menu Visualizar abre.
        """
        if self._dialeto is not None:
            return self._dialeto
        from tfedit import csv_dialeto

        try:
            cruas = self.documento.faixa(0, 200)
        except Exception:                     # noqa: BLE001 - nunca derrubar
            return None
        amostra = b"\n".join(cruas).decode(self.perfil.codec,
                                            errors="replace")
        dialeto = csv_dialeto.detectar(amostra)
        if dialeto.colunas < 2 or dialeto.confianca < 50:
            return None
        self._dialeto = dialeto
        return dialeto

    def _descartar_views_de_texto(self) -> None:
        """Views cuja leitura depende do PERFIL de codificacao.

        Chamado ao reinterpretar ou converter: o dialeto do CSV foi detectado
        sobre uma amostra decodificada com o codec ANTIGO, e mante-lo daria
        colunas erradas sem nenhum erro visivel.
        """
        self._dialeto = None
        self.remover_view("tabela")

    # ==================================================================
    # Codificacao
    # ==================================================================

    def reinterpretar(self, codec: str, bom: bytes = b"") -> None:
        """Le os MESMOS bytes com outra codificacao. Nada muda no disco.

        E' o conserto de "abri e veio tudo com acento quebrado": o arquivo
        estava certo, a leitura e' que errou.

        Recusa com edicao pendente, e o motivo nao e' preciosismo: o que foi
        digitado esta' guardado como BYTES na codificacao antiga. Reinterpretar
        transformaria o texto que a propria pessoa acabou de escrever em
        rabisco, sem desfazer possivel.
        """
        if self.documento.alterado:
            raise ValueError(
                "Este arquivo tem alterações não salvas. Salve ou desfaça "
                "antes de reinterpretar a codificação: o que você digitou "
                "está guardado na codificação atual e sairia ilegível.")

        self.perfil = replace(self.perfil, codec=codec, bom=bom,
                              como_decidiu="escolha do usuário")
        self.janela.perfil = self.perfil
        self._descartar_views_de_texto()
        self.editor.recarregar(self.editor.linha_atual_no_documento())
        self.titulo_mudou.emit()
        log.info("%s reinterpretado como %s", self.nome, self.perfil.rotulo)

    def converter_codificacao(self, alvo: conversao.Alvo,
                              cancelar=None) -> int:
        """Reescreve o arquivo INTEIRO na codificacao `alvo`.

        Ao contrario de `salvar`, isto nao e' no-op quando nao ha' edicao: o
        pedido e' justamente reescrever os bytes.
        """
        self.editor.sincronizar()
        self.original.conferir_no_disco()

        escritos = conversao.converter(
            self.caminho, self.documento, self.perfil.codec, alvo,
            rotulo_de=self.perfil.rotulo, cancelar=cancelar,
            antes_de_trocar=self.original.fechar)

        # Mesmo cuidado de `salvar`: o arquivo do disco e' outro, com OUTROS
        # offsets -- em UTF-8 os acentos passaram a ocupar dois bytes. As pecas
        # e o indice antigos apontam para posicoes que nao existem mais.
        novo = Original(self.caminho)
        novo.indexar()
        self.original = novo
        self.documento.confirmar_gravacao(novo)
        self.janela.documento = self.documento

        # Redetectar em vez de assumir o alvo: e' a prova de que o arquivo
        # gravado E' o que se pediu. Se a deteccao discordar, o rotulo da barra
        # mostra o que esta' no disco, e nao o que a gente quis fazer.
        self.perfil = codificacao.detectar(
            self.original.ler(0, codificacao.SONDAGEM))
        self.janela.perfil = self.perfil
        self._descartar_views_de_texto()
        self.editor.recarregar(self.editor.linha_atual_no_documento())
        self.ao_indexar()
        self.titulo_mudou.emit()
        log.info("%s convertido para %s (%d bytes, detectado como %s)",
                 self.nome, alvo.rotulo, escritos, self.perfil.rotulo)
        return escritos

    def _salvar_planilha(self, alvo: pathlib.Path) -> int:
        """Grava o .xlsx. Sem edicao, devolve os bytes ORIGINAIS intactos.

        `bytes_para_salvar()` de uma pasta nao alterada devolve o pacote
        original sem nem recomprimir -- e' o equivalente, aqui, da peca
        ORIGINAL que a gravacao por streaming copia byte a byte.
        """
        if alvo == self.caminho and not self.planilha.alterado:
            log.info("nada a gravar em %s", alvo)
            return 0

        dados = self.planilha.bytes_para_salvar()
        escritos = gravar_bytes(alvo, dados)
        self.planilha.confirmar_gravacao(dados)
        self.caminho = alvo
        self.titulo_mudou.emit()
        return escritos

    # ==================================================================
    # Fim de vida
    # ==================================================================

    def encerrar(self) -> None:
        """Para a varredura e SO' ENTAO fecha o mmap. Idempotente.

        A ordem importa: fechar o mmap com o worker lendo dele levanta na thread
        de disco. `parar()` espera a thread sair.
        """
        if self.e_planilha:
            for nome in list(self._views):
                widget = self._views.pop(nome)
                widget.encerrar()
                widget.setParent(None)
                widget.deleteLater()
            log.info("fechada planilha %s", self.nome)
            return
        if getattr(self, "_relogio", None) is not None:
            self._relogio.stop()
        if self.indexador is not None:
            self.indexador.parar()
            self.indexador = None
        # As views ANTES do mmap. Uma view ja' descartada ainda pode receber um
        # paintEvent antes de o `deleteLater` acontecer, e nesse instante ela
        # leria de um mmap fechado.
        for nome in [n for n in self._views if n != "texto"]:
            self.remover_view(nome)
        if self.original is not None:
            self.original.fechar()
        log.info("fechado %s", self.nome)

    # ==================================================================
    # Linguagem
    # ==================================================================

    def _resolver_linguagem(self):
        """Provedor de realce deste arquivo, pela extensao e pelo comeco dele.

        A AMOSTRA e' curta de proposito. No TextForge o documento inteiro esta'
        na memoria e olhar mais nao custa; aqui o arquivo pode ter 1 GB, e o
        shebang, o `<?xml` e o `<!DOCTYPE` -- que e' o que a deteccao por
        conteudo procura -- estao todos nos primeiros bytes.
        """
        linguagens.carregar_embutidos()
        try:
            amostra = self.original.ler(0, 4096).decode(
                self.perfil.codec, errors="replace")
        except Exception:                     # noqa: BLE001 - nunca impedir abrir
            amostra = ""
        return registro_de_linguagens.por_caminho(self.caminho, amostra)

    def definir_linguagem(self, provedor) -> None:
        self.provedor = provedor
        self.editor.definir_linguagem(provedor)
        log.info("linguagem de %s: %s", self.nome,
                 provedor.nome if provedor else "nenhuma")

    @property
    def nome_da_linguagem(self) -> str:
        return self.provedor.nome if self.provedor is not None else "Texto"
