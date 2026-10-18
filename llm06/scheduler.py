"""Bounded case concurrency with one serialized journal and isolated tool states."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from runner import execute


def run_tests(journal,tests,config,client,judge_client,stop_event,on_progress,recover=False,execute_fn=execute):
    outcomes={e['test_id']:e for e in journal.snapshot() if e['kind']=='test_result'}
    candidates=[t for t in tests if t['test_id'] not in outcomes or (recover and outcomes[t['test_id']]['status']!='completed')]
    if len({t['test_id'] for t in candidates})!=len(candidates):raise ValueError('Duplicate tests cannot run concurrently')
    iterator=iter(candidates);active={};finished=0
    def worker(test):
        tid=test['test_id'];journal.append('worker_started',test_id=tid)
        try:execute_fn(journal,tid,test['scenario'],config,client,judge_client,recover=recover,stop_event=stop_event)
        finally:journal.append('worker_finished',test_id=tid)
    with ThreadPoolExecutor(max_workers=config['concurrency'],thread_name_prefix='llm06') as pool:
        def submit():
            while not stop_event.is_set() and len(active)<config['concurrency']:
                test=next(iterator,None)
                if test is None:break
                active[pool.submit(worker,test)]=test
        try:
            submit()
            while active:
                ready,_=wait(active,timeout=5,return_when=FIRST_COMPLETED)
                for future in ready:
                    test=active.pop(future);future.result();finished+=1
                on_progress(finished,len(candidates),[t['test_id'] for t in active.values()])
                submit()
        except BaseException:
            stop_event.set()
            raise
    return finished
