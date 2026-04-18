"""
Advanced Signal Engine — inspired by Freqtrade, Jesse, and Hummingbot
Features:
  - Multi-timeframe analysis (MTF)
  - ATR, Supertrend, VWAP, ADX, Stochastic RSI
  - Weighted signal confluence scoring (0–100)
  - Only emits HIGH-confidence signals (score ≥ 65)
  - Divergence detection (RSI vs price)
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class SignalDirection(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"


class MarketRegime(str, Enum):
    TRENDING = "TRENDING"   # ADX > 25, CI < 61.8, clear DI spread — ride the trend
    RANGING  = "RANGING"    # ADX < 20, CI > 61.8 — mean-revert with tight stops
    VOLATILE = "VOLATILE"   # ADX > 25, CI > 61.8 — strong but directionless, half size
    NEUTRAL  = "NEUTRAL"    # transition zone — use default params


def detect_regime(adx: float, chop: float, plus_di: float, minus_di: float) -> MarketRegime:
    di_spread = abs(plus_di - minus_di)
    if adx > 25 and chop < 61.8 and di_spread > 5:
        return MarketRegime.TRENDING
    if adx > 25 and chop >= 61.8:
        return MarketRegime.VOLATILE
    if adx < 20 and chop >= 61.8:
        return MarketRegime.RANGING
    return MarketRegime.NEUTRAL


@dataclass(frozen=True)
class StrategyParams:
    atr_stop_multiplier: float = 1.6
    atr_tp_multiplier: float = 2.8
    rsi_long_min: float = 30.0
    rsi_long_max: float = 65.0
    rsi_short_min: float = 35.0
    rsi_short_max: float = 70.0
    stoch_rsi_overbought: float = 75.0
    stoch_rsi_oversold: float = 25.0
    chop_threshold: float = 61.8


@dataclass
class Signal:
    direction: SignalDirection
    confidence: float          # 0–100
    timeframe: str
    symbol: str
    price: float
    atr: float                 # current ATR value
    stop_loss: float           # ATR-based stop
    take_profit: float         # ATR-based TP (R:R ≥ 1.5)
    indicators: Dict[str, float] = field(default_factory=dict)
    reasons: List[str]         = field(default_factory=list)
    regime: MarketRegime       = field(default_factory=lambda: MarketRegime.NEUTRAL)
    trailing: bool             = False   # replace fixed TP with trailing ATR stop
    size_factor: float         = 1.0     # position size multiplier (0.5 in VOLATILE)


# ─── Indicator Calculations ───────────────────────────────────────────────────

def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _stoch_rsi(series: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
               smooth_k: int = 3, smooth_d: int = 3) -> Tuple[pd.Series, pd.Series]:
    rsi   = _rsi(series, rsi_period)
    lo    = rsi.rolling(stoch_period).min()
    hi    = rsi.rolling(stoch_period).max()
    stoch = (rsi - lo) / (hi - lo).replace(0, np.nan) * 100
    k     = stoch.rolling(smooth_k).mean()
    d     = k.rolling(smooth_d).mean()
    return k, d


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["High"], df["Low"], df["Close"]
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm   = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_smooth = _atr(df, period)   # EWM average ATR — same scale as EWM DM
    plus_di   = 100 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan)
    minus_di  = 100 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1/period, adjust=False).mean() / tr_smooth.replace(0, np.nan)
    dx        = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean(), plus_di, minus_di


def _supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0
                ) -> Tuple[pd.Series, pd.Series]:
    """Returns (supertrend_line, direction) where direction=1=bullish, -1=bearish."""
    atr    = _atr(df, period)
    hl2    = (df["High"] + df["Low"]) / 2
    upper  = hl2 + multiplier * atr
    lower  = hl2 - multiplier * atr

    supertrend = pd.Series(np.nan, index=df.index)
    direction  = pd.Series(1, index=df.index)

    for i in range(1, len(df)):
        prev_upper = upper.iloc[i-1] if not pd.isna(upper.iloc[i-1]) else upper.iloc[i]
        prev_lower = lower.iloc[i-1] if not pd.isna(lower.iloc[i-1]) else lower.iloc[i]

        upper.iloc[i] = min(upper.iloc[i], prev_upper) if df["Close"].iloc[i-1] <= prev_upper else upper.iloc[i]
        lower.iloc[i] = max(lower.iloc[i], prev_lower) if df["Close"].iloc[i-1] >= prev_lower else lower.iloc[i]

        if pd.isna(supertrend.iloc[i-1]):
            direction.iloc[i] = 1
        elif supertrend.iloc[i-1] == prev_upper:
            direction.iloc[i] = -1 if df["Close"].iloc[i] < upper.iloc[i] else 1
        else:
            direction.iloc[i] = 1 if df["Close"].iloc[i] > lower.iloc[i] else -1

        supertrend.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]

    return supertrend, direction


def _vwap(df: pd.DataFrame) -> pd.Series:
    tp    = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_tp_vol = (tp * df["Volume"]).cumsum()
    cum_vol    = df["Volume"].cumsum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def _macd(series: pd.Series, fast: int = 12, slow: int = 26,
          signal_period: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast   = series.ewm(span=fast, adjust=False).mean()
    ema_slow   = series.ewm(span=slow, adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal     = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram  = macd_line - signal
    return macd_line, signal, histogram


def _bollinger(series: pd.Series, period: int = 20,
               std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    mid   = series.rolling(period).mean()
    std   = series.rolling(period).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def _choppiness(df: pd.DataFrame, period: int = 14) -> float:
    """
    Choppiness Index — measures whether market is trending or ranging.
    > 61.8  → sideways/choppy (avoid trading)
    < 38.2  → strongly trending (ideal for signals)
    38–62   → transition zone
    """
    if len(df) < period + 1:
        return 50.0
    recent   = df.iloc[-period:]
    tr       = _atr(df, 1).iloc[-period:]   # 1-period ATR = raw True Range
    atr_sum  = tr.sum()
    hh       = recent["High"].max()
    ll       = recent["Low"].min()
    if hh == ll or atr_sum == 0:
        return 50.0
    ci = 100.0 * np.log10(atr_sum / (hh - ll)) / np.log10(period)
    return float(np.clip(ci, 0.0, 100.0))


def _detect_candle_patterns(df: pd.DataFrame) -> List[str]:
    """
    Detect high-accuracy single and two-candle patterns.
    Returns a list of matched pattern names for the last closed candle.
    """
    if len(df) < 2:
        return []
    patterns: List[str] = []
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    c_o, c_c, c_h, c_l = float(curr["Open"]), float(curr["Close"]), float(curr["High"]), float(curr["Low"])
    p_o, p_c            = float(prev["Open"]), float(prev["Close"])

    c_range = c_h - c_l
    if c_range > 0:
        c_body       = abs(c_c - c_o)
        body_pct     = c_body / c_range
        upper_wick   = c_h - max(c_o, c_c)
        lower_wick   = min(c_o, c_c) - c_l

        # Bullish pin bar: small body, large lower wick (rejection of lows)
        if body_pct < 0.3 and lower_wick > 0.6 * c_range and upper_wick < 0.15 * c_range:
            patterns.append("BULLISH_PIN_BAR")

        # Bearish pin bar: small body, large upper wick (rejection of highs)
        if body_pct < 0.3 and upper_wick > 0.6 * c_range and lower_wick < 0.15 * c_range:
            patterns.append("BEARISH_PIN_BAR")

    # Bullish engulfing: current bullish body completely engulfs previous bearish body
    if c_c > c_o and p_c < p_o:
        if c_o <= p_c and c_c >= p_o:
            patterns.append("BULLISH_ENGULFING")

    # Bearish engulfing: current bearish body completely engulfs previous bullish body
    if c_c < c_o and p_c > p_o:
        if c_o >= p_c and c_c <= p_o:
            patterns.append("BEARISH_ENGULFING")

    # Morning star approximation: bearish → small doji/indecision → bullish
    if len(df) >= 3:
        mid = df.iloc[-2]
        m_range = float(mid["High"]) - float(mid["Low"])
        m_body  = abs(float(mid["Close"]) - float(mid["Open"]))
        if m_range > 0 and m_body / m_range < 0.2:   # doji in middle
            first = df.iloc[-3]
            if float(first["Close"]) < float(first["Open"]) and c_c > c_o:
                patterns.append("MORNING_STAR")
            elif float(first["Close"]) > float(first["Open"]) and c_c < c_o:
                patterns.append("EVENING_STAR")

    return patterns


def _detect_rsi_divergence(df: pd.DataFrame, rsi: pd.Series,
                            lookback: int = 5) -> Optional[str]:
    """Detect bullish or bearish RSI divergence over the last `lookback` candles."""
    if len(df) < lookback + 2:
        return None
    price_slice = df["Close"].iloc[-lookback:]
    rsi_slice   = rsi.iloc[-lookback:]
    price_lo, price_hi = price_slice.idxmin(), price_slice.idxmax()
    rsi_lo,   rsi_hi   = rsi_slice.idxmin(),   rsi_slice.idxmax()

    # Bullish divergence: price makes new low, RSI makes higher low
    if (df["Close"].iloc[-1] <= price_slice.min() and
            rsi.iloc[-1] > rsi_slice.min() + 2):
        return "BULLISH_DIVERGENCE"

    # Bearish divergence: price makes new high, RSI makes lower high
    if (df["Close"].iloc[-1] >= price_slice.max() and
            rsi.iloc[-1] < rsi_slice.max() - 2):
        return "BEARISH_DIVERGENCE"

    return None


# ─── Single-Timeframe Analysis ────────────────────────────────────────────────

def analyse_timeframe(df: pd.DataFrame, symbol: str,
                      timeframe: str) -> Optional[Dict]:
    """Compute all indicators for one timeframe; return None if data is too short."""
    if len(df) < 50:
        logger.warning(f"[{symbol}/{timeframe}] Not enough candles ({len(df)}), need 50")
        return None

    close = df["Close"]
    current_price = float(close.iloc[-1])

    # ── Indicators ──────────────────────────────────────────────────────────
    atr_series = _atr(df, 14)
    atr_val    = float(atr_series.iloc[-1])

    rsi_series         = _rsi(close, 14)
    rsi_val            = float(rsi_series.iloc[-1])
    stoch_k, stoch_d   = _stoch_rsi(close)
    stoch_k_val        = float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50.0
    stoch_d_val        = float(stoch_d.iloc[-1]) if not pd.isna(stoch_d.iloc[-1]) else 50.0

    adx_series, plus_di, minus_di = _adx(df, 14)
    adx_val    = float(adx_series.iloc[-1]) if not pd.isna(adx_series.iloc[-1]) else 0.0
    plus_di_v  = float(plus_di.iloc[-1])   if not pd.isna(plus_di.iloc[-1])   else 0.0
    minus_di_v = float(minus_di.iloc[-1])  if not pd.isna(minus_di.iloc[-1])  else 0.0

    st_line, st_dir    = _supertrend(df, 10, 3.0)
    st_direction       = int(st_dir.iloc[-1])           # 1 = bullish, -1 = bearish
    st_val             = float(st_line.iloc[-1]) if not pd.isna(st_line.iloc[-1]) else current_price

    vwap_series = _vwap(df)
    vwap_val    = float(vwap_series.iloc[-1]) if not pd.isna(vwap_series.iloc[-1]) else current_price

    macd_line, macd_sig, macd_hist = _macd(close)
    macd_val  = float(macd_line.iloc[-1])
    msig_val  = float(macd_sig.iloc[-1])
    mhist_val = float(macd_hist.iloc[-1])

    # Previous histogram to detect crossover
    mhist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else mhist_val

    bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2.0)
    bb_u = float(bb_upper.iloc[-1])
    bb_m = float(bb_mid.iloc[-1])
    bb_l = float(bb_lower.iloc[-1])
    bb_width = (bb_u - bb_l) / bb_m if bb_m != 0 else 0.0

    ema_50  = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
    ema_200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1]) if len(df) >= 200 else ema_50

    volume_ma   = df["Volume"].rolling(20).mean().iloc[-1]
    volume_ratio = float(df["Volume"].iloc[-1] / volume_ma) if volume_ma > 0 else 1.0

    divergence    = _detect_rsi_divergence(df, rsi_series)
    choppiness    = _choppiness(df, 14)
    candle_pats   = _detect_candle_patterns(df)

    return {
        "price":       current_price,
        "atr":         atr_val,
        "rsi":         rsi_val,
        "stoch_k":     stoch_k_val,
        "stoch_d":     stoch_d_val,
        "adx":         adx_val,
        "plus_di":     plus_di_v,
        "minus_di":    minus_di_v,
        "st_direction": st_direction,
        "st_line":     st_val,
        "vwap":        vwap_val,
        "macd":        macd_val,
        "macd_signal": msig_val,
        "macd_hist":   mhist_val,
        "macd_hist_prev": mhist_prev,
        "bb_upper":    bb_u,
        "bb_mid":      bb_m,
        "bb_lower":    bb_l,
        "bb_width":    bb_width,
        "ema_50":      ema_50,
        "ema_200":     ema_200,
        "volume_ratio": volume_ratio,
        "divergence":   divergence,
        "choppiness":   choppiness,
        "candle_pats":  candle_pats,
    }


# ─── Signal Scorer ────────────────────────────────────────────────────────────

def _score_direction(ind: Dict, direction: SignalDirection, params: StrategyParams = None) -> Tuple[float, List[str]]:
    """
    Score a trade direction based on indicator evidence.
    Returns (score 0–100, reasons list).
    Higher score = stronger confluence.
    """
    if params is None:
        params = StrategyParams()
        
    score   = 0.0
    reasons = []
    is_long = direction == SignalDirection.LONG

    # ── Trend filter via Supertrend (weight 25) ──────────────────────────────
    if is_long and ind["st_direction"] == 1:
        score += 25
        reasons.append("Supertrend BULLISH")
    elif not is_long and ind["st_direction"] == -1:
        score += 25
        reasons.append("Supertrend BEARISH")

    # ── ADX trend strength (weight 15) ──────────────────────────────────────
    if ind["adx"] > 25:
        if is_long and ind["plus_di"] > ind["minus_di"]:
            score += 15
            reasons.append(f"ADX={ind['adx']:.1f} strong +DI")
        elif not is_long and ind["minus_di"] > ind["plus_di"]:
            score += 15
            reasons.append(f"ADX={ind['adx']:.1f} strong -DI")
    elif ind["adx"] > 20:
        if is_long and ind["plus_di"] > ind["minus_di"]:
            score += 8
        elif not is_long and ind["minus_di"] > ind["plus_di"]:
            score += 8

    # ── MACD histogram crossover (weight 15) ─────────────────────────────────
    hist, prev = ind["macd_hist"], ind["macd_hist_prev"]
    if is_long and hist > 0 and prev <= 0:
        score += 15
        reasons.append("MACD histogram bullish cross")
    elif is_long and hist > 0:
        score += 8
    elif not is_long and hist < 0 and prev >= 0:
        score += 15
        reasons.append("MACD histogram bearish cross")
    elif not is_long and hist < 0:
        score += 8

    # ── Stochastic RSI (weight 15) ───────────────────────────────────────────
    k, d = ind["stoch_k"], ind["stoch_d"]
    if is_long and k < params.stoch_rsi_oversold and d < params.stoch_rsi_oversold:
        score += 15
        reasons.append(f"Stoch RSI oversold ({k:.0f})")
    elif is_long and k > d and k < 55:
        score += 8
    elif not is_long and k > params.stoch_rsi_overbought and d > params.stoch_rsi_overbought:
        score += 15
        reasons.append(f"Stoch RSI overbought ({k:.0f})")
    elif not is_long and k < d and k > 45:
        score += 8

    # ── Price vs VWAP (weight 10) ─────────────────────────────────────────────
    price = ind["price"]
    if is_long and price > ind["vwap"]:
        score += 10
        reasons.append("Price above VWAP")
    elif not is_long and price < ind["vwap"]:
        score += 10
        reasons.append("Price below VWAP")

    # ── EMA alignment (weight 10) ─────────────────────────────────────────────
    if is_long and price > ind["ema_50"] > ind["ema_200"]:
        score += 10
        reasons.append("Price > EMA50 > EMA200 (uptrend)")
    elif not is_long and price < ind["ema_50"] < ind["ema_200"]:
        score += 10
        reasons.append("Price < EMA50 < EMA200 (downtrend)")

    # ── RSI not extreme against direction (weight 5) ──────────────────────────
    rsi = ind["rsi"]
    if is_long and params.rsi_long_min < rsi < params.rsi_long_max:
        score += 5
        reasons.append(f"RSI in healthy long zone ({rsi:.0f})")
    elif not is_long and params.rsi_short_min < rsi < params.rsi_short_max:
        score += 5
        reasons.append(f"RSI in healthy short zone ({rsi:.0f})")

    # ── RSI divergence bonus (weight 10) ─────────────────────────────────────
    div = ind.get("divergence")
    if is_long and div == "BULLISH_DIVERGENCE":
        score += 10
        reasons.append("Bullish RSI divergence detected")
    elif not is_long and div == "BEARISH_DIVERGENCE":
        score += 10
        reasons.append("Bearish RSI divergence detected")

    # ── Volume confirmation (weight 5) ────────────────────────────────────────
    if ind["volume_ratio"] > 1.3:
        score += 5
        reasons.append(f"Volume spike ({ind['volume_ratio']:.1f}x avg)")

    # ── Candle pattern confirmation (weight 8) ────────────────────────────────
    pats = ind.get("candle_pats", [])
    bullish_pats = {"BULLISH_PIN_BAR", "BULLISH_ENGULFING", "MORNING_STAR"}
    bearish_pats = {"BEARISH_PIN_BAR", "BEARISH_ENGULFING", "EVENING_STAR"}
    if is_long and any(p in bullish_pats for p in pats):
        matched = [p for p in pats if p in bullish_pats]
        score += 8
        reasons.append(f"Candle pattern: {matched[0].replace('_',' ').title()}")
    elif not is_long and any(p in bearish_pats for p in pats):
        matched = [p for p in pats if p in bearish_pats]
        score += 8
        reasons.append(f"Candle pattern: {matched[0].replace('_',' ').title()}")

    # ── Machine Learning Override (weight ±40) ────────────────────────────────
    if "ml_up_prob" in ind:
        ml_prob = ind["ml_up_prob"]
        ml_offset = (ml_prob - 0.5) * 80.0
        
        if is_long:
            score += ml_offset
            if ml_offset > 10: reasons.append(f"ML Random Forest is BULLISH ({ml_prob*100:.1f}%)")
            elif ml_offset < -10: reasons.append(f"ML Predictor contradicts LONG ({ml_prob*100:.1f}%)")
        else:
            score -= ml_offset
            if ml_offset < -10: reasons.append(f"ML Random Forest is BEARISH ({(1-ml_prob)*100:.1f}%)")
            elif ml_offset > 10: reasons.append(f"ML Predictor contradicts SHORT ({(1-ml_prob)*100:.1f}%)")

    return min(score, 100.0), reasons


# ─── Multi-Timeframe Engine ───────────────────────────────────────────────────

class SignalEngine:
    """
    Multi-timeframe signal engine.
    Primary timeframe: lower TF for entry.
    Confirmation timeframe: higher TF for trend bias.
    """

    CONFIDENCE_THRESHOLD = 65.0    # minimum score to emit a signal
    # HTF bias: relaxed — only Supertrend required (EMA alignment is bonus, not gate)
    HTF_STRICT           = False

    def __init__(self, fetch_klines_fn, get_funding_rate_fn=None, params: StrategyParams = None):
        """
        fetch_klines_fn(symbol, interval, limit) → pd.DataFrame with columns:
            Open, High, Low, Close, Volume  (numeric)
        get_funding_rate_fn(symbol) → float (optional) — current funding rate
        """
        self._fetch   = fetch_klines_fn
        self._funding = get_funding_rate_fn
        self.params   = params or StrategyParams()
        
        try:
            from src.ml.predictor import MLPredictor
            self.ml_predictor = MLPredictor()
        except Exception as e:
            logger.warning(f"ML configuration omitted: {e}")
            self.ml_predictor = None

    def _get_df(self, symbol: str, interval: str, limit: int = 200) -> Optional[pd.DataFrame]:
        try:
            return self._fetch(symbol, interval, limit)
        except Exception as e:
            logger.error(f"[{symbol}/{interval}] Fetch error: {e}")
            return None

    def analyse(self, symbol: str, primary_tf: str = "5m",
                confirm_tf: str = "1h") -> Optional[Signal]:
        """
        Run multi-timeframe analysis.
        Returns a Signal if confidence ≥ threshold, else None.
        """
        df_primary = self._get_df(symbol, primary_tf, 200)
        df_confirm = self._get_df(symbol, confirm_tf, 200)

        if df_primary is None or df_confirm is None:
            return None

        ind_p = analyse_timeframe(df_primary, symbol, primary_tf)
        ind_c = analyse_timeframe(df_confirm, symbol, confirm_tf)

        if ind_p is None or ind_c is None:
            return None
            
        if getattr(self, "ml_predictor", None) and self.ml_predictor.enabled:
            ind_p["ml_up_prob"] = self.ml_predictor.predict_up_probability(df_primary)

        # ── Regime detection + adaptive parameters ───────────────────────────
        chop   = ind_p["choppiness"]
        regime = detect_regime(ind_p["adx"], chop, ind_p["plus_di"], ind_p["minus_di"])

        if regime == MarketRegime.TRENDING:
            effective_chop = 70.0
            stop_mult      = max(self.params.atr_stop_multiplier, 2.5)
            tp_mult        = 8.0   # far-away circuit breaker — trailing stop handles the exit
            use_trailing   = True
            size_factor    = 1.0
        elif regime == MarketRegime.VOLATILE:
            effective_chop = 70.0
            stop_mult      = max(self.params.atr_stop_multiplier, 2.0)
            tp_mult        = max(self.params.atr_tp_multiplier, 3.0)
            use_trailing   = False
            size_factor    = 0.5
        elif regime == MarketRegime.RANGING:
            effective_chop = self.params.chop_threshold
            stop_mult      = min(self.params.atr_stop_multiplier, 1.2)
            tp_mult        = min(self.params.atr_tp_multiplier, 2.0)
            use_trailing   = False
            size_factor    = 0.75
        else:  # NEUTRAL
            effective_chop = self.params.chop_threshold
            stop_mult      = self.params.atr_stop_multiplier
            tp_mult        = self.params.atr_tp_multiplier
            use_trailing   = False
            size_factor    = 1.0

        if chop > effective_chop:
            logger.info(
                f"[{symbol}] Market {regime.value} (CI={chop:.1f} > {effective_chop:.0f}) — no signal"
            )
            return None

        # ── Higher timeframe trend bias ───────────────────────────────────────
        # Relaxed: Supertrend alone is sufficient; EMA alignment adds score but isn't a hard gate
        htf_bias: SignalDirection
        if ind_c["st_direction"] == 1:
            htf_bias = SignalDirection.LONG
        elif ind_c["st_direction"] == -1:
            htf_bias = SignalDirection.SHORT
        else:
            htf_bias = SignalDirection.FLAT

        if htf_bias == SignalDirection.FLAT:
            logger.info(f"[{symbol}] Higher TF Supertrend unclear — skipping")
            return None

        # ── Funding rate bias ─────────────────────────────────────────────────
        # Positive funding → longs pay shorts → crowded long → short bias
        # Negative funding → shorts pay longs → crowded short → long bias
        funding_rate = 0.0
        funding_note = ""
        if self._funding:
            try:
                funding_rate = self._funding(symbol)
                if funding_rate > 0.0005:    # > 0.05% per 8h — strongly crowded long
                    funding_note = f"Funding {funding_rate*100:.3f}% (crowded longs → short bias)"
                    if htf_bias == SignalDirection.LONG:
                        logger.info(f"[{symbol}] High funding rate ({funding_rate:.4f}) conflicts with LONG — skipping")
                        return None
                elif funding_rate < -0.0005:  # < -0.05% — crowded short
                    funding_note = f"Funding {funding_rate*100:.3f}% (crowded shorts → long bias)"
                    if htf_bias == SignalDirection.SHORT:
                        logger.info(f"[{symbol}] Negative funding ({funding_rate:.4f}) conflicts with SHORT — skipping")
                        return None
            except Exception as e:
                logger.warning(f"[{symbol}] Could not fetch funding rate: {e}")

        # Calculate confidence score for the HTF direction using primary TF data
        score, reasons = _score_direction(ind_p, htf_bias, self.params)

        # HTF EMA alignment adds to confidence (was previously a hard gate)
        if htf_bias == SignalDirection.LONG and ind_c["ema_50"] > ind_c["ema_200"]:
            score = min(score + 7, 100.0)
            reasons.insert(0, f"HTF ({confirm_tf}) EMA50>EMA200 + Supertrend LONG")
        elif htf_bias == SignalDirection.SHORT and ind_c["ema_50"] < ind_c["ema_200"]:
            score = min(score + 7, 100.0)
            reasons.insert(0, f"HTF ({confirm_tf}) EMA50<EMA200 + Supertrend SHORT")
        else:
            reasons.insert(0, f"HTF ({confirm_tf}) Supertrend {htf_bias.value} (no EMA align)")

        if funding_note:
            reasons.append(funding_note)

        reasons.append(
            f"Regime: {regime.value} (CI={chop:.1f}, ADX={ind_p['adx']:.1f})"
            + (" → trailing exit" if use_trailing else "")
            + (f" → {size_factor:.0%} size" if size_factor < 1.0 else "")
        )

        if score < self.CONFIDENCE_THRESHOLD:
            logger.info(f"[{symbol}] Score {score:.1f} below threshold {self.CONFIDENCE_THRESHOLD} — no signal")
            return None

        price = ind_p["price"]
        atr   = ind_p["atr"]

        if htf_bias == SignalDirection.LONG:
            stop_loss   = price - stop_mult * atr
            take_profit = price + tp_mult * atr
        else:
            stop_loss   = price + stop_mult * atr
            take_profit = price - tp_mult * atr

        sig = Signal(
            direction   = htf_bias,
            confidence  = round(score, 1),
            timeframe   = primary_tf,
            symbol      = symbol,
            price       = price,
            atr         = atr,
            stop_loss   = round(stop_loss, 6),
            take_profit = round(take_profit, 6),
            indicators  = ind_p,
            reasons     = reasons,
            regime      = regime,
            trailing    = use_trailing,
            size_factor = size_factor,
        )

        logger.info(
            f"[{symbol}] SIGNAL {sig.direction.value} | "
            f"confidence={sig.confidence} | SL={sig.stop_loss} | TP={sig.take_profit}"
        )
        return sig

    def scan_symbols(self, symbols: List[str], primary_tf: str = "5m",
                     confirm_tf: str = "1h") -> List[Signal]:
        """Scan multiple symbols and return all valid signals."""
        results = []
        for sym in symbols:
            try:
                sig = self.analyse(sym, primary_tf, confirm_tf)
                if sig:
                    results.append(sig)
            except Exception as e:
                logger.error(f"[{sym}] Error during analysis: {e}")
        return results
