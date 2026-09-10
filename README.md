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
| `tfedit/configuracao.py` — preferências, recentes, limites | pronto |
| `tfedit/cli.py` — `--linha`, vários arquivos, recusa de dispositivos | pronto |
| `tfedit/sessao.py` — sessão pelo diário de edições | pronto |
| `tfedit/instancia_unica.py` — uma janela só, "Abrir com" | pronto |
| `tfedit/realce/` + `tfedit/linguagens/` — realce, 24 linguagens | pronto |
| `tfedit/tema.py` — temas claro/escuro, temas do usuário | pronto |
| `tfedit/conversao.py` — reinterpretar e converter a codificação | pronto |
| `tfedit/interface/visualizadores/` — views: hexadecimal e grade CSV | pronto |
| `tfedit/csv_dialeto.py` — detecção de separador, aspas e cabeçalho | pronto |
| `tfedit/planilha/` — .xlsx: leitura e gravação por patch no ZIP | pronto |
| `tfedit/formatadores/` — JSON, XML, CSS, HTML e SQL | pronto |

**Medido**, arquivo de 18 MB com 400 mil linhas: digitar duas frases (uma no
começo, outra na linha 300.000, com deslize entre elas) deixa **42 bytes** na
memória. O `QPlainTextEdit` segura 5.001 blocos — a fatia —, e não as 400.001
linhas. Gravar preserva o CRLF das 400.000 linhas e deixa intactas as que não
foram tocadas.

## Visualizar em hexadecimal

Menu **Visualizar** (ou o campo do rodapé) troca entre `Texto` e `Hexadecimal`
sem reabrir nada: as duas são views do **mesmo** documento, e o mmap, o índice e
a tabela de peças são os mesmos.

```
00000000  48 65 6c 6c 6f 2c 20 6d  75 6e 64 6f 21 0d 0a 41  |Hello, mundo!..A|
```

**Funciona em 1 GB porque desenha sozinho.** Um `QTableView` com modelo virtual
quebraria em dois pontos: a barra de rolagem em pixels estoura o inteiro de 32
bits um pouco acima de 4 GB de arquivo, e o modelo seria consultado 17 vezes por
linha visível (uma por célula e por papel). Aqui a rolagem é em unidade de
**linha** — o mesmo inteiro aguenta 32 GB — e cada linha são três `drawText`.

**Uma leitura por repintura.** O `paintEvent` pede ao documento um bloco com
tudo o que a tela mostra. Medido no teste: **752 bytes** para desenhar uma tela
de um arquivo de 2 MB. O custo por quadro não depende do tamanho do arquivo.

Ele lê o **documento**, não o disco: o que você digitou no modo texto e ainda
não gravou aparece no dump. `Ctrl+G` vira "ir para deslocamento" e aceita `1024`
ou `0x400`. Copiar tem teto de 1 MB — a área de transferência guarda o texto
inteiro na memória.

## Grade de CSV que não carrega o CSV

A grade do TextForge não serve aqui, e não é questão de ajuste: ela fatia o
texto inteiro em uma `str` por registro. Para 240 MB isso são vários GB.

Aqui **o modelo não tem os dados**. `rowCount` é o total de linhas do índice, e
cada célula é lida na hora por `Documento.faixa()`, em blocos de 256 linhas.
Medido no teste: abrir um CSV de **200 mil linhas lê 456 delas**.

**Editar uma célula troca só os bytes daquele campo.** Reconstruir o registro
inteiro — o caminho do irmão — reescreveria todos os campos com o *quoting*
mínimo do módulo `csv`, tirando aspas legítimas de campos que ninguém tocou. E
o fim de linha vem da **própria linha**, não do perfil do arquivo: em arquivo
com CRLF e LF misturados, usar o majoritário trocaria bytes que ninguém mandou
trocar. Cada célula editada é **uma** operação de desfazer.

**A detecção do separador é pela consistência, não pela frequência** — e ganhou
um critério a mais que o irmão não tem. Num export brasileiro:

```
produto;preco;desconto          <- o cabeçalho tem ';' e nenhuma vírgula
Parafuso 3,5mm 0;0,50;0,00      <- nos dados, ambos são uniformes
```

Vírgula e ponto e vírgula são os dois 100% consistentes, e a vírgula tem
contagem *maior*. O que decide é a **presença**: um separador de verdade está em
todas as linhas, inclusive no cabeçalho.

**O que a grade não faz, e diz que não faz.** Um campo entre aspas pode conter
quebra de linha; descobrir isso exigiria varrer do byte 0. Então aqui uma linha
é um registro — e as linhas com aspas sem fechar aparecem marcadas e **não são
editáveis**, com a explicação na dica. Não se corrompe o que não se consegue
analisar. O cabeçalho também não ordena: um clique acionaria a leitura do
arquivo inteiro.

## Planilhas .xlsx

Um `.xlsx` **não é texto** — é um ZIP de XML. Não tem linha, nem fim de linha,
nem codificação, e indexar 100 MB de ZIP contando `
` produziria um número sem
sentido. Por isso uma aba de planilha **não cria** mmap, índice nem tabela de
peças: `editor`, `documento` e `original` ficam `None`, e a única visualização é
a grade.

O princípio que se mantém é o mesmo, um formato acima: **o que ninguém tocou sai
como entrou**. Abrir e salvar sem editar devolve o arquivo byte a byte — o
pacote original nem é recomprimido. Editar uma célula vira um *patch* nos bytes
daquela célula, dentro do ZIP remontado na ordem original.

Isso não é preciosismo. Uma planilha regravada do zero perde formatação,
gráficos e tabelas dinâmicas — e o Excel costuma abrir assim mesmo, sem avisar
que o arquivo empobreceu. O teste verifica que o formato de moeda da coluna
sobrevive à edição de uma célula vizinha.

**O teto de tamanho é consequência, não descuido.** Como a pasta inteira vai
para a memória, o tamanho é conferido por `stat` **antes** de ler um byte. Acima
de 100 MB o arquivo abre como arquivo comum, onde as garantias de memória do
editor voltam a valer. Um `.zip` renomeado para `.xlsx` também é recusado — a
detecção olha o conteúdo.

## Comparar arquivos

`Ferramentas → Comparar arquivos` (`Ctrl+D`): dois painéis alinhados, com `F7` e
`Shift+F7` pulando de diferença em diferença. Verde o que só existe à direita,
vermelho o que só existe à esquerda, âmbar o que mudou.

**O `difflib` sozinho não serve, e isso foi medido.** Dois arquivos de 200 mil
linhas com uma mudança a cada dez — duas versões de um export, 10% das linhas
alteradas — passavam de **dois minutos**:

| linhas | tempo | |
|---|---|---|
| 5 mil | 0,24 s | |
| 10 mil | 0,96 s | 4× |
| 20 mil | 4,63 s | 4,8× |
| 40 mil | 27,94 s | 6× |

Dobrar o tamanho quintuplicava o tempo. Não era um teto que resolvia: seria
preciso recusar qualquer arquivo acima de umas 20 mil linhas.

A saída foi **ancorar nas linhas únicas**, como o diff de paciência do git: uma
linha que aparece exatamente uma vez nos dois arquivos só pode corresponder a si
mesma. As âncoras cortam o problema em pedaços pequenos, e o `difflib` só roda
dentro de cada pedaço. **O mesmo caso passou a 0,37 s.**

Três decisões de memória, todas medidas:

- **compara-se o hash da linha**, não a linha — 8 bytes contra a linha inteira;
- **o resultado são os blocos**, não as linhas alinhadas. Dois arquivos iguais
  de 1 GB produzem **um** bloco, e a linha exibida N é resolvida por busca
  binária. Medido: 200 mil linhas com 20 mil diferenças custam 32 MB;
- **a pintura lê uma tela por vez** — medido: 5 linhas por painel.

CRLF contra LF **não** é diferença: quem quer ver o terminador usa o
hexadecimal.

## Barra de atalhos

Doze botões em quatro grupos — arquivo, edição, busca, visualização —, e a lista
de quais aparecem fica em `Configurações → Barra de atalhos`. A **ordem salva** é
a da barra, e marcar ou desmarcar vale na hora.

**Os ícones são desenhados em código, não arquivos de imagem.** Três motivos, e o
terceiro decide:

- o Qt quase não tem ícone padrão útil para um editor — não há tesoura, lupa nem
  seta de desfazer em `QStyle.StandardPixmap`, e metade da barra ficaria sem
  símbolo;
- um PNG tem **uma** resolução: numa tela 4K a 150% ele borra, e seriam três
  tamanhos de treze ícones para versionar;
- **eles seguem o tema.** Um ícone escuro gravado em arquivo desaparece no tema
  escuro; um claro desaparece no claro. Desenhados, recebem a cor do texto da
  janela e funcionam nos três temas sem nenhum arquivo a mais.

O teste mede cada ícone reduzido a 16 px e reprova o que ficar com menos de 20
pixels opacos — é a mesma lição que o ícone do programa ensinou: abaixo disso o
símbolo não diz mais nada.

Uma chave desconhecida na configuração é **ignorada em silêncio**: um arquivo
gravado por uma versão mais nova não pode impedir esta de abrir.

## Números de linha

`Configurações → Editor → Número de linha`, com três estados:

| | |
|---|---|
| **Todas** | todos os números, com a linha do cursor realçada (padrão) |
| **Somente a linha do cursor** | visual limpo |
| **Nenhum** | a margem some, com largura zero |

A margem pintava com a `palette()` do Qt em vez do tema. Medido: fundo
`#f7f7f7` com números `#b8b8b8` — **63 de diferença de luminância**, contra 83
das cores do tema. E a `palette()` de um widget não acompanha o tema do editor,
então a margem ficava presa nas cores padrão do Qt em qualquer tema. Só o número
da **linha do cursor** usava outra cor, e por isso era o único que se
distinguia — parecia um recurso e era uma cor errada. O tema sempre teve
`editor.margem_texto` e `editor.margem_texto_atual`, sem ninguém usar.

## Configurações

`Arquivo → Configurações` (`Ctrl+,`): tema (escuro, claro, **azul** ou seguir o
Windows), pasta padrão dos diálogos, número de linha, fonte, e os limites de
leitura.

**Duas regras, e as duas estão travadas por teste** que varre o fonte — não uma
lista à mão, que envelheceria:

- **Nenhuma chave lida sem estar declarada.** `tema` era lido com um padrão
  embutido e nunca declarado; como só o declarado chega ao arquivo de
  configuração, **não havia como mudar o tema**. Eram cinco chaves nessa
  situação.
- **Nenhuma opção que finge existir.** `limite_de_substituicoes` era o inverso:
  declarado, editável, e ignorado — o código usava uma constante. Uma opção que
  não faz nada é pior que a ausência dela, porque tira a chance de a pessoa
  procurar outro caminho.

**O que dá para aplicar na hora, aplica na hora.** Tema, número de linha, fonte
e quebra de linha valem nos arquivos **já abertos** ao fechar a janela — se só
valessem no próximo arquivo, a conclusão natural seria que a opção não funciona.
Os limites de leitura já foram usados na abertura, e a própria tela avisa isso.

O tema **azul** é derivado do escuro, e não escrito do zero: só as superfícies
mudam de matiz. Os 40 papéis de realce passam intactos — eles já foram
escolhidos para ter contraste em fundo escuro, e um tema digitado à mão
esqueceria alguns (e `tema.cor` só avisa no log, então o esquecimento viraria um
realce monocromático sem erro visível).

## Abrir já com um documento pronto

O programa nunca abre numa janela vazia: sem arquivo na linha de comando e sem
sessão a restaurar, ele cria um **Sem título 1** pronto para digitar. `Ctrl+N`
cria outro a qualquer momento.

**O documento novo é um arquivo de verdade**, vazio, numa pasta interna
(`%APPDATA%\TextForgeEdit
ascunhos`). Não é detalhe de implementação — é o que
faz ele passar exatamente pelo mesmo código de um arquivo de 1 GB: mesma tabela
de peças, mesmo desfazer, mesma gravação por streaming. Um caminho paralelo "sem
arquivo" seria uma segunda implementação de tudo isso, e as duas divergiriam na
primeira correção feita só numa delas.

Três consequências, e as três estão travadas por teste:

- **`Ctrl+S` pergunta onde salvar.** Gravar no arquivo de trabalho esconderia o
  texto numa pasta interna, e você nunca mais o encontraria.
- **O arquivo de trabalho some** quando a aba fecha — depois de soltar o mmap,
  que no Windows segura o arquivo. E o que sobrou de um fechamento anormal é
  varrido no arranque, só o que tem mais de sete dias: um rascunho recente pode
  ser de outra janela aberta agora.
- **Abrir um arquivo fecha o "Sem título" vazio**, senão o editor acumularia uma
  aba em branco por sessão. Só o intocado sai — um rascunho em que você digitou
  é trabalho.

## Ícones

Dois, e não um — são coisas diferentes, e o Explorer as mostra em lugares
diferentes:

```
icone.ico            o APLICATIVO      quadrado cheio, na barra de tarefas
icone_arquivo.ico    o TIPO DE ARQUIVO página com canto dobrado, no Explorer
```

Com um ícone só, um `.txt` associado fica com cara de **programa** na pasta, e
não dá para saber olhando se aquilo é o editor ou um arquivo dele.

Mesma família visual do TextForge — fundo ardósia, barras de texto — com o vinco
lateral em **azul** no lugar do laranja-brasa.

**Tudo é grosso, e isso não é escolha estética.** A primeira versão tinha um
vinco de 1 px e três linhas de 1 px sobre um fundo quase preto: no papel parecia
elegante, na barra de tarefas virou um borrão. Duas lições ficaram, e os testes
guardam as duas:

- a 16 px, uma forma de 1 px com 1 px de folga **some**. O vinco ocupa 4 px, as
  barras 3, e são **duas** barras de texto em vez de três;
- um retângulo `#1E1F22` numa barra de tarefas escura tem quase a cor da barra.
  O que separa o ícone do fundo é o **vinco azul** — por isso ele é largo.

A página do ícone de arquivo é clara pelo motivo espelhado: ela vive no Explorer,
onde o fundo é branco, e por isso ganha **borda** — sem ela a silhueta de
documento desaparece.

`ferramentas/gerar_icone.py` regera os dois **sem Pillow**: os `.ico` são
versionados justamente para o build funcionar numa máquina que não o tenha, e um
gerador que exigisse Pillow anularia isso.

## Associar às extensões do Windows

```powershell
.ssociar.ps1 .txt .csv .log .dat
```

Escreve **apenas em HKCU** — sem administrador, nada fora do seu perfil. Usa
`OpenWithProgids`, que **acrescenta** o TextForgeEdit à lista "Abrir com" sem
roubar o programa padrão de ninguém. Para trocar de editor em vez de acumular
os dois, `-TirarDaLista TextForge.exe`. Para desfazer, `-Remover`.

**O programa padrão não sai daqui, e não é limitação do script.** Desde o
Windows 10 o `UserChoice` de cada extensão é protegido por um hash amarrado ao
seu usuário, à extensão e ao horário: escrever ali direto é revertido pelo
sistema. Para tornar o TextForgeEdit padrão, é uma vez por extensão em
*Abrir com → Escolher outro aplicativo → Sempre*.

Duas armadilhas do PowerShell estão travadas por teste, porque as duas quebram
o script **em silêncio**:

- Um parâmetro com `ValueFromRemainingArguments` fica **fora** da ligação
  posicional. Sem `PositionalBinding = $false`, `.ssociar.ps1 .txt` entende
  `.txt` como o *caminho do executável* — e o script responde "não encontrei o
  .exe" sem dar pista do porquê.
- O menu de contexto mora numa chave chamada `*`, e o provedor de registro do
  PowerShell trata isso como **curinga**: sem `-LiteralPath` ele varre as
  milhares de chaves de `Software\Classes` e o script parece travado.

## Formatar código

Menu **Formatar**: documento (`Shift+Alt+F`), seleção, compactar e validar
sintaxe. Cinco motores — JSON, XML, CSS, HTML e SQL.

**O Python ficou de fora de propósito.** O motor dele é o `black`, que arrasta
`click`, `pathspec` e `platformdirs`, e um arquivo-fonte Python não é o motivo
deste editor existir. Não é esquecimento; está registrado no código.

**Como o resultado chega ao arquivo.** Os formatadores recebem `str` e devolvem
`str` — não existe versão em streaming disso, e nem daria: indentar exige
conhecer a estrutura inteira. E o editor só tem a fatia. Então o resultado não
passa pelo editor: vai direto à tabela de peças, **aparado** por
`_prefixo_comum`/`_sufixo_comum` — os mesmos da janela viva.

O aparo dá de graça uma propriedade valiosa: **reformatar um arquivo já
formatado é no-op**. Não mexe na tabela, não suja a aba, não muda a data do
arquivo ao salvar. E o documento inteiro formatado é **um único** passo de
desfazer.

**Acima de 64 MB o comando vem desabilitado com o motivo na dica** — formatar é
a única operação daqui que precisa do arquivo inteiro na memória, e esse é o
limite honesto da técnica. Formatar **seleção** não tem teto: a seleção está na
fatia.

## O rodapé é interativo

A linguagem e a codificação aparecem no rodapé, e **clicar em qualquer um dos
dois abre o menu para trocar** — é onde a pessoa já está olhando para saber o
que o arquivo é. Obrigá-la a subir até a barra de menus para mudar o que está
lendo ali é atravessar a janela por uma informação que estava debaixo do cursor.

Os dois campos têm cursor de mãozinha e dica: um rótulo de barra de status
normalmente não faz nada ao ser clicado, então sem essa pista ninguém tentaria.

## Codificação: dois verbos diferentes

O menu **Codificação** tem duas coisas que costumam ser confundidas, e a
confusão é o defeito clássico aqui:

| | O que faz | O arquivo no disco |
|---|---|---|
| **Reinterpretar como** | lê os mesmos bytes de outro jeito | **não muda** |
| **Converter para** | reescreve o arquivo na codificação escolhida | **todo byte muda** |

"Abri e veio tudo com acento quebrado" é caso de *reinterpretar*: o arquivo
estava certo, a leitura é que errou. "Preciso mandar este export do ERP em
UTF-8" é caso de *converter*.

**Converter é caro aqui, por construção.** A gravação normal copia os trechos
intactos byte a byte, direto do mmap — é o que faz salvar 240 MB com três
parágrafos alterados custar segundos. Não existe conversão que preserve os
bytes: `á` em ISO-8859-1 é um byte e em UTF-8 são dois. O arquivo inteiro passa
por decodificar e recodificar. Continua O(1) em **memória**, por streaming, mas
é O(n) em **trabalho** — e o programa avisa antes de começar.

**Nada se perde em silêncio.** `errors="replace"` seria fácil e gravaria `?` no
lugar de um `中` que não cabe em ISO-8859-1 — sem volta. A conversão **para**,
diz qual caractere e em que linha, e o arquivo continua exatamente como estava
(a escrita é num temporário ao lado, como toda gravação daqui).

O detalhe que só aparece em arquivo grande: os blocos têm 4 MB e não respeitam
fronteira de caractere, então um `ç` pode ter um byte no fim de um bloco e o
outro no começo do próximo. Por isso os codecs são **incrementais** — decodificar
bloco a bloco produziria lixo a cada 4 MB.

## Realce de sintaxe numa fatia

O motor veio inteiro do TextForge — o `Pintor`, as regras e os 24 provedores de
linguagem. O que **não** veio de graça é o ponto em que os dois programas
diferem:

    no TextForge o QTextDocument tem o ARQUIVO;
    aqui ele tem uma FATIA tirada do meio de um arquivo de 1 GB.

O `QSyntaxHighlighter` começa o bloco 0 no contexto inicial da linguagem. Lá isso
está certo por construção. Aqui, uma fatia que caia dentro de um `/* comentário */`
aberto 3.000 linhas antes seria pintada como **código** — cores erradas
justamente no trecho que a pessoa foi ler.

A correção é a **semente de contexto**: antes de pintar, o editor roda a máquina
de contextos sobre as 200 linhas anteriores à fatia (sem pintar nada) e usa o
resultado como estado de entrada do bloco 0.

```
linha 200  /* abre o comentário          <- fora da fatia
   ...     (as 200 linhas de contexto)
────────── começo da fatia ──────────
linha 350  ainda dentro do comentário    <- pintado como comentário, e não como código
```

São 200 linhas, e não o arquivo inteiro: varrer 500 mil linhas para descobrir a
cor da primeira linha da fatia trocaria uma imprecisão visual por uma pausa a
cada rolagem. O que não couber nelas volta ao contexto inicial da linguagem — o
comportamento de antes.

A suíte `teste_realce.py` não verifica só que o realce funciona: ela **desliga a
semente e exige que o resultado mude**. Sem essa contraprova o teste passaria com
o recurso quebrado.

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
| **Localizar e substituir** | `Ctrl+F` localiza, `Ctrl+H` substitui, `F3` e `Shift+F3` navegam — com maiúsculas, palavra inteira e regex |
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
