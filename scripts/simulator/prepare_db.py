"""Recria o banco do zero e escolhe o modo do ML na política, antes de uma medição.

    python scripts/simulator/prepare_db.py --ml-mode shadow
    python scripts/simulator/prepare_db.py --ml-mode active

APAGA TUDO: derruba o schema `public` e roda o database/database.sql de
novo, como o `DbUtils.rollback()` dos testes. Não existe endpoint para o
modo do ML (o escopo deixa as APIs de configuração de fora), então ele é
trocado aqui, direto na política ativa. É preparo de ambiente: o
simulador em si só fala com a API por HTTP.
"""

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = "postgresql+psycopg2://bootcamp:bootcamp@localhost:5432/bootcamp"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ml-mode", choices=["shadow", "active"], default="shadow")
    args = parser.parse_args()

    engine = create_engine(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        # Pelo cursor do driver, sem parâmetros: assim um "%" num comentário
        # do database.sql não é lido como marcador de parâmetro.
        cursor = connection.connection.cursor()
        cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cursor.execute((ROOT / "database" / "database.sql").read_text())
        cursor.close()
        connection.execute(text("UPDATE policy_version SET ml_mode = :mode WHERE is_active"), {"mode": args.ml_mode})
    engine.dispose()

    print(f"Banco recriado, política ativa com ml_mode = {args.ml_mode}.")


if __name__ == "__main__":
    main()
