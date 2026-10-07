#!/usr/bin/env python3
"""Prepare, execute, resume and report bounded LLM10 assessments."""
import asyncio
import argparse
import json
import os
from pathlib import Path
import sys

# Avoid shadowing Hugging Face's top-level datasets package when run as a script.
if __package__ in (None, ''):
    sys.path = [p for p in sys.path if Path(p or '.').resolve() != Path(__file__).parent.resolve()]
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llm10.config import load_config, estimate_calls
from llm10.datasets import prepare
from llm10.tests import build_manifest
from llm10.files import digest, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.yaml')))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--validate-config', action='store_true')
    modes.add_argument('--prepare-only', action='store_true')
    modes.add_argument('--report-run', metavar='DIRECTORY')
    args = parser.parse_args()
    try:
        if args.report_run:
            from llm10.report import rebuild
            rebuild(args.report_run)
            return 0
        cfg = load_config(args.config)
        print(json.dumps(estimate_calls(cfg), indent=2))
        if args.validate_config:
            return 0
        # HF imports happen lazily in prepare; keep even its raw Hub cache local
        # to this process/configuration, without affecting the LLM02 process.
        cache_root = Path(cfg['paths']['data']) / 'huggingface'
        os.environ['HF_HOME'] = str(cache_root / 'home')
        os.environ['HF_HUB_CACHE'] = str(cache_root / 'hub')
        os.environ['HF_DATASETS_CACHE'] = str(cache_root / 'datasets')
        samples, coverage = prepare(cfg)
        manifest = build_manifest(cfg, samples)
        path = Path(cfg['paths']['data']) / 'manifests' / (digest(manifest)[:24] + '.json')
        write_json(path, manifest)
        if args.prepare_only:
            print(f'Prepared {len(samples)} prompts; no inference requests made.')
            print(f'Workload manifest: {path} ({len(manifest["calls"])} planned calls)')
            return 0
        from llm10.client import resolve
        from llm10.runner import execute
        return asyncio.run(execute(cfg,manifest,coverage,resolve(cfg['model'])))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
