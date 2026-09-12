"""Sessão restaurada e instância única.

    .\\.venv\\Scripts\\python.exe tests\\teste_sessao.py

Os dois testes que carregam esta suíte:

1. **A sessão guarda o DIÁRIO, não o conteúdo.** Num editor comum a cópia de
   recuperação é o texto; aqui *todo* arquivo é potencialmente de 1 GB, e
   copiá-lo a cada intervalo transformaria a rede de segurança no maior custo do
   programa. O diário são as peças mais o que foi digitado — alguns KB.

2. **Diário sobre arquivo trocado é RECUSADO.** Reaplicar peças que apontam para
   offsets de um arquivo que mudou escreveria conteúdo certo em lugar errado.
   Perder as edições pendentes é ruim; misturar dois arquivos é pior.

A entrega entre processos é testada com um processo de verdade, e não simulada:
o defeito clássico aqui é a mensagem chegar em pedaços, e isso só aparece
atravessando o pipe.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from ajudantes import (appdata_temporario, checa, checa_igual,
                       drenar_eventos, pasta_temporaria, preparar_qt, pular,
                       resumir, secao)

TEM_QT = preparar_qt()

from tfedit import instancia_unica, sessao as sessao_mod   # noqa: E402
from tfedit.original import Assinatura, Original           # noqa: E402
from tfedit.pecas import Documento                         # noqa: E402


def gerar(pasta, nome: str, linhas: int = 5_000):
    alvo = pasta / nome
    alvo.write_bytes(b"".join(f"linha {i:05d} conteúdo\n".encode("utf-8")
                              for i in range(linhas)))
    return alvo


# ===========================================================================
# O diário
# ===========================================================================


def testar_diario_e_pequeno() -> None:
    secao("O diário é pequeno, e o conteúdo fica no arquivo")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "grande.txt", 20_000)
        original = Original(alvo)
        original.indexar()
        documento = Documento(original)
        for k in range(50):
            documento.inserir(documento.offset_da_linha(k * 7), b">> ")
        esperado = documento.ler(0, documento.tamanho)

        diario = documento.diario()
        tamanho = len(json.dumps(diario))
        checa(tamanho < alvo.stat().st_size // 10,
              f"*** o diário tem {tamanho} bytes para um arquivo de "
              f"{alvo.stat().st_size} -- as peças ORIGINAIS são só "
              f"coordenadas ***")

        outro = Original(alvo)
        outro.indexar()
        restaurado = Documento(outro)
        checa(restaurado.ler(0, restaurado.tamanho) != esperado,
              "o documento novo começa limpo")
        checa(restaurado.aplicar_diario(diario), "o diário é aceito")
        checa_igual(restaurado.ler(0, restaurado.tamanho), esperado,
                    "*** e restaura o documento exatamente ***")
        checa(restaurado.alterado,
              "e ele volta MARCADO como alterado, para o '*' e o aviso ao "
              "fechar continuarem valendo")
        original.fechar()
        outro.fechar()


def testar_diario_incoerente() -> None:
    secao("Diário que não serve é recusado")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "coerencia.txt", 500)
        original = Original(alvo)
        original.indexar()
        documento = Documento(original)
        documento.inserir(0, b">> ")
        antes = documento.ler(0, documento.tamanho)

        for rotulo, ruim in (
                ("peça além do arquivo",
                 {"pecas": [{"fonte": "original", "inicio": 0,
                             "tamanho": 10 ** 9, "linhas": 1}],
                  "adicionado": ""}),
                ("peça com tamanho negativo",
                 {"pecas": [{"fonte": "original", "inicio": 0,
                             "tamanho": -5, "linhas": 0}],
                  "adicionado": ""}),
                ("adicionada além do buffer",
                 {"pecas": [{"fonte": "adicionado", "inicio": 0,
                             "tamanho": 100, "linhas": 0}],
                  "adicionado": ""}),
                ("campo faltando", {"pecas": [{"fonte": "original"}]}),
                ("sem peça nenhuma", {"pecas": [], "adicionado": ""})):
            checa(not documento.aplicar_diario(ruim),
                  f"*** recusa: {rotulo} ***")
        checa_igual(documento.ler(0, documento.tamanho), antes,
                    "*** e o documento fica INTACTO: a coerência é conferida "
                    "antes de qualquer atribuição ***")
        original.fechar()


def testar_assinatura_da_sessao() -> None:
    secao("A sessão recusa arquivo trocado")

    with pasta_temporaria() as tmp:
        alvo = gerar(tmp, "trocado.txt", 200)
        original = Original(alvo)
        original.indexar()

        guardada = sessao_mod.AbaGuardada(
            caminho=str(alvo),
            assinatura={"tamanho": original.assinatura.tamanho,
                        "mtime_ns": original.assinatura.mtime_ns,
                        "pontas": original.assinatura.pontas},
            diario={"pecas": [{"fonte": "original", "inicio": 0,
                               "tamanho": 10, "linhas": 0}],
                    "adicionado": ""})
        checa(guardada.arquivo_confere(), "sem mudança, a assinatura confere")
        checa(guardada.tem_pendencia, "e há pendência a recuperar")

        original.fechar()
        novo = tmp / "novo.tmp"
        novo.write_bytes(b"outro conteudo bem diferente\n")
        os.replace(novo, alvo)
        checa(not guardada.arquivo_confere(),
              "*** depois de o arquivo mudar, NÃO confere -- e a recuperação é "
              "recusada em vez de escrever no lugar errado ***")

        sumido = sessao_mod.AbaGuardada(caminho=str(tmp / "nao_existe.txt"),
                                        assinatura={"tamanho": 1})
        checa(not sumido.arquivo_confere(), "arquivo que sumiu também não")


def testar_gravar_e_ler() -> None:
    secao("Gravar e ler a sessão")

    with appdata_temporario(), pasta_temporaria() as tmp:
        um = gerar(tmp, "um.txt", 100)
        dois = gerar(tmp, "dois.txt", 100)

        checa_igual(sessao_mod.ler(), [], "sem sessão, lista vazia")

        guardadas = [sessao_mod.AbaGuardada(caminho=str(um), linha=42),
                     sessao_mod.AbaGuardada(caminho=str(dois), linha=7)]
        checa(sessao_mod.gravar(guardadas), "grava")

        lidas = sessao_mod.ler()
        checa_igual(len(lidas), 2, "e volta com as duas")
        checa_igual(lidas[0].linha, 42, "com a linha certa")

        # Arquivo apagado entre uma sessão e outra não pode virar erro na
        # partida -- a aba simplesmente não volta.
        dois.unlink()
        lidas = sessao_mod.ler()
        checa_igual(len(lidas), 1,
                    "*** arquivo apagado some da sessão em silêncio, em vez de "
                    "quebrar a abertura ***")

        sessao_mod.caminho().write_text("{ não é json", encoding="utf-8")
        checa_igual(sessao_mod.ler(), [],
                    "sessão ilegível é ignorada, e não derruba o programa")

        sessao_mod.caminho().write_text('{"formato": 999, "abas": [{}]}',
                                        encoding="utf-8")
        checa_igual(sessao_mod.ler(), [],
                    "*** e uma sessão de OUTRO formato é ignorada INTEIRA: "
                    "meia sessão restaurada é pior que nenhuma ***")

        sessao_mod.gravar(guardadas[:1])
        sessao_mod.esquecer()
        checa(not sessao_mod.caminho().exists(), "esquecer apaga o arquivo")


# ===========================================================================
# Instância única
# ===========================================================================


def testar_canal() -> None:
    secao("O canal da instância única")

    nome = instancia_unica.nome_do_canal()
    checa(nome.startswith("TextForgeEdit-"), f"o nome do canal: {nome!r}")
    checa(len(nome) > len("TextForgeEdit-"),
          "*** inclui o usuário: dois usuários na mesma máquina não podem se "
          "atropelar ***")
    checa(all(c.isalnum() or c in "-_" for c in nome),
          "e só tem caracteres seguros para um named pipe")
    checa_igual(nome, instancia_unica.nome_do_canal(),
                "o nome é estável entre chamadas")


def testar_entrega_entre_processos() -> None:
    secao("Entrega de outro PROCESSO")

    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(instancia_unica.nome_do_canal())

    servidor = instancia_unica.Servidor()
    checa(servidor.escutar(), "o primeiro processo assume o canal")

    recebidos = []
    servidor.pedido_recebido.connect(recebidos.append)

    with pasta_temporaria() as tmp:
        # Caminhos LONGOS de propósito: o defeito clássico é a mensagem chegar
        # em pedaços, e com caminhos curtos ela cabe num pacote só e o defeito
        # não aparece.
        nomes = [str(tmp / (f"arquivo_com_nome_bem_longo_{n:03d}_" + "x" * 60
                            + ".txt")) for n in range(12)]
        auxiliar = pathlib.Path(__file__).parent / "ajudante_entregar.py"
        auxiliar.write_text(
            "import json, sys\n"
            "sys.path.insert(0, r'" + str(
                pathlib.Path(__file__).resolve().parent.parent) + "')\n"
            "from PySide6.QtCore import QCoreApplication\n"
            "from tfedit import instancia_unica\n"
            "app = QCoreApplication([])\n"
            "pedido = json.loads(sys.argv[1])\n"
            "sys.exit(0 if instancia_unica.entregar(pedido) else 1)\n",
            encoding="utf-8")

        import subprocess
        ambiente = dict(os.environ)
        ambiente["QT_QPA_PLATFORM"] = "offscreen"

        # O filho roda EM PARALELO, e não com `subprocess.run`. Bloqueado à
        # espera dele, este processo não giraria a fila de eventos do Qt -- e o
        # `QLocalServer` só aceita a conexão de dentro dela. O filho ficaria
        # esperando por um servidor que está vivo mas surdo, e o teste acusaria
        # um defeito que não existe.
        proc = subprocess.Popen(
            [sys.executable, str(auxiliar),
             json.dumps({"arquivos": nomes, "linha": 4242})],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=ambiente)

        limite = time.monotonic() + 30
        while time.monotonic() < limite and not recebidos:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        QCoreApplication.processEvents()

        try:
            _, erro = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, erro = proc.communicate()
        checa_igual(proc.returncode, 0,
                    f"o outro processo entregou (saída {proc.returncode}) "
                    f"{(erro or '')[-200:]}")

        checa(bool(recebidos), "e o pedido chegou nesta instância")
        if recebidos:
            pedido = recebidos[0]
            checa_igual(len(pedido.get("arquivos", [])), 12,
                        "*** os 12 caminhos chegaram INTEIROS -- é o cabeçalho "
                        "de tamanho que garante isso; sem ele o último viria "
                        "cortado ***")
            checa_igual(pedido["arquivos"], nomes, "e idênticos")
            checa_igual(pedido.get("linha"), 4242, "com a linha junto")
        auxiliar.unlink(missing_ok=True)

    servidor.parar()


def testar_sem_ninguem_escutando() -> None:
    secao("Sem instância aberta")

    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(instancia_unica.nome_do_canal())
    checa(not instancia_unica.entregar({"arquivos": ["x.txt"]}),
          "*** entregar devolve False quando não há ninguém: é assim que o "
          "primeiro processo sabe que deve abrir a janela ***")


def testar_canal_orfao() -> None:
    secao("Canal órfão não impede abrir")

    from PySide6.QtNetwork import QLocalServer

    nome = instancia_unica.nome_do_canal()
    QLocalServer.removeServer(nome)

    # Um servidor que ficou para trás sem ninguém atendendo: é o que sobra
    # quando o programa morre sem fechar o canal.
    orfao = QLocalServer()
    orfao.listen(nome)

    servidor = instancia_unica.Servidor()
    assumiu = servidor.escutar()
    checa(assumiu or True,
          "com um canal ocupado, escutar decide sem estourar")
    orfao.close()
    QLocalServer.removeServer(nome)
    servidor2 = instancia_unica.Servidor()
    checa(servidor2.escutar(),
          "*** e depois de o órfão sair, o canal é assumido normalmente ***")
    servidor2.parar()
    servidor.parar()



def _sem_perguntar(monitor: list):
    """Troca o QMessageBox.question por um espiao que NUNCA responde.

    Qualquer pergunta durante o fechamento cai aqui e e' registrada. E' o
    coracao deste teste: um `question` de verdade travaria a suite esperando
    um clique, e um que responde "descartar" esconderia justamente o defeito
    que se quer vigiar.
    """
    from PySide6.QtWidgets import QMessageBox

    original = QMessageBox.question

    def espiao(*args, **_kwargs):
        monitor.append(args[2] if len(args) > 2 else "?")
        return QMessageBox.StandardButton.Discard

    QMessageBox.question = staticmethod(espiao)
    return original


def testar_documento_novo_nao_pergunta_e_volta() -> None:
    """PEDIDO: um documento novo nao pergunta ao fechar, e reaparece depois.

    O que tornava isso possivel ja' estava pronto desde a v0.10.0: um
    documento novo nasce como ARQUIVO de verdade numa pasta interna. O que
    faltava e' que ele nascia com ZERO BYTE -- o texto digitado vive na tabela
    de pecas, nao no disco. Fechar sem perguntar, sem guardar antes, perderia
    tudo em silencio, que e' pior que a caixa de dialogo.
    """
    secao("*** Documento novo: nao pergunta ao fechar, e volta depois ***")

    from PySide6.QtWidgets import QMessageBox
    from tfedit import sessao as sessao_mod
    from tfedit.interface.janela_principal import JanelaPrincipal

    TEXTO = "anotação que não foi salva em lugar nenhum"

    perguntas: list = []
    original = _sem_perguntar(perguntas)
    try:
        janela = JanelaPrincipal({"restaurar_sessao": True})
        checa(janela.novo(), "cria o documento novo")
        aba = janela.aba_atual
        nome = aba.nome
        caminho = pathlib.Path(aba.caminho)
        checa(aba.e_rascunho, f"e ele e' um rascunho: {nome!r}")
        checa_igual(caminho.stat().st_size, 0,
                    "*** que nasce com ZERO BYTE: o texto ainda nao esta' no "
                    "disco ***")

        aba.editor.insertPlainText(TEXTO)
        aba.editor.sincronizar()
        checa(aba.modificado, "com texto digitado e nao salvo")

        # Fecha o PROGRAMA.
        janela.close()
        drenar_eventos()

        checa_igual(perguntas, [],
                    f"*** NENHUMA pergunta ao fechar: nao ha' o que perder, "
                    f"entao nao ha' o que perguntar. Perguntou: "
                    f"{perguntas} ***")
        checa(caminho.stat().st_size > 0,
              f"*** e o texto FOI para o disco ({caminho.stat().st_size} "
              f"bytes): 'manter sem salvar' so' e' seguro se houver onde "
              f"manter ***")

        guardadas = sessao_mod.ler()
        rascunhos = [g for g in guardadas if g.sem_titulo]
        checa_igual([g.sem_titulo for g in rascunhos], [nome],
                    "*** e a sessao guardou o rascunho, com o nome ***")

        # Abre de novo: ele reaparece.
        outra = JanelaPrincipal({"restaurar_sessao": True})
        try:
            checa_igual(outra.restaurar_sessao(), 1, "uma aba voltou")
            volta = outra.aba_atual
            checa_igual(volta.nome, nome,
                        f"*** com o MESMO nome, {nome!r}, e nao o caminho da "
                        f"pasta interna ***")
            checa(volta.e_rascunho,
                  "*** e ainda e' um rascunho: o proximo Ctrl+S continua "
                  "perguntando onde salvar, em vez de gravar escondido ***")
            conteudo = volta.documento.ler(0, volta.documento.tamanho)
            checa(TEXTO.encode() in conteudo,
                  f"*** e o texto voltou inteiro ***")
        finally:
            outra.close()
            drenar_eventos()
    finally:
        QMessageBox.question = original


def testar_rascunho_da_sessao_escapa_da_limpeza() -> None:
    """A limpeza roda ANTES da restauracao, e nao pode levar o rascunho junto.

    Sem esta protecao, um documento novo deixado aberto mais de uma semana
    seria apagado instantes antes de voltar -- e a aba simplesmente nao
    reapareceria, sem erro nenhum na tela. Justamente o rascunho mais
    valioso: o que a pessoa manteve por mais tempo.
    """
    secao("*** O rascunho da sessao escapa da limpeza por idade ***")

    import os
    import time

    from tfedit.interface.aba import (limpar_rascunhos_antigos,
                                      pasta_de_rascunhos, rascunhos_da_sessao)
    from tfedit import sessao as sessao_mod

    pasta = pasta_de_rascunhos()
    pasta.mkdir(parents=True, exist_ok=True)
    guardado = pasta / "teste-guardado.txt"
    perdido = pasta / "teste-perdido.txt"
    guardado.write_text("texto que a sessao promete reabrir", encoding="utf-8")
    perdido.write_text("orfao de um fechamento anormal", encoding="utf-8")

    # Os dois com 30 dias: a IDADE e' igual, so' a sessao os distingue.
    antigo = time.time() - 30 * 86400
    os.utime(guardado, (antigo, antigo))
    os.utime(perdido, (antigo, antigo))

    sessao_mod.gravar([sessao_mod.AbaGuardada(
        caminho=str(guardado), sem_titulo="Sem título 1")])
    try:
        checa(guardado.resolve() in rascunhos_da_sessao(),
              "a sessao promete reabrir o primeiro")
        limpar_rascunhos_antigos(dias=7)

        checa(guardado.is_file(),
              "*** o rascunho da sessao SOBREVIVEU, com 30 dias ***")
        checa(not perdido.is_file(),
              "*** e o orfao da mesma idade foi apagado: a diferenca e' a "
              "sessao, e nao a idade ***")
    finally:
        sessao_mod.esquecer()
        guardado.unlink(missing_ok=True)
        perdido.unlink(missing_ok=True)

def main() -> int:
    if not TEM_QT:
        return pular("PySide6 não está instalado")
    testar_diario_e_pequeno()
    testar_diario_incoerente()
    testar_assinatura_da_sessao()
    testar_gravar_e_ler()
    testar_canal()
    testar_entrega_entre_processos()
    testar_sem_ninguem_escutando()
    testar_canal_orfao()
    testar_documento_novo_nao_pergunta_e_volta()
    testar_rascunho_da_sessao_escapa_da_limpeza()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
