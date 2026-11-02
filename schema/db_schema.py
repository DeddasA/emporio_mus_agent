import os
import re
import unicodedata
import pandas as pd
import sqlite3 as sq3

from pdf_injector.pdf_loader import load_pdf_to_db

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(ROOT_DIR, "instance", "emporio_musica.db")
DATA_DIR = os.path.join(ROOT_DIR, "data")
PDF_DEFAULT_PATH = os.path.join(ROOT_DIR, "políticas_da_loja.pdf")

if not os.path.exists(PDF_DEFAULT_PATH):
    PDF_DEFAULT_PATH = os.path.join(DATA_DIR, "políticas_da_loja.pdf")

# CRITICAL: Create the instance folder BEFORE SQLite tries to connect
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def normalize_text(text: str) -> str:
    if pd.isna(text) or not isinstance(text, str):
        return "" if pd.isna(text) else str(text)

    normalized = unicodedata.normalize('NFD', text)
    cleaned = ''.join(ch for ch in normalized if unicodedata.category(ch) != 'Mn')
    return cleaned.lower().strip()


KNOWN_BRANDS = [
    "Tagima Memphis", "Yamaha", "Tagima", "Giannini", "Rozini", "Shelby",
    "Crafter", "Martin", "Taylor", "Takamine", "Kala", "Ohana", "Kalani",
    "Fender", "Gibson", "Ibanez", "PRS", "Music Man", "Pearl", "Tama",
    "Korg", "Nord", "Roland"
]


def extract_instrument_brand_model(name: str, desc: str, cat_name: str = ""):
    name_str = str(name).strip() if pd.notna(name) else ""
    desc_str = str(desc).strip() if pd.notna(desc) else ""

    brand = "Outros"
    model = name_str

    generic_prefixes = ["Bateria Acústica", "Bateria", "Teclado Sintetizador", "Teclado"]
    cleaned_name = name_str
    for gp in generic_prefixes:
        if cleaned_name.startswith(gp):
            cleaned_name = cleaned_name[len(gp):].strip()
            break

    sorted_brands = sorted(KNOWN_BRANDS, key=lambda b: len(b.split()), reverse=True)
    for b in sorted_brands:
        pattern = rf"^{re.escape(b)}\b"
        if re.search(pattern, cleaned_name, re.IGNORECASE):
            brand = b
            model = re.sub(pattern, "", cleaned_name, flags=re.IGNORECASE).strip()
            break

    instrument = ""
    inst_candidates = [
        "Violão clássico", "Violão folk", "Violão dreadnought", "Violão eletroacústico", "Violão 7 cordas", "Violão",
        "Ukulele soprano", "Ukulele concert", "Ukulele tenor", "Ukulele barítono", "Ukulele",
        "Guitarra elétrica", "Guitarra",
        "Contrabaixo elétrico", "Contrabaixo", "Baixo",
        "Bateria acústica", "Bateria",
        "Teclado sintetizador", "Teclado arranjador", "Sintetizador", "Piano de palco", "Teclado"
    ]
    for cand in inst_candidates:
        if cand.lower() in desc_str.lower()[:40] or cand.lower() in name_str.lower()[:30]:
            instrument = cand
            break

    if not instrument:
        cat_map = {
            "Guitarras": "Guitarra",
            "Baixos": "Contrabaixo",
            "Baterias e Percussão": "Bateria",
            "Teclados e Pianos": "Teclado",
            "Violões": "Violão",
            "Ukuleles": "Ukulele"
        }
        instrument = cat_map.get(cat_name, cat_name or "Instrumento Musical")

    clean_desc = desc_str

    return brand, model, instrument, clean_desc


def csv_to_db(force: bool = False):
    if os.path.exists(DB_PATH) and not force:
        try:
            conn = sq3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='products';")
            has_products = cursor.fetchone()[0] > 0
            if has_products:
                cursor.execute("PRAGMA table_info(products);")
                cols = [c[1] for c in cursor.fetchall()]
                if "brand" in cols and "instrument" in cols:
                    cursor.execute("SELECT count(*) FROM products;")
                    if cursor.fetchone()[0] > 0:
                        load_pdf_to_db()
                        conn.close()
                        return []
            conn.close()
        except Exception as e:
            print(f"⚠️ Verificação do banco: {e}")

    # Connect to the DB
    conn = sq3.connect(DB_PATH)
    cursor = conn.cursor()

    # CRITICAL: Create the store_policies table BEFORE pdf_loader tries to insert data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_number INTEGER,
            section_title TEXT,
            content TEXT,
            content_clean TEXT
        );
    """)
    conn.commit()

    mapping_csvs = {
        "customers": [os.path.join(DATA_DIR, "customers.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - customers.csv")],
        "categories": [os.path.join(DATA_DIR, "categories.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - categories.csv")],
        "order_items": [os.path.join(DATA_DIR, "order_items.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - order_items.csv")],
        "products": [os.path.join(DATA_DIR, "products.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - products.csv")],
        "orders": [os.path.join(DATA_DIR, "orders.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - orders.csv")],
        "promotions": [os.path.join(DATA_DIR, "promotions.csv"), os.path.join(ROOT_DIR, "desafio_tecnico_ai_eng - promotions.csv")]
    }

    cat_file = next((f for f in mapping_csvs["categories"] if os.path.exists(f)), None)
    cat_dict = {}
    if cat_file:
        df_cat_temp = pd.read_csv(cat_file)
        df_cat_temp.columns = [col.strip().lower().replace(" ", "_") for col in df_cat_temp.columns]
        if "category_id" in df_cat_temp.columns and "name" in df_cat_temp.columns:
            cat_dict = dict(zip(df_cat_temp["category_id"], df_cat_temp["name"]))

    loaded_tables = []
    for table, candidates in mapping_csvs.items():
        chosen_file = next((f for f in candidates if os.path.exists(f)), None)
        if chosen_file:
            try:
                df = pd.read_csv(chosen_file)
                df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]

                if table == "products":
                    brands = []
                    models = []
                    instruments = []
                    clean_descriptions = []

                    for _, row in df.iterrows():
                        cat_id = row.get("category_id")
                        cat_name = cat_dict.get(cat_id, "")
                        b, m, inst, d = extract_instrument_brand_model(
                            row.get("name", ""),
                            row.get("description", ""),
                            cat_name
                        )
                        brands.append(b)
                        models.append(m)
                        instruments.append(inst)
                        clean_descriptions.append(d)

                    df["brand"] = brands
                    df["model"] = models
                    df["instrument"] = instruments
                    df["description"] = clean_descriptions

                    df["brand_clean"] = df["brand"].apply(normalize_text)
                    df["model_clean"] = df["model"].apply(normalize_text)
                    df["instrument_clean"] = df["instrument"].apply(normalize_text)
                    df["name_clean"] = df["name"].apply(normalize_text)
                    df["description_clean"] = df["description"].apply(normalize_text)
                    if "specs" in df.columns:
                        df["specs_clean"] = df["specs"].apply(normalize_text)

                elif table == "categories":
                    if "name" in df.columns:
                        df["category_name_clean"] = df["name"].apply(normalize_text)
                    if "description" in df.columns:
                        df["description_clean"] = df["description"].apply(normalize_text)

                elif table == "customers":
                    if "name" in df.columns:
                        df["name_clean"] = df["name"].apply(normalize_text)
                    if "city" in df.columns:
                        df["city_clean"] = df["city"].apply(normalize_text)
                    if "email" in df.columns:
                        df["email"] = df["email"].astype(str).str.strip().str.lower()

                df.to_sql(table, conn, if_exists="replace", index=False)
                loaded_tables.append(f"{table} ({len(df)} linhas)")
                print(f"✅ Tabela '{table}' carregada com colunas [brand, model, instrument].")
            except Exception as e:
                print(f"❌ Erro ao carregar {chosen_file}: {e}")
        else:
            print(f"⚠️ Arquivo para tabela '{table}' não encontrado.")

    # THESE MUST BE OUTSIDE THE FOR LOOP
    conn.commit()
    conn.close()

    load_pdf_to_db()
    return loaded_tables



