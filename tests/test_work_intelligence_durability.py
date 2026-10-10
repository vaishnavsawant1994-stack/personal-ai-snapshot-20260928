from continuity.model_handoff import build_handoff
from future_intelligence.work_orchestration import (
    DurableWorkStore,
    GoalSpec,
    ReadinessStatus,
    WorkDispatcher,
    WorkOrder,
    WorkOrderStatus,
    WorkPlan,
    WorkPlanStatus,
)


def _store_with_plan():
    store = DurableWorkStore()
    goal = GoalSpec(id='g1',title='Goal',objective='Build safely',desired_outcome='Verified result')
    store.upsert_goal(goal)
    a = WorkOrder(id='a',plan_id='p1',title='A',objective='Research',worker_type='research',status=WorkOrderStatus.QUEUED)
    b = WorkOrder(id='b',plan_id='p1',title='B',objective='Code',worker_type='coding',status=WorkOrderStatus.QUEUED)
    c = WorkOrder(id='c',plan_id='p1',title='C',objective='Review',worker_type='reviewer',status=WorkOrderStatus.QUEUED,dependencies=('a','b'))
    plan = WorkPlan(id='p1',goal_id='g1',version=1,summary='Plan',work_orders=(a,b,c),readiness=ReadinessStatus.READY,status=WorkPlanStatus.READY)
    store.save_plan(plan)
    return store


def test_intelligence_assignment_round_trip():
    store = _store_with_plan()
    saved = store.save_intelligence_assignment(
        'a',worker_id='research',routing_policy='research',required_capabilities=('chat',),
        preferred_capabilities=('json',),parallelizable=True,deliberation_mode='single',metadata={'x':1},
    )
    loaded = store.get_intelligence_assignment('a')
    assert loaded['routing_policy'] == 'research'
    assert loaded['parallelizable'] is True
    assert loaded['metadata'] == {'x':1}
    assert loaded['model_is_authority'] is False
    store.close()


def test_model_handoff_public_projection_excludes_sensitive_context():
    store = _store_with_plan()
    handoff = build_handoff(
        execution_id='e1',agent_id='research',task_id='a',goal='Research',current_plan={'id':'p1'},current_task={'id':'a'},
        important_context='private secret context',project_instructions='private instructions',relevant_memory=('secret memory',),
        tool_results={'private-tool': {'secret':'value'}},previous_provider='p1',previous_model='m1',next_provider='p2',next_model='m2',handoff_reason='rate_limit',
    )
    store.record_model_handoff('a',handoff)
    rows = store.list_model_handoffs('a')
    assert len(rows) == 1
    assert rows[0]['important_context'] == ''
    assert rows[0]['project_instructions'] == ''
    assert rows[0]['relevant_memory'] == []
    assert rows[0]['tool_results'] == ['private-tool']
    assert rows[0]['previous_provider'] == 'p1'
    assert rows[0]['next_provider'] == 'p2'
    store.close()


def test_batch_dispatch_claims_only_independent_ready_work():
    store = _store_with_plan()
    dispatcher = WorkDispatcher(store)
    claims = dispatcher.claim_ready_batch(worker_id='runtime',runtime_epoch=1,max_claims=4,lease_seconds=60)
    assert {claim.attempt.work_order_id for claim in claims} == {'a','b'}
    assert store.get_order('c').status == WorkOrderStatus.QUEUED
    # A second dispatcher cannot double-claim leased work and C is still blocked.
    assert dispatcher.claim_ready_batch(worker_id='other',runtime_epoch=1,max_claims=4) == ()
    store.close()
