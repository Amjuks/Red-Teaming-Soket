#!/usr/bin/env python3
"""One-command dataset preparation, execution, resume, grading and reporting."""
import argparse
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path = [p for p in sys.path if Path(p or '.').resolve() != Path(__file__).parent.resolve()]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--prepare-only', action='store_true', help='download/cache/normalize without inference')
    modes.add_argument('--report-only', action='store_true', help='rebuild reports from persisted evidence')
    modes.add_argument('--report-run', metavar='DIRECTORY', help='rebuild a historical run without config, credentials or dataset access')
    args = parser.parse_args()
    from llm02.config import load_config
    from llm02.runner import main, report_saved
    try:
        if args.report_run:
            return report_saved(args.report_run)
        return main(load_config(args.config), args.prepare_only, args.report_only)
    except KeyboardInterrupt:
        print('Interrupted; restart the same command to resume.', file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'Assessment blocked: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(cli())
