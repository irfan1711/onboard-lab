import os, re, json, subprocess, requests
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
REPO = os.environ["GH_REPO"]            # e.g. irfan1711/onboard-lab
TOKEN = os.environ["GH_TOKEN"]
app = FastAPI(title="Tenant Provisioning API")

class Tenant(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9-]{3,30}$")
    display_name: str
    environment: str = Field(pattern=r"^(dev|staging|prod)$")
    platforms: list[str] = ["linux", "windows"]

@app.post("/tenants", status_code=202)
def create_tenant(t: Tenant):
    path = ROOT / "tenants" / f"{t.tenant_id}.yaml"
    tpl = (ROOT / "templates/tenant.yaml.tpl").read_text()
    path.write_text(tpl.format(**{**t.model_dump(), "platforms": json.dumps(t.platforms)}))
    # 1) config-as-code: commit + push (audit trail)
    subprocess.run(["git", "-C", str(ROOT), "add", str(path)], check=True)
    subprocess.run(["git", "-C", str(ROOT), "commit", "-m", f"onboard tenant {t.tenant_id}"], check=False)
    subprocess.run(["git", "-C", str(ROOT), "push", "origin", "main"], check=True)
    # 2) event -> pipeline (no manual run)
    r = requests.post(f"https://api.github.com/repos/{REPO}/dispatches",
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"},
        json={"event_type": "tenant-provisioned",
              "client_payload": {"tenant_id": t.tenant_id, "environment": t.environment}})
    if r.status_code != 204:
        raise HTTPException(502, f"dispatch failed: {r.text}")
    return {"status": "accepted", "tenant": t.tenant_id}
