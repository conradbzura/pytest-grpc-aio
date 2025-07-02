from __future__ import annotations

import socket
from concurrent import futures
from contextlib import asynccontextmanager
from contextlib import contextmanager
from typing import Any
from typing import AsyncContextManager
from typing import AsyncGenerator
from typing import Callable
from typing import ContextManager
from typing import Generator
from typing import List
from typing import Protocol
from typing import Type
from typing import TypeVar

import grpc
import grpc.aio
import pytest
from grpc._cython.cygrpc import CompositeChannelCredentials
from grpc._cython.cygrpc import _Metadatum


class GrpcStub(Protocol):
    def __init__(
        self, channel: grpc.Channel | grpc.aio.Channel | FakeChannel | FakeAioChannel
    ): ...


T_GrpcStub = TypeVar("T_GrpcStub", bound=GrpcStub)
T_GrpcServicer = TypeVar("T_GrpcServicer")


def pytest_addoption(parser):
    parser.addoption("--grpc-fake-server", action="store_true", dest="grpc-fake")
    parser.addoption("--grpc-max-workers", type=int, dest="grpc-max-workers", default=1)


class FakeServer(object):
    def __init__(self, pool):
        self.handlers = {}
        self.pool = pool

    def add_generic_rpc_handlers(self, generic_rpc_handlers):
        from grpc._server import _validate_generic_rpc_handlers

        _validate_generic_rpc_handlers(generic_rpc_handlers)

        self.handlers.update(generic_rpc_handlers[0]._method_handlers)

    def start(self):
        pass

    def stop(self, grace=None):
        pass

    def add_secure_port(self, target, server_credentials):
        pass

    def add_insecure_port(self, target):
        pass


class FakeRpcError(RuntimeError, grpc.RpcError):
    def __init__(self, code, details):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


class FakeContext(object):
    def __init__(self):
        self._invocation_metadata = []

    def abort(self, code, details):
        raise FakeRpcError(code, details)

    def invocation_metadata(self):
        return self._invocation_metadata


class FakeChannel:
    def __init__(self, fake_server, credentials):
        self.server = fake_server
        self._credentials = credentials

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def fake_method(self, method_name, uri, *args, **kwargs):
        handler = self.server.handlers[uri]
        real_method = getattr(handler, method_name)

        def fake_handler(request):
            context = FakeContext()

            def metadata_callbak(metadata, error):
                context._invocation_metadata.extend(
                    (_Metadatum(k, v) for k, v in metadata)
                )

            if self._credentials and isinstance(
                self._credentials._credentials, CompositeChannelCredentials
            ):
                for call_cred in self._credentials._credentials._call_credentialses:
                    call_cred._metadata_plugin._metadata_plugin(
                        context, metadata_callbak
                    )
            future = self.server.pool.submit(real_method, request, context)
            return future.result()

        return fake_handler

    def unary_unary(self, *args, **kwargs):
        return self.fake_method("unary_unary", *args, **kwargs)

    def unary_stream(self, *args, **kwargs):
        return self.fake_method("unary_stream", *args, **kwargs)

    def stream_unary(self, *args, **kwargs):
        return self.fake_method("stream_unary", *args, **kwargs)

    def stream_stream(self, *args, **kwargs):
        return self.fake_method("stream_stream", *args, **kwargs)


@pytest.fixture(scope="function")
def grpc_addr() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("localhost", 0))
    return f"localhost:{sock.getsockname()[1]}"


@pytest.fixture(scope="function")
def grpc_interceptors() -> List[grpc.aio.ServerInterceptor] | None:
    return


@pytest.fixture(scope="function")
def grpc_servicer() -> object:
    raise NotImplementedError


@pytest.fixture(scope="function")
def grpc_server(
    request: pytest.FixtureRequest,
    grpc_addr: str,
    grpc_add_to_server: Callable[
        [T_GrpcServicer, grpc.Server | FakeServer],
    ],
    grpc_servicer: T_GrpcServicer,
    grpc_interceptors: List[grpc.ServerInterceptor] | None,
):
    @contextmanager
    def _grpc_server():
        max_workers = request.config.getoption("grpc-max-workers")
        try:
            max_workers = max(request.module.grpc_max_workers, max_workers)
        except AttributeError:
            pass
        pool = futures.ThreadPoolExecutor(max_workers=max_workers)
        if request.config.getoption("grpc-fake"):
            server = FakeServer(pool)
        else:
            server = grpc.server(pool, interceptors=grpc_interceptors)
        grpc_add_to_server(grpc_servicer, server)
        server.add_insecure_port(grpc_addr)
        server.start()
        yield server
        server.stop(grace=None)
        pool.shutdown(wait=False)

    return _grpc_server


@pytest.fixture(scope="function")
def grpc_channel(
    request: pytest.FixtureRequest,
    grpc_addr: str,
    grpc_server: Callable[[], ContextManager[grpc.Server | FakeServer]],
):
    @contextmanager
    def _grpc_channel(
        credentials: grpc.ChannelCredentials | None = None, options=None
    ) -> Generator[grpc.Channel | FakeChannel]:
        with grpc_server() as server:
            if request.config.getoption("grpc-fake"):
                yield FakeChannel(server, credentials)
            elif credentials is not None:
                yield grpc.secure_channel(grpc_addr, credentials, options)
            else:
                yield grpc.insecure_channel(grpc_addr, options)

    return _grpc_channel


@pytest.fixture(scope="function")
def grpc_stub(
    grpc_stub_cls: Type[T_GrpcStub],
    grpc_channel: Callable[
        [grpc.ChannelCredentials | None, Any], ContextManager[grpc.Channel | FakeChannel]
    ],
) -> Callable[[grpc.ChannelCredentials | None, Any], ContextManager[T_GrpcStub]]:
    @contextmanager
    def _grpc_stub(
        credentials: grpc.ChannelCredentials | None = None, options=None
    ) -> Generator[T_GrpcStub]:
        with grpc_channel(credentials, options) as channel:
            yield grpc_stub_cls(channel)

    return _grpc_stub


class FakeAioServer(object):
    def __init__(self, pool):
        self.handlers = {}
        self.pool = pool

    def add_generic_rpc_handlers(self, generic_rpc_handlers):
        from grpc._server import _validate_generic_rpc_handlers

        _validate_generic_rpc_handlers(generic_rpc_handlers)

        self.handlers.update(generic_rpc_handlers[0]._method_handlers)

    async def start(self):
        pass

    async def stop(self, grace=None):
        pass

    def add_secure_port(self, target, server_credentials):
        pass

    def add_insecure_port(self, target):
        pass


class FakeAioChannel:
    def __init__(self, fake_server, credentials):
        self.server = fake_server
        self._credentials = credentials

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def fake_method(self, method_name, uri, *args, **kwargs):
        handler = self.server.handlers[uri]
        real_method = getattr(handler, method_name)

        def fake_handler(request):
            context = FakeContext()

            def metadata_callbak(metadata, error):
                context._invocation_metadata.extend(
                    (_Metadatum(k, v) for k, v in metadata)
                )

            if self._credentials and isinstance(
                self._credentials._credentials, CompositeChannelCredentials
            ):
                for call_cred in self._credentials._credentials._call_credentialses:
                    call_cred._metadata_plugin._metadata_plugin(
                        context, metadata_callbak
                    )
            future = self.server.pool.submit(real_method, request, context)
            return future.result()

        return fake_handler

    def unary_unary(self, *args, **kwargs):
        return self.fake_method("unary_unary", *args, **kwargs)

    def unary_stream(self, *args, **kwargs):
        return self.fake_method("unary_stream", *args, **kwargs)

    def stream_unary(self, *args, **kwargs):
        return self.fake_method("stream_unary", *args, **kwargs)

    def stream_stream(self, *args, **kwargs):
        return self.fake_method("stream_stream", *args, **kwargs)


@pytest.fixture(scope="function")
def grpc_aio_server(
    request: pytest.FixtureRequest,
    grpc_addr: str,
    grpc_add_to_server: Callable[
        [T_GrpcServicer, grpc.Server | grpc.aio.Server | FakeServer | FakeAioServer],
        None,
    ],
    grpc_servicer: T_GrpcServicer,
    grpc_interceptors: List[grpc.aio.ServerInterceptor],
) -> Callable[[], AsyncContextManager[grpc.aio.Server | FakeAioServer]]:
    @asynccontextmanager
    async def _grpc_aio_server() -> AsyncGenerator[grpc.aio.Server | FakeAioServer]:
        max_workers = request.config.getoption("grpc-max-workers")
        try:
            max_workers = max(request.module.grpc_max_workers, max_workers)
        except AttributeError:
            pass
        pool = futures.ThreadPoolExecutor(max_workers=max_workers)
        if request.config.getoption("grpc-fake"):
            server = FakeAioServer(pool)
        else:
            server = grpc.aio.server(pool, interceptors=grpc_interceptors)
        grpc_add_to_server(grpc_servicer, server)
        server.add_insecure_port(grpc_addr)
        await server.start()
        yield server
        await server.stop(grace=None)
        pool.shutdown(wait=False)

    return _grpc_aio_server


@pytest.fixture(scope="function")
def grpc_aio_channel(
    request: pytest.FixtureRequest,
    grpc_addr: str,
    grpc_aio_server: Callable[[], AsyncContextManager[grpc.aio.Server]],
) -> Callable[[], AsyncContextManager[grpc.aio.Channel | FakeAioChannel]]:
    @asynccontextmanager
    async def _grpc_aio_channel(
        credentials: grpc.ChannelCredentials | None = None, options=None
    ) -> AsyncGenerator[grpc.aio.Channel | FakeAioChannel]:
        async with grpc_aio_server() as server:
            if request.config.getoption("grpc-fake"):
                yield FakeAioChannel(server, credentials)
            elif credentials is not None:
                yield grpc.aio.secure_channel(grpc_addr, credentials, options)
            else:
                yield grpc.aio.insecure_channel(grpc_addr, options)

    return _grpc_aio_channel


@pytest.fixture(scope="function")
def grpc_aio_stub(
    grpc_stub_cls: Type[T_GrpcStub],
    grpc_aio_channel: Callable[
        [grpc.ChannelCredentials | None, Any], AsyncContextManager[grpc.aio.Channel]
    ],
) -> Callable[[], AsyncContextManager[T_GrpcStub]]:
    @asynccontextmanager
    async def _grpc_aio_stub(
        credentials: grpc.ChannelCredentials | None = None, options=None
    ) -> AsyncGenerator[T_GrpcStub]:
        async with grpc_aio_channel(credentials, options) as channel:
            yield grpc_stub_cls(channel)

    return _grpc_aio_stub
