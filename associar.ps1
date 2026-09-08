<#
.SYNOPSIS
    Registra o TextForgeEdit em "Abrir com" para as extensões que você escolher.

.DESCRIPTION
    Escreve APENAS em HKCU — nenhum privilégio de administrador é necessário, e
    nada fora do seu perfil é tocado.

    Usa OpenWithProgids, que ACRESCENTA o TextForgeEdit à lista "Abrir com" da
    extensão SEM roubar o programa padrão. Abrir um .csv continua abrindo no que
    você já usava; o TextForgeEdit passa a ser uma opção.

    O PROGRAMA PADRÃO NÃO SAI DAQUI, e não é limitação deste script. Desde o
    Windows 10 o `UserChoice` de cada extensão é protegido por um hash amarrado
    ao seu usuário, à extensão e ao horário: escrever ali direto é revertido
    pelo sistema. Para tornar o TextForgeEdit padrão de uma extensão:

        Botão direito > Abrir com > Escolher outro aplicativo > Sempre

    ou Configurações > Aplicativos > Aplicativos padrão > por tipo de arquivo.

    Registra SOMENTE as extensões passadas como argumento. Não há lista embutida
    de "extensões que um editor deveria pegar" — de propósito.

.PARAMETER Extensoes
    As extensões, com ou sem ponto: .log csv .txt

.PARAMETER Exe
    Caminho do TextForgeEdit.exe. Por padrão procura em dist\TextForgeEdit\ e
    em dist\.

.PARAMETER TirarDaLista
    Nome de um executável a REMOVER da lista "Abrir com" das mesmas extensões,
    para trocar um editor por outro em vez de acumular os dois.
    Exemplo: -TirarDaLista TextForge.exe

.PARAMETER Remover
    Desfaz tudo o que este script criou.

.PARAMETER Simular
    Mostra o que seria feito, sem escrever nada no registro.

.EXAMPLE
    .\associar.ps1 .txt .csv .log .dat
.EXAMPLE
    .\associar.ps1 .txt .csv -TirarDaLista TextForge.exe
.EXAMPLE
    .\associar.ps1 -Remover

.NOTES
    ESTE ARQUIVO PRECISA ESTAR EM UTF-8 **COM BOM**. O PowerShell 5.1 lê arquivo
    sem BOM como ANSI, e todos os acentos das mensagens viram lixo.

    O executável fica em dist\, que o build.bat APAGA e refaz. O caminho é o
    mesmo depois de reconstruir, então a associação continua valendo; mas se
    você limpar o dist sem reconstruir, o item de "Abrir com" aponta para um
    arquivo que não existe. Rode este script de novo depois de mudar o exe de
    lugar.

    No Windows 11 o item do menu de contexto aparece em "Mostrar mais opções". O
    menu novo exige uma extensão de shell IExplorerCommand empacotada em MSIX,
    que não sai de um script — e prometer o contrário seria enganar quem lê.
#>

# `PositionalBinding = $false` NAO e' enfeite.
#
# Um parametro com `ValueFromRemainingArguments` fica DE FORA da ligacao
# posicional. Sem esta linha, `$Exe` vira o primeiro posicional e um
# `.ssociar.ps1 .txt .csv` silenciosamente entende `.txt` como o CAMINHO DO
# EXECUTAVEL -- e o script responde "nao encontrei o TextForgeEdit.exe" sem dar
# a menor pista de por que. Com ela, so' o que tem `Position` explicito liga por
# posicao, e o resto cai em `$Extensoes`.
[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Extensoes,
    [string] $Exe = "",
    [string] $TirarDaLista = "",
    [switch] $Remover,
    [switch] $Simular
)

$ErrorActionPreference = "Stop"
$ProgID  = "TextForgeEdit.arquivo"
$AppExe  = "TextForgeEdit.exe"
# `$PSScriptRoot` e' o jeito certo desde o PowerShell 3.0. O
# `$MyInvocation.MyCommand.Path` que se ve' por ai' vem VAZIO em varias formas
# de invocacao (dot-sourcing, `&`, chamada por outro processo), e ai' o script
# procura o executavel a partir de uma raiz em branco e jura que nao achou.
$Raiz = $PSScriptRoot
if (-not $Raiz) { $Raiz = Split-Path -Parent $MyInvocation.MyCommand.Definition }
if (-not $Raiz) { $Raiz = (Get-Location).Path }
$FileExts = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"

function Escrever($mensagem, $cor = "Gray") {
    Write-Host $mensagem -ForegroundColor $cor
}

# `-LiteralPath` EM TODA CHAMADA, e nao por preciosismo.
#
# O menu de contexto mora em `HKCU:\Software\Classes\*\shell\...`, e esse `*`
# e' o nome LITERAL da chave que o Windows usa para "qualquer arquivo". Sem
# `-LiteralPath`, o provedor de registro do PowerShell trata o `*` como CURINGA
# e sai varrendo as milhares de chaves de Software\Classes atras de um casamento
# -- o script parece travado, e a chave nunca e' criada.
function Definir-Chave($caminho, $nome, $valor) {
    if ($Simular) {
        Escrever "  [simulacao] $caminho :: $(if ($nome) { $nome } else { '(padrao)' }) = $valor"
        return
    }
    if (-not (Test-Path -LiteralPath $caminho)) {
        # `New-Item` NAO aceita -LiteralPath no provedor de registro, e com `*`
        # no caminho ele tambem globa. A saida e' a API do .NET, que trata o
        # caminho como texto puro.
        $sub = $caminho.Replace("HKCU:\", "")
        [void][Microsoft.Win32.Registry]::CurrentUser.CreateSubKey($sub)
    }
    if ($nome) {
        New-ItemProperty -LiteralPath $caminho -Name $nome -Value $valor -PropertyType String -Force | Out-Null
    } else {
        Set-ItemProperty -LiteralPath $caminho -Name "(default)" -Value $valor -Force
    }
}

function Remover-Chave($caminho) {
    if (-not (Test-Path -LiteralPath $caminho)) { return }
    if ($Simular) { Escrever "  [simulacao] remover $caminho"; return }
    Remove-Item -LiteralPath $caminho -Recurse -Force -ErrorAction SilentlyContinue
}

function Atualizar-Explorer {
    # Sem isto o Explorer só mostra a mudança depois de reiniciar.
    # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0.
    if ($Simular) { Escrever "  [simulacao] SHChangeNotify(ASSOCCHANGED)"; return }
    try {
        Add-Type -Namespace TFE -Name Shell -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("shell32.dll")]
public static extern void SHChangeNotify(int eventId, uint flags, System.IntPtr a, System.IntPtr b);
'@ -ErrorAction Stop
        [TFE.Shell]::SHChangeNotify(0x08000000, 0, [System.IntPtr]::Zero, [System.IntPtr]::Zero)
    } catch {
        Escrever "  (nao foi possivel notificar o Explorer: $($_.Exception.Message))" "DarkYellow"
    }
}

function Tirar-Do-OpenWithList($ext, $alvoExe) {
    <#
        Remove um programa da lista "Abrir com" que o EXPLORER mantem, em
        FileExts\<ext>\OpenWithList. Nao e' a mesma coisa que OpenWithProgids:
        esta e' a lista de uso recente que o Explorer preenche sozinho quando
        voce escolhe um programa pelo dialogo.

        O CUIDADO QUE IMPORTA: os valores sao letras (a, b, c...) e o `MRUList`
        e' uma string com essas letras em ordem de uso. Apagar o valor sem tirar
        a letra do MRUList deixa o Explorer apontando para uma entrada que nao
        existe mais.
    #>
    $chave = "$FileExts\$ext\OpenWithList"
    if (-not (Test-Path -LiteralPath $chave)) { return $false }

    $prop = Get-ItemProperty -LiteralPath $chave -ErrorAction SilentlyContinue
    if (-not $prop) { return $false }

    $letras = $prop.PSObject.Properties |
        Where-Object { $_.Name -notlike "PS*" -and $_.Name -ne "MRUList" -and
                       $_.Value -eq $alvoExe } |
        ForEach-Object { $_.Name }
    if (-not $letras) { return $false }

    if ($Simular) {
        Escrever "  [simulacao] $ext : tirar $alvoExe (valor $($letras -join ', '))"
        return $true
    }

    foreach ($letra in $letras) {
        Remove-ItemProperty -LiteralPath $chave -Name $letra -Force -ErrorAction SilentlyContinue
    }
    $mru = $prop.MRUList
    if ($mru) {
        $novo = ($mru.ToCharArray() | Where-Object { $letras -notcontains "$_" }) -join ""
        Set-ItemProperty -LiteralPath $chave -Name "MRUList" -Value $novo -Force
    }
    return $true
}

# ---------------------------------------------------------------------------
# Remover
# ---------------------------------------------------------------------------

if ($Remover) {
    Escrever "Removendo o registro do TextForgeEdit (somente HKCU)..." "Cyan"

    Remover-Chave "HKCU:\Software\Classes\$ProgID"
    Remover-Chave "HKCU:\Software\Classes\Applications\$AppExe"
    Remover-Chave "HKCU:\Software\Classes\*\shell\TextForgeEdit"

    # Tira o ProgID do OpenWithProgids de TODA extensao que o tenha. Varrer e'
    # obrigatorio: quem remove normalmente nao lembra quais extensoes registrou.
    $limpas = 0
    Get-ChildItem "HKCU:\Software\Classes" -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -like ".*" } |
        ForEach-Object {
            $alvo = "HKCU:\Software\Classes\$($_.PSChildName)\OpenWithProgids"
            if (Test-Path -LiteralPath $alvo) {
                $prop = Get-ItemProperty -LiteralPath $alvo -ErrorAction SilentlyContinue
                if ($prop -and ($prop.PSObject.Properties.Name -contains $ProgID)) {
                    if ($Simular) {
                        Escrever "  [simulacao] tirar $ProgID de $($_.PSChildName)"
                    } else {
                        Remove-ItemProperty -LiteralPath $alvo -Name $ProgID -Force -ErrorAction SilentlyContinue
                    }
                    $limpas++
                }
            }
        }

    Atualizar-Explorer
    Escrever "Pronto. $limpas extensao(oes) desassociada(s)." "Green"
    Escrever "O programa padrao de cada extensao NAO foi alterado (nunca foi tocado)."
    exit 0
}

# ---------------------------------------------------------------------------
# Localizar o executavel
# ---------------------------------------------------------------------------

if (-not $Exe) {
    $candidatos = @(
        (Join-Path $Raiz "dist\TextForgeEdit\$AppExe"),
        (Join-Path $Raiz "dist\$AppExe"),
        (Join-Path $Raiz $AppExe)
    )
    $Exe = $candidatos | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $Exe -or -not (Test-Path $Exe)) {
    Escrever "ERRO: nao encontrei o TextForgeEdit.exe." "Red"
    Escrever ""
    Escrever "Gere o executavel primeiro:"
    Escrever "    .\build.bat"
    Escrever "ou informe o caminho:"
    Escrever "    .\associar.ps1 .txt -Exe C:\caminho\TextForgeEdit.exe"
    exit 1
}
$Exe = (Resolve-Path $Exe).Path

# O icone do TIPO DE ARQUIVO, que e' diferente do icone do programa.
#
# Sem isto, um `.txt` associado aparece no Explorer com o simbolo do EDITOR --
# e a pessoa nao sabe, olhando a pasta, se aquilo e' o programa ou um arquivo
# dele. Com a variante de pagina, o arquivo parece um arquivo.
#
# Procura ao lado do executavel (build one-dir, dentro de `_internal`) e depois
# na arvore de fontes. Nao achando, cai no icone do proprio .exe -- que e' o
# comportamento antigo, e continua correto.
$PastaDoExe = Split-Path -Parent $Exe
$IconeDoArquivo = @(
    (Join-Path $PastaDoExe "_internal\tfedit\recursos\icone_arquivo.ico"),
    (Join-Path $PastaDoExe "tfedit\recursos\icone_arquivo.ico"),
    (Join-Path $Raiz "tfedit\recursos\icone_arquivo.ico")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if ($IconeDoArquivo) {
    $IconeDoArquivo = (Resolve-Path $IconeDoArquivo).Path
    $ExpressaoDoIcone = "`"$IconeDoArquivo`""
} else {
    $ExpressaoDoIcone = "`"$Exe`",0"
}

if (-not $Extensoes -or $Extensoes.Count -eq 0) {
    Escrever "Nenhuma extensao informada." "Yellow"
    Escrever ""
    Escrever "Uso:  .\associar.ps1 .txt .csv .log .dat"
    Escrever ""
    Escrever "De proposito nao ha' lista embutida: registra SOMENTE o que voce"
    Escrever "pedir. Sugestoes para este editor, que e' feito para arquivo grande:"
    Escrever "    .txt .log .dat .csv .tsv .dsv .json .xml .sql .xlsx"
    exit 1
}

# ---------------------------------------------------------------------------
# Registrar
# ---------------------------------------------------------------------------

Escrever "TextForgeEdit: $Exe" "Cyan"
if ($Simular) { Escrever "MODO SIMULACAO: nada sera' escrito no registro." "Yellow" }
Escrever ""

$comando = "`"$Exe`" `"%1`""

# 1. O ProgID: o "tipo de arquivo" do TextForgeEdit.
if ($IconeDoArquivo) {
    Escrever "Ícone dos arquivos: $IconeDoArquivo" "Cyan"
} else {
    Escrever "Ícone dos arquivos: o do próprio executável (icone_arquivo.ico não encontrado)" "DarkYellow"
}
Escrever ""

Escrever "1. ProgID $ProgID"
Definir-Chave "HKCU:\Software\Classes\$ProgID" $null "Arquivo de texto (TextForgeEdit)"
Definir-Chave "HKCU:\Software\Classes\$ProgID\DefaultIcon" $null $ExpressaoDoIcone
Definir-Chave "HKCU:\Software\Classes\$ProgID\shell\open\command" $null $comando

# 2. O registro do aplicativo, que faz o nome aparecer bonito no "Abrir com".
Escrever "2. Applications\$AppExe"
Definir-Chave "HKCU:\Software\Classes\Applications\$AppExe" "FriendlyAppName" "TextForgeEdit"
Definir-Chave "HKCU:\Software\Classes\Applications\$AppExe\shell\open\command" $null $comando
# SupportedTypes vazio nao restringe: e' o que faz o TextForgeEdit aparecer
# tambem no "Abrir com > Escolher outro aplicativo" de QUALQUER extensao.
Definir-Chave "HKCU:\Software\Classes\Applications\$AppExe\SupportedTypes" ".*" ""

# 3. As extensoes pedidas -- via OpenWithProgids, que ACRESCENTA sem roubar.
Escrever "3. Extensoes"
$normalizadas = @()
foreach ($bruta in $Extensoes) {
    $ext = $bruta.Trim()
    if (-not $ext) { continue }
    if (-not $ext.StartsWith(".")) { $ext = ".$ext" }
    $ext = $ext.ToLower()

    if ($ext -notmatch '^\.[a-z0-9_\-\.]{1,20}$') {
        Escrever "   ignorada (nao parece uma extensao): $bruta" "DarkYellow"
        continue
    }
    $normalizadas += $ext
    Definir-Chave "HKCU:\Software\Classes\$ext\OpenWithProgids" $ProgID ""
    Escrever "   $ext  ->  adicionado a lista 'Abrir com'" "Green"
}

# 4. Tirar outro programa da lista, quando pedido.
if ($TirarDaLista) {
    $outro = $TirarDaLista.Trim()
    if (-not $outro.ToLower().EndsWith(".exe")) { $outro = "$outro.exe" }
    Escrever "4. Tirando $outro da lista 'Abrir com'"

    $tiradas = 0
    foreach ($ext in $normalizadas) {
        if (Tirar-Do-OpenWithList $ext $outro) {
            Escrever "   $ext  ->  $outro removido" "Green"
            $tiradas++
        }
    }
    # E o ProgID dele, se estiver registrado nessas extensoes.
    $progOutro = [System.IO.Path]::GetFileNameWithoutExtension($outro) + ".arquivo"
    foreach ($ext in $normalizadas) {
        $alvo = "HKCU:\Software\Classes\$ext\OpenWithProgids"
        if (Test-Path -LiteralPath $alvo) {
            $prop = Get-ItemProperty -LiteralPath $alvo -ErrorAction SilentlyContinue
            if ($prop -and ($prop.PSObject.Properties.Name -contains $progOutro)) {
                if ($Simular) {
                    Escrever "   [simulacao] $ext : tirar o ProgID $progOutro"
                } else {
                    Remove-ItemProperty -LiteralPath $alvo -Name $progOutro -Force -ErrorAction SilentlyContinue
                }
                $tiradas++
            }
        }
    }
    if ($tiradas -eq 0) {
        Escrever "   (nada a remover: $outro nao estava listado nessas extensoes)"
    }
    $numero = 5
} else {
    $numero = 4
}

# 5. Menu de contexto de qualquer arquivo.
Escrever "$numero. Menu de contexto ('Abrir com o TextForgeEdit')"
Definir-Chave "HKCU:\Software\Classes\*\shell\TextForgeEdit" $null "Abrir com o Text&ForgeEdit"
Definir-Chave "HKCU:\Software\Classes\*\shell\TextForgeEdit" "Icon" "`"$Exe`",0"
Definir-Chave "HKCU:\Software\Classes\*\shell\TextForgeEdit\command" $null $comando

Atualizar-Explorer

Escrever ""
Escrever "Pronto." "Green"
Escrever ""
Escrever "O programa PADRAO de cada extensao NAO foi alterado, e nao da' para"
Escrever "altera-lo por script: desde o Windows 10 o UserChoice e' protegido por um"
Escrever "hash amarrado ao seu usuario, e escrever ali direto e' revertido pelo"
Escrever "sistema. Para tornar o TextForgeEdit padrao de uma extensao:"
Escrever ""
Escrever "    Botao direito > Abrir com > Escolher outro aplicativo > Sempre"
Escrever ""
Escrever "No Windows 11, o item do menu de contexto fica em 'Mostrar mais opcoes'."
Escrever ""
Escrever "Para desfazer:  .\associar.ps1 -Remover"
