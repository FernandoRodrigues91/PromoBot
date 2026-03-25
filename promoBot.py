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