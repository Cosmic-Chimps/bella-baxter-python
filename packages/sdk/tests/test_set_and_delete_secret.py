"""
#1500 — ``BaxterClient.set_secret`` / ``delete_secret`` (and their ``_async`` pairs).

The Ansible ``secret`` module called ``client.update_secret(...)`` and ``client.delete_secret(...)``. Neither
existed, so ``state: present`` and ``state: absent`` could not work. The SDK now offers the two calls, and the
module goes through them by name.

What is pinned here:

* the request lands on the right route (project slug, environment SLUG — an environment UUID is not
  addressable — provider slug or UUID, key) with the right body;
* project and environment fall back to the API key's own, and the key context is fetched only when needed;
* ``delete_secret`` answers ``False`` for a 404 (already gone), decided from the STATUS CODE the Kiota error
  carries, never from its text; any other failure raises;
* ``set_secret`` PUTs first (an upsert) and, when a scope-limited key gets 404 for a key it may not read yet,
  POSTs the create (``SetSecretCommand`` in the CLI does the same, #1476). A 404 from the create is real and
  raises; any other PUT error raises WITHOUT trying the create;
* everything after ``key`` (and ``value``) is keyword-only, so a positional mix-up like #1482's cannot happen.

The Kiota client is replaced by a recording stand-in that mirrors the builder chain the SDK uses. The
generated models are only needed as value holders: when ``generated/`` has not been produced (it is
gitignored), a minimal stand-in is registered so these tests run on a plain checkout.
"""

from __future__ import annotations

import asyncio
import importlib.abc
import importlib.machinery
import sys
import types

import pytest
from kiota_abstractions.api_error import APIError


# ── generated-model stand-ins (only when `generated/` is absent) ─────────────────────────────────────────


class _Holder:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _GeneratedModule(types.ModuleType):
    def __getattr__(self, name: str):
        if name.startswith("__"):
            raise AttributeError(name)
        cls = type(name, (_Holder,), {})
        setattr(self, name, cls)
        return cls


class _GeneratedFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    PREFIX = "bella_baxter.generated"

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.PREFIX or fullname.startswith(self.PREFIX + "."):
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _GeneratedModule(spec.name)
        module.__path__ = []  # type: ignore[attr-defined]
        return module

    def exec_module(self, module):
        return None


def _load_client_module():
    try:
        import bella_baxter.generated.models.update_secret_request  # noqa: F401
        import bella_baxter.generated.models.create_secret_request  # noqa: F401
        import bella_baxter.generated.bella_client  # noqa: F401
    except ImportError:
        for name in [n for n in sys.modules if n.startswith("bella_baxter.generated")]:
            del sys.modules[name]
        sys.meta_path.insert(0, _GeneratedFinder())
    import bella_baxter.client as client_module

    return client_module


client_module = _load_client_module()
BaxterClient = client_module.BaxterClient
BaxterClientOptions = client_module.BaxterClientOptions

API_KEY = "bax-0123456789abcdef-" + "ab" * 32
CTX = {"projectSlug": "key-project", "environmentSlug": "key-env"}
SECRET_VALUE = "s3cr3t-value-that-must-not-leak"


# ── the Kiota stand-in ───────────────────────────────────────────────────────────────────────────────────


class Recorder:
    """Records every terminal request (path, body) and answers from a queue of outcomes."""

    def __init__(self, outcomes=()):
        self.calls: list[tuple[str, object]] = []
        self.outcomes = list(outcomes)

    def send(self, path: str, body):
        self.calls.append((path, body))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _Node:
    TERMINALS = ("put", "post", "delete", "get")

    def __init__(self, recorder: Recorder, path: str = ""):
        self._recorder = recorder
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return _Node(self._recorder, f"{self._path}.{name}" if self._path else name)

    def __call__(self, *args):
        name = self._path.rsplit(".", 1)[-1]
        if name in self.TERMINALS:
            body = args[0] if args else None
            recorder, path = self._recorder, self._path

            async def terminal():
                return recorder.send(path, body)

            return terminal()
        rendered = ", ".join(repr(a) for a in args)
        return _Node(self._recorder, f"{self._path}({rendered})")


def make_client(*outcomes, key_context=CTX):
    client = BaxterClient.__new__(BaxterClient)
    client._options = BaxterClientOptions(baxter_url="https://baxter.example.com", api_key=API_KEY)
    client._key_context = key_context
    recorder = Recorder(outcomes)
    client._kiota = _Node(recorder)
    return client, recorder


def route(project, env, provider, key, verb):
    return (
        f"api.v1.projects.by_id({project!r}).environments.by_env_slug({env!r})"
        f".providers.by_provider_slug({provider!r}).secrets"
        + (f".by_key({key!r}).{verb}" if verb != "post" else ".post")
    )


def status(code: int) -> APIError:
    return APIError(message="problem", response_status_code=code)


# ── set_secret: the upsert ───────────────────────────────────────────────────────────────────────────────


def test_set_secret_puts_to_the_providers_secret_with_explicit_slugs():
    client, recorder = make_client()

    result = client.set_secret(
        "RDS_PASSWORD",
        SECRET_VALUE,
        provider="vault-main",
        project_slug="sandbox",
        env_slug="dev",
        description="rotated by Ansible",
    )

    assert result is None
    (path, body), = recorder.calls
    assert path == route("sandbox", "dev", "vault-main", "RDS_PASSWORD", "put")
    assert body.key == "RDS_PASSWORD"  # the route key wins server-side; the body still names it
    assert body.value == SECRET_VALUE
    assert body.description == "rotated by Ansible"
    # Tags go through PATCH .../metadata; the API refuses them on a PUT.
    assert getattr(body, "tags", None) is None


def test_set_secret_takes_project_and_environment_from_the_api_key_when_not_given():
    client, recorder = make_client()

    client.set_secret("K", "v", provider="vault-main")

    (path, _), = recorder.calls
    assert path == route("key-project", "key-env", "vault-main", "K", "put")


def test_set_secret_overrides_only_what_it_is_given():
    client, recorder = make_client()

    client.set_secret("K", "v", provider="p", env_slug="staging")

    (path, _), = recorder.calls
    assert path == route("key-project", "staging", "p", "K", "put")


def test_set_secret_accepts_a_provider_uuid():
    client, recorder = make_client()
    provider = "550e8400-e29b-41d4-a716-446655440001"

    client.set_secret("K", "v", provider=provider, project_slug="p", env_slug="e")

    (path, _), = recorder.calls
    assert path == route("p", "e", provider, "K", "put")


def test_set_secret_does_not_ask_the_server_who_the_key_is_when_both_slugs_are_given():
    client, recorder = make_client(key_context=None)
    client.get_key_context = lambda: pytest.fail("GET /keys/me was not needed")

    client.set_secret("K", "v", provider="p", project_slug="p1", env_slug="e1")

    assert len(recorder.calls) == 1


def test_set_secret_async_does_the_same():
    client, recorder = make_client()

    asyncio.run(client.set_secret_async("K", "v", provider="p", project_slug="p1", env_slug="e1"))

    (path, body), = recorder.calls
    assert path == route("p1", "e1", "p", "K", "put")
    assert body.value == "v"


def test_a_successful_put_does_not_create():
    client, recorder = make_client()

    client.set_secret("K", "v", provider="p")

    assert [p.rsplit(".", 1)[-1] for p, _ in recorder.calls] == ["put"]


# ── set_secret: the scope-limited create fallback ────────────────────────────────────────────────────────


def test_a_put_404_falls_back_to_creating_the_secret():
    # A scope-limited key may not change what it may not read, so the PUT on a key that does not exist yet
    # answers 404; POST is the path that stamps the key's scopes on what it creates.
    client, recorder = make_client(status(404))

    client.set_secret(
        "NEW_KEY", SECRET_VALUE, provider="vault-main", project_slug="sandbox", env_slug="dev", description="d"
    )

    (put_path, _), (post_path, post_body) = recorder.calls
    assert put_path == route("sandbox", "dev", "vault-main", "NEW_KEY", "put")
    assert post_path == route("sandbox", "dev", "vault-main", None, "post")
    assert post_body.key == "NEW_KEY"
    assert post_body.value == SECRET_VALUE
    assert post_body.description == "d"
    assert getattr(post_body, "tags", None) is None


def test_the_create_fallback_works_through_the_async_method_too():
    client, recorder = make_client(status(404))

    asyncio.run(client.set_secret_async("K", "v", provider="p", project_slug="a", env_slug="b"))

    assert [p.rsplit(".", 1)[-1] for p, _ in recorder.calls] == ["put", "post"]


def test_a_404_from_the_create_raises_and_does_not_loop():
    # The environment or the provider really is not there.
    client, recorder = make_client(status(404), status(404))

    with pytest.raises(APIError) as raised:
        client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")

    assert raised.value.response_status_code == 404
    assert [p.rsplit(".", 1)[-1] for p, _ in recorder.calls] == ["put", "post"]


@pytest.mark.parametrize("code", [400, 401, 403, 409, 500, 502])
def test_a_put_error_other_than_404_raises_without_trying_the_create(code):
    client, recorder = make_client(status(code))

    with pytest.raises(APIError) as raised:
        client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")

    assert raised.value.response_status_code == code
    assert [p.rsplit(".", 1)[-1] for p, _ in recorder.calls] == ["put"]


@pytest.mark.parametrize("code", [400, 403, 409, 500])
def test_a_create_error_after_a_put_404_raises(code):
    client, recorder = make_client(status(404), status(code))

    with pytest.raises(APIError) as raised:
        client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")

    assert raised.value.response_status_code == code


def test_a_404_is_recognised_by_status_code_not_by_message():
    # An error whose TEXT says "404 not found" but whose status is 500 must not be treated as absent;
    # an error with an unrelated message but status 404 must be.
    misleading = APIError(message="404 Not Found somewhere in the text", response_status_code=500)
    client, recorder = make_client(misleading)
    with pytest.raises(APIError):
        client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")
    assert len(recorder.calls) == 1

    client, recorder = make_client(APIError(message="no", response_status_code=404))
    client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")
    assert len(recorder.calls) == 2


def test_an_exception_without_a_status_code_is_never_a_404():
    client, recorder = make_client(RuntimeError("404 not found"))

    with pytest.raises(RuntimeError):
        client.set_secret("K", "v", provider="p", project_slug="a", env_slug="b")

    assert len(recorder.calls) == 1


# ── delete_secret ───────────────────────────────────────────────────────────────────────────────────────


def test_delete_secret_deletes_by_route_and_reports_true():
    client, recorder = make_client()

    deleted = client.delete_secret("OLD", provider="vault-main", project_slug="sandbox", env_slug="dev")

    assert deleted is True
    (path, body), = recorder.calls
    assert path == route("sandbox", "dev", "vault-main", "OLD", "delete")
    assert body is None


def test_delete_secret_takes_project_and_environment_from_the_api_key_when_not_given():
    client, recorder = make_client()

    client.delete_secret("OLD", provider="p")

    (path, _), = recorder.calls
    assert path == route("key-project", "key-env", "p", "OLD", "delete")


def test_delete_secret_reports_false_when_the_api_answers_404():
    client, recorder = make_client(status(404))

    deleted = client.delete_secret("GONE", provider="p", project_slug="a", env_slug="b")

    assert deleted is False
    assert len(recorder.calls) == 1


@pytest.mark.parametrize("code", [400, 401, 403, 409, 500, 502])
def test_delete_secret_raises_on_any_other_error(code):
    client, _ = make_client(status(code))

    with pytest.raises(APIError) as raised:
        client.delete_secret("K", provider="p", project_slug="a", env_slug="b")

    assert raised.value.response_status_code == code


def test_delete_secret_does_not_read_a_404_out_of_the_message():
    client, _ = make_client(APIError(message="404 Not Found", response_status_code=403))

    with pytest.raises(APIError):
        client.delete_secret("K", provider="p", project_slug="a", env_slug="b")


def test_delete_secret_async_does_the_same():
    client, recorder = make_client(status(404))

    deleted = asyncio.run(client.delete_secret_async("K", provider="p", project_slug="a", env_slug="b"))

    assert deleted is False


# ── the signature: nothing positional after key / value ─────────────────────────────────────────────────


def test_set_secret_refuses_a_positional_provider():
    client, recorder = make_client()

    with pytest.raises(TypeError):
        client.set_secret("K", "v", "vault-main")  # type: ignore[misc]

    assert recorder.calls == []


def test_set_secret_requires_the_provider():
    client, _ = make_client()

    with pytest.raises(TypeError):
        client.set_secret("K", "v")  # type: ignore[call-arg]


def test_delete_secret_refuses_a_positional_provider():
    client, recorder = make_client()

    with pytest.raises(TypeError):
        client.delete_secret("K", "vault-main")  # type: ignore[misc]

    assert recorder.calls == []


def test_the_slugs_cannot_be_passed_positionally_either():
    client, _ = make_client()

    with pytest.raises(TypeError):
        client.set_secret("K", "v", "vault", "project", "env")  # type: ignore[misc]
    with pytest.raises(TypeError):
        client.delete_secret("K", "vault", "project", "env")  # type: ignore[misc]


@pytest.mark.parametrize("provider", ["", "   ", None])
def test_an_empty_provider_is_refused_before_any_request(provider):
    client, recorder = make_client()

    with pytest.raises(ValueError):
        client.set_secret("K", "v", provider=provider)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        client.delete_secret("K", provider=provider)  # type: ignore[arg-type]

    assert recorder.calls == []
