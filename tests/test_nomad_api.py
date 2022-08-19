# type: ignore
"""Test the Nomad API."""

from nd._commands.utils.call_nomad_api import make_nomad_api_call


class MockResponse:
    """Mock response from the Nomad API."""

    @staticmethod
    def json():  # noqa: D102
        return {
            "Address": "10.138.0.5",
            "Attributes": {"os.name": "ubuntu"},
            "CreateIndex": 6,
            "Datacenter": "dc1",
            "ID": "f7476465-4d6e-c0de-26d0-e383c49be941",
            "ModifyIndex": 2526,
            "Name": "nomad-4",
            "NodeClass": "",
            "SchedulingEligibility": "eligible",
            "Status": "ready",
            "StatusDescription": "",
            "Version": "0.8.0-rc1",
        }


def test_nomad_api_call_valid(monkeypatch) -> None:
    """Test a valid response from the Nomad API."""

    def mock_get(*args, **kwargs):
        return MockResponse

    monkeypatch.setattr("requests.request", mock_get)

    response = make_nomad_api_call("http://fake.url", "get")
    assert response["Address"] == "10.138.0.5"
    assert response["Attributes"]["os.name"] == "ubuntu"
