from apps.coordinator.network.server import CoordinatorState


class _FlakyChain:
    def __init__(self, results):
        self.results = iter(results)
        self.finalize_calls = 0

    def finalize_round(self, *_args):
        self.finalize_calls += 1
        return next(self.results)

    def register_client(self, *_args):
        return True

    def record_aggregation(self, *_args):
        return True

    def submit_update(self, *_args):
        return True

    def create_round(self, *_args):
        return True

    def activate_round(self, *_args):
        return True


def test_failed_finalization_retries_without_reaggregating():
    chain = _FlakyChain([False, True])
    state = CoordinatorState(min_clients=1, num_rounds=2, blockchain_client=chain, require_signatures=False)
    assert state.register_client("client", {})
    assert state.submit_update("client", 1, [[1.0]], 1, {})
    assert state.current_round == 1
    assert len(state.round_history) == 1
    state.monitor_tick()
    assert state.current_round == 2
    assert len(state.round_history) == 1
    assert chain.finalize_calls == 2


def test_permanently_failed_finalization_does_not_mark_round_failed_or_duplicate_history():
    chain = _FlakyChain([False, False])
    state = CoordinatorState(min_clients=1, num_rounds=1, blockchain_client=chain, require_signatures=False)
    assert state.register_client("client", {})
    assert state.submit_update("client", 1, [[1.0]], 1, {})
    state.monitor_tick()
    assert state.current_round == 1
    assert len(state.round_history) == 1
    assert state.round_history[0].get("status") != "FAILED"
