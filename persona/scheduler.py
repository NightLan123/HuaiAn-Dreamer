"""Runtime-owned local task polling; independent of incoming QQ traffic."""
import copy
import threading
from .common import now


class Scheduler:
    def __init__(self, runtime):
        self.runtime = runtime
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.records = {}
        self.thread = threading.Thread(target=self.loop, daemon=True, name='huaian-scheduler')

    def start(self):
        if not self.runtime.preview and not self.thread.is_alive() and not self.stop.is_set():
            self.thread.start()

    def status(self, owner):
        with self.lock:
            return {'running': self.thread.is_alive() and not self.stop.is_set(), 'interval_seconds': 1,
                    'tasks': copy.deepcopy([r for (pid, _), r in self.records.items() if pid == owner]),
                    'model_calls_on_tick': False, 'reflection': self.runtime.contexts[owner][2].motive_generation.status(),
                    'affect_sampling': self.runtime.contexts[owner][2].affect_sampling.status()}

    def loop(self):
        while not self.stop.is_set():
            app = self.runtime
            if app.job_lock.acquire(blocking=False):
                try:
                    if app.reloading: return
                    if not any(j['status'] in ('queued', 'running') for j in app.jobs.values()):
                        for pid, (_, _, engine, bridge) in list(app.contexts.items()):
                            if self.stop.is_set(): break
                            if bridge.stop.is_set() or not bridge.lifecycle.acquire(blocking=False): continue
                            try:
                                if bridge.busy: continue
                                if not engine.lock.acquire(blocking=False):continue
                                engine.lock.release()
                                tasks = [('resume_wait', bridge.turn_taking.wake_paused),
                                         ('delivery_recovery', engine.recover_delivered),
                                         ('consolidation', engine.consolidation.poll),
                                         ('learning', engine.learning.poll),
                                         ('memory', engine.memory_lifecycle.poll),
                                         ('social', engine.social.poll),
                                         ('memory_reflection', engine.motive_generation.poll),
                                         ('affect_sampling', engine.affect_sampling.poll)]
                                for name, fn in tasks:
                                    if self.stop.is_set(): break
                                    row = {'task_id': name, 'persona_id': pid, 'last_run': now(),
                                           'due_at': now()+1, 'status': 'polling'}
                                    try:
                                        if not engine.lock.acquire(blocking=False):
                                            row.update(status='busy',last_result='conversation_or_worker_busy')
                                        else:
                                            # Polls inspect local policy or spawn workers; model
                                            # execution stays in those existing worker methods.
                                            try:fn();row.update(status='checked',last_result='polled_existing_policy')
                                            finally:engine.lock.release()
                                    except Exception as exc:
                                        row.update(status='failed', last_result=type(exc).__name__)
                                    with self.lock: self.records[pid, name] = row
                            finally: bridge.lifecycle.release()
                finally: app.job_lock.release()
            self.stop.wait(1)

    def close(self):
        self.stop.set()
        if self.thread.is_alive(): self.thread.join()
