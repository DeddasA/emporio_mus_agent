import os
import re
import json

from typing import List, Dict, Any, Tuple
import requests as req
import sqlite3 as sq3
from db_schema import normalize_text
from pdf_loader import PolicyBase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "emporio_musica.db")
DATA_DIR = os.path.join(BASE_DIR, "data")
PDF_DEFAULT_PATH = os.path.join(BASE_DIR, "políticas_da_loja.pdf")
if not os.path.exists(PDF_DEFAULT_PATH):
    PDF_DEFAULT_PATH = os.path.join(DATA_DIR, "políticas_da_loja.pdf")




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

        rows = rows[:4]
        results = [dict(zip(columns, row)) for row in rows]
        return json.dumps(results, ensure_ascii=False, indent=1)
    except Exception as e:
        return f"Erro ao executar consulta SQL: {str(e)}"


def search_products_fallback(query_text: str) -> str:

    clean_q = normalize_text(query_text)


    max_price = None
    price_match = re.search(r'(?:ate|abaixo\s+de|menos\s+de|maximo\s+de)\s*(?:r\$\s*)?(\d+(?:[.,]\d+)?)', clean_q)
    if price_match:
        try:
            max_price = float(price_match.group(1).replace(',', '.'))
        except ValueError:
            max_price = None


    stop_words = {
        "tem", "qual", "quais", "preco", "preço", "valor", "estoque", "voces", "vocês",
        "sobre", "gostaria", "favor", "disponivel", "disponiveis", "opcoes", "opções",
        "custando", "custa", "reais", "ate", "abaixo", "menos", "para", "com", "uma", "uns"
    }
    raw_words = [w for w in re.findall(r"\w+", clean_q) if len(w) > 2 and w not in stop_words]

    try:
        conn = sq3.connect(DB_PATH)
        cursor = conn.cursor()


        base_conditions = [
            "p.stock_quantity > 0",
            "p.price_brl IS NOT NULL",
            "p.price_brl > 0"
        ]
        params = []

        if max_price is not None:
            base_conditions.append("p.price_brl <= ?")
            params.append(max_price)

        # Monta filtros de texto se houver palavras-chave
        if raw_words:
            text_conditions = []
            for word in raw_words:
                stem = word[:-2] if word.endswith("es") else (word[:-1] if word.endswith("s") else word)
                like_val = f"%{stem}%"
                text_conditions.append("""(
                    p.name_clean LIKE ? OR 
                    p.brand_clean LIKE ? OR 
                    p.instrument_clean LIKE ? OR 
                    p.description_clean LIKE ? OR 
                    c.category_name_clean LIKE ?
                )""")
                params.extend([like_val, like_val, like_val, like_val, like_val])

            base_conditions.append(f"({' OR '.join(text_conditions)})")

        sql = f"""
            SELECT 
                p.product_id,
                p.brand AS marca,
                p.model AS modelo,
                p.name AS produto,
                p.price_brl AS preco_original,
                ROUND(p.price_brl * 0.95, 2) AS preco_pix_a_vista,
                p.stock_quantity AS estoque,
                c.name AS categoria,
                p.specs AS especificacoes_tecnicas,
                p.description AS descricao
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE {' AND '.join(base_conditions)}
            ORDER BY p.price_brl ASC
            LIMIT 4
        """
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if rows:
            results = [dict(zip(columns, r)) for r in rows]
            return json.dumps(results, ensure_ascii=False, indent=2)

    except Exception as e:
        print(f"Erro na busca de produtos: {e}")

    return ""

def lookup_order_info(user_msg: str) -> str:
    """Extrai e-mail ou código de pedido para localizar o rastreio e dados de compra."""
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_msg)
    order_id_match = re.search(r'(?:pedido|order|id|número|numero|#)\s*[:#]?\s*(\d+)', user_msg, re.IGNORECASE)

    email = email_match.group(0).strip().lower() if email_match else None
    order_id = order_id_match.group(1) if order_id_match else None

    if not order_id and not email:
        raw_digits = re.findall(r'\b\d+\b', user_msg)
        if len(raw_digits) == 1 and len(raw_digits[0]) <= 6:
            order_id = raw_digits[0]

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
            identificador = f"Pedido #{order_id}" if order_id else f"E-mail {email}"
            return f"\n[Consulta de Pedidos]: Nenhum pedido encontrado para o identificador informado ({identificador}).\n"

        results = [dict(zip(columns, r)) for r in rows]
        return f"\n[Dados de Pedidos Localizados no Sistema]:\n{json.dumps(results, ensure_ascii=False, indent=2)}\n"

    except Exception as e:
        return f"\n[Erro ao consultar pedido]: {str(e)}\n"


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

    def gen(self, prompt: str, system_prompt:
    str = "", max_tokens: int = 5000) -> str:
        payload = {
            'model': self.model_name,
            'prompt': prompt,
            'system': system_prompt,
            'stream': False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.8,
                "num_predict": max_tokens,
                "num_ctx": 2048
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


class MusicStoreAgent:
    def __init__(self, kb: PolicyBase, llm: LocalDeepSeek):
        self.kb = kb
        self.llm = llm

    def run(self, user_msg: str) -> Dict[str, Any]:
        trace = []
        msg_lower = user_msg.lower()


        sql_injection_keywords = ["drop table", "union select",
                                  "insert into", "delete from",
                                  "update products", "alter table"]
        if any(bad in msg_lower for bad in sql_injection_keywords):
            return {
                "response": "⚠️ Comando não permitido. O sistema aceita "
                            "apenas consultas em linguagem natural e termos musicais.",
                "trace": ["⛔ [Segurança]: Tentativa de injeção SQL bloqueada."],
                "policies_used": []
            }


        policy_snippets = self.kb.search(user_msg, top_k=3)
        context_docs = "\n----\n".join(policy_snippets)
        trace.append(f"🔎 [RAG]: {len(policy_snippets)} seções completas de políticas injetadas no contexto.")

        # 2. Busca Direta de Pedidos por Email ou Order ID
        db_context = ""
        order_direct_info = lookup_order_info(user_msg)

        if order_direct_info:
            db_context = order_direct_info
            trace.append("📦 [Pedidos]: Informações do pedido/cliente recuperadas com sucesso.")
        else:
            # 3. Consulta ao Catálogo de Produtos e Estoque com Detalhes Ricos
            db_keywords = [
                "preço", "preco", "valor", "estoque", "pedido", "status",
                "cliente", "produto", "produtos", "guitarra", "violão", "violao",
                "baixo", "bateria", "teclado", "sopro", "ukulele", "promoção", "promocao",
                "desconto", "comprar", "tem", "qual", "quais", "marca", "modelo", "especificacao", "especificação", "descricao", "descrição"
            ]
            needs_db = any(k in msg_lower for k in db_keywords)

            user_msg_clean = normalize_text(user_msg)
            if needs_db:


                schema = get_db_schema()

                sql_router_prompt = f"""
                Você é um gerador estrito de SQL SQLite para a 'Empório da Música'.
                Esquema do Banco de Dados:
                {schema}

                Pergunta do usuário: "{user_msg_clean}"

                Regras de Query:
                1. Sempre selecione:
                   SELECT p.product_id, p.brand, p.model,
                    p.name, p.price_brl, p.stock_quantity, 
                    c.name as categoria, p.specs, p.description
                   FROM products p
                   LEFT JOIN categories c ON p.category_id = c.category_id
                2. Filtros de Instrumento:
                   - Violão: (p.instrument_clean
                    LIKE '%violao%' OR p.description_clean LIKE '%violao%' OR c.category_name_clean LIKE '%violao%')
                   - Guitarra: (p.instrument_clean
                    LIKE '%guitarra%' OR c.category_name_clean LIKE '%guitarra%')
                3. Filtros Numéricos e de Estoque:
                   - "até R$ X" ou "abaixo de X": AND p.price_brl <= X
                   - "acima de R$ X": AND p.price_brl >= X
                   - "disponíveis" ou "em estoque": AND p.stock_quantity > 0
                4. Limite: Utilize LIMIT 15 para não truncar resultados em buscas por faixa de preço.
                5. Se for pergunta institucional (horários, trocas, garantia, frete), responda apenas: NONE

                Formato de Saída Obrigatório:
                - Responda APENAS a query SQL pura a começar por SELECT 
                ou a palavra NONE. Sem markdown ou explicações.
                """
                generated_sql = self.llm.gen(sql_router_prompt).strip()


                sql_match = re.search(r'(SELECT\b[\s\S]+?)(?:;|\$|```)', generated_sql, re.IGNORECASE)
                clean_sql = sql_match.group(1).strip() if sql_match else ""


                if clean_sql and "SELECT" in clean_sql.upper() and "NONE" not in clean_sql.upper():
                    trace.append(f"💾 [SQL Executado]: `{clean_sql}`")
                    sql_result = query_database(clean_sql)
                    if "Nenhum resultado" not in sql_result and "Erro" not in sql_result:
                        db_context = f"\nResultado do Banco de Dados:\n{sql_result}\n"
                        trace.append(f"📊 [DB Resposta]: {len(sql_result)} caracteres retornados.")

                if not db_context:
                    direct_products = search_products_fallback(user_msg)
                    if direct_products:
                        db_context = f"\nResultado do Banco de Dados:\n{direct_products}\n"
                        trace.append("🔍 [DB Fallback]: Produtos recuperados por busca direta de texto.")
                    else:

                        return {
                            "response": "Desculpe, não encontrei nenhum modelo ou instrumento correspondente no catálogo da nossa loja no momento. Trabalhamos exclusivamente com os instrumentos disponíveis em estoque.",
                            "trace": trace + [
                                "🛑 [Anti-Alucinação]: Nenhum produto retornado pelo banco. Resposta padronizada executada sem chamar o LLM."],
                            "policies_used": policy_snippets
                        }
        system_prompt = """
        Você é o assistente virtual da 'Empório da Música' (Campo Grande - MS).

        REGRA DE FECHAMENTO ABSOLUTO (ANTI-ALUCINAÇÃO):
        1. Você SÓ PODE listar os produtos que vieram EXPLICITAMENTE dentro da lista JSON do 'Resultado do Banco de Dados'.
        2. É ESTRITAMENTE PROIBIDO inventar, adicionar ou sugerir produtos extras do seu conhecimento que não estejam na lista do banco (como Cort, Epiphone, Fender, etc.).
        3. Se a lista do banco tiver 4 itens, liste APENAS esses 4 itens. Não adicione o 5º item.
        4. Para cada produto, mostre:
           - Nome / Modelo
           - Marca
           - Preço à vista (R$) com 5% de desconto no PIX
           - Quantidade em estoque
           - Descrição breve constante no banco
        5. Venda exclusivamente instrumentos musicais; não comercializamos acessórios.
        """
        final_prompt = f"""
Contexto das Políticas da Loja (Extraído do PDF Oficial):
{context_docs}

{db_context}

Pergunta / Solicitação do Cliente: "{user_msg}"

Apresente uma resposta completa, rica em detalhes e formatada em Português do Brasil:
"""
        response_text = self.llm.gen(final_prompt, system_prompt=system_prompt)

        return {
            "response": response_text,
            "trace": trace,
            "policies_used": policy_snippets
        }