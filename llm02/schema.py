from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = '1'


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass
class Case:
    source: str
    source_id: str
    category: str
    user_prompt: str
    protected_values: list[str] = field(default_factory=list)
    system_prompt: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    subcategory: str = ''
    attack_type: str = 'direct'
    difficulty: str = 'medium'
    expected: str = 'must_not_disclose'
    synthetic: bool = False
    metadata: dict = field(default_factory=dict)
    id: str = ''

    def __post_init__(self):
        if not isinstance(self.user_prompt, str) or not self.user_prompt.strip():
            raise ValueError('user_prompt must be non-empty text')
        if self.expected not in ('must_not_disclose', 'benign'):
            raise ValueError('invalid expected outcome')
        if any(not isinstance(v, str) or not v.strip() for v in self.protected_values):
            raise ValueError('protected values must be non-empty strings')
        self.protected_values = sorted(set(v.strip() for v in self.protected_values))
        if any(m.get('role') not in ('user', 'assistant', 'system') or
               not isinstance(m.get('content'), str) for m in self.messages):
            raise ValueError('invalid conversation messages')
        if any(not isinstance(v, str) or not v.strip() for v in self.followups):
            raise ValueError('invalid followup')
        if not self.id:
            self.id = 'LLM02-' + self.identity()[:24]

    def identity(self) -> str:
        data = asdict(self)
        for k in ('id', 'source', 'source_id'):
            data.pop(k)
        data['metadata'] = {k: v for k, v in data['metadata'].items()
                            if k not in ('provenance', 'source_url', 'source_file', 'row')}
        return digest(data)

    def to_dict(self) -> dict:
        return asdict(self)

    def initial_messages(self) -> list[dict[str, str]]:
        return ([{'role': 'system', 'content': self.system_prompt}] if self.system_prompt else []) + self.messages + [
            {'role': 'user', 'content': self.user_prompt}]
