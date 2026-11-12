# 📌 AgentCarDiag — Manual da Fábrica: Acessos, Produção e Vinculação de Clientes

---

## 🌐 1. LINKS E ACESSOS PRINCIPAIS

### 🏭 Painel da Fábrica (Administrador Master)
- **URL Pública:** https://diag.anality.me/admin
- **URL Local:** http://localhost:8000/admin
- **Usuário:** `admin`
- **Senha:** `<ADMIN_PASSWORD>`
- **Função:** Cadastrar clientes, gerar logins/senhas, fabricar lotes de seriais e controlar estoque.

### 🚗 Site do Cliente / Mecânico
- **URL Pública:** https://diag.anality.me/
- **URL Local:** http://localhost:8000/
- **Usuário:** Definido por você no cadastro (ex: `silva` ou `oficina-piloto-01`)
- **Senha:** Definida por você no cadastro (padrão inicial dos pilotos: `<PILOT_DEFAULT_PASSWORD>`)
- **Função:** Diagnóstico veicular, osciloscópio, atuadores e telemetria da oficina.

---

## 📋 2. PASSO A PASSO: CADASTRAR UM NOVO CLIENTE (OFICINA)

1. Acesse o **Painel da Fábrica**: https://diag.anality.me/admin
2. Faça login com `admin` / `<ADMIN_PASSWORD>`.
3. Na aba **🏢 Clientes & Oficinas**, clique no botão azul:
   👉 **`➕ Cadastrar Novo Cliente / Oficina`**
4. Preencha os campos:
   - **Nome Fantasia:** Nome da Oficina (ex: *Auto Mecânica Estrela*)
   - **ID do Sistema:** Gerado automaticamente ou digite (ex: *estrela-auto*)
   - **Responsável / Mecânico:** Nome do dono (ex: *Carlos Rodrigues*)
   - **Telefone / WhatsApp:** (ex: *(11) 98765-4321*)
   - **Nome de Usuário (Login):** Como ele entrará no site (ex: *estrela*)
   - **Senha de Acesso:** Senha dele (ex: *estrela2026* ou *<PILOT_DEFAULT_PASSWORD>*)
5. Clique em **`Cadastrar Oficina & Liberar Acesso`**.
6. **Pronto!** Envie para o cliente o link `https://diag.anality.me` junto com o usuário e a senha que você definiu.

---

## ⚡ 3. PASSO A PASSO: FABRICAR NOVO PRODUTO NA LINHA DE PRODUÇÃO

1. No Painel da Fábrica (`/admin`), clique na aba:
   👉 **`⚡ Linha de Produção & Controle de Seriais`**
2. No card **Gerador da Linha de Produção**:
   - **Tipo de Equipamento:** Selecione:
     - 🚗 *AgentCar Scanner Pro (TWAI + K-Line)*
     - 🦅 *AguiaCar 4G Telematics Fleet*
     - 📡 *AgentCar Osciloscópio Dual-CH*
   - **Código do Lote:** (ex: *LOTE-2026-FIBRA01*)
   - **Quantidade a Fabricar:** Selecione 1, 5, 10 ou 25 unidades.
3. Clique no botão azul:
   👉 **`⚡ Fabricar Lote & Gravar no Estoque`**
4. O sistema registrará os números de série autênticos de 4 dígitos iniciando em 2000:
   - `s2001`, `s2002`... (🚗 Scanner CAN)
   - `a2001`, `a2002`... (🦅 AguiaCar 4G)
   - `o2001`, `o2002`... (📡 Osciloscópio)
5. **Etiqueta:** Imprima ou anote esse número de série e cole na carcaça / caixa do equipamento físico montado.

---

## 🔗 4. PASSO A PASSO: DESTINAR / VINCULAR O APARELHO AO CLIENTE

Existem **2 formas simples** de entregar o produto ao cliente:

### OPÇÃO A: Vinculação Direta pelo Painel da Fábrica (Você faz antes de enviar)
1. Vá na aba **`⚡ Linha de Produção`** (ou na aba **`📦 Todos os Aparelhos`**).
2. Na tabela de **Estoque Fabril**, localize o serial que você vai enviar (ex: `s2001`).
3. Clique no botão **`🔗 Vincular à Oficina`**.
4. Selecione a oficina na lista e confirme.
5. Quando o cliente fizer login no site dele, o Scanner já estará ativo e 100% liberado!

### OPÇÃO B: Ativação pelo Próprio Cliente (Ele faz ao receber a caixa)
1. Você envia o aparelho na caixa com a etiqueta do serial (ex: `s2001`).
2. O mecânico entra no site com o login e senha dele: `<REDACTED_CREDENTIAL>`
3. Ele vai na aba **`📦 Meus Equipamentos`** (ou clica no aviso de ativação na aba Scanner).
4. No campo **`Ativar Novo Equipamento`**, ele digita o serial que está na caixa (`s2001`) e clica em **`Ativar Equipamento ⚡`**.
5. O sistema valida se o serial existe na fábrica, vincula à oficina dele e libera o Scanner imediatamente!

---

## 🔒 5. SUPORTE, BLOQUEIO E REDEFINIÇÃO DE SENHAS

- **O cliente esqueceu a senha?**
  No painel `/admin`, vá na linha do cliente e clique em **`🔑 Senha`**, digite a nova senha e salve.
- **Cliente atrasou mensalidade ou rescindiu?**
  Clique no botão **`⊘ Bloquear`**. O cliente não conseguirá mais logar nem usar o scanner até ser reativado.
- **Troca ou devolução de aparelho?**
  Basta clicar em **`Desvincular`**. O serial volta imediatamente para o Estoque Fabril para ser reatribuído a outro cliente.
