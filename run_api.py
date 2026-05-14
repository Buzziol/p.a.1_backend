import sys
import os
from pathlib import Path

# Carregar variáveis do .env antes de qualquer import que leia os.getenv()
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # python-dotenv não instalado — ler manualmente
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.api.app import main

if __name__ == '__main__':
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║         SKIN CANCER CLASSIFICATION API v1.0.0                 ║
    ╚═══════════════════════════════════════════════════════════════╝

    Iniciando servidor...
    Documentação disponível em: http://localhost:5001/docs
    API Base URL:   http://localhost:5001/api/v1

    """)

    main()

