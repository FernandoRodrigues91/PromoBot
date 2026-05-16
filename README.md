# 🎮 Game Price Monitor

Bot de monitoramento de promoções de jogos que roda automaticamente via **GitHub Actions** e envia alertas pelo **Telegram**.

Monitora preços na Steam, Green Man Gaming e Instant Gaming — notificando quando o desconto atingir o limiar configurado.

---

## 📋 Índice

- [Como funciona](#como-funciona)
- [Jogos monitorados](#jogos-monitorados)
- [Configuração do projeto](#configuração-do-projeto)
- [Integração com Telegram](#integração-com-telegram)
- [Configurando o GitHub Actions](#configurando-o-github-actions)
- [Rodando localmente](#rodando-localmente)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Adicionando novos jogos](#adicionando-novos-jogos)

---

## Como funciona

```
GitHub Actions (agendado) → ark_monitor.py → consulta APIs/páginas
                                           → compara com estado anterior
                                           → envia alerta no Telegram (se houver promoção)
                                           → salva novo estado (commit automático)
```

O arquivo `estado_precos.json` guarda o último desconto visto para cada jogo. A cada execução, o bot compara o desconto atual com o anterior e só notifica se:

- O desconto **aumentou** e atingiu o mínimo configurado, **ou**
- A promoção **encerrou** (voltou a 0% após ter desconto)

Isso evita notificações repetidas para a mesma promoção.

---

## Jogos monitorados

| Jogo | Plataforma | Desconto mínimo |
|------|-----------|----------------|
| ARK: Astraeos | Steam | 10% |
| ARK: Lost Colony Expansion Pass | Steam | 10% |
| Borderlands 4 | Steam | 10% |
| Borderlands 4 | Green Man Gaming | 60% |
| Borderlands 4 | Instant Gaming | 60% |

> Veja como [adicionar novos jogos](#adicionando-novos-jogos).

---

## Configuração do projeto

### 1. Faça um fork do repositório

Clique em **Fork** no canto superior direito desta página.

### 2. Clone o seu fork

```bash
git clone https://github.com/SEU_USUARIO/game-price-monitor.git
cd game-price-monitor
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

---

## Integração com Telegram

O bot usa o Telegram para enviar notificações. Você precisará de dois valores: um **token de bot** e um **chat ID**. Ambos são configurados como segredos no GitHub (nunca no código).

### Passo 1 — Criar um bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Inicie uma conversa e envie o comando `/newbot`
3. Siga as instruções: escolha um nome e um username para o bot (o username deve terminar em `bot`, ex: `meu_monitor_bot`)
4. Ao finalizar, o BotFather enviará uma mensagem com o seu **token**, no formato:

```
123456789:AAFbkLmNoPqRsTuVwXyZ-exemplo
```

> ⚠️ **Guarde esse token com segurança.** Quem tiver acesso a ele pode controlar o seu bot.

### Passo 2 — Obter o seu Chat ID

O Chat ID identifica para qual conversa o bot vai enviar as mensagens. Pode ser uma conversa direta com você ou um grupo.

**Opção A — Conversa direta (mais simples):**

1. Inicie uma conversa com o seu bot recém-criado no Telegram (procure pelo username que você escolheu)
2. Envie qualquer mensagem para ele (ex: `/start`)
3. Acesse a URL abaixo no navegador, substituindo `SEU_TOKEN`:

```
https://api.telegram.org/botSEU_TOKEN/getUpdates
```

4. Procure pelo campo `"id"` dentro de `"chat"` na resposta JSON:

```json
{
  "message": {
    "chat": {
      "id": 123456789,
      "type": "private"
    }
  }
}
```

Esse número (`123456789`) é o seu **Chat ID**.

**Opção B — Grupo do Telegram:**

1. Crie um grupo e adicione o seu bot como membro
2. Envie uma mensagem no grupo
3. Acesse a mesma URL `/getUpdates` acima
4. O Chat ID de grupos é um número **negativo** (ex: `-987654321`)

### Passo 3 — Testar a conexão localmente

Antes de configurar o GitHub, você pode validar que o bot está funcionando:

```bash
export TELEGRAM_TOKEN="SEU_TOKEN_AQUI"
export TELEGRAM_CHAT_ID="SEU_CHAT_ID_AQUI"

python ark_monitor.py --teste
```

Se tudo estiver certo, você receberá uma mensagem no Telegram confirmando que o bot está operacional.

---

## Configurando o GitHub Actions

As credenciais do Telegram são armazenadas como **GitHub Secrets** — nunca ficam expostas no código ou nos logs.

### Passo 1 — Adicionar os secrets

1. No seu repositório, vá em **Settings → Secrets and variables → Actions**
2. Clique em **New repository secret** e adicione:

| Nome do secret | Valor |
|----------------|-------|
| `TELEGRAM_TOKEN` | O token gerado pelo BotFather |
| `TELEGRAM_CHAT_ID` | O seu Chat ID |

### Passo 2 — Criar o workflow

Crie o arquivo `.github/workflows/monitor.yml` no repositório:

```yaml
name: Monitor de Preços

on:
  schedule:
    # Roda a cada 6 horas (0h, 6h, 12h, 18h — horário UTC)
    - cron: "0 */6 * * *"
  workflow_dispatch: # Permite rodar manualmente pela interface do GitHub

jobs:
  monitorar:
    runs-on: ubuntu-latest

    permissions:
      contents: write  # Necessário para commitar o estado_precos.json

    steps:
      - name: Checkout do repositório
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Instalar dependências
        run: pip install -r requirements.txt

      - name: Executar monitor
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
        run: python ark_monitor.py

      - name: Salvar estado (commit automático)
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add estado_precos.json
          git diff --cached --quiet || git commit -m "chore: atualiza estado de preços [skip ci]"
          git push
```

> O `[skip ci]` no commit message evita que o commit do estado dispare um novo workflow em loop.

### Passo 3 — Verificar a execução

Após o push do workflow, vá em **Actions** no seu repositório para acompanhar as execuções. Você também pode disparar manualmente clicando em **Run workflow**.

---

## Rodando localmente

```bash
# Instalação
pip install -r requirements.txt

# Execução normal
export TELEGRAM_TOKEN="seu_token"
export TELEGRAM_CHAT_ID="seu_chat_id"
python ark_monitor.py

# Modo debug (exibe logs detalhados de parsing)
LOG_LEVEL=DEBUG python ark_monitor.py

# Modo teste (envia mensagem de validação no Telegram e encerra)
python ark_monitor.py --teste
```

---

## Estrutura do projeto

```
game-price-monitor/
├── ark_monitor.py          # Script principal
├── requirements.txt        # Dependências Python
├── estado_precos.json      # Estado persistido (gerado automaticamente, no .gitignore)
├── .gitignore
├── .github/
│   └── workflows/
│       └── monitor.yml     # Workflow do GitHub Actions
└── README.md
```

---

## Adicionando novos jogos

### Steam

Encontre o **App ID** do jogo na URL da página da Steam:
`https://store.steampowered.com/app/`**`730`**`/Counter_Strike_2/`

Adicione ao dicionário `JOGOS_STEAM` em `ark_monitor.py`:

```python
JOGOS_STEAM = {
    "ARK: Astraeos":    "3483400",
    "Counter-Strike 2": "730",      # ← novo jogo
}
```

### Green Man Gaming / Instant Gaming

Copie a URL da página do jogo na plataforma e adicione ao dicionário correspondente:

```python
JOGOS_GMG = {
    "Borderlands 4": "https://www.greenmangaming.com/games/borderlands-4-pc/",
    "Novo Jogo":     "https://www.greenmangaming.com/games/novo-jogo-pc/",  # ← novo
}
```

Ajuste também o **desconto mínimo** para não receber alertas desnecessários:

```python
DESCONTO_MINIMO_STEAM = 10   # notifica a partir de 10% OFF
DESCONTO_MINIMO_GMG   = 60   # notifica a partir de 60% OFF
DESCONTO_MINIMO_IG    = 60   # notifica a partir de 60% OFF
```

---

## Segurança

- ✅ Credenciais do Telegram ficam **exclusivamente** nos GitHub Secrets — nunca no código
- ✅ O arquivo `estado_precos.json` está no `.gitignore` (não expõe histórico de preços)
- ✅ O bot usa apenas variáveis de ambiente — seguro para repositórios públicos
- ✅ Nenhuma dependência com acesso escrito a sistemas externos além do Telegram

---

## Licença

MIT
