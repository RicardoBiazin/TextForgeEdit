r"""Empacota dist\TextForgeEdit\ num ZIP pronto para entregar.

O one-dir tem ~200 arquivos. Extrair isso no Explorer sem uma pasta na raiz
despeja tudo onde o usuario estiver -- por isso o ZIP carrega a pasta
`TextForgeEdit/` dentro, e nao o conteudo solto.
"""

from __future__ import annotations

import pathlib
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tfedit import VERSAO                                    # noqa: E402


def main() -> int:
    origem = RAIZ / "dist" / "TextForgeEdit"
    if not origem.is_dir():
        print(f"ERRO: {origem} nao existe. Rode o build.bat primeiro.")
        return 1

    destino = RAIZ / "dist" / f"TextForgeEdit-{VERSAO}-win64.zip"
    arquivos = sorted(p for p in origem.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in arquivos)

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=9) as zip_:
        for arquivo in arquivos:
            zip_.write(arquivo,
                       str(pathlib.Path("TextForgeEdit")
                           / arquivo.relative_to(origem)))

    print(destino)
    print(f"  {destino.stat().st_size / (1024*1024):.1f} MB zipado "
          f"(de {total / (1024*1024):.1f} MB em {len(arquivos)} arquivos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
