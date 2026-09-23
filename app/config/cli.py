from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from app.config.reference import ConfigurationError, load_reference_configuration
from app.config.settings import Settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate or synchronize reference data")
    parser.add_argument("command", choices=("validate", "sync"))
    parser.add_argument("--config", dest="config_path")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    try:
        configuration = load_reference_configuration(args.config_path or settings.reference_config_path)
        if args.command == "validate":
            print(json.dumps({"status": "valid", "checksum": configuration.checksum}))
            return 0

        from app.application.reference import ReferenceDataService
        from app.database.session import create_database_engine, create_session_factory, session_scope
        from app.repositories.reference import SqlAlchemyReferenceDataRepository

        engine = create_database_engine(settings)
        factory = create_session_factory(engine)
        with session_scope(factory) as session:
            result = ReferenceDataService(SqlAlchemyReferenceDataRepository(session)).sync(configuration)
        print(json.dumps({"status": "synchronized", **result.__dict__}))
        return 0
    except ConfigurationError as exc:
        parser.exit(2, f"configuration error: {exc}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
