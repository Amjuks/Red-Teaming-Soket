from llm10.metrics import assessment


def test_observations_do_not_claim_vulnerability():
    record=dict(attempt_id='a',test_family='context_growth',status='ERROR',
                http_status=500,latency=120,estimated_cost=None)
    events=[dict(kind='attempt_finished',record=record)]
    manifest={'calls':[dict(call_id='c',family='context_growth')]}
    result=assessment(events,manifest)
    assert all(not f['confirmed_vulnerability'] for f in result['findings'])
    failure=result['findings'][0]
    assert failure['evidence_attempt_ids']==['a']
    assert '120.00' in failure['observation']
    assert failure['recommended_action'] and failure['retest']
    assert result['controls'][0]['unfinished_calls']==1
    assert result['controls'][0]['disposition']=='INCOMPLETE / INCONCLUSIVE'


def test_requested_cap_and_reasoning_are_not_leaks():
    record=dict(attempt_id='b',test_family='baseline',status='SUCCESS',
                finish_reason='length',content='',reasoning='partial answer',estimated_cost=None)
    result=assessment([dict(kind='attempt_finished',record=record)],{'calls':[]})
    by_id={f['finding_id']:f for f in result['findings']}
    assert by_id['LLM10-output-cap']['status']=='REQUESTED CAP OBSERVED'
    assert 'not a data-leak' in by_id['LLM10-empty-final']['possible_impact']
    assert 'not proof of free' in by_id['LLM10-cost']['observation']
