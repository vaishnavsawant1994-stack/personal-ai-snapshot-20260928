from activities.projection import ActivitiesProjection
from core.events import EventBus
from future_intelligence.work_orchestration.event_normalization import WorkEventNormalizer
from memory.store import MemoryStore


def test_normalized_work_event_appears_in_existing_activities_with_exact_action(tmp_path):
    store=MemoryStore(tmp_path/'memory.sqlite3'); events=EventBus()
    normalizer=WorkEventNormalizer(events,audit=store.audit)
    events.emit('p10.task_dispatched',goal_id='g1',plan_id='p1',task_id='t1',work_order_id='wo1',operation_id='op1',state='WAITING_APPROVAL',authorization='Bearer never-persist',raw_prompt='never-persist')

    rows=ActivitiesProjection(store).list(category='work')
    assert len(rows)==1
    row=rows[0]
    assert row['kind']=='work'
    assert row['label']=='Work'
    assert row['action']=='work.order.waiting_approval'
    assert row['status']=='needs_approval'
    assert row['details']['goal_id']=='g1'
    assert row['details']['plan_id']=='p1'
    assert row['details']['task_id']=='t1'
    assert row['details']['work_order_id']=='wo1'
    serialized=repr(row).lower()
    assert 'never-persist' not in serialized
    assert 'authorization' not in serialized
    assert 'raw_prompt' not in serialized
    normalizer.close()
