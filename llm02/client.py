from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from .schema import digest
from .loop_transport import complete as loop_complete, LoopFailure


class RequestFailed(Exception):
    def __init__(self, message: str, status: str = 'ERROR'):
        super().__init__(message)
        self.status = status


def retry_after(value: str | None) -> float:
    if not value:
        return 0
    try:
        return max(0, float(value))
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            return max(0, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class Endpoint:
    def __init__(self, model: dict, execution: dict, generation: dict, store, transport=None):
        self.model, self.execution, self.generation, self.store = model, execution, generation, store
        self.http = httpx.AsyncClient(timeout=execution['timeout_seconds'], transport=transport)

    async def close(self):
        await self.http.aclose()

    async def request(self, messages: list, request_key: str, case=None, turn=0) -> dict:
        previous = self.store.request_events(request_key)
        done = [e for e in previous if e['kind'] == 'response']
        if done:
            return done[-1]['response']
        attempts = [e for e in previous if e['kind'] == 'request_start']
        if previous and previous[-1]['kind'] == 'request_error' and not previous[-1].get('retryable'):
            raise RequestFailed(previous[-1]['error'])
        if previous and previous[-1]['kind'] == 'request_start':
            if self.execution.get('uncertain_policy', 'record') == 'record':
                raise RequestFailed('request outcome uncertain after interruption; no automatic duplicate request', 'UNCERTAIN')
        if len(attempts) >= self.execution['max_retries'] + 1:
            raise RequestFailed('persisted retry budget exhausted')
        if previous and previous[-1]['kind'] == 'request_error':
            await asyncio.sleep(max(0, previous[-1].get('next_retry_at', 0) - time.time()))
        for attempt in range(len(attempts), self.execution['max_retries'] + 1):
            self.store.append('request_start', request_key=request_key, attempt=attempt,
                              messages=messages, model=self.model['model'])
            started = time.monotonic()
            retryable, delay = False, 0.0
            try:
                if self.model.get('mode') == 'mock':
                    response = self._mock(case, turn)
                elif self.model.get('mode') == 'loop':
                    response = await loop_complete(self.model, messages, self.generation, request_key,
                                                   self.execution['timeout_seconds'])
                else:
                    headers = {'Idempotency-Key': request_key, 'Content-Type': 'application/json'}
                    if self.model.get('api_key_env'):
                        headers['Authorization'] = 'Bearer ' + os.environ.get(self.model['api_key_env'], '')
                    r = await self.http.post(self.model['base_url'].rstrip('/') + '/chat/completions',
                                             json={'model': self.model['model'], 'messages': messages, **self.generation},
                                             headers=headers)
                    if r.status_code >= 400:
                        retryable = r.status_code in (408, 409, 429) or r.status_code >= 500
                        delay = retry_after(r.headers.get('Retry-After'))
                        raise RequestFailed(f'HTTP {r.status_code}')
                    try:
                        raw = r.json()
                        choice = raw['choices'][0]
                        message = choice['message']
                        content = message.get('content')
                        if not isinstance(content, str):
                            if isinstance(message.get('refusal'), str):
                                content = message['refusal']
                            else:
                                raise ValueError('missing text')
                        reasoning = message.get('reasoning_content') or message.get('reasoning') or ''
                        if not isinstance(reasoning, str):
                            reasoning = json.dumps(reasoning)
                        if not content.strip() and not reasoning.strip():
                            raise ValueError('empty response')
                        response = {'content': content, 'reasoning': reasoning, 'raw': raw,
                                    'usage': raw.get('usage'), 'finish_reason': choice.get('finish_reason')}
                    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                        # Preserve malformed payload separately, never put it in console output.
                        self.store.append('malformed_response', request_key=request_key,
                                          status_code=r.status_code, body=r.text)
                        retryable = True
                        raise RequestFailed('malformed endpoint response') from None
                response['latency_seconds'] = time.monotonic() - started
                self.store.append('response', request_key=request_key, response=response)
                return response
            except httpx.HTTPError as exc:
                retryable = True
                error = type(exc).__name__
            except LoopFailure as exc:
                retryable = exc.retryable
                delay = retry_after(exc.retry_after)
                error = str(exc)
                if exc.detail:
                    self.store.append('provider_error_detail', request_key=request_key, detail=exc.detail)
            except RequestFailed as exc:
                error = str(exc)
            delay = max(delay, min(self.execution['max_backoff_seconds'],
                                   self.execution['retry_backoff_seconds'] * (2 ** attempt) * random.uniform(0.8, 1.2)))
            self.store.append('request_error', request_key=request_key, attempt=attempt,
                              error=error, retryable=retryable, next_retry_at=time.time() + delay)
            if not retryable or attempt == self.execution['max_retries']:
                raise RequestFailed(error)
            await asyncio.sleep(delay)
        raise RequestFailed('retry budget exhausted')

    def _mock(self, case, turn):
        behavior = case.metadata.get('mock_behavior', 'safe') if case else 'safe'
        secret = case.protected_values[0] if case and case.protected_values else ''
        choices = {'safe': 'I cannot disclose private information.', 'full': secret,
                   'partial': secret[:max(8, len(secret) // 2)],
                   'normalized': ' '.join(secret),
                   'encoded': base64.b64encode(secret.encode()).decode(),
                   'reconstruct': secret[:len(secret) // 2] if turn == 0 else secret[len(secret) // 2:],
                   'benign': 'Recursion solves a problem by calling the same function on a smaller input.',
                   'refusal': 'I cannot assist with that request.'}
        content = choices.get(behavior, choices['safe'])
        return {'content': content, 'reasoning': '', 'raw': {'mock': True, 'content': content},
                'usage': None, 'finish_reason': 'stop'}
