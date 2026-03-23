# Polymarket Temporal Arbitrage — Paper Trading Bot

## Specification complète pour Claude Code

> **Auteur** : Théo — EDHEC M1 Data Science Applied to Business
> **Objectif** : Construire un paper trading bot qui détecte et simule des opportunités d'arbitrage temporel sur les marchés crypto Up/Down de Polymarket, avec une interface web temps réel pour valider la stratégie avant passage en live.

---

## 1. Contexte & Stratégie

### 1.1 Qu'est-ce que l'arbitrage temporel sur Polymarket ?

Polymarket propose des marchés binaires crypto (BTC, ETH, SOL, XRP) avec des résolutions à 5 minutes et 15 minutes. Chaque marché a deux outcomes : **Up** (le prix monte) et **Down** (le prix baisse). Ces outcomes sont mutuellement exclusifs et exhaustifs : l'un paie 1.00 USDC par share, l'autre paie 0.

Les prix de Up et Down oscillent en permanence au gré de l'offre et la demande. L'arbitrage temporel consiste à :

1. **À t₁** : Observer que le prix d'un côté (ex: Down) est bas → acheter Down
2. **À t₂** (quelques secondes/minutes plus tard) : Le prix oscille et l'autre côté (Up) devient aussi bas → acheter Up
3. **Résultat** : On détient les deux côtés du marché. Quel que soit le résultat, une position paie 1.00 USDC. Si le coût total des deux positions < 1.00, le profit est garanti.

### 1.2 Condition mathématique fondamentale

Soit :
- `p₁` = prix d'achat de la première leg (Down ou Up)
- `p₂` = prix d'achat de la seconde leg (l'outcome opposé)
- `C` = capital total déployé

**Condition d'arbitrage (avant fees)** :

```
p₁ + p₂ < 1.00
```

### 1.3 Formules complètes

#### Sizing optimal des mises

Pour verrouiller un profit identique quel que soit le scénario, les mises doivent être proportionnelles aux prix :

```
S₁ = C × p₁ / (p₁ + p₂)     (mise sur leg 1)
S₂ = C × p₂ / (p₁ + p₂)     (mise sur leg 2)
```

Les deux legs génèrent le même nombre de shares :

```
shares = C / (p₁ + p₂)
```

#### Payout garanti

```
payout = shares × 1.00 = C / (p₁ + p₂)
```

#### Profit brut

```
π_brut = payout - C = C × (1 - p₁ - p₂) / (p₁ + p₂)
```

#### Fees Polymarket (formule officielle, marchés crypto 5min/15min)

```python
def polymarket_fee(num_shares: float, price: float) -> float:
    """
    Formule officielle Polymarket pour les marchés crypto.
    Source: https://docs.polymarket.com/trading/fees
    
    Paramètres crypto 5min/15min:
      - feeRate = 0.25
      - exponent = 2
    
    Le fee est un TAKER FEE à l'entrée (pas sur le profit).
    Pas de fee sur le payout à la résolution.
    Le fee est collecté en shares sur les buy orders.
    """
    fee_rate = 0.25
    exponent = 2
    fee = num_shares * price * fee_rate * (price * (1 - price)) ** exponent
    return round(fee, 4)  # arrondi 4 décimales
```

Caractéristiques clés de la fee curve :
- **Taux effectif max** : 1.56% à p = 0.50
- **Symétrique** : le fee diminue vers 0% et 100%
- **Exposant quadratique** : (p(1-p))² → le fee s'écrase très vite aux extrêmes
- **Pas de fee à la résolution** : le winning share paie 1.00 USDC net

#### Profit net (après fees)

```
fee₁ = polymarket_fee(shares, p₁)
fee₂ = polymarket_fee(shares, p₂)

π_net = π_brut - fee₁ - fee₂
```

#### ROI

```
ROI = π_net / C
```

#### Tableau de référence des fees (100 shares, crypto)

| Prix  | Fee (USDC) | Taux effectif |
|-------|-----------|---------------|
| 0.10  | 0.02      | 0.20%         |
| 0.20  | 0.13      | 0.64%         |
| 0.30  | 0.33      | 1.10%         |
| 0.40  | 0.58      | 1.44%         |
| 0.45  | 0.69      | 1.53%         |
| 0.50  | 0.78      | 1.56%         |
| 0.60  | 0.86      | 1.44%         |
| 0.70  | 0.77      | 1.10%         |
| 0.80  | 0.51      | 0.64%         |
| 0.90  | 0.18      | 0.20%         |

---

## 2. Architecture du Bot

### 2.1 Vue d'ensemble

```
┌─────────────────────────────────────────────────────────┐
│                    PAPER TRADING BOT                     │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Market   │→ │ Opportunity  │→ │ Paper Execution   │  │
│  │ Monitor  │  │ Detector     │  │ Engine            │  │
│  └──────────┘  └──────────────┘  └───────────────────┘  │
│       ↑                                    │            │
│       │         ┌──────────────┐           │            │
│       │         │ Portfolio &  │←──────────┘            │
│       │         │ P&L Tracker  │                        │
│       │         └──────────────┘                        │
│       │                │                                │
│  ┌────┴────────────────┴──────────────────────────────┐ │
│  │              Web Dashboard (FastAPI + HTMX)         │ │
│  │  - Prix temps réel         - Historique trades     │ │
│  │  - Opportunités détectées  - P&L cumulé           │ │
│  │  - Positions ouvertes      - Paramètres config    │ │
│  └────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
         ↕                    
┌─────────────────────┐
│ Polymarket CLOB API │
│  REST + WebSocket   │
└─────────────────────┘
```

### 2.2 Stack technique

| Composant | Technologie | Justification |
|-----------|-------------|---------------|
| Backend | **Python 3.11+** | Écosystème data/trading, asyncio natif |
| API client | **aiohttp** + **websockets** | Connexions async au CLOB |
| Serveur web | **FastAPI** + **uvicorn** | API moderne, WebSocket natif, auto-docs |
| Frontend | **HTMX** + **Alpine.js** + **TailwindCSS (CDN)** | Réactivité sans framework lourd, SSE pour temps réel |
| Base de données | **SQLite** (via **aiosqlite**) | Zero config, suffisant pour paper trading, portable |
| Scheduling | **asyncio** natif | Pas de dépendance externe |
| Graphiques | **Chart.js** (CDN) | Léger, interactif, directement dans le HTML |

### 2.3 Structure des fichiers

```
polymarket-arb-bot/
├── README.md
├── requirements.txt
├── config.yaml                  # Configuration utilisateur
├── .env.example                 # Template variables d'environnement
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # Entry point — lance le bot + serveur web
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py            # Chargement config YAML + env vars
│   │   ├── models.py            # Dataclasses: Market, Opportunity, Trade, Position
│   │   └── fees.py              # Calcul exact des fees Polymarket
│   │
│   ├── market/
│   │   ├── __init__.py
│   │   ├── client.py            # Client REST Polymarket CLOB API
│   │   ├── websocket.py         # WebSocket pour prix temps réel
│   │   ├── monitor.py           # Boucle de monitoring des marchés Up/Down
│   │   └── pairs.py             # Détection et mapping des paires Up/Down
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── detector.py          # Détection d'opportunités d'arbitrage temporel
│   │   ├── executor.py          # Paper execution engine
│   │   └── risk.py              # Gestion des risques et limites
│   │
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── tracker.py           # Suivi des positions et P&L
│   │   └── database.py          # Persistance SQLite
│   │
│   └── web/
│       ├── __init__.py
│       ├── app.py               # FastAPI application
│       ├── routes.py            # Endpoints API + pages HTML
│       ├── sse.py               # Server-Sent Events pour temps réel
│       └── templates/
│           ├── base.html        # Layout principal
│           ├── dashboard.html   # Dashboard principal
│           ├── trades.html      # Historique des trades
│           └── settings.html    # Configuration
│
├── static/
│   └── style.css                # Styles custom (minimal, Tailwind fait le gros)
│
├── data/
│   └── paper_trades.db          # SQLite database (créée automatiquement)
│
└── tests/
    ├── test_fees.py             # Tests unitaires sur le calcul des fees
    ├── test_detector.py         # Tests de la détection d'opportunités
    └── test_executor.py         # Tests du paper execution engine
```

---

## 3. Polymarket CLOB API — Intégration

### 3.1 Endpoints nécessaires

**Base URL** : `https://clob.polymarket.com`

#### Lister les marchés crypto actifs

```
GET /markets
```

Response contient un array de marchés. Filtrer par :
- `active: true`
- Tokens contenant "Up" ou "Down" dans le `outcome`
- `closed: false`

Chaque marché a :
- `condition_id` : identifiant unique du marché
- `tokens` : array avec les outcomes (Up/Down), chacun ayant un `token_id`
- `question` : description du marché (ex: "Will Bitcoin go up in the next 15 minutes?")
- `end_date_iso` : date de résolution

#### Prix temps réel (orderbook)

```
GET /book?token_id={token_id}
```

Response :
```json
{
  "market": "...",
  "asset_id": "...",
  "bids": [{"price": "0.55", "size": "1000"}, ...],
  "asks": [{"price": "0.56", "size": "500"}, ...]
}
```

Le **best bid** = prix max auquel on peut vendre. Le **best ask** = prix min auquel on peut acheter (c'est le prix pertinent pour notre stratégie).

#### Vérifier les fees

```
GET /fee-rate?token_id={token_id}
```

Retourne le `fee_rate_bps` pour le marché. Les marchés crypto retournent une valeur non-nulle.

#### Prix simplifié (midpoint)

```
GET /price?token_id={token_id}
```

Pour un monitoring rapide sans parser l'orderbook complet.

#### Marchés par event/slug

```
GET /markets/{condition_id}
```

### 3.2 WebSocket pour flux temps réel

```
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

Subscription message :
```json
{
  "type": "market",
  "assets_ids": ["token_id_up", "token_id_down"]
}
```

Le WebSocket push les changements de prix en temps réel. Si le WebSocket n'est pas disponible ou instable, fallback sur du polling REST toutes les 2-5 secondes.

### 3.3 Identification des paires Up/Down

Les marchés crypto Up/Down sont structurés comme des **events** contenant exactement 2 marchés :
- Un marché "Up" (ex: "Bitcoin Up" — token_id pour Yes)
- Un marché "Down" (ex: "Bitcoin Down" — token_id pour Yes)

**Stratégie de pairing** :
1. Fetch tous les marchés actifs via `GET /markets`
2. Grouper par `group_id` ou pattern dans le `question` (même asset + même timeframe)
3. Pour chaque paire, stocker : `asset` (BTC/ETH/SOL/XRP), `timeframe` (5min/15min), `token_id_up`, `token_id_down`, `end_date_iso`

**Attention** : les marchés 5min et 15min se renouvellent en continu. Il faut rafraîchir la liste des paires régulièrement (toutes les 1-2 minutes) pour capter les nouveaux marchés qui s'ouvrent.

---

## 4. Modules détaillés

### 4.1 `core/fees.py` — Calcul des fees

```python
"""
Implémentation exacte de la formule de fees Polymarket.
Source officielle : https://docs.polymarket.com/trading/fees

IMPORTANT : 
- Le fee est un TAKER fee, payé à l'entrée (achat)
- Collecté en shares sur les buy orders (tu reçois moins de shares)
- PAS de fee sur le payout à la résolution
- Arrondi à 4 décimales, minimum 0.0001 USDC
"""

# Paramètres par type de marché
FEE_PARAMS = {
    "crypto": {"fee_rate": 0.25, "exponent": 2},     # 5min & 15min crypto
    "sports": {"fee_rate": 0.0175, "exponent": 1},    # NCAAB, Serie A
}

def calculate_fee(num_shares: float, price: float, market_type: str = "crypto") -> float:
    """Calcule le taker fee exact en USDC."""
    params = FEE_PARAMS[market_type]
    fee = num_shares * price * params["fee_rate"] * (price * (1 - price)) ** params["exponent"]
    fee = round(fee, 4)
    if 0 < fee < 0.0001:
        fee = 0.0001
    return fee

def effective_fee_rate(price: float, market_type: str = "crypto") -> float:
    """Taux de fee effectif en pourcentage pour un prix donné."""
    params = FEE_PARAMS[market_type]
    return params["fee_rate"] * (price * (1 - price)) ** params["exponent"]

def shares_after_fee(amount_usdc: float, price: float, market_type: str = "crypto") -> float:
    """
    Nombre réel de shares reçues après fee.
    Le fee est collecté en shares sur les buy orders.
    """
    gross_shares = amount_usdc / price
    fee_usdc = calculate_fee(gross_shares, price, market_type)
    # Le fee en shares = fee_usdc / price (puisque collecté en shares)
    fee_shares = fee_usdc / price
    return gross_shares - fee_shares

def arbitrage_profit(p1: float, p2: float, capital: float, market_type: str = "crypto") -> dict:
    """
    Calcul complet du profit d'arbitrage temporel.
    
    Args:
        p1: prix d'achat de la leg 1
        p2: prix d'achat de la leg 2
        capital: capital total en USDC
    
    Returns:
        dict avec tous les détails du trade
    """
    # Sizing optimal
    s1 = capital * p1 / (p1 + p2)
    s2 = capital * p2 / (p1 + p2)
    
    # Shares (avant fee)
    gross_shares = capital / (p1 + p2)
    
    # Fees à l'entrée
    fee1 = calculate_fee(gross_shares, p1, market_type)
    fee2 = calculate_fee(gross_shares, p2, market_type)
    
    # Shares réelles après fee (collecté en shares sur buy)
    real_shares_1 = gross_shares - (fee1 / p1)
    real_shares_2 = gross_shares - (fee2 / p2)
    
    # Payout selon le scénario (le pire cas détermine le profit garanti)
    payout_if_side1_wins = real_shares_1 * 1.0  # leg 1 paie, leg 2 = 0
    payout_if_side2_wins = real_shares_2 * 1.0  # leg 2 paie, leg 1 = 0
    
    worst_payout = min(payout_if_side1_wins, payout_if_side2_wins)
    best_payout = max(payout_if_side1_wins, payout_if_side2_wins)
    
    return {
        "p1": p1,
        "p2": p2,
        "combined_cost": p1 + p2,
        "capital": capital,
        "stake_leg1": round(s1, 4),
        "stake_leg2": round(s2, 4),
        "gross_shares": round(gross_shares, 4),
        "fee_leg1": fee1,
        "fee_leg2": fee2,
        "total_fees": round(fee1 + fee2, 4),
        "gross_profit": round(gross_shares - capital, 4),
        "worst_case_profit": round(worst_payout - capital, 4),
        "best_case_profit": round(best_payout - capital, 4),
        "worst_case_roi": round((worst_payout - capital) / capital * 100, 4),
        "is_profitable": worst_payout > capital,
    }
```

### 4.2 `core/models.py` — Data models

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    UP = "up"
    DOWN = "down"


class TradeStatus(str, Enum):
    LEG1_OPEN = "leg1_open"           # Première leg achetée, en attente de la seconde
    FULLY_HEDGED = "fully_hedged"     # Les deux legs sont en place
    RESOLVED_WIN = "resolved_win"     # Marché résolu, profit réalisé
    RESOLVED_LOSS = "resolved_loss"   # Marché résolu, perte (leg 2 jamais placée)
    EXPIRED = "expired"               # Leg 1 ouverte mais marché résolu avant leg 2
    CANCELLED = "cancelled"           # Annulé manuellement


@dataclass
class MarketPair:
    """Une paire de marchés Up/Down pour un même asset et timeframe."""
    pair_id: str                       # Identifiant unique de la paire
    asset: str                         # BTC, ETH, SOL, XRP
    timeframe: str                     # "5min" ou "15min"
    token_id_up: str                   # Token ID du outcome Up (Yes)
    token_id_down: str                 # Token ID du outcome Down (Yes)
    condition_id_up: str               # Condition ID marché Up
    condition_id_down: str             # Condition ID marché Down
    resolution_time: datetime          # Quand le marché résout
    price_up: float = 0.0
    price_down: float = 0.0
    best_ask_up: float = 0.0          # Best ask = prix d'achat réel
    best_ask_down: float = 0.0
    ask_size_up: float = 0.0          # Liquidité disponible
    ask_size_down: float = 0.0
    last_update: Optional[datetime] = None


@dataclass  
class Opportunity:
    """Une opportunité d'arbitrage détectée."""
    id: str
    pair: MarketPair
    leg1_side: Side                    # Quel côté acheter en premier
    leg1_price: float                  # Prix de la leg 1 (best ask)
    timestamp: datetime
    combined_cost: float               # p1 + p2 estimé
    estimated_profit_pct: float        # ROI estimé après fees
    available_liquidity: float         # Min liquidité des deux côtés
    status: str = "detected"           # detected, leg1_filled, completed, expired


@dataclass
class PaperTrade:
    """Un trade paper (simulé)."""
    id: str
    pair_id: str
    asset: str
    timeframe: str
    
    # Leg 1
    leg1_side: Side
    leg1_price: float
    leg1_shares: float
    leg1_fee: float
    leg1_timestamp: datetime
    leg1_stake: float
    
    # Leg 2 (rempli quand la seconde leg est exécutée)
    leg2_side: Optional[Side] = None
    leg2_price: Optional[float] = None
    leg2_shares: Optional[float] = None
    leg2_fee: Optional[float] = None
    leg2_timestamp: Optional[datetime] = None
    leg2_stake: Optional[float] = None
    
    # Résultat
    status: TradeStatus = TradeStatus.LEG1_OPEN
    capital_deployed: float = 0.0
    total_fees: float = 0.0
    payout: Optional[float] = None
    profit: Optional[float] = None
    roi: Optional[float] = None
    resolution_outcome: Optional[str] = None  # "up" ou "down"
    resolved_at: Optional[datetime] = None


@dataclass
class PortfolioState:
    """État courant du portfolio paper."""
    initial_capital: float = 10000.0
    current_capital: float = 10000.0   # Cash disponible
    total_deployed: float = 0.0        # Capital dans des positions ouvertes
    total_pnl: float = 0.0
    total_fees_paid: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    active_positions: list = field(default_factory=list)
```

### 4.3 `strategy/detector.py` — Détection d'opportunités

Le détecteur surveille en continu les prix des paires Up/Down et identifie les fenêtres d'arbitrage.

**Logique de détection** :

```
BOUCLE PRINCIPALE (toutes les 2-5 secondes) :

Pour chaque paire active (BTC/ETH/SOL/XRP × 5min/15min) :
    1. Fetch best ask Up et best ask Down
    2. Calculer combined_cost = best_ask_up + best_ask_down
    3. Calculer le profit net théorique (avec fees exactes)
    
    SI combined_cost < SEUIL_ENTRY (ex: 0.97) ET profit_net > 0 :
        → Arbitrage SIMULTANÉ détecté → acheter les deux legs immédiatement
    
    SI une leg est déjà ouverte (LEG1_OPEN) :
        SI le prix de l'autre côté est assez bas pour compléter l'arb :
            → Acheter la leg 2, passer en FULLY_HEDGED
        SI le temps restant avant résolution < SAFETY_MARGIN :
            → Alerte : risque de résolution sans hedge
    
    TRACKING TEMPOREL (pour arb temporel) :
        - Enregistrer les prix dans un rolling buffer (ex: 5 dernières minutes)
        - SI un côté a touché un prix bas récemment ET l'autre côté touche un prix bas maintenant :
            → Opportunité temporelle détectée
```

**Paramètres configurables** :

```yaml
# config.yaml
strategy:
  # Seuil pour l'arbitrage simultané
  simultaneous_arb_threshold: 0.98  # combined_cost < ce seuil
  
  # Seuil pour ouvrir la leg 1 de l'arb temporel
  leg1_max_price: 0.52              # N'acheter une leg que si prix ≤ cette valeur
  
  # Seuil pour compléter la leg 2
  combined_cost_target: 0.97        # Compléter si combined ≤ ce seuil
  
  # Capital par trade
  capital_per_trade: 100            # USDC (paper) par opportunité
  max_concurrent_positions: 5       # Positions ouvertes max simultanées
  
  # Timing
  min_time_to_resolution: 120       # Secondes minimum avant résolution pour ouvrir leg 1
  max_leg1_hold_time: 300           # Secondes max en attente de leg 2 avant abandon
  
  # Liquidité minimale
  min_liquidity: 50                 # USDC minimum de liquidité sur le best ask

monitoring:
  poll_interval: 3                  # Secondes entre chaque poll (si pas de WebSocket)
  pair_refresh_interval: 60         # Secondes entre chaque refresh de la liste des paires
  assets: ["BTC", "ETH", "SOL", "XRP"]
  timeframes: ["5min", "15min"]

portfolio:
  initial_capital: 10000            # Capital paper initial
  
web:
  host: "127.0.0.1"
  port: 8080
```

### 4.4 `strategy/executor.py` — Paper Execution Engine

Le paper executor simule l'exécution sans passer de vrais ordres.

```
QUAND une opportunité est détectée :

    1. Vérifier : capital disponible ≥ capital_per_trade
    2. Vérifier : nombre de positions ouvertes < max
    3. Vérifier : liquidité suffisante sur le best ask
    4. Vérifier : temps restant avant résolution > min_time_to_resolution
    
    SI toutes les conditions sont remplies :
        - Calculer les shares avec fees exactes (shares_after_fee)
        - Créer un PaperTrade avec status LEG1_OPEN
        - Déduire le stake du capital disponible
        - Logger et notifier le dashboard
    
QUAND la leg 2 est disponible :
    
    1. Recalculer le profit net avec les prix réels des deux legs
    2. Vérifier que le profit est toujours positif
    3. Compléter le PaperTrade avec les infos leg 2
    4. Passer en FULLY_HEDGED
    
QUAND un marché résout :
    
    1. Déterminer le résultat (Up ou Down gagnant)
    2. Calculer le payout réel
    3. Créditer le capital
    4. Mettre à jour le P&L
    5. Logger et notifier
```

### 4.5 `strategy/risk.py` — Gestion des risques

Risques spécifiques à surveiller et gérer :

| Risque | Description | Mitigation |
|--------|-------------|------------|
| **Risque d'exécution** | Le marché résout avant que la leg 2 soit placée | Timer de sécurité, fermer la position si temps restant < seuil |
| **Slippage** | Le prix réel d'exécution est pire que le best ask observé | Utiliser le best ask (pas le mid) et ajouter un buffer de slippage |
| **Liquidité insuffisante** | Pas assez de volume sur le best ask pour le trade | Vérifier la taille du best ask avant d'exécuter |
| **Concentration** | Trop de capital sur un seul asset ou timeframe | Limiter les positions par asset/timeframe |
| **Gap de prix** | Le prix saute brusquement (gap) et l'arb disparaît | Revalider le prix juste avant l'exécution de leg 2 |

```python
# Contrôles de risque pré-trade
MAX_PORTFOLIO_EXPOSURE = 0.5   # Max 50% du portfolio déployé simultanément
MAX_PER_ASSET = 0.25           # Max 25% sur un seul asset
MAX_LOSS_PER_TRADE = 0.02      # Max 2% de perte si leg 1 expire non hedgée
```

### 4.6 `portfolio/database.py` — Persistance

Schema SQLite :

```sql
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    pair_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    
    leg1_side TEXT NOT NULL,
    leg1_price REAL NOT NULL,
    leg1_shares REAL NOT NULL,
    leg1_fee REAL NOT NULL,
    leg1_timestamp TEXT NOT NULL,
    leg1_stake REAL NOT NULL,
    
    leg2_side TEXT,
    leg2_price REAL,
    leg2_shares REAL,
    leg2_fee REAL,
    leg2_timestamp TEXT,
    leg2_stake REAL,
    
    status TEXT NOT NULL DEFAULT 'leg1_open',
    capital_deployed REAL NOT NULL DEFAULT 0,
    total_fees REAL NOT NULL DEFAULT 0,
    payout REAL,
    profit REAL,
    roi REAL,
    resolution_outcome TEXT,
    resolved_at TEXT,
    
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    price_up REAL NOT NULL,
    price_down REAL NOT NULL,
    combined_cost REAL NOT NULL,
    ask_size_up REAL,
    ask_size_down REAL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS opportunities (
    id TEXT PRIMARY KEY,
    pair_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    leg1_side TEXT NOT NULL,
    leg1_price REAL NOT NULL,
    combined_cost REAL NOT NULL,
    estimated_profit_pct REAL NOT NULL,
    available_liquidity REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'detected',
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    acted_on INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capital REAL NOT NULL,
    deployed REAL NOT NULL,
    total_pnl REAL NOT NULL,
    total_fees REAL NOT NULL,
    total_trades INTEGER NOT NULL,
    win_rate REAL NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index pour les requêtes fréquentes
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_asset ON trades(asset);
CREATE INDEX IF NOT EXISTS idx_price_history_pair ON price_history(pair_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status, detected_at);
```

---

## 5. Interface Web (Dashboard)

### 5.1 Architecture frontend

Le dashboard est servi par FastAPI et utilise **HTMX** pour les mises à jour dynamiques + **Server-Sent Events** (SSE) pour le streaming temps réel.

### 5.2 Pages et composants

#### Page 1 : Dashboard principal (`/`)

Layout en grille avec les sections suivantes :

**Barre du haut — Métriques clés** (4 cartes) :
- Capital disponible (avec variation)
- P&L total (avec %)
- Trades actifs / Total trades
- Win rate

**Section gauche — Marchés temps réel** :
- Tableau des paires actives (BTC, ETH, SOL, XRP × 5min, 15min)
- Pour chaque paire : prix Up, prix Down, combined cost, spread vs 1.00
- Code couleur : vert si combined < 0.97, orange si < 1.00, rouge si ≥ 1.00
- Refresh automatique via SSE

**Section centrale — Opportunités** :
- Liste des opportunités détectées (temps réel)
- Pour chaque opp : asset, timeframe, prix, profit estimé, liquidité
- Bouton "Execute Paper Trade" (ou auto-execute selon config)
- Badge de statut : "new", "leg1_open", "completed", "expired"

**Section droite — Positions ouvertes** :
- Trades avec status LEG1_OPEN ou FULLY_HEDGED
- Timer countdown vers la résolution
- P&L latent
- Indicateur de risque (vert/orange/rouge selon temps restant)

**Section bas — Graphiques** :
- Chart.js line chart : P&L cumulé dans le temps
- Chart.js line chart : combined cost historique des paires (visualiser les oscillations)

#### Page 2 : Historique des trades (`/trades`)

- Tableau paginé de tous les trades
- Filtres par : asset, timeframe, status, date
- Détail de chaque trade en expandable row
- Export CSV

#### Page 3 : Paramètres (`/settings`)

- Formulaire pour modifier `config.yaml` à chaud
- Toggle paper trading on/off
- Reset du portfolio
- Slider pour les seuils (combined_cost_target, leg1_max_price, etc.)

### 5.3 SSE (Server-Sent Events) pour temps réel

```python
# Endpoint SSE
@app.get("/api/stream")
async def event_stream():
    async def generate():
        async for event in event_bus.subscribe():
            yield f"event: {event.type}\ndata: {event.data}\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream")
```

Types d'événements SSE :
- `price_update` : nouveau prix pour une paire
- `opportunity_detected` : nouvelle opportunité d'arb
- `trade_opened` : trade paper exécuté
- `trade_completed` : les deux legs sont en place
- `trade_resolved` : marché résolu, P&L final
- `portfolio_update` : métriques du portfolio mises à jour

Côté frontend (HTMX) :
```html
<div hx-ext="sse" sse-connect="/api/stream">
    <div sse-swap="price_update" hx-swap="innerHTML">
        <!-- Mis à jour automatiquement -->
    </div>
</div>
```

---

## 6. Lancement et utilisation

### 6.1 Installation

```bash
# Cloner et setup
cd polymarket-arb-bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copier et éditer la config
cp .env.example .env
cp config.example.yaml config.yaml
# Éditer config.yaml selon préférences
```

### 6.2 Requirements

```
# requirements.txt
aiohttp>=3.9.0
websockets>=12.0
fastapi>=0.109.0
uvicorn>=0.27.0
jinja2>=3.1.0
aiosqlite>=0.19.0
pyyaml>=6.0
python-dotenv>=1.0.0
httpx>=0.26.0          # Client HTTP alternatif si besoin
pydantic>=2.5.0        # Validation des données
```

### 6.3 Démarrage

```bash
# Lancer le bot + dashboard
python -m src.main

# Output attendu :
# [INFO] Loading config from config.yaml
# [INFO] Initializing SQLite database...
# [INFO] Fetching active crypto Up/Down markets...
# [INFO] Found 8 active pairs (4 assets × 2 timeframes)
# [INFO] Starting market monitor (poll every 3s)...
# [INFO] Starting opportunity detector...
# [INFO] Dashboard available at http://127.0.0.1:8080
# [INFO] Paper trading engine ready. Initial capital: $10,000
```

Ouvrir `http://127.0.0.1:8080` dans le navigateur pour le dashboard.

### 6.4 Commandes CLI (optionnel)

```bash
# Voir le status
python -m src.main status

# Reset le portfolio
python -m src.main reset

# Backtest sur des prix historiques (si implémenté)
python -m src.main backtest --days 7
```

---

## 7. Tests

### 7.1 Tests unitaires prioritaires

```python
# tests/test_fees.py
"""
Valider le calcul des fees contre la table officielle Polymarket.
Ces valeurs sont extraites directement de https://docs.polymarket.com/trading/fees
"""

def test_fee_at_050():
    """100 shares à $0.50 → fee = $0.78, rate = 1.56%"""
    fee = calculate_fee(100, 0.50, "crypto")
    assert abs(fee - 0.7813) < 0.01  # arrondi

def test_fee_at_045():
    """100 shares à $0.45 → fee = $0.69, rate = 1.53%"""
    fee = calculate_fee(100, 0.45, "crypto")
    assert abs(fee - 0.6891) < 0.01

def test_fee_at_010():
    """100 shares à $0.10 → fee = $0.02, rate = 0.20%"""
    fee = calculate_fee(100, 0.10, "crypto")
    assert abs(fee - 0.0203) < 0.01

def test_fee_at_090():
    """Symétrie : fee à 0.10 ≈ fee à 0.90"""
    fee_10 = calculate_fee(100, 0.10, "crypto")
    fee_90 = calculate_fee(100, 0.90, "crypto")
    assert abs(fee_10 - fee_90) < 0.01

def test_arbitrage_profitable():
    """p1=0.45, p2=0.45 → combined=0.90, doit être profitable"""
    result = arbitrage_profit(0.45, 0.45, 1000, "crypto")
    assert result["is_profitable"] is True
    assert result["worst_case_roi"] > 8.0  # ~9-10%

def test_arbitrage_not_profitable():
    """p1=0.55, p2=0.50 → combined=1.05, pas d'arbitrage"""
    result = arbitrage_profit(0.55, 0.50, 1000, "crypto")
    assert result["is_profitable"] is False

def test_optimal_sizing():
    """Vérifier que le sizing proportionnel égalise les payouts."""
    result = arbitrage_profit(0.40, 0.48, 1000, "crypto")
    # Les payouts des deux scénarios doivent être proches
    diff = abs(result["worst_case_profit"] - result["best_case_profit"])
    assert diff < 2.0  # Moins de 2$ de différence
```

### 7.2 Tests d'intégration

```python
# tests/test_detector.py
"""Tester la détection d'opportunités sur des données simulées."""

def test_detect_simultaneous_arb():
    """Si Up=0.45 et Down=0.45 en même temps → détection."""
    pass

def test_detect_temporal_arb():
    """Si Down=0.45 à t1 puis Up=0.45 à t2 → détection."""
    pass

def test_no_false_positive():
    """Si Up=0.55 et Down=0.48 → combined=1.03 → pas d'arb."""
    pass

def test_respects_liquidity_minimum():
    """Même si combined < 1, si liquidité < min → pas de trade."""
    pass
```

---

## 8. Notes d'implémentation pour Claude Code

### 8.1 Priorité d'implémentation

1. **Phase 1 — Core** : `fees.py`, `models.py`, `config.py` + tests des fees
2. **Phase 2 — API Client** : `client.py` pour fetch les marchés et prix, `pairs.py` pour identifier les paires
3. **Phase 3 — Monitoring** : `monitor.py` + `detector.py` avec polling REST
4. **Phase 4 — Paper Engine** : `executor.py` + `database.py` + `tracker.py`
5. **Phase 5 — Dashboard** : FastAPI app + templates HTMX + SSE
6. **Phase 6 — Polish** : WebSocket (si disponible), graphiques, export, CLI

### 8.2 Points d'attention critiques

- **Les fees sont en shares, pas en USDC** sur les buy orders. Le nombre de shares reçues est inférieur au théorique. C'est subtil mais impacte le calcul du payout.
- **Les marchés crypto se renouvellent toutes les 5/15 minutes**. La liste des paires doit être rafraîchie en continu.
- **L'API Polymarket n'est pas documentée de manière exhaustive**. Commencer par explorer les endpoints et loguer les réponses pour comprendre la structure des données.
- **Gérer les erreurs réseau** : l'API peut être lente ou indisponible. Implémenter des retry avec backoff exponentiel.
- **Les prix affichés sur Polymarket sont le midpoint du spread**. Pour le calcul d'arb, utiliser le **best ask** (prix réel d'achat), pas le midpoint.
- **Le fee est un taker fee** : si on place des limit orders (maker), il n'y a pas de fee. Mais en paper trading, on simule des market orders (taker) pour la simplicité.
- **Respecter le rate limiting** de l'API Polymarket. Ne pas spammer les endpoints.

### 8.3 Variables d'environnement

```bash
# .env
POLYMARKET_API_URL=https://clob.polymarket.com
POLYMARKET_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
DATABASE_PATH=data/paper_trades.db
LOG_LEVEL=INFO
```

### 8.4 Logging

Utiliser le module `logging` Python avec des niveaux structurés :
- `INFO` : trades exécutés, opportunités détectées, résolutions
- `DEBUG` : prix reçus, calculs de fees, état du détecteur
- `WARNING` : liquidité faible, timeout API, positions proches de la résolution
- `ERROR` : erreurs API, données invalides, erreurs de calcul

---

## 9. Extensions futures (post-MVP)

- **Passage en live** : remplacer le paper executor par de vrais ordres via le SDK Polymarket (py-clob-client)
- **Maker orders** : placer des limit orders (pas de fee) au lieu de market orders
- **Multi-window arb** : combiner les timeframes (acheter Down sur 15min, Up sur le même 15min plus tard)
- **ML signal** : utiliser un modèle ML pour prédire les oscillations de prix et timer les entrées
- **Backtest engine** : rejouer les prix historiques pour valider la stratégie
- **Alertes Telegram/Discord** : notifier les opportunités en temps réel sur mobile
- **Intégration Polymarket Gamma API** pour des données enrichies sur les marchés
