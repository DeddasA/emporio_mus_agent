import os
import re
import json
import pandas as pd
from typing import List, Dict,Any, Tuple
import requests as req
import sqlite3 as sq3
from flask import Flask, render_template, request,jsonify




Db = ("emporio_musica.db")

def csv_to_db():
    conn = sq3.connect(Db)
    cursos = conn.cursor()

    mapping_csvs = {"customers": "data/customers.csv",
                    "categories":"data/categories.csv",
                    "order_items":"data/order_items.csv",
                    "products":"data/products.csv",
                    "orders":"data/orders.csv",
                    "promotions":"data/promotions.csv"}


    loaded_tables = []
    for table, file in mapping_csvs.items():
        if os.path.exists(file):
            try:
                df = pd.read_csv(file)
                df.columns = [col.strip().lower().replace(" ","_") for col in df.columns]
                df.to_sql(table, conn, if_exists="replace",index=False)
                loaded_tables.append(f"{file} ({len(df)}) rows")
            except Exception as e:
                print(f"Error loading {file}: {e}")
        else:
            print(f'{file} not found locally. Verifying table: {table}')

    conn.commit()
    conn.close()
    return  loaded_tables


class PolicyBase:
    def __init__(self, pdf_path: str="data/policy.pdf"):
        self.pdf_path = pdf_path
        self.chunks : list[Dict[str, Any]] = []
        self._load_and_chunk()

    def _extract_pdf_text(self) -> str:
        text = ""
        try:
            import pypdf
            reader = pypdf.PdfReader(self.pdf_path)
            for item, page in enumerate(reader.pages):
                extracted = page.extract_text()
                if extracted:
                    text += f"\n---- Página {item+1} ----\n" + extracted
        except Exception:

            text = """
                            MANUAL DE POLÍTICAS E PROCEDIMENTOS - EMPÓRIO DA MÚSICA
                            Endereço: Rua 14 de Maio, 3200 Centro, Campo Grande - MS, 79202-333
                            Telefone / WhatsApp: (67) 3341-4444 / (67) 3321-4500.
                            Horário de Funcionamento: Segunda a Sexta 09:00 às 18:00, Sábado 09:00 às 13:00. Domingos e Feriados: Fechado.

                            Catálogo e Escopo:
                            Trabalhamos exclusivamente com instrumentos musicais (guitarras, baixos, violões, baterias, teclados, sopro, cordas orquestrais e ukuleles).
                            NÃO comercializamos acessórios como cordas, palhetas, cabos, cases, pedais ou amplificadores.

                            Formas de Pagamento e Parcelamento:
                            - PIX: Pagamento à vista com 5% de desconto sobre o preço de tabela (não cumulativo com promoções).
                            - Cartão de Débito: À vista.
                            - Boleto Bancário: À vista, compensação em até 3 dias úteis.
                            - Cartão de Crédito: Até 12x sem juros (até 3x sem valor mínimo exceto abaixo de R$ 50; 4x a 6x parcela mínima R$ 80; 7x a 12x parcela mínima R$ 100).
                            - Combinação de pagamentos (PIX + cartão): permitida para compras acima de R$ 2.000,00.

                            Trocas e Devoluções:
                            - Direito de Arrependimento (Online): Até 7 dias corridos após recebimento. Embalagem original, sem sinais de uso. Frete de devolução por conta da loja. Reembolso em até 10 dias úteis.
                            - Defeito de fabricação: Até 30 dias corridos diretamente com a loja. Após 30 dias, acionar fabricante.
                            - Preferência (cor, modelo): Até 7 dias corridos, produto em perfeito estado.
                            - Itens não elegíveis para troca: Instrumentos com personalização/regulagem sob encomenda, itens em liquidação "venda final", boquilhas de instrumentos de sopro (higiene).

                            Frete e Entregas:
                            - Grande Campo Grande: Frete grátis acima de R$ 500,00. Abaixo de R$ 500,00 taxa fixa de R$ 35,00. Prazo: 1 a 3 dias úteis por motoboy próprio.
                            - Outras cidades: PAC (5-12 dias úteis), SEDEX (2-5 dias úteis), Jadlog (3-8 dias úteis). Todos incluem seguro contra extravio e avaria.
                            - Rastreamento: Formato padrão BR + 9 caracteres + BR (ex: BR4K7M2X9P1BR).

                            Garantia:
                            - Garantia Legal: 90 dias contra defeitos de fabricação (CDC).
                            - Garantia de Fabricante: 6 meses a 2 anos dependendo da marca.
                            - Não cobre desgaste natural (cordas, trastes, feltros), mau uso, umidade extrema ou reparo não autorizado.

                            Promoções:
                            - Aniversário (Agosto: 10% a 25%), Black Friday (Novembro: 15% a 30%), Volta às Aulas (Fevereiro), Semana do Músico (22 de Novembro).
                            - Descontos não são cumulativos. Preços promocionais não ganham 5% do PIX adicional.
                            """
        return text

    def _load_and_chunk(self):
        full_text = self._extract_pdf_text()
        paragraphs = full_text.split("\n\n")
        current_chunk: str = ""
        for p in paragraphs:
            clean_p = p.strip()
            if not clean_p:
                continue
            if len(current_chunk) + len(clean_p) < 600:
                current_chunk += "\n" + clean_p
            else:
                self.chunks.append(current_chunk.strip())
        if current_chunk:
            self.chunks.append(current_chunk.strip())

    def search(self, query: str, top_k: int = 3) -> List[str]:
        query_words = set(re.findall(r"\w+", query.lower()))
        scores = []
        for chunk in self.chunks:
            chunk_words = set(re.findall(r"\w+", query.lower()))
            overlap = len(query_words.intersection(chunk_words))
            for word in query_words:
                if len(word) > 3 and word in chunk.lower():
                    overlap += 1
            scores.append((overlap,chunk))
        scores.sort(key=lambda x: [0], reverse=True)
        return [chunk for score, chunk in scores [:top_k] if score > 0] or self.chunks[:2]




def query_database(sql_query: str) -> str:
    prohibited = ["DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "ATTACH"]
    for keyword in prohibited:
        if re.search(rf"\b{keyword}\b", sql_query, re.IGNORECASE):
            return "Erro: Apenas consultas de leitura (SELECT) são permitidas."

    try:
        conn = sq3.connect(Db)
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if not rows:
            return "Nenhum resultado encontrado no banco de dados."

        rows = rows[:10]
        results =  [dict(zip(columns,rows)) for row in rows]
        return  json.dumps(results,ensure_ascii=False, indent=1)
    except Exception as e:
        return f"Erro ao executar consulta SQL: {str(e)}"


def get_db_schema() -> str:
    conn = sq3.connect(Db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables  = cursor.fetchall()
    schema_info = []
    for t in tables:
        table_name= t[0]
        cursor.execute(f"Pragma table_info({table_name});")
        cols = [f"{col[1]} ({col[2]})" for col in cursor.fetchall()]
        schema_info.append(f'Tabela{table_name}: ' "+".join(cols))
    conn.close()
    return "\n".join(schema_info)



class LocalDeepSeek:
    def __init__(self , model_name: str= "deepseek-r1:8b", base_url: str = "http//loaclhost:11434"):
        self.model_name = model_name
        self.base_url = base_url
    def is_available(self) -> bool:
        try:
            res = req.get(f'{self.base_url}/api/tags', timeout=2)
            return res.status_code == 200
        except Exception as e:
            print(f"Error -- {e}")
            return  False


    def gen(self, prompt:str, system_prompt: str = "") -> str:
        payload = { 'model': self.model_name,
                    'prompt': prompt,
                    'system': system_prompt,
                    'stream': False,
                    "options": {"temperature":0.35,
                                'top_p':0.95}
                    }

        try:
            res = req.post(f'{self.base_url}/api/genarate',json=payload, timeout=45)
            if res.status_code == 200:
                data = res.json()
                response_text = data.get("response","")
                response_text = re.sub("<think>.*?</think>","", response_text, flags=re.DOTALL).strip()
                return  response_text
        except req.exceptions.ConnectionError:
            return      \
                ( "⚠️ Ollama não detectado em http://localhost:11434.\n\n"
                "Para rodar o DeepSeek localmente:\n"
                "1. Instale o Ollama: https://ollama.ai\n"
                "2. No terminal: `ollama run deepseek-r1:8b` "
                  "(ou `ollama run deepseek-coder:6.7b`)\n"
                "3. Recarregue a mensagem."
            )
        except Exception as e:
            return f"Erro ao contatar o DeepSeek local: {str(e)}"


class MusicStoreAgent:
    def __init__(self, kb: PolicyBase, llm: LocalDeepSeek):
       self.kb = kb
       self.llm= llm

    def run(self, user_msg: str) -> Dict[str,Any]:
        trace = []
        msg_lower = user_msg.lower()
        policy_snippets = self.kb.search(user_msg, top_k=3)
        context_docs  = "\n----\n".join(policy_snippets)
        trace.append(f"🔎 [RAG]: Recuperados {len(policy_snippets)} trechos das Políticas da Loja.")

        db_context = ""
        db_keywords = ["preço", "valor", "estoque", "pedido", "status", "cliente", "produto", "guitarra", "violão",
                       "promoção", "desconto", "comprar", "tem"]
        needs_db = any(k in msg_lower for k in db_keywords)

        if needs_db:
            schema = get_db_schema()
            sql_router_prompt = f"""
                    Você é um especialista em SQL para o banco de dados da 'Empório da Música'.
                    Esquema do Banco de Dados:
                    {schema}

                    Pergunta do usuário: "{user_msg}"

                    Instruções:
                    - Se a pergunta precisar consultar produtos, clientes, promoções, pedidos ou estoque, escreva APENAS uma query SQL válida para SQLite.
                    - Exemplo: SELECT nome, preco, estoque FROM products WHERE nome LIKE '%violao%' LIMIT 5;
                    - Se NÃO for necessária consulta ao banco, responda apenas 'NONE'.
                    - NÃO adicione formatação markdown ou explicações.
                    """
            generated_sql = self.llm.generate(sql_router_prompt).strip()
            # Clean possible markdown wrap
            clean_sql = re.sub(r"```(sql)?", "", generated_sql).replace("```", "").strip()

            if clean_sql and "SELECT" in clean_sql.upper() and "NONE" not in clean_sql.upper():
                trace.append(f"💾 [SQL Executado]: `{clean_sql}`")
                sql_result = query_database(clean_sql)
                db_context = f"\nResultado do Banco de Dados:\n{sql_result}\n"
                trace.append(f"📊 [DB Resposta]: {len(sql_result)} caracteres retornados.")
            else:
                trace.append("ℹ️ [DB]: Nenhuma consulta SQL necessária.")

            # Step 3: Final Synthesis Prompt

        system_prompt = """
                    Você é o assistente virtual inteligente da 'Empório da Música', fundada em 2008 em Campo Grande - MS.
                    Seu tom de voz é amigável, acolhedor e profissional, como um músico atendendo outro músico.

                    Regras Críticas:
                    1. Escopo de Produtos: A Empório da Música vende EXCLUSIVAMENTE instrumentos musicais. NÃO vendemos acessórios (cordas, palhetas, cabos, cases, pedais ou amplificadores). Se o cliente pedir acessórios, explique com educação e sugira lojas parceiras.
                    2. Formas de Pagamento: PIX tem 5% de desconto à vista sobre o preço de tabela (não cumulativo com promoções). Parcelamento em até 12x sem juros (parcela mínima de R$ 100 para 7-12x). Combinação de formas (PIX + Cartão) só acima de R$ 2.000.
                    3. Frete: Grande Campo Grande tem frete grátis acima de R$ 500 (abaixo é taxa fixa R$ 35). Outras cidades: PAC, Sedex e Jadlog com seguro.
                    4. Trocas: Arrependimento online em até 7 dias corridos. Defeito de fabricação com a loja em até 30 dias (garantia legal de 90 dias).
                    5. Preços e Estoque: Use SEMPRE os dados do banco fornecidos no contexto. Nunca invente estoques ou valores.
                    """

        final_prompt = f"""
                    Contexto das Políticas da Loja:
                    {context_docs}

                    {db_context}

                    Histórico / Mensagem do Cliente: "{user_msg}"

                    Responda ao cliente com precisão, gentileza e clareza em Português do Brasil:
                    """
        response_text = self.llm.generate(final_prompt, system_prompt=system_prompt)
        return {
            "response": response_text,
            "trace": trace,
            "policies_used": policy_snippets
        }

# ---------------------------------------------------




if __name__ == '__main__':
    app = Flask(__name__)

    # Initialize components
    print("Iniciando banco de dados a partir dos CSVs...")
    csv_to_db()
    knowledge_base = PolicyBase()
    deepseek_client = LocalDeepSeek()
    agent = MusicStoreAgent(knowledge_base, deepseek_client)



















