import os
import re
import json
import logging
import datetime as dt
import requests as req
import sqlite3 as sq3
from Fuzz_matcher.fuzz import get_fuzzy_product_ids
from schema.db_schema import normalize_text

from Config.config import DB_PATH, LOG_PATH_LLM

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ROOT_DIR = os.getcwd()





os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH_LLM), exist_ok=True)

agent_logger = logging.getLogger("Agent")
agent_logger.setLevel(logging.INFO)
if not agent_logger.handlers:
    _fh = logging.FileHandler(LOG_PATH_LLM, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s"))
    agent_logger.addHandler(_fh)
    agent_logger.propagate = False


def agent_log(message):
    print(message, flush=True)
    agent_logger.info(message)
    try:
        with open(LOG_PATH_LLM, "a", encoding="utf-8") as f:
            timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp} - [RAW_BACKUP]: {message}\n")
    except Exception as e:
        print(f"[agent_log] failed to write log: {e!r}", flush=True)


def query_database(sql_query: str) -> str:
    prohibited = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH"]
    for keyword in prohibited:
        if re.search(rf"\b{keyword}\b", sql_query, re.IGNORECASE):
            return "Erro: Apenas consultas de leitura (SELECT) são permitidas."

    try:
        conn = sq3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if not rows:
            return "Nenhum resultado encontrado no banco de dados."

        rows = rows[:8]
        results = [dict(zip(columns, row)) for row in rows]
        return json.dumps(results, ensure_ascii=False, indent=1)
    except Exception as e:
        return f"Erro ao executar consulta SQL: {str(e)}"


def search_products_fallback(query_text: str) -> str:
    clean_q = normalize_text(query_text)

    max_price = None
    price_match = re.search(
        r'(?:ate|abaixo\s+de|menos\s+de|maximo\s+de|no\s+maximo|por\s+ate)\s*(?:r\$\s*)?(\d+(?:[.,]\d+)?)',
        clean_q,
    )
    if price_match:
        try:
            max_price = float(price_match.group(1).replace(',', '.'))
        except ValueError:
            max_price = None

    if max_price is None:
        loose = re.search(r'r\$\s*(\d+(?:[.,]\d+)?)', clean_q)
        if loose:
            try:
                max_price = float(loose.group(1).replace(',', '.'))
            except ValueError:
                max_price = None

    # Adicionadas palavras de pergunta para limpar a busca
    stop_words = {
        "tem", "qual", "quais", "preco", "preço", "valor", "estoque", "voces", "vocês",
        "sobre", "gostaria", "favor", "disponivel", "disponiveis", "opcoes", "opções",
        "custando", "custa", "reais", "ate", "abaixo", "menos", "para", "com", "uma", "uns",
        "opcao", "opção", "modelo", "modelos", "marca", "marcas",
        "quanto", "quantos", "quantas", "queria", "busco", "procuro", "ver"
    }
    raw_words = [w for w in re.findall(r"\w+", clean_q) if len(w) > 2 and w not in stop_words]

    try:
        conn = sq3.connect(DB_PATH)
        cursor = conn.cursor()

        # -------------------------------------------------------------
        # 1. FUZZY SEARCH PRIMEIRO (Alta precisão para Rozini, Yamaha, etc)
        # -------------------------------------------------------------
        if raw_words:
            fuzzy_ids = get_fuzzy_product_ids(clean_q, DB_PATH, threshold=65, limit=3)

            if fuzzy_ids:
                placeholders = ",".join(["?"] * len(fuzzy_ids))
                price_condition = ""
                params = list(fuzzy_ids)

                if max_price is not None:
                    price_condition = "AND p.price_brl <= ?"
                    params.append(max_price)

                sql = f"""
                    SELECT 
                        p.product_id, p.brand AS marca, p.model AS modelo, p.name AS produto,
                        p.price_brl AS preco_original, ROUND(p.price_brl * 0.95, 2) AS preco_pix_a_vista,
                        p.stock_quantity AS estoque, c.name AS categoria, p.specs AS especificacoes_tecnicas, p.description AS descricao
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.category_id
                    WHERE p.product_id IN ({placeholders}) {price_condition}
                    ORDER BY p.price_brl ASC
                """
                cursor.execute(sql, params)
                rows = cursor.fetchall()

                if rows:
                    columns = [desc[0] for desc in cursor.description] if cursor.description else []
                    results = [dict(zip(columns, r)) for r in rows]
                    conn.close()
                    agent_log(f"[FALLBACK_OK] rows={len(results)} query={query_text!r}")
                    return json.dumps(results, ensure_ascii=False, indent=2)





        cursor.execute("PRAGMA table_info(products);")
        p_cols = {r[1] for r in cursor.fetchall()}
        cursor.execute("PRAGMA table_info(categories);")
        c_cols = {r[1] for r in cursor.fetchall()}

        searchable = []
        for col in ("name", "name_clean", "brand", "brand_clean",
                    "instrument", "instrument_clean", "description", "description_clean"):
            if col in p_cols:
                searchable.append(f"p.{col}")
        for col in ("name", "category_name_clean"):
            if col in c_cols:
                searchable.append(f"c.{col}")

        base_conditions = [
            "p.stock_quantity > 0",
            "p.price_brl IS NOT NULL",
            "p.price_brl > 0",
            "(p.status IS NULL OR p.status = 'active')",
        ]
        params = []

        if max_price is not None:
            base_conditions.append("p.price_brl <= ?")
            params.append(max_price)

        if raw_words and searchable:
            text_conditions = []
            for word in raw_words:
                stem = word
                if stem.endswith("oes") or stem.endswith("aes"):
                    stem = stem[:-3]
                elif stem.endswith("es"):
                    stem = stem[:-2]
                elif stem.endswith("s"):
                    stem = stem[:-1]
                if len(stem) < 3:
                    stem = word
                like_val = f"%{stem}%"

                ors = " OR ".join(f"{col} LIKE ?" for col in searchable)
                text_conditions.append(f"({ors})")

                for _ in range(len(searchable)):
                    params.append(like_val)

            base_conditions.append(f"({' OR '.join(text_conditions)})")

        sql = f"""
            SELECT 
                p.product_id, p.brand AS marca, p.model AS modelo, p.name AS produto,
                p.price_brl AS preco_original, ROUND(p.price_brl * 0.95, 2) AS preco_pix_a_vista,
                p.stock_quantity AS estoque, c.name AS categoria, p.specs AS especificacoes_tecnicas, p.description AS descricao
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE {' AND '.join(base_conditions)}
            ORDER BY 
                CASE WHEN p.name_clean LIKE ? OR p.model_clean LIKE ? THEN 0 ELSE 1 END ASC,
                p.price_brl ASC
            LIMIT 8
        """

        exact_match_val = f"%{' '.join(raw_words)}%" if raw_words else f"%{clean_q.strip()}%"
        params.append(exact_match_val)
        params.append(exact_match_val)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if rows:
            results = [dict(zip(columns, r)) for r in rows]
            payload = json.dumps(results, ensure_ascii=False, indent=2)
            agent_log(f"[FALLBACK_OK] rows={len(results)} query={query_text!r}")
            return payload

        agent_log(f"[FALLBACK_EMPTY] query={query_text!r} max_price={max_price} raw_words={raw_words}")

    except Exception as e:
        agent_log(f"[FALLBACK_ERROR] {e!r}")

    return ""

def lookup_order_info(user_msg: str) -> str:
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_msg)
    order_id_match = re.search(
        r'(?:pedido|order|rastreio|tracking|compra|encomenda|nota\s*fiscal|nf)\s*[:#]?\s*(\d{1,8})',
        user_msg,
        re.IGNORECASE,
    )

    email = email_match.group(0).strip().lower() if email_match else None
    order_id = order_id_match.group(1) if order_id_match else None

    if not email and not order_id:
        return ""

    try:
        conn = sq3.connect(DB_PATH)
        cursor = conn.cursor()

        base_query = """
            SELECT 
                o.order_id,
                o.order_date,
                o.status,
                o.total_brl,
                o.payment_method,
                o.tracking_code,
                o.estimated_delivery,
                c.name AS customer_name,
                c.email AS customer_email,
                GROUP_CONCAT(p.name || ' (Qtd: ' || oi.quantity || ')', '; ') AS itens
            FROM orders o
            JOIN customers c ON o.customer_id = c.customer_id
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            LEFT JOIN products p ON oi.product_id = p.product_id
        """

        if order_id:
            query = base_query + " WHERE o.order_id = ? GROUP BY o.order_id"
            cursor.execute(query, (order_id,))
        else:
            query = base_query + " WHERE LOWER(c.email) = ? GROUP BY o.order_id ORDER BY o.order_date DESC LIMIT 3"
            cursor.execute(query, (email,))

        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        conn.close()

        if not rows:
            return ""

        results = [dict(zip(columns, r)) for r in rows]
        return f"\n[Dados de Pedidos Localizados no Sistema]:\n{json.dumps(results, ensure_ascii=False, indent=2)}\n"

    except Exception as e:
        return ""


def get_db_schema() -> str:
    conn = sq3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    schema_info = []
    for t in tables:
        table_name = t[0]
        cursor.execute(f"PRAGMA table_info({table_name});")
        cols = [f"{col[1]} ({col[2]})" for col in cursor.fetchall()]
        schema_info.append(f"Tabela '{table_name}': " + ", ".join(cols))
    conn.close()
    return "\n".join(schema_info)


class LocalDeepSeek:
    def __init__(
        self,
        model_name: str = "deepseek-r1:8b",
        base_url: str = "http://localhost:11434",
    ):
        self.model_name = model_name
        self.base_url = base_url

    def is_available(self) -> bool:
        try:
            res = req.get(f'{self.base_url}/api/tags', timeout=2)
            return res.status_code == 200
        except Exception:
            return False

    def gen(self, prompt: str, system_prompt: str = "", max_tokens: int = 5000) -> str:
        payload = {
            'model': self.model_name,
            'prompt': prompt,
            'system': system_prompt,
            'stream': False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.8,
                "num_predict": max_tokens,
                "num_ctx": 4096
            }
        }

        try:
            res = req.post(f'{self.base_url}/api/generate', json=payload, timeout=60)
            if res.status_code == 200:
                data = res.json()
                response_text = data.get("response", "")
                response_text = re.sub(r"<think>.*?</think>", "", response_text, flags=re.DOTALL).strip()
                return response_text
            else:
                return f"⚠️ Erro no Ollama ({res.status_code}): {res.text}"
        except req.exceptions.ConnectionError:
            return (
                "⚠️ Ollama não detectado em http://localhost:11434.\n\n"
                "Para rodar o DeepSeek localmente:\n"
                "1. Certifique-se de que o Ollama está rodando (`ollama serve`).\n"
                "2. Baixe o modelo: `ollama run deepseek-r1:14b` ou `ollama run deepseek-r1:8b`."
            )
        except Exception as e:
            return f"Erro ao contatar o DeepSeek local: {str(e)}"


