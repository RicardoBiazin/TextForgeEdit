# CLAUDE.md — convenções do TextForgeEdit

Instruções para quem editar este projeto depois. Vale para pessoas e para
agentes. O que está aqui não é preferência de estilo: cada regra existe porque a
alternativa já produziu um defeito — em geral no projeto irmão, o TextForge.

## As regras que não se negociam

**1. O documento nunca é carregado inteiro.** Nenhuma função pode devolver o
conteúdo completo de um arquivo grande como `str` ou `bytes` no caminho normal de
uso. Ler é sempre por faixa (`ler(a, b)`) ou por linha (`faixa(a, b)`). Uma
função que materializa 240 MB anula o projeto inteiro.

**2. Nunca alterar conteúdo em silêncio.** Sem edição, gravar devolve o arquivo
**byte a byte** — CRLF, fim de linha misto e ausência de quebra final inclusive.
As peças intocadas são copiadas como bytes, então o gravador nem precisa
entendê-las. Há teste com 10 fixtures.

**3. Um arquivo aberto é DADO, nunca código.** Nada do que o usuário abre é
executado. `eval`, `exec`, `os.system`, `subprocess(shell=True)` e `pickle.load`
estão proibidos no pacote.

## Armadilhas específicas deste código

| Onde | O quê |
|---|---|
| `pecas.py` | A pilha de desfazer guarda **operações inversas** (o que saiu e o que entrou), nunca um instantâneo da lista de peças. No TextForge, um instantâneo por operação mediu **800 MB** com 10 mil edições: cada cópia carrega as peças que as anteriores criaram, e o custo é quadrático. |
| `pecas.py` | `Edicao` guarda `removido` **e** `inserido`. Uma versão inicial guardava o texto inserido num dicionário indexado por `id()` do objeto — id é reaproveitado pelo Python após a coleta, e o dicionário era atributo de **classe**, compartilhado entre todos os documentos abertos. |
| `pecas.py` | Há um cursor guardado em `_localizar`. Digitar avança o offset de um em um; sem o atalho, cada tecla varreria a lista inteira e o custo total seria quadrático. |
| `pecas.py` | O caminho rápido da digitação seguida faz a peça **crescer** em vez de criar uma por tecla. Sem ele, digitar um parágrafo cria centenas de peças. |
| `pecas.py` | `substituir` é **uma** operação de desfazer, não duas. Registrada como remover+inserir, um `Ctrl+Z` devolveria o texto antigo e manteria o novo — um estado que nunca existiu. |
| `pecas.py` | Editar exige `pode_editar` (índice completo). Partir uma peça precisa saber quantas linhas ficam de cada lado, e isso vem de `original.linhas_ate()`, que só é confiável depois da varredura. |
| `original.py` | Tudo é em **bytes**. Posição em caracteres exigiria decodificar tudo que vem antes — ou seja, carregar o arquivo. A decodificação é por linha, na hora de desenhar. |
| `original.py` | O índice é **esparso** (`PASSO`). Guardar o offset de cada linha de 13 milhões custaria ~100 MB só de lista Python. |
| `gravacao.py` | A ordem no Windows: escrever o temporário com o mmap **aberto** → fechar o mmap → trocar → reabrir. Fechar antes grava arquivo vazio; deixar aberto faz a troca falhar com acesso negado. As duas falhas já aconteceram no TextForge. |
| `gravacao.py` | `ReplaceFileW` antes de `os.replace`: o segundo perde ACEs explícitas e fluxos alternativos do original. E o temporário nasce **na mesma pasta** — `os.replace` entre volumes falha. |
| `gravacao.py` | Espaço em disco é conferido **antes** do primeiro byte. Descobrir que faltou disco depois de escrever 200 MB é o pior momento possível. |

## Ao acrescentar um recurso

1. O núcleo (`tfedit/*.py`, exceto interface) **não importa Qt**. É o que permite
   testá-lo sem tela e reaproveitá-lo depois.
2. Teste novo entra em `tests/` e na lista `SUITES` de `rodar_todos.py`.
3. Uma verificação que não pode falhar não vale nada. Se um teste passa com o
   código quebrado, ele está errado — enfraquecer a condição não é opção.
4. Comentário explica **por quê**, não o quê. O código já diz o quê.
