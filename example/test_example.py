import threading

import pytest
from stub.test_pb2 import EchoRequest
from stub.test_pb2 import Empty


@pytest.fixture(scope="function")
def grpc_add_to_server():
    from stub.test_pb2_grpc import add_EchoServiceServicer_to_server

    return add_EchoServiceServicer_to_server


@pytest.fixture(scope="function")
def grpc_servicer():
    from servicer import Servicer

    return Servicer()


@pytest.fixture(scope="function")
def grpc_stub_cls():
    from stub.test_pb2_grpc import EchoServiceStub

    return EchoServiceStub


def test_some(grpc_stub):
    with grpc_stub() as stub:
        request = EchoRequest()
        response = stub.handler(request)
        assert response.name == f"test-{request.name}"


def test_example(grpc_stub):
    with grpc_stub() as stub:
        request = EchoRequest()
        response = stub.error_handler(request)
        assert response.name == f"test-{request.name}"


grpc_max_workers = 2


def test_blocking(grpc_stub):
    with grpc_stub() as stub:
        stream = stub.blocking(Empty())

        # after this call the servicer blocks its thread
        def call_unblock():
            # with grpc_max_workers = 1 this call could not be executed
            stub.unblock(Empty())
            stub.unblock(Empty())

        t = threading.Thread(target=call_unblock)
        t.start()
        for resp in stream:
            pass
        t.join()
