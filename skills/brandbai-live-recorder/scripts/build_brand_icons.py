"""Mechanical size/format conversion of the approved logo, for release builds only."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def main():
    assets = ROOT / 'assets' / 'chrome-extension' / 'assets'
    with Image.open(assets / 'brandbai-logo.png') as original:
        logo = original.convert('RGBA')
        for size in (16, 32, 48, 128):
            logo.resize((size, size), Image.Resampling.LANCZOS).save(assets / f'icon-{size}.png')
        logo.save(ROOT / 'assets' / 'windows-assistant' / 'brandbai.ico',
                  format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])


if __name__ == '__main__':
    main()
