# assets/fonts

Bundled Unicode fonts used by the PDF export feature (`pages/1_Vocab_Export.py`).

| File | Weight | Size |
|------|--------|------|
| `DejaVuSans.ttf` | Regular | ~739 KB |
| `DejaVuSans-Bold.ttf` | Bold | ~689 KB |

## Font choice

**DejaVu Sans 2.37** — open license (see [LICENSE](https://github.com/dejavu-fonts/dejavu-fonts/blob/master/LICENSE)), covers Latin Extended A & B which includes all German umlauts (ä ö ü ß Ä Ö Ü), Afrikaans characters, and common punctuation such as em-dashes produced by GPT-4o output.

## Re-downloading

If the font files are missing, run from the repo root:

```bash
micromamba run -n language_learning_env python -c "
import io, pathlib, urllib.request, zipfile
fonts = pathlib.Path('assets/fonts')
fonts.mkdir(parents=True, exist_ok=True)
url = 'https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-fonts-ttf-2.37.zip'
needed = {'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'}
data = urllib.request.urlopen(url).read()
with zipfile.ZipFile(io.BytesIO(data)) as zf:
    for m in zf.namelist():
        if pathlib.PurePosixPath(m).name in needed:
            (fonts / pathlib.PurePosixPath(m).name).write_bytes(zf.read(m))
            print('extracted', pathlib.PurePosixPath(m).name)
"
```
