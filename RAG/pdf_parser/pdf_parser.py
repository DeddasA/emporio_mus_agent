import sqlite3 as sq3
import requests as req
import json
import os
from Config.config import DB_PATH,POLICY_PATH






def get_all_policies_from_db():
    """Pega as poíticas do pdf e as tranforam em markdown cecra de 80% de percisão"""
    conn = sq3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT page_number, section_title, content FROM store_policies ORDER BY page_number;")
    rows = cursor.fetchall()
    conn.close()

    full_text = ""
    for page, title, content in rows:
        full_text += f"\n--- Página {page} | {title} ---\n{content}\n"
    return full_text


def generate_with_deepseek(prompt, model="deepseek-r1:14b"):
    """Manda a instrução para o LLm Ollama deepseek 14b é altemnte recomendável"""
    print(f"⏳ Enviando prompt para o DeepSeek ({model}). Isso pode levar de 1 a 3 minutos...")
    payload = {
        'model': model,
        'prompt': prompt,
        'stream': False,
        'options': {
            "temperature": 0.1,
            "num_ctx": 8192  # Aumentado para o 14b conseguir ler o PDF inteiro de uma vez
        }
    }

    try:
        res = req.post("http://localhost:11434/api/generate", json=payload, timeout=300)
        if res.status_code == 200:
            return res.json().get("response", "")
        else:
            return f"Erro: {res.status_code} - {res.text}"
    except Exception as e:
        return f"Erro de conexão: {e}"


if __name__ == "__main__":
    raw_policies = get_all_policies_from_db()
    """Fallback e error handling"""
    if not raw_policies.strip():
        print("❌ Nenhuma política encontrada no banco de dados.")
        exit()

    prompt = f"""
    Você é um analista de dados sênior. Abaixo está o texto bruto extraído do PDF de políticas da loja 'Empório da Música'.

    Sua tarefa é ler atentamente e reescrever essas políticas de forma extremamente clara, organizada em tópicos (Markdown).
    NÃO invente nenhuma regra que não esteja no texto. Apenas sintetize e organize.

    Certifique-se de destacar claramente:
    1. Regras de Frete e Entrega (prazos, valores, Campo Grande vs Outras Cidades).
    2. Formas de Pagamento (PIX, Cartão, Parcelamento, descontos).
    3. Política de Trocas e Devoluções.
    4. Garantia.
    5. Horários e Endereço.

    TEXTO BRUTO DO PDF:
    {raw_policies}
    """

    print("Lendo o banco de dados...")
    summary = generate_with_deepseek(prompt, model="deepseek-r1:14b")

    # Remove blocos de pensamento (thinking) do DeepSeek R1
    import re

    summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()

    print("\n✅ Síntese concluída! Salvando em 'Policy.md'...")

    with open(POLICY_PATH, "w", encoding="utf-8") as f:
        f.write(summary)

    print("\n--- PRÉVIA DO RESULTADO ---\n")
    print(summary[:1000] + "\n\n[...]")