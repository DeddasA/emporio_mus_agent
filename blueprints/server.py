import os
from flask import Flask, render_template, request, jsonify

from agent import LocalDeepSeek, MusicStoreAgent, DB_PATH
from pdf_loader import  PolicyBase


print(f"📦 Verificando/carregando banco de dados em: {DB_PATH}")


app = Flask(__name__, template_folder="templates")
knowledge_base = PolicyBase()
deepseek_client = LocalDeepSeek(model_name="deepseek-r1:14b")
agent = MusicStoreAgent(knowledge_base, deepseek_client)


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def agent_endpoint():
    data = request.get_json() or {}
    user_msg = data.get("message", "").strip()
    if not user_msg:
        return jsonify({
            "response": "Por favor, envie uma mensagem válida."
                        "\nEx: 'Qual o status do pedido 12?' ou 'Quais violões estão disponíveis?'"
        }), 400

    agent_result = agent.run(user_msg)
    return jsonify(agent_result)

@app.route("/api/health")
def health_endpoint():
    ollama_ready = deepseek_client.is_available()
    return jsonify({
        "status": "nominal",
        "ollama_ready": ollama_ready,
        "model": deepseek_client.model_name,
        "database_path": DB_PATH
    })

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🎸 Servidor Empório da Música Agent rodando em: http://127.0.0.1:5000")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=True)