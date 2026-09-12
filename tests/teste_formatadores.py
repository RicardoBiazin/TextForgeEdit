"""Formatar codigo sobre a tabela de pecas.

    .\\.venv\\Scripts\\python.exe tests\\teste_formatadores.py

Os formatadores recebem `str` e devolvem `str` -- nao ha' versao em streaming
disso, e nem daria para haver: indentar exige saber a estrutura inteira. Entao
formatar e' a unica operacao deste editor que precisa do documento inteiro na
memoria, e o teto de 64 MB e' o limite honesto da tecnica, nao um descuido.

O QUE ESTA SUITE GUARDA:

1. **Reformatar um arquivo ja' formatado e' NO-OP.** O resultado e' aparado por
   `_prefixo_comum`/`_sufixo_comum` -- os mesmos da janela viva -- antes de ir
   para a tabela. Sem isso, formatar duas vezes reescreveria o arquivo inteiro
   na segunda, sujaria a aba e mexeria na data ao salvar.

2. **O documento inteiro formatado e' UMA operacao de desfazer.** Um Ctrl+Z tem
   de devolver o arquivo como estava, e nao desfazer paragrafo por paragrafo um
   estado que nunca existiu.

3. **Acima do teto, o comando vem DESABILITADO com o motivo.** Nao tenta e
   falha depois; nao trava a interface enquanto le' 200 MB.
"""

from __future__ import annotations

import sys

from ajudantes import (checa, checa_igual, checa_levanta, pasta_temporaria,
                       preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()


def _janela_com(pasta, nome: str, dados: bytes):
    from tfedit.interface.janela_principal import JanelaPrincipal

    alvo = pasta / nome
    alvo.write_bytes(dados)
    janela = JanelaPrincipal({})
    janela.abrir_arquivo(str(alvo))
    return janela, alvo


def _encerrar(janela) -> None:
    for aba in janela.todas_as_abas():
        janela.abas.removeTab(janela.abas.indexOf(aba))
        aba.encerrar()
    janela.close()


def _conteudo(aba) -> str:
    return aba.documento.ler(0, aba.documento.tamanho).decode(
        aba.perfil.codec, errors="replace")


# ======================================================================
# Os motores
# ======================================================================

def testar_os_cinco_motores() -> None:
    secao("Os cinco motores portados")

    from tfedit import linguagens
    from tfedit.linguagens.registro import REGISTRO

    linguagens.carregar_embutidos()
    for nome in ("JSON", "XML", "CSS", "HTML", "SQL"):
        provedor = REGISTRO.por_nome(nome)
        checa(provedor is not None and provedor.formatador() is not None,
              f"{nome} tem formatador")

    # Deixado de FORA de propósito, e não esquecido: o motor é o black, que
    # seria a maior adição isolada ao .exe, e arquivo-fonte Python não é o
    # motivo deste editor existir.
    python = REGISTRO.por_nome("Python")
    checa(python is not None and python.formatador() is None,
          "*** Python NAO tem formatador: o black ficou fora de propósito ***")
    texto = REGISTRO.por_nome("Texto")
    checa(texto is not None and texto.formatador() is None,
          "e texto puro também não tem")


def testar_motores_formatam() -> None:
    secao("Cada motor produz o que se espera")

    from tfedit.formatadores import de_css, de_html, de_json, de_sql, de_xml

    opcoes = {"usa_espacos": True, "largura": 2, "comprimento_de_linha": 100}
    casos = [
        (de_json, '{"b":1,"a":[2]}', '"b": 1'),
        (de_xml, "<a><b>1</b></a>", "<b>1</b>"),
        (de_css, "a{color:red}", "color: red;"),
        (de_sql, "select a from t", "SELECT"),
    ]
    for modulo, entrada, esperado in casos:
        saida = modulo.FORMATADOR.formatar(entrada, opcoes)
        checa(getattr(saida, "texto", None) and esperado in saida.texto,
              f"{modulo.__name__.split('.')[-1]}: {esperado!r} aparece no "
              f"resultado")


# ======================================================================
# A aplicacao sobre a tabela de pecas
# ======================================================================

def testar_formatar_e_uma_operacao() -> None:
    secao("*** O documento inteiro formatado e' UM Ctrl+Z ***")

    with pasta_temporaria() as pasta:
        bruto = b'{"z":1,"a":[2,3],"m":{"k":true,"j":[4,5,6]}}\r\n'
        janela, _ = _janela_com(pasta, "d.json", bruto)
        try:
            aba = janela.aba_atual
            checa_igual(aba.nome_da_linguagem, "JSON", "reconheceu JSON")

            janela.formatar_documento()
            depois = _conteudo(aba)
            checa('"z": 1' in depois,
                  f"*** o documento foi formatado ***")
            checa_igual(aba.documento.total_de_edicoes, 1,
                        "*** e em UMA operacao: um Ctrl+Z devolve o arquivo "
                        "como estava, e nao um estado que nunca existiu ***")

            aba.documento.desfazer()
            checa_igual(
                aba.documento.ler(0, aba.documento.tamanho), bruto,
                "*** desfazer devolve os bytes originais, byte a byte ***")
        finally:
            _encerrar(janela)


def testar_reformatar_e_no_op() -> None:
    secao("*** Formatar o que ja' esta' formatado nao mexe em nada ***")

    with pasta_temporaria() as pasta:
        janela, alvo = _janela_com(pasta, "e.json", b'{"b":1,"a":[2,3]}\r\n')
        try:
            aba = janela.aba_atual
            janela.formatar_documento()
            checa_igual(aba.documento.total_de_edicoes, 1, "formatou uma vez")
            aba.salvar()
            gravado = alvo.read_bytes()
            # Gravar CONFIRMA as pecas: o documento passa a ser o arquivo que
            # esta' no disco, e a conta de edicoes pendentes volta a zero.
            checa_igual(aba.documento.total_de_edicoes, 0,
                        "gravar confirma as pecas e zera as pendencias")

            # A SEGUNDA vez. Sem o aparo por prefixo e sufixo comuns, ela
            # substituiria o arquivo inteiro por um conteudo identico:
            # sujaria a aba, gastaria uma operacao de desfazer e mexeria na
            # data do arquivo ao salvar.
            janela.formatar_documento()
            checa_igual(aba.documento.total_de_edicoes, 0,
                        "*** e a segunda vez NAO gerou operacao nenhuma ***")
            checa(not aba.modificado,
                  "*** a aba continua limpa ***")
            checa("já estava formatado" in janela.barra.currentMessage(),
                  f"e a mensagem diz por que: "
                  f"{janela.barra.currentMessage()!r}")
            checa_igual(aba.salvar(), 0,
                        "*** salvar continua no-op: a data do arquivo nao "
                        "muda ***")
            checa_igual(alvo.read_bytes(), gravado, "e o disco tambem nao")
        finally:
            _encerrar(janela)


def testar_sem_teto_formata_de_qualquer_tamanho() -> None:
    """O padrao passou a ser SEM TETO, a pedido do usuario.

    Antes, `seguranca.LIMITE_DE_ENTRADA_MB` era a constante 64 e nao havia
    como o usuario muda-la. Agora ela e' o padrao de uma chave de
    configuracao, e ZERO DESLIGA A CHECAGEM. O custo nao sumiu -- formatar
    constroi a arvore inteira na memoria --, o que mudou e' de quem e' a
    decisao.
    """
    secao("*** Sem teto (0), formatar nunca e' recusado por tamanho ***")

    from tfedit import configuracao, seguranca

    checa_igual(int(configuracao.padrao()["limite_formatar_mb"]), 0,
                "*** o padrao de fabrica e' SEM LIMITE ***")
    checa(seguranca.LIMITE_DE_ENTRADA_MB <= 0,
          f"e a constante do modulo tambem: "
          f"{seguranca.LIMITE_DE_ENTRADA_MB}")

    # A checagem de dentro tambem tem de estar desligada: `de_json` e `de_xml`
    # conferem o tamanho POR DENTRO, e se so' o menu tivesse sido liberado a
    # recusa viria depois do clique -- com o comando habilitado, que e' o pior
    # dos dois mundos.
    grande = "x" * (2 * 1024 * 1024)
    seguranca.conferir_tamanho(grande, 0)
    checa(True, "*** `conferir_tamanho` com 0 nao levanta em 2 MB ***")
    checa_levanta(seguranca.EntradaGrandeDemais,
                  lambda: seguranca.conferir_tamanho(grande, 1),
                  "e com 1 MB levanta: o mecanismo continua inteiro")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "f.json", b'{"a":1}\r\n')
        try:
            aba = janela.aba_atual
            checa(janela._por_que_nao_formata(aba) is None,
                  "e nenhum arquivo e' recusado por tamanho")
        finally:
            _encerrar(janela)


def testar_teto_explicito_desabilita_o_comando() -> None:
    """Quem QUISER o teto de volta poe um numero, e ele volta inteiro.

    Tirar o teto nao podia virar tirar o mecanismo: ele e' o que protege quem
    manda formatar um JSON de 3 GB numa maquina de 8 GB. O arquivo aqui passa
    de 1 MB DE VERDADE -- e' o caminho real, e nao um atalho por constante.
    """
    secao("*** Com um teto explicito, o comando vem desabilitado ***")

    with pasta_temporaria() as pasta:
        # Um JSON acima de 1 MB, e valido.
        itens = ",".join(f'"c{i}":{i}' for i in range(120_000))
        dados = ("{" + itens + "}").encode()
        checa(len(dados) > 1024 * 1024,
              f"o JSON de teste tem {len(dados) / (1024 * 1024):.1f} MB")

        janela, _ = _janela_com(pasta, "g.json", dados)
        try:
            aba = janela.aba_atual
            janela.cfg = {**janela.cfg, "limite_formatar_mb": 1}

            motivo = janela._por_que_nao_formata(aba)
            checa(motivo and "limite para formatar" in motivo,
                  f"*** acima do teto, o motivo e' explicito: {motivo!r} ***")
            checa(motivo and "Configurações" in motivo,
                  "*** e diz ONDE mudar: uma recusa sem saida e' parede ***")

            janela._ajustar_menu_formatar()
            acoes = [a for a in janela.menu_formatar.actions()
                     if not a.isSeparator()]
            checa(acoes and not any(a.isEnabled() for a in acoes),
                  "*** e as acoes do menu vem DESABILITADAS ***")
            checa(all(motivo in (a.toolTip() or "") for a in acoes),
                  "com o motivo na dica de cada uma")

            # E nao tenta mesmo se for chamado direto.
            janela.formatar_documento()
            checa(not aba.documento.alterado,
                  "*** chamado direto, tambem nao formata ***")

            # Zerado, volta a valer.
            janela.cfg = {**janela.cfg, "limite_formatar_mb": 0}
            janela._ajustar_menu_formatar()
            acoes = [a for a in janela.menu_formatar.actions()
                     if not a.isSeparator()]
            checa(all(a.isEnabled() for a in acoes),
                  "*** e com 0 volta a ficar habilitado ***")
        finally:
            _encerrar(janela)


def testar_o_limite_chega_ao_formatador() -> None:
    """O teto tem de ATRAVESSAR ate' o motor, e nao parar no menu.

    `de_json` e `de_xml` conferem o tamanho por dentro. Enquanto eles liam a
    constante do modulo, liberar so' o menu deixaria o comando habilitado e a
    recusa apareceria depois do clique. Este teste passa o limite pelas
    OPCOES, que e' o caminho que a janela usa.
    """
    secao("*** O limite atravessa das opcoes ate' o motor ***")

    from tfedit.formatadores import de_json, de_xml

    grande_json = "{" + ",".join(f'"c{i}":{i}' for i in range(120_000)) + "}"
    grande_xml = "<r>" + "".join(f"<i>{i}</i>" for i in range(120_000)) + "</r>"
    checa(len(grande_json) > 1024 * 1024, "o JSON de teste passa de 1 MB")
    checa(len(grande_xml) > 1024 * 1024, "e o XML tambem")

    for nome, motor, texto in (("de_json", de_json, grande_json),
                               ("de_xml", de_xml, grande_xml)):
        apertado = motor.FORMATADOR.formatar(texto, {"limite_mb": 1})
        checa(not apertado.ok,
              f"*** {nome}: com limite 1 MB nas opcoes, RECUSA ***")
        solto = motor.FORMATADOR.formatar(texto, {"limite_mb": 0})
        checa(solto.ok,
              f"*** {nome}: com 0 nas opcoes, formata os "
              f"{len(texto) / (1024 * 1024):.1f} MB ***")


def testar_sem_formatador_explica() -> None:
    secao("Uma linguagem sem formatador diz que nao tem")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "g.txt", b"texto corrido\r\n" * 20)
        try:
            aba = janela.aba_atual
            motivo = janela._por_que_nao_formata(aba)
            checa(motivo and "Não há formatador" in motivo,
                  f"*** explica em vez de sumir: {motivo!r} ***")
            checa("Linguagem" in motivo,
                  "e diz o que fazer: escolher outra linguagem")
        finally:
            _encerrar(janela)


def testar_erro_de_sintaxe_aponta_a_linha() -> None:
    secao("*** Erro de sintaxe diz onde ***")

    with pasta_temporaria() as pasta:
        # A vírgula sobrando na linha 3.
        bruto = b'{\r\n  "a": 1,\r\n  "b": 2,\r\n}\r\n'
        janela, _ = _janela_com(pasta, "ruim.json", bruto)
        try:
            aba = janela.aba_atual
            erro = aba.provedor.formatador().validar(_conteudo(aba))
            checa(erro is not None, "*** o JSON quebrado e' recusado ***")
            checa(erro.linha >= 3,
                  f"*** e o erro aponta a linha certa ({erro.linha}) ***")
            checa(erro.descrever(),
                  f"com um motivo legivel: {erro.descrever()!r}")

            # A apresentacao do erro e' uma caixa MODAL, e em modo offscreen
            # nao ha' quem a feche: a suite travaria para sempre. Trocada por
            # um gravador -- o que se quer verificar aqui e' que
            # `formatar_documento` CHEGA ao ramo de erro e nao altera nada, e
            # nao como a caixa e' desenhada.
            vistos = []
            janela._mostrar_erro_de_sintaxe = lambda _a, e: vistos.append(e)

            janela.formatar_documento()
            checa(vistos, "*** formatar um arquivo quebrado mostra o erro ***")
            checa(vistos and vistos[0].linha >= 3,
                  f"apontando a mesma linha ({vistos[0].linha if vistos else '?'})")
            checa(not aba.documento.alterado,
                  "*** e NAO altera nada ***")
            checa_igual(_conteudo(aba).encode("utf-8"), bruto,
                        "o conteudo continua exatamente como estava")
        finally:
            _encerrar(janela)


def testar_formatar_selecao() -> None:
    secao("Formatar so' a selecao")

    with pasta_temporaria() as pasta:
        janela, _ = _janela_com(pasta, "h.css",
                                b"a{color:red}\r\nb{margin:0}\r\n")
        try:
            aba = janela.aba_atual
            checa_igual(aba.nome_da_linguagem, "CSS", "reconheceu CSS")

            cursor = aba.editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.EndOfLine,
                                cursor.MoveMode.KeepAnchor)
            aba.editor.setTextCursor(cursor)
            checa(aba.editor.textCursor().hasSelection(), "ha' selecao")

            janela.formatar_selecao()
            aba.editor.sincronizar()
            texto = _conteudo(aba)
            checa("color: red;" in texto,
                  f"*** a primeira regra foi formatada ***")
            checa("b{margin:0}" in texto,
                  "*** e a segunda, fora da selecao, ficou intacta ***")
        finally:
            _encerrar(janela)


def testar_planilha_nao_formata() -> None:
    secao("Uma planilha nao e' codigo")

    try:
        import openpyxl
    except ImportError:
        checa(True, "openpyxl ausente: teste pulado")
        return

    with pasta_temporaria() as pasta:
        alvo = pasta / "p.xlsx"
        livro = openpyxl.Workbook()
        livro.active.append(["a", 1])
        livro.save(alvo)

        from tfedit.interface.janela_principal import JanelaPrincipal
        janela = JanelaPrincipal({})
        janela.abrir_arquivo(str(alvo))
        try:
            aba = janela.aba_atual
            motivo = janela._por_que_nao_formata(aba)
            checa(motivo and "planilha" in motivo.lower(),
                  f"*** explica em vez de levantar: {motivo!r} ***")
            janela.formatar_documento()
            checa(not aba.modificado,
                  "*** e chamado direto nao toca na planilha ***")
        finally:
            _encerrar(janela)


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_os_cinco_motores()
    testar_motores_formatam()
    testar_formatar_e_uma_operacao()
    testar_reformatar_e_no_op()
    testar_sem_teto_formata_de_qualquer_tamanho()
    testar_teto_explicito_desabilita_o_comando()
    testar_o_limite_chega_ao_formatador()
    testar_sem_formatador_explica()
    testar_erro_de_sintaxe_aponta_a_linha()
    testar_formatar_selecao()
    testar_planilha_nao_formata()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
