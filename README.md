# TextForgeEdit

Editor de texto **completo** para arquivos grandes: cursor de caractere,
digitação livre, seleção atravessando linhas — num arquivo de 1 GB que **continua
no disco**.

## Por que existe

O [TextForge](https://github.com/RicardoBiazin/TextForge) abre 240 MB
instantaneamente e, desde a v0.3.0, edita **linha a linha**: `F2` abre um campo
sobre a linha, `Enter` confirma. Isso resolve corrigir um valor num export de
ERP. Não resolve escrever.

Este projeto é o outro lado da mesma moeda. Mesma economia de memória, sem o modo
de edição por linha.

## A ideia central

É a única coisa que precisa ser entendida antes de mexer em qualquer arquivo
daqui:

> O documento **não é texto na memória**. É uma lista de faixas — umas apontando
> para o arquivo no disco, outras para o que você digitou.

```
peças = [ (ORIGINAL,   0, 4.812.003 bytes, 120.301 linhas),   ← nunca foi lido
          (ADICIONADO, 0,        27 bytes,       0 linhas),   ← o que você digitou
          (ORIGINAL, 4.812.050, 8.400.112 bytes, 210.884 linhas) ]
```

O documento acima tem 13 MB e o que está na RAM são 27 bytes. É a estrutura
clássica de editor (*piece table*), escolhida por três propriedades:

1. **A memória acompanha as edições, não o arquivo.** Digitar num arquivo de 1 GB
   custa o tamanho do que foi digitado.
2. **Desfazer sai de graça.** O texto original nunca é destruído — desfazer é
   voltar a apontar para ele.
3. **Gravar é copiar bytes.** Uma peça intocada vai do arquivo velho para o novo
   sem nunca virar `str`.

A diferença para o TextForge é a **granularidade**: lá a unidade é a linha, aqui é
o byte — e é isso que permite o cursor andar caractere a caractere.

## Estado

Já dá para abrir, digitar e salvar:

```bat
.venv\Scripts\python.exe app.py caminho\do\arquivo.txt
```

| Parte | Situação |
|---|---|
| `tfedit/original.py` — mmap + índice esparso incremental | pronto |
| `tfedit/pecas.py` — tabela de peças, desfazer, fusão de digitação | pronto |
| `tfedit/gravacao.py` — gravação por streaming, troca atômica | pronto |
| `tfedit/codificacao.py` — cascata de detecção, fim de linha | pronto |
| `tfedit/janela.py` — a janela viva e a escrita de volta mínima | pronto |
| `tfedit/busca.py` — localizar e substituir no documento inteiro | pronto |
| `tfedit/log_interno.py` — log e captura de erro não tratado | pronto |
| `tfedit/interface/` — abas, editor deslizante, barra de busca | pronto |
| Empacotamento (`build.bat`, `.spec`, ZIP) | pronto |
| Sessão restaurada, realce de sintaxe, instância única | não começou |

**Medido**, arquivo de 18 MB com 400 mil linhas: digitar duas frases (uma no
começo, outra na linha 300.000, com deslize entre elas) deixa **42 bytes** na
memória. O `QPlainTextEdit` segura 5.001 blocos — a fatia —, e não as 400.001
linhas. Gravar preserva o CRLF das 400.000 linhas e deixa intactas as que não
foram tocadas.

## A janela viva

O editor é um `QPlainTextEdit` **de verdade** segurando apenas uma fatia:

```
arquivo de 1 GB
 │
 ├─ linhas 0 .. 1.199.999          na tabela de peças, no disco
 ├─ linhas 1.200.000 .. 1.205.000  ← JANELA VIVA, num QTextDocument real
 └─ linhas 1.205.001 .. fim        na tabela de peças, no disco
```

Rolar para fora faz a fatia **deslizar**: o que estava vivo volta para a tabela
de peças e uma fatia nova é carregada. Dentro dela funciona tudo o que o Qt sabe
fazer — caret, acentuação com tecla morta, seleção, clipboard, arrastar.

A escrita de volta é **mínima**: o prefixo e o sufixo iguais são descartados, e
só o miolo que mudou entra na tabela. Sem isso, cada deslize com uma vírgula
corrigida injetaria a fatia inteira — centenas de KB para representar um byte.

## Desfazer, em dois níveis

`Ctrl+Z` consulta **duas** pilhas, nesta ordem:

1. a do Qt, que cobre o que você digitou na fatia agora;
2. a da tabela de peças, que cobre o que já foi consolidado — inclusive
   `Substituir todas`.

Uma substituição em massa cabe num **único** `Ctrl+Z`: as trocas entram como um
grupo, e desfazer processa o grupo inteiro. Sem isso, voltar atrás de 500
substituições exigiria 500 `Ctrl+Z`, o que na prática é não poder voltar.

O `Ctrl+Z` é interceptado no `keyPressEvent` do editor, e não deixado a cargo do
atalho do menu: o `QPlainTextEdit` fica com essa tecla antes do menu e desfaria
na própria pilha — vazia depois de todo deslize.

**Limitação que resta:** ao deslizar a fatia, o que foi editado é consolidado na
tabela e a pilha do Qt recomeça. O desfazer continua funcionando (pela tabela),
mas a granularidade fica mais grossa — um `Ctrl+Z` desfaz a consolidação inteira
daquele trecho, e não a última tecla.

## O que já dá para fazer

| | |
|---|---|
| **Abas** | uma por arquivo — reabrir o mesmo caminho foca a aba existente, inclusive com caixa diferente |
| **Salvar / Salvar como / Salvar tudo** | `Ctrl+S`, `Ctrl+Shift+S` |
| **Localizar e substituir** | `Ctrl+F`, `F3`, `Shift+F3` — com maiúsculas, palavra inteira e regex |
| **Arrastar-e-soltar** | solte arquivos na janela |
| **Ir para linha** | `Ctrl+G` |

A busca varre o **documento inteiro**, e não a fatia carregada. Achar na linha
150.000 desliza a janela até lá. Ela também enxerga o que você digitou e ainda
não gravou — e **não** encontra o que você apagou, embora ainda esteja no
arquivo.

`Substituir todas` aplica de trás para a frente: do começo, cada troca deslocaria
o que vem depois e a segunda cairia no lugar errado. Tem teto de 100.000 por
passada, avisado antes.

## Diagnóstico

O log fica em `%APPDATA%\TextForgeEdit\textforgeedit.log`, com rotação em 2 MB.
Toda exceção não tratada vai para lá **e** para `erro.log`, com o traceback
inteiro.

Isso existe por uma falha concreta: numa sessão de teste o executável sumiu
depois de gravar um arquivo de 176 MB e não havia nada para consultar. Três
tentativas de reproduzir falharam, e o defeito segue sem causa conhecida — mas na
próxima vez haverá rastro.

## Decisões já tomadas, e o porquê

**Tudo é em bytes, não em caracteres.** Saber que a posição 4.000.000 é o
caractere 3.812.577 exigiria decodificar tudo antes dela — ou seja, carregar o
arquivo. A decodificação acontece **linha a linha**, na hora de desenhar, e uma
linha é curta.

**Editar exige o índice completo.** Partir uma peça precisa saber quantas linhas
ficam de cada lado. Enquanto a varredura corre, o arquivo é navegável e a
contagem de linhas cresce na tela — mas não se edita.

**Digitação seguida vira uma peça só.** Sem esse caminho rápido, digitar um
parágrafo criaria centenas de peças. E as teclas seguidas viram **uma** operação
de desfazer: `Ctrl+Z` desfaz a frase, não a letra.

**A ordem da gravação no Windows não é negociável:** escrever o temporário com o
mmap aberto → fechar o mmap → trocar → reabrir. Fechar antes grava arquivo vazio;
deixar aberto faz a troca falhar com acesso negado.

## Rodar os testes

```bat
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe tests\rodar_todos.py
```

## Gerar o executável

```bat
build.bat              :: dist\TextForgeEdit\    (one-dir, recomendado)
build.bat umarquivo    :: dist\TextForgeEdit.exe (portátil)
```

O `build.bat` roda a suíte **antes** de empacotar e uma prova de vida do `.exe`
**depois**: ela cria um arquivo, edita, grava, confere byte a byte e ainda testa
a busca. Excludes agressivos quebram o programa só em tempo de execução — sem
essa prova, isso chegaria como relatório de bug do usuário.

Sem pytest, de propósito — cada suíte roda num processo separado, então um
travamento de Qt numa não leva as outras.

## Licença

MIT. Autor: Ricardo Biazin.
