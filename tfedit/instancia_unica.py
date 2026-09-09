"""Uma janela só: o segundo processo entrega os arquivos e sai.

Sem isto, selecionar 12 arquivos no Explorer e mandar "Abrir com" dispara **12
processos**, cada um com seu Qt, seu mmap e sua janela. Com abas, o certo é o
contrário: os 12 viram 12 abas na janela que já está aberta.

Como funciona: o primeiro processo abre um `QLocalServer` — um *named pipe* no
Windows — com um nome derivado do usuário. Quem vier depois tenta se conectar;
conseguindo, manda os caminhos e **sai sem abrir janela**.

TRÊS DETALHES QUE JÁ CUSTARAM DEFEITO EM PROJETOS ASSIM:

**O canal é POR USUÁRIO.** Dois usuários na mesma máquina (ou uma sessão de
área de trabalho remota) têm processos separados e não devem se atropelar —
entregar o arquivo de um na janela do outro seria vazamento de conteúdo.

**Um pipe órfão não pode travar a abertura.** Se o programa morreu sem fechar o
canal, o nome continua registrado e o `listen()` falha. Nesse caso o servidor
remove o nome e tenta de novo; se ainda assim não der, o programa **abre
normalmente** como instância comum. Ficar sem abrir por causa de um pipe é
desproporcional.

**O pedido chega em pedaços.** Um named pipe não garante que a mensagem venha
inteira num `readyRead`. Sem um cabeçalho de tamanho, abrir 12 arquivos com
caminhos longos entregaria o último caminho cortado ao meio — e o editor tentaria
abrir um arquivo que não existe.
"""

from __future__ import annotations

import getpass
import json
import os

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from tfedit import log_interno

log = log_interno.obter(__name__)

APP = "TextForgeEdit"

#: Espera de CADA tentativa de conexão, em milissegundos.
ESPERA_MS = 700

#: Quantas tentativas antes de desistir e abrir janela própria.
#:
#: Mais de uma porque a outra instância pode estar OCUPADA -- indexando um
#: arquivo de 1 GB, por exemplo -- e demorar para voltar à fila de eventos, que
#: é onde o `QLocalServer` aceita a conexão. Com uma tentativa só, o segundo
#: processo desistia e abria uma janela paralela, que é justamente o que este
#: módulo existe para evitar. O sintoma apareceu primeiro como teste instável:
#: passava sozinho e falhava com a máquina carregada.
TENTATIVAS = 3


#: Variavel de ambiente que TROCA o nome do canal.
#:
#: Existe para os TESTES. Sem ela a suite usa o canal de producao -- o mesmo do
#: programa que o usuario pode ter aberto neste instante --, e entao o teste
#: "entregar devolve False quando nao ha' ninguem" falha porque HA' alguem: a
#: janela de verdade. Pior: a suite entrega pedidos de arquivo a ela.
#:
#: Aconteceu de verdade, e as duas falhas pareciam regressao do codigo. E' a
#: mesma classe de defeito do %APPDATA% que os testes ja' isolam.
VARIAVEL_DO_CANAL = "TFEDIT_CANAL"


def nome_do_canal() -> str:
    """Canal por usuário. Ver o cabeçalho."""
    forcado = os.environ.get(VARIAVEL_DO_CANAL)
    if forcado:
        return forcado
    try:
        usuario = getpass.getuser()
    except Exception:                     # noqa: BLE001 - depende do ambiente
        usuario = "desconhecido"
    seguro = "".join(c if c.isalnum() else "_" for c in usuario)
    return f"{APP}-{seguro}"


def _empacotar(pedido: dict) -> bytes:
    """Mensagem com cabeçalho de tamanho. Ver o terceiro detalhe do cabeçalho."""
    corpo = json.dumps(pedido, ensure_ascii=False).encode("utf-8")
    return len(corpo).to_bytes(4, "big") + corpo


def entregar(pedido: dict) -> bool:
    """Entrega o pedido a uma instância já aberta. False se não havia nenhuma.

    Tenta `TENTATIVAS` vezes: a outra instância pode estar ocupada e demorar a
    voltar à fila de eventos. Desistir cedo abriria uma segunda janela --
    exatamente o que este módulo evita.
    """
    for tentativa in range(1, TENTATIVAS + 1):
        soquete = QLocalSocket()
        soquete.connectToServer(nome_do_canal())
        if not soquete.waitForConnected(ESPERA_MS):
            soquete.abort()
            if tentativa < TENTATIVAS:
                # Uma espera curta e crescente: se ninguém estiver escutando, a
                # conexão falha na hora e as três tentativas custam quase nada.
                QThread.msleep(120 * tentativa)
                continue
            return False

        soquete.write(_empacotar(pedido))
        soquete.flush()
        entregue = soquete.waitForBytesWritten(ESPERA_MS)
        soquete.disconnectFromServer()
        if entregue:
            log.info("pedido entregue a uma instância já aberta (tentativa %d)",
                     tentativa)
            return True
        if tentativa >= TENTATIVAS:
            return False
    return False


class Servidor(QObject):
    """Escuta pedidos de outras instâncias e os repassa para a janela."""

    #: O pedido recebido: {"arquivos": [...], "linha": N, "coluna": N}
    pedido_recebido = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._servidor: QLocalServer | None = None
        self._parciais: dict[QLocalSocket, bytearray] = {}

    def escutar(self) -> bool:
        """Assume o canal. False quando outra instância já o tem."""
        servidor = QLocalServer(self)
        # `WorldAccess` NÃO: o canal é por usuário, e abri-lo para todo mundo
        # deixaria outra conta entregar arquivos nesta janela.
        servidor.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)

        if not servidor.listen(nome_do_canal()):
            # Pipe órfão de um processo que morreu sem fechar. Remover o nome e
            # tentar de novo é seguro: se houvesse alguém escutando de verdade,
            # `entregar()` teria funcionado antes de chegarmos aqui.
            QLocalServer.removeServer(nome_do_canal())
            if not servidor.listen(nome_do_canal()):
                log.warning("não foi possível assumir o canal %r: %s. O "
                            "programa abre como instância comum.",
                            nome_do_canal(), servidor.errorString())
                return False
            log.info("canal órfão removido e reassumido")

        servidor.newConnection.connect(self._ao_conectar)
        self._servidor = servidor
        log.info("escutando em %s", nome_do_canal())
        return True

    def parar(self) -> None:
        if self._servidor is not None:
            self._servidor.close()
            self._servidor = None

    # ==================================================================

    def _ao_conectar(self) -> None:
        while self._servidor and self._servidor.hasPendingConnections():
            soquete = self._servidor.nextPendingConnection()
            if soquete is None:
                continue
            self._parciais[soquete] = bytearray()
            soquete.readyRead.connect(lambda s=soquete: self._ao_ler(s))
            soquete.disconnected.connect(lambda s=soquete: self._descartar(s))

    def _ao_ler(self, soquete: QLocalSocket) -> None:
        buffer = self._parciais.get(soquete)
        if buffer is None:
            return
        buffer.extend(bytes(soquete.readAll().data()))

        # Enquanto não chegou o cabeçalho inteiro, ou o corpo que ele anuncia,
        # não há mensagem completa: esperar é o certo. Ver o cabeçalho.
        if len(buffer) < 4:
            return
        tamanho = int.from_bytes(buffer[:4], "big")
        if tamanho <= 0 or tamanho > 1_000_000:
            log.warning("pedido com tamanho implausível (%d); descartado",
                        tamanho)
            self._descartar(soquete)
            return
        if len(buffer) < 4 + tamanho:
            return

        corpo = bytes(buffer[4:4 + tamanho])
        self._descartar(soquete)
        try:
            pedido = json.loads(corpo.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as erro:
            # Lixo no canal não pode derrubar o editor: outro programa pode ter
            # se conectado por engano a um pipe de nome parecido.
            log.warning("pedido ilegível no canal: %s", erro)
            return
        if isinstance(pedido, dict):
            log.info("pedido recebido de outra instância: %s",
                     pedido.get("arquivos"))
            self.pedido_recebido.emit(pedido)

    def _descartar(self, soquete: QLocalSocket) -> None:
        self._parciais.pop(soquete, None)
        soquete.close()
        soquete.deleteLater()
