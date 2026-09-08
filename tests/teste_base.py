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


def main() -> int:
    testar_configuracao()
    testar_recentes()
    testar_cli()
    testar_trava_do_mapeamento()
    testar_soltar_e_retomar()
    testar_assinatura()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
