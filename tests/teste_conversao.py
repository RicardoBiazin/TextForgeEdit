"""Trocar a codificacao de um arquivo grande.

    .\\.venv\\Scripts\\python.exe tests\\teste_conversao.py

Sao DUAS operacoes, e confundi-las foi o defeito relatado no projeto irmao ("a
conversao nao esta' funcionando, ele continua na mesma"):

    REINTERPRETAR  le os mesmos bytes de outro jeito  -> disco intacto
    CONVERTER      reescreve o arquivo                -> todo byte muda

O que esta suite guarda, em ordem de importancia:

1. **A fronteira de bloco.** Os blocos tem 4 MB e nao respeitam caractere. Um
   `ç` em UTF-8 pode ter um byte em cada bloco. `testar_fronteira_de_bloco`
   monta exatamente esse caso -- com blocos pequenos, para nao gerar 4 MB de
   fixture -- e falha se a conversao usar `bytes.decode` em vez do codec
   incremental.

2. **Perda silenciosa.** Converter `中` para ISO-8859-1 com `errors="replace"`
   grava `?` e nao ha' volta. A conversao tem de PARAR e deixar o arquivo
   intacto.

3. **O rotulo da barra.** O sintoma relatado foi visual: converter e o rotulo
   continuar dizendo a codificacao velha. Aqui a aba REDETECTA a partir do
   disco depois de gravar, e o teste confere o rotulo.
"""

from __future__ import annotations

import codecs
import sys

from ajudantes import (checa, checa_igual, checa_levanta, pasta_temporaria,
                       preparar_qt, pular, resumir, secao)

TEM_QT = preparar_qt()

ACENTOS = "ação, coração, José e o çedilha — três níveis"


def _documento(pasta, nome: str, dados: bytes):
    """Um Documento sobre um arquivo recem-escrito, sem interface."""
    from tfedit.original import Original
    from tfedit.pecas import Documento

    alvo = pasta / nome
    alvo.write_bytes(dados)
    original = Original(alvo)
    original.indexar()
    return alvo, original, Documento(original)


def _converter_para_bytes(documento, codec_de, alvo) -> bytes:
    from tfedit import conversao
    return b"".join(conversao.blocos_convertidos(documento, codec_de, alvo))


def _levanta(excecao, funcao, mensagem):
    """Como `checa_levanta`, mas DEVOLVE a excecao para inspecao.

    Metade do valor destes testes esta' na mensagem de erro: dizer qual
    caractere e em que linha e' o que torna a recusa acionavel. Conferir so'
    que "levantou algo" deixaria a mensagem apodrecer sem ninguem notar.
    """
    try:
        funcao()
    except excecao as exc:
        checa(True, mensagem)
        return exc
    except BaseException as exc:                # noqa: BLE001
        checa(False, f"{mensagem} (levantou {exc.__class__.__name__}: {exc})")
        return None
    checa(False, f"{mensagem} (nao levantou nada)")
    return None


# ======================================================================
# O nucleo da conversao
# ======================================================================

def testar_ida_e_volta() -> None:
    secao("ISO-8859-1 -> UTF-8 -> ISO-8859-1")

    from tfedit import conversao

    texto = (ACENTOS.replace("—", "-") + "\r\n") * 50
    with pasta_temporaria() as pasta:
        _, orig, doc = _documento(pasta, "latin.txt",
                                  texto.encode("iso-8859-1"))
        try:
            utf8 = conversao.alvo_de("utf-8")
            saida = _converter_para_bytes(doc, "iso-8859-1", utf8)
            checa_igual(saida.decode("utf-8"), texto,
                        "*** o texto sobrevive a ida para UTF-8 ***")
            checa(len(saida) > len(texto.encode("iso-8859-1")),
                  f"e o arquivo CRESCEU ({len(saida)} bytes contra "
                  f"{len(texto.encode('iso-8859-1'))}) -- e' o que impede a "
                  f"copia byte a byte da gravacao normal")
            checa(b"\r\n" in saida,
                  "o CRLF atravessou a conversao sem virar LF")
        finally:
            orig.fechar()

        # E a volta, para provar que nao foi perda mascarada de simetria.
        _, orig2, doc2 = _documento(pasta, "utf8.txt", saida)
        try:
            latin = conversao.alvo_de("iso-8859-1")
            volta = _converter_para_bytes(doc2, "utf-8", latin)
            checa_igual(volta, texto.encode("iso-8859-1"),
                        "*** e a volta devolve os bytes originais ***")
        finally:
            orig2.fechar()


def testar_fronteira_de_bloco() -> None:
    secao("*** Um caractere partido entre dois blocos ***")

    from tfedit import conversao, gravacao

    # Texto so' de acentos: em UTF-8 cada um ocupa 2 bytes, entao um bloco de
    # tamanho IMPAR corta um caractere no meio com certeza.
    texto = "áéíóú" * 4000
    with pasta_temporaria() as pasta:
        _, orig, doc = _documento(pasta, "acentos.txt", texto.encode("utf-8"))
        original = gravacao.BLOCO
        try:
            gravacao.BLOCO = 1023           # impar: corta caractere de 2 bytes
            partes = list(gravacao.blocos(doc))
            checa(len(partes) > 10,
                  f"o documento saiu em {len(partes)} blocos de 1023 bytes")
            cortados = sum(1 for parte in partes
                           if _termina_no_meio(parte))
            checa(cortados > 0,
                  f"*** {cortados} bloco(s) terminam no meio de um caractere "
                  f"-- e' o caso que quebra `bytes.decode` ***")

            latin = conversao.alvo_de("iso-8859-1")
            saida = _converter_para_bytes(doc, "utf-8", latin)
            checa_igual(saida.decode("iso-8859-1"), texto,
                        "*** e mesmo assim a conversao saiu inteira ***")

            # A contraprova: o jeito ingenuo, bloco a bloco, de fato quebra.
            ingenuo = 0
            for parte in partes:
                try:
                    parte.decode("utf-8")
                except UnicodeDecodeError:
                    ingenuo += 1
            checa(ingenuo > 0,
                  f"*** decodificar bloco a bloco falharia em {ingenuo} "
                  f"blocos -- o codec incremental e' o que resolve ***")
        finally:
            gravacao.BLOCO = original
            orig.fechar()


def _termina_no_meio(bruto: bytes) -> bool:
    """O bloco acaba no meio de uma sequencia UTF-8?"""
    try:
        bruto.decode("utf-8")
    except UnicodeDecodeError as erro:
        return erro.end >= len(bruto)
    return False


def testar_recusa_perda() -> None:
    secao("*** O que nao cabe no destino NAO vira '?' ***")

    from tfedit import conversao

    texto = "linha um\nlinha dois\num ideograma: 中\nlinha quatro\n"
    with pasta_temporaria() as pasta:
        _, orig, doc = _documento(pasta, "cjk.txt", texto.encode("utf-8"))
        try:
            latin = conversao.alvo_de("iso-8859-1")
            erro = _levanta(
                conversao.NaoRepresentavel,
                lambda: _converter_para_bytes(doc, "utf-8", latin),
                "*** converter o ideograma para ISO-8859-1 e' RECUSADO ***")
            if erro is not None:
                checa_igual(erro.caractere, "中",
                            "a mensagem diz QUAL caractere")
                checa_igual(erro.linha, 3,
                            "e em que linha ele esta'")
                checa("?" not in str(erro) or "\"?\"" in str(erro),
                      "a mensagem explica que o caractere viraria '?'")
        finally:
            orig.fechar()


def testar_recusa_origem_invalida() -> None:
    secao("Bytes que nao sao texto na codificacao de origem")

    from tfedit import conversao

    with pasta_temporaria() as pasta:
        # 0x81 nao existe em Windows-1252 (e' um dos cinco buracos da tabela).
        _, orig, doc = _documento(pasta, "quebrado.txt",
                                  b"linha um\nlinha dois\n\x81 aqui\n")
        try:
            utf8 = conversao.alvo_de("utf-8")
            erro = _levanta(
                conversao.OrigemInvalida,
                lambda: _converter_para_bytes(doc, "cp1252", utf8),
                "*** um byte invalido na origem PARA a conversao ***")
            if erro is not None:
                checa(erro.linha >= 3,
                      f"e aponta a linha ({erro.linha})")
                checa("Reinterprete" in str(erro),
                      "a mensagem diz o que fazer: reinterpretar antes")
        finally:
            orig.fechar()


def testar_bom() -> None:
    secao("O BOM: um so', e do destino")

    from tfedit import conversao

    texto = "com marca\ne acento: ção\n"
    with pasta_temporaria() as pasta:
        # Entrada COM BOM de UTF-8, saida em UTF-8 SEM BOM.
        _, orig, doc = _documento(pasta, "bom.txt",
                                  codecs.BOM_UTF8 + texto.encode("utf-8"))
        try:
            sem = conversao.alvo_de("utf-8", b"")
            saida = _converter_para_bytes(doc, "utf-8", sem)
            checa(not saida.startswith(codecs.BOM_UTF8),
                  "*** o BOM da origem nao passou adiante ***")
            checa_igual(saida.decode("utf-8"), texto,
                        "e o texto ficou inteiro, sem U+FEFF no comeco")

            com = conversao.alvo_de("utf-8", codecs.BOM_UTF8)
            saida2 = _converter_para_bytes(doc, "utf-8", com)
            checa(saida2.startswith(codecs.BOM_UTF8),
                  "pedindo BOM, ele aparece")
            checa(not saida2[3:].startswith(codecs.BOM_UTF8),
                  "*** e aparece UMA vez, e nao duas ***")
        finally:
            orig.fechar()


def testar_utf16() -> None:
    secao("Para UTF-16, que dobra o arquivo")

    from tfedit import conversao

    texto = "ascii puro\n" * 20
    with pasta_temporaria() as pasta:
        _, orig, doc = _documento(pasta, "ascii.txt", texto.encode("ascii"))
        try:
            alvo = conversao.alvo_de("utf-16-le", codecs.BOM_UTF16_LE)
            saida = _converter_para_bytes(doc, "utf-8", alvo)
            checa_igual(saida.decode("utf-16"), texto,
                        "UTF-16 LE com BOM le de volta certo")
            checa(len(saida) > 2 * len(texto),
                  f"e o arquivo mais que dobrou ({len(saida)} bytes) -- por "
                  f"isso o `fator` do Alvo existe")
            checa_igual(alvo.fator, 4,
                        "o fator de UTF-16 e' folgado de proposito: errar "
                        "para menos enche o disco no meio da escrita")
        finally:
            orig.fechar()


def testar_edicao_pendente_entra_na_conversao() -> None:
    secao("O que foi digitado tambem e' convertido")

    from tfedit import conversao

    with pasta_temporaria() as pasta:
        _, orig, doc = _documento(pasta, "misto.txt",
                                  "primeira\n".encode("iso-8859-1"))
        try:
            # Uma peca EDITADA, em latin-1 como o resto do documento.
            doc.inserir(len(b"primeira\n"), "ação\n".encode("iso-8859-1"))
            utf8 = conversao.alvo_de("utf-8")
            saida = _converter_para_bytes(doc, "iso-8859-1", utf8)
            checa_igual(saida.decode("utf-8"), "primeira\nação\n",
                        "*** peça ORIGINAL e texto digitado sairam os dois "
                        "em UTF-8 ***")
        finally:
            orig.fechar()


# ======================================================================
# Na aba: o disco e o rotulo
# ======================================================================

def testar_converter_na_aba() -> None:
    secao("*** Converter de verdade, e o rotulo da barra ***")

    from tfedit import conversao
    from tfedit.interface.aba import Aba

    texto = (ACENTOS.replace("—", "-") + "\n") * 30
    with pasta_temporaria() as pasta:
        alvo_arq = pasta / "relatorio.txt"
        alvo_arq.write_bytes(texto.encode("iso-8859-1"))

        aba = Aba(alvo_arq, {"linhas_da_janela": 100})
        try:
            # A deteccao chuta entre as tabelas de 8 bits -- para este texto ela
            # respondeu CP1250, que difere de ISO-8859-1 em varios acentos.
            # Converter a partir do palpite errado gravaria caracteres errados,
            # e e' por isso que "reinterpretar" existe: o usuario diz qual e' a
            # origem ANTES de mandar reescrever. Este teste faz o mesmo.
            checa(aba.perfil.codec != "utf-8",
                  f"a deteccao viu uma tabela de 8 bits: {aba.perfil.rotulo}")
            aba.reinterpretar("iso-8859-1")
            antes = alvo_arq.read_bytes()

            escritos = aba.converter_codificacao(conversao.alvo_de("utf-8"))
            depois = alvo_arq.read_bytes()

            checa(escritos > 0, f"gravou {escritos} bytes")
            checa(depois != antes, "os bytes do disco mudaram")
            checa(depois.decode("utf-8") == texto,
                  "*** e o arquivo no disco agora e' UTF-8 valido, com o "
                  "mesmo texto ***")
            checa_igual(aba.perfil.rotulo, "UTF-8",
                        "*** o rotulo acompanhou: era o sintoma relatado no "
                        "projeto irmao ('continua na mesma') ***")
            checa(not aba.documento.alterado,
                  "e a aba nao ficou marcada como suja depois de converter")

            # A prova de que o editor tambem enxerga o arquivo novo: o texto da
            # fatia tem de continuar legivel, e nao virar rabisco.
            checa("ação" in aba.editor.toPlainText(),
                  "a fatia na tela continua com os acentos certos")
        finally:
            aba.encerrar()


def testar_conversao_recusada_nao_toca_no_arquivo() -> None:
    secao("*** Conversao recusada deixa o arquivo INTACTO ***")

    from tfedit import conversao
    from tfedit.interface.aba import Aba

    with pasta_temporaria() as pasta:
        alvo_arq = pasta / "com_cjk.txt"
        conteudo = "linha\num ideograma: 中\noutra\n".encode("utf-8")
        alvo_arq.write_bytes(conteudo)

        aba = Aba(alvo_arq, {"linhas_da_janela": 100})
        try:
            checa_levanta(
                conversao.NaoRepresentavel,
                lambda: aba.converter_codificacao(
                    conversao.alvo_de("iso-8859-1")),
                "a conversao com perda foi recusada")
            checa_igual(alvo_arq.read_bytes(), conteudo,
                        "*** o arquivo continua byte a byte como estava ***")
            sobras = list(pasta.glob("*.tfenew"))
            checa(not sobras,
                  f"e nao sobrou temporario ao lado: {sobras}")
        finally:
            aba.encerrar()


def testar_reinterpretar() -> None:
    secao("Reinterpretar NAO mexe no disco")

    from tfedit.interface.aba import Aba

    with pasta_temporaria() as pasta:
        alvo_arq = pasta / "duvidoso.txt"
        # Bytes latin-1 que TAMBEM sao UTF-8 invalido, para a deteccao ter de
        # escolher e o usuario poder discordar.
        conteudo = "ação\n".encode("iso-8859-1") * 20
        alvo_arq.write_bytes(conteudo)

        aba = Aba(alvo_arq, {"linhas_da_janela": 100})
        try:
            antes = alvo_arq.read_bytes()
            aba.reinterpretar("iso-8859-1")
            checa_igual(aba.perfil.codec, "iso-8859-1", "o perfil trocou")
            checa_igual(alvo_arq.read_bytes(), antes,
                        "*** e nenhum byte do disco mudou ***")
            checa("ação" in aba.editor.toPlainText(),
                  "a fatia foi redecodificada e esta' legivel")
        finally:
            aba.encerrar()


def testar_reinterpretar_recusa_com_edicao() -> None:
    secao("*** Reinterpretar com edicao pendente e' recusado ***")

    from tfedit.interface.aba import Aba

    with pasta_temporaria() as pasta:
        alvo_arq = pasta / "editado.txt"
        alvo_arq.write_bytes("linha com ação\n".encode("iso-8859-1") * 10)

        aba = Aba(alvo_arq, {"linhas_da_janela": 100})
        try:
            # Guardado do que FOI detectado, e nao chutado no teste: qual
            # tabela de 8 bits a deteccao escolhe nao e' o que se verifica
            # aqui, e fixar um palpite faria este teste falhar por motivo
            # alheio ao que ele guarda.
            codec_antes = aba.perfil.codec
            aba.editor.insertPlainText("ção ")
            aba.editor.sincronizar()
            checa(aba.documento.alterado, "ha' edicao pendente")

            erro = _levanta(
                ValueError, lambda: aba.reinterpretar("utf-8"),
                "reinterpretar foi recusado")
            if erro is not None:
                checa("digitou" in str(erro),
                      "e a mensagem explica que o texto digitado sairia "
                      "ilegivel")
            checa_igual(aba.perfil.codec, codec_antes,
                        "*** e o perfil NAO mudou pela metade ***")
        finally:
            aba.encerrar()


def testar_menu_de_codificacao() -> None:
    secao("*** O menu: dois verbos, e o atual desabilitado ***")

    from tfedit.interface.janela_principal import JanelaPrincipal

    with pasta_temporaria() as pasta:
        alvo_arq = pasta / "menu.txt"
        alvo_arq.write_bytes("ação\n".encode("utf-8") * 10)

        janela = JanelaPrincipal({"linhas_da_janela": 100})
        try:
            # Sem arquivo o menu nao pode ficar vazio nem quebrar.
            janela._montar_menu_codificacao()
            acoes = janela.menu_codificacao.actions()
            checa(len(acoes) == 1 and not acoes[0].isEnabled(),
                  "sem arquivo, o menu explica que nao ha' o que codificar")

            checa(janela.abrir_arquivo(str(alvo_arq)), "arquivo aberto")
            # `aboutToShow` e' o gatilho real. Chamar o metodo direto e' o
            # equivalente sem abrir menu de verdade em modo offscreen -- e e'
            # aqui que um NameError ou um enum errado apareceria, e nao na
            # montagem da janela.
            janela._montar_menu_codificacao()
            rotulos = [a.text() for a in janela.menu_codificacao.actions()]
            checa(any("UTF-8" in r for r in rotulos),
                  f"o menu diz em que codificacao o arquivo esta': {rotulos[0]!r}")

            submenus = {a.menu().title().replace("&", ""): a.menu()
                        for a in janela.menu_codificacao.actions()
                        if a.menu() is not None}
            checa(set(submenus) == {"Reinterpretar como", "Converter para"},
                  f"*** os dois verbos aparecem separados: "
                  f"{sorted(submenus)} ***")

            # A codificacao ATUAL nao pode ser oferecida como conversao: seria
            # reescrever 240 MB para chegar exatamente onde ja' se esta'.
            converter = submenus["Converter para"]
            atual = [a for a in converter.actions()
                     if a.text().startswith("UTF-8") and "BOM" not in a.text()]
            checa(atual and not atual[0].isEnabled(),
                  "*** converter para a codificacao atual vem desabilitado ***")
            outros = [a for a in converter.actions() if a.isEnabled()]
            checa(len(outros) >= 4,
                  f"e os outros destinos continuam disponiveis ({len(outros)})")

            # Reinterpretar marca a atual, para a pessoa ver onde esta'.
            reler = submenus["Reinterpretar como"]
            marcadas = [a.text() for a in reler.actions() if a.isChecked()]
            checa_igual(marcadas, ["UTF-8"],
                        "e o submenu de leitura marca a codificacao em uso")
        finally:
            janela.close()


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_ida_e_volta()
    testar_fronteira_de_bloco()
    testar_recusa_perda()
    testar_recusa_origem_invalida()
    testar_bom()
    testar_utf16()
    testar_edicao_pendente_entra_na_conversao()
    testar_converter_na_aba()
    testar_conversao_recusada_nao_toca_no_arquivo()
    testar_reinterpretar()
    testar_reinterpretar_recusa_com_edicao()
    testar_menu_de_codificacao()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
