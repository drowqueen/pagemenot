"""Integration tests for FastAPI webhook endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from pagemenot.main import app

AZURE_VM_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertId": "/subscriptions/sub123/providers/Microsoft.AlertsManagement/alerts/abc",
            "alertRule": "VM CPU High",
            "severity": "Sev1",
            "monitorCondition": "Fired",
            "alertTargetIDs": [
                "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.compute/virtualmachines/my-vm"
            ],
            "configurationItems": ["my-vm"],
            "firedDateTime": "2026-03-11T10:00:00Z",
            "description": "CPU > 90% for 5 minutes",
        },
        "alertContext": {},
    },
}

AZURE_RESOLVED_ALERT = {
    "schemaId": "azureMonitorCommonAlertSchema",
    "data": {
        "essentials": {
            "alertRule": "VM CPU High",
            "severity": "Sev1",
            "monitorCondition": "Resolved",
            "alertTargetIDs": [
                "/subscriptions/sub123/resourcegroups/my-rg/providers/microsoft.compute/virtualmachines/my-vm"
            ],
            "configurationItems": ["my-vm"],
            "description": "",
        },
        "alertContext": {},
    },
}


@pytest.mark.asyncio
async def test_azure_fired():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhooks/azure", json=AZURE_VM_ALERT)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_azure_resolved():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhooks/azure", json=AZURE_RESOLVED_ALERT)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "skipped"
    assert data["reason"] == "azure alert resolved"
