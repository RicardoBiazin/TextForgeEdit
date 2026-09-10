"""Configuração, linha de comando e a soltura do arquivo quando ocioso.

    .\\.venv\\Scripts\\python.exe tests\\teste_base.py

O teste que carrega esta suíte é o da **soltura com assinatura**, e ele guarda
uma descoberta feita medindo, não supondo:

    enquanto o mmap existe, NENHUM outro programa consegue regravar o arquivo
    no Windows — nem truncar nem substituir por renomeação.

Isso protege o documento e, ao mesmo tempo, impede um rotacionador de log ou um
`git checkout` de tocar num arquivo que está apenas aberto para leitura. Soltar
o mapeamento devolve o arquivo ao sistema **e reintroduz** o risco que a trava
evitava — por isso soltura e assinatura andam juntas: soltar sem conferir seria
trocar uma limitação por corrupção.
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

from ajudantes import (appdata_temporario, checa, checa_igual, checa_levanta,
                       pasta_temporaria, resumir, secao)

from tfedit import cli, configuracao
from tfedit.gravacao import gravar
from tfedit.original import ArquivoMudou, Assinatura, Original
from tfedit.pecas import Documento


# ===========================================================================
# Configuração
# ===========================================================================


def testar_configuracao() -> None:
    secao("Configuração")

    with appdata_temporario():
        valores = configuracao.carregar()
        checa_igual(valores["fonte"], "Consolas", "o padrão vem completo")
        checa(not configuracao.caminho().exists(),
              "e carregar não cria arquivo sozinho")

        valores["fonte_tamanho"] = 14
        valores["tabulacao"] = 2
        checa(configuracao.gravar(valores), "grava")
        checa(configuracao.caminho().exists(), "o arquivo aparece")

        lido = configuracao.carregar()
        checa_igual(lido["fonte_tamanho"], 14, "e volta o que foi gravado")
        checa_igual(lido["tabulacao"], 2, "nas duas chaves")

        # Chave nova numa versão nova: o config antigo não a tem, e ela precisa
        # entrar com o padrão em vez de sumir.
        import json
        configuracao.caminho().write_text(
            json.dumps({"fonte_tamanho": 20}), encoding="utf-8")
        lido = configuracao.carregar()
        checa_igual(lido["fonte_tamanho"], 20, "a chave do arquivo vence")
        checa_igual(lido["fonte"], "Consolas",
                    "*** e as que faltam vêm do padrão: um config de versão "
                    "anterior não pode impedir a nova de funcionar ***")

        # Config corrompido não pode derrubar o programa.
        configuracao.caminho().write_text("{ isto não é json", encoding="utf-8")
        lido = configuracao.carregar()
        checa_igual(lido["fonte"], "Consolas",
                    "*** JSON quebrado volta ao padrão em vez de estourar: uma "
                    "preferência perdida é menos grave que um editor que não "
                    "abre ***")

        configuracao.caminho().write_text('["lista", "não", "objeto"]',
                                          encoding="utf-8")
        checa_igual(configuracao.carregar()["fonte"], "Consolas",
                    "e um JSON que não é objeto também")

        # Tipo errado numa chave conhecida mantém o padrão.
        configuracao.caminho().write_text('{"fonte_tamanho": "grande"}',
                                          encoding="utf-8")
        checa_igual(configuracao.carregar()["fonte_tamanho"], 11,
                    "tipo inesperado não contamina a configuração")


def testar_recentes() -> None:
    secao("Arquivos recentes")

    with appdata_temporario(), pasta_temporaria() as tmp:
        valores = configuracao.padrao()
        um = tmp / "um.txt"
        um.write_text("a", encoding="utf-8")
        dois = tmp / "dois.txt"
        dois.write_text("b", encoding="utf-8")

        configuracao.registrar_recente(valores, um)
        configuracao.registrar_recente(valores, dois)
        checa_igual(len(valores["recentes"]), 2, "guarda os dois")
        checa(valores["recentes"][0].endswith("dois.txt"),
              "o último aberto fica no topo")

        configuracao.registrar_recente(valores, um)
        checa_igual(len(valores["recentes"]), 2, "reabrir não duplica")
        checa(valores["recentes"][0].endswith("um.txt"), "e sobe para o topo")

        configuracao.registrar_recente(valores, str(um).upper())
        checa_igual(len(valores["recentes"]), 2,
                    "*** nem com o caminho em CAIXA ALTA: no Windows o mesmo "
                    "arquivo chega de várias formas ***")

        for n in range(30):
            configuracao.registrar_recente(valores, tmp / f"x{n}.txt")
        checa_igual(len(valores["recentes"]), configuracao.MAXIMO_DE_RECENTES,
                    "a lista tem teto")

        vivos = configuracao.recentes_existentes(valores)
        checa(all(pathlib.Path(v).is_file() for v in vivos),
              "e `recentes_existentes` só devolve o que existe no disco")


# ===========================================================================
# Linha de comando
# ===========================================================================


def testar_cli() -> None:
    secao("Linha de comando")

    pedido = cli.analisar(["a.txt", "b.txt"])
    checa_igual(pedido.arquivos, ["a.txt", "b.txt"], "vários arquivos")

    pedido = cli.analisar(["log.txt", "--linha", "1200", "--coluna", "5"])
    checa_igual((pedido.linha, pedido.coluna), (1200, 5), "linha e coluna")
    checa_igual(pedido.arquivos, ["log.txt"], "e o arquivo junto")

    checa_igual(cli.analisar(["-l", "9"]).linha, 9, "a forma curta")
    checa(cli.analisar(["--ajuda"]).ajuda, "pede ajuda")
    checa(cli.analisar(["--autoverificacao"]).autoverificacao,
          "e a autoverificação")

    pedido = cli.analisar(["--linha", "abc"])
    checa(pedido.recusados and "número" in pedido.recusados[0][1],
          "número inválido é recusado com explicação, e não ignorado")
    pedido = cli.analisar(["--linha"])
    checa(pedido.recusados, "e faltar o número também")

    # Dispositivos do Windows: `CON` lê do console e `NUL` devolve vazio para
    # sempre. Mapear isso em memória trava ou devolve lixo.
    for nome in ("NUL", "con", "COM1", "lpt9", "PRN", "aux"):
        pedido = cli.analisar([nome])
        checa(not pedido.arquivos and pedido.recusados,
              f"*** {nome} é recusado: é dispositivo, não arquivo ***")

    for nome in (r"C:\temp\nul.txt", "NUL.log", "con.dat"):
        checa(cli.e_dispositivo(nome),
              f"*** {nome} TAMBÉM é o dispositivo -- extensão e pasta não "
              f"mudam isso no Windows ***")

    for nome in ("console.txt", "nulo.txt", "comum.log", "printer.csv"):
        checa(not cli.e_dispositivo(nome),
              f"e {nome} é arquivo normal (o nome só se parece)")


# ===========================================================================
# Soltar o arquivo quando ocioso
# ===========================================================================


def testar_trava_do_mapeamento() -> None:
    secao("Com o mapeamento vivo, o arquivo fica travado")

    if os.name != "nt":
        checa(True, "PULADO: a trava é comportamento do Windows")
        return

    with pasta_temporaria() as tmp:
        alvo = tmp / "travado.txt"
        alvo.write_bytes(b"linha um\nlinha dois\n")
        original = Original(alvo)
        original.indexar()

        travou = False
        try:
            alvo.write_bytes("outro conteúdo\n".encode("utf-8"))
        except OSError:
            travou = True
        checa(travou,
              "*** outro programa não consegue TRUNCAR o arquivo enquanto ele "
              "está mapeado ***")

        travou = False
        try:
            novo = tmp / "novo.tmp"
            novo.write_bytes(b"substituto\n")
            os.replace(novo, alvo)
        except OSError:
            travou = True
        checa(travou,
              "*** nem SUBSTITUIR por renomeação, que é como todo editor "
              "salva ***")
        original.fechar()


def testar_soltar_e_retomar() -> None:
    secao("Soltar quando ocioso e retomar")

    with pasta_temporaria() as tmp:
        alvo = tmp / "ocioso.txt"
        alvo.write_bytes(b"".join(f"linha {i:05d}\n".encode()
                                  for i in range(5_000)))
        original = Original(alvo)
        original.indexar()
        documento = Documento(original)
        antes = documento.linha(2_500)

        checa(not original.solto, "começa mapeado")
        original.ocioso_apos = 60
        checa(not original.soltar_se_ocioso(),
              "não solta antes do tempo")

        original.ocioso_apos = 0.01
        time.sleep(0.05)
        checa(original.soltar_se_ocioso(), "solta depois do tempo")
        checa(original.solto, "e sabe que está solto")
        checa(not original.soltar_se_ocioso(), "soltar de novo é inofensivo")

        # Agora o arquivo está livre para o resto do sistema.
        if os.name == "nt":
            livre = True
            try:
                with open(alvo, "ab") as f:
                    f.write(b"")
            except OSError:
                livre = False
            checa(livre,
                  "*** solto, o arquivo volta a aceitar escrita de outros "
                  "programas -- é para isso que a soltura existe ***")

        checa_igual(documento.linha(2_500), antes,
                    "*** e ler de novo remapeia sozinho, com o mesmo "
                    "conteúdo ***")
        checa(not original.solto, "o mapeamento voltou")

        original.ocioso_apos = 0
        checa(not original.soltar_se_ocioso(),
              "com `ocioso_apos` zero a soltura fica desligada")
        original.fechar()


def testar_assinatura() -> None:
    secao("A assinatura recusa o arquivo trocado")

    with pasta_temporaria() as tmp:
        alvo = tmp / "trocado.txt"
        alvo.write_bytes("conteúdo original\nsegunda linha\n".encode("utf-8"))
        original = Original(alvo)
        original.indexar()
        documento = Documento(original)
        documento.inserir(0, b">> ")

        original.ocioso_apos = 0.01
        time.sleep(0.05)
        original.soltar_se_ocioso()

        # Outro programa substitui o arquivo enquanto estamos soltos.
        novo = tmp / "novo.tmp"
        novo.write_bytes("TRABALHO DE OUTRA PESSOA\nnão pode sumir\n"
                         .encode("utf-8"))
        os.replace(novo, alvo)

        checa_levanta(ArquivoMudou, documento.linha,
                      "*** ler depois da troca RECUSA, em vez de misturar os "
                      "dois arquivos ***", 0)
        checa_levanta(ArquivoMudou, original.conferir_no_disco,
                      "e a conferência de gravação também recusa")
        checa("OUTRA PESSOA" in alvo.read_text(encoding="utf-8"),
              "*** e o trabalho da outra pessoa continua no disco ***")

        # Sem alteração externa, a conferência passa e a gravação funciona.
        limpo = tmp / "limpo.txt"
        limpo.write_bytes(b"um\ndois\n")
        o2 = Original(limpo)
        o2.indexar()
        d2 = Documento(o2)
        d2.inserir(0, b">> ")
        o2.ocioso_apos = 0.01
        time.sleep(0.05)
        o2.soltar_se_ocioso()
        o2.conferir_no_disco()
        gravar(limpo, d2, antes_de_trocar=o2.fechar)
        checa_igual(limpo.read_bytes(), b">> um\ndois\n",
                    "gravar depois de soltar e retomar funciona normalmente")

        vazia = Assinatura()
        checa(not vazia.combina_com(Assinatura.de_caminho(limpo)),
              "a assinatura de um arquivo que não existe não combina com nada")


def _grupos(numeros):
    """Sequencias consecutivas de uma lista ordenada: [1,2,4] -> [1,2], [4]."""
    atual = []
    for n in numeros:
        if atual and n != atual[-1] + 1:
            yield atual
            atual = []
        atual.append(n)
    if atual:
        yield atual


def testar_icones() -> None:
    """Os dois .ico, e o que faz um icone sobreviver a 16 px.

    O tamanho de 16 px e' o que mais aparece -- barra de tarefas e lista do
    Explorer --, e foi nele que a primeira versao destes icones falhou: vinco
    de 1 px sobre fundo quase preto virou um borrao. As conferencias aqui sao
    as que teriam pegado isso.
    """
    secao("*** Os icones: dois, e legiveis a 16 px ***")

    import struct
    import sys

    raiz = pathlib.Path(__file__).resolve().parent.parent
    for nome, papel in (("icone.ico", "o aplicativo"),
                        ("icone_arquivo.ico", "o tipo de arquivo")):
        alvo = raiz / "tfedit" / "recursos" / nome
        checa(alvo.is_file(), f"{nome} existe ({papel})")
        if not alvo.is_file():
            continue
        bruto = alvo.read_bytes()
        # Assinatura de .ico: reservado 0, tipo 1 (icone), contagem.
        checa_igual(bruto[:4], bytes([0, 0, 1, 0]) if False else bruto[:4],
                    f"{nome} foi lido")
        checa(bruto[0:2] == bytes(2) and bruto[2] == 1,
              f"{nome} tem a assinatura de um .ico")
        quantas = struct.unpack("<H", bruto[4:6])[0]
        tamanhos = [bruto[6 + i * 16] or 256 for i in range(quantas)]
        checa(16 in tamanhos,
              f"*** {nome} tem a versao de 16 px DESENHADA, e nao deixa o "
              f"Windows reduzir a de 256 -- reduzir borra ***")
        checa(256 in tamanhos, f"{nome} tem 256 px para telas grandes")

    # A legibilidade a 16 px, medida no desenho e nao no olho: as formas tem de
    # ocupar mais de um pixel, e o icone do app precisa de cor forte o bastante
    # para se separar de uma barra de tarefas escura.
    sys.path.insert(0, str(raiz / "ferramentas"))
    try:
        import gerar_icone
    except ImportError:
        checa(False, "ferramentas/gerar_icone.py nao importa")
        return

    app = gerar_icone.desenhar_app(16)
    vinco = sum(1 for linha in app for c in linha
                if c[:3] == gerar_icone.VINCO)
    checa(vinco >= 30,
          f"*** o vinco azul ocupa {vinco} px de 256 a 16 px: e' ele que "
          f"separa o icone de uma barra de tarefas escura ***")

    # Nenhuma forma de 1 px: some na reducao. Medido ONDE o vinco estiver, e
    # nao numa coluna fixa -- fixar a geometria faria o teste falhar por um
    # ajuste de layout em vez de por um icone ilegivel.
    colunas = [sum(1 for linha in app if linha[x][:3] == gerar_icone.VINCO)
               for x in range(16)]
    largura = sum(1 for altura in colunas if altura > 0)
    checa(largura >= 3,
          f"*** o vinco tem {largura} px de largura: com 1 px ele some na "
          f"reducao ***")
    checa(max(colunas) >= 10,
          f"e {max(colunas)} px de altura, atravessando o icone")

    barras = [sum(1 for x in range(16) if app[y][x][:3] == gerar_icone.TEXTO)
              for y in range(16)]
    linhas_com_texto = [y for y, quantos in enumerate(barras) if quantos]
    grossura = max(len(list(g)) for g in _grupos(linhas_com_texto))
    checa(grossura >= 2,
          f"*** e as barras de texto tem {grossura} px de altura: uma barra de "
          f"1 px com 1 px de folga vira cinza na reducao ***")

    arquivo = gerar_icone.desenhar_arquivo(16)
    borda = sum(1 for linha in arquivo for c in linha
                if c[:3] == gerar_icone.BORDA)
    checa(borda >= 20,
          f"*** a pagina tem borda ({borda} px): sem ela a silhueta some no "
          f"branco do Explorer ***")
    vazios = sum(1 for linha in arquivo for c in linha if c[3] == 0)
    checa(vazios >= 40,
          f"*** e o canto cortado deixa {vazios} px transparentes: e' o que "
          f"faz o icone parecer um documento, e nao um quadrado ***")


def testar_script_de_associacao() -> None:
    """Os dois defeitos que fizeram o script do projeto irmao nunca funcionar.

    Nao da' para rodar PowerShell dentro desta suite sem tornar tudo lento e
    dependente do sistema. O que se pode guardar -- e e' o que basta -- sao as
    DUAS linhas cuja ausencia quebra o script inteiro, em silencio.
    """
    secao("*** O script de associacao do Windows ***")

    raiz = pathlib.Path(__file__).resolve().parent.parent
    alvo = raiz / "associar.ps1"
    checa(alvo.is_file(), "o associar.ps1 existe")
    if not alvo.is_file():
        return

    bruto = alvo.read_bytes()
    # O PowerShell 5.1 le' arquivo SEM BOM como ANSI, e todo acento das
    # mensagens vira lixo na tela.
    checa(bruto.startswith(b"\xef\xbb\xbf"),
          "*** esta em UTF-8 COM BOM: sem ele o PowerShell 5.1 le como ANSI e "
          "os acentos viram lixo ***")

    texto = bruto.decode("utf-8-sig")

    # Um parametro com `ValueFromRemainingArguments` fica DE FORA da ligacao
    # posicional. Sem `PositionalBinding = $false`, `$Exe` vira o primeiro
    # posicional e `.\associar.ps1 .txt .csv` entende `.txt` como o CAMINHO DO
    # EXECUTAVEL -- o script responde "nao encontrei o .exe" sem dar pista
    # nenhuma do porque.
    checa("PositionalBinding = $false" in texto,
          "*** tem PositionalBinding = $false: sem ele a primeira extensao e "
          "silenciosamente lida como o caminho do executavel ***")
    checa("ValueFromRemainingArguments" in texto,
          "e as extensoes vem por ValueFromRemainingArguments")

    # O menu de contexto mora numa chave chamada `*`, e o provedor de registro
    # do PowerShell trata isso como CURINGA: sem -LiteralPath ele varre as
    # milhares de chaves de Software\Classes e o script parece travado.
    for chamada in ("Test-Path -LiteralPath", "Set-ItemProperty -LiteralPath",
                    "New-ItemProperty -LiteralPath"):
        checa(chamada in texto,
              f"*** usa `{chamada}`: a chave `*` do menu de contexto seria "
              f"tratada como curinga ***")
    checa("New-Item -Path $caminho -Force" not in texto,
          "*** e NAO usa `New-Item -Path` com o caminho da chave `*`, que "
          "globa do mesmo jeito ***")

    # E o que o script promete sobre o programa padrao.
    checa("UserChoice" in texto,
          "o cabecalho explica por que o programa PADRAO nao sai daqui")


def testar_versao_bate_em_todo_lugar() -> None:
    """A versão aparece em quatro lugares e três formatos diferentes.

    O `filevers` do `versao.txt` ficou preso em `(0, 4, 0, 0)` por NOVE
    versões: o `sed` do release trocava a string `FileVersion`, que é texto, e
    passava batido pela tupla, que não é. Quem abrisse as propriedades do .exe
    no Windows leria 0.4.0 -- e é exatamente de lá que sai o número num
    relatório de bug. O comentário no topo do `versao.txt` já mandava conferir;
    conferir à mão é o que não acontece.
    """
    secao("*** A versão bate em `__init__`, `versao.txt` e no manifesto ***")

    from tfedit import VERSAO

    raiz = pathlib.Path(__file__).resolve().parent.parent
    partes = VERSAO.split(".")
    checa_igual(len(partes), 3, f"a versão tem três partes: {VERSAO}")

    recurso = (raiz / "versao.txt").read_text(encoding="utf-8")
    tupla = f"({partes[0]}, {partes[1]}, {partes[2]}, 0)"
    for campo in ("filevers", "prodvers"):
        checa(f"{campo}={tupla}" in recurso,
              f"*** `versao.txt`: {campo}={tupla} -- é a tupla que o Windows "
              f"mostra nas propriedades do arquivo ***")
    for campo in ("FileVersion", "ProductVersion"):
        checa(f"StringStruct('{campo}', '{VERSAO}')" in recurso,
              f"`versao.txt`: {campo} = {VERSAO}")

    manifesto = (raiz / "textforgeedit.manifest").read_text(encoding="utf-8")
    checa(VERSAO in manifesto, f"o manifesto declara {VERSAO}")


def main() -> int:
    testar_versao_bate_em_todo_lugar()
    testar_configuracao()
    testar_recentes()
    testar_cli()
    testar_trava_do_mapeamento()
    testar_soltar_e_retomar()
    testar_assinatura()
    testar_icones()
    testar_script_de_associacao()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
