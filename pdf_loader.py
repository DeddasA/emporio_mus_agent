import os
import re
import unicodedata
from typing import List
import sqlite3 as sq3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "emporio_musica.db")
DATA_DIR = os.path.join(BASE_DIR, "data")

PDF_DEFAULT_PATH = os.path.join(BASE_DIR, "políticas_da_loja.pdf")
if not os.path.exists(PDF_DEFAULT_PATH):
    PDF_DEFAULT_PATH = os.path.join(DATA_DIR, "políticas_da_loja.pdf")


def remove_accents(text: str) -> str:

    nfkd = unicodedata.normalize('NFKD', text)
    return u"".join([c for c in nfkd if not unicodedata.combining(c)]).lower()


def load_pdf_to_db(pdf_path: str = None) -> int:

    target_pdf = pdf_path or PDF_DEFAULT_PATH
    if not os.path.exists(target_pdf):
        print(f"⚠️ Arquivo PDF não encontrado em {target_pdf}")
        return 0

    try:
        import pypdf
        reader = pypdf.PdfReader(target_pdf)
    except Exception as e:
        print(f"❌ Erro ao inicializar leitor do PDF: {e}")
        return 0

    conn = sq3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_number INTEGER,
            section_title TEXT,
            content TEXT,
            content_clean TEXT
        );
    """)


    cursor.execute("SELECT count(*) FROM store_policies;")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return 0

    records = []
    for page_idx, page in enumerate(reader.pages):
        page_num = page_idx + 1
        raw_text = page.extract_text() or ""
        if not raw_text.strip():
            continue

        paragraphs = raw_text.split("\n\n")
        current_chunk = ""
        current_title = f"Página {page_num}"

        for p in paragraphs:
            clean_p = p.strip()
            if not clean_p:
                continue

            # Detecta se o parágrafo parece um título de seção numerado (ex: "1. Sobre", "3.1 Regras")
            title_match = re.match(r"^(\d+(\.\d+)*\s+[A-ZÀ-Ú][^\n]+)", clean_p)
            if title_match:
                if current_chunk:
                    records.append((page_num, current_title, current_chunk.strip(), remove_accents(current_chunk)))
                    current_chunk = ""
                current_title = title_match.group(1).strip()

            if len(current_chunk) + len(clean_p) < 700:
                current_chunk += "\n" + clean_p
            else:
                if current_chunk:
                    records.append((page_num, current_title, current_chunk.strip(), remove_accents(current_chunk)))
                current_chunk = clean_p

        if current_chunk:
            records.append((page_num, current_title, current_chunk.strip(), remove_accents(current_chunk)))

    cursor.executemany(
        "INSERT INTO store_policies (page_number, section_title, content, content_clean) VALUES (?, ?, ?, ?);",
        records
    )
    conn.commit()
    conn.close()
    print(f"📄 [PDF -> SQLite]: {len(records)} seções extraídas do PDF e salvas na tabela 'store_policies'.")
    return len(records)






class PolicyBase:

    def __init__(self, pdf_path: str = None):
        self.pdf_path = pdf_path or PDF_DEFAULT_PATH
        # Garante que o PDF foi processado para o banco
        load_pdf_to_db(self.pdf_path)

    def search(self, query: str, top_k: int = 3) -> List[str]:
        """Consulta as políticas salvas no SQLite calculando relevância semântica e lexical."""
        clean_query = remove_accents(query)
        words = [w for w in re.findall(r"\w+", clean_query) if len(w) > 2]

        if not os.path.exists(DB_PATH):
            return []

        try:
            conn = sq3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id, page_number, section_title, content, content_clean FROM store_policies;")
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return []

            scored = []
            for row in rows:
                _id, page_num, title, content, content_clean = row
                score = 0
                title_clean = remove_accents(title)

                for w in words:
                    if w in title_clean:
                        score += 5
                    if w in content_clean:
                        score += 1

                if score > 0:
                    formatted_snippet = f"[Página {page_num} | {title}]\n{content}"
                    scored.append((score, formatted_snippet))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = [s[1] for s in scored[:top_k]]
            if not results and rows:
                # Retorna os primeiros trechos do manual como contexto padrão
                results = [f"[Página {r[1]} | {r[2]}]\n{r[3]}" for r in rows[:2]]
            return results
        except Exception as e:
            print(f"Erro na consulta de políticas: {e}")
            return []


