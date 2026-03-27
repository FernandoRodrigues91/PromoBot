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

