from types import SimpleNamespace

import pytest

from agent.planner import InvalidPlan, Planner


class Tools:
    def all(self):
        return [SimpleNamespace(name='read_repo',prohibited=False)]

    def schema_text(self):
        return 'read_repo'


class Models:
    def json(self,*args,**kwargs):
        raise AssertionError('not used')


def planner():
    return Planner(Models(),Tools())


def test_intelligence_metadata_is_preserved_when_valid():
    plan = planner().validate({'goal':'x','steps':[{
        'id':'s1','tool':'read_repo','parameters':{},'depends_on':[],
        'agent_role':'research','routing_policy':'research',
        'required_model_capabilities':['chat'],'preferred_model_capabilities':['json'],
        'parallelizable':True,
    }]})
    step = plan['steps'][0]
    assert step['agent_role'] == 'research'
    assert step['routing_policy'] == 'research'
    assert step['parallelizable'] is True


def test_planner_rejects_unknown_routing_policy():
    with pytest.raises(InvalidPlan):
        planner().validate({'goal':'x','steps':[{'id':'s1','tool':'read_repo','parameters':{},'routing_policy':'use-secret-model'}]})


def test_planner_rejects_unknown_agent_role():
    with pytest.raises(InvalidPlan):
        planner().validate({'goal':'x','steps':[{'id':'s1','tool':'read_repo','parameters':{},'agent_role':'root-admin'}]})
