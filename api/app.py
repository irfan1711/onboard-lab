import os, json, subprocess, requests
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ["GH_REPO"]
TOKEN = os.environ["GH_TOKEN"]
GH = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"}
app = FastAPI(title="Tenant Provisioning API")

class Tenant(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9-]{3,30}$")
    display_name: str = Field(min_length=2, max_length=60)
    environment: Literal["dev", "staging", "prod"] = "dev"
    platforms: list[Literal["linux", "windows"]] = Field(default=["linux", "windows"], min_length=1)

@app.get("/", response_class=HTMLResponse)
def portal():
    return (ROOT / "ui/index.html").read_text()

@app.post("/tenants", status_code=202)
def create_tenant(t: Tenant):
    path = ROOT / "tenants" / f"{t.tenant_id}.yaml"
    if path.exists():
        raise HTTPException(409, f"tenant {t.tenant_id} already exists")
    tpl = (ROOT / "templates/tenant.yaml.tpl").read_text()
    path.write_text(tpl.format(**{**t.model_dump(), "platforms": json.dumps(t.platforms)}))
    subprocess.run(["git", "-C", str(ROOT), "pull", "--rebase", "-q"], check=True)
    subprocess.run(["git", "-C", str(ROOT), "add", str(path)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-qm", f"onboard tenant {t.tenant_id}"], check=True)
    subprocess.run(["git", "-C", str(ROOT), "push", "-q", "origin", "main"], check=True)
    r = requests.post(f"https://api.github.com/repos/{REPO}/dispatches", headers=GH,
        json={"event_type": "tenant-provisioned",
              "client_payload": {"tenant_id": t.tenant_id, "environment": t.environment}})
    if r.status_code != 204:
        raise HTTPException(502, f"dispatch failed: {r.text}")
    return {"status": "accepted", "tenant": t.tenant_id}

@app.get("/tenants/{tenant_id}/status")
def status(tenant_id: str):
    r = requests.get(f"https://api.github.com/repos/{REPO}/actions/workflows/tenant-release.yml/runs",
                     headers=GH, params={"per_page": 30})
    for run in r.json().get("workflow_runs", []):
        if run["display_title"] == f"onboard {tenant_id}":
            return {"tenant": tenant_id, "status": run["status"],
                    "conclusion": run["conclusion"], "url": run["html_url"]}
    return {"tenant": tenant_id, "status": "queued", "conclusion": None, "url": None}
