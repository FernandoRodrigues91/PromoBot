"""
🎮 Monitor de Jogos — GitHub Actions
Verifica promoções e notifica via Telegram.
"""

import logging
import requests
import json
import re
import os
import sys
from datetime import datetime, timezone, timedelta
from time import sleep

# ============================================================
# ⚙️  CONFIGURAÇÕES
# ============================================================

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Nível de log controlável via variável de ambiente:
#   LOG_LEVEL=DEBUG python ark_monitor.py  → mostra debug
#   LOG_LEVEL=INFO  python ark_monitor.py  → apenas info/erros (padrão)
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

BRASILIA = timezone(timedelta(hours=-3))

# --- Steam ---
JOGOS_STEAM = {
    "ARK: Astraeos":                   "3483400",
    "ARK: Lost Colony Expansion Pass": "3720100",
    "Borderlands 4":                   "1285190",
}
DESCONTO_MINIMO_STEAM = 10

# --- Green Man Gaming ---
JOGOS_GMG = {
    "Borderlands 4": "https://www.greenmangaming.com/games/borderlands-4-pc/",
}
DESCONTO_MINIMO_GMG = 60

# --- Instant Gaming ---
JOGOS_IG = {
    "Borderlands 4": "https://www.instant-gaming.com/pt/19682-comprar-borderlands-4-pc-steam/",
}
DESCONTO_MINIMO_IG = 60

# ATENÇÃO: este arquivo é commitado pelo workflow do GitHub Actions para
# persistir o estado entre runs. Se o step de commit falhar silenciosamente,
# o estado se perde e notificações duplicadas poderão ser enviadas.
ARQUIVO_ESTADO = "estado_precos.json"

MAX_RETRIES = 3
RETRY_DELAY = 5  # segundos

HEADERS_BASE = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GMG_COOKIES = {"gmg_currency": "BRL", "gmg_country": "BR"}

# ============================================================


def _chave_estado(plataforma: str, nome: str) -> str:
    """Gera uma chave padronizada para o dicionário de estado."""
    return f"{plataforma}_{nome.lower().replace(' ', '_')}"


def _parse_float_br(valor: str) -> float:
    """
    Converte string de preço nos formatos BR e US para float.

    Exemplos:
        "1.299,90"  →  1299.90   (formato BR)
        "1,299.90"  →  1299.90   (formato US)
        "299.90"    →  299.90
        "299,90"    →  299.90
    """
    valor = valor.strip()
    tem_ponto  = "." in valor
    tem_virgula = "," in valor

    if tem_ponto and tem_virgula:
        # Descobre qual é o separador decimal pelo que vem por último
        if valor.rfind(".") > valor.rfind(","):
            # Formato US: 1,299.90
            return float(valor.replace(",", ""))
        else:
            # Formato BR: 1.299,90
            return float(valor.replace(".", "").replace(",", "."))
    elif tem_virgula:
        # Só vírgula: assume separador decimal BR (299,90)
        return float(valor.replace(",", "."))
    else:
        # Só ponto ou sem separador de milhar: formato padrão
        return float(valor)


def requisicao_com_retry(url: str, method: str = "get", **kwargs) -> requests.Response | None:
    """Faz uma requisição HTTP com retry automático em caso de falha."""
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = getattr(requests, method)(url, timeout=15, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            log.warning("[RETRY %d/%d] %s", tentativa, MAX_RETRIES, e)
            if tentativa < MAX_RETRIES:
                sleep(RETRY_DELAY)
    log.error("[ERRO] Todas as tentativas falharam para: %s", url)
    return None

# ------------------------------------------------------------
# Steam
# ------------------------------------------------------------

def buscar_preco_steam(app_id: str) -> dict | None:
    url  = "https://store.steampowered.com/api/appdetails"
    resp = requisicao_com_retry(url, params={"appids": app_id, "cc": "br", "l": "portuguese"})
    if resp is None:
        return None

    data = resp.json()
    jogo = data.get(app_id, {})
    if not jogo.get("success"):
        log.warning("[AVISO] App ID %s não encontrado.", app_id)
        return None

    price = jogo["data"].get("price_overview")
    if not price:
        log.info("[INFO] App ID %s sem dados de preço.", app_id)
        return None

    return {
        "preco_original": price["initial"] / 100,
        "preco_atual":    price["final"] / 100,
        "desconto":       price["discount_percent"],
        "moeda":          price["currency"],
        "simbolo":        "R$",
    }


# ------------------------------------------------------------
# Green Man Gaming
# ------------------------------------------------------------

def buscar_preco_gmg(url: str) -> dict | None:
    resp = requisicao_com_retry(url, headers=HEADERS_BASE, cookies=GMG_COOKIES)
    if resp is None:
        return None

    html = resp.text

    # Estratégia 1: JSON-LD
    preco_atual, preco_orig, desconto = _extrair_jsonld(html)
    if preco_atual is not None:
        if preco_orig and preco_orig > preco_atual:
            desconto = round((1 - preco_atual / preco_orig) * 100)
        moeda, simbolo = _detectar_moeda(html)  # FIX: usa helper unificado
        log.debug("[GMG] JSON-LD: orig=%s atual=%s desconto=%s%%", preco_orig, preco_atual, desconto)
        return {
            "preco_original": preco_orig or preco_atual,
            "preco_atual":    preco_atual,
            "desconto":       desconto,
            "moeda":          moeda,
            "simbolo":        simbolo,
        }
        
        # Estratégia 2: Tags <gmgPrice>
    precos = re.findall(r'<gmgPrice[^>]*>\s*\$?\s*([\d.,]+)\s*</gmgPrice>', html)
    log.debug("[GMG] gmgPrice tags: %s", precos)

    if len(precos) >= 2:
        preco_orig  = _parse_float_br(precos[0])  # FIX: parsing correto BR/US
        preco_atual = _parse_float_br(precos[1])
        desconto    = round((1 - preco_atual / preco_orig) * 100) if preco_orig > 0 else 0
    elif len(precos) == 1:
        preco_atual = _parse_float_br(precos[0])  # FIX: parsing correto BR/US
        preco_orig  = preco_atual
        desconto    = 0
    else:
        log.error("[GMG] Nenhuma estratégia funcionou.")
        return None

    moeda, simbolo = _detectar_moeda(html)  # FIX: usa helper unificado
    log.debug("[GMG] orig=%s atual=%s desconto=%s%%", preco_orig, preco_atual, desconto)
    return {
        "preco_original": preco_orig,
        "preco_atual":    preco_atual,
        "desconto":       desconto,
        "moeda":          moeda,
        "simbolo":        simbolo,
    }
    
    # ------------------------------------------------------------
# Instant Gaming
# ------------------------------------------------------------

def buscar_preco_ig(url: str) -> dict | None:
    resp = requisicao_com_retry(url, headers=HEADERS_BASE)
    if resp is None:
        return None

    html = resp.text

    # Estratégia 1: JSON-LD
    preco_atual, preco_orig, desconto = _extrair_jsonld(html)
    if preco_atual is not None:
        moeda, simbolo = _detectar_moeda(html)

        # FIX: busca o original ANTES de calcular o desconto
        if preco_orig is None or preco_orig == preco_atual:
            preco_orig = _extrair_preco_original_ig(html, preco_atual)

        # FIX: calcula o desconto com preco_orig já resolvido
        if desconto == 0 and preco_orig and preco_orig > preco_atual:
            desconto = round((1 - preco_atual / preco_orig) * 100)

        log.debug("[IG] JSON-LD: orig=%s atual=%s desconto=%s%%", preco_orig, preco_atual, desconto)
        return {
            "preco_original": preco_orig or preco_atual,
            "preco_atual":    preco_atual,
            "desconto":       desconto,
            "moeda":          moeda,
            "simbolo":        simbolo,
        }
        
        # Estratégia 2: HTML estruturado — par (desconto%, preço)
    pares = re.findall(
        r'class=["\']discounted["\'][^>]*>\s*-(\d+)%.*?'
        r'class=["\']total["\'][^>]*>\s*(?:R\$|€|\$|£)?\s*([\d]+[.,][\d]{2})',
        html, re.DOTALL
    )
    log.debug("[IG] Pares HTML: %s", pares[:5])

    if pares:
        # Pega o maior desconto (mais provável ser o produto principal)
        pares_num = [(int(d), _parse_float_br(p)) for d, p in pares]  # FIX: parsing correto
        pares_num.sort(key=lambda x: -x[0])
        desconto, preco_atual = pares_num[0]
        preco_orig = round(preco_atual / (1 - desconto / 100), 2) if desconto < 100 else preco_atual

        moeda, simbolo = _detectar_moeda(html)
        log.debug("[IG] Par selecionado: desconto=%s%% atual=%s orig=%s", desconto, preco_atual, preco_orig)
        return {
            "preco_original": preco_orig,
            "preco_atual":    preco_atual,
            "desconto":       desconto,
            "moeda":          moeda,
            "simbolo":        simbolo,
        }

    log.error("[IG] Nenhuma estratégia funcionou.")
    return None

def _extrair_jsonld(html: str) -> tuple[float | None, float | None, int]:
    """Extrai preço atual, original e desconto de blocos JSON-LD."""
    blocos = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
    for bloco in blocos:
        try:
            data  = json.loads(bloco)
            items = data if isinstance(data, list) else [data]
            for item in items:
                offers = item.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = offers.get("price") or item.get("price")
                if price is not None:
                    atual = float(str(price).replace(",", "."))

                    # FIX: removido fallback para "priceValidUntil", que é uma
                    # data (ex: "2025-12-31"), não um preço — causava ValueError.
                    original = offers.get("highPrice")
                    try:
                        original = float(str(original).replace(",", ".")) if original else None
                    except ValueError:
                        original = None

                    return atual, original, 0
        except (json.JSONDecodeError, ValueError):
            continue
    return None, None, 0


def _extrair_preco_original_ig(html: str, preco_atual: float) -> float | None:
    """Tenta extrair o preço original riscado da página da IG."""
    m = re.search(
        r'class=["\'](?:old.?price|original.?price|strike)["\'][^>]*>.*?([\d]+[.,][\d]{2})',
        html
    )
    if m:
        try:
            return _parse_float_br(m.group(1))  # FIX: parsing correto BR/US
        except ValueError:
            pass
    return None


def _detectar_moeda(html: str) -> tuple[str, str]:
    """Detecta a moeda predominante no HTML."""
    m = re.search(r'["\']currency["\']\s*:\s*["\']([A-Z]{3})["\']', html[:8000])
    if m:
        cur = m.group(1)
        return cur, {"BRL": "R$", "USD": "$", "EUR": "€"}.get(cur, cur)
    if "R$" in html[:50000]:
        return "BRL", "R$"
    if "€" in html[:50000]:
        return "EUR", "€"
    return "USD", "$"

# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

def enviar_telegram(mensagem: str) -> bool:
    url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requisicao_com_retry(
        url, method="post",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "HTML"}
    )
    return resp is not None


# ------------------------------------------------------------
# Estado
# ------------------------------------------------------------

def carregar_estado() -> dict:
    if os.path.exists(ARQUIVO_ESTADO):
        try:
            with open(ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.warning("[AVISO] Erro ao carregar estado: %s. Iniciando do zero.", e)
    return {}


def salvar_estado(estado: dict):
    with open(ARQUIVO_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ------------------------------------------------------------
# Lógica de notificação (unificada)
# ------------------------------------------------------------

def _processar_preco(nome: str, url_compra: str, plataforma: str, chave: str,
                     preco: dict | None, estado: dict, novo_estado: dict,
                     desconto_minimo: int, agora: str):
    """Lógica centralizada de comparação e notificação para qualquer plataforma."""
    if preco is None:
        novo_estado[chave] = estado.get(chave, {})
        return

    desconto_atual    = preco["desconto"]
    desconto_anterior = estado.get(chave, {}).get("desconto", 0)
    s                 = preco["simbolo"]

    novo_estado[chave] = {
        "nome":     nome,
        "desconto": desconto_atual,
        "preco":    preco["preco_atual"],
    }

    if desconto_atual >= desconto_minimo and desconto_atual > desconto_anterior:
        mensagem = (
            f"🔥 <b>PROMOÇÃO DETECTADA!</b>\n\n"
            f"🎮 <b>{nome}</b>\n"
            f"🏪 Plataforma: <b>{plataforma}</b>\n"
            f"💸 De <s>{s} {preco['preco_original']:.2f}</s> "
            f"por <b>{s} {preco['preco_atual']:.2f}</b>\n"
            f"🏷️ Desconto: <b>{desconto_atual}% OFF</b>\n"
            f"🛒 <a href='{url_compra}'>Comprar agora</a>\n\n"
            f"⏰ Detectado em: {agora}"
        )
        log.info("✅ Promoção! %d%% OFF — enviando alerta para %s...", desconto_atual, nome)
        enviar_telegram(mensagem)

    elif desconto_atual == 0 and desconto_anterior > 0:
        mensagem = (
            f"⏰ <b>Promoção encerrada</b>\n\n"
            f"🎮 <b>{nome}</b> ({plataforma}) voltou ao preço normal.\n"
            f"💰 Preço atual: <b>{s} {preco['preco_atual']:.2f}</b>"
        )
        log.info("ℹ️  Promoção encerrada para %s.", nome)
        enviar_telegram(mensagem)

    else:
        status = f"{desconto_atual}% OFF" if desconto_atual > 0 else "sem desconto"
        log.info("ℹ️  %s: %s (%s %.2f)", nome, status, s, preco["preco_atual"])

# ------------------------------------------------------------
# Verificações
# ------------------------------------------------------------

def verificar_steam(estado, novo_estado, agora):
    log.info("\n  🟦 Steam")
    for nome, app_id in JOGOS_STEAM.items():
        log.info("    🔍 %s (AppID: %s)", nome, app_id)
        preco = buscar_preco_steam(app_id)
        chave = _chave_estado("steam", app_id)  # FIX: helper unificado
        link  = f"https://store.steampowered.com/app/{app_id}/"
        _processar_preco(nome, link, "Steam", chave, preco,
                         estado, novo_estado, DESCONTO_MINIMO_STEAM, agora)


def verificar_gmg(estado, novo_estado, agora):
    log.info("\n  🟩 Green Man Gaming")
    for nome, url in JOGOS_GMG.items():
        log.info("    🔍 %s", nome)
        preco = buscar_preco_gmg(url)
        chave = _chave_estado("gmg", nome)  # FIX: helper unificado
        _processar_preco(nome, url, "Green Man Gaming (DRM: Steam)", chave, preco,
                         estado, novo_estado, DESCONTO_MINIMO_GMG, agora)


def verificar_ig(estado, novo_estado, agora):
    log.info("\n  🟧 Instant Gaming")
    for nome, url in JOGOS_IG.items():
        log.info("    🔍 %s", nome)
        preco = buscar_preco_ig(url)
        chave = _chave_estado("ig", nome)  # FIX: helper unificado
        _processar_preco(nome, url, "Instant Gaming (DRM: Steam)", chave, preco,
                         estado, novo_estado, DESCONTO_MINIMO_IG, agora)


def verificar_jogos():
    agora = datetime.now(BRASILIA).strftime("%d/%m/%Y %H:%M (Brasília)")
    log.info("[%s] Iniciando verificação de preços...", agora)

    estado      = carregar_estado()
    novo_estado = {}

    verificar_steam(estado, novo_estado, agora)
    verificar_gmg(estado, novo_estado, agora)
    verificar_ig(estado, novo_estado, agora)

    salvar_estado(novo_estado)
    log.info("\n  ✔️  Verificação concluída.\n")

# ------------------------------------------------------------

if __name__ == "__main__":
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.error("⚠️  TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não definidos!")
        sys.exit(1)  # FIX: sys.exit em vez de exit (correto para scripts)

    if "--teste" in sys.argv:
        # FIX: modo teste agora realmente valida o envio via Telegram
        log.info("🧪 Modo teste: enviando mensagem de validação...")
        ok = enviar_telegram("✅ <b>Bot funcionando corretamente!</b>\nConexão com Telegram validada.")
        log.info("Mensagem de teste %s.", "enviada com sucesso" if ok else "FALHOU")
        sys.exit(0 if ok else 1)
    else:
        verificar_jogos()