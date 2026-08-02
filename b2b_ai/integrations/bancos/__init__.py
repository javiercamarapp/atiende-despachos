"""Módulo de integración bancaria — BBVA, Banorte, Santander, HSBC, Banamex, Scotiabank, Inbursa, Afirme, OFX, CSV."""
from b2b_ai.integrations.bancos.adapter import BankAdapter, BankAdapterError
from b2b_ai.integrations.bancos.bbva import BBVAAdapter
from b2b_ai.integrations.bancos.banorte import BanorteAdapter
from b2b_ai.integrations.bancos.santander import SantanderAdapter
from b2b_ai.integrations.bancos.hsbc import HSBCAdapter
from b2b_ai.integrations.bancos.banamex import BanamexAdapter
from b2b_ai.integrations.bancos.scotiabank import ScotiabankAdapter
from b2b_ai.integrations.bancos.inbursa import InbursaAdapter
from b2b_ai.integrations.bancos.afirme import AfirmeAdapter
from b2b_ai.integrations.bancos.ofx_parser import OFXParser
from b2b_ai.integrations.bancos.csv_parser import CSVParser
from b2b_ai.integrations.bancos.models import (
    BankConfig, BankStatement, BankTransaction, Banco, FormatoEstado, TipoTransaccion,
)

__all__ = [
    "BankAdapter", "BankAdapterError",
    "BBVAAdapter", "BanorteAdapter", "SantanderAdapter",
    "HSBCAdapter", "BanamexAdapter", "ScotiabankAdapter", "InbursaAdapter", "AfirmeAdapter",
    "OFXParser", "CSVParser",
    "BankConfig", "BankStatement", "BankTransaction", "Banco", "FormatoEstado", "TipoTransaccion",
]
