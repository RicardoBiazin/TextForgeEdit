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

Núcleo pronto e testado; interface ainda não.

| Parte | Situação |
|---|---|
| `tfedit/original.py` — mmap + índice esparso incremental | pronto |
| `tfedit/pecas.py` — tabela de peças, desfazer, fusão de digitação | pronto |
| `tfedit/gravacao.py` — gravação por streaming, troca atômica | pronto |
| Interface | a definir |

**Medido** (arquivo de 33 MB, 800 mil linhas): 3 mil edições custam menos de
2 MB de RAM; gravar tem pico de poucos MB.

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

Sem pytest, de propósito — cada suíte roda num processo separado, então um
travamento de Qt numa não leva as outras.

## Licença

MIT. Autor: Ricardo Biazin.
