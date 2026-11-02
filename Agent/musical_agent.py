import os
import re
import json
import logging
import datetime as dt
from typing import List, Dict, Any
from schema.db_schema import normalize_text
from LLm.llm import LocalDeepSeek,lookup_order_info, search_products_fallback,get_db_schema,query_database
from RAG.pdf_injector.pdf_loader import PolicyBase
from Config.config import LOG_PATH_AGENT


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(ROOT_DIR, "Instance", "emporio_musica.db")







music_llm_agent = logging.getLogger("music_agent")
music_llm_agent.setLevel(logging.INFO)
if not music_llm_agent.handlers:
    _fh = logging.FileHandler(LOG_PATH_AGENT, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] - %(message)s"))
    music_llm_agent.addHandler(_fh)
    music_llm_agent.propagate = False

def agent_log(message):
    print(message, flush=True)
    music_llm_agent.info(message)
    try:
        with open(LOG_PATH_AGENT, "a", encoding="utf-8") as f:
            timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp} - [RAW_BACKUP]: {message}\n")
    except Exception as e:
        print(f"[agent_log] failed to write log: {e!r}", flush=True)


def format_brl(value):
    """Formata um float para o padrão de moeda brasileiro (R$ 1.234,56)"""
    if value is None or value == "":
        return "Indisponível"
    try:
        # Formata com vírgula para milhar e ponto para decimal
        val = f"{float(value):,.2f}"
        # Inverte para o padrão brasileiro
        val = val.replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {val}"
    except (ValueError, TypeError):
        return str(value)


class MusicStoreAgent:
    def __init__(self, kb: PolicyBase, llm: LocalDeepSeek):
        self.kb = kb
        self.llm = llm

    _PRODUCT_STEMS = [
        "viol", "guitarr", "baix", "bateri", "teclad", "sintetiz", "sopro",
        "ukulel", "cavaquinh", "viola", "contrabaix",
    ]

    _INSTITUTIONAL_KEYWORDS = [
        "horário", "horario", "funcionamento", "troca", "trocas", "devolução", "devolucao",
        "garantia", "frete", "entrega", "formas de pagamento", "endereço", "endereco",
        "telefone", "whatsapp", "cnpj", "localização", "localizacao", "onde fica",
        "como chegar", "parcelar", "cartão", "cartao", "pix", "boleto", "corda", "cordas",
        "palheta", "palhetas", "cabo", "cabos", "case", "cases", "pedal", "pedais",
        "amplificador", "amplificadores", "arrependi", "arrependo", "razão social", 'nome fantasia',
        "quebrou", "quebrado", "caiu", "defeito", "conserto", "reparo", "trincou", "estragou", "arrumar"
    ]

    _KNOWN_BRANDS = {
        "fender", "gibson", "cort", "epiphone", "yamaha", "ibanez", "tagima", "squier",
        "martin", "taylor", "roland", "strinberg", "seizi", "phx", "staner", "nzs",
        "memphis", "hofner", "rickenbacker", "prs", "jackson", "esp", "ltd", "schecter",
        "gretsch", "danelectro", "seagull", "godin", "kala", "ohana", "kalani", "shelby",
        "rozini", "giannini", "crafter", "takamine", "music man", "musicman", "pearl",
        "tama", "korg", "nord", "almeida",
    }

    _FORBIDDEN_BRANDS = {
        "fender", "gibson", "epiphone", "ibanez", "squier", "cort",
        "prs", "jackson", "esp", "ltd", "schecter", "gretsch", "danelectro"
    }

    _FALSE_NEGATIVE_PATTERNS = [
        r"não\s+(?:há|encontrei|temos|possuímos|tenho|está\s+dispon|estão\s+dispon)",
        r"nenhum\s+(?:violão|guitarra|baixo|bateria|teclado|ukulele|produto|item|modelo|instrumento|resultado)",
        r"não\s+encontrei", r"infelizmente\s+não", r"não\s+possui",
        r"não\s+estão\s+dispon", r"não\s+está\s+dispon", r"sem\s+produtos", r"nada\s+dispon",
        r"não\s+(?:está|consta|aparece)\s+(?:na|nessa|nesta)\s+lista", r"não\s+encontrei\s+o\s+produto",
    ]

    def _build_safe_response(self, db_rows_for_validation: List[Dict[str, Any]]) -> str:
        if not db_rows_for_validation:
            return "Nenhum produto encontrado no momento."

        safe_lines = ["🛍️ **Aqui estão os instrumentos disponíveis no nosso catálogo:**\n"]

        for i, row in enumerate(db_rows_for_validation[:8], start=1):
            nome = row.get("produto") or row.get("name") or row.get("modelo") or "Instrumento"
            marca = row.get("marca") or row.get("brand") or "Não informada"

            preco_original = row.get("preco_original") or row.get("price_brl") or 0
            preco_pix = row.get("preco_pix_a_vista")
            if preco_pix is None and preco_original:
                try:
                    preco_pix = round(float(preco_original) * 0.95, 2)
                except (ValueError, TypeError):
                    preco_pix = preco_original

            estoque = row.get("estoque") or row.get("stock_quantity") or 0
            desc = row.get("descricao") or row.get("description") or ""

            safe_lines.append(
                f"**{i}. {nome}**\n"
                f"   - 🏷️ **Marca:** {marca}\n"
                f"   - 💰 **Preço no PIX:** {format_brl(preco_pix)} *(com 5% de desconto)*\n"
                f"   - 📦 **Estoque:** {estoque} unidades\n"
                f"   - 📝 **Sobre:** {desc}\n"
            )

        return "\n".join(safe_lines)

    def run(self, user_msg: str) -> Dict[str, Any]:
        trace = []
        msg_lower = user_msg.lower()
        agent_log(f"[RUN_START] user_msg={user_msg!r}")

        # 1. Bloqueio de SQL Injection

        if any(bad in msg_lower for bad in
               ["drop table", "union select", "insert into", "delete from", "update products", "alter table"]):
            return {"response": "⚠️ Comando não permitido.", "trace": ["⛔ [Segurança]: Injeção SQL bloqueada."],
                    "policies_used": []}

        # 2. Busca RAG de Políticas

        policy_snippets = self.kb.search(user_msg, top_k=3)
        context_docs = "\n----\n".join(policy_snippets)

        db_context = ""
        db_rows_for_validation = []

        # 3. Detecta Intenções (Defeito e Institucional) no início para evitar NameError

        user_msg_clean = normalize_text(user_msg)
        has_product_stem = any(stem in user_msg_clean for stem in self._PRODUCT_STEMS)
        has_institutional = any(k in user_msg_clean for k in self._INSTITUTIONAL_KEYWORDS)
        has_defect_intent = any(k in user_msg_clean for k in
                                ["quebrou", "quebrado", "caiu", "defeito", "conserto", "reparo", "trincou",
                                 "estragou", "arrumar"])


    # fallback para marcas inexistentes.

        user_msg_clean_for_brand = normalize_text(user_msg)
        forbidden_found = [brand for brand in self._FORBIDDEN_BRANDS if brand in user_msg_clean_for_brand]
        if forbidden_found and not db_rows_for_validation:
            agent_log(f"[FORBIDDEN_BRAND] Usuário pediu marca não vendida: {forbidden_found}")
            return {
                "response": f"Poxa, infelizmente não trabalhamos com a marca **{forbidden_found[0].title()}**. "
                            f"Nossa loja é especializada em marcas como Yamaha, Tagima, Martin, Takamine, Rozini, Giannini, entre outras. "
                            f"Posso te mostrar opções de violões ou guitarras de outras marcas que temos em estoque?",
                "trace": trace + [f"⛔ [Forbidden Brand]: Marca {forbidden_found[0]} bloqueada."],
                "policies_used": policy_snippets
            }




        # 4. Busca de Pedidos
        order_direct_info = lookup_order_info(user_msg)

        if order_direct_info:
            db_context = order_direct_info
            trace.append("📦 [Pedidos]: Informações recuperadas.")
            db_rows_for_validation = [{"order_found": True}]
        else:
            if has_defect_intent or (has_institutional and not has_product_stem):
                agent_log("[ROUTER] Pergunta sobre defeito/garantia detectada. Pulando banco de produtos.")
                trace.append("🏛️ [Roteador]: Pergunta de defeito/garantia detectada. Usando apenas políticas.")
            else:
                direct_products = search_products_fallback(user_msg)
                if direct_products:
                    try:
                        db_rows_for_validation = json.loads(direct_products)
                    except Exception:
                        db_rows_for_validation = []
                    db_context = f"\nResultado do Banco de Dados:\n{direct_products}\n"
                    trace.append(f"🔍 [Fallback]: {len(db_rows_for_validation)} produtos encontrados.")
                else:
                    trace.append("🔍 [Fallback]: Nenhum produto encontrado por busca direta.")

                if not db_context and not has_institutional and not has_defect_intent:
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
                    2. Filtros de Texto (MUITO IMPORTANTE):
                       - Se o usuário citar uma MARCA ou MODELO ESPECÍFICO (ex: Martin, Yamaha, Tagima, F310, D-28), use:
                         AND (p.name_clean LIKE '%[palavra]%' OR p.brand_clean LIKE '%[palavra]%' OR p.model_clean LIKE '%[palavra]%')
                       - Se o usuário citar apenas um TIPO de instrumento (ex: violão, guitarra), use os radicais:
                         - Violão: (p.instrument_clean LIKE '%viol%' OR p.name_clean LIKE '%viol%' OR c.category_name_clean LIKE '%viol%')
                         - Guitarra: (p.instrument_clean LIKE '%guitarr%' OR p.name_clean LIKE '%guitarr%' OR c.category_name_clean LIKE '%guitarr%')
                         - Baixo: (p.instrument_clean LIKE '%baix%' OR p.name_clean LIKE '%baix%')
                         - Bateria: (p.instrument_clean LIKE '%bateri%' OR p.name_clean LIKE '%bateri%')
                         - Teclado: (p.instrument_clean LIKE '%teclad%' OR p.instrument_clean LIKE '%sintetiz%')
                         - Ukulele: (p.instrument_clean LIKE '%ukulel%' OR p.name_clean LIKE '%ukulel%')
                    3. Filtros Numéricos e de Estoque:
                       - "até R$ X" / "abaixo de X" / "por até X" / "R$X": AND p.price_brl <= X
                       - "acima de R$ X": AND p.price_brl >= X
                       - Sempre inclua: AND p.stock_quantity > 0 AND (p.status IS NULL OR p.status = 'active')
                    4. Limite: Utilize LIMIT 20.
                    5. Se for pergunta puramente institucional (horários, trocas, garantia, frete), responda apenas: NONE

                    Formato de Saída Obrigatório:
                    - Responda APENAS a query SQL pura a começar por SELECT 
                    ou a palavra NONE. Sem markdown ou explicações.
                    """
                    generated_sql = self.llm.gen(sql_router_prompt).strip()
                    agent_log(f"[SQL_RAW] {generated_sql[:300]!r}")
                    sql_match = re.search(r'(SELECT\b[\s\S]+?)(?:;|$|```)', generated_sql, re.IGNORECASE)
                    clean_sql = sql_match.group(1).strip() if sql_match else ""

                    if clean_sql:
                        clean_sql = re.sub(r"LIKE\s+'%([^'%]+)%\)", r"LIKE '%\1%')", clean_sql)
                        clean_sql = re.sub(r"LIKE\s+'%([^'%]+)%$", r"LIKE '%\1%'", clean_sql)

                    if clean_sql and "SELECT" in clean_sql.upper() and "NONE" not in clean_sql.upper():
                        trace.append(f"💾 [SQL Executado]: `{clean_sql}`")
                        sql_result = query_database(clean_sql)
                        if "Nenhum resultado" not in sql_result and "Erro" not in sql_result:
                            try:
                                db_rows_for_validation = json.loads(sql_result)
                            except Exception:
                                db_rows_for_validation = []
                            db_context = f"\nResultado do Banco de Dados:\n{sql_result}\n"
                            trace.append(f"📊 [SQL Resposta]: {len(db_rows_for_validation)} linhas retornadas.")

                if not db_context and not has_institutional and not has_defect_intent:
                    return {
                        "response": "Desculpe, não encontrei nenhum modelo correspondente no catálogo.",
                        "trace": trace,
                        "policies_used": policy_snippets
                    }

        is_order_query = bool(order_direct_info)

        # =====================================================================
        # EARLY EXIT - Respostas de 0.1s
        # =====================================================================
        if db_rows_for_validation and not is_order_query:
            user_words = set(re.findall(r"\w+", user_msg_clean))

            # 1. Match Exato (Ex: Yamaha F310)
            if len(user_words) > 2:
                for row in db_rows_for_validation:
                    prod_name = row.get("produto") or row.get("name") or row.get("modelo") or "Instrumento"
                    prod_words = set(re.findall(r"\w+", normalize_text(prod_name)))

                    if prod_words and len(prod_words & user_words) >= 2:
                        agent_log(f"[FAST_KEYWORD_MATCH] Ignorando LLM para: {prod_name}")
                        marca = row.get("marca") or row.get("brand") or "Não informada"
                        preco_original = row.get("preco_original") or row.get("price_brl") or 0
                        preco_pix = row.get("preco_pix_a_vista")
                        if preco_pix is None and preco_original:
                            try:
                                preco_pix = round(float(preco_original) * 0.95, 2)
                            except (ValueError, TypeError):
                                preco_pix = preco_original
                        estoque = row.get("estoque") or row.get("stock_quantity") or 0
                        desc = row.get("descricao") or row.get("description") or ""

                        return {
                            "response": f"🎯 **Encontrei o produto exato para você!**\n\n"
                                        f"🎸 **{prod_name}**\n"
                                        f"- 🏷️ **Marca:** {marca}\n"
                                        f"- 💰 **Preço original:** {format_brl(preco_original)}\n"
                                        f"- 💸 **Preço à vista (PIX):** {format_brl(preco_pix)} *(5% de desconto)*\n"
                                        f"- 📦 **Estoque:** {estoque} unidades\n"
                                        f"- 📝 **Descrição:** {desc}\n",
                            "trace": trace + ["🎯 [Fast Match]: Resposta gerada em 0.1s diretamente do banco."],
                            "policies_used": policy_snippets
                        }

            # =====================================================================
            # Match  de produtos - Respostas de 0.1s
            # =====================================================================
            if any(stem in user_msg_clean for stem in self._PRODUCT_STEMS):
                agent_log("[FAST_CATEGORY_MATCH] Ignorando LLM para busca por categoria.")
                return {
                    "response": self._build_safe_response(db_rows_for_validation),
                    "trace": trace + ["🎯 [Category Match]: Lista gerada em 0.1s diretamente do banco."],
                    "policies_used": policy_snippets
                }

        # =====================================================================
        # LLM (Para perguntas complexas ou institucionais)
        # =====================================================================
        system_prompt = """
        Você é o assistente virtual da 'Empório da Música' (Campo Grande - MS).

        DIRETRIZES DE ATENDIMENTO:
        1. Seja empático e educado. Se o cliente disse que o instrumento quebrou, demonstre empatia.
        2. Se o cliente perguntar sobre conserto, defeito ou peça quebrada, use APENAS a seção [POLÍTICAS DA LOJA] para responder. 
           - Explique que a garantia legal cobre defeitos de fabricação (90 dias).
           - Explique que a garantia NÃO cobre quedas, mau uso ou danos físicos.
           - Se for dano por queda, informe que a loja não realiza consertos, mas que ele pode procurar um luthier especializado.
        3. Se a pergunta for sobre PRODUTOS (ex: "quanto custa o violão?"), você SÓ PODE listar os produtos do 'Resultado do Banco de Dados'.
        4. É PROIBIDO inventar produtos, marcas ou modelos.
        5. NÃO vendemos acessórios (cordas, palhetas, cabos).
        """
        final_prompt = f"""
[DADOS DO BANCO]
{db_context if db_context else "(nenhum produto)"}

[POLÍTICAS DA LOJA]
{context_docs}

[PERGUNTA DO CLIENTE]
"{user_msg}"
"""
        response_text = self.llm.gen(final_prompt, system_prompt=system_prompt)
        agent_log(f"[LLM_RAW] {response_text!r}")

        # =====================================================================
        # Validação (Grounding & Hard Fallbacks)
        # =====================================================================
        if db_rows_for_validation and not is_order_query:
            brands_in_db = set()
            for row in db_rows_for_validation:
                for key in ("marca", "brand"):
                    if row.get(key):
                        brands_in_db.update(re.split(r"[\s\-/]+", str(row[key]).lower()))

            mentioned_brands = {b for b in self._KNOWN_BRANDS if
                                re.search(rf"\b{re.escape(b)}\b", response_text, re.IGNORECASE)}
            invented_brands = mentioned_brands - brands_in_db

            says_nothing = any(re.search(pat, response_text, re.IGNORECASE) for pat in self._FALSE_NEGATIVE_PATTERNS)

            if invented_brands or says_nothing:
                agent_log(f"[GROUNDING_OVERRIDE] {invented_brands=} {says_nothing=}")
                return {"response": self._build_safe_response(db_rows_for_validation), "trace": trace,
                        "policies_used": policy_snippets}

        # Hard Fallback para Endereço (se o LLM falhar e não for produto)
        if "endereço" in user_msg.lower() or "onde fica" in user_msg.lower():
            if "não está disponível" in response_text.lower() or "não tenho" in response_text.lower():
                agent_log("[HARD_FALLBACK] Forçando resposta de endereço.")
                return {
                    "response": "A Empório da Música fica na Rua 14 de Maio, 3200 — Centro, Campo Grande – MS. CEP: 79202-333. Nosso telefone/WhatsApp é (67) 3341-4444.",
                    "trace": trace + ["🛑 [Hard Fallback]: LLM falhou no endereço, resposta bruta forçada."],
                    "policies_used": policy_snippets
                }

        if has_defect_intent:
            if "não está disponível" in response_text.lower() or "não tenho" in response_text.lower() or "não encontrei" in response_text.lower():
                agent_log("[HARD_FALLBACK] Forçando resposta de defeito.")
                return {
                    "response": "Poxa, sinto muito pelo ocorrido! 😔\n\nDe acordo com a nossa política, **danos por quedas ou mau uso não são cobertos pela garantia**. A garantia legal de 90 dias cobre apenas defeitos de fabricação.\n\nComo a loja não realiza consertos, recomendamos levar o instrumento a um luthier especializado para avaliar o dano. Se for um defeito de fabricação, entre em contato com nosso suporte pelo WhatsApp (67) 3341-4444.",
                    "trace": trace + ["🛑 [Hard Fallback]: Resposta de defeito gerada sem LLM."],
                    "policies_used": policy_snippets
                }

        return {"response": response_text, "trace": trace, "policies_used": policy_snippets}