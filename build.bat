@echo off
chcp 65001 >nul
setlocal

rem ===========================================================================
rem  build.bat            gera dist\TextForgeEdit\TextForgeEdit.exe  (one-dir)
rem  build.bat umarquivo  gera dist\TextForgeEdit.exe                (portatil)
rem
rem  SEMPRE o python do .venv, e nunca o `python` do PATH.
rem ===========================================================================

cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo.
    echo ERRO: nao encontrei "%PY%"
    echo.
    echo Monte o ambiente primeiro:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    exit /b 1
)

"%PY%" -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo ERRO: pyinstaller nao esta instalado NO VENV.
    echo     "%PY%" -m pip install -r requirements.txt
    exit /b 1
)

rem -- 1. A suite roda ANTES de empacotar --------------------------------------
rem Empacotar codigo quebrado so adianta a descoberta do problema para depois de
rem o usuario instalar.
echo.
echo === [1/4] Rodando a suite de testes ===
"%PY%" -u tests\rodar_todos.py
if errorlevel 1 (
    echo.
    echo BUILD ABORTADO: a suite falhou. Corrija antes de empacotar.
    exit /b 1
)

rem -- 2. Empacotar ------------------------------------------------------------
echo.
if /i "%~1"=="umarquivo" (
    echo === [2/4] Empacotando ONE-FILE ===
    echo.
    echo     AVISO: o modo um-arquivo descompacta o pacote em %%TEMP%% a CADA
    echo     abertura. Use-o para pendrive; para uso diario, prefira o one-dir.
    echo.
    set "TFEDIT_UM_ARQUIVO=1"
) else (
    echo === [2/4] Empacotando ONE-DIR ===
    set "TFEDIT_UM_ARQUIVO="
)

rem Uma instancia rodando SEGURA os arquivos de dist\ -- o rmdir apaga o que
rem consegue e deixa o resto, e o PyInstaller falha no meio com "Acesso negado".
rem Pior: o que sobra e um dist PELA METADE, e o .exe passa a morrer com
rem "Failed to import encodings module". Ja aconteceu aqui; e melhor recusar.
rem A checagem NAO usa "tasklist | find". Rodando o build sem console
rem anexado -- de um terminal que redireciona a saida --, o find fica
rem esperando no pipe PARA SEMPRE e o build trava sem imprimir nada.
rem Aconteceu duas vezes aqui, e o sintoma ("parou no passo 2") nao
rem aponta para a causa. O PowerShell devolve o resultado pelo codigo de
rem saida, sem pipe nenhum.
powershell -NoProfile -NonInteractive -Command "if (Get-Process TextForgeEdit -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
    echo.
    echo BUILD ABORTADO: ha um TextForgeEdit.exe em execucao.
    echo Ele segura os arquivos de dist\ e o empacotamento falharia no meio,
    echo deixando um dist quebrado. Feche o programa e rode de novo.
    echo.
    exit /b 1
)

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

if exist dist (
    echo.
    echo BUILD ABORTADO: nao foi possivel apagar dist\ por completo.
    echo Algum programa esta com arquivos de la abertos ^(antivirus, Explorer^).
    exit /b 1
)

"%PY%" -m PyInstaller --noconfirm --clean TextForgeEdit.spec
if errorlevel 1 (
    echo.
    echo BUILD ABORTADO: o PyInstaller falhou.
    exit /b 1
)

rem -- 3. Fumaca do executavel -------------------------------------------------
rem `excludes` agressivos quebram o app SO em tempo de execucao.
echo.
echo === [3/4] Autoverificacao do executavel gerado ===
set "EXE=dist\TextForgeEdit\TextForgeEdit.exe"
if /i "%~1"=="umarquivo" set "EXE=dist\TextForgeEdit.exe"

if not exist "%EXE%" (
    echo ERRO: "%EXE%" nao foi gerado.
    exit /b 1
)

"%EXE%" --autoverificacao
if errorlevel 1 (
    echo.
    echo BUILD ABORTADO: o executavel NAO passou na autoverificacao.
    echo Causa mais provavel: um modulo na lista `excludes` do
    echo TextForgeEdit.spec e usado em tempo de execucao.
    exit /b 1
)

rem -- 4. ZIP, so no one-dir ---------------------------------------------------
rem No one-dir o ZIP e o unico jeito de entregar o programa sem alguem copiar so
rem o .exe e descobrir que ele nao funciona sozinho.
if /i not "%~1"=="umarquivo" (
    echo.
    echo === [4/4] Gerando o ZIP ===
    "%PY%" ferramentas\empacotar_zip.py
    if errorlevel 1 (
        echo AVISO: o ZIP nao foi gerado. O build em dist\TextForgeEdit continua valido.
    )
)

echo.
echo ============================================================
echo  BUILD OK
echo  Executavel: %EXE%
for %%F in ("%EXE%") do echo  Tamanho do .exe: %%~zF bytes
if /i not "%~1"=="umarquivo" (
    echo.
    echo  ATENCAO: o .exe do one-dir NAO funciona sozinho. Para distribuir,
    echo  use o ZIP acima ^(ou gere o portatil: build.bat umarquivo^).
)
echo ============================================================
endlocal
