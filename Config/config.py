import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


DB_PATH = os.path.join(ROOT_DIR, "Instance", "emporio_musica.db")
DATA_DIR = os.path.join(ROOT_DIR, "Data")
LOG_PATH_AGENT = os.path.join(ROOT_DIR, "Logs", "agent.log")
LOG_PATH_LLM = os.path.join(ROOT_DIR, "Logs", "llm.log")
POLICY_PATH = os.path.join(ROOT_DIR, "Policy", "policy.md")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH_AGENT), exist_ok=True)
os.makedirs(os.path.dirname(LOG_PATH_LLM), exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


print(f"✅ RAIZ DO PROJETO: {ROOT_DIR}")
print(f"✅ BANCO DE DADOS: {DB_PATH}")