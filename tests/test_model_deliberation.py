from types import SimpleNamespace

from models.contracts import ModelRequest, ModelResponse
from models.deliberation import DeliberationEngine


class Provider:
    def __init__(self,pid):
        self.id=pid; self.model=f'{pid}-model'


class Router:
    def __init__(self,enabled=True):
        self.settings=SimpleNamespace(multi_model_deliberation_enabled=enabled,model_max_parallel_calls=3)
        self.owner_privacy='external_allowed'; self.disabled=set(); self.primary='a'
        self.providers={pid:Provider(pid) for pid in ('a','b','c')}
        self.request_calls=0
    def eligible_providers(self,capability,sensitivity):
        return tuple(self.providers.values())
    def _chat_call(self,provider,messages,temperature):
        return f'{provider.id}: independent answer'
    def _run(self,capability,call,*,sensitivity,conversation_id,task_id,hybrid_request,model_request):
        provider=self.providers[hybrid_request.allowed_providers[0]]
        return call(provider)
    def request(self,request):
        self.request_calls+=1
        return ModelResponse(request.request_id,'a','a-model',content='synthesized')


def test_deliberation_runs_distinct_providers_then_synthesizes():
    router=Router(True)
    result=DeliberationEngine(router,max_models=3).run(ModelRequest(prompt='hard problem',routing_policy='critical'),mode='synthesize')
    assert {answer.provider_id for answer in result.answers} == {'a','b','c'}
    assert result.final.content == 'synthesized'
    assert router.request_calls == 1


def test_deliberation_feature_flag_falls_back_to_single_request():
    router=Router(False)
    result=DeliberationEngine(router).run(ModelRequest(prompt='normal'),mode='judge')
    assert result.mode == 'single'
    assert result.answers == ()
    assert result.final.content == 'synthesized'
