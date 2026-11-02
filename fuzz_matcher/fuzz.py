import sqlite3 as sq3
from rapidfuzz import process, fuzz

# Cache global para não bater no banco toda hora
_PRODUCT_CACHE = None


def get_fuzzy_product_ids(query_text: str, db_path: str, threshold: int = 65, limit: int = 3) -> list:
    global _PRODUCT_CACHE
    try:
        # Se o cache não existe, busca no banco UMA VEZ e salva na memória
        if _PRODUCT_CACHE is None:
            conn = sq3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT product_id, name FROM products WHERE stock_quantity > 0 AND (status IS NULL OR status = 'active')")
            _PRODUCT_CACHE = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

        if not _PRODUCT_CACHE:
            return []

        names_list = list(_PRODUCT_CACHE.values())

        # fuzz.token_set_ratio ignora palavras extras ("quanto custa o...")
        matches = process.extract(query_text, names_list, scorer=fuzz.token_set_ratio, limit=limit)

        best_ids = []
        for match_name, score, _ in matches:
            if score >= threshold:
                for pid, pname in _PRODUCT_CACHE.items():
                    if pname == match_name:
                        best_ids.append(pid)
                        break
        return best_ids
    except Exception as e:
        print(f"Erro no fuzzy search: {e}")
        return []