"""Varrer o arquivo numa thread, para a abertura ser instantanea.

Sem isto, abrir 1 GB congela a janela pelo tempo da varredura -- e uma janela que
nao responde e' indistinguivel de um programa travado. Aqui a abertura mostra o
comeco do arquivo em milissegundos e a contagem de linhas CRESCE enquanto o
usuario ja' esta' lendo.

SOBRE AS DUAS THREADS TOCAREM A MESMA `Original`. E' seguro, e nao por acaso:

  * `_marcadores` so' CRESCE, por `append`. Ler `len()` e depois indexar continua
    valido mesmo com um append no meio -- a lista nunca encolhe nem reordena, e
    as duas operacoes sao atomicas sob o GIL.
  * `_quebras` e `_varrido` sao inteiros. Uma leitura defasada custa, no maximo,
    uma linha a menos na barra de rolagem por um instante.
  * `mmap.find(sub, a, b)` e o fatiamento nao usam a posicao interna do mmap,
    entao nao ha' estado compartilhado entre chamadas.

O que NAO e' seguro e' fechar o mmap com o worker lendo dele: isso levanta na
thread de disco. Por isso `parar()` ESPERA a thread sair antes de devolver, e
quem fecha o arquivo so' o faz depois.

E editar so' libera quando a varredura termina (`Documento.pode_editar`): partir
uma peca precisa saber quantas linhas ficam de cada lado, e isso so' e' confiavel
com o indice completo.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from tfedit.original import Original

#: Quanto o worker varre entre duas checagens de cancelamento. 8 MB levam alguns
#: milissegundos num SSD: pequeno o bastante para o cancelamento responder na
#: hora, grande o bastante para o custo por byte continuar sendo o do memchr.
ORCAMENTO = 8 * 1024 * 1024

#: Quanto se varre ANTES de mostrar a janela. Precisa cobrir a primeira fatia --
#: 8 MB sao ~100 mil linhas de 80 colunas, com folga sobre as 5 mil da fatia --
#: e custa milissegundos. Sem isto a tela apareceria vazia e so' encheria no
#: primeiro sinal de progresso.
PARTIDA = 8 * 1024 * 1024


class Indexador(QThread):
    """Conduz a varredura de UMA `Original`. Vive na thread da interface."""

    #: (bytes varridos, bytes totais)
    progresso = Signal(int, int)
    #: total de linhas, quando o arquivo inteiro foi varrido
    concluido = Signal(int)
    falhou = Signal(str)

    def __init__(self, original: Original, parent=None) -> None:
        super().__init__(parent)
        self.original = original
        self._cancelado = False

    def cancelar(self) -> None:
        self._cancelado = True

    def parar(self) -> None:
        """Cancela e ESPERA a thread sair.

        Esperar e' obrigatorio: quem chama isto vai fechar o mmap em seguida, e
        fecha-lo com o worker lendo dele levanta na thread de disco.
        """
        self.cancelar()
        if self.isRunning():
            self.wait(5_000)

    def run(self) -> None:                                # noqa: D102 - Qt
        try:
            ultimo = -1
            while not self.original.indexacao_completa:
                if self._cancelado:
                    return
                self.original.indexar(ORCAMENTO,
                                      cancelar=lambda: self._cancelado)
                varrido, total = self.original.progresso
                # Um sinal por bloco de 8 MB num arquivo de 1 GB seriam 128
                # sinais atravessando a fila de eventos. Emitir so' quando o
                # PONTO PERCENTUAL muda corta isso para no maximo 100.
                por_cento = varrido * 100 // max(1, total)
                if por_cento != ultimo:
                    ultimo = por_cento
                    self.progresso.emit(varrido, total)
            if not self._cancelado:
                self.concluido.emit(self.original.total_de_linhas)
        except Exception as erro:                         # noqa: BLE001
            # Uma falha na thread de disco NAO pode derrubar o programa: o
            # arquivo continua legivel pelo que ja' foi indexado.
            self.falhou.emit(str(erro))
