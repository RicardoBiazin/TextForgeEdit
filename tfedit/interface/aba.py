"""Uma aba: um arquivo aberto, com tudo o que ele precisa.

Cada aba e' dona de quatro objetos que so' fazem sentido juntos:

    Original      o mmap e o indice esparso do arquivo no disco
    Documento     a tabela de pecas -- o disco mais o que foi digitado
    JanelaViva    a fatia que esta' no editor
    Indexador     a thread que varre o arquivo

Juntar isso numa classe, em vez de deixar na janela principal, e' o que torna
"varias abas" uma lista em vez de uma reescrita: a janela passa a conduzir abas,
e nao arquivos.

REGRA DE IDENTIDADE: uma aba por ARQUIVO, comparada por caminho resolvido e em
caixa baixa. Duas abas do mesmo arquivo produziriam duas versoes divergentes, e
uma delas se perderia no primeiro salvamento -- no Windows o mesmo arquivo chega
com caixa diferente pelo Explorer, pela forma curta 8.3 e por caminho relativo.
"""

from __future__ import annotations

import pathlib

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from tfedit import codificacao, log_interno
from tfedit.gravacao import gravar
from tfedit.interface.editor import EditorDeslizante
from tfedit.interface.indexador import PARTIDA, Indexador
from tfedit.janela import JanelaViva
from tfedit.original import Original
from tfedit.pecas import Documento

log = log_interno.obter(__name__)


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

    def __init__(self, caminho, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.caminho = pathlib.Path(caminho)
        self.original = Original(self.caminho)
        self.perfil = codificacao.detectar(
            self.original.ler(0, codificacao.SONDAGEM))
        # Um primeiro pedaco SINCRONO, so' o bastante para a fatia inicial
        # existir. Sem ele a aba abriria vazia e so' encheria no primeiro sinal
        # de progresso.
        self.original.indexar(PARTIDA)

        self.documento = Documento(self.original)
        self.janela = JanelaViva(self.documento, self.perfil)
        self.editor = EditorDeslizante(self.janela, self)
        self.editor.posicao_mudou.connect(self.posicao_mudou)
        self.editor.sujou.connect(self.titulo_mudou)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

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

        log.info("aberto %s (%d bytes, %s, %s)", self.caminho,
                 self.original.tamanho, self.perfil.rotulo,
                 self.perfil.rotulo_eol)

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
        return (self.documento.alterado
                or self.editor.document().isModified())

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
        return not self.original.indexacao_completa

    # ==================================================================
    # Gravar
    # ==================================================================

    def salvar(self, destino=None) -> int:
        """Grava. `destino` diferente do atual faz "Salvar como".

        Devolve quantos bytes foram escritos. Levanta o que `gravacao.gravar`
        levantar -- quem chama e' que sabe como avisar o usuario.
        """
        self.editor.sincronizar()
        alvo = pathlib.Path(destino) if destino else self.caminho
        mesmo_arquivo = self.chave_de(alvo) == self.chave()

        if mesmo_arquivo and not self.documento.alterado:
            # Regravar por regravar num arquivo de 240 MB custa minutos de
            # escrita e ainda mexe na data -- backup e sincronizador passam a
            # achar que o arquivo mudou. Salvar sem edicao e' um no-op honesto.
            log.info("nada a gravar em %s", alvo)
            return 0

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
    # Fim de vida
    # ==================================================================

    def encerrar(self) -> None:
        """Para a varredura e SO' ENTAO fecha o mmap. Idempotente.

        A ordem importa: fechar o mmap com o worker lendo dele levanta na thread
        de disco. `parar()` espera a thread sair.
        """
        if self.indexador is not None:
            self.indexador.parar()
            self.indexador = None
        if self.original is not None:
            self.original.fechar()
        log.info("fechado %s", self.nome)
