import logging
from pathlib import Path
import pandas as pd
import joblib

from src.ml.dataset_builder import build_features
from src.ml.train_rf import FEATURES

logger = logging.getLogger(__name__)

class MLPredictor:
    def __init__(self, model_path: str = "data/models/rf_latest.joblib"):
        self.enabled = False
        self.model = None
        
        mp = Path(model_path)
        if mp.exists():
            try:
                self.model = joblib.load(mp)
                self.enabled = True
                logger.info(f"Loaded ML Predictor perfectly from {model_path}")
            except Exception as e:
                logger.error(f"Failed to load ML model: {e}")
        else:
            logger.warning(f"No ML model found at {model_path}. Technical Analysis mode only.")
            
    def predict_up_probability(self, raw_df: pd.DataFrame) -> float:
        """Returns the probability (0.0 to 1.0) that the next N bars will jump."""
        if not self.enabled or self.model is None:
            return 0.5
            
        try:
            # We must compute all lag features exactly as during training
            df_feat = build_features(raw_df)
            if df_feat.empty:
                return 0.5
                
            # Extract just the very last known state to predict its direct future
            latest = df_feat.iloc[-1:][FEATURES]
            
            # predict_proba returns [[prob_0, prob_1]]
            probs = self.model.predict_proba(latest)
            return float(probs[0][1])
        except Exception as e:
            logger.error(f"Prediction failed dynamically: {e}")
            return 0.5
