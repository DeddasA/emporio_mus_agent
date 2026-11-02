# 🎸 Empório da Música - Agente de IA com RAG

Assistente virtual inteligente para a **Empório da Música** (Campo Grande - MS). O sistema utiliza uma arquitetura **RAG (Retrieval-Augmented Generation)** com o modelo local **DeepSeek** (via Ollama) e uma camada de validação em Python (Fast Matcher / Grounding) para responder sobre produtos, pedidos e políticas sem alucinações.

Para perguntas sobre produtos e valores, o sistema usa RAG + Fast Matcher (SQL + RapidFuzz). Para perguntas complexas e institucionais (frete, garantia, devolução), o sistema usa RAG + LLM (DeepSeek lendo o `policy.md`).

---

## 🗂️ Estrutura do Projeto

*   **`Server/server.py`**: API em Flask (porta 5000).
*   **`Agent/agent.py`**: Roteador, regras de negócio e validação anti-alucinação (Grounding).
*   **`LLm/llm.py`**: Lógica de busca SQL (Fast Match), motor RapidFuzz e conexão com o LLM.
*   **`Schema/db_schema.py`**: ETL que lê os CSVs (Pandas) e gera o banco SQLite.
*   **`RAG/pdf_injector/pdf_loader.py`**: Parser do `policy.md` (RAG).
*   **`RAG/policy/policy.md`**: Manual de políticas da loja (fonte de verdade).
*   **`Server/templates/index.html`**: Interface do chat (Dark Mode + RAG Trace).
*   **`Instance/emporio_musica.db`**: Banco de dados SQLite (gerado automaticamente).
*   **`Data/`**: Arquivos CSV base para a criação do banco de dados.
*   **`Config/config.py`**: Centraliza os caminhos dinâmicos (banco, logs e dados) para garantir portabilidade.
*   **`Logs/`**: Logs gerais do `musical_agent.py` e `llm.py`.
*   **`requirements.txt`**: Dependências Python para rodar o agente.
*   **`README.md`**: Este documento.

---

## 🧠 Stack Tecnológico e Justificativa das Decisões Técnicas

### 💻 Linguagem e Ambiente
*   **Linguagem:** Python 3.12+.
*   **Framework Web:** Flask (leve, fácil de rodar localmente e integrar com o Ollama).
*   **IDE:** PyCharm.

### 🧠 Inteligência Artificial
*   **LLM Local (Agente):** **DeepSeek-R1 8B** e **14B** via Ollama. *Justificativa:* Rodar o modelo localmente garante privacidade dos dados da loja, custo zero por token e funciona offline. O 8B é mais rápido para formatação; o 14B é usado se o hardware permitir.
*   **Arquitetura Híbrida (RAG + Determinismo):** *Justificativa:* LLMs são péssimos em buscar dados exatos (preços, estoque) e tendem a alucinar. Por isso, a busca de produtos é feita via SQL (determinístico) e o LLM apenas formata a resposta final.
*   **Busca Semântica (Fuzzy Matching):** Biblioteca **RapidFuzz**. *Justificativa:* Permite encontrar produtos mesmo com erros de digitação (ex: "Rozine" em vez de "Rozini") e é extremamente rápido (processamento em C).
*   **Auxílio no Desenvolvimento:** DeepSeek e Gemini Pro (via chat) foram usados como assistentes para acelerar a escrita de código (boilerplate do Flask, HTML/Tailwind) e brainstorming. **O heavy lifting foi manual:** a lógica de anti-alucinação, o roteamento de intenções, o Fast Matcher e o Grounding foram desenhados e implementados por mim, com o DeepSeek atuando como apoio na escrita e correção.

### 🗄️ Dados e ETL
*   **Banco de Dados:** SQLite (`instance/emporio_musica.db`). *Justificativa:* Leve, portátil e não exige instalação de servidor para o protótipo. Em produção, seria substituído por PostgreSQL/MySQL.
*   **ETL:** **Pandas** para leitura, tratamento e limpeza dos CSVs.
*   **Parser de Políticas:** Leitura do Markdown (`policy.md`) para injetar as regras no banco (RAG).

### 🛡️ Segurança e Anti-Alucinação (O Diferencial)
*   **Grounding Validator (Bouncer):** Se o LLM inventar uma marca (ex: "Fender") que não está no JSON do banco, ou negar um produto que existe, a resposta é descartada e o Python gera uma lista determinística.
*   **Fast Matcher (Early Exit):** Respostas de catálogo em **0.1s** geradas diretamente pelo Python, ignorando o LLM. Isso elimina a latência e a chance de alucinação em consultas de preço.
*   **SQL Injection Blocker:** Regex que bloqueia comandos maliciosos (ex: `DROP TABLE`).

---
## 🚀 Melhorias Futuras (Se houvesse mais tempo)

Com mais tempo de desenvolvimento, o projeto poderia evoluir para uma versão de produção ainda mais robusta. As principais ideias de melhorias incluem:

1.  **Migração para Banco de Dados Relacional (MySQL/PostgreSQL):** Substituir o SQLite por um banco de dados em servidor (como MySQL ou PostgreSQL). Embora o SQLite seja excelente para portabilidade e testes locais, um banco em servidor suportaria múltiplas conexões simultâneas de usuários, maior volume de dados e permitiria a criação de usuários com permissões de acesso (leitura/escrita), algo essencial para um ambiente de produção real.
2.  **Fallback Avançado e Multi-camadas:** Expandir a lógica de *Fallback* para além do catálogo. Quando o agente não encontrar uma resposta exata, ele poderia fazer uma busca semântica por produtos similares no banco (ex: sugerir um violão de outra marca com o mesmo perfil) em vez de apenas dizer que não encontrou.
3.  **Diversificação de Respostas por Cenário:** Implementar regras de formatação para o LLM de acordo com o contexto do usuário (ex: respostas mais diretas e técnicas para clientes experientes; respostas mais empáticas e explicativas para iniciantes).
4.  **Interface (UI/UX) Premium:** Criar um design mais elaborado com animações de carregamento (skeleton screens), histórico de conversas na barra lateral (salvo em *local storage*) e a inclusão de imagens reais dos produtos nos cards do catálogo.
5.  **Orquestração de Agentes (Multi-Agent System):** Dividir o *MusicStoreAgent* atual em subagentes especializados. Um agente focado apenas em vendas, outro exclusivo para políticas (RAG) e um terceiro para suporte técnico/garantia, coordenados por um agente gerente (Router Master).
6.  **Embeddings e Busca Semântica Real:** Substituir o RapidFuzz (busca difusa por strings) por um banco de dados vetorial (como ChromaDB ou FAISS) usando embeddings do Ollama. Isso permitiria buscas semânticas complexas (ex: *"um instrumento com som mais quente e ideal para bossa nova"*).
7.  **Melhoria Contínua com Feedback:** Adicionar botões de "Joinha" e "Não gostei" nas respostas do chat, salvando os feedbacks em uma tabela do banco para que a equipe de desenvolvimento possa monitorar as falhas de alucinação do LLM e refinar os prompts.
8.  **Medidas mais robustas para segurança para combater 
injeções de comandos maliciosos através de prompt poisoning dentre demais ameaças.**  

## 🚀 Como Executar

### 1. Pré-requisitos de Hardware
*   **Ollama** instalado e rodando (`ollama serve`).
*   **Modelo DeepSeek** baixado:
    ```bash
    ollama run deepseek-r1:8b
    #depois
    pip install -r requirements.txt

  *Aguarde uns segundos para a criação do banco de dados antes de usar o agente, cerca de 2 a 5 segundos dependendo da sua máquina.
    

# Casos de Teste (QA) - Empório da Música

Este documento lista os cenários de teste para validar a precisão, a velocidade e as barreiras de segurança (anti-alucinação) do agente virtual.

## 1. Testes de Catálogo (Fast Matcher / SQL)
*Objetivo: Garantir que o agente retorne dados exatos do banco em menos de 1 segundo, sem chamar o LLM.*

| ID | Entrada do Usuário | Resultado Esperado | Tipo de Rota |
| :--- | :--- | :--- | :--- |
| **T01** | *"Quanto custa a Yamaha F310?"* | Deve retornar exatamente a Yamaha F310, com preço original, desconto PIX, estoque e descrição. | Match Exato (Fast Matcher) |
| **T02** | *"Quais violões disponíveis até R$1000?"* | Deve listar apenas violões com `price_brl <= 1000`, ordenados do mais barato para o mais caro. | Busca por Categoria + Filtro SQL |
| **T03** | *"Vocês têm Tagima Memphis?"* | Deve retornar os produtos da Tagima Memphis (mesmo que o usuário não digite o nome completo). | Fuzzy Match (RapidFuzz) |
| **T04** | *"Martin D-28"* | Deve retornar o produto exato (Martin D-28), ignorando o LLM e calculando o PIX (R$ 10.924,05). | Match Exato (Fast Matcher) |
| **T05** | *"Quais as opções de ukulele?"* | Deve listar todos os ukuleles em estoque (Kala, Ohana, Kalani, etc.). | Busca por Categoria |
**Imagens:**
* Quanto custa a Yamaha F310?
<img src="./Img/01.png" alt="Texto alternativo" width="700" />
---
* Quais violões disponíveis até R$1000?
<img src="./Img/02.png"  width="700" />
---

* Vocês têm Tagima Memphis?
<img src="./Img/04.png"  width="700" />
---
* Martin D-28
<img src="./Img/04.png"  width="700" />
---
* Quais as opções de ukulele?
<img src="./img/05.png"  width="700" />
---


## 2. Testes Institucionais (RAG / Políticas)
*Objetivo: Validar se o agente lê o `policy.md` e responde corretamente usando o LLM, sem inventar informações.*

| ID | Entrada do Usuário | Resultado Esperado | Fonte da Resposta |
| :--- | :--- | :--- | :--- |
| **T06** | *"Qual o endereço da loja?"* | Deve informar a Rua 14 de Maio, 3200, Centro, Campo Grande - MS. | `policy.md` (Seção 1) |
| **T07** | *"Como funciona o frete para outras cidades?"* | Deve citar Correios (PAC/SEDEX) e Jadlog, com os prazos de 2 a 12 dias úteis. | `policy.md` (Seção 4) |
| **T08** | *"Posso parcelar no cartão?"* | Deve informar que aceita até 12x sem juros, com parcela mínima de R$ 100,00. | `policy.md` (Seção 2) |
| **T09** | *"Me arrependi da minha compra, posso devolver?"* | Deve explicar o direito de arrependimento de 7 dias e as condições do produto. | `policy.md` (Seção 3) |
| **T10** | *"Meu violão caiu no chão e quebrou uma parte. Tenho garantia?"* | Deve ser empático e informar que danos por queda **não** são cobertos, recomendando um luthier. | `policy.md` (Seção 6 - Garantia) |

* Qual o endereço da loja?
<img src="./Img/06.png"  width="700" />
---
* Como funciona o frete para outras cidades?
<img src="./Img/07.png"  width="700" />
---

* Posso parcelar no cartão?
<img src="./Img/08.png"  width="700" />
---

* Posso parcelar no cartão?
<img src="./Img/08.png"  width="700" />
---

* Me arrependi da minha compra, posso devolver?
<img src="./Img/09.png"  width="700" />
---

* Meu violão caiu no chão e quebrou uma parte. Tenho garantia?
<img src="./Img/10.png"  width="700" />
---



## 3. Testes de Pedidos e Rastreamento (SQL)
*Objetivo: Validar a extração de e-mail/ID e a query de `JOIN` nas tabelas de pedidos.*

| ID | Entrada do Usuário | Resultado Esperado | Condição |
| :--- | :--- | :--- | :--- |
| **T11** | *"Qual o status do pedido 5?"* | Deve retornar o status "Entregue", código de rastreio `BRTP3456789BR` e a data estimada. | Pedido existe no banco |
| **T12** | *"Quero ver os pedidos do email rafael.pereira@jmail.com"* | Deve listar os pedidos associados a este e-mail, com os itens comprados. | E-mail válido no banco |


* Qual o status do pedido 5?
<img src="./Img/11.png"  width="700" />
---
* Quero ver os pedidos do email rafael.pereira@jmail.com"
<img src="./Img/12.png"  width="700" />
---



## 4. Testes de Segurança e Anti-Alucinação (Bouncer)
*Objetivo: Provar que o Python impede o LLM de inventar dados ou aceitar comandos maliciosos.*

| ID      | Entrada do Usuário | Resultado Esperado | Barreira Ativada |
|:--------| :--- | :--- | :--- |
| **T13** | *"DROP TABLE products;"* | Deve bloquear imediatamente e retornar um aviso de "Comando não permitido". | SQL Injection Blocker |
| **T14** | *"Vocês vendem cordas e palhetas?"* | Deve informar que a loja só vende instrumentos e redirecionar para o catálogo. | Roteador Institucional |
| **T15** | *"Quais guitarras Fender vocês têm?"* (Sabendo que não há Fender no CSV) | O LLM pode tentar inventar. O Python deve interceptar, bloquear a resposta e dizer que não há Fender no estoque. | Grounding Validator (Marcas) |
|

* DROP TABLE products
<img src="./Img/13.png"  width="700" />
---
* Quais guitarras Fender vocês têm?
<img src="./Img/15.png"  width="700" />
---



## 🛠️ Como executar os testes de API (Via `curl` ou Postman)

Para testar o endpoint do chat via terminal (com o servidor rodando):

```bash
curl -X POST http://127.0.0.1:5000/api/chat \
     -H "Content-Type: application/json" \
     -d '{"message": "Quanto custa a Yamaha F310?"}'
