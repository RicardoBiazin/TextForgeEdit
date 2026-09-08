# -*- mode: python ; coding: utf-8 -*-
"""Empacotamento do TextForgeEdit.

    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean TextForgeEdit.spec

Duas coisas valem ser lidas antes de mexer:

**`PySide6.QtNetwork` NAO entra nos excludes**, por mais que pareca um recurso de
rede dispensavel. E' onde vivem QLocalServer e QLocalSocket -- a instancia unica e
o "Abrir com" do Explorer dependem deles. Excluir mata os dois SEM erro de build:
o defeito so' aparece em uso.

**As DLLs descartadas foram verificadas, e nao adivinhadas.** O OpenSSL so' serve
ao TLS do QtNetwork, e aqui o QtNetwork nao faz TLS; o `opengl32sw.dll` e' o
rasterizador de software do Qt, e este programa e' Widgets puro -- nada cria um
contexto OpenGL. Se em alguma maquina o programa nao abrir, o primeiro teste e'
tirar `opengl32sw.dll` desta lista e gerar de novo.
"""

import os
import pathlib

UM_ARQUIVO = bool(os.environ.get("TFEDIT_UM_ARQUIVO"))

hiddenimports = [
    # Import tardio, dentro de funcao: a analise estatica nao alcanca.
    "charset_normalizer",
    # Idem: `planilha/leitor.py` so' importa openpyxl quando abre uma planilha.
    "openpyxl",
]

excludes = [
    # Modulos Qt que o projeto nao usa. Vem do PySide6-Essentials; o metapacote
    # PySide6 traria muito mais, e por isso o requirements.txt pede o -Essentials.
    #
    # ATENCAO: `PySide6.QtNetwork` NAO entra aqui. Ver o cabecalho.
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPositioning",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtSerialPort", "PySide6.QtSvgWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtConcurrent",
    # Pesos pesados que nada aqui importa. Um `import pandas` que entrasse por
    # descuido somaria dezenas de MB ao pacote.
    "tkinter", "numpy", "pandas", "matplotlib", "scipy",
    "PyQt5", "PyQt6", "IPython", "pytest", "setuptools", "pip",
]

# Descartadas de `a.binaries` -- sao bibliotecas NATIVAS, e `excludes` age sobre
# modulos Python. Ver o cabecalho para o porque de cada uma.
DLLS_DESNECESSARIAS = [
    "libcrypto-3-x64.dll", "libssl-3-x64.dll",
    "libcrypto-3.dll", "libssl-3.dll",
    "opengl32sw.dll",
    "Qt6Pdf.dll", "Qt6Quick.dll", "Qt6Qml.dll",
]

# Traducao do Qt para portugues do Brasil. Sem estes .qm, os botoes dos
# dialogos padrao ("Save", "Discard", "Cancel", "Open") aparecem em ingles no
# meio de uma janela em portugues -- e o PyInstaller NAO os inclui sozinho.
import PySide6 as _PySide6
_traducoes = pathlib.Path(_PySide6.__file__).parent / "translations"
datas = [(str(_traducoes / f"{c}.qm"), "traducoes")
         for c in ("qtbase_pt_BR", "qt_pt_BR")
         if (_traducoes / f"{c}.qm").is_file()]
print(f"[TextForgeEdit] {len(datas)} catalogo(s) de traducao no pacote")

# Os temas do realce. Sem eles o .exe cai nas "cores de emergencia" de
# `tema.embutido()` -- o programa abre, mas sem realce nenhum, e o defeito so'
# aparece no executavel: rodando do fonte a pasta esta' la'.
_temas = pathlib.Path("tfedit/recursos/temas")
_json = sorted(_temas.glob("*.json"))
if not _json:
    raise SystemExit("[TextForgeEdit] tfedit/recursos/temas/ vazio: o .exe "
                     "sairia sem realce. Empacotamento abortado.")
datas += [(str(a), "tfedit/recursos/temas") for a in _json]
print(f"[TextForgeEdit] {len(_json)} tema(s) no pacote")

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,          # remove asserts; NAO usa 2, que apagaria os docstrings
)

_antes = len(a.binaries)
a.binaries = [b for b in a.binaries
              if pathlib.Path(b[0]).name.lower()
              not in {d.lower() for d in DLLS_DESNECESSARIAS}]
print(f"[TextForgeEdit] {_antes - len(a.binaries)} DLL(s) desnecessaria(s) "
      f"removida(s)")

pyz = PYZ(a.pure)

# UPX fica FORA das DLLs grandes do Qt e do Python: comprimi-las aumenta o tempo
# de partida e e' um gatilho conhecido de falso positivo de antivirus.
upx_exclude = ["Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Network.dll",
               "python313.dll", "qwindows.dll", "vcruntime140.dll"]

if UM_ARQUIVO:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="TextForgeEdit",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=upx_exclude,
        runtime_tmpdir=None,
        console=False,                    # e' programa de janela
        disable_windowed_traceback=False,  # sem isto um erro fica invisivel
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version="versao.txt",
        manifest="textforgeedit.manifest",
        uac_admin=False,   # elevado, o arrastar-e-soltar do Explorer PARA
    )
else:
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="TextForgeEdit",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=upx_exclude,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        version="versao.txt",
        manifest="textforgeedit.manifest",
        uac_admin=False,
    )
    coll = COLLECT(
        exe, a.binaries, a.datas,
        strip=False,
        upx=True,
        upx_exclude=upx_exclude,
        name="TextForgeEdit",
    )
