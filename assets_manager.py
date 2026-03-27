import json
import os
import logging

logger = logging.getLogger(__name__)

class AssetsManager:
    def __init__(self, config_path="/home/ubuntu/BotAcoes/assets.json", default_assets=None):
        self.config_path = config_path
        self.assets = self._load_assets(default_assets)

    def _load_assets(self, default_assets):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar ativos de {self.config_path}: {e}")
        
        # Se não existir ou falhar, usa os padrões e guarda
        assets = default_assets if default_assets is not None else []
        self._save_assets(assets)
        return assets

    def _save_assets(self, assets):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(assets, f, indent=4)
            self.assets = assets
            return True
        except Exception as e:
            logger.error(f"Erro ao guardar ativos em {self.config_path}: {e}")
            return False

    def add_asset(self, ticker):
        ticker = ticker.upper().strip()
        if ticker not in self.assets:
            new_assets = self.assets.copy()
            new_assets.append(ticker)
            return self._save_assets(new_assets)
        return False

    def remove_asset(self, ticker):
        ticker = ticker.upper().strip()
        if ticker in self.assets:
            new_assets = [a for a in self.assets if a != ticker]
            return self._save_assets(new_assets)
        return False

    def get_assets(self):
        return self.assets
