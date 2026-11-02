import os
import re
import unicodedata
from typing import List
import sqlite3 as sq3


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(ROOT_DIR, "instance", "emporio_musica.db")
MD_DEFAULT_PATH = os.path.join(ROOT_DIR, "policy", "policy.md")


def remove_accents(text: str) -> str:
    nfkd = unicodedata.normalize('NFKD', text)
    return u"".join([c for c in nfkd if not unicodedata.combining(c)]).lower()


def load_pdf_to_db(md_path: str = None) -> int:
    target_md = md_path or MD_DEFAULT_PATH

    if not os.path.exists(target_md):
        print(f"⚠️ Arquivo Markdown não encontrado em {target_md}")
        return 0

    with open(target_md, "r", encoding="utf-8") as f:
        raw_text = f.read()

    conn = sq3.connect(DB_PATH)
    cursor = conn.cursor()

    records = []

    # Split by "## " (sections)
    sections = re.split(r'\n(?=## )', raw_text)

    page_num = 1
    for section in sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n")
        title = lines[0].replace("#", "").strip()

        # If it's the main title, we STILL save it because it contains the address!
        if title.startswith("EMPÓRIO DA MÚSICA"):
            title = "Informações Gerais e Endereço"

        records.append((page_num, title, section, remove_accents(section)))
        page_num += 1

    if records:
        try:
            cursor.execute("DELETE FROM store_policies;")
        except sq3.OperationalError:
            print("⚠️ Tabela 'store_policies' não existe.")
            conn.close()
            return 0

        cursor.executemany(
            "INSERT INTO store_policies (page_number, section_title, content, content_clean) VALUES (?, ?, ?, ?);",
            records
        )
        conn.commit()

    conn.close()
    print(f"📄 [MD -> SQLite]: {len(records)} seções extraídas do Markdown e salvas na tabela 'store_policies'.")
    return len(records)


from rapidfuzz import fuzz


class PolicyBase:
    def __init__(self, md_path: str = None):
        self.md_path = md_path or MD_DEFAULT_PATH
        load_pdf_to_db(self.md_path)
        self._policies = []
        self._load_policies_to_memory()

    def _load_policies_to_memory(self):
        try:
            conn = sq3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT page_number, section_title, content, content_clean FROM store_policies;")
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                page_num, title, content, content_clean = row
                self._policies.append({
                    "title": title,
                    "title_clean": remove_accents(title),
                    "content": content,
                    "content_clean": content_clean
                })
            print(f"📚 [PolicyBase] {len(self._policies)} seções carregadas na memória.")
        except Exception as e:
            print(f"Erro ao carregar políticas: {e}")

    def search(self, query: str, top_k: int = 3) -> List[str]:
        if not self._policies:
            return []

        clean_query = remove_accents(query)

        scored = []
        for p in self._policies:

            title_score = fuzz.partial_ratio(clean_query, p["title_clean"])
            content_score = fuzz.partial_ratio(clean_query, p["content_clean"])


            total_score = (title_score * 2) + content_score


            if any(kw in clean_query for kw in ["endereco", "localizacao", "onde", "horario", "funcionamento"]):
                if "sobre a empório" in p["title_clean"].lower() or "horário" in p["content_clean"]:
                    total_score += 150

            if total_score > 70:  # Só adiciona se a similaridade for razoável
                formatted_snippet = f"[Seção: {p['title']}]\n{p['content']}"
                scored.append((total_score, formatted_snippet))


        scored.sort(key=lambda x: x[0], reverse=True)
        results = [s[1] for s in scored[:top_k]]

        # Fallback caso nada atinja o score mínimo
        if not results and self._policies:
            results = [f"[Seção: {r['title']}]\n{r['content']}" for r in self._policies[:2]]

        return results