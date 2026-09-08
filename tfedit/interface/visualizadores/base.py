"""O contrato de uma view que nao e' texto.

A DIFERENCA PARA O PROJETO IRMAO, e ela e' o motivo deste arquivo existir:

No TextForge um visualizador RECEBE o conteudo e o DEVOLVE (`para_texto() ->
str`, `visualizadores/base.py`), e a janela reescreve o QTextDocument com o que
ele devolveu. Aqui isso materializaria 1 GB numa `str` -- e' exatamente a
assinatura que este editor existe para nao ter.

Aqui a view recebe o `Documento` e le por faixa:

    Documento  --- faixa() / ler() --->  view
        ^
        +------- substituir() ---------  view (quando edita)

O ganho nao e' so' de memoria. "Sem edicao, os bytes voltam identicos" deixa de
ser uma promessa que cada visualizador precisa cumprir e passa a ser
ESTRUTURAL: uma view que nao editou nao chamou nada na tabela de pecas, entao a
tabela esta' bit a bit como estava. Nao ha' o que testar por confianca.

POR QUE ISTO E' UM MIXIN SEM Qt, E NAO UMA CLASSE QWidget

Cada view quer uma base Qt DIFERENTE: o hexadecimal desenha sozinho e quer
`QAbstractScrollArea`; a grade e a planilha querem `QTableView`. O PySide6
aceita **uma so'** base Qt por classe -- herdar de duas levanta no import.
Fixar `QWidget` aqui obrigaria cada view a embrulhar o widget de verdade num
container, so' para satisfazer a heranca.

Entao a parte comum e' um mixin de Python puro, e cada view escolhe a propria
base Qt:

    class VisorHexadecimal(VisualizadorDeDocumento, QAbstractScrollArea)
    class GradeCsv(VisualizadorDeDocumento, QTableView)

Os SINAIS ficam declarados em cada view concreta, e nao aqui: o PySide6 so'
registra `Signal` como atributo de uma classe que ja' e' `QObject`, e declara-los
num mixin comum os deixaria mudos -- um defeito que nao levanta erro, so' nunca
dispara. Sao tres linhas repetidas por view, e este paragrafo e' o motivo.
"""

from __future__ import annotations

#: Os sinais que toda view concreta deve declarar. Ver o cabecalho.
#:
#:     posicao_mudou = Signal(int, int)   # (linha no documento, coluna)
#:     sujou = Signal()                   # escreveu na tabela de pecas
#:     recusou = Signal(str)              # recusou uma edicao, com o motivo
SINAIS = ("posicao_mudou", "sujou", "recusou")


class VisualizadorDeDocumento:
    """Parte comum das views. Mixin: a base Qt vem da view concreta."""

    #: Nome sob o qual a view e' registrada na aba: "hex", "tabela", ...
    nome: str = ""
    #: Aceita edicao? Quem nao aceita nunca escreve no documento.
    editavel: bool = False

    def preparar(self, documento, perfil, *, tema=None,
                 cfg: dict | None = None) -> None:
        """Guarda o que toda view precisa. Chame no `__init__` da view."""
        self.documento = documento
        self.perfil = perfil
        self.tema = tema
        self.cfg = cfg or {}
        # Uma view descartada ainda pode receber um paintEvent antes de o
        # `deleteLater` acontecer -- e nesse instante o mmap ja' pode estar
        # fechado. Todo desenho confere isto antes de ler.
        self._vivo = True

    # ==================================================================
    # O que a aba e a janela chamam
    # ==================================================================

    def atualizar(self) -> None:
        """O documento mudou por fora (edicao no texto, gravacao). Redesenhe."""

    def sincronizar(self) -> bool:
        """Leva para o documento o que estiver pendente na view.

        Uma celula aberta em edicao ainda nao esta' na tabela de pecas. Sem
        isto, salvar com a grade aberta gravaria o arquivo sem a ultima celula.
        Devolve True se algo foi para o documento.
        """
        return False

    def linha_atual(self) -> int:
        """Linha do documento sob o cursor, base zero, para a barra de status."""
        return 0

    def ir_para_linha(self, linha: int) -> None:
        """Leva a visualizacao ate' a linha pedida (base zero)."""

    def aplicar_tema(self, tema) -> None:
        self.tema = tema

    def encerrar(self) -> None:
        """Solta recursos. Idempotente.

        Existir na BASE, e nao so' em quem precisa, e' o que deixa
        `Aba.remover_view` chamar sem `hasattr` -- e uma view com thread que
        nao fosse encerrada continuaria rodando sobre um objeto destruido, que
        e' a forma classica de o programa morrer sem traceback.
        """
        self._vivo = False

    def cor_do_tema(self, caminho: str):
        """Cor do tema, com o embutido como rede.

        So' use chaves que ja' existem nos temas de `recursos/temas/`:
        `tema.cor` apenas AVISA no log quando a chave falta e devolve a cor do
        texto, entao uma chave nova daria uma view monocromatica sem erro
        visivel.
        """
        from tfedit import tema as tema_mod

        alvo = self.tema if self.tema is not None else tema_mod.embutido("escuro")
        return alvo.cor(caminho)
