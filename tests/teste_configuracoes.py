"""A tela de Configurações, e a regra que ela existe para fazer valer.

    .\\.venv\\Scripts\\python.exe tests\\teste_configuracoes.py

NENHUMA OPÇÃO QUE NÃO FAZ NADA.

Antes desta tela existir havia os dois lados do defeito, e este arquivo guarda
os dois:

  * `tema` era LIDO com um padrão embutido e nunca declarado em `padrao()`.
    Como só o que está declarado vai parar no arquivo de configuração, não
    havia como o usuário mudá-lo -- a opção existia no código e não existia
    para quem usa;

  * `limite_de_substituicoes` era o inverso: declarado, editável, e ignorado
    pelo código, que usava uma constante. Uma opção que finge existir é pior
    que a ausência dela, porque tira da pessoa a chance de procurar outro
    caminho.

`testar_toda_chave_e_lida` e `testar_toda_chave_e_declarada` são as duas metades
dessa regra, e varrem o fonte -- não uma lista escrita à mão, que envelheceria.
"""

from __future__ import annotations

import pathlib
import re
import sys

from ajudantes import (checa, checa_igual, pasta_temporaria, preparar_qt,
                       pular, resumir, secao)

TEM_QT = preparar_qt()

RAIZ = pathlib.Path(__file__).resolve().parent.parent
LEITURA = re.compile(r"""cfg\.get\(\s*["']([a-z_]+)["']""")


def _chaves_lidas() -> dict[str, set[str]]:
    achadas: dict[str, set[str]] = {}
    for arquivo in list((RAIZ / "tfedit").rglob("*.py")) + [RAIZ / "app.py"]:
        for m in LEITURA.finditer(arquivo.read_text(encoding="utf-8")):
            achadas.setdefault(m.group(1), set()).add(arquivo.name)
    return achadas


# ======================================================================
# A regra
# ======================================================================

def testar_toda_chave_e_declarada() -> None:
    secao("*** Nenhuma chave lida sem estar declarada ***")

    from tfedit import configuracao

    declaradas = set(configuracao.padrao())
    lidas = _chaves_lidas()
    faltando = sorted(set(lidas) - declaradas)

    checa(len(lidas) > 10, f"a varredura de fato achou chaves ({len(lidas)})")
    checa(not faltando,
          "*** toda chave lida por `cfg.get` está declarada em `padrao()`: "
          "uma chave ausente nunca chega ao arquivo de configuração, e o "
          "usuário não tem como mudá-la ***"
          + "".join(f"\n         {k} (lida em {', '.join(sorted(lidas[k]))})"
                    for k in faltando))


def testar_toda_chave_e_lida() -> None:
    secao("*** Nenhuma opção que finge existir ***")

    from tfedit import configuracao

    lidas = set(_chaves_lidas())
    # `recentes` é escrita e lida por função própria, e não por `cfg.get`.
    conhecidas = lidas | {"recentes"}
    ignoradas = sorted(k for k in configuracao.padrao() if k not in conhecidas)

    checa(not ignoradas,
          "*** toda chave declarada é lida por alguém: uma opção editável que "
          "o código ignora é pior que a ausência dela ***"
          + "".join(f"\n         {k}" for k in ignoradas))


def testar_limite_de_substituicoes_e_obedecido() -> None:
    secao("*** O teto de substituições vem da CONFIGURAÇÃO ***")

    fonte = (RAIZ / "tfedit/interface/janela_principal.py").read_text(
        encoding="utf-8")
    # Era este o defeito: `busca.contar` recebia a constante do módulo, e a
    # chave da configuração ficava decorativa.
    checa('teto=TETO_DE_SUBSTITUICOES' not in fonte,
          "*** a busca NÃO recebe mais a constante direto ***")
    checa('self.cfg.get("limite_de_substituicoes"' in fonte,
          "*** e o teto sai da configuração, com a constante só de reserva ***")


# ======================================================================
# A tela
# ======================================================================

def testar_temas() -> None:
    secao("Os três temas, e o 'seguir o Windows'")

    from tfedit import tema
    from tfedit.interface.configuracoes import TEMAS, temas_validos

    disponiveis = tema.disponiveis()
    for nome in ("escuro", "claro", "azul"):
        checa(nome in disponiveis, f"o tema {nome} está disponível")
        carregado = tema.carregar(nome)
        checa_igual(carregado.nome.lower(), nome,
                    f"*** e `carregar({nome!r})` devolve ELE, e não o escuro "
                    f"por engano ***")
        checa(len(carregado.papeis) >= 30,
              f"com os {len(carregado.papeis)} papéis de realce")

    azul = tema.carregar("azul")
    escuro = tema.carregar("escuro")
    checa(azul.cor("editor.fundo") != escuro.cor("editor.fundo"),
          "*** o azul tem fundo próprio: derivar do escuro não pode virar "
          "uma cópia ***")
    checa_igual(azul.papeis, escuro.papeis,
                "*** e os papéis de realce são os MESMOS: eles já foram "
                "escolhidos para ter contraste em fundo escuro ***")

    oferecidos = [c for c, _ in TEMAS]
    checa_igual(oferecidos, ["sistema", "escuro", "claro", "azul"],
                "a tela oferece os quatro")
    checa_igual(temas_validos(), oferecidos,
                "*** e todos carregam de verdade ***")


def testar_dialogo_devolve_o_que_foi_escolhido() -> None:
    secao("A tela lê e devolve, sem gravar sozinha")

    from tfedit import configuracao
    from tfedit.interface.configuracoes import Configuracoes

    cfg = configuracao.padrao()
    dialogo = Configuracoes(cfg, None)

    dialogo.tema.setCurrentIndex(dialogo.tema.findData("azul"))
    dialogo.numero_de_linha.setCurrentIndex(
        dialogo.numero_de_linha.findData("atual"))
    dialogo.tamanho.setValue(14)
    dialogo.substituicoes.setValue(5000)

    novo = dialogo.valores()
    checa_igual(novo["tema"], "azul", "o tema escolhido volta")
    checa_igual(novo["numero_de_linha"], "atual", "e o número de linha")
    checa_igual(novo["fonte_tamanho"], 14, "e o tamanho da fonte")
    checa_igual(novo["limite_de_substituicoes"], 5000, "e o teto")
    checa_igual(cfg["tema"], "sistema",
                "*** e o dicionário ORIGINAL não foi tocado: Cancelar não "
                "pode deixar resíduo ***")


def testar_pasta_inexistente_vira_vazio() -> None:
    secao("*** Uma pasta padrão que não existe é recusada ***")

    from tfedit import configuracao
    from tfedit.interface.configuracoes import Configuracoes

    with pasta_temporaria() as pasta:
        dialogo = Configuracoes(configuracao.padrao(), None)
        dialogo.pasta.setText(str(pasta))
        checa_igual(dialogo.valores()["pasta_padrao"], str(pasta),
                    "uma pasta que existe é guardada")

        dialogo.pasta.setText(str(pasta / "nao" / "existe"))
        checa_igual(dialogo.valores()["pasta_padrao"], "",
                    "*** e uma que não existe vira vazio: guardá-la faria o "
                    "diálogo abrir num lugar qualquer, e a pessoa concluiria "
                    "que a opção não pegou ***")


# ======================================================================
# Valer AGORA
# ======================================================================

def _janela():
    from tfedit import configuracao
    from tfedit.interface.janela_principal import JanelaPrincipal

    janela = JanelaPrincipal(configuracao.padrao())
    janela.novo()
    return janela


def _encerrar(janela) -> None:
    for aba in janela.todas_as_abas():
        janela.abas.removeTab(janela.abas.indexOf(aba))
        aba.encerrar()
    janela.close()


def testar_tema_vale_na_hora() -> None:
    secao("*** Trocar o tema vale AGORA, e não no próximo arquivo ***")

    janela = _janela()
    try:
        aba = janela.aba_atual
        antes_janela = janela.tema.nome
        antes_editor = aba.editor.tema.cor("editor.fundo").name()

        anterior = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "tema": "azul"}
        janela.aplicar_configuracao(anterior)

        checa_igual(janela.tema.nome, "Azul", "a janela trocou de tema")
        checa(aba.editor.tema.cor("editor.fundo").name() != antes_editor,
              f"*** e o editor JÁ ABERTO trocou também "
              f"({antes_editor} -> {aba.editor.tema.cor('editor.fundo').name()}) "
              f"-- se só valesse para o próximo arquivo, a conclusão seria "
              f"que a opção não funciona ***")
        checa(janela.tema.nome != antes_janela, "e mudou de fato")
    finally:
        _encerrar(janela)


def testar_numero_de_linha_vale_na_hora() -> None:
    secao("*** Trocar o modo do número de linha vale AGORA ***")

    janela = _janela()
    try:
        aba = janela.aba_atual
        com = aba.editor.largura_da_margem()
        checa(com > 0, f"mostrando números, a margem tem {com} px")

        anterior = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "numero_de_linha": "nenhum"}
        janela.aplicar_configuracao(anterior)
        checa_igual(aba.editor.largura_da_margem(), 0,
                    "*** em 'nenhum', a margem tem largura ZERO: é assim que "
                    "ela some sem mexer no layout ***")

        anterior = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "numero_de_linha": "todas"}
        janela.aplicar_configuracao(anterior)
        checa_igual(aba.editor.largura_da_margem(), com, "e volta igual")
        checa_igual(aba.editor.modo_do_numero_de_linha(), "todas",
                    "o editor enxerga o modo escolhido")

        # Um valor estranho no arquivo de configuração não pode apagar a
        # margem: cai no padrão em vez de virar "nenhum" por acidente.
        anterior = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "numero_de_linha": "azul-claro"}
        janela.aplicar_configuracao(anterior)
        checa_igual(aba.editor.modo_do_numero_de_linha(), "todas",
                    "*** um valor desconhecido cai em 'todas', e não some "
                    "com a margem ***")
    finally:
        _encerrar(janela)


def _luz(cor) -> float:
    """Luminância aproximada, para medir contraste sem depender do olho."""
    return 0.299 * cor.red() + 0.587 * cor.green() + 0.114 * cor.blue()


def testar_margem_pinta_com_o_TEMA() -> None:
    """O defeito: a margem ignorava o tema e usava a `palette()` do Qt.

    MEDIDO no programa de verdade: a margem se pintava com
    `palette().alternateBase()` (#f7f7f7) e escrevia os números em
    `palette().mid()` (#b8b8b8) -- 63 de diferença de luminância. Só o número
    da linha do cursor saía em outra cor, e por isso era o único que se
    distinguia. Parecia um recurso ("mostra só a linha atual") e era uma cor
    errada: o tema sempre teve `editor.margem_texto` e
    `editor.margem_texto_atual`, sem ninguém usar.
    """
    secao("*** Os números aparecem: a margem pinta com o TEMA ***")

    from tfedit import tema as tema_mod

    fonte = (RAIZ / "tfedit/interface/editor.py").read_text(encoding="utf-8")
    inicio = fonte.index("def pintar_margem")
    fim = fonte.index("def cor_da_margem")
    checa("self.palette()" not in fonte[inicio:fim],
          "*** a pintura da margem NÃO chama mais `self.palette()`: as cores "
          "vêm do tema ***")
    checa("cor_da_margem" in fonte[inicio:fim],
          "*** e tira as cores do tema ***")

    for nome in ("escuro", "claro", "azul"):
        tema = tema_mod.carregar(nome)
        fundo = tema.cor("editor.margem_fundo")
        comum = tema.cor("editor.margem_texto")
        atual = tema.cor("editor.margem_texto_atual")
        checa(abs(_luz(fundo) - _luz(comum)) > 60,
              f"{nome}: os números comuns contrastam com a margem "
              f"({abs(_luz(fundo) - _luz(comum)):.0f} de luminância)")
        checa(abs(_luz(comum) - _luz(atual)) > 40,
              f"*** {nome}: e o número do cursor se distingue dos outros "
              f"({abs(_luz(comum) - _luz(atual)):.0f}) ***")

    janela = _janela()
    try:
        editor = janela.aba_atual.editor
        editor.resize(700, 300)
        editor.show()

        def tinta(modo: str) -> int:
            anterior = dict(janela.cfg)
            janela.cfg = {**janela.cfg, "numero_de_linha": modo}
            janela.aplicar_configuracao(anterior)
            if editor.largura_da_margem() == 0:
                return 0
            editor.margem.resize(editor.largura_da_margem(), 300)
            imagem = editor.margem.grab().toImage()
            fundo = editor.cor_da_margem("editor.margem_fundo").rgb()
            return sum(1 for y in range(imagem.height())
                       for x in range(imagem.width())
                       if imagem.pixelColor(x, y).rgb() != fundo)

        todas = tinta("todas")
        atual = tinta("atual")
        nenhum = tinta("nenhum")

        checa(todas > 500,
              f"*** em 'todas' há {todas} pixels desenhados na margem, com "
              f"as cores do tema ***")
        checa(atual < todas / 3,
              f"*** em 'atual' há bem menos ({atual}): só o número do "
              f"cursor ***")
        checa_igual(nenhum, 0, "e em 'nenhum' a margem não existe")
    finally:
        _encerrar(janela)


def testar_realce_da_linha_do_cursor() -> None:
    secao("*** Mostrando todas, a linha do cursor fica realçada ***")

    janela = _janela()
    try:
        aba = janela.aba_atual
        editor = aba.editor
        for _ in range(30):
            editor.insertPlainText("linha de conteúdo\n")
        editor.sincronizar()
        anterior = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "numero_de_linha": "todas"}
        janela.aplicar_configuracao(anterior)

        editor.resize(700, 300)
        editor.show()
        editor.margem.resize(editor.largura_da_margem(), 300)

        def cores_da_margem() -> set:
            imagem = editor.margem.grab().toImage()
            return {imagem.pixelColor(x, y).name()
                    for y in range(imagem.height())
                    for x in range(imagem.width())}

        cores = cores_da_margem()
        destaque = editor.cor_da_margem("editor.margem_texto_atual").name()
        comum = editor.cor_da_margem("editor.margem_texto").name()
        faixa = editor.cor_da_margem("editor.linha_atual").name()

        checa(comum in cores,
              f"*** os números comuns estão lá, em {comum} ***")
        checa(destaque in cores,
              f"*** e o da linha do cursor em outra cor, {destaque} ***")
        checa(faixa in cores,
              f"*** com uma faixa de fundo ({faixa}): a cor sozinha se perde "
              f"no meio dos outros números ***")
    finally:
        _encerrar(janela)


def testar_menu_tem_configuracoes() -> None:
    secao("O menu Arquivo tem Configurações")

    janela = _janela()
    try:
        arquivo = next((a.menu() for a in janela.menuBar().actions()
                        if "Arquivo" in a.text()), None)
        checa(arquivo is not None, "o menu Arquivo existe")
        if arquivo is None:
            return
        rotulos = [a.text() for a in arquivo.actions()]
        checa(any("Configura" in r for r in rotulos),
              f"*** e tem Configurações: {[r for r in rotulos if r]} ***")
    finally:
        _encerrar(janela)



# ======================================================================
# A barra de atalhos
# ======================================================================

def testar_icones_legiveis_a_16px() -> None:
    """A mesma licao que o icone do programa ensinou, agora na barra.

    Um simbolo com traco fino vira uma mancha cinza quando o Qt o reduz para os
    16 px de uma barra. A conta abaixo nao julga o desenho -- julga se sobrou
    massa suficiente para ele significar alguma coisa.
    """
    secao("*** Todo icone da barra sobrevive a 16 px ***")

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor
    from tfedit.interface import icones

    magros = []
    for chave in icones.CATALOGO:
        icone = icones.icone(chave, QColor("#d6d8dc"))
        checa(icone is not None and not icone.isNull(),
              f"{chave}: o ícone foi desenhado")
        if icone is None:
            continue
        imagem = icone.pixmap(QSize(16, 16)).toImage()
        opacos = sum(1 for y in range(imagem.height())
                     for x in range(imagem.width())
                     if imagem.pixelColor(x, y).alpha() > 40)
        if opacos < 20:
            magros.append(f"{chave} ({opacos} px)")

    checa(not magros,
          "*** nenhum ícone fica com menos de 20 px opacos a 16x16: abaixo "
          "disso o símbolo não diz mais nada ***"
          + "".join(f"\n         {m}" for m in magros))


def testar_icones_seguem_o_tema() -> None:
    secao("*** O ícone é desenhado na cor do tema ***")

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor
    from tfedit.interface import icones

    # Um PNG embutido teria UMA cor: escuro some no tema escuro, claro some no
    # claro. Desenhado, ele recebe a cor do texto da janela.
    claro = icones.icone("salvar", QColor("#ffffff")).pixmap(QSize(32, 32))
    escuro = icones.icone("salvar", QColor("#000000")).pixmap(QSize(32, 32))

    def media(mapa):
        img = mapa.toImage()
        pontos = [img.pixelColor(x, y) for y in range(img.height())
                  for x in range(img.width())
                  if img.pixelColor(x, y).alpha() > 128]
        return sum(c.red() for c in pontos) / max(1, len(pontos))

    checa(media(claro) > 200,
          f"*** pedido em branco, sai claro (média {media(claro):.0f}) ***")
    checa(media(escuro) < 60,
          f"*** pedido em preto, sai escuro (média {media(escuro):.0f}) ***")


def testar_barra_monta_da_configuracao() -> None:
    secao("*** A barra é a configuração, e na ordem dela ***")

    janela = _janela()
    try:
        barra = janela.barra_atalhos
        acoes = [a for a in barra.actions() if not a.isSeparator()]
        checa(len(acoes) >= 10, f"a barra tem {len(acoes)} botões")
        checa(all(not a.icon().isNull() for a in acoes),
              "todos com ícone")
        checa(all(a.toolTip() for a in acoes),
              "*** e todos com dica: um ícone sem dica é um enigma ***")
        checa(any(a.isSeparator() for a in barra.actions()),
              "*** com separadores entre os grupos: treze botões seguidos "
              "viram uma fileira indistinta ***")

        # A ORDEM é a da configuração, e não a de um catálogo interno.
        antes = dict(janela.cfg)
        janela.cfg = {**janela.cfg,
                      "botoes_da_barra": ["salvar", "novo", "formatar"]}
        janela.aplicar_configuracao(antes)
        acoes = [a.text() for a in janela.barra_atalhos.actions()
                 if not a.isSeparator()]
        checa_igual(acoes, ["Salvar", "Novo", "Formatar documento"],
                    "*** a barra respeita a ordem salva, inclusive fora da "
                    "ordem do catálogo ***")
    finally:
        _encerrar(janela)


def testar_barra_pode_sumir() -> None:
    secao("A barra pode ser escondida")

    janela = _janela()
    try:
        antes = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "mostrar_barra": False}
        janela.aplicar_configuracao(antes)
        checa(janela.barra_atalhos.isHidden(), "escondida quando desmarcada")

        antes = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "mostrar_barra": True}
        janela.aplicar_configuracao(antes)
        checa(not janela.barra_atalhos.isHidden(), "e volta quando marcada")

        # Marcada mas sem botão nenhum: some também, senão fica uma faixa
        # cinza ocupando espaço sem oferecer nada.
        antes = dict(janela.cfg)
        janela.cfg = {**janela.cfg, "botoes_da_barra": []}
        janela.aplicar_configuracao(antes)
        checa(janela.barra_atalhos.isHidden(),
              "*** sem botão nenhum ela some, em vez de virar uma faixa "
              "vazia ***")
    finally:
        _encerrar(janela)


def testar_chave_desconhecida_nao_derruba() -> None:
    secao("*** Um botão que não existe é ignorado, e não quebra ***")

    janela = _janela()
    try:
        # Uma configuração gravada por uma versão MAIS NOVA chega assim. Ela
        # não pode impedir esta versão de abrir.
        antes = dict(janela.cfg)
        janela.cfg = {**janela.cfg,
                      "botoes_da_barra": ["novo", "teletransporte", "salvar"]}
        janela.aplicar_configuracao(antes)
        acoes = [a.text() for a in janela.barra_atalhos.actions()
                 if not a.isSeparator()]
        checa_igual(acoes, ["Novo", "Salvar"],
                    "*** a chave desconhecida sai e o resto continua ***")
    finally:
        _encerrar(janela)


def testar_botoes_oferecidos_tem_tudo() -> None:
    secao("A tela de Configurações lista o que a barra sabe fazer")

    from tfedit.interface import icones

    janela = _janela()
    try:
        oferecidos = dict(janela.botoes_da_barra())
        checa(len(oferecidos) >= 12,
              f"{len(oferecidos)} botões oferecidos")
        for chave in oferecidos:
            checa(chave in icones.CATALOGO,
                  f"{chave} tem ícone no catálogo")

        # A regra, dos dois lados. Na v0.12.0 `comparar` tinha ícone e NÃO
        # era oferecido, porque o comando ainda não existia -- um botão que
        # abre "não implementado" é a opção que finge existir. Na v0.13.0 o
        # comando chegou, e ele passou a ser oferecido.
        #
        # O que este teste guarda não é o caso de `comparar`, e sim a regra:
        # ícone e comando andam juntos, nos dois sentidos.
        sem_comando = [c for c in icones.CATALOGO if c in oferecidos
                       and c not in janela._comandos_da_barra()]
        checa(not sem_comando,
              f"*** nada é oferecido sem ter comando: {sem_comando} ***")
        sem_icone = [c for c in janela._comandos_da_barra()
                     if c not in icones.CATALOGO]
        checa(not sem_icone,
              f"*** e nenhum comando fica sem ícone: {sem_icone} ***")

        # E o padrão de fábrica só cita botões que existem.
        from tfedit import configuracao
        padrao = configuracao.padrao()["botoes_da_barra"]
        desconhecidos = [c for c in padrao if c not in oferecidos]
        checa(not desconhecidos,
              f"*** e o padrão de fábrica só cita botões reais: "
              f"{desconhecidos or 'nenhum sobrando'} ***")
    finally:
        _encerrar(janela)


def main() -> int:
    if not TEM_QT:
        return pular("PySide6 nao esta' instalado")

    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])

    testar_toda_chave_e_declarada()
    testar_toda_chave_e_lida()
    testar_limite_de_substituicoes_e_obedecido()
    testar_temas()
    testar_dialogo_devolve_o_que_foi_escolhido()
    testar_pasta_inexistente_vira_vazio()
    testar_tema_vale_na_hora()
    testar_numero_de_linha_vale_na_hora()
    testar_margem_pinta_com_o_TEMA()
    testar_realce_da_linha_do_cursor()
    testar_menu_tem_configuracoes()
    testar_icones_legiveis_a_16px()
    testar_icones_seguem_o_tema()
    testar_barra_monta_da_configuracao()
    testar_barra_pode_sumir()
    testar_chave_desconhecida_nao_derruba()
    testar_botoes_oferecidos_tem_tudo()
    return resumir()


if __name__ == "__main__":
    sys.exit(main())
