import fitz
import os
import glob

out_dir = 'tmp_txt'
os.makedirs(out_dir, exist_ok=True)
pdfs = glob.glob('input/pdf_content/*.pdf')
print(f'Found {len(pdfs)} pdfs')

for p in pdfs:
    doc = fitz.open(p)
    txt = ''
    for page in doc:
        txt += page.get_text()
    out_path = os.path.join(out_dir, os.path.basename(p) + '.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(txt)
    print(f'Extracted {out_path}')
