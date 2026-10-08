from apps.coordinator.network.server import CoordinatorState
from packages.crypto.trustfl_crypto.keys import ClientIdentity
from packages.crypto.trustfl_crypto.signer import UpdateSigner


def test_coordinator_rejects_unsigned_and_tampered_updates():
    identity = ClientIdentity.generate("client-1")
    state = CoordinatorState(min_clients=1, num_rounds=1, require_signatures=True)

    assert state.register_client("client-1", {"public_key": identity.public_key_b64})
    signer = UpdateSigner(identity, "fed-1")
    signed = signer.sign(
        round_id=1,
        model_version="model-v1",
        parameters=[[1.0, 2.0]],
        num_examples=1,
        metrics={"loss": 0.1},
    )

    assert not state.submit_update(
        "client-1", 1, signed.parameters, 1, signed.metrics, None, None
    )
    assert state.submit_update(
        "client-1",
        1,
        signed.parameters,
        1,
        signed.metrics,
        signed.metadata.to_dict(),
        signed.signature_b64,
    )
